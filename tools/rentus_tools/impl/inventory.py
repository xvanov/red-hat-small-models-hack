"""Inventory tools: list_rooms, get_room, update_room."""
from __future__ import annotations

import copy

from ..core import tool
from ..errors import ToolError
from ._util import need, num, parse_date

SUMMARY_FIELDS = ("room_id", "area", "zip", "address_public", "type", "private_bath", "own_entrance", "furnished",
                  "rent", "deposit", "utilities", "available_from", "pets", "lease_min_months", "max_occupants")

EDITABLE = {"area", "zip", "address", "address_public", "type", "private_bath", "own_entrance", "furnished", "rent",
            "deposit", "utilities", "available_from", "pets", "lease_min_months", "max_occupants", "amenities",
            "photos", "notes"}


@tool("list_rooms")
def list_rooms(world, available_by: str | None = None, area: str | None = None):
    cutoff = parse_date(available_by, "available_by") if available_by else None
    out = []
    for r in world.rooms:
        if cutoff and parse_date(r["available_from"], "available_from") > cutoff:
            continue
        if area:
            a = area.strip().lower()
            if a not in (str(r.get("area", "")).lower(), str(r.get("zip", ""))):
                continue
        out.append({k: r.get(k) for k in SUMMARY_FIELDS if k in r})
    return {"rooms": out, "count": len(out)}


@tool("get_room")
def get_room(world, room_id: str):
    r = need(world, "rooms", room_id, "room", "list_rooms")
    return {"room": {k: v for k, v in copy.deepcopy(r).items() if k != "price_basis"}}


@tool("update_room")
def update_room(world, room_id: str, fields: dict):
    r = need(world, "rooms", room_id, "room", "list_rooms")
    if not fields:
        raise ToolError("INVALID_ARGS", "update_room: fields is empty", hint="e.g. {\"rent\": 750}")
    bad = [k for k in fields if k not in EDITABLE]
    if bad:
        raise ToolError("INVALID_ARGS", f"update_room: cannot edit {', '.join(bad)}",
                        hint=f"editable fields: {', '.join(sorted(EDITABLE))}")
    for k in ("rent", "deposit"):
        if k in fields and (num(fields[k]) is None or num(fields[k]) <= 0 or isinstance(fields[k], bool)):
            raise ToolError("INVALID_ARGS", f"update_room: {k} must be a positive number")
    if "available_from" in fields:
        parse_date(fields["available_from"], "fields.available_from")
    for k in ("private_bath", "own_entrance", "furnished"):
        if k in fields and not isinstance(fields[k], bool):
            raise ToolError("INVALID_ARGS", f"update_room: {k} must be true or false")
    for k in ("lease_min_months", "max_occupants"):
        if k in fields and (not isinstance(fields[k], int) or isinstance(fields[k], bool) or fields[k] < 1):
            raise ToolError("INVALID_ARGS", f"update_room: {k} must be a positive integer")
    for k, v in fields.items():
        if k in ("rent", "deposit"):
            v = int(v) if float(v).is_integer() else float(v)
        r[k] = v
        if k == "address":
            r["address_public"] = v
    return get_room(world, room_id)
