"""Real providers: Twilio SMS (two lines), Resend email out + Gmail IMAP in, Facebook Messenger (Graph).

Reading is by polling only. Nothing here changes provider settings (webhooks, Page subscriptions, numbers).
Each `poll(allow, since, seen)` returns only messages FROM allowlisted contacts; for Messenger, conversations
whose participants are not allowlisted are skipped before any message text is fetched.

Inbound item shape: {"channel","contact","text","ext_id","ts","line","line_last4","renter_name","meta"}.
Send result shape:  {"ok": bool, "provider_id", "status", "error_code", "error"}  (never raises).
"""
from __future__ import annotations

import email
import email.policy
import imaplib
import re
from datetime import datetime, timezone
from email.utils import getaddresses, parsedate_to_datetime

import httpx

from . import config

TWILIO = "https://api.twilio.com/2010-04-01"
RESEND = "https://api.resend.com"
GRAPH = "https://graph.facebook.com/v23.0"
OPT_OUT = {"stop", "stopall", "unsubscribe", "cancel", "end", "quit", "revoke", "optout"}


def _scrub(msg: str, *secrets: str) -> str:
    for s in secrets:
        if s:
            msg = msg.replace(s, "***")
    return msg[:300]


def _dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00").replace("+0000", "+00:00"))
    except ValueError:
        try:
            d = parsedate_to_datetime(s)
        except (TypeError, ValueError):
            return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


# ====================================================================== SMS (Twilio)

class TwilioSms:
    channel = "sms"

    def __init__(self, line: config.SmsLine, http=None):
        self.line = line
        self.http = http or httpx

    def _req(self, method: str, path: str, **kw) -> tuple[int, dict]:
        try:
            r = self.http.request(method, f"{TWILIO}/Accounts/{self.line.account_sid}/{path}",
                                  auth=(self.line.account_sid, self.line.auth_token), timeout=30, **kw)
            return r.status_code, r.json()
        except Exception as e:
            return 0, {"message": _scrub(f"{type(e).__name__}: {e}", self.line.auth_token)}

    @property
    def display(self) -> str:
        n = self.line.number  # a business line: area code shown, middle masked
        return n[:5] + "\u2026" + n[-4:]

    def connected(self) -> tuple[bool, str]:
        code, body = self._req("GET", "IncomingPhoneNumbers.json", params={"PhoneNumber": self.line.number})
        if code != 200:
            return False, f"Twilio API error {code}: {body.get('message', '')}"[:200]
        ok = bool(body.get("incoming_phone_numbers"))
        return ok, (f"{self.line.name} line {self.display} on the account" if ok else "number not on the account")

    def send(self, to: str, text: str) -> dict:
        data = {"To": config.normalize_phone(to), "Body": text}
        if self.line.messaging_service_sid:
            data["MessagingServiceSid"] = self.line.messaging_service_sid
            data["From"] = self.line.number  # pins this line inside the messaging service
        else:
            data["From"] = self.line.number
        code, body = self._req("POST", "Messages.json", data=data)
        if code in (200, 201):
            return {"ok": True, "provider_id": body.get("sid"), "status": body.get("status"),
                    "error_code": body.get("error_code"), "error": body.get("error_message")}
        return {"ok": False, "provider_id": None, "status": "failed", "error_code": body.get("code"),
                "error": body.get("message")}

    def delivery(self, sid: str) -> dict:
        code, body = self._req("GET", f"Messages/{sid}.json")
        if code != 200:
            return {"status": "unknown", "error": body.get("message")}
        return {"status": body.get("status"), "error_code": body.get("error_code"),
                "error": body.get("error_message")}

    def poll(self, allow: config.Allowlist, since: datetime, seen: set, include_unlisted: bool = False) -> list[dict]:
        """include_unlisted (public demo mode): every inbound text to this line, so the daemon can look for the demo
        code; unlisted senders without it are dropped by the daemon before anything is stored."""
        out = []
        senders = [None] if include_unlisted else sorted(allow.phones)
        for phone in senders:
            params = {"To": self.line.number, "DateSent>": since.strftime("%Y-%m-%d"), "PageSize": 100}
            if phone:
                params["From"] = phone
            code, body = self._req("GET", "Messages.json", params=params)
            if code != 200:
                continue
            for m in body.get("messages", []):
                if not str(m.get("direction", "")).startswith("inbound") or m.get("sid") in seen:
                    continue
                ts = _dt(m.get("date_sent") or m.get("date_created"))
                if ts and ts < since:
                    continue
                frm = config.normalize_phone(m.get("from"))
                if phone and frm != phone:  # defensive: provider filter is the first check
                    continue
                out.append({"channel": "sms", "contact": frm, "text": m.get("body") or "", "ext_id": m["sid"],
                            "ts": ts.isoformat() if ts else None, "line": self.line.name,
                            "line_last4": self.line.last4, "renter_name": None, "meta": {}})
        return sorted(out, key=lambda x: x["ts"] or "")


