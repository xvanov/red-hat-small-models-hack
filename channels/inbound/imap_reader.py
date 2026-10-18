"""Read platform lead emails from an IMAP inbox the owner configures. Read-only.

The mailbox is opened with SELECT ... READONLY and messages are fetched with BODY.PEEK[], so nothing is
marked read, moved, flagged or deleted. Nothing is ever sent from here.

Configuration (env vars, values never printed or logged):
  CHANNELS_IMAP_CONFIRMED=1      required: the owner confirms which inbox this is. Without it the reader refuses.
  CHANNELS_IMAP_HOST             e.g. imap.gmail.com (default for a gmail.com user)
  CHANNELS_IMAP_PORT             default 993 (SSL)
  CHANNELS_IMAP_USER             mailbox login
  CHANNELS_IMAP_PASSWORD         an app password, not the account password
  CHANNELS_IMAP_FOLDER           default INBOX
  CHANNELS_IMAP_ENV_FILE         optional file to load the above from (e.g. a gitignored .env)
  CHANNELS_IMAP_USER_VAR / CHANNELS_IMAP_PASSWORD_VAR
                                 optional: read the login from differently named variables in that file
                                 (for example GMAIL_USER / GMAIL_PASS), once the owner says which inbox.
"""
from __future__ import annotations

import imaplib
import os
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from .email_parse import PLATFORMS, Lead, parse_email


class ImapNotConfigured(RuntimeError):
    pass


def _read_env_file(path: str | Path) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        lines = Path(path).expanduser().read_text().splitlines()
    except OSError:
        return out
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.removeprefix("export ").strip()
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
            v = v[1:-1]
        out[k] = v
    return out


@dataclass
class ImapConfig:
    host: str
    user: str
    password: str
    port: int = 993
    folder: str = "INBOX"

    def __repr__(self) -> str:  # never show the login in logs or tracebacks
        return f"ImapConfig(host={self.host!r}, port={self.port}, folder={self.folder!r}, user=<set>, password=<set>)"

    @classmethod
    def from_env(cls, env: dict | None = None) -> "ImapConfig":
        env = dict(os.environ if env is None else env)
        if env.get("CHANNELS_IMAP_ENV_FILE"):
            env = {**_read_env_file(env["CHANNELS_IMAP_ENV_FILE"]), **env}
        if env.get("CHANNELS_IMAP_CONFIRMED") != "1":
            raise ImapNotConfigured(
                "IMAP reading is off until the owner confirms the inbox: set CHANNELS_IMAP_CONFIRMED=1 "
                "together with CHANNELS_IMAP_USER / CHANNELS_IMAP_PASSWORD (see channels/LOGIN.md)")
        user = env.get(env.get("CHANNELS_IMAP_USER_VAR") or "CHANNELS_IMAP_USER", "")
        pw = env.get(env.get("CHANNELS_IMAP_PASSWORD_VAR") or "CHANNELS_IMAP_PASSWORD", "")
        if not user or not pw:
            raise ImapNotConfigured("CHANNELS_IMAP_USER and CHANNELS_IMAP_PASSWORD (or the *_VAR names) are not set")
        host = env.get("CHANNELS_IMAP_HOST") or ("imap.gmail.com" if user.lower().endswith("@gmail.com") else "")
        if not host:
            raise ImapNotConfigured("CHANNELS_IMAP_HOST is not set")
        return cls(host=host, user=user, password=pw, port=int(env.get("CHANNELS_IMAP_PORT") or 993),
                   folder=env.get("CHANNELS_IMAP_FOLDER") or "INBOX")


def config_status(env: dict | None = None) -> dict:
    """Which settings are present (True/False), for the owner's checklist. Never returns values."""
    env = dict(os.environ if env is None else env)
    file_env = _read_env_file(env["CHANNELS_IMAP_ENV_FILE"]) if env.get("CHANNELS_IMAP_ENV_FILE") else {}
    merged = {**file_env, **env}
    uv = merged.get("CHANNELS_IMAP_USER_VAR") or "CHANNELS_IMAP_USER"
    pv = merged.get("CHANNELS_IMAP_PASSWORD_VAR") or "CHANNELS_IMAP_PASSWORD"
    return {"confirmed": merged.get("CHANNELS_IMAP_CONFIRMED") == "1", "env_file": bool(file_env),
            "user_var": uv, "user_set": bool(merged.get(uv)), "password_var": pv, "password_set": bool(merged.get(pv)),
            "host_set": bool(merged.get("CHANNELS_IMAP_HOST")), "folder": merged.get("CHANNELS_IMAP_FOLDER") or "INBOX"}


def _search_criteria(since: date) -> list[str]:
    """SINCE <date> and FROM any platform domain (OR-chained). Direct renter emails need a full scan
    (pass platforms_only=False)."""
    doms = [d for p in PLATFORMS.values() for d in p["domains"]]
    crit = f'FROM "{doms[0]}"'
    for d in doms[1:]:
        crit = f'OR FROM "{d}" {crit}'
    return ["SINCE", since.strftime("%d-%b-%Y"), f"({crit})"]


def fetch_leads(cfg: ImapConfig, *, since_days: int = 14, limit: int = 200, platforms_only: bool = True,
                imap_factory=None) -> tuple[list[Lead], dict]:
    """Return (leads, stats). `imap_factory(host, port)` is injectable for tests."""
    factory = imap_factory or (lambda h, p: imaplib.IMAP4_SSL(h, p))
    since = date.today() - timedelta(days=since_days)
    stats = {"scanned": 0, "leads": 0, "skipped": 0}
    conn = factory(cfg.host, cfg.port)
    try:
        conn.login(cfg.user, cfg.password)
        typ, _ = conn.select(f'"{cfg.folder}"', readonly=True)
        if typ != "OK":
            raise RuntimeError(f"cannot open folder {cfg.folder!r}")
        crit = _search_criteria(since) if platforms_only else ["SINCE", since.strftime("%d-%b-%Y")]
        typ, data = conn.search(None, *crit)
        ids = (data[0] or b"").split() if typ == "OK" else []
        leads: list[Lead] = []
        for mid in ids[-limit:]:
            typ, parts = conn.fetch(mid, "(BODY.PEEK[])")
            raw = next((p[1] for p in parts or [] if isinstance(p, tuple) and len(p) > 1), None)
            if typ != "OK" or raw is None:
                continue
            stats["scanned"] += 1
            lead = parse_email(raw)
            if lead is None:
                stats["skipped"] += 1
                continue
            leads.append(lead)
        stats["leads"] = len(leads)
        return leads, stats
    finally:
        try:
            conn.logout()
        except Exception:
            pass
