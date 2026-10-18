"""SMS channel: drafts only, written to a local outbox file. Nothing is ever sent.

Inbound texts reach a thread in one of two ways: the owner (or the demo) adds them with
`python -m channels.inbound sms-add`, or a future reader appends them through `ingest_text`.
Replies go to `channels/.inbox/sms_outbox.jsonl` with the reason they are drafts.

TwilioSender below is the seam for a future real send. It is DISABLED: `send()` always refuses,
it never reads TWILIO_* values, and there is no flag in this repo that turns it on. Enabling real
sends is the owner's decision and needs, at minimum: an explicit per-message owner approval step, the
owner's existing communications guard (safe recipients, kill switch) in front of it, opt-out handling,
and 10DLC/toll-free registration for the sending number.
"""
from __future__ import annotations

import re

from .store import ChannelStore, thread_key

DRAFT_REASON = "SMS replies are drafts only: the owner sends texts from his own phone"


def normalize_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) == 10:
        digits = "1" + digits
    return "+" + digits if digits else ""


def masked(phone: str) -> str:
    p = normalize_phone(phone)
    return p[:2] + "*" * (len(p) - 6) + p[-4:] if len(p) > 6 else p


def ingest_text(store: ChannelStore, *, phone: str, text: str, name: str | None = None, ts: str | None = None,
                external_id: str | None = None) -> dict:
    p = normalize_phone(phone)
    if not p or not text.strip():
        raise ValueError("phone and text are required")
    tid = thread_key("sms", p)
    t, _ = store.add_message(channel="sms", thread_id=tid, text=text.strip(), renter_name=name or masked(p), ts=ts,
                             external_id=external_id,
                             meta={"contact": {"phone": p}, "source_platform": "sms", "reply_via": "sms"})
    return t


def save_reply_draft(store: ChannelStore, thread_id: str, text: str, reason: str | None = None) -> dict:
    t = store.get_thread(thread_id) or {}
    to = (t.get("contact") or {}).get("phone")
    last = next((m for m in reversed(t.get("messages", [])) if m["from"] == "renter"), None)
    return store.save_draft(channel="sms", thread_id=thread_id, text=text, to=to, reply_via="sms",
                            reason=reason or DRAFT_REASON,
                            extra={"in_reply_to": last["id"] if last else None})


class SendDisabled(RuntimeError):
    pass


class TwilioSender:
    """Future real SMS send. Disabled by design; see the module docstring for what enabling needs."""

    enabled = False

    def send(self, to: str, text: str) -> dict:
        raise SendDisabled("SMS sending is disabled in this repo; replies are saved as drafts in the outbox")
