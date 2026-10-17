import pytest

import rentus_tools as rt

THREAD = {"thread_id": "T001", "channel": "marketplace", "renter_name": "Maria", "language": "en", "room_id": "R023",
          "messages": [{"from": "renter", "text": "Hi, is the Appling Way room still available?"}]}

COMPLETE_GATE = {
    "lease": {"status": "answered", "value": True},
    "move_in": {"status": "answered", "date": "2026-11-01", "raw": "Nov 1st"},
    "phone": {"status": "answered", "value": "+19195550123"},
    "occupants": {"status": "answered", "value": 1},
    "reason": {"status": "answered", "value": "new job at Duke"},
}


@pytest.fixture
def world():
    w = rt.load(patch={"threads": [THREAD], "clock": {"now": "2026-10-17T09:00:00"}})
    return w


@pytest.fixture
def sink():
    return rt.EventSink(run_id="r_test", clock=lambda: "2026-10-17T13:00:00Z")


def call_ok(world, name, args, **kw):
    r = rt.call(world, name, args, **kw)
    assert r["ok"], r
    return r["data"]


def call_err(world, name, args, code, **kw):
    r = rt.call(world, name, args, **kw)
    assert not r["ok"], r
    assert r["error"]["code"] == code, r
    assert r["error"]["message"]
    return r["error"]
