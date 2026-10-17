"""A console run driven by the real operator (rentus_operator, W2) over the real tools (rentus_tools, W3).

One run = one World and a queue of turns. Each turn is one `rentus_operator.run(...)` call, with
the conversation history carried over, so the owner can keep talking while renters arrive:

  owner chat        -> run(world, "<text>")
  renter arrives    -> run(world, {"thread_id", "channel", "renter_name", "text"})
  owner decision    -> run(world, "Owner decision on escalation X: approved ...")

Renters are scripted counterparts. With a gym scenario we use the gym's own RolloutSession
(W4), so counterparts answer inside send_message exactly as they do when scoring. In free play
the console seeds a few synthetic renters once a listing is live.
"""
from __future__ import annotations

import copy
import json
import os
import queue
import threading
import time
from pathlib import Path

from . import integration as integ
from .renters import DEFAULT_COUNTERPARTS
from .renters import Counterpart as ConsoleCounterpart

FIXTURE = integ.REPO / "operator" / "fixtures" / "appling_way.json"


def _gym_counterpart_cls():
    mod, _ = integ.try_import("rentus_env.counterparts")
    return getattr(mod, "Counterpart", None) if mod else None


class FreePlaySession:
    """Same surface as the gym's RolloutSession.call, for owner-driven runs."""

    def __init__(self, rt, world):
        self.rt, self.world = rt, world
        self.counterparts: dict = {}
        self.transcript: list[dict] = []
        self._n = 0

    def add_counterpart(self, spec: dict, listing: dict | None) -> tuple[dict, str]:
        Gym = _gym_counterpart_cls()
        spec = {**spec, "thread_id": spec.get("thread_id") or "t_" + spec["id"].split(":", 1)[-1]}
        cp = Gym(spec) if Gym else ConsoleCounterpart(spec)
        cp.thread_id = spec["thread_id"]
        self.counterparts[cp.thread_id] = cp
        opening = " ".join(cp.opening())
        thread = {"thread_id": cp.thread_id, "channel": cp.channel, "renter_name": cp.name,
                  "language": cp.language, "messages": [self._msg("renter", opening)]}
        if listing:
            thread["listing_id"], thread["room_id"] = listing.get("listing_id"), listing.get("room_id")
        self.world.threads.append(thread)
        ch = self.world.channels.get(cp.channel)
        if isinstance(ch, dict) and isinstance(ch.get("threads"), list):
            ch["threads"].append(cp.thread_id)
        self.transcript.append({"thread_id": cp.thread_id, "from": "renter", "text": opening})
        return thread, opening

    def _msg(self, who, text):
        self._n += 1
        now = self.world.clock.get("now") if isinstance(self.world.clock, dict) else str(self.world.clock)
        return {"id": f"con-m{self._n:03d}", "from": who, "text": text, "attachments": [], "ts": now}

    def call(self, name, args, **kw):
        env = self.rt.call(self.world, name, args, **kw)
        if env.get("ok") and name == "send_message" and isinstance(args, dict):
            tid = args.get("thread_id")
            cp = self.counterparts.get(tid)
            if cp is not None:
                say = cp.respond(args.get("text", ""))[1] if hasattr(cp, "respond") else cp.reply_to(args.get("text", ""))
                if say:
                    t = next((t for t in self.world.threads if t.get("thread_id") == tid), None)
                    if t is not None:
                        t.setdefault("messages", []).append(self._msg("renter", say))
                    self.transcript.append({"thread_id": tid, "from": "renter", "text": say})
                    env = copy.deepcopy(env)
                    env.setdefault("data", {})["replies"] = [{"thread_id": tid, "from": "renter", "text": say}]
        return env


class _Backend:
    """What rentus_operator.run(backend=...) needs: call(), TOOLS, tool_schemas(); routed via the session."""

    def __init__(self, owner: "OperatorRun"):
        self._o = owner
        self.TOOLS = owner.rt.TOOLS

    def tool_schemas(self, variant="verbose"):
        return self._o.rt.tool_schemas(variant)

    def call(self, world, name, args, **kw):
        o = self._o
        time.sleep(0.25 / o.speed)  # pacing so a stub-fast run is still watchable
        before = len(o.session.transcript)
        with o.lock:
            env = o.session.call(name, args, **kw)
        for line in o.session.transcript[before:]:
            if line["from"] == "renter":
                o.emit_renter(line["thread_id"], line["text"])
        return env

    def __getattr__(self, item):
        return getattr(self._o.rt, item)


