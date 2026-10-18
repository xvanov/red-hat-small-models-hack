"""Lane 3: Google Calendar behind find_showing_slots / propose_showing (owner decision D29).

    from rentus_tools.live.calendar_adapter import register_calendar
    register_calendar()            # wraps the two registry entries; uninstall_calendar() restores them

With world.mode == "live":
  find_showing_slots   showing hours are 08:00-20:00 every day (CHANNELS_SHOWINGS_HOURS), the clock is the
                       real America/New_York time, and every busy block on the Google calendars (free/busy
                       query, read-only) counts as taken, for every room: the owner can't be at two showings.
  propose_showing      runs every sandbox check (gate, occupants, hours, overlaps incl. Google busy), re-checks
                       the slot on Google, then creates ONE event "PROPOSED: Showing with <first name>" on
                       CHANNELS_SHOWINGS_CALENDAR_ID. No attendees, sendUpdates=none, so nobody is invited or
                       emailed. If that var is unset nothing is written anywhere (calendar.status "not_written").
                       If Google refuses the write, the proposal is rolled back and the tool returns
                       UPSTREAM_ERROR.
In sandbox mode the wrappers do nothing.

Env (values are never printed):
  CHANNELS_SHOWINGS_CALENDAR_ID       the only calendar events are ever created on; also read for free/busy
  CHANNELS_SHOWINGS_BUSY_CALENDAR_IDS optional comma list of extra calendars read for free/busy only
  CHANNELS_SHOWINGS_HOURS             default "08:00-20:00"; CHANNELS_SHOWINGS_SLOT_MINUTES default 30
  CHANNELS_SHOWINGS_TZ                default "America/New_York"
  CHANNELS_GOOGLE_ENV_FILE            env file holding the service account (default ~/rental-management/.env.production)
  service account: GOOGLE_SERVICE_ACCOUNT_EMAIL + GOOGLE_PRIVATE_KEY, or a JSON blob named by
  CHANNELS_GOOGLE_CREDENTIALS_VAR (e.g. GOOGLE_CALENDAR_CREDENTIALS).

Dry run (read-only, lists tomorrow's free slots):
  PYTHONPATH=tools channels/.venv/bin/python -m rentus_tools.live.calendar_adapter slots [--date YYYY-MM-DD] [--calendar ID]
"""
from __future__ import annotations

import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from ..errors import ToolError

REPO = Path(__file__).resolve().parents[3]
API = "https://www.googleapis.com/calendar/v3"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPE_READ = "https://www.googleapis.com/auth/calendar.readonly"
SCOPE_WRITE = "https://www.googleapis.com/auth/calendar.events"
DEFAULT_ENV_FILE = "~/rental-management/.env.production"
TAG = "_calendar_live"


class CalendarNotConfigured(RuntimeError):
    pass


def _read_env_file(path) -> dict:
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    from channels.inbound.imap_reader import _read_env_file as read

    return read(path)


def settings(env: dict | None = None) -> dict:
    env = dict(os.environ if env is None else env)
    hours = env.get("CHANNELS_SHOWINGS_HOURS", "08:00-20:00")
    start, end = hours.split("-")
    busy_extra = [c.strip() for c in env.get("CHANNELS_SHOWINGS_BUSY_CALENDAR_IDS", "").split(",") if c.strip()]
    target = env.get("CHANNELS_SHOWINGS_CALENDAR_ID", "").strip()
    return {"target": target, "read": ([target] if target else []) + [c for c in busy_extra if c != target],
            "start": start.strip(), "end": end.strip(), "slot_minutes": int(env.get("CHANNELS_SHOWINGS_SLOT_MINUTES", 30)),
            "tz": env.get("CHANNELS_SHOWINGS_TZ", "America/New_York")}


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


