"""Provider for channels/live: the owner's PERSONAL Facebook Messenger (Marketplace inquiries), via the web.

Same shape as the providers in channels/live/providers.py:
  channel = "messenger_personal"
  display, connected() -> (bool, str)
  poll(allow, since, seen) -> [{"channel","contact","text","ext_id","ts","line","line_last4","renter_name","meta"}]
  send(contact, text) -> {"ok","provider_id","status","error_code","error"}      (never raises)

`contact` is the Facebook thread id (from the /messages/t/<id>/ URL). This class does no browser work: the
browser worker (`python -m channels.messenger_web serve`) owns the logged-in profile, writes what it reads to
runs/live/messenger_web/threads.json and executes send requests dropped in runs/live/messenger_web/outbox/.

Safety: every thread is polled (each operator reply becomes a draft that needs the owner's approval);
`allows_autosend(thread_id)` is True only for threads whose participant display name is in
LIVE_ALLOW_MESSENGER_NAMES. outbound.deliver() must use it as this channel's allowlist gate. send() trusts that
gate (it is only called for an allowlisted thread or an owner-approved draft) and adds its own checks in the
worker (kill switch, rate cap, exact-text check, verify after send).
"""
from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path

from . import common as C
from .worker import new_request_id, unanswered_tail

CHANNEL = C.CHANNEL


def _threads(root: Path) -> dict:
    return C.read_json(root / "threads.json", {}) or {}


def thread_name(thread_id: str, root: Path | None = None) -> str | None:
    t = _threads(Path(root) if root else C.data_dir()).get(str(thread_id))
    return t.get("name") if t else None


def allows_autosend(thread_id: str, root: Path | None = None) -> bool:
    """The allowlist gate for this channel: the thread's participant name is in LIVE_ALLOW_MESSENGER_NAMES."""
    return C.name_allowed(thread_name(thread_id, root))


class MessengerPersonal:
    channel = CHANNEL

    def __init__(self, root: Path | None = None, *, send_wait: float | None = None, sleep=time.sleep):
        self.root = Path(root) if root else C.data_dir()
        self.send_wait = send_wait if send_wait is not None else C.env_num("MESSENGER_WEB_SEND_WAIT", 120)
        self.sleep = sleep

    @property
    def display(self) -> str:
        return "Personal Messenger (facebook.com)"

    def status(self) -> dict:
        return C.read_json(self.root / "status.json", {}) or {}

    def connected(self) -> tuple[bool, str]:
        st = self.status()
        age = C.heartbeat_age(st)
        if not st or age > 120:
            return False, "browser worker not running: channels/.venv/bin/python -m channels.messenger_web serve"
        if st.get("state") == "login_required":
            return False, "login required: channels/.venv/bin/python -m channels.messenger_web login"
        if st.get("state") != "running":
            return False, f"worker {st.get('state')}: {st.get('detail', '')}"[:200]
        n = len(C.allowed_names())
        return True, (f"{st.get('threads', 0)} threads tracked; last poll {st.get('last_poll')}; "
                      f"auto-send names: {n} (everyone else: owner approval)")

    def poll(self, allow=None, since: datetime | None = None, seen: set | None = None) -> list[dict]:
        """Unanswered inbound messages (after the thread's last outbound one), every thread, not yet seen."""
        seen = seen or set()
        out = []
        for tid, t in _threads(self.root).items():
            msgs = t.get("messages") or []
            for m in unanswered_tail(msgs):
                if m["ext_id"] in seen or not C.norm_text(m.get("text")):
                    continue
                out.append({"channel": CHANNEL, "contact": tid, "text": m["text"], "ext_id": m["ext_id"],
                            "ts": m.get("first_seen"), "line": "personal", "line_last4": None,
                            "renter_name": t.get("name"),
                            "meta": {"listing_title": t.get("listing_title"), "marketplace": t.get("marketplace"),
                                     "thread_url": t.get("url"), "autosend": C.name_allowed(t.get("name"))}})
        return sorted(out, key=lambda x: x["ts"] or "")

    def send(self, contact: str, text: str) -> dict:
        def fail(err, code):
            return {"ok": False, "provider_id": None, "status": "failed", "error_code": code, "error": err}

        ok, detail = self.connected()
        if not ok:
            return fail(detail, "worker_unavailable")
        if str(contact) not in _threads(self.root):
            return fail("unknown Messenger thread", "unknown_thread")
        rid = new_request_id()
        box = self.root / "outbox"
        box.mkdir(parents=True, exist_ok=True)
        pending = box / f"{rid}.pending.json"
        C.write_json(pending, {"id": rid, "thread_id": str(contact), "text": text, "created": C.now_iso()})
        done = box / f"{rid}.done.json"
        deadline = time.time() + self.send_wait
        while time.time() < deadline:
            if done.exists():
                res = (C.read_json(done, {}) or {}).get("result") or fail("worker wrote no result", "no_result")
                return res
            self.sleep(0.5)
        # timed out: cancel if the worker has not claimed it, so it can never go out later unseen
        try:
            os.rename(pending, box / f"{rid}.cancelled.json")
            return fail(f"worker did not pick up the send within {int(self.send_wait)} s; cancelled", "timeout")
        except FileNotFoundError:
            pass  # claimed: the worker is typing it now; wait for the outcome
        end = time.time() + 90
        while time.time() < end:
            if done.exists():
                return (C.read_json(done, {}) or {}).get("result") or fail("worker wrote no result", "no_result")
            self.sleep(0.5)
        return fail("send in progress but unconfirmed; check the thread before retrying", "unconfirmed")
