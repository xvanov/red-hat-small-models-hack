"""SMS channel: inbound texts become threads, replies go to the local outbox, sending is disabled."""
import pytest

from channels.inbound import sms
from channels.inbound.store import ChannelStore


@pytest.fixture
def store(tmp_path):
    return ChannelStore(tmp_path / "inbox")


def test_text_thread_and_outbox_draft(store):
    t = sms.ingest_text(store, phone="(919) 555-0101", text="Is the room on Appling Way still open?")
    assert t["thread_id"].startswith("sms:") and t["contact"]["phone"] == "+19195550101"
    assert t["renter_name"] == "+1******0101"
    again = sms.ingest_text(store, phone="919.555.0101", text="I can move in Nov 1")
    assert again["thread_id"] == t["thread_id"] and len(again["messages"]) == 2
    d = sms.save_reply_draft(store, t["thread_id"], "Yes, it is available November 1.")
    assert d["status"] == "draft_saved" and d["sent"] is False and d["to"] == "+19195550101"
    assert "drafts only" in d["reason"]
    lines = store.outbox_path("sms").read_text().splitlines()
    assert len(lines) == 1 and '"sent": false' in lines[0]


def test_twilio_stub_is_disabled():
    s = sms.TwilioSender()
    assert s.enabled is False
    with pytest.raises(sms.SendDisabled):
        s.send("+19195550101", "hello")


def test_empty_input_rejected(store):
    with pytest.raises(ValueError):
        sms.ingest_text(store, phone="", text="hi")
