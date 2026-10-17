"""Event log writer and tailer for runs/<run_id>/events.jsonl (contract section 6)."""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class EventLog:
    """Append-only JSONL writer. Thread-safe; seq is monotonic per file."""

    def __init__(self, path: Path, run_id: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id
        self._lock = threading.Lock()
        self._seq = 0
        if self.path.exists():
            self._seq = sum(1 for _ in self.path.open())

    def emit(self, type_: str, actor: str, data: dict | None = None) -> dict:
        with self._lock:
            self._seq += 1
            ev = {"ts": utc_now(), "run_id": self.run_id, "seq": self._seq,
                  "type": type_, "actor": actor, "data": data or {}}
            with self.path.open("a") as f:
                f.write(json.dumps(ev, ensure_ascii=False) + "\n")
            return ev


class Tail:
    """Incremental reader of a JSONL file that may not exist yet or be mid-write."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.offset = 0
        self._partial = ""

    def read_new(self) -> list[dict]:
        if not self.path.exists():
            return []
        with self.path.open("r") as f:
            f.seek(self.offset)
            chunk = f.read()
            self.offset = f.tell()
        if not chunk:
            return []
        text = self._partial + chunk
        lines = text.split("\n")
        self._partial = lines.pop()  # incomplete last line (or "")
        out = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                out.append({"type": "console_error", "actor": "system",
                            "data": {"message": "unparseable event line", "line": line[:200]}})
        return out
