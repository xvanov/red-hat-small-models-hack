"""Live Google Calendar adapter behind find_showing_slots / propose_showing, with a fake Google client."""
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
rt = pytest.importorskip("rentus_tools")
pytest.importorskip("jsonschema")

from rentus_tools.errors import ToolError  # noqa: E402
from rentus_tools.live import calendar_adapter as ca  # noqa: E402

TZ = ZoneInfo("America/New_York")
TOMORROW = (datetime.now(TZ) + timedelta(days=1)).date()
GATE = {"lease": {"status": "answered", "value": True},
        "move_in": {"status": "answered", "date": "2026-11-01", "raw": "Nov 1st"},
        "phone": {"status": "answered", "value": "+19195550123"},
        "occupants": {"status": "answered", "value": 1},
        "reason": {"status": "answered", "value": "new job at Duke"}}
THREAD = {"thread_id": "T001", "channel": "marketplace", "renter_name": "Maria Lopez", "language": "en", "room_id": "R023",
          "messages": [{"from": "renter", "text": "Hi, is the room still available?"}]}


def _ev(summary, start, end, transparency=None, all_day=False):
    if all_day:
        ev = {"summary": summary, "start": {"date": start.isoformat()}, "end": {"date": end.isoformat()}}
    else:
        ev = {"summary": summary, "start": {"dateTime": start.isoformat()}, "end": {"dateTime": end.isoformat()}}
    if transparency:
        ev["transparency"] = transparency
    return ev


class FakeGoogle:
    """busy=[(start, end)] become existing showing events; events=[...] are raw Google event dicts."""

    def __init__(self, busy=(), fail_insert=False, events=()):
        self.busy, self.fail_insert, self.inserted, self.reads = list(busy), fail_insert, [], 0
        self.events = [_ev("Showing with Bob", b0, b1) for b0, b1 in busy] + list(events)

    def list_events(self, cal, t0, t1):
        self.reads += 1
        out = []
        for e in self.events + [_ev(i["summary"], i["start"], i["end"]) for i in self.inserted]:
            b = ca._event_bounds(e, TZ)
            if b[0] < t1 and b[1] > t0:
                out.append(e)
        return out

    def insert_event(self, calendar_id, summary, start, end, description, tz):
        if self.fail_insert:
            raise ToolError("UPSTREAM_ERROR", "Google Calendar HTTP 403: forbidden")
        self.inserted.append({"calendar_id": calendar_id, "summary": summary, "start": start, "end": end})
        return {"id": f"g{len(self.inserted)}"}


def _at(h, m=0):
    return datetime(TOMORROW.year, TOMORROW.month, TOMORROW.day, h, m, tzinfo=TZ)


@pytest.fixture
def make_world(monkeypatch):
    made = []

    def make(fake, target="owner-showings@group.calendar.google.com"):
        if target:
            monkeypatch.setenv("CHANNELS_SHOWINGS_CALENDAR_ID", target)
        else:
            monkeypatch.delenv("CHANNELS_SHOWINGS_CALENDAR_ID", raising=False)
        ca.register_calendar(fake)
        made.append(1)
        w = rt.load(patch={"threads": [THREAD]})
        w.mode = "live"
        rid = rt.call(w, "upsert_renter", {"thread_id": "T001", "fields": {"name": "Maria Lopez", "gate": GATE}})["data"]["renter"]["renter_id"]
        return w, rid

    yield make
    ca.uninstall_calendar()


def test_slots_use_owner_hours_and_skip_google_busy(make_world):
    fake = FakeGoogle(busy=[(_at(9), _at(11))])
    w, _ = make_world(fake)
    clock = dict(w.clock)
    res = rt.call(w, "find_showing_slots", {"room_id": "R023", "date_from": TOMORROW.isoformat(), "date_to": TOMORROW.isoformat()})
    assert res["ok"], res
    starts = [s["start"][11:16] for s in res["data"]["slots"]]
    assert starts[0] == "08:00" and starts[-1] == "19:30" and len(starts) == 24 - 4
    assert "09:00" not in starts and "10:30" not in starts and "11:00" in starts
    assert w.calendar == [] and w.clock == clock  # temporary busy blocks and the sandbox clock are restored


def test_propose_writes_one_proposed_event_without_attendees(make_world):
    fake = FakeGoogle()
    w, rid = make_world(fake)
    res = rt.call(w, "propose_showing", {"renter_id": rid, "room_id": "R023", "start": f"{TOMORROW}T08:00"})
    assert res["ok"], res
    ev = res["data"]["event"]
    assert ev["calendar"]["status"] == "written" and ev["google_event_id"] == "g1"
    assert fake.inserted == [{"calendar_id": "owner-showings@group.calendar.google.com", "summary": "PROPOSED: Showing with Maria",
                              "start": _at(8), "end": _at(8, 30)}]
    # no overlaps: the same slot is gone for any room afterwards
    other = next(r["room_id"] for r in w.rooms if r["room_id"] != "R023")
    slots = rt.call(w, "find_showing_slots", {"room_id": other, "date_from": TOMORROW.isoformat(), "date_to": TOMORROW.isoformat()})
    assert f"{TOMORROW}T08:00" not in [s["start"] for s in slots["data"]["slots"]]


