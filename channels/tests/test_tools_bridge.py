"""rentus_tools (W3) in live mode, routed through channels via tools/rentus_tools/live/channels_adapter.py."""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
rt = pytest.importorskip("rentus_tools")
pytest.importorskip("jsonschema")

from channels.mock_sites.app import STATE  # noqa: E402


@pytest.fixture
def bridged(base_url, monkeypatch):
    from rentus_tools import live
    from rentus_tools.live.channels_adapter import register_all

    monkeypatch.setattr(live, "ADAPTERS", {})
    return register_all("mock", base_url=base_url)


def test_publish_listing_tool_in_live_mode_hits_mock_and_stops(bridged):
    world = rt.load()
    world.mode = "live"
    room = world.rooms[0]
    price = room["rent"]
    made = rt.call(world, "create_listing", {"room_id": room["room_id"], "title": "Private room, own bath",
                                             "body": "Quiet room in a shared house. Utilities included.",
                                             "price": price})
    assert made["ok"], made
    lid = made["data"]["listing"]["listing_id"]
    res = rt.call(world, "publish_listing", {"listing_id": lid, "channel": "roomies"})
    assert res["ok"], res
    assert res["data"]["status"] == "ready_to_submit" and Path(res["data"]["screenshot"]).exists()
    assert STATE.listings["roomies"] == []
