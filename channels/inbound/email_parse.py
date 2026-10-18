"""Turn a platform lead notification email into a Lead.

Platforms send a notification when a renter writes: Roomies ("<name> sent you a message"), Furnished
Finder (lead / booking request emails), the Zillow family (Zillow, Trulia, HotPads: "New contact" /
"is interested in"), craigslist reply relays, PadSplit, Facebook. A renter may also email directly.
Notifications that carry no renter message (newsletters, receipts, security alerts) return None.

The patterns are written from the general shape of these emails, not from real messages; anything
they miss falls back to the first prose paragraph of the body, and `confidence` says which path won.
"""
from __future__ import annotations

import html as html_mod
import re
from dataclasses import asdict, dataclass, field
from email import message_from_bytes, message_from_string, policy
from email.message import EmailMessage
from email.utils import parseaddr, parsedate_to_datetime

PLATFORMS: dict[str, dict] = {
    "roomies": {"domains": ("roomies.com",), "reply_via": "platform"},
    "furnished_finder": {"domains": ("furnishedfinder.com",), "reply_via": "email"},
    "zillow": {"domains": ("zillow.com", "zillowrentals.com", "trulia.com", "hotpads.com", "zillowgroup.com"),
               "reply_via": "email"},
    "craigslist": {"domains": ("craigslist.org",), "reply_via": "relay"},
    "padsplit": {"domains": ("padsplit.com",), "reply_via": "platform"},
    "facebook": {"domains": ("facebookmail.com", "facebook.com"), "reply_via": "platform"},
}
# subjects / bodies that mean "a person wrote to you"
LEAD_MARKERS = re.compile(
    r"sent you a (new )?message|new message from|new (contact|lead|inquiry|enquiry)|is interested in|"
    r"booking request|tenant (lead|inquiry)|wants to (rent|know|see)|has a question|question about your|"
    r"replied to your|reply to your (post|ad|listing)|interested in your|is the room (still )?available|"
    r"still available|\bmove[- ]in\b|nuevo mensaje|interesad[oa]", re.I)
# automated mail that is never a lead even if it matches a word above
NOT_LEAD = re.compile(
    r"newsletter|unsubscribe from (all|marketing)|receipt|invoice|password|verify your (email|account)|"
    r"security alert|sign[- ]in attempt|your listing (has )?expired|weekly (digest|summary)|"
    r"tips for hosts|promotion", re.I)
LABEL = r"(?:^|\n)\s*(?:\*\*)?{}(?:\*\*)?\s*[:\-]\s*(.+)"
PHONE = re.compile(r"(?<!\d)(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}(?!\d)")
SIGNOFF = re.compile(r"\n\s*(?:reply (?:directly|to|on|in)|to reply|respond (?:to|on)|view (?:the )?(?:full )?(?:message|conversation|lead)|"
                     r"log ?in to|open the app|this (?:email|message) was sent|you(?:'re| are) receiving|"
                     r"manage (?:your )?notifications|-{2,}|_{3,}|={3,}|sent from my)", re.I)


@dataclass
class Lead:
    platform: str                      # roomies | furnished_finder | zillow | craigslist | padsplit | facebook | direct
    renter_name: str
    text: str
    subject: str = ""
    message_id: str = ""
    received_at: str | None = None
    renter_email: str | None = None    # only when the email itself gives a direct address
    renter_phone: str | None = None
    reply_to: str | None = None        # where a reply would go (platform relay or renter)
    reply_via: str = "email"           # email | relay | platform (reply must be written in the platform)
    listing_ref: str | None = None
    move_in: str | None = None
    confidence: str = "pattern"        # pattern | fallback
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------- helpers

def _msg(raw: bytes | str | EmailMessage) -> EmailMessage:
    if isinstance(raw, EmailMessage):
        return raw
    if isinstance(raw, bytes):
        return message_from_bytes(raw, policy=policy.default)
    return message_from_string(raw, policy=policy.default)


