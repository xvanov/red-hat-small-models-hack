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
OPEN_DISCLOSURE = "Hi, you're chatting with Rentus Homes' AI assistant."


def open_mode() -> bool:
    """LIVE_PUBLIC_MODE=open (owner decision): everyone who writes to the 888 line, the Page or the public email
    address is enrolled as a prospect, no keyword."""
    return (config.env("LIVE_PUBLIC_MODE", "") or "").strip().lower() == "open"


def keyword_mode() -> bool:
    return (config.env("LIVE_PUBLIC_DEMO", "0") or "0").strip() == "1"


def enabled() -> bool:
    return open_mode() or keyword_mode()


OPEN_DISCLOSURE_ES = "Hola, estás hablando con el asistente de IA de Rentus Homes."
_ES = re.compile(r"[¿¡ñáéíóú]|\b(hola|gracias|cuarto|habitaci[oó]n|disponible|renta|alquiler|busco|quiero|"
                 r"mudo|mudarme|n[uú]mero|solo|est[aá])\b", re.I)


def is_spanish(text: str) -> bool:
    return len(_ES.findall(text or "")) >= 2


def disclosure(lang: str = "en") -> str:
    if open_mode():
        return OPEN_DISCLOSURE_ES if lang == "es" else OPEN_DISCLOSURE
    return DISCLOSURE


def is_automated(channel: str, contact: str, meta: dict | None = None) -> bool:
    """Bot-loop guard: SMS short codes / non-NANP senders, email auto-replies, lists, no-reply addresses."""
    meta = meta or {}
    if channel == "sms":
        return not re.fullmatch(r"\+1\d{10}", config.normalize_phone(contact) or "")
    if channel == "email":
        c = (contact or "").lower()
        if re.search(r"(^|[._+-])(no-?reply|do-?not-?reply|mailer-daemon|postmaster|bounce[s]?|notifications?)"
                     r"([._+-]|@)", c):
            return True
        return bool(meta.get("automated")) or c.endswith("@rentus.homes")
    return False


def code() -> str:
    return (config.env("LIVE_DEMO_CODE", "DEMO") or "DEMO").strip()


def has_code(text: str) -> bool:
    c = code()
    return bool(c) and re.search(rf"(?<![\w]){re.escape(c)}(?![\w])", text or "", re.I) is not None


def max_per_day() -> int:
    d = "30" if open_mode() else "20"
    try:
        return int(config.env("LIVE_DEMO_MAX_PER_DAY", d) or d)
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


def open_since(store: Store) -> str | None:
    """When open mode was first seen on (messages older than this are never answered: no backlog). Caller holds
    the lock."""
    if not open_mode():
        return None
    d = load(store)
    if not d.get("open_since"):
        d["open_since"] = now_iso()
        save(store, d)
    return d["open_since"]


def save(store: Store, d: dict) -> None:
    store._write(_path(store), d)


def _key(channel: str, contact: str) -> str:
    return config.normalize_phone(contact) if channel == "sms" else str(contact).strip().lower()


def is_enrolled(store: Store, channel: str, contact: str) -> bool:
    return enabled() and _key(channel, contact) in load(store)["enrolled"].get(channel, {})


def admit(store: Store, channel: str, contact: str, text: str, *, ts: str | None = None,
          meta: dict | None = None) -> bool:
    """Decide for an unlisted sender (caller holds the store lock). True = public contact, process the message."""
    if not enabled() or is_automated(channel, contact, meta):
        return False
    if open_mode():
        since = open_since(store)
        if ts and since:
            from datetime import datetime
            try:
                if datetime.fromisoformat(ts.replace("Z", "+00:00")) < datetime.fromisoformat(since):
                    return False  # backlog from before open mode: never answered
            except ValueError:
                pass
    d = load(store)
    k = _key(channel, contact)
    if k in d["enrolled"].get(channel, {}):
        return True
    if open_mode():
        d["enrolled"].setdefault(channel, {})[k] = now_iso()
        save(store, d)
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
