"""Email channel: lead emails -> threads in the local store; replies -> drafts with a reason. Never sends."""
from __future__ import annotations

from pathlib import Path

from .email_parse import Lead, parse_email
from .store import ChannelStore, thread_key

PLATFORM_NAMES = {"roomies": "Roomies", "furnished_finder": "Furnished Finder", "zillow": "Zillow",
                  "craigslist": "craigslist", "padsplit": "PadSplit", "facebook": "Facebook", "direct": "email"}


def ingest_lead(store: ChannelStore, lead: Lead) -> tuple[dict, bool]:
    """One thread per renter per platform; the same notification twice is stored once."""
    who = lead.renter_email or lead.reply_to or lead.renter_phone or lead.renter_name
    tid = thread_key("email", lead.platform, who or lead.subject)
    meta = {"source_platform": lead.platform, "reply_via": lead.reply_via, "subject": lead.subject,
            "listing_ref": lead.listing_ref,
            "contact": {k: v for k, v in {"email": lead.renter_email, "reply_to": lead.reply_to,
                                          "phone": lead.renter_phone}.items() if v},
            "lead_facts": {k: v for k, v in {"move_in": lead.move_in, **lead.extra}.items() if v}}
    return store.add_message(channel="email", thread_id=tid, text=lead.text, renter_name=lead.renter_name or None,
                             ts=lead.received_at, external_id=lead.message_id or None, meta=meta)


def ingest_raw(store: ChannelStore, raw: bytes | str) -> tuple[dict | None, bool]:
    lead = parse_email(raw)
    if lead is None:
        return None, False
    return ingest_lead(store, lead)


def ingest_files(store: ChannelStore, paths: list[str | Path]) -> dict:
    out = {"files": 0, "leads": 0, "new_messages": 0, "skipped": 0, "threads": []}
    for p in paths:
        out["files"] += 1
        t, added = ingest_raw(store, Path(p).read_bytes())
        if t is None:
            out["skipped"] += 1
            continue
        out["leads"] += 1
        out["new_messages"] += int(added)
        if t["thread_id"] not in out["threads"]:
            out["threads"].append(t["thread_id"])
    return out


def draft_reason(thread: dict) -> str:
    via = thread.get("reply_via", "email")
    plat = PLATFORM_NAMES.get(thread.get("source_platform", "direct"), "email")
    base = "Email replies are drafts only: the owner sends them himself"
    if via == "platform":
        return f"{base}. This lead came from {plat}; reply inside {plat} (its emails are notifications, not a mailbox)"
    if via == "relay":
        return f"{base}. Reply to the {plat} relay address from the owner's inbox"
    return f"{base} from his own inbox"


def save_reply_draft(store: ChannelStore, thread_id: str, text: str, reason: str | None = None) -> dict:
    t = store.get_thread(thread_id) or {}
    c = t.get("contact") or {}
    last = next((m for m in reversed(t.get("messages", [])) if m["from"] == "renter"), None)
    subj = t.get("subject") or ""
    return store.save_draft(channel="email", thread_id=thread_id, text=text,
                            to=c.get("reply_to") or c.get("email"), reply_via=t.get("reply_via"),
                            reason=reason or draft_reason(t),
                            extra={"subject": subj if subj.lower().startswith("re:") else f"Re: {subj}".strip(),
                                   "in_reply_to": last["id"] if last else None,
                                   "source_platform": t.get("source_platform")})