def is_opt_out(text: str) -> bool:
    return re.sub(r"[^a-z]", "", (text or "").lower()) in OPT_OUT


# ====================================================================== Email (Resend out, Gmail IMAP in)

REF_RE = re.compile(r"\[ref ([0-9a-f]{6,10})\]")
QUOTE_RE = re.compile(r"^(On .{0,200}wrote:|-{2,} ?Original Message|From: .*<.*@.*>|>)", re.M)


SIG_RE = re.compile(r"^(-- ?$|__+$|Sent from my |Get Outlook for |Best,?$|Best regards,?$|Regards,?$|Thanks,?$|"
                    r"Thank you,?$|Cheers,?$|Sincerely,?$)", re.M | re.I)


def strip_quoted(text: str) -> str:
    """Keep the new part of a reply: cut at the first 'On ... wrote:' line or quoted block, then at a signature
    ("-- ", "Sent from my iPhone", a sign-off line like "Best," / "Thanks,")."""
    m = QUOTE_RE.search(text or "")
    body = text[:m.start()] if m else (text or "")
    s_ = SIG_RE.search(body)
    if s_ and s_.start() > 0 and body[:s_.start()].strip():
        body = body[:s_.start()]
    return re.sub(r"\n{3,}", "\n\n", body).strip()


def body_text(msg) -> str:
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    txt = part.get_content()
    if part.get_content_type() == "text/html":
        txt = re.sub(r"<br\s*/?>|</p>", "\n", txt, flags=re.I)
        txt = re.sub(r"<[^>]+>", "", txt)
    return txt


PLATFORM_DOMAINS = ("zillow.com", "furnishedfinder.com", "facebook.com", "facebookmail.com", "padsplit.com",
                    "roomies.com", "craigslist.org", "resend.com", "resend.dev", "sendgrid.net", "sendgrid.com",
                    "twilio.com", "google.com", "accounts.google.com", "zoho.com", "zohocorp.com", "apartments.com",
                    "hotpads.com", "trulia.com", "rent.com", "stripe.com", "intuit.com")
AUTO_LOCAL = re.compile(r"^(no-?reply|do-?not-?reply|mailer-daemon|postmaster|bounces?|notifications?|notify|"
                        r"alerts?|news(letter)?|marketing|support|billing|calendar|invitations?|team|hello)([+._-].*)?$")


def is_automated_email(msg) -> bool:
    """Bot-loop guard for inbound mail: auto-replies, lists, bulk, no-reply / platform notification senders,
    calendar invites."""
    auto = str(msg.get("Auto-Submitted", "no")).strip().lower()
    if auto not in ("", "no"):
        return True
    if any(msg.get(h) for h in ("List-Id", "List-Unsubscribe", "List-Post", "X-Autoreply", "X-Autorespond",
                                "X-Auto-Response-Suppress")):
        return True
    if str(msg.get("Precedence", "")).strip().lower() in ("bulk", "junk", "list", "auto_reply"):
        return True
    frm = [a.lower() for _, a in getaddresses(msg.get_all("From", []))]
    if frm:
        local, _, dom = frm[0].partition("@")
        if AUTO_LOCAL.match(local) or any(dom == d or dom.endswith("." + d) for d in PLATFORM_DOMAINS):
            return True
    if any(p.get_content_type() == "text/calendar" for p in msg.walk()):
        return True
    subj = str(msg.get("Subject", "")).lower()
    return subj.startswith(("invitation:", "updated invitation", "accepted:", "declined:", "automatic reply",
                            "out of office", "undeliverable", "delivery status notification"))


