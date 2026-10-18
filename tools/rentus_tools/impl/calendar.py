"""Calendar tools: find_showing_slots, propose_showing."""
from __future__ import annotations

import copy
from datetime import datetime, time, timedelta

from ..core import tool
from ..errors import ToolError
from ._util import need, parse_date, parse_dt
from .register import _floor, gate_missing

MAX_SLOTS = 24


def _hours(world):
    h = world.policy.get("showing_hours") or {}
    sh, sm = map(int, h.get("start", "10:00").split(":"))
    eh, em = map(int, h.get("end", "18:00").split(":"))
    return h.get("days", list(range(7))), time(sh, sm), time(eh, em), int(h.get("slot_minutes", 30))


def _busy(world, room_id: str | None = None):
    # D29: never two showings at the same time, for ANY room (the owner shows them all himself).
    return [(datetime.fromisoformat(e["start"]), datetime.fromisoformat(e["end"])) for e in world.calendar
            if e.get("status") in ("proposed", "confirmed") and (e.get("room_id") or e.get("renter_id"))]


def _blocks(world, room_id: str):
    return [(datetime.fromisoformat(e["start"]), datetime.fromisoformat(e["end"])) for e in world.calendar
            if e.get("status") == "available_block" and e.get("room_id") in (None, room_id)]


def _free(start, end, busy) -> bool:
    return all(end <= b0 or start >= b1 for b0, b1 in busy)


@tool("find_showing_slots")
def find_showing_slots(world, room_id: str, date_from: str, date_to: str):
    need(world, "rooms", room_id, "room", "list_rooms")
    d0, d1 = parse_date(date_from, "date_from"), parse_date(date_to, "date_to")
    if d1 < d0:
        raise ToolError("INVALID_ARGS", "date_to is before date_from")
    if (d1 - d0).days > 14:
        raise ToolError("INVALID_ARGS", "date range is longer than 14 days", hint="ask for a shorter window")
    days, t0, t1, step = _hours(world)
    busy, blocks, now = _busy(world, room_id), _blocks(world, room_id), world.now()
    slots = []
    d = d0
    while d <= d1 and len(slots) < MAX_SLOTS:
        if d.weekday() in days:
            s = datetime.combine(d, t0)
            while s + timedelta(minutes=step) <= datetime.combine(d, t1) and len(slots) < MAX_SLOTS:
                e = s + timedelta(minutes=step)
                in_block = not blocks or any(b0 <= s and e <= b1 for b0, b1 in blocks)
                if s > now and in_block and _free(s, e, busy):
                    slots.append({"start": s.isoformat(timespec="minutes"), "end": e.isoformat(timespec="minutes")})
                s = e
        d += timedelta(days=1)
    return {"slots": slots, "room_id": room_id}


@tool("propose_showing")
def propose_showing(world, renter_id: str, room_id: str, start: str):
    renter = need(world, "register", renter_id, "renter")
    room = need(world, "rooms", room_id, "room", "list_rooms")
    missing = gate_missing(renter, _floor(world))
    if missing:
        raise ToolError("POLICY_BLOCKED", f"gate incomplete for {renter_id}: missing {', '.join(missing)}",
                        hint=f"ask for {missing[0]} next (one item per message), read the reply with read_reply, record it with upsert_renter",
                        details={"missing": missing})
    occ = renter["gate"]["occupants"]["value"]
    if room.get("max_occupants") and occ > room["max_occupants"]:
        raise ToolError("POLICY_BLOCKED", f"{occ} occupants exceeds {room_id}'s maximum of {room['max_occupants']}",
                        hint="match_renters for another room, or escalate_to_owner")
    s = parse_dt(start, "start")
    days, t0, t1, step = _hours(world)
    e = s + timedelta(minutes=step)
    if s <= world.now():
        raise ToolError("INVALID_ARGS", f"start {start} is in the past (now {world.clock['now']})", hint="use find_showing_slots")
    if s.weekday() not in days or s.time() < t0 or e.time() > t1 or e.date() != s.date():
        raise ToolError("CONFLICT", f"{start} is outside showing hours", hint="use find_showing_slots")
    if not _free(s, e, _busy(world, room_id)):
        raise ToolError("CONFLICT", f"{start} overlaps another showing (no two showings at once)", hint="use find_showing_slots")
    for ev in world.calendar:
        if ev.get("renter_id") == renter_id and ev.get("room_id") == room_id and ev.get("status") in ("proposed", "confirmed"):
            raise ToolError("CONFLICT", f"{renter_id} already has a {ev['status']} showing {ev['event_id']} for {room_id}")
    event = {"event_id": world.next_id("E"), "title": f"Showing {room_id} with {renter.get('name') or renter_id}",
             "start": s.isoformat(timespec="minutes"), "end": e.isoformat(timespec="minutes"), "status": "proposed",
             "renter_id": renter_id, "room_id": room_id, "created_at": world.clock["now"]}
    world.calendar.append(event)
    renter["status"] = "showing_proposed"
    return {"event": copy.deepcopy(event)}
