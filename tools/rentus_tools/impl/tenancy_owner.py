"""Owner-only approvals (owner decisions D29). Not an operator tool: reached through
demand_owner.owner_call(world, "owner_approve", {...}) from the console /approve flow.

An approval lets the agent communicate exactly that commitment to that person (ref_id: tenant_id, thread_id,
renter_id, room_id, quote_id or job_id; '*' is an owner-set bound for everyone, optionally capped by max_usd).
Approving kind payment_plan for a tenant also approves their plan awaiting the owner; kind spend lets
book_vendor book that quote (or any quote on that job) despite the spend limit.
"""
from __future__ import annotations

import copy

from ..errors import ToolError

KINDS = ("discount", "hold", "waive_fee", "payment_plan", "grace", "deposit_return", "repair_date", "rule_exception",
         "enforcement", "spend")

OWNER_APPROVE_PARAMS = {
    "type": "object", "additionalProperties": False, "required": ["kind", "ref_id", "decision"],
    "properties": {"kind": {"type": "string", "enum": list(KINDS)}, "ref_id": {"type": "string"},
                   "decision": {"type": "string", "enum": ["approve", "reject"]}, "terms": {"type": "string"},
                   "max_usd": {"type": "number"}},
}


def owner_approve(world, kind: str, ref_id: str, decision: str, terms: str | None = None, max_usd: float | None = None):
    if kind not in KINDS:
        raise ToolError("INVALID_ARGS", f"kind must be one of {', '.join(KINDS)}")
    if decision not in ("approve", "reject"):
        raise ToolError("INVALID_ARGS", "decision must be approve or reject")
    now = world.clock["now"]
    rec = {"approval_id": world.next_id("APR"), "kind": kind, "ref_id": ref_id,
           "status": "approved" if decision == "approve" else "rejected", "terms": terms, "approved_by": "owner",
           "created_at": now}
    if max_usd is not None:
        rec["max_usd"] = max_usd
    world.approvals.append(rec)
    nxt = "the agent may now communicate exactly this" if decision == "approve" else "the agent tells the person no, kindly"
    if kind == "payment_plan":
        t = next((x for x in world.tenants if x.get("tenant_id") == ref_id or ref_id in x.get("thread_ids", [])), None)
        plan = (t or {}).get("plan") or {}
        if plan.get("status") == "awaiting_owner":
            plan["status"] = "approved" if decision == "approve" else "rejected"
            plan["decided_at"] = now
            nxt = ("send the approved schedule to the tenant (exact amounts and dates), then rent_ladder plan_sent"
                   if decision == "approve" else "tell the tenant kindly and ask how else they could pay")
    for esc in world.escalations:
        if esc.get("ref_id") == ref_id and esc.get("status") == "open":
            esc.update({"status": "resolved", "resolved_at": now, "resolution": rec["status"]})
    return {"approval": copy.deepcopy(rec), "next_step": nxt}
