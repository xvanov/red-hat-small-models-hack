"""rentus_tools in live mode with the email/SMS channels registered: threads sync in, replies are drafts."""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
rt = pytest.importorskip("rentus_tools")
pytest.importorskip("jsonschema")

from channels.inbound import email_channel, sms  # noqa: E402
from channels.inbound.store import ChannelStore  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "email"


@pytest.fixture
def live_world(tmp_path, monkeypatch):
    from rentus_tools import live
    from rentus_tools.live import inbound_adapter

    monkeypatch.setattr(live, "ADAPTERS", {})
    store = ChannelStore(tmp_path / "inbox")
    email_channel.ingest_files(store, sorted(FIX.glob("*.eml")))
    sms.ingest_text(store, phone="919-555-0101", text="Hi, is the room still available?")
    inbound_adapter.register_inbound(store)
    world = rt.load()
    world.mode = "live"
    yield world, store
    inbound_adapter.uninstall_sync()


def test_list_and_read_threads_route_to_inbound(live_world):
    world, store = live_world
    res = rt.call(world, "list_threads", {"channel": "email"})
    assert res["ok"], res
    ids = {t["thread_id"] for t in res["data"]["threads"]}
    assert len(ids) == 5 and all(i.startswith("email:") for i in ids)
    assert all(t["unanswered"] for t in res["data"]["threads"])
    sms_res = rt.call(world, "list_threads", {"channel": "sms", "unanswered_only": True})
    assert sms_res["data"]["count"] == 1
    tid = next(iter(ids))
    th = rt.call(world, "read_thread", {"thread_id": tid})
    assert th["ok"] and th["data"]["thread"]["messages"][0]["from"] == "renter"
    # a second sync adds nothing
    again = rt.call(world, "list_threads", {"channel": "email"})
    assert again["data"]["count"] == 5 and len(world.threads) == len({t["thread_id"] for t in world.threads})


def test_send_message_saves_a_draft_never_sends(live_world):
    world, store = live_world
    t = next(t for t in rt.call(world, "list_threads", {"channel": "email"})["data"]["threads"]
             if t["renter_name"] == "Jordan")
    res = rt.call(world, "send_message", {"thread_id": t["thread_id"], "text": "Yes, it is available November 1."})
    assert res["ok"], res
    assert res["data"]["status"] == "draft_saved"
    drafts = store.drafts("email")
    assert len(drafts) == 1 and drafts[0]["sent"] is False and "Roomies" in drafts[0]["reason"]
    s = rt.call(world, "list_threads", {"channel": "sms"})["data"]["threads"][0]
    res2 = rt.call(world, "send_message", {"thread_id": s["thread_id"], "text": "Yes, it is still available."})
    assert res2["ok"] and res2["data"]["status"] == "draft_saved"
    assert len(store.drafts("sms")) == 1


def test_send_guards_still_apply_before_any_draft(live_world):
    world, store = live_world
    threads = rt.call(world, "list_threads", {"channel": "email"})["data"]["threads"]
    t = next(x for x in threads if x["renter_name"] == "Riley Chen")
    long = "Sure. It is open. Come see it. Saturday works?"
    res = rt.call(world, "send_message", {"thread_id": t["thread_id"], "text": long})
    assert not res["ok"] and res["error"]["code"] == "POLICY_BLOCKED"
    es = next(x for x in threads if x["renter_name"] == "Maria Lopez")
    res = rt.call(world, "send_message", {"thread_id": es["thread_id"], "text": "Yes, the room is available."})
    assert not res["ok"] and "Spanish" in res["error"]["message"]
    assert store.drafts() == []


def test_sandbox_mode_is_untouched(live_world):
    world, _ = live_world
    world.mode = "sandbox"
    res = rt.call(world, "list_threads", {"channel": "email"})
    assert res["ok"] and res["data"]["count"] == 0


def test_register_live_wires_everything(tmp_path, monkeypatch):
    from rentus_tools import live
    from rentus_tools.live import inbound_adapter

    monkeypatch.setattr(live, "ADAPTERS", {})
    try:
        out = live.register_live("mock", store=ChannelStore(tmp_path / "x"))
        assert set(live.ADAPTERS) == {"marketplace", "roomies", "craigslist", "padsplit", "email", "sms"}
        assert out["email"].store is out["sms"].store
        with pytest.raises(rt.ToolError) as e:
            out["email"].publish_listing(None, {}, "email")
        assert e.value.code == "POLICY_BLOCKED"
        assert out["calendar"] == "google" and getattr(rt.core.REGISTRY["propose_showing"], "_calendar_live", False)
    finally:
        inbound_adapter.uninstall_sync()
        from rentus_tools.live import calendar_adapter
        calendar_adapter.uninstall_calendar()
