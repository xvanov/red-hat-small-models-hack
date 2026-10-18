"""A console run driven by the real operator (rentus_operator, W2) over the real tools (rentus_tools, W3).

One run = one World. Work arrives as turns, and each turn is one `rentus_operator.run(...)` call:

  owner chat        -> run(world, "<text>")                       owner lane, one at a time, history kept
  renter arrives    -> run(world, {"thread_id", "channel", ...})  renter lanes, up to RENTER_WORKERS at once,
                                                                  one history per thread
  owner decision    -> run(world, "Owner decision on escalation X: ...")   owner lane

Renter conversations run in parallel (vLLM batches the concurrent requests), the owner can keep talking
while they run, and every tool call is serialized on one lock so the World stays consistent.

The operator runs with the FINAL held-out config from docs/results.md (prompt v3 + renter guard +
style pre-check + reasoning kept in history), not the RunConfig() defaults, which are the baseline.

Renters are scripted counterparts. With a gym scenario we use the gym's own RolloutSession (W4), so
counterparts answer inside send_message exactly as they do when scoring. In free play the console adds
renters itself (a few synthetic ones once a listing is live, or whatever the demo director sends).
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
# The held-out winner (docs/results.md, "final" row): guard + prompt v3 + style pre-check + reasoning history.
FINAL_CONFIG = {"prompt_version": "v3", "renter_guard": True, "style_precheck": True,
                "keep_reasoning_in_history": True}
FINAL_CONFIG_NAME = "guard+prompt3+style+rhist"
RENTER_WORKERS = 3


def _gym_counterpart_cls():
    mod, _ = integ.try_import("rentus_env.counterparts")
    return getattr(mod, "Counterpart", None) if mod else None


class LockedWorld:
    """What the operator loop reads the World through: every read of the whole state takes the run lock,
    so a renter turn never deep-copies the World while another turn's tool call is changing it."""

    def __init__(self, world, lock):
        self._w, self._lock = world, lock

    def to_dict(self):
        with self._lock:
            return self._w.to_dict()

    def __getattr__(self, item):
        return getattr(self._w, item)


class FreePlaySession:
    """Same surface as the gym's RolloutSession.call, for owner-driven runs."""

    def __init__(self, rt, world):
        self.rt, self.world = rt, world
        self.counterparts: dict = {}
        self.transcript: list[dict] = []
        self._n = 0

    def add_counterpart(self, spec: dict, listing: dict | None, opening: bool = True) -> tuple[dict, str]:
        Gym = _gym_counterpart_cls()
        spec = {**spec, "thread_id": spec.get("thread_id") or "t_" + spec["id"].split(":", 1)[-1]}
        cp = Gym(spec) if Gym else ConsoleCounterpart(spec)
        cp.thread_id = spec["thread_id"]
        self.counterparts[cp.thread_id] = cp
        said = " ".join(cp.opening()) if opening else ""
        thread = {"thread_id": cp.thread_id, "channel": cp.channel, "renter_name": cp.name,
                  "language": cp.language, "messages": [self._msg("renter", said)] if said else []}
        if spec.get("kind"):
            thread["kind"] = spec["kind"]
        if listing:
            thread["listing_id"], thread["room_id"] = listing.get("listing_id"), listing.get("room_id")
        elif spec.get("room_of_interest"):
            thread["room_id"] = spec["room_of_interest"]
        self.world.threads.append(thread)
        ch = self.world.channels.get(cp.channel)
        if isinstance(ch, dict) and isinstance(ch.get("threads"), list):
            ch["threads"].append(cp.thread_id)
        if said:
            self.transcript.append({"thread_id": cp.thread_id, "from": "renter", "text": said})
        return thread, said

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
                text = args.get("text", "")
                say = cp.respond(text)[1] if hasattr(cp, "respond") else cp.reply_to(text)
                if not say and "?" not in text and hasattr(cp, "respond"):
                    # A real renter answers "Please tell me the exact day" too; the scored Gym renter only answers
                    # questions. Free play only (scenarios keep the Gym's exact behavior).
                    say = cp.respond(text.rstrip(" .!") + "?")[1]
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
        with o.lock:
            before = len(o.session.transcript)
            env = o.session.call(name, args, **kw)
            new = o.session.transcript[before:]
        for line in new:
            if line["from"] == "renter":
                o.emit_renter(line["thread_id"], line["text"])
        return env

    def __getattr__(self, item):
        return getattr(self._o.rt, item)


def opening_goal(task: dict, session):
    """Same first turn the gym's local runner gives the operator (gym/run_eval.py opening_goal)."""
    if task.get("owner_instruction"):
        return task["owner_instruction"]
    cp = next(iter(session.counterparts.values()))
    said = " ".join(l["say"] for l in cp.script if l.get("after") == "start")
    return {"thread_id": cp.thread_id, "channel": cp.channel, "renter_name": cp.name, "text": said}


