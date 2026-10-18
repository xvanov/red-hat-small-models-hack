"""Per-contact roles on the live channels: where in the leasing lifecycle this contact is.

Configured per channel in .env (not hardcoded):
  LIVE_ROLE_SMS=tenant  LIVE_ROLE_EMAIL=lease_signing  LIVE_ROLE_MESSENGER=prospect   (default: prospect)

  prospect       inquiry -> qualifying -> qualified -> showing -> application (register stage), the concierge flow
  tenant         a current tenant of R100 Appling Way (lease active, $750 due the 1st): maintenance, rent, plans
  lease_signing  an approved applicant (qualified, showing done); next step is signing the lease. The live-only
                 tool `send_lease_link` puts the lease-signing link into the reply; stage becomes lease_sent.

Stage values the console sees: inquiry | qualifying | qualified | showing | application | lost (prospect),
tenant, lease_signing | lease_sent.
"""
from __future__ import annotations

import copy

from . import config

ROLES = ("prospect", "tenant", "lease_signing")
ROOM_ID = "R100"
TENANT_ID = "TEN_KALIN"


def role_for(channel: str) -> str:
    r = (config.env(f"LIVE_ROLE_{channel.upper()}", "prospect") or "prospect").strip().lower()
    return r if r in ROLES else "prospect"


def live_room() -> dict:
    from channels.pilot_post import ROOM
    r = copy.deepcopy(ROOM)
    r["room_id"] = ROOM_ID
    return r


def initial_stage(role: str) -> str:
    return {"tenant": "tenant", "lease_signing": "lease_signing"}.get(role, "inquiry")


def context(t: dict) -> str:
    role = t.get("role", "prospect")
    if role == "tenant":
        return "Current tenant · Appling Way R100 · rent $750 due 1st"
    if role == "lease_signing":
        if t.get("lease_sent"):
            return "Approved applicant · Appling Way R100 · lease link sent " + str(t["lease_sent"])[:10]
        return "Approved applicant · Appling Way R100 · lease ready to sign"
    return "Prospect · Appling Way R100 · $750/mo, private bath, available Nov 1"


def note(role: str) -> str:
    if role == "tenant":
        return (f"- This contact is a CURRENT TENANT, not a prospect: Kalin, room {ROOM_ID} on Appling Way, lease active, "
                f"rent $750 due on the 1st (tenant_id {TENANT_ID}). Use the tenant tools: maintenance goes "
                "`triage_maintenance` first, then `create_job`, `find_vendors`, `request_quote`, `compare_quotes`; rent "
                "questions `get_ledger`; payment plans `propose_payment_plan`. Every money decision (vendor quotes, "
                "plans) goes to `escalate_to_owner`. Never ask qualifying questions.\n"
                "- Read the whole thread first. Never ask a question the tenant already answered, never repeat your own "
                "earlier question, and never add details the tenant did not say (do not call a leak slow, small or "
                "running unless they said so).\n"
                "- Maintenance, once the tenant has said WHERE (toilet, sink, tub, ceiling, ...): in THIS turn, without "
                "asking anything else and without asking for a photo: (1) `create_job` (severity medium unless it is an "
                "emergency) and `find_vendors` with the trade (plumber for water); (2) `send_message` one sentence of "
                "safety advice for that spot, e.g. for a toilet \"Please turn the shut-off valve behind the toilet "
                "clockwise and put towels down.\"; (3) `send_message` \"I'm lining up a plumber and will confirm the "
                "visit with you shortly.\"; then `escalate_to_owner` with the vendor options before any spending. "
                "Only if they have not said where yet, ask where (one question).")
    if role == "lease_signing":
        return (f"- This contact is an APPROVED APPLICANT for room {ROOM_ID} on Appling Way: qualification and the "
                "showing are done, the next step is signing the lease. When they ask for the lease or say they are "
                "ready to sign, call `send_lease_link` with the thread_id (it adds the signing link to your reply), "
                "then `send_message` one short line saying the lease link is in this message. Never ask qualifying "
                "questions; anything about changing terms goes to `escalate_to_owner`.")
    return ("- Before replying to anything the renter states, record it: `read_reply` on their message, then "
            "`upsert_renter` with every answered gate item (lease, move_in, phone, reason, occupants) and "
            "`capture_demand` with new criteria.")


