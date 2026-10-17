"""Register tools: upsert_renter, match_renters. Gate items follow data/reader_schema.md shapes."""
from __future__ import annotations

import copy
import re
from datetime import date

from ..core import tool
from ..errors import ToolError
from ._util import need, normalize_phone, num

STATUSES = {"answered", "vague", "no", "exception", "absent"}
GATE_ITEMS = ("lease", "move_in", "phone", "occupants", "reason")
RENTER_STATUSES = {"new", "qualifying", "qualified", "showing_proposed", "showing_confirmed", "applied", "leased",
                   "not_now", "lost", "escalated"}
TOP_FIELDS = {"name", "phone", "gate", "wants", "status", "listing_of_interest", "language", "notes", "email"}
WANT_FIELDS = {"area", "budget", "type", "private_bath", "move_in", "pets"}


def _empty_gate() -> dict:
    return {"lease": {"status": "absent", "value": None}, "move_in": {"status": "absent", "date": None, "raw": None},
            "phone": {"status": "absent", "value": None}, "occupants": {"status": "absent", "value": None},
            "reason": {"status": "absent", "value": None}}


def _gate_item(item: str, v) -> dict:
    """Accept the reader's object shape or a shorthand scalar."""
    if isinstance(v, dict):
        out = dict(v)
        st = out.get("status", "answered")
        if st not in STATUSES:
            raise ToolError("INVALID_ARGS", f"gate.{item}.status must be one of {', '.join(sorted(STATUSES))}")
        out["status"] = st
    else:
        out = {"status": "answered"}
        if item == "move_in":
            out.update({"date": v, "raw": None})
        else:
            out["value"] = v
    if item == "move_in":
        out.setdefault("date", None)
        out.setdefault("raw", None)
        if out["date"] is not None:
            try:
                date.fromisoformat(out["date"])
            except (TypeError, ValueError):
                raise ToolError("INVALID_ARGS", f"gate.move_in.date {out['date']!r} is not YYYY-MM-DD",
                                hint="a vague answer goes in as {\"status\": \"vague\", \"date\": null, \"raw\": \"next month\"}")
        out = {k: out[k] for k in ("status", "date", "raw") if k in out} | {k: v for k, v in out.items() if k not in ("status", "date", "raw", "value")}
    else:
        out.setdefault("value", None)
        val = out["value"]
        if item == "lease" and val is not None and not isinstance(val, bool):
            if str(val).lower() in ("yes", "true", "si", "sí"):
                out["value"] = True
            elif str(val).lower() in ("no", "false"):
                out["value"] = False
            else:
                raise ToolError("INVALID_ARGS", "gate.lease.value must be true, false or null")
        if item == "phone" and val is not None:
            p = normalize_phone(str(val))
            if p is None:
                raise ToolError("INVALID_ARGS", f"gate.phone.value {val!r} is not a 10-digit US number",
                                hint="a partial number is {\"status\": \"vague\", \"value\": null}")
            out["value"] = p
        if item == "occupants" and val is not None:
            if isinstance(val, bool) or num(val) is None or int(num(val)) != num(val) or num(val) < 1:
                raise ToolError("INVALID_ARGS", "gate.occupants.value must be a positive integer")
            out["value"] = int(num(val))
    return out


def gate_missing(renter: dict) -> list[str]:
    """Items blocking a showing. Strict: lease needs an explicit yes (status answered, value true)."""
    g = renter.get("gate") or {}
    miss = []
    lease = g.get("lease") or {}
    if not (lease.get("status") == "answered" and lease.get("value") is True):
        miss.append("lease")
    mi = g.get("move_in") or {}
    if not (mi.get("status") in ("answered", "exception") and mi.get("date")):
        miss.append("move_in")
    ph = g.get("phone") or {}
    if not (ph.get("status") in ("answered", "exception") and ph.get("value")):
        miss.append("phone")
    rs = g.get("reason") or {}
    if not (rs.get("status") == "answered" and rs.get("value")):
        miss.append("reason")
    oc = g.get("occupants") or {}
    if not (oc.get("status") in ("answered", "exception") and oc.get("value")):
        miss.append("occupants")
    return miss


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-") or "renter"


