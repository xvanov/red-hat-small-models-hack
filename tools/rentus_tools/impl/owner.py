"""Owner tools: escalate_to_owner, report_to_owner."""
from __future__ import annotations

import copy

from ..core import tool
from ..errors import ToolError

REF_COLLECTIONS = (("threads", "thread_id"), ("jobs", "job_id"), ("register", "renter_id"), ("listings", "listing_id"),
                   ("quotes", "quote_id"), ("rooms", "room_id"), ("calendar", "event_id"),
                   ("tenants", "tenant_id"))


@tool("escalate_to_owner")
def escalate_to_owner(world, reason: str, ref_id: str, draft: str | None = None):
    if not reason.strip():
        raise ToolError("INVALID_ARGS", "escalate_to_owner: reason must not be empty")
    kind = next((key for coll, key in REF_COLLECTIONS if world.get(coll, ref_id)), None)
    if kind is None:
        raise ToolError("NOT_FOUND", f"ref_id {ref_id!r} matches no thread, job, renter, listing, quote, room, event or tenant")
    for e in world.escalations:
        if e["ref_id"] == ref_id and e["reason"] == reason and e.get("status") == "open":
            return {"escalation": copy.deepcopy(e), "existing": True}
    esc = {"esc_id": world.next_id("ESC"), "reason": reason, "ref_id": ref_id, "ref_type": kind, kind: ref_id,
           "draft": draft, "status": "open", "created_at": world.clock["now"]}
    world.escalations.append(esc)
    return {"escalation": copy.deepcopy(esc)}


@tool("report_to_owner")
def report_to_owner(world, summary: str):
    if not summary.strip():
        raise ToolError("INVALID_ARGS", "report_to_owner: summary must not be empty")
    world.owner_reports.append({"report_id": world.next_id("RPT"), "summary": summary, "created_at": world.clock["now"]})
    return {"ok": True}
