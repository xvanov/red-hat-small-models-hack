from pathlib import Path

import httpx
import pytest

from channels.adapters import api
from channels.mock_sites.app import STATE

EXPECT = {  # mock form field name (v1) -> value the adapter should have typed
    "marketplace": {"price": "750", "address": "Appling Way, Durham NC", "home_type": "Room only",
                    "available_date": "2026-11-01"},
    "roomies": {"rent": "750", "min_stay": "6 months", "private_bath": "yes", "headline": "Private room with own bath, Appling Way"},
    "craigslist": {"price": "750", "postal": "27703", "geographic_area": "Durham", "id": "rooms & shares",
                   "private_bath": "private bath"},
    "padsplit": {"weekly_price": "173", "address": "Appling Way, Durham NC", "private_bath": "yes"},
}


@pytest.mark.parametrize("platform", api.PLATFORMS)
def test_publish_stops_before_submit(platform, base_url, sel_dir, listing):
    r = api.publish_listing(listing, platform, base_url=base_url, selectors_dir=sel_dir, repair=False)
    assert r["ok"], r
    d = r["data"]
    assert d["status"] == "ready_to_submit" and Path(d["screenshot"]).exists()
    assert STATE.listings[platform] == []  # nothing was posted


@pytest.mark.parametrize("platform", api.PLATFORMS)
def test_mock_submit_fills_the_right_fields(platform, base_url, sel_dir, listing):
    r = api.publish_listing(listing, platform, base_url=base_url, selectors_dir=sel_dir, repair=False, submit=True)
    assert r["ok"] and r["data"]["status"] == "live", r
    posted = STATE.listings[platform][0]
    for k, v in EXPECT[platform].items():
        assert posted["fields"].get(k) == v, (k, posted["fields"])
    assert len(posted["photos"]) == 3


def test_live_submit_is_refused(listing):
    r = api.publish_listing(listing, "marketplace", target="live", submit=True)
    assert not r["ok"] and r["error"]["code"] == "POLICY_BLOCKED"


def test_live_inbox_is_not_automated():
    for r in (api.list_threads("marketplace", target="live"), api.send_message("marketplace:t1", "hi", target="live")):
        assert not r["ok"] and r["error"]["code"] == "UPSTREAM_ERROR"


def test_login_wall_reports_login_required(base_url, sel_dir, listing):
    httpx.post(base_url + "/_admin/config", json={"craigslist": {"login_wall": "on"}})
    r = api.publish_listing(listing, "craigslist", base_url=base_url, selectors_dir=sel_dir, repair=False)
    assert not r["ok"] and r["error"]["code"] == "LOGIN_REQUIRED"


def test_missing_required_value_is_invalid_args(base_url, sel_dir, listing):
    listing["body"] = ""
    r = api.publish_listing(listing, "roomies", base_url=base_url, selectors_dir=sel_dir, repair=False)
    assert not r["ok"] and r["error"]["code"] == "INVALID_ARGS"


def test_inbox_list_read_send(base_url, sel_dir):
    kw = dict(base_url=base_url, selectors_dir=sel_dir, repair=False)
    r = api.list_threads("padsplit", unanswered_only=True, **kw)
    assert r["ok"] and len(r["data"]["threads"]) == 2
    tid = r["data"]["threads"][1]["thread_id"]
    th = api.read_thread(tid, **kw)["data"]["thread"]
    assert th["messages"][0]["from"] == "renter" and "disponible" in th["messages"][0]["text"]
    s = api.send_message(tid, "Sí, está disponible desde el 1 de noviembre.", **kw)
    assert s["ok"], s
    assert STATE.threads["padsplit"][1]["messages"][-1]["from"] == "operator"
    left = api.list_threads("padsplit", unanswered_only=True, **kw)["data"]["threads"]
    assert [t["thread_id"] for t in left] == [r["data"]["threads"][0]["thread_id"]]