def test_nothing_written_without_designated_calendar(make_world):
    fake = FakeGoogle()
    w, rid = make_world(fake, target=None)
    res = rt.call(w, "propose_showing", {"renter_id": rid, "room_id": "R023", "start": f"{TOMORROW}T12:00"})
    assert res["ok"], res
    assert res["data"]["event"]["calendar"]["status"] == "not_written" and fake.inserted == [] and fake.reads == 0


def test_google_busy_and_hours_refuse(make_world):
    fake = FakeGoogle(busy=[(_at(14), _at(15))])
    w, rid = make_world(fake)
    assert rt.call(w, "propose_showing", {"renter_id": rid, "room_id": "R023", "start": f"{TOMORROW}T14:30"})["error"]["code"] == "CONFLICT"
    assert rt.call(w, "propose_showing", {"renter_id": rid, "room_id": "R023", "start": f"{TOMORROW}T20:00"})["error"]["code"] == "CONFLICT"
    assert rt.call(w, "propose_showing", {"renter_id": rid, "room_id": "R023", "start": f"{TOMORROW}T07:30"})["error"]["code"] == "CONFLICT"
    assert fake.inserted == []


def test_failed_write_rolls_back(make_world):
    fake = FakeGoogle(fail_insert=True)
    w, rid = make_world(fake)
    res = rt.call(w, "propose_showing", {"renter_id": rid, "room_id": "R023", "start": f"{TOMORROW}T10:00"})
    assert res["error"]["code"] == "UPSTREAM_ERROR"
    assert w.calendar == [] and w.get("register", rid)["status"] != "showing_proposed"


def test_sandbox_mode_untouched(make_world):
    fake = FakeGoogle()
    w, rid = make_world(fake)
    w.mode = "sandbox"
    rt.call(w, "find_showing_slots", {"room_id": "R023", "date_from": TOMORROW.isoformat(), "date_to": TOMORROW.isoformat()})
    assert fake.reads == 0 and fake.inserted == []


def _slots(w, room="R023"):
    res = rt.call(w, "find_showing_slots", {"room_id": room, "date_from": TOMORROW.isoformat(), "date_to": TOMORROW.isoformat()})
    assert res["ok"], res
    return [s["start"][11:16] for s in res["data"]["slots"]]


def test_availability_block_is_the_window_not_a_busy_block(make_world):
    # the owner's real shape: an opaque 08:00-20:00 "Available for showings" block plus one existing showing
    fake = FakeGoogle(events=[_ev("Available for showings", _at(8), _at(20)),
                              _ev("Showing with Lamarr", _at(13), _at(13, 30))])
    w, _ = make_world(fake)
    starts = _slots(w)
    assert starts[0] == "08:00" and starts[-1] == "19:30" and len(starts) == 23 and "13:00" not in starts


def test_slots_only_inside_availability_blocks_clipped_to_hours(make_world, monkeypatch):
    monkeypatch.setenv("CHANNELS_SHOWINGS_AVAILABILITY_TITLE", "open house")
    fake = FakeGoogle(events=[_ev("OPEN HOUSE window", _at(6), _at(9)), _ev("Open house", _at(15), _at(17)),
                              _ev("PROPOSED: Showing with Ann", _at(16), _at(16, 30)),
                              _ev("Available for showings", _at(10), _at(12))])  # not the configured title, not a showing: ignored
    w, rid = make_world(fake)
    assert _slots(w) == ["08:00", "08:30", "15:00", "15:30", "16:30"]
    assert rt.call(w, "propose_showing", {"renter_id": rid, "room_id": "R023", "start": f"{TOMORROW}T12:30"})["error"]["code"] == "CONFLICT"
    assert rt.call(w, "propose_showing", {"renter_id": rid, "room_id": "R023", "start": f"{TOMORROW}T15:00"})["ok"]
    assert [i["summary"] for i in fake.inserted] == ["PROPOSED: Showing with Maria"]


def test_owner_other_events_are_ignored_only_showings_block(make_world, monkeypatch):
    # R-SHOW-3: the owner's other meetings never block; extra calendars are not read at all
    monkeypatch.setenv("CHANNELS_SHOWINGS_BUSY_CALENDAR_IDS", "other@group.calendar.google.com")
    nxt = TOMORROW + timedelta(days=1)
    fake = FakeGoogle(events=[_ev("Out of town", TOMORROW, nxt, all_day=True), _ev("Dentist", _at(9), _at(11)),
                              _ev("Holiday", TOMORROW, nxt, transparency="transparent", all_day=True)])
    w, _ = make_world(fake)
    assert len(_slots(w)) == 24 and fake.reads == 1  # no availability block: D29 default 08:00-20:00
    fake.events += [_ev("PROPOSED: Showing with Ann", _at(12), _at(12, 30)), _ev("Showing with Lamarr", _at(18), _at(19))]
    starts = _slots(w)
    assert len(starts) == 21 and "12:00" not in starts and "18:30" not in starts and "09:00" in starts
    assert ca.settings()["read"] == ["owner-showings@group.calendar.google.com"]


def test_blocking_intervals_fall_back_to_hours_per_day():
    cfg = ca.settings({"CHANNELS_SHOWINGS_TZ": "America/New_York"})
    d2 = TOMORROW + timedelta(days=1)
    win = [(_at(10), _at(12))]
    blocks = ca.blocking_intervals(win, [], TOMORROW, d2, cfg)
    assert blocks == [(_at(8), _at(10)), (_at(12), _at(20))]  # day 2 has no block: nothing added
