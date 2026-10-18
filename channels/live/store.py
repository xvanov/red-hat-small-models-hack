"""On-disk store for live conversations, shared by the daemon and the console process.

Layout under live_dir() (runs/live/, gitignored; it holds real conversation text and must never be committed):
  threads/<id>.json     one thread: contact, messages, trace, gate/stage, operator world + model history
  approvals.json        approval items (pending / approved / edited / denied / failed)
  sends.jsonl           one row per real outbound attempt (no message text): rate cap + audit
  state.json            poll cursors and seen provider ids
  STOP                  kill switch: while it exists nothing is sent
  .lock                 fcntl lock file; every read-modify-write holds it
"""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import config

THREAD_ID_RE = re.compile(r"^[a-z_]+:[\w:]+$")
CHANNEL_WORLD = {"sms": "sms", "email": "email", "messenger": "facebook_page"}


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def short_hash(s: str) -> str:
    return hashlib.sha256((s or "").strip().lower().encode()).hexdigest()[:10]


def make_thread_id(channel: str, contact: str, line_last4: str | None = None) -> str:
    if channel == "sms":
        return f"sms:{line_last4}:{short_hash(config.normalize_phone(contact))}"
    return f"{channel}:{short_hash(contact)}"


class Store:
    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root else config.live_dir()

    # ---------------------------------------------------------------- plumbing
    @property
    def threads_dir(self) -> Path:
        return self.root / "threads"

    @contextlib.contextmanager
    def locked(self):
        self.root.mkdir(parents=True, exist_ok=True)
        with open(self.root / ".lock", "a+") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)

    def _read(self, p: Path, default):
        try:
            return json.loads(p.read_text())
        except (OSError, ValueError):
            return default

    def _write(self, p: Path, obj) -> None:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(obj, ensure_ascii=False, default=str, indent=1))
        os.replace(tmp, p)

    def _tpath(self, thread_id: str) -> Path:
        if not isinstance(thread_id, str) or not THREAD_ID_RE.match(thread_id):
            raise ValueError("invalid thread id")
        return self.threads_dir / (thread_id.replace(":", "_") + ".json")

    # ---------------------------------------------------------------- threads
    def get_thread(self, thread_id: str) -> dict | None:
        try:
            p = self._tpath(thread_id)
        except ValueError:
            return None
        return self._read(p, None)

    def save_thread(self, t: dict) -> None:
        t["updated"] = now_iso()
        self._write(self._tpath(t["thread_id"]), t)

    def all_threads(self) -> list[dict]:
        if not self.threads_dir.exists():
            return []
        out = [self._read(p, None) for p in self.threads_dir.glob("*.json")]
        return [t for t in out if t]

    def ensure_thread(self, channel: str, contact: str, *, line: str | None = None, line_last4: str | None = None,
                      renter_name: str | None = None) -> dict:
        """Get or create (caller holds the lock). An archived thread is never reused: the contact's next message
        starts a new thread (<id>:2, <id>:3, ...) with fresh history."""
        base = make_thread_id(channel, contact, line_last4)
        tid, n = base, 1
        while (old := self.get_thread(tid)) is not None and old.get("archived"):
            n += 1
            tid = f"{base}:{n}"
        t = self.get_thread(tid)
        if t is None:
            if channel == "sms":
                disp = config.mask_phone(contact)
            elif channel == "email":
                disp = config.mask_email(contact)
            else:
                disp = (renter_name or "Messenger user").split()[0]
            from . import registry
            t = {"thread_id": tid, "channel": channel, "line": line, "contact": contact, "contact_display": disp,
                 "renter_name": renter_name or "", "messages": [], "trace": [], "unread": 0, "needs_owner": False,
                 "stage": "inquiry", "gate": {k: "missing" for k in ("lease", "move_in", "phone", "reason", "people")},
                 "world": None, "history": None, "owner_pending": [], "email": {}, "created": now_iso(),
                 "world_channel": registry.world_channel(channel)}
            from . import roles
            t["role"] = roles.role_for(channel)
            t["stage"] = roles.initial_stage(t["role"])
            self.save_thread(t)
        elif renter_name and not t.get("renter_name"):
            t["renter_name"] = renter_name
        return t

    def add_message(self, t: dict, direction: str, text: str, status: str, *, ext_id: str | None = None,
                    ts: str | None = None, origin: str | None = None) -> dict:
        m = {"id": f"m_{uuid.uuid4().hex[:10]}", "direction": direction, "text": text, "ts": ts or now_iso(),
             "status": status, "channel": t["channel"]}
        if ext_id:
            m["ext_id"] = ext_id
        if origin:
            m["origin"] = origin
        t["messages"].append(m)
        if direction == "in":
            t["unread"] = int(t.get("unread", 0)) + 1
        return m

    # ---------------------------------------------------------------- approvals
    def approvals(self) -> list[dict]:
        return self._read(self.root / "approvals.json", [])

    def save_approvals(self, items: list[dict]) -> None:
        self._write(self.root / "approvals.json", items)

    def add_approval(self, thread_id: str, reason: str, draft_text: str, *, message_id: str | None = None,
                     kind: str = "draft") -> dict:
        items = self.approvals()
        a = {"id": f"ap_{uuid.uuid4().hex[:8]}", "thread_id": thread_id, "reason": reason,
             "draft_text": draft_text or "", "created": now_iso(), "status": "pending", "kind": kind,
             "message_id": message_id}
        items.append(a)
        self.save_approvals(items)
        return a

    # ---------------------------------------------------------------- sends (rate cap, audit; no text)
    def log_send(self, row: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        with (self.root / "sends.jsonl").open("a") as fh:
            fh.write(json.dumps({"at": time.time(), **row}, default=str) + "\n")

    def sends_last_hour(self, now: float | None = None) -> int:
        now = now or time.time()
        p = self.root / "sends.jsonl"
        if not p.exists():
            return 0
        n = 0
        for line in p.read_text().splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("attempted") and now - float(r.get("at", 0)) < 3600:
                n += 1
        return n

    def sends_last_day(self, thread_id: str, now: float | None = None) -> int:
        now = now or time.time()
        p = self.root / "sends.jsonl"
        if not p.exists():
            return 0
        n = 0
        for line in p.read_text().splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("attempted") and r.get("thread_id") == thread_id and now - float(r.get("at", 0)) < 86400:
                n += 1
        return n

    # ---------------------------------------------------------------- poll state
    def state(self) -> dict:
        st = self._read(self.root / "state.json", {})
        if "started" not in st:
            # First run: only messages from the last 30 minutes count, so old texts are not answered.
            st["started"] = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat(timespec="seconds")
            st.setdefault("seen", {})
            self.save_state(st)
        return st

    def save_state(self, st: dict) -> None:
        self._write(self.root / "state.json", st)