class OperatorRun:
    def __init__(self, run_id: str, run_dir: Path, goal: str, scenario: dict | None, speed: float,
                 live: bool, badge: dict, world_patch: dict | None = None, seed_renters: bool | None = None):
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
        self.owner_turns: queue.Queue = queue.Queue()
        self.renter_turns: queue.Queue = queue.Queue()
        self.owner_history: list[dict] | None = None
        self.thread_history: dict[str, list[dict]] = {}
        self.thread_locks: dict[str, threading.Lock] = {}
        self._active = 0
        self.owner_busy = False
        self._active_lock = threading.Lock()
        self._stop = threading.Event()
        self.sink = rt.EventSink(run_id=run_id, path=self.run_dir / "events.jsonl")
        self.note = None  # console annotation hook (app sets it): note(type, data, actor="system")
        self.cfg = op.RunConfig().with_(**FINAL_CONFIG)
        self.config_name = FINAL_CONFIG_NAME
        if live:
            from rentus_operator.loop import make_client
            model = os.environ.get("OPERATOR_MODEL") or (badge.get("models") or [self.cfg.model])[0]
            self.cfg = self.cfg.with_(model=model)
            self.client = make_client(self.cfg, timeout=180, max_retries=1)
        else:
            from rentus_operator.stub_model import StubClient, listing_demo
            self.client = StubClient(listing_demo(channels=("marketplace", "roomies", "craigslist", "padsplit")))
            self.cfg = self.cfg.with_(model="stub")

        self.free_play_renters = (not scenario) if seed_renters is None else seed_renters
        if scenario:
            gym, err = integ.try_import("rentus_env")
            if not gym:
                raise RuntimeError(f"gym package not importable: {err}")
            self.session = gym.RolloutSession(scenario)
            self.world = self.session.world
            self.submit(opening_goal(scenario, self.session))
        else:
            self.world = rt.load(patch=world_patch) if world_patch else rt.load()
            if FIXTURE.exists():
                toolbox.add_room(self.world, json.loads(FIXTURE.read_text())["room"])
            self.session = FreePlaySession(rt, self.world)
            if goal:
                self.submit(goal)
        self.view_world = LockedWorld(self.world, self.lock)
        self.backend = _Backend(self)
        self.threads = [threading.Thread(target=self._owner_main, name=f"op-{run_id}", daemon=True)]
        self.threads += [threading.Thread(target=self._renter_main, name=f"op-{run_id}-r{i}", daemon=True)
                         for i in range(RENTER_WORKERS)]

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
        for t in self.threads:
            t.start()

    def stop(self):
        self._stop.set()
        self.status = "stopped"

    @property
    def busy(self) -> bool:
        return self._active > 0 or not self.owner_turns.empty() or not self.renter_turns.empty()

    @property
    def owner_idle(self) -> bool:
        return not self.owner_busy and self.owner_turns.empty()

    def submit(self, turn):
        """Route a turn: renter inbound (dict with thread_id) to the renter lanes, anything else to the owner.
        {"thread_id", "owner_text"} is an owner message about one conversation (a decision on its escalation):
        it runs in that conversation's lane, after its current turn, with its history."""
        if isinstance(turn, dict) and turn.get("thread_id") and not turn.get("owner_instruction"):
            self.renter_turns.put(turn)
        else:
            self.owner_turns.put(turn)

    def _turn(self, turn, history, who: str | None = None, thread_id: str | None = None):
        with self._active_lock:
            self._active += 1
        self.status = "running"
        try:
            t0 = time.time()
            res = self.op.run(self.view_world, turn, client=self.client, config=self.cfg, sink=self.sink,
                              backend=self.backend, run_id=self.run_id, history=history)
            if self.note:
                self.note("turn_done", {"kind": "renter" if thread_id else "owner", "thread_id": thread_id,
                                        "who": who,
                                        "status": res.status, "final_text": (res.final_text or "")[:1500],
                                        "steps": res.steps, "tool_calls": res.tool_calls,
                                        "seconds": round(time.time() - t0, 1), "model": self.cfg.model})
            return res.messages
        except Exception as e:  # keep the console alive; surface it in the trace
            import traceback
            self.error = f"{type(e).__name__}: {e}"
            self.sink.emit("fallback", "system", {"reason": "operator turn crashed: " + self.error[:300]})
            (self.run_dir / "errors.log").open("a").write(traceback.format_exc() + "\n")
            return history
        finally:
            with self._active_lock:
                self._active -= 1
            self.save()
            self._settle()

    def _settle(self):
        if self._stop.is_set():
            self.status = "stopped"
        elif not self.busy:
            self.status = "idle"

    def _owner_main(self):
        renters_seeded = False
        while not self._stop.is_set():
            try:
                turn = self.owner_turns.get(timeout=0.2)
            except queue.Empty:
                self._settle()
                if self.free_play_renters and not renters_seeded and self.world.listings and not self.busy:
                    renters_seeded = True
                    threading.Thread(target=self._seed_renters, daemon=True).start()
                continue
            self.owner_busy = True
            try:
                self.owner_history = self._turn(turn, self.owner_history)
            finally:
                self.owner_busy = False
        self.save()

    def _renter_main(self):
        while not self._stop.is_set():
            try:
                turn = self.renter_turns.get(timeout=0.2)
            except queue.Empty:
                continue
            tid = turn["thread_id"]
            lock = self.thread_locks.setdefault(tid, threading.Lock())
            goal = turn["owner_text"] if turn.get("owner_text") else turn
            cp = self.session.counterparts.get(tid)
            who = getattr(cp, "name", None) or turn.get("renter_name") or tid
            if turn.get("owner_text"):
                who = f"owner's decision for {who}"
            with lock:  # one conversation is never handled by two workers at once
                self.thread_history[tid] = self._turn(goal, self.thread_history.get(tid), who=who, thread_id=tid)

    def _seed_renters(self):
        for spec in DEFAULT_COUNTERPARTS:
            self._stop.wait(3.0 / self.speed)
            if self._stop.is_set():
                return
            self.add_renter(spec)

    def add_renter(self, spec: dict, listing: dict | None = None) -> dict:
        """A renter writes in: their thread appears in the lane and a renter turn is queued."""
        with self.lock:
            listing = listing or (self.world.listings[-1] if self.world.listings else None)
            thread, opening = self.session.add_counterpart(spec, listing)
        self.emit_renter(thread["thread_id"], opening)
        self.submit({"thread_id": thread["thread_id"], "channel": thread["channel"],
                     "renter_name": thread["renter_name"], "text": opening})
        return thread

    def renter_says(self, thread_id: str, text: str) -> bool:
        """An existing renter writes again: the message lands in their thread and a renter turn is queued."""
        with self.lock:
            t = next((t for t in self.world.threads if t.get("thread_id") == thread_id), None)
            if t is None:
                return False
            t.setdefault("messages", []).append(self.session._msg("renter", text))
            self.session.transcript.append({"thread_id": thread_id, "from": "renter", "text": text})
        self.emit_renter(thread_id, text)
        self.submit({"thread_id": thread_id, "channel": t.get("channel"), "renter_name": t.get("renter_name"),
                     "text": text})
        return True

    def add_thread(self, spec: dict, opening: bool = True) -> dict:
        """A thread with a scripted counterpart but no renter turn (e.g. a tenant the owner tells us about)."""
        with self.lock:
            thread, said = self.session.add_counterpart(spec, None, opening=opening)
        if said:
            self.emit_renter(thread["thread_id"], said)
        return thread

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
        self.submit(text)

    def decide(self, esc_id: str, approve: bool, note: str = "", text: str | None = None, source: str = "console"):
        reason, draft, ref = "", "", ""
        with self.lock:
            for e in self.world.escalations:
                if e.get("esc_id") == esc_id:
                    e["status"] = "approved" if approve else "denied"
                    e["decided_via"] = source
                    if text:
                        e["owner_text"] = text
                    reason, draft = e.get("reason", ""), e.get("draft") or ""
                    ref = e.get("thread_id") or e.get("job_id") or e.get("ref_id") or ""
        where = f" (ref {ref})" if ref else ""
        if approve and text and text.strip() != draft.strip():
            msg = (f"Owner decision on escalation {esc_id}{where} ({reason}): APPROVED with my own wording. "
                   f"Send exactly this text, unchanged: \"{text.strip()}\"")
        elif approve:
            msg = (f"Owner decision on escalation {esc_id}{where} ({reason}): APPROVED, go ahead with the draft"
                   + (f": \"{draft}\"" if draft else "") + ".")
        else:
            msg = f"Owner decision on escalation {esc_id}{where} ({reason}): DENIED, do not do it."
        if note:
            msg += f" Note: {note}"
        known = any(t.get("thread_id") == ref for t in self.world.threads)
        if ref.startswith("t_") and known:
            msg += f" Reply to the renter on thread {ref} with send_message."
            self.submit({"thread_id": ref, "owner_text": msg})
        else:
            self.submit(msg)

    def set_speed(self, speed: float):
        self.speed = max(0.1, float(speed))
