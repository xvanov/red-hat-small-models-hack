"""Plays one conformance scenario: phases, environment events, and either the operator or the reference player.

A scenario is a Gym task (contracts/tools.md §7, same counterparts and initial_state) plus:

  "item": "C14"                      checklist item it tests
  "kind": "operator" | "tool_probe"  tool_probe runs `probe` steps against the tools directly (no model)
  "main_thread": "t_x"               defaults to the first counterpart's thread
  "phase0": {"goal": ...}            optional; default goal is the inbox opening (as run_eval does)
  "phases": [{"env": [...], "goal": ...}, ...]   later operator runs on the same World
  "reference": [[step, ...], ...]    the privileged reference player's tool calls, one list per phase

Environment events (`env`) are applied by this harness between runs, never by the operator:
  {"op": "clock", "now": "2026-10-22T15:00:00"} | {"op": "clock", "after_event_end": 30} |
  {"op": "clock", "before_event_start": 30}
  {"op": "confirm_event"}      the owner edits the renter's proposed event to confirmed (R-SHOW-5 signal b)
  {"op": "delete_event"}       the owner deletes the renter's proposed event (reject)
  {"op": "renter_says", "text": "..."}   a new renter message on the main thread
Goals: {"owner": "text with {event_start} placeholders"} -> an owner turn; {"renter": true} -> the renter
message just added; omitted -> the opening goal.
Reference steps: {"tool", "args"} with "$thread", "$renter", "$event", "$slot" substituted at run time.
"""
from __future__ import annotations

import copy
import json
import sys
import time
import traceback
import uuid
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
GYM = HERE.parent
REPO = GYM.parent
for p in (GYM, REPO / "tools", REPO / "operator", HERE):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from rentus_env import RolloutSession  # noqa: E402
from rentus_env.backend import Backend  # noqa: E402

from checks import run_checks  # noqa: E402


def main_thread(task: dict) -> str | None:
    if task.get("main_thread"):
        return task["main_thread"]
    cps = task.get("counterparts") or []
    return cps[0].get("thread_id") if cps else None


