"""Public read-only view (CONSOLE_PUBLIC_READONLY=1): a second console process judges can open without a login.

Enforced on the server: every mutating request is refused (app.py middleware), and live data is filtered here
before it leaves the process: the owner's personal Messenger threads are dropped, contact details of everyone
except the owner's own test contacts (the live allow-list) are masked, and approval drafts of other people's
threads are removed.
"""
from __future__ import annotations

import os
import re
import time

READONLY = os.environ.get("CONSOLE_PUBLIC_READONLY") == "1"
HIDDEN_CHANNELS = {"messenger_personal"}
_OWNER: dict = {"at": 0.0, "ids": set()}


def owner_threads() -> set:
    """Thread ids whose contact is on the live allow-list (the owner's own test phone, email, Messenger id)."""
    if time.monotonic() - _OWNER["at"] < 30:
        return _OWNER["ids"]
    ids = set()
    try:
        from channels.live import config
        from channels.live.store import Store
        allow = config.Allowlist.load()
        for t in Store().all_threads():
            if t.get("contact") and allow.allows(t.get("channel", ""), t["contact"]):
                ids.add(t["thread_id"])
    except Exception:
        pass
    _OWNER.update(at=time.monotonic(), ids=ids)
    return ids


def mask_phone(s: str) -> str:
    digits = re.sub(r"\D", "", s or "")
    return f"+1 ••• ••• {digits[-4:]}" if len(digits) >= 4 else "•••"


def mask_email(s: str) -> str:
    user, _, dom = (s or "").partition("@")
    return f"{user[:1]}•••@{dom}" if dom else "•••"


def mask_name(s: str) -> str:
    parts = (s or "").split()
    if not parts:
        return ""
    return parts[0] + (f" {parts[-1][0]}." if len(parts) > 1 else "")


def mask_contact(c: str, channel: str) -> str:
    c = c or ""
    if "@" in c:
        return mask_email(c)
    if channel == "sms" or re.fullmatch(r"[+\d\s().…-]{4,}", c):
        return mask_phone(c)
    return mask_name(c)


def visible(t: dict) -> bool:
    return t.get("channel") not in HIDDEN_CHANNELS


def thread(t: dict) -> dict:
    """One thread (summary or full) as the public may see it."""
    t = dict(t)
    if t.get("thread_id") not in owner_threads():
        t["contact_display"] = mask_contact(t.get("contact_display") or "", t.get("channel", ""))
        t["renter_name"] = mask_name(t.get("renter_name") or "")
        t.pop("line", None)
    return t


def approvals(items: list[dict], threads_by_id: dict) -> list[dict]:
    out = []
    owner = owner_threads()
    for a in items:
        t = threads_by_id.get(a.get("thread_id"))
        if t is not None and not visible(t):
            continue
        if a.get("channel") in HIDDEN_CHANNELS:
            continue
        a = dict(a)
        if a.get("thread_id") not in owner:
            a["draft_text"] = ""
            a["last_message"] = None
            if a.get("who"):
                a["who"] = mask_contact(a["who"], a.get("channel") or "")
        out.append(a)
    return out