def html_to_text(h: str) -> str:
    h = re.sub(r"(?is)<(script|style|head)[^>]*>.*?</\1>", " ", h)
    h = re.sub(r"(?is)<blockquote[^>]*>(.*?)</blockquote>",
               lambda m: "\n" + "\n".join("> " + x for x in re.sub(r"(?s)<[^>]+>", " ", m.group(1)).splitlines()
                                          if x.strip()) + "\n", h)
    h = re.sub(r"(?i)<br\s*/?>", "\n", h)
    h = re.sub(r"(?i)</(p|div|tr|h\d|li|blockquote|table)>", "\n", h)
    h = re.sub(r"(?s)<[^>]+>", " ", h)
    h = html_mod.unescape(h)
    h = re.sub(r"[ \t\xa0]+", " ", h)
    return re.sub(r"\n\s*\n+", "\n\n", "\n".join(line.strip() for line in h.splitlines())).strip()


def body_text(m: EmailMessage) -> str:
    part = m.get_body(preferencelist=("plain",))
    if part is not None:
        txt = part.get_content()
        if txt.strip():
            return txt.replace("\r\n", "\n").strip()
    part = m.get_body(preferencelist=("html",))
    if part is not None:
        return html_to_text(part.get_content())
    return ""


def detect_platform(from_addr: str, reply_to: str, body: str) -> str:
    dom = (from_addr.rsplit("@", 1)[-1] if "@" in from_addr else "").lower()
    rdom = (reply_to.rsplit("@", 1)[-1] if "@" in reply_to else "").lower()
    for name, p in PLATFORMS.items():
        if any(dom == d or dom.endswith("." + d) or rdom.endswith(d) for d in p["domains"]):
            return name
    return "direct"


def _label(text: str, *names: str) -> str | None:
    for n in names:
        m = re.search(LABEL.format(n), text, re.I)
        if m:
            v = m.group(1).strip().strip("*").strip()
            if v:
                return v
    return None


def _cut(text: str) -> str:
    m = SIGNOFF.search("\n" + text)
    if m:
        text = ("\n" + text)[: m.start()]
    return text.strip()


def _quoted_block(text: str) -> str | None:
    """A message shown in quotes or as '> ' lines."""
    q = re.findall(r"(?m)^\s*>\s?(.*)$", text)
    if q and sum(len(x) for x in q) > 8:
        return " ".join(x.strip() for x in q if x.strip())
    m = re.search(r"[\"“]([^\"”]{8,1500})[\"”]", text, re.S)
    return m.group(1).strip() if m else None


def _name_from_subject(subject: str) -> str | None:
    for pat in (r"^(?:re:\s*)?(.+?) sent you a (?:new )?message", r"new message from (.+?)(?: about| on| re|$)",
                r"new (?:contact|lead|inquiry) from (.+?)(?: for| about| on|$)", r"^(.+?) is interested in",
                r"booking request from (.+?)(?: for| on|$)", r"^(.+?) has a question"):
        m = re.search(pat, subject, re.I)
        if m:
            return m.group(1).strip(" :-")
    return None


def _first_paragraph(text: str) -> str:
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    for p in paras:
        low = p.lower()
        if re.match(r"^(hi|hello|dear|hey)\b[^\n]{0,40}[,!]?$", low) or len(p) < 12:
            continue
        if re.search(r"sent you a message|new (contact|lead|message)|is interested in your|has a question|"
                     r"^(about )?your listing|^listing:", low) and len(p) < 160:
            continue
        return p
    return paras[0] if paras else ""


def _listing_ref(text: str, subject: str) -> str | None:
    v = _label(text, "listing", "property", "room", "regarding", "re", "your listing")
    if v:
        return v[:140]
    m = re.search(r"(?:about|for|in) (?:your|the) (?:listing|room|property|post)[:\s]+[\"“]?([^\"”\n]{4,120})", text + "\n" + subject, re.I)
    return m.group(1).strip() if m else None


