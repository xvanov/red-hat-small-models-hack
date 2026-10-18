"""One-click "Demo run": a tight, scripted sequence over the REAL operator, for the video.

The director only plays the owner and the world: it types the owner's instructions, lets scripted
renters write in, flips faults on, and waits. Every reply, tool call, retry and escalation comes from
the live operator (Lightning on vLLM) and the real tools, exactly as in free play.

  1 listing   owner: "Appling Way room free Nov 1, $750, private bath"
  2 renters   María (Spanish, vague date first) and Devon (offers $700) write in at the same time
  3 fault     Marketplace rate-limits the next message and the reader returns a broken result
  4 ops       owner: the tenant's kitchen sink leaks; get it fixed (one plumber never answers)
  5 approve   Devon's price question waits for the owner, who approves it on his phone (/approve)
"""
from __future__ import annotations

import threading
import time

from .renters import DEVON, MARIA

LISTING_GOAL = "Appling Way room free Nov 1, $750, private bath. Post it on Marketplace, Roomies and Craigslist."
OPS_GOAL = ("Jordan, the tenant at Appling Way (room R100, zip 27703), says the kitchen sink is leaking under the "
            "cabinet. Get a plumber booked and keep her posted. Her thread is t_tenant_jordan.")

# A demo world: the sandbox inventory plus three plumbers for the Appling Way zip, one of whom never answers.
DEMO_PATCH = {
    "clock": {"now": "2026-10-17T10:00:00"},
    "policy": {"spend_limit_usd": 400},
    "vendors": {"$replace": [
        {"vendor_id": "V01", "name": "Bull City Pipe Works", "trade": "plumber", "phone": "+19195551100",
         "rating": 4.6, "service_area": ["27703"], "eta_days": 1, "responds": True, "quote_range": [310, 310]},
        {"vendor_id": "V02", "name": "Triangle Pipe Pros", "trade": "plumber", "phone": "+19195551101",
         "rating": 4.8, "service_area": ["27703"], "eta_days": 1, "responds": False, "quote_range": [220, 220]},
        {"vendor_id": "V03", "name": "Eno River Plumbing", "trade": "plumber", "phone": "+19195551102",
         "rating": 4.5, "service_area": ["27703"], "eta_days": 2, "responds": True, "quote_range": [185, 185]},
    ]},
}

TENANT = {"id": "tenant:jordan", "name": "Jordan (tenant)", "channel": "sms", "language": "en",
          "thread_id": "t_tenant_jordan", "kind": "tenant", "room_of_interest": "R100",
          "script": [
              {"after": "start", "say": "Hi, the kitchen sink at Appling Way is leaking under the cabinet."},
              {"when_asked": "any", "say": "Thank you, I'll be home."},
              {"when_asked": "any", "say": "Sounds good, thanks!", "reuse": True},
          ]}
# If nothing is waiting for the owner when the approval beat starts, Devon asks for payment terms, which the
# operator may never agree to on its own (prompt v3: "special payment terms ... escalate_to_owner").
DEVON_FOLLOW_UP = "One more question: could I get a discount if I pay 3 months upfront?"
FAULTS = [
    {"tool": "send_message", "kind": "rate_limited", "times": 1, "match": {"thread_id": "t_maria"}},
    {"tool": "read_reply", "kind": "malformed", "times": 1},
]

STEPS = [
    {"id": "listing", "title": "List the room", "say": "The owner types one line. The operator writes the "
     "listing from the room record, checks it against fair-housing rules and posts it to three channels."},
    {"id": "renters", "title": "Two renters at once", "say": "María writes in Spanish and Devon asks for a lower rent. "
     "Both conversations run in parallel; the fine-tuned reader turns every reply into exact fields."},
    {"id": "fault", "title": "Break something", "say": "Marketplace rate-limits the next message and the reader "
     "returns a broken result. Watch the verifier catch it and the operator retry."},
    {"id": "ops", "title": "Plumber job", "say": "A tenant's sink leaks. The operator opens a job, asks plumbers "
     "for quotes (one never answers), books the cheapest under the $400 limit and tells the tenant."},
    {"id": "approve", "title": "Owner approves on the phone", "say": "Devon asked for a lower rent. The operator never "
     "commits money on its own: it escalated with a draft and kept qualifying him. The owner decides on his phone."},
    {"id": "done", "title": "Done", "say": "Everything the owner had to decide came to him; everything else ran."},
]


