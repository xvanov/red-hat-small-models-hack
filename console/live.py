"""Bridge to the live channels (channels/live/api.py, owned by the live-channels workstream).

Every call is guarded: if the module is missing, fails to import, raises or hangs, the console gets a clean
"unavailable" answer instead of an error page. `CONSOLE_LIVE_MODULE` swaps the module (tests use a fake).
"""
from __future__ import annotations

import concurrent.futures as cf
import importlib
import os
import time

_POOL = cf.ThreadPoolExecutor(max_workers=4, thread_name_prefix="live")
_STATE: dict = {"mod": None, "error": None, "tried": 0.0}
CALL_TIMEOUT_S = float(os.environ.get("CONSOLE_LIVE_TIMEOUT_S") or 8)
SEND_TIMEOUT_S = float(os.environ.get("CONSOLE_LIVE_SEND_TIMEOUT_S") or 40)  # decide / reply actually deliver
GATE = ["lease", "move_in", "phone", "reason", "people"]


class Unavailable(Exception):
    pass


def module_name() -> str:
    return os.environ.get("CONSOLE_LIVE_MODULE") or "channels.live.api"


def _api():
    if _STATE["mod"] is not None:
        return _STATE["mod"]
    if time.monotonic() - _STATE["tried"] < 5 and _STATE["error"]:
        raise Unavailable(_STATE["error"])
    _STATE["tried"] = time.monotonic()
    try:
        _STATE["mod"] = importlib.import_module(module_name())
        _STATE["error"] = None
        return _STATE["mod"]
    except Exception as e:  # not built yet, or a dependency is missing
        _STATE["error"] = f"{type(e).__name__}: {e}"
        raise Unavailable(_STATE["error"])


def call(fn: str, *args, _timeout: float | None = None, **kw):
    mod = _api()
    f = getattr(mod, fn, None)
    if f is None:
        raise Unavailable(f"{module_name()}.{fn} is missing")
    fut = _POOL.submit(f, *args, **kw)
    try:
        return fut.result(timeout=_timeout or CALL_TIMEOUT_S)
    except cf.TimeoutError:
        raise Unavailable(f"{fn} did not answer within {_timeout or CALL_TIMEOUT_S:.0f}s; it may still complete, check the thread")


def has(fn: str) -> bool:
    try:
        return callable(getattr(_api(), fn, None))
    except Unavailable:
        return False


def last_error() -> str | None:
    return _STATE["error"]


def _gate(g) -> dict:
    g = g if isinstance(g, dict) else {}
    out = {}
    for k in GATE:
        v = g.get(k, g.get("occupants") if k == "people" else None)
        out[k] = v if v in ("exact", "vague", "missing") else "missing"
    return out


def norm_thread(t: dict) -> dict:
    t = dict(t or {})
    t["gate"] = _gate(t.get("gate"))
    t.setdefault("channel", "unknown")
    t["contact_display"] = t.get("contact_display") or t.get("renter_name") or t.get("thread_id")
    t["stage"] = t.get("stage") or "inquiry"
    t["unread"] = bool(t.get("unread"))
    t["needs_owner"] = bool(t.get("needs_owner"))
    return t