def parse_inbox_message(raw: bytes, *, ours: set, internal_ts: datetime | None = None) -> dict | None:
    """Raw RFC 822 bytes -> inbound item for the email channel, or None for our own mail. `ours` = lowercase
    addresses that are us (info@rentus.homes, the Gmail login, ...). meta.automated flags bot mail."""
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    frm = getaddresses(msg.get_all("From", []))
    if not frm or not frm[0][1]:
        return None
    addr = frm[0][1].lower()
    if addr in ours:
        return None
    mid = str(msg.get("Message-ID", "")).strip()
    if not mid:
        return None
    ts = internal_ts or _dt(str(msg.get("Date", "")))
    text = strip_quoted(body_text(msg))
    if not text.strip():  # empty body: the subject is the message
        text = re.sub(r"^\s*((re|fwd?|aw)\s*:\s*)+", "", str(msg.get("Subject", "")), flags=re.I).strip()
    return {"channel": "email", "contact": addr, "text": text, "ext_id": mid,
            "ts": ts.isoformat() if ts else None, "line": "info@rentus.homes", "line_last4": None,
            "renter_name": frm[0][0] or None,
            "meta": {"subject": str(msg.get("Subject", "")), "message_id": mid,
                     "references": str(msg.get("References", "")).split(), "automated": is_automated_email(msg),
                     "in_reply_to": str(msg.get("In-Reply-To", "")).strip(), "inbox": "zoho"}}


class ZohoInbox:
    """Read-only IMAP poller for info@rentus.homes (Zoho). SELECT ... READONLY + BODY.PEEK: nothing is marked
    seen, moved or deleted. Creds: ZOHO_IMAP_USER / ZOHO_IMAP_PASSWORD in the repo .env (never printed)."""
    channel = "email"
    HOST = "imappro.zoho.com"

    def __init__(self, user: str, password: str, ours: set, imap_factory=None):
        self.user, self.password = user, password
        self.ours = {a.lower() for a in ours} | {user.lower()}
        self.imap_factory = imap_factory or (lambda: imaplib.IMAP4_SSL(self.HOST, 993))
        self.display = user

    def __repr__(self) -> str:
        return "ZohoInbox(<set>)"

    def connected(self) -> tuple[bool, str]:
        try:
            c = self.imap_factory()
            c.login(self.user, self.password)
            typ, data = c.select("INBOX", readonly=True)
            c.logout()
        except Exception as e:
            return False, "Zoho IMAP login failed: " + type(e).__name__
        return typ == "OK", f"info@ inbox readable (read-only, {int(data[0] or 0)} messages)"

    def stats(self) -> dict:
        """Count and newest UIDs only (no content)."""
        c = self.imap_factory()
        try:
            c.login(self.user, self.password)
            typ, data = c.select("INBOX", readonly=True)
            typ, uids = c.uid("SEARCH", None, "ALL")
            u = (uids[0] or b"").split()
            return {"messages": int(data[0] or 0), "last_uids": [x.decode() for x in u[-5:]]}
        finally:
            try:
                c.logout()
            except Exception:
                pass

    def poll(self, allow: config.Allowlist, since: datetime, seen: set, include_unlisted: bool = False) -> list[dict]:
        out = []
        c = self.imap_factory()
        try:
            c.login(self.user, self.password)
            if c.select("INBOX", readonly=True)[0] != "OK":
                return []
            typ, data = c.uid("SEARCH", None, "SINCE", since.strftime("%d-%b-%Y"))
            for uid in ((data[0] or b"").split() if typ == "OK" else [])[-60:]:
                try:
                    typ, parts = c.uid("FETCH", uid, "(INTERNALDATE BODY.PEEK[])")
                    raw = next((p[1] for p in parts or [] if isinstance(p, tuple) and len(p) > 1), None)
                    if typ != "OK" or raw is None:
                        continue
                    head = b" ".join(p[0] for p in parts if isinstance(p, tuple))
                    its = None
                    m = re.search(rb'INTERNALDATE "([^"]+)"', head)
                    if m:
                        its = datetime.strptime(m.group(1).decode().strip(), "%d-%b-%Y %H:%M:%S %z")
                    item = parse_inbox_message(raw, ours=self.ours, internal_ts=its)
                except Exception:
                    continue
                if not item or item["ext_id"] in seen:
                    continue
                if item["ts"] and _dt(item["ts"]) < since:
                    continue
                if not include_unlisted and item["contact"] not in allow.emails:
                    continue
                out.append(item)
        finally:
            try:
                c.logout()
            except Exception:
                pass
        return sorted(out, key=lambda x: x["ts"] or "")


def zoho_inbox() -> "ZohoInbox | None":
    u, pw = config.env("ZOHO_IMAP_USER"), config.env("ZOHO_IMAP_PASSWORD")
    if not (u and pw):
        return None
    ec = config.email_cfg()
    ours = {"info@rentus.homes"} | ({ec.from_addr, ec.imap_user, ec.reply_to} if ec else set())
    return ZohoInbox(u, pw, ours)