@tool("upsert_renter")
def upsert_renter(world, thread_id: str, fields: dict):
    thread = need(world, "threads", thread_id, "thread", "list_threads")
    bad = [k for k in fields if k not in TOP_FIELDS]
    if bad:
        raise ToolError("INVALID_ARGS", f"upsert_renter: unknown field(s) {', '.join(bad)}",
                        hint=f"fields: {', '.join(sorted(TOP_FIELDS))}; gate items: {', '.join(GATE_ITEMS)}")
    renter = next((r for r in world.register if thread_id in r.get("thread_ids", [])), None)
    created = renter is None
    if created:
        rid = thread.get("renter_id") or f"renter:{_slug(fields.get('name') or thread.get('renter_name'))}"
        if world.get("register", rid):
            existing = world.get("register", rid)
            if thread.get("renter_id") == rid:
                renter, created = existing, False
                renter.setdefault("thread_ids", []).append(thread_id)
            else:
                i = 2
                while world.get("register", f"{rid}-{i}"):
                    i += 1
                rid = f"{rid}-{i}"
        if created:
            renter = {"renter_id": rid, "thread_ids": [thread_id], "name": thread.get("renter_name"), "phone": None,
                      "gate": _empty_gate(), "wants": {}, "status": "new", "listing_of_interest": thread.get("listing_id"),
                      "language": thread.get("language", "en"), "created_at": world.clock["now"]}
    # validate everything before mutating
    new = copy.deepcopy(renter)
    gate = fields.get("gate")
    if gate is not None:
        if not isinstance(gate, dict):
            raise ToolError("INVALID_ARGS", "fields.gate must be an object keyed by lease, move_in, phone, occupants, reason")
        badg = [k for k in gate if k not in GATE_ITEMS]
        if badg:
            raise ToolError("INVALID_ARGS", f"unknown gate item(s) {', '.join(badg)}", hint=f"gate items: {', '.join(GATE_ITEMS)}")
        for k, v in gate.items():
            new["gate"][k] = _gate_item(k, v)
    wants = fields.get("wants")
    if wants is not None:
        if not isinstance(wants, dict) or any(k not in WANT_FIELDS for k in wants):
            raise ToolError("INVALID_ARGS", f"fields.wants keys: {', '.join(sorted(WANT_FIELDS))}")
        if "budget" in wants and wants["budget"] is not None and num(wants["budget"]) is None:
            raise ToolError("INVALID_ARGS", "wants.budget must be a number (USD/month)")
        new["wants"].update(wants)
    if "phone" in fields and fields["phone"] is not None:
        p = normalize_phone(str(fields["phone"]))
        if p is None:
            raise ToolError("INVALID_ARGS", f"phone {fields['phone']!r} is not a 10-digit US number")
        new["phone"] = p
        if new["gate"]["phone"]["status"] == "absent":
            new["gate"]["phone"] = {"status": "answered", "value": p}
    if new["gate"]["phone"].get("value") and not new.get("phone"):
        new["phone"] = new["gate"]["phone"]["value"]
    if "status" in fields:
        if fields["status"] not in RENTER_STATUSES:
            raise ToolError("INVALID_ARGS", f"status must be one of {', '.join(sorted(RENTER_STATUSES))}")
        new["status"] = fields["status"]
    if fields.get("listing_of_interest"):
        loi = fields["listing_of_interest"]
        if not (world.get("listings", loi) or world.get("rooms", loi)):
            raise ToolError("NOT_FOUND", f"listing_of_interest {loi!r} is neither a listing_id nor a room_id")
        new["listing_of_interest"] = loi
    for k in ("name", "language", "notes", "email"):
        if k in fields:
            new[k] = fields[k]
    if new["status"] in ("new", "qualifying"):
        new["status"] = "qualified" if not gate_missing(new) else ("qualifying" if gate else new["status"])
    new["updated_at"] = world.clock["now"]
    if created:
        world.register.append(new)
    else:
        renter.clear()
        renter.update(new)
    return {"renter": copy.deepcopy(new), "created": created, "gate_missing": gate_missing(new)}


def _room_of(world, loi: str | None) -> str | None:
    if not loi:
        return None
    l = world.get("listings", loi)
    return l["room_id"] if l else loi


@tool("match_renters")
def match_renters(world, room_id: str):
    room = need(world, "rooms", room_id, "room", "list_rooms")
    avail = date.fromisoformat(room["available_from"])
    rent = float(room["rent"])
    out = []
    for r in world.register:
        if r.get("status") in ("lost", "leased"):
            continue
        score, reasons = 0, []
        w = r.get("wants") or {}
        g = r.get("gate") or {}
        occ = (g.get("occupants") or {}).get("value")
        if occ and room.get("max_occupants") and occ > room["max_occupants"]:
            continue  # cannot live there
        b = num(w.get("budget"))
        if b is not None:
            if b >= rent:
                score += 30; reasons.append(f"budget ${b:g} covers rent ${rent:g}")
            elif b >= rent * 0.95:
                score += 10; reasons.append(f"budget ${b:g} is within 5% of rent")
            else:
                score -= 20; reasons.append(f"budget ${b:g} below rent ${rent:g}")
        if w.get("area"):
            if str(w["area"]).lower() in (room["area"].lower(), room["zip"]):
                score += 20; reasons.append(f"wants {room['area']}")
            else:
                score -= 10; reasons.append(f"wants {w['area']}, room is in {room['area']}")
        if w.get("private_bath") is True:
            if room.get("private_bath"):
                score += 15; reasons.append("private bath")
            else:
                score -= 15; reasons.append("wants a private bath")
        if w.get("type") and str(w["type"]).lower() in room.get("type", "").lower():
            score += 10; reasons.append(f"type {room['type']}")
        mi = (g.get("move_in") or {}).get("date")
        if mi:
            d = date.fromisoformat(mi)
            gap = (d - avail).days
            if 0 <= gap <= 14:
                score += 20; reasons.append(f"moves in {mi}, room free {room['available_from']}")
            elif gap < 0:
                score -= 10 if gap < -14 else 0; reasons.append(f"moves in {mi}, before the room is free")
            else:
                score += 5; reasons.append(f"moves in {mi}, {gap} days after the room is free")
        if occ:
            score += 5; reasons.append(f"{occ} occupant(s) fits max {room.get('max_occupants')}")
        if not gate_missing(r):
            score += 10; reasons.append("gate complete")
        if _room_of(world, r.get("listing_of_interest")) == room_id:
            score += 15; reasons.append("asked about this room")
        out.append({"renter_id": r["renter_id"], "score": score, "reasons": reasons})
    out.sort(key=lambda m: (-m["score"], m["renter_id"]))
    return {"matches": out}
