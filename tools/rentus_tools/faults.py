"""Fault injection (contracts/tools.md section 5).

`world.faults` is a list of `{tool, kind, times, after?, match?}`:
- `tool`: tool name, or "*" for any tool.
- `kind`: timeout | rate_limited | malformed | login_required | page_changed | upstream_error | not_found.
- `times`: how many matching calls fail before the tool recovers (default 1).
- `after`: optional; let this many matching calls succeed first (default 0).
- `match`: optional extension; an args subset, e.g. {"channel": "marketplace"}, that a call must contain.
- `field` (malformed only, optional extension): corrupt this key wherever it appears in `data` (for example
  `"rent"` in get_room or every room of list_rooms) instead of the default first-key corruption.
  `field_mode`: "wrong_type" (default, e.g. 875 -> "N/A") or "drop" (the key is missing).

Counters are kept on the fault dict itself (`_seen`, `_fired`), so they are part of world state and
show up in snapshots. `malformed` lets the tool run (side effects happen) and then corrupts `data`.
"""
from __future__ import annotations

import copy

from .errors import ToolError

KINDS = ("timeout", "rate_limited", "malformed", "login_required", "page_changed", "upstream_error", "not_found")

_ERRORS = {
    "timeout": ("TIMEOUT", "{tool} timed out after 30s", True, "retry once; if it keeps failing, try another route or escalate"),
    "rate_limited": ("RATE_LIMITED", "{tool} is rate limited (429)", True, "wait and retry later; do not hammer"),
    "login_required": ("LOGIN_REQUIRED", "{tool}: the session expired and the channel requires login", False,
                       "ask the owner to log in, or use another channel"),
    "page_changed": ("PAGE_CHANGED", "{tool}: the page layout changed and the automation could not find its fields", False,
                     "the channel adapter needs repair; use another channel meanwhile and tell the owner"),
    "upstream_error": ("UPSTREAM_ERROR", "{tool}: upstream service returned 502", True, "retry once, then fall back"),
    "not_found": ("NOT_FOUND", "{tool}: the requested resource was not found upstream", False,
                  "check the id with a list/read tool"),
}


def _matches(f: dict, tool: str, args: dict) -> bool:
    if f.get("tool") not in (tool, "*"):
        return False
    m = f.get("match") or {}
    return all(args.get(k) == v for k, v in m.items())


def pick_fault(world, tool: str, args: dict) -> dict | None:
    """Advance counters and return the fault that fires for this call, if any."""
    for f in world.faults:
        if not _matches(f, tool, args):
            continue
        if f.get("kind") not in KINDS:
            continue
        f["_seen"] = f.get("_seen", 0) + 1
        if f["_seen"] <= f.get("after", 0):
            continue
        if f.get("_fired", 0) >= f.get("times", 1):
            continue
        f["_fired"] = f.get("_fired", 0) + 1
        return f
    return None


def error_for(kind: str, tool: str) -> ToolError:
    code, msg, retryable, hint = _ERRORS[kind]
    return ToolError(code, msg.format(tool=tool), hint=hint, retryable=retryable)


def _wrong_type(v):
    if isinstance(v, bool):
        return "yes"
    if isinstance(v, (int, float)):
        return "N/A"
    if isinstance(v, str):
        return 0
    if isinstance(v, list):
        return "[]"
    if isinstance(v, dict):
        return []
    return "corrupt"


def corrupt_field(data, field: str, mode: str = "wrong_type"):
    """Targeted corruption: every `field` key anywhere in `data` is dropped or given a wrong type."""
    data = copy.deepcopy(data)

    def walk(x):
        if isinstance(x, dict):
            if field in x:
                if mode == "drop":
                    del x[field]
                else:
                    x[field] = _wrong_type(x[field])
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(data)
    return data


def corrupt(data):
    """Deterministic corruption: drop the first key and give the next one a wrong type,
    recursing into the main payload when the top level is a single wrapper key."""
    data = copy.deepcopy(data)
    if isinstance(data, list):
        return [corrupt(x) if isinstance(x, dict) else x for x in data] if data else "[]"
    if not isinstance(data, dict) or not data:
        return {"error": None, "data": "<html>502</html>"}
    keys = sorted(data)
    if len(keys) == 1 and isinstance(data[keys[0]], (dict, list)) and data[keys[0]]:
        return {keys[0]: corrupt(data[keys[0]])}
    del data[keys[0]]
    if len(keys) > 1:
        data[keys[1]] = _wrong_type(data[keys[1]])
    return data
