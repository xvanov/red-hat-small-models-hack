"""Live channels configuration: lines, credentials, allowlist, kill switch, rate cap.

Credentials are loaded programmatically (dotenv_values) from the owner's existing env files and are never
printed, logged or returned. Every function here that reports on configuration returns booleans and masked
identifiers only.

Env vars (repo .env or process env; all optional):
  LIVE_DIR                       store directory (default runs/live, gitignored)
  LIVE_SEND_ENABLED              "0" turns every real send off (drafts become approval items). Default on.
  LIVE_MAX_PER_HOUR              outbound cap across all channels (default 30)
  LIVE_ALLOW_PHONES              extra allowlisted phones, comma separated (DEMO_TEST_PHONE always included)
  LIVE_ALLOW_EMAILS              extra allowlisted emails (DEMO_TEST_EMAIL always included)
  LIVE_ALLOW_MESSENGER_PSIDS     allowlisted Messenger PSIDs (the owner's personal account on the Page)
  LIVE_SMS_LINES                 which SMS lines to run, comma separated (default "tollfree"; add ",local" to opt in
                                 to the 910 10DLC line, which belongs to another business's campaign)
  LIVE_SMS_LOCAL_ENV             env file of the local 10DLC line (default ~/ivanovstroy/.env.sms)
  LIVE_SMS_TOLLFREE_ENV          env file of the 888 line (default ~/rental-management/.env.production)
  LIVE_EMAIL_ENV                 env file with RESEND_KEY / RESEND_FROM_EMAIL / GMAIL_USER / GMAIL_PASS
                                 (default ~/rental-management/.env.production)
  LIVE_EMAIL_FROM                sender address (default RESEND_FROM_EMAIL, i.e. info@rentus.homes)
  LIVE_EMAIL_REPLY_TO            Reply-To header (default: plus-address of GMAIL_USER, "<user>+rentus@gmail.com")
  LIVE_POLL_SECONDS              daemon poll interval (default 8)
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HOME = Path.home()


def _repo_env() -> dict:
    try:
        from dotenv import dotenv_values
        return {k: v for k, v in dotenv_values(REPO / ".env").items() if v is not None}
    except Exception:
        return {}


def env(name: str, default: str | None = None) -> str | None:
    if name in os.environ:
        return os.environ[name]
    return _repo_env().get(name, default)


def _file_env(path: str | Path) -> dict:
    p = Path(path).expanduser()
    if not p.exists():
        return {}
    from dotenv import dotenv_values
    return {k: v for k, v in dotenv_values(p).items() if v}


def live_dir() -> Path:
    return Path(env("LIVE_DIR") or (REPO / "runs" / "live"))


def normalize_phone(p: str | None) -> str:
    d = re.sub(r"\D", "", p or "")
    if len(d) == 10:
        d = "1" + d
    return "+" + d if d else ""


def mask_phone(p: str | None) -> str:
    p = normalize_phone(p)
    return (p[:2] + "…" + p[-4:]) if len(p) > 6 else p


def mask_email(e: str | None) -> str:
    if not e or "@" not in e:
        return e or ""
    user, dom = e.split("@", 1)
    return f"{user[:1]}…@{dom}"


def _csv(v: str | None) -> list[str]:
    return [x.strip() for x in (v or "").split(",") if x.strip()]


@dataclass
class Allowlist:
    phones: set = field(default_factory=set)
    emails: set = field(default_factory=set)
    psids: set = field(default_factory=set)
    extra: dict = field(default_factory=dict)     # extra channel name -> set of contact ids

    @classmethod
    def load(cls) -> "Allowlist":
        phones = {normalize_phone(p) for p in _csv(env("DEMO_TEST_PHONE")) + _csv(env("LIVE_ALLOW_PHONES"))}
        emails = {e.lower() for e in _csv(env("DEMO_TEST_EMAIL")) + _csv(env("LIVE_ALLOW_EMAILS"))}
        psids = set(_csv(env("LIVE_ALLOW_MESSENGER_PSIDS")))
        return cls({p for p in phones if p}, emails, psids)

    def ids_for(self, channel: str) -> set:
        if channel not in self.extra:
            self.extra[channel] = set(_csv(env(f"LIVE_ALLOW_{channel.upper()}_IDS")))
        return self.extra[channel]

    def allows(self, channel: str, contact: str) -> bool:
        if channel == "sms":
            return normalize_phone(contact) in self.phones
        if channel == "email":
            return (contact or "").strip().lower() in self.emails
        if channel == "messenger":
            return str(contact) in self.psids
        return str(contact) in self.ids_for(channel)

    def size(self) -> int:
        return len(self.phones) + len(self.emails) + len(self.psids) + sum(len(v) for v in self.extra.values())


@dataclass
class SmsLine:
    name: str                  # "tollfree" | "local"
    account_sid: str
    auth_token: str
    number: str
    messaging_service_sid: str | None = None

    def __repr__(self) -> str:  # never show credentials
        return f"SmsLine({self.name}, {mask_phone(self.number)})"

    @property
    def last4(self) -> str:
        return self.number[-4:]


def sms_lines() -> list[SmsLine]:
    out = []
    # The 910 local line is another business's 10DLC campaign: opt-in only (LIVE_SMS_LINES=tollfree,local).
    for name in _csv(env("LIVE_SMS_LINES", "tollfree")):
        if name == "tollfree":
            e = _file_env(env("LIVE_SMS_TOLLFREE_ENV") or HOME / "rental-management" / ".env.production")
            num = e.get("TWILIO_PHONE_NUMBER")
            msid = None
        elif name == "local":
            e = _file_env(env("LIVE_SMS_LOCAL_ENV") or HOME / "ivanovstroy" / ".env.sms")
            num = e.get("TWILIO_FROM_NUMBER") or e.get("TWILIO_PHONE_NUMBER")
            msid = e.get("TWILIO_MESSAGING_SERVICE_SID")
        else:
            continue
        if e.get("TWILIO_ACCOUNT_SID") and e.get("TWILIO_AUTH_TOKEN") and num:
            out.append(SmsLine(name, e["TWILIO_ACCOUNT_SID"], e["TWILIO_AUTH_TOKEN"], normalize_phone(num), msid))
    return out


@dataclass
class EmailCfg:
    resend_key: str
    from_addr: str
    from_name: str
    reply_to: str
    imap_user: str
    imap_pass: str

    def __repr__(self) -> str:
        return f"EmailCfg(from={self.from_addr}, reply_to={mask_email(self.reply_to)})"


def email_cfg() -> EmailCfg | None:
    e = _file_env(env("LIVE_EMAIL_ENV") or HOME / "rental-management" / ".env.production")
    if not (e.get("RESEND_KEY") and e.get("GMAIL_USER") and e.get("GMAIL_PASS")):
        return None
    frm = env("LIVE_EMAIL_FROM") or e.get("RESEND_FROM_EMAIL") or "info@rentus.homes"
    user = e["GMAIL_USER"]
    reply_to = env("LIVE_EMAIL_REPLY_TO") or (user.split("@")[0] + "+rentus@" + user.split("@")[1])
    return EmailCfg(e["RESEND_KEY"], frm, e.get("RESEND_FROM_NAME") or "Rentus Homes", reply_to, user, e["GMAIL_PASS"])


def send_enabled() -> bool:
    if (live_dir() / "STOP").exists():
        return False
    return (env("LIVE_SEND_ENABLED", "1") or "1").strip() not in ("0", "false", "no", "off")


def max_per_hour() -> int:
    try:
        return int(env("LIVE_MAX_PER_HOUR", "30") or 30)
    except ValueError:
        return 30


def poll_seconds() -> float:
    try:
        return float(env("LIVE_POLL_SECONDS", "8") or 8)
    except ValueError:
        return 8.0