# ---------------------------------------------------------------- main entry

def parse_email(raw: bytes | str | EmailMessage) -> Lead | None:
    m = _msg(raw)
    subject = str(m.get("Subject", "") or "")
    from_name, from_addr = parseaddr(str(m.get("From", "") or ""))
    _, reply_to = parseaddr(str(m.get("Reply-To", "") or ""))
    body = body_text(m)
    platform = detect_platform(from_addr, reply_to, body)
    head = subject + "\n" + body[:600]
    if NOT_LEAD.search(subject) or (platform != "direct" and not LEAD_MARKERS.search(head)):
        return None
    if platform == "direct" and not (LEAD_MARKERS.search(head) or re.search(
            r"\b(room|rent|rental|lease|available|cuarto|habitaci[oó]n|renta|alquiler|disponible)\b", head, re.I)):
        return None

    msg_text = None
    # a labeled message runs to the next label or sign-off, not only to the end of its line
    lab = re.search(r"(?:^|\n)\s*(?:\*\*)?(?:message|comments?|their message|note|mensaje)(?:\*\*)?\s*:\s*", body, re.I)
    if lab:
        rest = body[lab.end():]
        nxt = re.search(r"\n\s*(?:name|phone|email|move[- ]in(?: date)?|listing|property|budget|occupants|"
                        r"length of stay|lease length)\s*:", rest, re.I)
        msg_text = _cut(rest[: nxt.start()] if nxt else rest) or None
    confidence = "pattern"
    if not msg_text:
        msg_text = _quoted_block(body)
    if not msg_text:
        msg_text = _first_paragraph(_cut(body))
        confidence = "fallback"
    msg_text = re.sub(r"\s+\n", "\n", msg_text).strip()
    if not msg_text:
        return None

    name = (_label(body, "name", "from", "renter", "tenant", "guest", "nombre") or _name_from_subject(subject)
            or (from_name if platform in ("direct", "craigslist") else None) or "")
    name = re.sub(r"\s*<[^>]+>|\s*\(.*?\)", "", name).strip()
    if platform != "direct" and from_name and not name:
        mm = re.match(r"(.+?) (?:via|through|on) ", from_name, re.I)
        name = mm.group(1) if mm else ""
    email_lbl = _label(body, "email", "e-mail", "correo")
    renter_email = None
    if email_lbl and "@" in email_lbl:
        renter_email = parseaddr(email_lbl)[1] or None
    elif platform == "direct":
        renter_email = from_addr or None
    phone_lbl = _label(body, "phone", "phone number", "mobile", "cell", "tel[eé]fono")
    ph = PHONE.search(phone_lbl or "") or (PHONE.search(msg_text) if confidence == "pattern" else None)
    move_in = _label(body, "move[- ]in date", "move[- ]in", "desired move[- ]in", "check[- ]in", "start date",
                     "fecha de mudanza")
    received = None
    try:
        received = parsedate_to_datetime(str(m.get("Date"))).isoformat() if m.get("Date") else None
    except (TypeError, ValueError):
        received = None
    reply_via = PLATFORMS.get(platform, {}).get("reply_via", "email")
    extra = {}
    for key, labels in {"budget": ("budget",), "occupants": ("occupants", "number of occupants", "people"),
                        "stay_length": ("length of stay", "lease length", "stay", "duration")}.items():
        v = _label(body, *labels)
        if v:
            extra[key] = v[:80]
    return Lead(platform=platform, renter_name=name[:80], text=msg_text[:4000], subject=subject[:200],
                message_id=str(m.get("Message-ID", "") or "").strip(), received_at=received,
                renter_email=renter_email, renter_phone=ph.group(0) if ph else None,
                reply_to=reply_to or (from_addr if platform in ("direct", "craigslist") else None),
                reply_via=reply_via, listing_ref=_listing_ref(body, subject),
                move_in=move_in[:60] if move_in else None, confidence=confidence, extra=extra)
