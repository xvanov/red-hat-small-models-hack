"""Inbox tools: list_threads, read_thread, send_message."""
from __future__ import annotations

import copy

from .. import live
from ..core import tool
from ..errors import ToolError
from ._util import dollar_figures, need
from .listings import allowed_figures
from .style import lease_terms, style_violations


def thread_room(world, thread: dict) -> tuple[dict | None, dict | None]:
    """The room/listing a thread is about: thread.listing_id / room_id, else the renter's listing_of_interest."""
    listing = world.get("listings", thread["listing_id"]) if thread.get("listing_id") else None
    if listing is None:
        for r in world.register:
            if thread["thread_id"] in r.get("thread_ids", []) and r.get("listing_of_interest"):
                listing = world.get("listings", r["listing_of_interest"]) or None
                if listing is None and world.get("rooms", r["listing_of_interest"]):
                    return world.get("rooms", r["listing_of_interest"]), None
                break
    room_id = thread.get("room_id") or (listing or {}).get("room_id")
    return (world.get("rooms", room_id) if room_id else None), listing


def _summary(t: dict) -> dict:
    last = t["messages"][-1] if t["messages"] else None
    return {"thread_id": t["thread_id"], "channel": t.get("channel"), "renter_name": t.get("renter_name"),
            "language": t.get("language"), "listing_id": t.get("listing_id"), "message_count": len(t["messages"]),
            "last_from": last["from"] if last else None, "last_text": (last["text"][:160] if last else None),
            "last_ts": last["ts"] if last else None, "unanswered": bool(last and last["from"] == "renter")}


@tool("list_threads")
def list_threads(world, channel: str | None = None, unanswered_only: bool = False):
    out = [_summary(t) for t in world.threads if (not channel or t.get("channel") == channel)]
    if unanswered_only:
        out = [s for s in out if s["unanswered"]]
    return {"threads": out, "count": len(out)}


@tool("read_thread")
def read_thread(world, thread_id: str):
    t = need(world, "threads", thread_id, "thread", "list_threads")
    return {"thread": copy.deepcopy(t)}


@tool("send_message")
def send_message(world, thread_id: str, text: str, attachments: list[str] | None = None):
    t = need(world, "threads", thread_id, "thread", "list_threads")
    attachments = attachments or []
    if not text.strip():
        raise ToolError("INVALID_ARGS", "send_message: text is empty")
    problems = style_violations(text)
    if problems:
        raise ToolError("POLICY_BLOCKED", "message breaks style rules: " + "; ".join(m for _, m in problems),
                        hint="rewrite: at most 2 short sentences, one question, commas instead of dashes",
                        details={"rules": [r for r, _ in problems]})
    room, listing = thread_room(world, t)
    figs = dollar_figures(text)
    if figs:
        if room is not None:
            allowed = allowed_figures(room, listing)
            where = room["room_id"]
        else:  # thread not tied to a room yet: any figure from any room or listing record
            allowed = set()
            for r in world.rooms:
                allowed |= allowed_figures(r)
            for l in world.listings:
                allowed.add(float(l["price"]))
            where = "any room or listing"
        bad = [f for f in figs if f not in allowed]
        if bad:
            raise ToolError("POLICY_BLOCKED",
                            f"message quotes {', '.join(f'${b:g}' for b in bad)}, which is not in the record for {where}",
                            hint="quote the record's rent/deposit; price changes and discounts go to escalate_to_owner",
                            details={"rules": ["price_not_in_record"]})
    floor = world.policy.get("lease_min_months_public", 12)
    for phrase, months in lease_terms(text):
        room_min = (room or {}).get("lease_min_months", floor)
        if months is not None and months < min(floor, room_min):
            raise ToolError("POLICY_BLOCKED", f"message offers a lease term ('{phrase}') shorter than the public minimum of {floor} months",
                            hint="shorter leases are the owner's decision; escalate_to_owner with a draft",
                            details={"rules": ["lease_term_not_in_record"]})
    known = {p for r in world.rooms for p in r.get("photos", [])}
    unknown = [a for a in attachments if a.rsplit("/", 1)[-1] not in known]
    if unknown:
        raise ToolError("INVALID_ARGS", f"unknown attachment(s): {', '.join(unknown)}",
                        hint="use photo names from get_listing_media")
    msg = {"id": f"{thread_id}-m{len(t['messages']) + 1}", "from": "operator", "text": text,
           "attachments": attachments, "ts": world.clock["now"]}
    out = {"message_id": msg["id"]}
    if world.mode == "live":
        res = live.adapter_for(t.get("channel", "")).send_message(world, t, text, attachments)
        msg["status"] = res.get("status", "ready_to_submit")
        out.update({"status": msg["status"], "screenshot": res.get("screenshot")})
    else:
        msg["status"] = "sent"
        out["status"] = "sent"
    t["messages"].append(msg)
    return out
