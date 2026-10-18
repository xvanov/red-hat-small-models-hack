"""Shared paths, settings and small helpers for the personal-Messenger web channel.

Everything that holds real conversation text lives under runs/live/messenger_web/ (gitignored, see
`assert_private`). Settings come from the process env or the repo .env:

  LIVE_ALLOW_MESSENGER_NAMES     comma-separated display names whose threads may be auto-sent (default: none)
  MESSENGER_WEB_PROFILE          browser profile dir (default channels/.profiles/messenger_web, gitignored)
  MESSENGER_WEB_POLL_SECONDS     inbox poll interval, floor 20 (default 30)
  MESSENGER_WEB_MAX_THREADS      threads read from the top of the inbox (default 10)
  MESSENGER_WEB_OPENS_PER_POLL   changed threads opened per poll (default 3)
  MESSENGER_WEB_MAX_SENDS_HOUR   worker-side send cap (default 10)
  MESSENGER_WEB_HEADLESS         "1" hides the browser window (default: visible)
  MESSENGER_WEB_SEND_WAIT        seconds the adapter waits for the worker to confirm a send (default 120)
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

PKG = Path(__file__).resolve().parent
REPO = PKG.parents[1]
CHANNEL = "messenger_personal"
SELECTORS_PATH = PKG / "selectors.json"
EXTRACT_JS = (PKG / "extract.js").read_text()


def _repo_env() -> dict:
    try:
        from dotenv import dotenv_values
        return {k: v for k, v in dotenv_values(REPO / ".env").items() if v is not None}
    except Exception:
        return {}


def env(name: str, default: str | None = None) -> str | None:
    if name in os.environ:
        return os.environ[name]
    return _repo_env().get(name, default)


def env_num(name: str, default: float, floor: float | None = None) -> float:
    try:
        v = float(env(name) or default)
    except ValueError:
        v = default
    return max(v, floor) if floor is not None else v


def data_dir() -> Path:
    base = Path(env("LIVE_DIR") or (REPO / "runs" / "live"))
    return base / "messenger_web"


def profile_dir() -> Path:
    return Path(env("MESSENGER_WEB_PROFILE") or (REPO / "channels" / ".profiles" / "messenger_web"))


def selectors() -> dict:
    return json.loads(SELECTORS_PATH.read_text())


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def norm_name(s: str | None) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip().casefold()


def allowed_names() -> set[str]:
    return {norm_name(x) for x in (env("LIVE_ALLOW_MESSENGER_NAMES") or "").split(",") if x.strip()}


def name_allowed(name: str | None) -> bool:
    return bool(name) and norm_name(name) in allowed_names()


def norm_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def message_ids(thread_id: str, messages: list[dict]) -> list[str]:
    """Stable ids for parsed messages: hash of thread, direction, text and the occurrence number of that
    same (direction, text) pair in the thread, so a repeated "ok" gets distinct ids."""
    counts: dict = {}
    out = []
    for m in messages:
        key = (m["dir"], norm_text(m["text"]))
        counts[key] = counts.get(key, 0) + 1
        h = hashlib.sha256(f"{thread_id}|{key[0]}|{key[1]}|{counts[key]}".encode()).hexdigest()[:16]
        out.append(f"mw:{thread_id}:{h}")
    return out


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp{os.getpid()}")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1))
    os.replace(tmp, path)


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def assert_private(path: Path) -> None:
    """Refuse to write real conversation text anywhere git would pick it up."""
    path.mkdir(parents=True, exist_ok=True)
    probe = path / ".probe"
    try:
        r = subprocess.run(["git", "-C", str(REPO), "check-ignore", "-q", str(probe)], capture_output=True)
        ok = r.returncode == 0
    except FileNotFoundError:  # no git: only accept the default location
        ok = str(path).startswith(str(REPO / "runs"))
    if not ok and REPO in path.resolve().parents:
        raise RuntimeError(f"{path} is not gitignored; refusing to store conversation text there")


def heartbeat_age(status: dict | None) -> float:
    if not status or not status.get("heartbeat_epoch"):
        return 1e9
    return time.time() - float(status["heartbeat_epoch"])