class Director:
    def __init__(self, run, note, speed: float = 1.0, auto_approve_s: float | None = None, approve_url: str = ""):
        self.run, self.note = run, note
        self.speed = max(0.25, float(speed))
        self.auto_approve_s = auto_approve_s
        self.approve_url = approve_url
        self.step = None
        self.started = time.time()
        self.step_started = {}
        self.finished = None
        self.error = None
        self._stop = threading.Event()
        self.thread = threading.Thread(target=self._main, name="demo-director", daemon=True)

    def state(self) -> dict:
        return {"run_id": self.run.run_id, "step": self.step, "steps": STEPS, "started": self.started,
                "step_started": self.step_started, "finished": self.finished, "error": self.error,
                "speed": self.speed, "approve_url": self.approve_url, "elapsed": round(
                    (self.finished or time.time()) - self.started, 1), "auto_approve_s": self.auto_approve_s}

    def start(self):
        self.thread.start()

    def stop(self):
        self._stop.set()

    def set_speed(self, speed: float):
        self.speed = max(0.25, float(speed))
        self.run.set_speed(self.speed)

    # ---------------------------------------------------------------- helpers
    def _go(self, step_id: str):
        self.step = step_id
        self.step_started[step_id] = time.time()
        s = next(s for s in STEPS if s["id"] == step_id)
        self.note("demo_step", {"step": step_id, "title": s["title"], "say": s["say"]})

    def _pause(self, seconds: float):
        self._stop.wait(seconds / self.speed)
        if self._stop.is_set():
            raise _Stopped

    def _wait(self, cond, timeout: float, poll: float = 0.5) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            if self._stop.is_set() or self.run.status == "stopped":
                raise _Stopped
            if cond():
                return True
            time.sleep(poll)
        return False

    def _idle(self) -> bool:
        return not self.run.busy

    def _open_escalations(self) -> list[dict]:
        return [e for e in self.run.snapshot().get("escalations", []) if (e.get("status") or "open") == "open"]

    # ---------------------------------------------------------------- the sequence
    def _main(self):
        try:
            self._go("listing")
            self.run.owner_say(LISTING_GOAL)
            self._wait(lambda: self.run.snapshot().get("listings") and self._idle(), timeout=240)
            self._pause(2)

            self._go("renters")
            self.run.add_renter(MARIA)
            self.run.add_renter(DEVON)
            self._pause(5)

            self._go("fault")
            for f in FAULTS:
                self.run.inject_fault(dict(f))
                self.note("fault_injected", f, actor="owner")
            self._pause(10)

            self._go("ops")
            self.run.add_thread(TENANT)
            self.run.owner_say(OPS_GOAL)
            self._pause(2)
            self._wait(lambda: self.run.owner_idle, timeout=300)
            # the approval beat starts as soon as something is waiting for the owner (renters may still be talking)
            self._wait(lambda: self._open_escalations() or self._idle(), timeout=300)
            self._pause(1)

            self._go("approve")
            if not self._open_escalations() and self.run.renter_says("t_devon", DEVON_FOLLOW_UP):
                self.note("demo_nudge", {"thread_id": "t_devon", "text": DEVON_FOLLOW_UP})
                self._wait(lambda: self._open_escalations() or self._idle(), timeout=180)
            if self._open_escalations():
                self.note("approve_wait", {"url": self.approve_url, "open": len(self._open_escalations())})
                limit = self.auto_approve_s if self.auto_approve_s else 1e9
                t0 = time.time()
                decided = self._wait(lambda: not self._open_escalations(), timeout=limit)
                if not decided and self.auto_approve_s:
                    for e in self._open_escalations():
                        self.run.decide(e["esc_id"], True, source="demo timer")
                        self.note("owner_decision", {"esc_id": e["esc_id"], "decision": "approve",
                                                     "via": "demo timer (no owner tapped)"}, actor="owner")
                self.note("approve_done", {"waited_s": round(time.time() - t0, 1)})
                self._pause(1)
                self._wait(self._idle, timeout=240)
            else:
                self.note("approve_wait", {"url": self.approve_url, "open": 0,
                                           "detail": "nothing is waiting for the owner in this run"})
            self._go("done")
            self.finished = time.time()
        except _Stopped:
            self.finished = time.time()
        except Exception as e:  # keep the console alive and say what happened
            self.error = f"{type(e).__name__}: {e}"
            self.note("fallback", {"from": "demo director", "reason": self.error[:300]})
            self.finished = time.time()


class _Stopped(Exception):
    pass
