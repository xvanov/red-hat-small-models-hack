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


class FakeGoogle:
    def __init__(self, busy=(), fail_insert=False):
        self.busy, self.fail_insert, self.inserted, self.reads = list(busy), fail_insert, [], 0

    def freebusy(self, cals, t0, t1):
        self.reads += 1
        return [(b0, b1) for b0, b1 in self.busy if b0 < t1 and b1 > t0]

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
