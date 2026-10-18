"""Feature probes: does the system have the tool or state a checklist item needs?

An item whose `requires` lists a feature that probes False is BLOCKED (reported as "blocked: needs <what>"),
not failed. Probes look at behavior on a scratch World, not at names alone where that is possible, so a
feature counts as present whatever lane 2 calls it, as long as it works. Re-run the suite after new tools
land and blocked items unblock on their own.
"""
from __future__ import annotations

import copy
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
GYM = HERE.parent
for p in (GYM, GYM.parent / "tools", GYM.parent / "operator"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from rentus_env.backend import Backend  # noqa: E402

_SCRATCH = {"clock": {"now": "2026-10-20T10:00:00"},
            "threads": [{"thread_id": "t_probe_a", "channel": "marketplace", "renter_name": "Probe A", "language": "en",
                         "room_id": "R012", "messages": [{"id": "pa1", "from": "renter", "text": "hi", "ts": "2026-10-20T09:00:00"}]},
                        {"thread_id": "t_probe_b", "channel": "email", "renter_name": "Probe A", "language": "en",
                         "messages": [{"id": "pb1", "from": "renter", "text": "hello", "ts": "2026-10-20T09:00:00"}]}]}


def _names(be: Backend) -> list[str]:
    names = set(be.tool_names())
    try:  # owner-only tools may be registered without being exposed to the model
        import rentus_tools.core as core
        for attr in ("REGISTRY", "_REGISTRY", "TOOLS_BY_NAME", "_TOOLS"):
            reg = getattr(core, attr, None)
            if isinstance(reg, dict):
                names |= set(reg)
    except Exception:  # noqa: BLE001
        pass
    return sorted(names)


def _upsert_ok(be: Backend, fields: dict) -> bool:
    w = be.new_world(copy.deepcopy(_SCRATCH))
    env = be.call(w, "upsert_renter", {"thread_id": "t_probe_a", "fields": fields})
    return bool(env.get("ok"))


def _tool_like(names, pattern) -> list[str]:
    return [n for n in names if re.search(pattern, n)]


def probe_all(be: Backend | None = None) -> dict[str, dict]:
    be = be or Backend()
    names = _names(be)
    out: dict[str, dict] = {}

    def put(key, ok, need, how):
        out[key] = {"ok": bool(ok), "need": need, "how": how}

    park = _tool_like(names, r"park")
    put("reconnect_at", bool(park) or _upsert_ok(be, {"reconnect_at": "2026-11-01", "paused_reason": "probe"}),
        "reconnect_at / paused_reason on the register (park_prospect)",
        f"tool {park}" if park else "upsert_renter fields.reconnect_at")
    put("proxy", _upsert_ok(be, {"proxy": {"is_proxy": True, "actual_seeker_confirmed": False}}) or bool(_tool_like(names, r"demand")) and
        _demand_accepts(be, names, "proxy"), "register proxy field {is_proxy, actual_seeker_confirmed}", "upsert_renter fields.proxy")
    put("sourcing", _upsert_ok(be, {"sourcing": {"opened_at": "2026-10-20", "due_at": "2026-10-23"}}) or
        bool(_tool_like(names, r"sourc")), "sourcing task {opened_at, due_at} on the register", "upsert_renter fields.sourcing or a sourcing tool")
    put("dedupe", _dedupe(be), "cross-channel merge by phone/email with sources[]", "two threads, same phone -> one row")
    roll = _tool_like(names, r"rollup|supply_signal|cluster")
    put("rollup", bool(roll), "demand_rollup tool (clusters, WATCH, SUPPLY SIGNAL)", f"tool {roll or 'none'}")
    put("two_occupant", _two_occ(), "2-occupant rent/deposit/utilities on room records, allowed in messages",
        "allowed_figures accepts a 2-occupant field")
    put("video", _video(be), "walkthrough video asset on rooms + video attachment + video_sent state",
        "get_listing_media returns a video")
    put("event_mode", _event_mode(be), "showing mode (in_person / video_call / hybrid) on calendar events",
        "propose_showing takes mode")
    sched = _tool_like(names, r"tick|followup|follow_up|cadence|scheduler")
    put("scheduler", bool(sched), "follow-up state on the register + a sandbox clock tick that emits due check-ins",
        f"tool {sched or 'none'}")
    put("quiet_window", False, "clock-driven quiet windows in the sandbox (120 s small-talk wait, cancel on answer)",
        "no sandbox mechanism; live driver only")
    alert = _tool_like(names, r"alert|watchdog")
    put("unanswered_alert", bool(alert), "10-minute unanswered alert (clock + alert event)", f"tool {alert or 'none'}")
    return out


def _demand_accepts(be, names, key) -> bool:
    return False   # unknown demand tool shapes are checked by hand when they land


def _dedupe(be: Backend) -> bool:
    w = be.new_world(copy.deepcopy(_SCRATCH))
    a = be.call(w, "upsert_renter", {"thread_id": "t_probe_a", "fields": {"phone": "9195550101"}})
    b = be.call(w, "upsert_renter", {"thread_id": "t_probe_b", "fields": {"phone": "9195550101"}})
    if not (a.get("ok") and b.get("ok")):
        return False
    reg = be.coll(w, "register")
    return len(reg) == 1 and len(reg[0].get("thread_ids") or []) == 2


def _two_occ() -> bool:
    try:
        from rentus_tools.impl.listings import allowed_figures
    except Exception:  # noqa: BLE001
        return False
    room = {"rent": 800, "deposit": 800, "utilities": "$75 flat"}
    for k in ("rent_two_occupants", "two_occupant_rent", "rent_2", "rent_couple", "extra_occupant_rent"):
        if 951.0 in allowed_figures({**room, k: 951}):
            return True
    return any(951.0 in allowed_figures({**room, "two_occupants": {"rent": 951}}) for _ in [0])


def _video(be: Backend) -> bool:
    w = be.new_world({})
    env = be.call(w, "get_listing_media", {"room_id": "R012"})
    return bool(env.get("ok")) and any(k in (env.get("data") or {}) for k in ("video", "videos"))


def _event_mode(be: Backend) -> bool:
    for t in be.TOOLS:
        f = t.get("function", t)
        if f.get("name") == "propose_showing":
            return "mode" in (f.get("parameters") or {}).get("properties", {})
    return False


if __name__ == "__main__":
    for k, v in probe_all().items():
        print(f"{k:18s} {'yes' if v['ok'] else 'NO ':3s}  {v['need']}  ({v['how']})")