class ResendGmailEmail:
    channel = "email"
    FOLDER = '"[Gmail]/All Mail"'

    def __init__(self, cfg: config.EmailCfg, http=None, imap_factory=None):
        self.cfg = cfg
        self.http = http or httpx
        self.imap_factory = imap_factory or (lambda: imaplib.IMAP4_SSL("imap.gmail.com", 993))

    @property
    def display(self) -> str:
        return self.cfg.from_addr

    def connected(self) -> tuple[bool, str]:
        try:
            c = self.imap_factory()
            c.login(self.cfg.imap_user, self.cfg.imap_pass)
            c.logout()
        except Exception as e:
            return False, "IMAP login failed: " + _scrub(type(e).__name__, self.cfg.imap_pass)
        return True, f"sends as {self.cfg.from_addr} (Resend); replies read over IMAP"

    def send(self, to: str, text: str, *, subject: str, in_reply_to: str | None = None,
             references: list[str] | None = None, html: str | None = None,
             extra_headers: dict | None = None, reply_to: str | None = None) -> dict:
        payload = {"from": f"{self.cfg.from_name} <{self.cfg.from_addr}>", "to": [to], "subject": subject,
                   "text": text, "reply_to": reply_to or self.cfg.reply_to}
        if html:
            payload["html"] = html
        headers = dict(extra_headers or {})
        if in_reply_to:
            refs = [r for r in (references or []) if r]
            if in_reply_to not in refs:
                refs.append(in_reply_to)
            headers["In-Reply-To"] = in_reply_to
            headers["References"] = " ".join(refs[-20:])
        if headers:
            payload["headers"] = headers
        try:
            r = self.http.request("POST", f"{RESEND}/emails", json=payload, timeout=30,
                                  headers={"Authorization": f"Bearer {self.cfg.resend_key}"})
            body = r.json()
        except Exception as e:
            return {"ok": False, "provider_id": None, "status": "failed", "error_code": None,
                    "error": _scrub(f"{type(e).__name__}: {e}", self.cfg.resend_key)}
        if r.status_code in (200, 201) and body.get("id"):
            return {"ok": True, "provider_id": body["id"], "status": "accepted", "error_code": None, "error": None}
        return {"ok": False, "provider_id": None, "status": "failed", "error_code": body.get("name"),
                "error": _scrub(str(body.get("message")), self.cfg.resend_key)}

    def _addressed_to_us(self, msg) -> bool:
        ours = {self.cfg.from_addr.lower(), self.cfg.reply_to.lower()}
        rcpts = {a.lower() for _, a in getaddresses(msg.get_all("To", []) + msg.get_all("Cc", []))}
        return bool(ours & rcpts) or bool(REF_RE.search(str(msg.get("Subject", ""))))

    def poll(self, allow: config.Allowlist, since: datetime, seen: set, include_unlisted: bool = False,
             demo_to: str | None = None) -> list[dict]:
        """include_unlisted (public demo mode): also mail from anyone addressed TO `demo_to` (never info@)."""
        out = []
        c = self.imap_factory()
        try:
            c.login(self.cfg.imap_user, self.cfg.imap_pass)
            typ, _ = c.select(self.FOLDER, readonly=True)
            if typ != "OK":
                c.select("INBOX", readonly=True)
            for addr in sorted(allow.emails):
                typ, data = c.uid("SEARCH", None, "FROM", f'"{addr}"', "SINCE", since.strftime("%d-%b-%Y"))
                uids = (data[0] or b"").split() if typ == "OK" else []
                for uid in uids[-40:]:
                    try:
                        item = self._one(c, uid, addr, since, seen)
                    except Exception:  # one malformed message must not stop the others
                        item = None
                    if item:
                        out.append(item)
            if include_unlisted and demo_to and demo_to != self.cfg.from_addr.lower():
                typ, data = c.uid("SEARCH", None, "TO", f'"{demo_to}"', "SINCE", since.strftime("%d-%b-%Y"))
                for uid in ((data[0] or b"").split() if typ == "OK" else [])[-40:]:
                    try:
                        item = self._one(c, uid, None, since, seen, demo_to=demo_to)
                    except Exception:
                        item = None
                    if item and item["contact"] not in allow.emails and not any(o["ext_id"] == item["ext_id"] for o in out):
                        out.append(item)
        finally:
            try:
                c.logout()
            except Exception:
                pass
        return sorted(out, key=lambda x: x["ts"] or "")

    def _one(self, c, uid, addr: str | None, since: datetime, seen: set, demo_to: str | None = None) -> dict | None:
        typ, parts = c.uid("FETCH", uid, "(BODY.PEEK[])")
        raw = next((p[1] for p in parts or [] if isinstance(p, tuple) and len(p) > 1), None)
        if typ != "OK" or raw is None:
            return None
        msg = email.message_from_bytes(raw, policy=email.policy.default)
        mid = str(msg.get("Message-ID", "")).strip() or f"uid:{uid.decode()}"
        if mid in seen:
            return None
        frm = [a.lower() for _, a in getaddresses(msg.get_all("From", []))]
        if addr is None:  # demo: any sender, but only mail addressed to the demo address, never our own mail
            rcpts = {a.lower() for _, a in getaddresses(msg.get_all("To", []) + msg.get_all("Cc", []))}
            if not frm or demo_to not in rcpts or frm[0] in (self.cfg.from_addr.lower(), self.cfg.imap_user.lower()):
                return None
            addr = frm[0]
        elif addr not in frm or not self._addressed_to_us(msg):
            return None
        ts = _dt(str(msg.get("Date", "")))
        if ts and ts < since:
            return None
        subj = str(msg.get("Subject", ""))
        refs = str(msg.get("References", "")).split()
        automated = is_automated_email(msg)
        return {"channel": "email", "contact": addr, "text": strip_quoted(body_text(msg)),
                "ext_id": mid, "ts": ts.isoformat() if ts else None, "line": self.cfg.from_addr,
                "line_last4": None, "renter_name": (getaddresses(msg.get_all("From", []))[0][0] or None),
                "meta": {"subject": subj, "message_id": mid, "references": refs, "automated": automated,
                         "in_reply_to": str(msg.get("In-Reply-To", "")).strip()}}

    def gmail_thread_ids(self, header: str, value: str) -> list[str]:
        """X-GM-THRID of the messages whose <header> contains <value> (Gmail conversation ids)."""
        c = self.imap_factory()
        try:
            c.login(self.cfg.imap_user, self.cfg.imap_pass)
            c.select(self.FOLDER, readonly=True)
            typ, data = c.uid("SEARCH", None, "HEADER", header, f'"{value}"')
            out = []
            for uid in ((data[0] or b"").split() if typ == "OK" else []):
                typ, parts = c.uid("FETCH", uid, "(X-GM-THRID)")
                m = re.search(rb"X-GM-THRID (\d+)", b" ".join(p if isinstance(p, bytes) else p[0] for p in parts or []))
                if m:
                    out.append(m.group(1).decode())
            return out
        finally:
            try:
                c.logout()
            except Exception:
                pass

    def find_delivered(self, ref_tag: str, since: datetime) -> bool:
        """Delivery check for the test inbox: our message with this [ref] tag arrived in GMAIL_USER's mail."""
        c = self.imap_factory()
        try:
            c.login(self.cfg.imap_user, self.cfg.imap_pass)
            c.select(self.FOLDER, readonly=True)
            typ, data = c.uid("SEARCH", None, "FROM", f'"{self.cfg.from_addr}"', "SINCE", since.strftime("%d-%b-%Y"),
                              "SUBJECT", f'"{ref_tag}"')
            return typ == "OK" and bool((data[0] or b"").split())
        finally:
            try:
                c.logout()
            except Exception:
                pass


