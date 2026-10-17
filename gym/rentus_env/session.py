"""One rollout = one RolloutSession: its own World, its own counterparts, its own trace.

The session wraps the sandbox `call()` so every tool call is recorded with what the scorer
needs (args, outcome, and whether each renter's gate was complete at that moment), and so
scripted counterparts answer when the operator writes to them.
"""
from __future__ import annotations

import copy
import json
from typing import Any

from .backend import Backend, snapshot, state
from .counterparts import Counterpart

GATE_ITEMS = ("lease", "move_in", "phone", "reason", "occupants")
GOOD_STATUS = {"answered", "exception"}


def item_done(v: Any) -> bool:
    if isinstance(v, dict):
        if "status" in v:
            return v.get("status") in GOOD_STATUS
        return any(v.get(k) not in (None, "", False) for k in ("value", "date"))
    return v not in (None, "", False)


def gate_complete(row: dict) -> bool:
    g = (row or {}).get("gate") or {}
    return all(item_done(g.get(k)) for k in GATE_ITEMS)


def renter_for_thread(st: dict, thread_id: str) -> dict | None:
    for r in st.get("register", []) or []:
        if thread_id in (r.get("thread_ids") or []) or r.get("thread_id") == thread_id:
            return r
    return None


class RolloutSession:
    def __init__(self, task: dict, backend: Backend | None = None, surface_replies: bool = True,
                 max_tool_calls: int | None = None):
        self.task = task
        self.backend = backend or Backend()
        self.surface_replies = surface_replies
        self.max_tool_calls = max_tool_calls or 4 * int(task.get("max_turns", 30))
        self.trace: list[dict] = []
        self.transcript: list[dict] = []  # renter-side view: {thread_id, from, text}
        self.final_text: str = ""
        patch = copy.deepcopy(task.get("initial_state") or {})
        if task.get("faults"):
            patch["faults"] = copy.deepcopy(task["faults"])
        self.world = self.backend.new_world(patch)
        self.counterparts = {c.thread_id: c for c in (Counterpart(s) for s in task.get("counterparts", []))}
        self._seed_threads()

    # ---------------------------------------------------------------------------------- setup
    def _seed_threads(self):
        ts = self.backend.coll(self.world, "threads")
        channels = self.backend.coll(self.world, "channels") if not isinstance(self.world, dict) \
            else self.world.get("channels") or {}
        for tid, cp in self.counterparts.items():
            msgs = [self._msg("renter", text) for text in cp.opening()]
            existing = next((t for t in ts if t.get("thread_id") == tid), None)
            if existing:
                existing.setdefault("messages", []).extend(msgs)
                continue
            t = {"thread_id": tid, "channel": cp.channel, "renter_name": cp.name, "language": cp.language,
                 "messages": msgs}
            if cp.room_id:
                t["room_id"] = cp.room_id
            if cp.listing_id:
                t["listing_id"] = cp.listing_id
            ts.append(t)
            ch = channels.get(cp.channel)
            if isinstance(ch, dict) and isinstance(ch.get("threads"), list) and tid not in ch["threads"]:
                ch["threads"].append(tid)
            for m in msgs:
                self.transcript.append({"thread_id": tid, "from": "renter", "text": m["text"]})

    def _msg(self, who: str, text: str) -> dict:
        self._seq = getattr(self, "_seq", 0) + 1
        return {"id": f"gym-m{self._seq:03d}", "from": who, "text": text, "attachments": [],
                "ts": self.backend.now(self.world)}

    # ----------------------------------------------------------------------------------- tools
    @property
    def tools(self) -> list[dict]:
        return self.backend.TOOLS

    def gate_status(self) -> dict[str, bool]:
        reg = {"register": self.backend.coll(self.world, "register")}
        out = {}
        for tid in self.counterparts:
            r = renter_for_thread(reg, tid)
            out[tid] = bool(r) and self.backend.gate_complete(self.world, r)
        return out

    def call(self, name: str, args: Any, **call_kw) -> dict:
        if not isinstance(args, dict):
            try:
                args = json.loads(args) if isinstance(args, str) else {}
            except json.JSONDecodeError:
                args = None
        entry = {"i": len(self.trace), "tool": name, "args": args, "gate_before": self.gate_status()}
        if args is None:
            env = {"ok": False, "error": {"code": "INVALID_ARGS", "message": "arguments are not valid JSON",
                                          "retryable": False}}
        elif len(self.trace) >= self.max_tool_calls:
            env = {"ok": False, "error": {"code": "POLICY_BLOCKED", "message": "tool-call budget for this task is spent",
                                          "retryable": False, "hint": "stop and summarize"}}
        else:
            env = self.backend.call(self.world, name, args, **(call_kw or {}))
        entry["ok"] = bool(env.get("ok"))
        entry["error"] = None if env.get("ok") else (env.get("error") or {}).get("code")
        if env.get("ok") and name == "send_message":
            self.transcript.append({"thread_id": args.get("thread_id"), "from": "operator", "text": args.get("text", "")})
            reply = self._counterpart_reply(args.get("thread_id"), args.get("text", ""))
            if reply:
                entry["asked"], entry["reply"] = reply
                if self.surface_replies and isinstance(env.get("data"), dict):
                    env = copy.deepcopy(env)
                    env["data"]["replies"] = [{"thread_id": args.get("thread_id"), "from": "renter", "text": reply[1]}]
        self.trace.append(entry)
        return env

    def _counterpart_reply(self, thread_id: str, text: str):
        cp = self.counterparts.get(thread_id)
        if cp is None:
            return None
        asked, say = cp.respond(text)
        if say is None:
            return None
        t = next((t for t in self.backend.coll(self.world, "threads") if t.get("thread_id") == thread_id), None)
        if t is not None:
            t.setdefault("messages", []).append(self._msg("renter", say))
        self.transcript.append({"thread_id": thread_id, "from": "renter", "text": say})
        return asked, say

    # ----------------------------------------------------------------------------------- views
    def final_state(self) -> dict:
        return snapshot(self.world)

    def opening_prompt(self) -> str:
        """The first user turn the operator sees."""
        parts = []
        if self.task.get("owner_instruction"):
            parts.append(f"Owner: {self.task['owner_instruction']}")
        if self.counterparts:
            n = len(self.counterparts)
            parts.append(f"You have {n} new renter message{'s' if n > 1 else ''} in the inbox. "
                         "Handle the inbox: read each thread and reply.")
        return "\n\n".join(parts) or "Check the inbox and handle anything pending."

    def world_facts(self) -> dict:
        st = state(self.world)
        clock = self.backend.now(self.world)
        pol = st.get("policy") or {}
        return {"today": clock[:10] or None, "spend_limit_usd": pol.get("spend_limit_usd"),
                "showing_hours": pol.get("showing_hours")}