class OperatorRun:
    def __init__(self, run_id: str, run_dir: Path, goal: str, scenario: dict | None, speed: float,
                 live: bool, badge: dict):
        import rentus_operator as op
        import rentus_tools as rt
        from rentus_operator import toolbox

        self.op, self.rt, self.toolbox = op, rt, toolbox
        self.run_id, self.run_dir, self.goal, self.scenario = run_id, Path(run_dir), goal, scenario
        self.speed = max(0.1, float(speed))
        self.live = live
        self.mode = "operator" if live else "operator-stub"
        self.status = "starting"
        self.error = None
        self.lock = threading.RLock()
        self.turns: queue.Queue = queue.Queue()
        self.history: list[dict] | None = None
        self._stop = threading.Event()
        self.sink = rt.EventSink(run_id=run_id, path=self.run_dir / "events.jsonl")
        self.cfg = op.RunConfig()
        self.client = None
        if live:
            from openai import OpenAI
            model = os.environ.get("OPERATOR_MODEL") or (badge.get("models") or [self.cfg.model])[0]
            self.cfg = self.cfg.with_(model=model)
            self.client = OpenAI(base_url=self.cfg.base_url, api_key=self.cfg.api_key)
        else:
            from rentus_operator.stub_model import StubClient, listing_demo
            self.client = StubClient(listing_demo(channels=("marketplace", "roomies", "craigslist", "padsplit")))
            self.cfg = self.cfg.with_(model="stub")

        self.free_play_renters = not scenario
        if scenario:
            gym, err = integ.try_import("rentus_env")
            if not gym:
                raise RuntimeError(f"gym package not importable: {err}")
            self.session = gym.RolloutSession(scenario)
            self.world = self.session.world
            self.turns.put(self.session.opening_prompt())
        else:
            self.world = rt.load()
            if FIXTURE.exists():
                toolbox.add_room(self.world, json.loads(FIXTURE.read_text())["room"])
            self.session = FreePlaySession(rt, self.world)
            if goal:
                self.turns.put(goal)
        self.backend = _Backend(self)
        self.thread = threading.Thread(target=self._main, name=f"op-{run_id}", daemon=True)

    # ---------- events ----------
    def emit_renter(self, thread_id: str, text: str):
        cp = self.session.counterparts.get(thread_id)
        self.sink.emit("renter_message", getattr(cp, "id", "renter:?"),
                       {"thread_id": thread_id, "channel": getattr(cp, "channel", None),
                        "name": getattr(cp, "name", None), "language": getattr(cp, "language", None), "text": text})

    # ---------- lifecycle ----------
    def start(self):
        if self.scenario:
            for tid, t in ((t["thread_id"], t) for t in self.world.threads):
                if tid in self.session.counterparts:
                    for m in t.get("messages", []):
                        if m.get("from") == "renter":
                            self.emit_renter(tid, m["text"])
        self.thread.start()

    def stop(self):
        self._stop.set()

    def _main(self):
        renters_seeded = False
        while not self._stop.is_set():
            try:
                turn = self.turns.get(timeout=0.2)
            except queue.Empty:
                self.status = "idle" if self.status != "error" else "error"
                if self.free_play_renters and not renters_seeded and self.world.listings:
                    renters_seeded = True
                    threading.Thread(target=self._seed_renters, daemon=True).start()
                continue
            self.status = "running"
            try:
                res = self.op.run(self.world, turn, client=self.client, config=self.cfg, sink=self.sink,
                                  backend=self.backend, run_id=self.run_id, history=self.history)
                self.history = res.messages
            except Exception as e:  # keep the console alive; surface it in the trace
                self.error = f"{type(e).__name__}: {e}"
                self.status = "error"
                self.sink.emit("fallback", "system", {"reason": "operator turn crashed: " + self.error[:300]})
            self.save()
        self.save()
        self.status = "stopped"

    def _seed_renters(self):
        listing = self.world.listings[-1]
        for i, spec in enumerate(DEFAULT_COUNTERPARTS):
            self._stop.wait(3.0 / self.speed)
            if self._stop.is_set():
                return
            with self.lock:
                thread, opening = self.session.add_counterpart(spec, listing)
            self.emit_renter(thread["thread_id"], opening)
            self.turns.put({"thread_id": thread["thread_id"], "channel": thread["channel"],
                            "renter_name": thread["renter_name"], "text": opening})

    # ---------- console controls ----------
    def snapshot(self) -> dict:
        with self.lock:
            return integ.world_to_dict(self.world)

    def save(self):
        try:
            (self.run_dir / "world.json").write_text(json.dumps(self.snapshot(), indent=1, default=str))
        except Exception:
            pass

    def inject_fault(self, fault: dict):
        with self.lock:
            self.world.faults.append(fault)

    def owner_say(self, text: str):
        self.turns.put(text)

    def decide(self, esc_id: str, approve: bool, note: str = ""):
        reason = ""
        with self.lock:
            for e in self.world.escalations:
                if e.get("esc_id") == esc_id:
                    e["status"] = "approved" if approve else "denied"
                    reason = e.get("reason", "")
        self.turns.put(f"Owner decision on escalation {esc_id} ({reason}): "
                       f"{'APPROVED, go ahead with the draft' if approve else 'DENIED, do not do it'}."
                       + (f" Note: {note}" if note else ""))

    def set_speed(self, speed: float):
        self.speed = max(0.1, float(speed))