# ====================================================================== Messenger (Graph)

class RateLimited(RuntimeError):
    """The provider asked us to slow down; the poller backs off."""


class Messenger:
    channel = "messenger"

    def __init__(self, http=None, creds=None):
        self.http = http or httpx
        self._creds = creds
        self._page_name = None
        self._conv_seen: dict = {}

    def creds(self) -> tuple[str, str]:
        if self._creds is None:
            from channels.facebook_page import _creds
            self._creds = _creds()
        return self._creds

    def _req(self, method: str, path: str, **kw) -> tuple[int, dict]:
        page_id, token = self.creds()
        params = dict(kw.pop("params", {}) or {})
        params["access_token"] = token
        try:
            r = self.http.request(method, f"{GRAPH}/{path}", params=params, timeout=30, **kw)
            body = r.json()
        except Exception as e:
            return 0, {"error": {"message": _scrub(f"{type(e).__name__}: {e}", token)}}
        if r.status_code >= 400 or "error" in body:
            err = body.get("error", {}) if isinstance(body, dict) else {}
            return r.status_code or 400, {"error": {k: err.get(k) for k in ("message", "code", "error_subcode")}}
        return r.status_code, body

    @property
    def display(self) -> str:
        return self._page_name or "Facebook Page"

    def connected(self) -> tuple[bool, str]:
        try:
            page_id, token = self.creds()
        except Exception as e:
            return False, f"no Page credentials ({type(e).__name__})"
        code, body = self._req("GET", page_id, params={"fields": "name"})
        if code != 200:
            return False, f"Graph error: {body.get('error', {}).get('message')}"[:200]
        self._page_name = body.get("name")
        code, dbg = self._req("GET", "debug_token", params={"input_token": token})
        scopes = (dbg.get("data") or {}).get("scopes") or []
        if "pages_messaging" not in scopes:
            return False, "token lacks pages_messaging"
        return True, f"{self._page_name}: pages_messaging granted; send needs a renter message in the last 24 h"

    def send(self, psid: str, text: str) -> dict:
        page_id, _ = self.creds()
        code, body = self._req("POST", f"{page_id}/messages", json={
            "recipient": {"id": psid}, "messaging_type": "RESPONSE", "message": {"text": text}})
        if code == 200 and body.get("message_id"):
            return {"ok": True, "provider_id": body["message_id"], "status": "sent", "error_code": None, "error": None}
        err = body.get("error", {})
        return {"ok": False, "provider_id": None, "status": "failed", "error_code": err.get("code"),
                "error": err.get("message")}

    def conversations(self, limit: int = 25) -> list[dict]:
        page_id, _ = self.creds()
        code, body = self._req("GET", f"{page_id}/conversations", params={
            "platform": "messenger", "fields": "participants,updated_time", "limit": limit})
        if code != 200:
            err = body.get("error") or {}
            if code == 429 or err.get("code") in (4, 17, 32, 613, 80001, 80006):
                raise RateLimited(f"Graph rate limit (code {err.get('code')})")
            return []
        return body.get("data", [])

    def poll(self, allow: config.Allowlist, since: datetime, seen: set, include_unlisted: bool = False) -> list[dict]:
        """include_unlisted (public demo mode): read recent conversations of anyone, so the daemon can look for the
        demo code; otherwise conversations without an allowlisted participant are skipped before any text is read."""
        if not allow.psids and not include_unlisted:
            return []
        page_id, _ = self.creds()
        out = []
        for conv in self.conversations():
            upd = _dt(conv.get("updated_time"))
            if upd and upd < since:
                continue
            parts = (conv.get("participants") or {}).get("data", [])
            psid = next((p.get("id") for p in parts if p.get("id") in allow.psids), None)
            if not psid and include_unlisted:
                psid = next((p.get("id") for p in parts if p.get("id") != page_id), None)
            if psid and self._conv_seen.get(conv["id"]) == conv.get("updated_time"):
                continue  # unchanged since the last poll: no Graph call (rate limits)
            if not psid:
                continue  # not allowlisted: no message text is fetched
            name = next((p.get("name") for p in parts if p.get("id") == psid), None)
            code, body = self._req("GET", conv["id"], params={"fields": "messages.limit(10){id,created_time,from,message}"})
            if code != 200:
                continue
            self._conv_seen[conv["id"]] = conv.get("updated_time")
            for m in (body.get("messages") or {}).get("data", []):
                if (m.get("from") or {}).get("id") != psid or m.get("id") in seen or not (m.get("message") or "").strip():
                    continue
                ts = _dt(m.get("created_time"))
                if ts and ts < since:
                    continue
                out.append({"channel": "messenger", "contact": psid, "text": m["message"], "ext_id": m["id"],
                            "ts": ts.isoformat() if ts else None, "line": page_id, "line_last4": None,
                            "renter_name": name, "meta": {"conversation_id": conv["id"]}})
        return sorted(out, key=lambda x: x["ts"] or "")

    def recent_participants(self, hours: float = 2.0) -> list[dict]:
        """For the owner to find his own PSID: name + PSID of people in conversations updated recently."""
        page_id, _ = self.creds()
        cutoff = datetime.now(timezone.utc).timestamp() - hours * 3600
        out = []
        for conv in self.conversations():
            upd = _dt(conv.get("updated_time"))
            if upd and upd.timestamp() < cutoff:
                continue
            for p in (conv.get("participants") or {}).get("data", []):
                if p.get("id") != page_id:
                    out.append({"name": p.get("name"), "psid": p.get("id"), "updated": conv.get("updated_time")})
        return out