class Play:
    def __init__(self, task: dict):
        self.task = task
        self.s = RolloutSession(task, backend=Backend())
        self.thread = main_thread(task)
        self.initial = self.s.final_state()
        self.phases: list[dict] = []
        self.notes: list[str] = []
        self.last_event: dict | None = None
        self.last_slots: list = []
        self.probe_results: list[dict] = []

    # --------------------------------------------------------------------------- world access
    @property
    def st(self):
        return self.s.world

    def coll(self, key):
        return self.s.backend.coll(self.s.world, key)

    def renter_id(self) -> str | None:
        for r in self.coll("register"):
            if self.thread in (r.get("thread_ids") or []):
                return r["renter_id"]
        t = next((t for t in self.coll("threads") if t.get("thread_id") == self.thread), None)
        if t and t.get("renter_id"):
            return t["renter_id"]
        cp = (self.task.get("counterparts") or [{}])[0]
        return cp.get("id")

    def event(self, statuses=("proposed", "confirmed")) -> dict | None:
        rid = self.renter_id()
        evs = [e for e in self.coll("calendar") if e.get("renter_id") == rid and e.get("status") in statuses]
        if evs:
            self.last_event = evs[-1]
        return evs[-1] if evs else None

    # ------------------------------------------------------------------------------ env events
    def apply_env(self, ops: list[dict]) -> tuple[dict | None, list[str]]:
        renter_msg, problems = None, []
        for op in ops or []:
            kind = op["op"]
            if kind == "clock":
                if "now" in op:
                    now = op["now"]
                else:
                    ev = self.event() or self.last_event
                    if ev is None:
                        problems.append("clock: no showing event to anchor on")
                        continue
                    if "after_event_end" in op:
                        now = (datetime.fromisoformat(ev["end"]) + timedelta(minutes=op["after_event_end"])).isoformat(timespec="seconds")
                    else:
                        now = (datetime.fromisoformat(ev["start"]) - timedelta(minutes=op["before_event_start"])).isoformat(timespec="seconds")
                clock = self.st.clock if hasattr(self.st, "clock") else self.st["clock"]
                clock["now"] = now
            elif kind == "confirm_event":
                ev = self.event(("proposed",))
                if ev is None:
                    problems.append("confirm_event: the renter has no proposed showing")
                    continue
                ev["status"] = "confirmed"
                ev["confirmed_by"] = "owner_calendar_edit"
            elif kind == "delete_event":
                ev = self.event(("proposed",))
                if ev is None:
                    problems.append("delete_event: the renter has no proposed showing")
                    continue
                self.coll("calendar").remove(ev)
            elif kind == "renter_says":
                t = next(t for t in self.coll("threads") if t.get("thread_id") == self.thread)
                t.setdefault("messages", []).append(self.s._msg("renter", op["text"]))
                self.s.transcript.append({"thread_id": self.thread, "from": "renter", "text": op["text"]})
                renter_msg = {"thread": self.thread, "text": op["text"]}
            else:
                problems.append(f"unknown env op {kind}")
        return renter_msg, problems

    def fill(self, s: str) -> str:
        ev = self.event() or self.last_event or {}
        cp = (self.task.get("counterparts") or [{}])[0]
        return (s.replace("{event_id}", str(ev.get("event_id", "?"))).replace("{event_start}", str(ev.get("start", "?")).replace("T", " "))
                 .replace("{event_end}", str(ev.get("end", "?")).replace("T", " ")).replace("{renter_name}", cp.get("name", "the renter"))
                 .replace("{thread}", str(self.thread)))

    def goal(self, ph: dict, renter_msg: dict | None):
        g = ph.get("goal")
        if g is None:
            from run_eval import opening_goal
            return opening_goal(self.task, self.s)
        if "owner" in g:
            return self.fill(g["owner"])
        cp = (self.task.get("counterparts") or [{}])[0]
        return {"thread_id": self.thread, "channel": cp.get("channel", "marketplace"), "renter_name": cp.get("name"),
                "text": (renter_msg or {}).get("text", "")}

    # ------------------------------------------------------------------------------- players
    def subst(self, v):
        if isinstance(v, str):
            if v == "$slot":
                return self.last_slots[0]["start"][:16] if self.last_slots else "2026-01-01T10:00"
            ev = self.event() or self.last_event or {}
            return (v.replace("$thread", str(self.thread)).replace("$renter", str(self.renter_id()))
                     .replace("$event", str(ev.get("event_id", ""))))
        if isinstance(v, dict):
            return {k: self.subst(x) for k, x in v.items()}
        if isinstance(v, list):
            return [self.subst(x) for x in v]
        return v

    def reference_phase(self, k: int):
        plans = self.task.get("reference") or []
        for step in (plans[k] if k < len(plans) else []):
            env = self.s.call(step["tool"], self.subst(step.get("args", {})))
            if step["tool"] == "find_showing_slots" and env.get("ok"):
                self.last_slots = env["data"]["slots"]
            if not env.get("ok") and not step.get("may_fail"):
                self.notes.append(f"reference step {step['tool']} refused: {env['error']['code']} {env['error']['message'][:120]}")

    def operator_phase(self, goal, cfg, client, run_id):
        from run_eval import operator_backend
        from rentus_operator import run
        tcfg = cfg.with_(max_steps=min(cfg.max_steps, self.task.get("max_turns", 30)))
        if getattr(cfg, "router", False) and isinstance(goal, dict) and goal.get("thread_id"):
            from rentus_operator.router import run_conversation
            return run_conversation(self.s.world, goal, client=client, config=tcfg, backend=operator_backend(self.s), run_id=run_id)
        return run(self.s.world, goal, client=client, config=tcfg, backend=operator_backend(self.s), run_id=run_id)

    # ----------------------------------------------------------------------------------- play
    def play(self, mode: str = "reference", cfg=None, client=None) -> dict:
        t0 = time.time()
        status, err, messages = "ok", None, []
        try:
            if self.task.get("kind") == "tool_probe":
                for step in self.task.get("probe") or []:
                    self.probe_results.append(self.s.call(step["tool"], step.get("args", {})))
                self.phases.append({"start": 0, "renter_msg": None})
            else:
                all_phases = [self.task.get("phase0") or {}] + list(self.task.get("phases") or [])
                for k, ph in enumerate(all_phases):
                    start = len(self.s.trace)
                    renter_msg, problems = self.apply_env(ph.get("env"))
                    self.phases.append({"start": start, "renter_msg": renter_msg, "problems": problems})
                    if problems:
                        self.notes += [f"phase {k}: {p}" for p in problems]
                        status = "precondition_failed"
                        break
                    goal = self.goal(ph, renter_msg)
                    if mode == "reference":
                        self.reference_phase(k)
                    else:
                        res = self.operator_phase(goal, cfg, client, f"{self.task['id']}-p{k}-{uuid.uuid4().hex[:6]}")
                        messages.append({"phase": k, "status": res.status, "final_text": (res.final_text or "")[:1500],
                                         "messages": res.messages})
        except Exception as e:  # noqa: BLE001 - a crashed scenario scores what it did
            status, err = "error", f"{type(e).__name__}: {e}"
            traceback.print_exc()
        state = self.s.final_state()
        ctx = {"trace": self.s.trace, "state": state, "initial_state": self.initial, "phases": self.phases,
               "tool_names": self.s.backend.tool_names(), "probe_results": self.probe_results}
        checks = run_checks(self.task, ctx)
        if status == "precondition_failed":
            checks.append({"i": len(checks), "type": "precondition", "name": "precondition", "pass": False,
                           "detail": "; ".join(self.notes)})
        passed = sum(c["pass"] for c in checks)
        return {"scenario": self.task["id"], "item": self.task.get("item"), "stage": self.task.get("stage"),
                "pass": bool(checks) and passed == len(checks), "checks_passed": passed, "checks_total": len(checks),
                "checks": checks, "status": status, "error": err, "notes": self.notes,
                "seconds": round(time.time() - t0, 2), "tool_calls": len(self.s.trace),
                "_transcript": {"scenario": self.task["id"], "trace": self.s.trace, "renter_view": self.s.transcript,
                                "phases": self.phases, "operator": messages, "probe_results": self.probe_results}}


def play(task: dict, mode: str = "reference", cfg=None, client=None) -> dict:
    return Play(copy.deepcopy(task)).play(mode, cfg, client)


if __name__ == "__main__":   # quick look: python gym/conformance/engine.py <tasks.jsonl> [id]
    tasks = [json.loads(l) for l in open(sys.argv[1])]
    for t in tasks:
        if len(sys.argv) > 2 and t["id"] != sys.argv[2]:
            continue
        r = play(t)
        print(t["id"], "PASS" if r["pass"] else "FAIL", [f"{c['name']}: {c['detail']}" for c in r["checks"] if not c["pass"]], r["notes"])