class GoogleCalendar:
    """Service-account client: free/busy (read) and events.insert (write). No attendees, ever."""

    def __init__(self, client_email: str, private_key: str, opener=None):
        self.client_email = client_email
        self._key = private_key.replace("\\n", "\n")
        self._tokens: dict[str, tuple[str, float]] = {}
        self._open = opener or urllib.request.urlopen

    def __repr__(self) -> str:  # never show the key
        return "GoogleCalendar(<service account>)"

    @classmethod
    def from_env(cls, env: dict | None = None) -> "GoogleCalendar":
        env = dict(os.environ if env is None else env)
        file_env = _read_env_file(env.get("CHANNELS_GOOGLE_ENV_FILE") or DEFAULT_ENV_FILE)
        merged = {**file_env, **env}
        var = merged.get("CHANNELS_GOOGLE_CREDENTIALS_VAR")
        if var and merged.get(var):
            j = json.loads(merged[var])
            return cls(j["client_email"], j["private_key"])
        email, key = merged.get("GOOGLE_SERVICE_ACCOUNT_EMAIL", ""), merged.get("GOOGLE_PRIVATE_KEY", "")
        if not (email and key):
            raise CalendarNotConfigured("no Google service account: set GOOGLE_SERVICE_ACCOUNT_EMAIL + GOOGLE_PRIVATE_KEY "
                                        "(or CHANNELS_GOOGLE_CREDENTIALS_VAR) in CHANNELS_GOOGLE_ENV_FILE")
        return cls(email, key)

    def _token(self, scope: str) -> str:
        tok = self._tokens.get(scope)
        if tok and tok[1] > time.time() + 60:
            return tok[0]
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding

        now = int(time.time())
        head = _b64(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
        claims = _b64(json.dumps({"iss": self.client_email, "scope": scope, "aud": TOKEN_URL,
                                  "iat": now, "exp": now + 3600}).encode())
        key = serialization.load_pem_private_key(self._key.encode(), password=None)
        sig = key.sign(f"{head}.{claims}".encode(), padding.PKCS1v15(), hashes.SHA256())
        body = urllib.parse.urlencode({"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                                       "assertion": f"{head}.{claims}.{_b64(sig)}"}).encode()
        data = self._request("POST", TOKEN_URL, body, {"Content-Type": "application/x-www-form-urlencoded"})
        self._tokens[scope] = (data["access_token"], now + int(data.get("expires_in", 3600)))
        return data["access_token"]

    def _request(self, method: str, url: str, body: bytes | None, headers: dict) -> dict:
        req = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            with self._open(req, timeout=20) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            try:
                err = json.loads(e.read()).get("error", {})
                msg = err.get("message") or err.get("error_description") or str(err) if isinstance(err, dict) else str(err)
            except Exception:
                msg = e.reason
            raise ToolError("UPSTREAM_ERROR", f"Google Calendar HTTP {e.code}: {msg}", retryable=e.code >= 500)

    def _api(self, method: str, path: str, scope: str, payload: dict | None = None) -> dict:
        body = json.dumps(payload).encode() if payload is not None else None
        return self._request(method, API + path, body, {"Authorization": f"Bearer {self._token(scope)}",
                                                        "Content-Type": "application/json"})

    def freebusy(self, calendar_ids: list[str], t0: datetime, t1: datetime) -> list[tuple[datetime, datetime]]:
        """Busy intervals (aware, UTC) across the calendars. Raises ToolError if any calendar can't be read."""
        data = self._api("POST", "/freeBusy", SCOPE_READ, {
            "timeMin": t0.astimezone(timezone.utc).isoformat(), "timeMax": t1.astimezone(timezone.utc).isoformat(),
            "items": [{"id": c} for c in calendar_ids]})
        busy, bad = [], []
        for cid, cal in (data.get("calendars") or {}).items():
            if cal.get("errors"):
                bad.append(cal["errors"][0].get("reason", "error"))
            for b in cal.get("busy", []):
                busy.append((_parse_rfc3339(b["start"]), _parse_rfc3339(b["end"])))
        if bad:
            raise ToolError("UPSTREAM_ERROR", f"Google Calendar free/busy refused {len(bad)} calendar(s): {', '.join(sorted(set(bad)))}",
                            hint="share the calendar with the service account (at least 'See all event details')",
                            details={"service_account_domain": self.client_email.split("@")[-1]})
        return busy

    def insert_event(self, calendar_id: str, summary: str, start: datetime, end: datetime, description: str, tz: str) -> dict:
        payload = {"summary": summary, "description": description,
                   "start": {"dateTime": start.isoformat(), "timeZone": tz},
                   "end": {"dateTime": end.isoformat(), "timeZone": tz},
                   "transparency": "opaque", "reminders": {"useDefault": True}}
        assert "attendees" not in payload
        cid = urllib.parse.quote(calendar_id, safe="")
        return self._api("POST", f"/calendars/{cid}/events?sendUpdates=none", SCOPE_WRITE, payload)


def _parse_rfc3339(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def free_slots(busy, day: date, cfg: dict, now: datetime) -> list[dict]:
    """Slots on `day` within showing hours that start after `now` and touch no busy interval (all aware)."""
    tz = ZoneInfo(cfg["tz"])
    sh, sm = map(int, cfg["start"].split(":"))
    eh, em = map(int, cfg["end"].split(":"))
    s, stop = datetime(day.year, day.month, day.day, sh, sm, tzinfo=tz), datetime(day.year, day.month, day.day, eh, em, tzinfo=tz)
    step, out = timedelta(minutes=cfg["slot_minutes"]), []
    while s + step <= stop:
        e = s + step
        if s > now and all(e <= b0 or s >= b1 for b0, b1 in busy):
            out.append({"start": s.isoformat(timespec="minutes"), "end": e.isoformat(timespec="minutes")})
        s = e
    return out


# ---- registry wrappers ---------------------------------------------------------------------------

_STATE: dict = {}


def _client():
    if "client" not in _STATE:
        _STATE["client"] = GoogleCalendar.from_env()
    return _STATE["client"]


def _live_context(world, cfg, d0: datetime, d1: datetime):
    """Swap in live hours + real clock and inject Google busy blocks as temporary events for every room.
    Returns a restore() callable."""
    tz = ZoneInfo(cfg["tz"])
    saved = {"hours": world.policy.get("showing_hours"), "now": world.clock["now"], "n": len(world.calendar)}
    world.policy["showing_hours"] = {"days": list(range(7)), "start": cfg["start"], "end": cfg["end"],
                                     "slot_minutes": cfg["slot_minutes"]}
    world.clock["now"] = datetime.now(tz).replace(tzinfo=None).isoformat(timespec="seconds")
    busy = []
    if cfg["read"]:
        busy = _client().freebusy(cfg["read"], d0.replace(tzinfo=tz), d1.replace(tzinfo=tz))
    # sandbox events for ANY room block the owner too (no overlaps across rooms)
    others = [e for e in world.calendar if e.get("status") in ("proposed", "confirmed")]
    for r in world.rooms:
        rid = r.get("room_id")
        for b0, b1 in busy:
            world.calendar.append({"status": "proposed", "room_id": rid, TAG: True,
                                   "start": b0.astimezone(tz).replace(tzinfo=None).isoformat(timespec="minutes"),
                                   "end": b1.astimezone(tz).replace(tzinfo=None).isoformat(timespec="minutes")})
        for e in others:
            if e.get("room_id") != rid:
                world.calendar.append({**{k: e[k] for k in ("start", "end")}, "status": "proposed", "room_id": rid, TAG: True})

    def restore():
        world.calendar[:] = [e for e in world.calendar if not e.get(TAG)]
        world.policy["showing_hours"] = saved["hours"]
        world.clock["now"] = saved["now"]
    return restore, busy


def _wrap_find(fn):
    def wrapped(world, room_id: str, date_from: str, date_to: str, **kw):
        if getattr(world, "mode", "sandbox") != "live":
            return fn(world, room_id=room_id, date_from=date_from, date_to=date_to, **kw)
        cfg = settings()
        try:
            d0, d1 = datetime.fromisoformat(date_from), datetime.fromisoformat(date_to) + timedelta(days=1)
        except ValueError:
            return fn(world, room_id=room_id, date_from=date_from, date_to=date_to, **kw)  # let the tool report it
        restore, _ = _live_context(world, cfg, d0, d1)
        try:
            out = fn(world, room_id=room_id, date_from=date_from, date_to=date_to, **kw)
        finally:
            restore()
        out["timezone"] = cfg["tz"]
        out["calendar"] = {"read": len(cfg["read"]), "target_set": bool(cfg["target"])}
        if not cfg["read"]:
            out["calendar_warning"] = "CHANNELS_SHOWINGS_CALENDAR_ID is not set: slots ignore the owner's Google calendar"
        return out
    wrapped._orig, wrapped._calendar_live = fn, True
    return wrapped


def _wrap_propose(fn):
    def wrapped(world, renter_id: str, room_id: str, start: str, **kw):
        if getattr(world, "mode", "sandbox") != "live":
            return fn(world, renter_id=renter_id, room_id=room_id, start=start, **kw)
        cfg = settings()
        try:
            s = datetime.fromisoformat(start)
        except ValueError:
            return fn(world, renter_id=renter_id, room_id=room_id, start=start, **kw)
        day = datetime(s.year, s.month, s.day)
        renter_before = dict(world.get("register", renter_id) or {})
        restore, _ = _live_context(world, cfg, day, day + timedelta(days=1))
        try:
            out = fn(world, renter_id=renter_id, room_id=room_id, start=start, **kw)
        finally:
            restore()
        ev = out["event"]
        if not cfg["target"]:
            ev["calendar"] = {"status": "not_written", "reason": "CHANNELS_SHOWINGS_CALENDAR_ID is not set"}
            return out
        tz = ZoneInfo(cfg["tz"])
        st, en = datetime.fromisoformat(ev["start"]).replace(tzinfo=tz), datetime.fromisoformat(ev["end"]).replace(tzinfo=tz)
        name = _renter_name(world, renter_id)
        try:
            if _client().freebusy(cfg["read"], st, en):
                raise ToolError("CONFLICT", f"{ev['start']} was just taken on the owner's calendar", hint="use find_showing_slots")
            g = _client().insert_event(cfg["target"], f"PROPOSED: Showing with {name}", st, en,
                                       f"Proposed by the Rent Us operator. Room {room_id}, renter {renter_id}, "
                                       f"sandbox event {ev['event_id']}. Not confirmed with the renter yet.", cfg["tz"])
        except ToolError:
            _rollback(world, ev["event_id"], renter_id, renter_before)
            raise
        for e in world.calendar:
            if e.get("event_id") == ev["event_id"]:
                e["google_event_id"] = g.get("id")
        ev["google_event_id"] = g.get("id")
        ev["calendar"] = {"status": "written", "title": f"PROPOSED: Showing with {name}"}
        return out
    wrapped._orig, wrapped._calendar_live = fn, True
    return wrapped


def _renter_name(world, renter_id: str) -> str:
    r = world.get("register", renter_id)
    first = ((r or {}).get("name") or "").strip().split()
    return first[0] if first else "renter"


def _rollback(world, event_id: str, renter_id: str, renter_before):
    world.calendar[:] = [e for e in world.calendar if e.get("event_id") != event_id]
    r = world.get("register", renter_id)
    if r is not None and "status" in renter_before:
        r["status"] = renter_before["status"]


def register_calendar(client: GoogleCalendar | None = None) -> None:
    from .. import core, impl  # noqa: F401  (populate the registry before wrapping)

    if client is not None:
        _STATE["client"] = client
    for name, wrap in (("find_showing_slots", _wrap_find), ("propose_showing", _wrap_propose)):
        fn = core.REGISTRY.get(name)
        if fn is not None and not getattr(fn, "_calendar_live", False):
            core.REGISTRY[name] = wrap(fn)


def uninstall_calendar() -> None:
    from .. import core

    for name in ("find_showing_slots", "propose_showing"):
        fn = core.REGISTRY.get(name)
        if getattr(fn, "_calendar_live", False):
            core.REGISTRY[name] = fn._orig
    _STATE.clear()


# ---- CLI: read-only dry run ----------------------------------------------------------------------

def main(argv: list[str]) -> int:
    import argparse

    p = argparse.ArgumentParser(prog="rentus_tools.live.calendar_adapter")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("slots", help="list free showing slots (read-only)")
    s.add_argument("--date", help="YYYY-MM-DD, default tomorrow")
    s.add_argument("--calendar", action="append", help="calendar id to read (read-only); default from env")
    a = p.parse_args(argv)
    cfg = settings()
    tz = ZoneInfo(cfg["tz"])
    day = date.fromisoformat(a.date) if a.date else datetime.now(tz).date() + timedelta(days=1)
    cals = a.calendar or cfg["read"]
    out = {"date": day.isoformat(), "hours": f"{cfg['start']}-{cfg['end']}", "timezone": cfg["tz"],
           "calendars_read": len(cals), "writes_enabled": bool(cfg["target"])}
    busy = []
    if cals:
        try:
            gc = GoogleCalendar.from_env()
            t0 = datetime(day.year, day.month, day.day, tzinfo=tz)
            busy = gc.freebusy(cals, t0, t0 + timedelta(days=1))
        except (ToolError, CalendarNotConfigured) as e:
            out["error"] = e.envelope()["error"] if isinstance(e, ToolError) else str(e)
            print(json.dumps(out, indent=2))
            return 1
    else:
        out["warning"] = "no calendar to read: set CHANNELS_SHOWINGS_CALENDAR_ID (or pass --calendar)"
    slots = free_slots(busy, day, cfg, datetime.now(tz))
    out.update({"busy_blocks": len(busy), "free_slots": len(slots), "slots": [x["start"][11:16] for x in slots]})
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
