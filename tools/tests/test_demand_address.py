"""Gap 5: public text and prospect messages never give a house number before a confirmed showing."""
import pytest

from conftest import COMPLETE_GATE, call_err, call_ok
from rentus_tools.impl.demand_guards import house_numbers, public_street

ROOMS = [{"address": "1316 Marrowstone St, Durham, NC 27707 (fictional)"},
         {"address": "4110 Odessa Gate Ln, Durham, NC 27704 (fictional)"}]


@pytest.mark.parametrize("text", ["The room is at 1316 Marrowstone St.", "It's 4110 Odessa Gate Ln in Durham.",
                                  "Come to 1316 Marrowstone at 11.", "Address: 22 Oak Ave, Raleigh"])
def test_house_numbers_found(text):
    assert house_numbers(text, ROOMS), text


@pytest.mark.parametrize("text", ["The room is on Marrowstone St in Durham.", "Rent is $750 a month, 2 people max.",
                                  "Available Nov 1, showings 10 AM to 6 PM.", "It's a 1 year lease, deposit $750.",
                                  "Call me at 919-555-0123."])
def test_no_house_number(text):
    assert house_numbers(text, ROOMS) == [], text


def test_public_street():
    assert public_street("1316 Marrowstone St, Durham, NC 27707 (fictional)") == "Marrowstone St"


def _addr(world):
    return world.get("rooms", "R023")["address"].split(",")[0]


def test_send_message_blocks_address_until_confirmed(world):
    addr = _addr(world)
    e = call_err(world, "send_message", {"thread_id": "T001", "text": f"The room is at {addr}."}, "POLICY_BLOCKED")
    assert e["details"]["rules"] == ["address_private"] and public_street(addr) in e["hint"]
    call_ok(world, "send_message", {"thread_id": "T001", "text": f"The room is on {public_street(addr)}."})
    call_ok(world, "upsert_renter", {"thread_id": "T001", "fields": {"gate": COMPLETE_GATE}})
    rid = world.register[0]["renter_id"]
    ev = call_ok(world, "propose_showing", {"renter_id": rid, "room_id": "R023", "start": "2026-10-24T11:00"})["event"]
    call_err(world, "send_message", {"thread_id": "T001", "text": f"The address is {addr}."}, "POLICY_BLOCKED")
    world.get("calendar", ev["event_id"])["status"] = "confirmed"
    call_ok(world, "send_message", {"thread_id": "T001", "text": f"The address is {addr}."})


def test_listing_tools_refuse_house_numbers(world):
    addr = _addr(world)
    rent = world.get("rooms", "R023")["rent"]
    e = call_err(world, "create_listing", {"room_id": "R023", "title": f"Room at {addr}", "body": f"${rent} a month.",
                                           "price": rent}, "POLICY_BLOCKED")
    assert e["details"]["rules"] == ["address_public"]
    lid = call_ok(world, "create_listing", {"room_id": "R023", "title": f"Room on {public_street(addr)}",
                                            "body": f"${rent} a month.", "price": rent})["listing"]["listing_id"]
    call_err(world, "update_listing", {"listing_id": lid, "fields": {"body": f"At {addr}."}}, "POLICY_BLOCKED")
    world.get("listings", lid)["body"] = f"At {addr}."   # edited behind the tools' back
    call_err(world, "publish_listing", {"listing_id": lid, "channel": "marketplace"}, "POLICY_BLOCKED")