def seed_world(w, t: dict, wid: str) -> None:
    """Add the role's records to a fresh live World (room R100 already in it, thread `wid` added)."""
    role = t.get("role", "prospect")
    wt = next(x for x in w.threads if x["thread_id"] == wid)
    wt["role"] = role
    room = next(r for r in w.rooms if r["room_id"] == ROOM_ID)
    if role == "tenant":
        room["available_from"] = None
        room["status"] = "occupied"
        wt["renter_name"] = wt.get("renter_name") or "Kalin"
        wt["kind"] = "tenant"
        w.tenants[:] = [{
            "tenant_id": TENANT_ID, "name": "Kalin", "thread_ids": [wid], "room_id": ROOM_ID, "language": "en",
            "lease": {"rent": 750, "due_day": 1, "deposit": None, "late_fee": None, "late_fee_after_days": 5,
                      "notices": {}},
            "ledger": [{"date": "2026-09-01", "kind": "charge", "amount": 750, "period": "2026-09", "note": "rent"},
                       {"date": "2026-09-01", "kind": "payment", "amount": 750, "period": "2026-09"},
                       {"date": "2026-10-01", "kind": "charge", "amount": 750, "period": "2026-10", "note": "rent"},
                       {"date": "2026-10-01", "kind": "payment", "amount": 750, "period": "2026-10"}]}]
    elif role == "lease_signing":
        wt["renter_name"] = wt.get("renter_name") or "Kalin"
        w.register.append({
            "renter_id": "renter:kalin", "name": "Kalin", "thread_ids": [wid], "phone": None, "email": t.get("contact"),
            "status": "applied", "listing_of_interest": None, "language": "en", "wants": {},
            "notes": "Approved applicant: qualification and showing done; next step is signing the lease.",
            "gate": {"lease": {"status": "answered", "value": True},
                     "move_in": {"status": "answered", "date": "2026-11-01", "raw": "Nov 1"},
                     "phone": {"status": "answered", "value": "on file"},
                     "occupants": {"status": "answered", "value": 1},
                     "reason": {"status": "answered", "value": "work"}}})


# ---------------------------------------------------------------- the live-only tool send_lease_link

TOOL = "send_lease_link"
_STATE: dict = {"installed": False, "on_link": None}


def install_lease_tool(on_link) -> None:
    """Register `send_lease_link` in this process only (no file under tools/ or operator/ changes): its schema goes
    into rentus_tools.schemas (PARAMS, the verbose/concierge DESCRIPTIONS and TOOL_NAMES, which tool_schemas reads
    at call time) and its handler into the tool registry. `on_link(world, thread, url)` is called with the link
    (the daemon appends it to this turn's reply)."""
    _STATE["on_link"] = on_link
    if _STATE["installed"]:
        return
    from rentus_tools import core, schemas
    from rentus_tools.errors import ToolError

    schemas.PARAMS[TOOL] = {"type": "object", "properties": {"thread_id": {"type": "string"}},
                            "required": ["thread_id"], "additionalProperties": False}
    for d in schemas.DESCRIPTIONS.values():
        d[TOOL] = ("Approved applicants only: get the lease-signing link for this thread's applicant and add it to "
                   "your reply on this thread. Then send_message one short line that the lease link is included.")
        d[f"{TOOL}.thread_id"] = "The applicant's thread id."
    if TOOL not in schemas.TOOL_NAMES:
        schemas.TOOL_NAMES.append(TOOL)

    @core.tool(TOOL)
    def send_lease_link(world, thread_id: str):
        t = next((x for x in world.threads if x.get("thread_id") == thread_id), None)
        if t is None:
            raise ToolError("NOT_FOUND", f"no thread {thread_id!r}", hint="use the thread_id from the inbound message")
        if t.get("role") != "lease_signing":
            raise ToolError("POLICY_BLOCKED", "this contact is not an approved applicant at lease signing",
                            hint="only approved applicants get the lease link; escalate_to_owner if unsure")
        from . import lease_link
        url = lease_link.get_link(t)
        if _STATE["on_link"]:
            _STATE["on_link"](world, t, url)
        t["lease_link_sent"] = True
        return {"status": "link_added", "note": "the lease-signing link is added to your reply on this thread; "
                                                "send_message one short line saying it is included"}

    _STATE["installed"] = True
