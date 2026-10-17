"""Event sink (contracts/tools.md section 6): append-only JSONL or an in-memory list."""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

EVENT_TYPES = {"tool_call", "tool_result", "model_message", "verifier", "retry", "fallback", "escalation",
               "owner_message", "renter_message", "score"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class EventSink:
    """Collects events. `path` (e.g. runs/<run_id>/events.jsonl) appends to a file; `events` always
    keeps an in-memory copy; `subscribers` are called with each event (the console's SSE hook).
    `clock` returns the ts string; pass `lambda: world.clock['now']` for reproducible files."""

    def __init__(self, run_id: str = "r_local", path: str | Path | None = None,
                 clock: Callable[[], str] | None = None, keep: bool = True):
        self.run_id = run_id
        self.path = Path(path) if path else None
        self.clock = clock or _utc_now
        self.keep = keep
        self.events: list[dict] = []
        self.subscribers: list[Callable[[dict], None]] = []
        self.seq = 0
        self._lock = threading.Lock()
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    @classmethod
    def for_run(cls, run_id: str, runs_dir: str | Path = "runs", **kw) -> "EventSink":
        return cls(run_id=run_id, path=Path(runs_dir) / run_id / "events.jsonl", **kw)

    def emit(self, type: str, actor: str, data: dict) -> dict:
        if type not in EVENT_TYPES:
            raise ValueError(f"unknown event type {type!r}")
        with self._lock:
            self.seq += 1
            ev = {"ts": self.clock(), "run_id": self.run_id, "seq": self.seq, "type": type, "actor": actor, "data": data}
            if self.keep:
                self.events.append(ev)
            if self.path:
                with self.path.open("a") as fh:
                    fh.write(json.dumps(ev, ensure_ascii=False, default=str) + "\n")
        for fn in list(self.subscribers):
            try:
                fn(ev)
            except Exception:  # a broken subscriber must not break a tool call
                pass
        return ev
