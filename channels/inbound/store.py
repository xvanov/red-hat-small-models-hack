"""Local store for inbound channels (email, SMS): threads plus a drafts outbox per channel.

Nothing in here sends anything. A reply is written to a JSONL outbox with the reason it is a draft;
the owner sends it himself (from his own inbox or phone) if he wants to.

Layout (default channels/.inbox/, gitignored; override with CHANNELS_INBOX_DIR):
  threads.json          {thread_id: thread}
  email_drafts.jsonl    one draft per line
  sms_outbox.jsonl      one draft per line
"""
from __future__ import annotations

import hashlib
import re
import json
import os
import threading
import time
from pathlib import Path

DEFAULT_DIR = Path(__file__).resolve().parents[1] / ".inbox"
OUTBOX_FILES = {"email": "email_drafts.jsonl", "sms": "sms_outbox.jsonl"}
CHANNELS = tuple(OUTBOX_FILES)
_LOCK = threading.Lock()


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def thread_key(channel: str, *parts: str) -> str:
    """Deterministic thread id: the same renter on the same platform lands in the same thread."""
    h = hashlib.sha1("|".join([channel, *[(p or "").strip().lower() for p in parts]]).encode()).hexdigest()[:10]
    return f"{channel}:{h}"


_ES = re.compile(r"[¿¡ñ]|\b(hola|gracias|cuarto|habitaci[oó]n|disponible|renta|buscamos|busco|quiero|"
                 r"puedo|somos|usted|para|mudarme|mes|semana)\b", re.I)


def guess_language(text: str) -> str:
    """'es' when a message reads as Spanish (two or more Spanish markers), else 'en'."""
    return "es" if len(_ES.findall(text or "")) >= 2 else "en"


class ChannelStore:
    def __init__(self, root: str | Path | None = None):
        self.root = Path(root or os.environ.get("CHANNELS_INBOX_DIR") or DEFAULT_DIR)

    # ------------------------------------------------------------ threads
    @property
    def threads_path(self) -> Path:
        return self.root / "threads.json"

    def threads(self) -> dict[str, dict]:
        try:
            return json.loads(self.threads_path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save_threads(self, threads: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.threads_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(threads, indent=2, ensure_ascii=False))
        tmp.replace(self.threads_path)

    def get_thread(self, thread_id: str) -> dict | None:
        return self.threads().get(thread_id)

    def list_threads(self, channel: str | None = None) -> list[dict]:
        return [t for t in self.threads().values() if not channel or t["channel"] == channel]

    def add_message(self, *, channel: str, thread_id: str, text: str, sender: str = "renter",
                    renter_name: str | None = None, ts: str | None = None, external_id: str | None = None,
                    meta: dict | None = None) -> tuple[dict, bool]:
        """Append a message to a thread (created if new). Returns (thread, added); a message whose
        external_id is already in the thread is skipped, so re-polling an inbox is idempotent."""
        assert channel in CHANNELS, channel
        assert sender in ("renter", "operator")
        with _LOCK:
            threads = self.threads()
            t = threads.get(thread_id)
            if t is None:
                t = {"thread_id": thread_id, "channel": channel, "renter_name": renter_name or "",
                     "language": guess_language(text) if sender == "renter" else "en", "messages": [],
                     "created_at": _now()}
                threads[thread_id] = t
            if renter_name and not t.get("renter_name"):
                t["renter_name"] = renter_name
            for k, v in (meta or {}).items():
                if v not in (None, "", [], {}):
                    t[k] = v
            if external_id and any(m.get("external_id") == external_id for m in t["messages"]):
                return t, False
            msg = {"id": f"{thread_id}-m{len(t['messages']) + 1}", "from": sender, "text": text,
                   "attachments": [], "ts": ts or _now()}
            if external_id:
                msg["external_id"] = external_id
            t["messages"].append(msg)
            t["updated_at"] = _now()
            self._save_threads(threads)
            return t, True

    # ------------------------------------------------------------ drafts (never sent)
    def outbox_path(self, channel: str) -> Path:
        return self.root / OUTBOX_FILES[channel]

    def save_draft(self, *, channel: str, thread_id: str, text: str, reason: str, to: str | None = None,
                   reply_via: str | None = None, extra: dict | None = None) -> dict:
        assert channel in CHANNELS, channel
        with _LOCK:
            n = len(self.drafts(channel)) + 1
            draft = {"draft_id": f"{channel}-draft-{n}", "channel": channel, "thread_id": thread_id, "to": to,
                     "reply_via": reply_via, "text": text, "reason": reason, "status": "draft_saved",
                     "sent": False, "created_at": _now(), **(extra or {})}
            self.root.mkdir(parents=True, exist_ok=True)
            with self.outbox_path(channel).open("a") as f:
                f.write(json.dumps(draft, ensure_ascii=False) + "\n")
            return draft

    def drafts(self, channel: str | None = None) -> list[dict]:
        out: list[dict] = []
        for ch in ([channel] if channel else CHANNELS):
            p = self.outbox_path(ch)
            if p.exists():
                out += [json.loads(line) for line in p.read_text().splitlines() if line.strip()]
        return out
