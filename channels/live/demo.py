"""Public demo mode: anyone can try the assistant by putting a demo code in their FIRST message.

The 888 line, the Rentus Homes Page and info@rentus.homes are production: real renters and tenants must never get
an AI reply by accident. So, with LIVE_PUBLIC_DEMO=1 (default off):
  - a sender who is not on the allowlist becomes a demo contact only when the first message the daemon sees from
    them contains the demo code (LIVE_DEMO_CODE, default "DEMO", case-insensitive, whole word);
  - a sender whose first message has no code is marked ineligible (a hash of the contact only, never text) and
    ignored from then on, exactly like today; their message is not stored or shown to a model;
  - demo contacts are prospects, get the disclosure line on the first reply, at most LIVE_DEMO_MAX_PER_DAY (20)
    replies a day, one turn at a time, STOP ends it; the global cap becomes LIVE_MAX_PER_HOUR (default 120 in demo
    mode); the kill switch is unchanged;
  - email: only mail addressed to the demo address (LIVE_DEMO_EMAIL_TO, default the Reply-To plus-address) counts,
    never mail to info@rentus.homes (that inbox feeds the production app).
State: runs/live/demo_contacts.json {"enrolled": {channel: {contact: iso}}, "ineligible": {channel: [sha]}}.
"""
from __future__ import annotations

import json
import re

from . import config
from .store import Store, now_iso, short_hash

DISCLOSURE = "You're chatting with Rentus Homes' AI assistant (demo). Reply STOP to end."


def enabled() -> bool:
    return (config.env("LIVE_PUBLIC_DEMO", "0") or "0").strip() == "1"


def code() -> str:
    return (config.env("LIVE_DEMO_CODE", "DEMO") or "DEMO").strip()


def has_code(text: str) -> bool:
    c = code()
    return bool(c) and re.search(rf"(?<![\w]){re.escape(c)}(?![\w])", text or "", re.I) is not None


def max_per_day() -> int:
    try:
        return int(config.env("LIVE_DEMO_MAX_PER_DAY", "20") or 20)
    except ValueError:
        return 20


def _path(store: Store):
    return store.root / "demo_contacts.json"


def load(store: Store) -> dict:
    try:
        d = json.loads(_path(store).read_text())
    except (OSError, ValueError):
        d = {}
    d.setdefault("enrolled", {})
    d.setdefault("ineligible", {})
    return d


def save(store: Store, d: dict) -> None:
    store._write(_path(store), d)


def _key(channel: str, contact: str) -> str:
    return config.normalize_phone(contact) if channel == "sms" else str(contact).strip().lower()


def is_enrolled(store: Store, channel: str, contact: str) -> bool:
    return enabled() and _key(channel, contact) in load(store)["enrolled"].get(channel, {})


def admit(store: Store, channel: str, contact: str, text: str) -> bool:
    """Decide for an unlisted sender (caller holds the store lock). True = demo contact, process the message."""
    if not enabled():
        return False
    d = load(store)
    k = _key(channel, contact)
    if k in d["enrolled"].get(channel, {}):
        return True
    h = short_hash(k)
    if h in d["ineligible"].get(channel, []):
        return False
    if has_code(text):
        d["enrolled"].setdefault(channel, {})[k] = now_iso()
        save(store, d)
        return True
    d["ineligible"].setdefault(channel, []).append(h)
    save(store, d)
    return False


def email_to() -> str | None:
    v = (config.env("LIVE_DEMO_EMAIL_TO") or "").strip().lower()
    if v:
        return v
    ec = config.email_cfg()
    return ec.reply_to.lower() if ec else None
