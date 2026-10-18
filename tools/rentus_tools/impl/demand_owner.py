"""Owner-only actions (docs/spec/concierge.md R-SHOW-5, C32, C33).

These are NOT operator tools: they are absent from schemas.PARAMS and REGISTRY, so a model that names
one gets "unknown tool" from rt.call(). Only the owner path (the console /approve flow) reaches them,
through owner_call():

    from rentus_tools.impl.demand_owner import owner_call
    owner_call(world, "owner_confirm_showing", {"event_id": "E001", "decision": "confirm"}, sink=sink)

Envelope and events match rt.call(): {"ok": true, "data": ...} or {"ok": false, "error": {...}}, plus
tool_call / tool_result events with actor "owner" and an "owner_message" event carrying the decision.
"""
from __future__ import annotations

import copy
from datetime import datetime, timedelta

from ..errors import ToolError, ok

OWNER_PARAMS = {
    "owner_confirm_showing": {
        "type": "object", "additionalProperties": False, "required": ["event_id", "decision"],
        "properties": {"event_id": {"type": "string"}, "decision": {"type": "string", "enum": ["confirm", "reject"]},
                       "note": {"type": "string"}, "housemate": {"type": "boolean"}},
    },
}


def owner_confirm_showing(world, event_id: str, decision: str, note: str | None = None, housemate: bool | None = None):
    ev = next((e for e in world.calendar if e.get("event_id") == event_id), None)
    if ev is None or not ev.get("renter_id"):
        raise ToolError("NOT_FOUND", f"no showing with event_id {event_id!r}")
    if decision not in ("confirm", "reject"):
        raise ToolError("INVALID_ARGS", "decision must be 'confirm' or 'reject'")
    want = "confirmed" if decision == "confirm" else "rejected"
    if ev.get("status") == want:   # either signal, first one wins: a second identical decision changes nothing
        return {"event": copy.deepcopy(ev), "already": True, "next_step": "nothing: this decision was already applied"}
    if ev.get("status") != "proposed":
        raise ToolError("CONFLICT", f"showing {event_id} is {ev.get('status')}, only a proposed showing can be decided")
    now = world.clock["now"]
    renter = next((r for r in world.register if r.get("renter_id") == ev["renter_id"]), None)
    ev.update({"status": want, "decided_at": now, "decided_by": "owner"})
    if note:
        ev["owner_note"] = note
    if want == "confirmed":
        start = datetime.fromisoformat(ev["start"])
        ev["on_the_way_by"] = (start - timedelta(hours=1)).isoformat(timespec="minutes")
        if housemate is not None:
            ev["housemate_confirmed"] = bool(housemate)
        if renter:
            renter["status"] = "showing_confirmed"
        nxt = ("tell the prospect, in first person, that the time is confirmed (once); then, as its own message, that "
               f"they must confirm they are on their way by {ev['on_the_way_by'].replace('T', ' ')} (one hour before) or "
               "there is no showing; the full address may now go to them privately")
    else:
        if renter and renter.get("status") in ("showing_proposed", "showing_confirmed"):
            renter["status"] = "qualified"
        nxt = "do not confirm: propose another slot (find_showing_slots, propose_showing) or close politely"
    for esc in world.escalations:
        if esc.get("ref_id") == event_id and esc.get("status") == "open":
            esc.update({"status": "resolved", "resolved_at": now, "resolution": want})
    world.meta.setdefault("owner_decisions", []).append(
        {"event_id": event_id, "decision": want, "at": now, "renter_id": ev["renter_id"], "note": note})
    thread_ids = (renter or {}).get("thread_ids", [])
    return {"event": copy.deepcopy(ev), "renter_id": ev["renter_id"], "thread_ids": thread_ids, "next_step": nxt}


OWNER_TOOLS = {"owner_confirm_showing": owner_confirm_showing}


def owner_call(world, name: str, args: dict | None = None, *, sink=None, call_id: str | None = None) -> dict:
    """Run one owner action. Never raises for tool-level problems."""
    args = dict(args or {})
    base = {"tool": name, "call_id": call_id}
    if sink:
        sink.emit("tool_call", "owner", {**base, "args": args})
    try:
        if name not in OWNER_TOOLS:
            raise ToolError("INVALID_ARGS", f"unknown owner action {name!r}", hint=f"owner actions: {', '.join(OWNER_TOOLS)}")
        schema = OWNER_PARAMS[name]
        unknown = [k for k in args if k not in schema["properties"]]
        missing = [k for k in schema["required"] if args.get(k) is None]
        if unknown or missing:
            raise ToolError("INVALID_ARGS", f"{name}: unknown {unknown or 'none'}, missing {missing or 'none'}",
                            hint="args: event_id (string), decision (confirm|reject), note?, housemate?")
        result = ok(OWNER_TOOLS[name](world, **args))
    except ToolError as e:
        result = e.envelope()
    if sink:
        sink.emit("tool_result", "system", {**base, "result": result, "fault": None})
        if result["ok"] and not result["data"].get("already"):
            ev = result["data"]["event"]
            sink.emit("owner_message", "owner", {"summary": f"{ev['status']} showing {ev['event_id']}",
                                                 "decision": ev["status"], "event": ev})
    return result
