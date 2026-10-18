"""Inbox tools: list_threads, read_thread, send_message."""
from __future__ import annotations

import copy
import re

from .. import live
from ..core import tool
from ..errors import ToolError
from ._util import dollar_figures, need
from .listings import allowed_figures
from .reader import read_reply_fallback
from .guards import booking_claims, has_confirmed_showing, language_mismatch
from .style import lease_terms, style_violations

# A renter asking for less than a year, in words the regex reader's shorter_lease intent can miss
# ("could I sign for 9 months instead?", "no, not a full year", "¿puede ser por menos tiempo?").
_NUM = r"(?:[1-9]|1[01]|one|two|three|four|five|six|seven|eight|nine|ten|eleven|un|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|once)"
SHORTER_ASK = re.compile(
    r"\b" + _NUM + r"[- ]?(?:months?|meses?)\b(?!\s+(?:upfront|up front|in advance|por adelantado|adelantad))"
    r"|\b(?:not|no) (?:a )?(?:full|whole) year\b|\bun año completo no\b|\bno (?:puedo|quiero) (?:un año|comprometerme)"
    r"|can.?t commit to (?:a |the )?(?:full |whole )?year|\b(?:less|shorter) (?:time|than a year|than 12 months|lease|term)\b"
    r"|\bmenos tiempo\b|\bm[aá]s corto\b|\bsemester\b|\bsemestre\b|\bsummer only\b|\bjust (?:for )?the summer\b"
    r"|\bsolo (?:por )?(?:el )?verano\b|\bmonth[- ]to[- ]month\b|\bmes a mes\b|\bshort[- ]term\b", re.IGNORECASE)


def renter_asked_shorter(world, thread: dict) -> bool:
    """True once the renter on this thread has asked for a lease shorter than a year (reader intent
    shorter_lease, an equivalent phrase, or a register row recording that they refused a year)."""
    for m in thread.get("messages", []):
        if m.get("from") != "renter":
            continue
        text = m.get("text") or ""
        if SHORTER_ASK.search(text) or "shorter_lease" in read_reply_fallback(text).get("intents", []):
            return True
    for r in world.register:
        if thread["thread_id"] in r.get("thread_ids", []):
            lease = (r.get("gate") or {}).get("lease") or {}
            if lease.get("status") == "answered" and lease.get("value") is False:
                return True
    return False


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
    mismatch = language_mismatch(t, text)
    if mismatch:
        want, got = mismatch
        names = {"en": "English", "es": "Spanish"}
        raise ToolError("POLICY_BLOCKED", f"the renter writes in {names[want]} but this draft is in {names[got]}",
                        hint=f"rewrite the same message in {names[want]} ({want}) and send it again",
                        details={"rules": ["language_mismatch"], "rewrite": True, "language": want, "draft_language": got})
    claims = booking_claims(text)
    if claims and not has_confirmed_showing(world, t):
        raise ToolError("POLICY_BLOCKED",
                        "message tells the renter a showing time is confirmed, but the owner has not confirmed it: "
                        + " / ".join(claims),
                        hint="say the time is proposed and pending the owner's confirmation, for example "
                             "'I proposed Saturday at 11 AM, pending the owner's confirmation' "
                             "('propuse el sábado a las 11, pendiente de confirmación del dueño')",
                        details={"rules": ["showing_not_confirmed"], "claims": claims})
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
    # Lease terms (owner decision D23): the public minimum is the default; the private floor
    # (policy.lease_floor_months, 6) may be named only after the renter asked for a shorter lease.
    floor = world.policy.get("lease_min_months_public", 12)
    hard_floor = world.policy.get("lease_floor_months", 6)
    for phrase, months in lease_terms(text):
        room_min = (room or {}).get("lease_min_months", floor)
        if months is None or months >= min(floor, room_min):
            continue
        if months >= hard_floor:
            if renter_asked_shorter(world, t):
                continue
            raise ToolError("POLICY_BLOCKED", f"message names a {months}-month lease, but the renter has not asked for a shorter lease",
                            hint=f"say '1 year minimum'; the {hard_floor}-month floor may be named only after the renter asks for less than a year",
                            details={"rules": ["lease_floor_not_requested"]})
        raise ToolError("POLICY_BLOCKED", f"message offers a lease term ('{phrase}') shorter than the {hard_floor}-month floor",
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
