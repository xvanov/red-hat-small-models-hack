"""Schemas, world load/patch/diff/save, call() validation, events, faults."""
import json

import pytest

import rentus_tools as rt
from rentus_tools.world import get_path, merge

from conftest import call_err, call_ok


# ---------------------------------------------------------------- schemas

def test_every_contract_tool_has_schema_and_impl():
    expected = {"list_rooms", "get_room", "update_room", "create_listing", "publish_listing", "update_listing", "mark_filled",
                "get_listing_media", "check_listing_compliance", "get_market_rent", "list_threads", "read_thread",
                "send_message", "read_reply", "upsert_renter", "match_renters", "find_showing_slots", "propose_showing",
                "web_search", "fetch_page", "find_vendors", "request_quote", "book_vendor", "create_job",
                "escalate_to_owner", "report_to_owner"}
    assert set(rt.TOOL_NAMES) == expected
    assert set(rt.REGISTRY) == expected


@pytest.mark.parametrize("variant", ["verbose", "terse"])
def test_schemas_are_openai_function_format(variant):
    tools = rt.tool_schemas(variant)
    assert len(tools) == 26
    for t in tools:
        assert t["type"] == "function"
        fn = t["function"]
        assert fn["name"] and fn["description"]
        assert fn["parameters"]["type"] == "object"
        json.dumps(t)
    names = [t["function"]["name"] for t in tools]
    assert len(names) == len(set(names))


def test_description_variants_differ_and_override():
    v = {t["function"]["name"]: t["function"]["description"] for t in rt.tool_schemas("verbose")}
    t = {t["function"]["name"]: t["function"]["description"] for t in rt.tool_schemas("terse")}
    assert all(len(t[n]) < len(v[n]) for n in v)
    o = rt.tool_schemas("terse", descriptions={"get_room": "X"}, only=["get_room"])
    assert o[0]["function"]["description"] == "X"
    with pytest.raises(KeyError):
        rt.tool_schemas("nope")


# ---------------------------------------------------------------- world

def test_load_inventory_and_vendors(world):
    assert len(world.rooms) == 30
    assert len(world.vendors) == 12
    r = world.get("rooms", "R023")
    assert r["address_public"] == r["address"]
    assert "T001" in world.channels["marketplace"]["threads"]
    assert world.threads[0]["messages"][0]["id"] == "T001-m1"


def test_patch_upserts_by_id_and_replace():
    w = rt.load(patch={"rooms": [{"room_id": "R023", "rent": 750}, {"room_id": "R999", "area": "Durham", "zip": "27701",
                                                                       "rent": 600, "available_from": "2026-11-01"}],
                       "policy": {"spend_limit_usd": 300}})
    assert w.get("rooms", "R023")["rent"] == 750
    assert w.get("rooms", "R023")["type"]  # other fields kept
    assert w.get("rooms", "R999")["rent"] == 600
    assert w.policy["spend_limit_usd"] == 300 and w.policy["lease_floor_months"] == 6
    w2 = rt.load(patch={"vendors": {"$replace": []}})
    assert w2.vendors == []
    assert merge({"a": [1, 2]}, {"a": [3]}) == {"a": [3]}


def test_snapshot_diff_save_roundtrip(world, tmp_path):
    before = world.snapshot()
    call_ok(world, "update_room", {"room_id": "R023", "fields": {"rent": 760}})
    d = rt.diff(before, world)
    assert {"path": "rooms[R023].rent", "op": "change", "before": 750, "after": 760} in d
    p = tmp_path / "w.json"
    world.save(p)
    w2 = rt.load_file(p)
    assert w2.get("rooms", "R023")["rent"] == 760
    assert rt.diff(world, w2) == []


def test_get_path_syntax(world):
    assert get_path(world, "rooms[R023].rent") == 750
    assert get_path(world, "threads[T001].messages[0].from") == "renter"
    assert get_path(world, "register[renter:nobody].gate") is None


def test_clock_is_world_driven(world):
    world.advance(minutes=90)
    assert world.clock["now"] == "2026-10-17T10:30:00"


# ---------------------------------------------------------------- call() and validation

def test_unknown_tool_suggests_close_name(world):
    e = call_err(world, "get_rooms", {}, "INVALID_ARGS")
    assert "get_room" in e["hint"]


def test_missing_and_unknown_and_wrong_type_args(world):
    e = call_err(world, "get_room", {}, "INVALID_ARGS")
    assert "room_id" in e["message"] and "get_room args" in e["hint"]
    e = call_err(world, "get_room", {"room": "R023"}, "INVALID_ARGS")
    assert "'room'" in e["message"]
    e = call_err(world, "create_listing", {"room_id": "R023", "title": "t", "body": "b", "price": "750"}, "INVALID_ARGS")
    assert "price" in e["message"]
    e = call_err(world, "list_rooms", {"available_by": "Nov 1"}, "INVALID_ARGS")
    assert "YYYY-MM-DD" in e["message"]
    e = call_err(world, "publish_listing", {"listing_id": "L1", "channel": "myspace"}, "INVALID_ARGS")
    assert "channel" in e["message"]


def test_args_as_json_string_and_bad_json(world):
    assert rt.call(world, "get_room", '{"room_id": "R023"}')["ok"]
    call_err(world, "get_room", "{room_id: R023", "INVALID_ARGS")
    call_err(world, "get_room", ["R023"], "INVALID_ARGS")


def test_not_found(world):
    call_err(world, "get_room", {"room_id": "R404"}, "NOT_FOUND")


def test_internal_errors_become_envelopes(world, monkeypatch):
    def boom(world, **kw):
        raise RuntimeError("bug")
    monkeypatch.setitem(rt.REGISTRY, "get_room", boom)
    e = call_err(world, "get_room", {"room_id": "R023"}, "UPSTREAM_ERROR")
    assert e["retryable"] is False


# ---------------------------------------------------------------- events

def test_events_tool_call_and_result(world, sink, tmp_path):
    call_ok(world, "get_room", {"room_id": "R023"}, sink=sink, call_id="c1")
    types = [e["type"] for e in sink.events]
    assert types == ["tool_call", "tool_result"]
    assert [e["seq"] for e in sink.events] == [1, 2]
    assert sink.events[0]["actor"] == "operator" and sink.events[0]["data"]["call_id"] == "c1"
    assert sink.events[1]["data"]["result"]["ok"] is True
    fsink = rt.EventSink.for_run("r_file", runs_dir=tmp_path)
    seen = []
    fsink.subscribers.append(seen.append)
    world.sink = fsink  # world-attached sink is used when none is passed
    call_ok(world, "escalate_to_owner", {"reason": "price change", "ref_id": "T001"})
    lines = [json.loads(l) for l in (tmp_path / "r_file" / "events.jsonl").read_text().splitlines()]
    assert [l["type"] for l in lines] == ["tool_call", "tool_result", "escalation"]
    assert all(l["run_id"] == "r_file" for l in lines) and len(seen) == 3


def test_report_emits_owner_message(world, sink):
    call_ok(world, "report_to_owner", {"summary": "Posted R023 to 2 channels."}, sink=sink)
    assert sink.events[-1]["type"] == "owner_message"
    assert world.owner_reports[0]["summary"].startswith("Posted")


# ---------------------------------------------------------------- faults

@pytest.mark.parametrize("kind,code,retryable", [
    ("timeout", "TIMEOUT", True), ("rate_limited", "RATE_LIMITED", True), ("login_required", "LOGIN_REQUIRED", False),
    ("page_changed", "PAGE_CHANGED", False), ("upstream_error", "UPSTREAM_ERROR", True), ("not_found", "NOT_FOUND", False)])
def test_fault_kinds_fail_then_recover(world, sink, kind, code, retryable):
    world.faults = [{"tool": "get_room", "kind": kind, "times": 2}]
    for _ in range(2):
        e = call_err(world, "get_room", {"room_id": "R023"}, code, sink=sink)
        assert e["retryable"] is retryable and e.get("hint")
    call_ok(world, "get_room", {"room_id": "R023"})
    assert sink.events[1]["data"]["fault"] == kind


def test_fault_after_and_match_and_wildcard(world):
    world.faults = [{"tool": "get_room", "kind": "timeout", "times": 1, "after": 1}]
    call_ok(world, "get_room", {"room_id": "R023"})
    call_err(world, "get_room", {"room_id": "R023"}, "TIMEOUT")
    call_ok(world, "get_room", {"room_id": "R023"})
    world.faults = [{"tool": "*", "kind": "rate_limited", "times": 1, "match": {"room_id": "R001"}}]
    call_ok(world, "get_room", {"room_id": "R023"})
    call_err(world, "get_room", {"room_id": "R001"}, "RATE_LIMITED")


def test_fault_does_not_run_tool(world):
    world.faults = [{"tool": "update_room", "kind": "timeout", "times": 1}]
    call_err(world, "update_room", {"room_id": "R023", "fields": {"rent": 1}}, "TIMEOUT")
    assert world.get("rooms", "R023")["rent"] == 750


def test_invalid_args_do_not_consume_fault(world):
    world.faults = [{"tool": "get_room", "kind": "timeout", "times": 1}]
    call_err(world, "get_room", {}, "INVALID_ARGS")
    call_err(world, "get_room", {"room_id": "R023"}, "TIMEOUT")


def test_malformed_returns_ok_with_corrupted_data_and_side_effect(world):
    world.faults = [{"tool": "create_listing", "kind": "malformed", "times": 1}]
    r = rt.call(world, "create_listing", {"room_id": "R023", "title": "Private bath room", "body": "Quiet room.", "price": 750})
    assert r["ok"] is True
    good_keys = {"listing_id", "room_id", "status", "title", "body", "price", "channels", "created_at"}
    data = r["data"]["listing"] if "listing" in r["data"] else r["data"]
    assert set(data) != good_keys or any(not isinstance(data[k], type(world.listings[0][k])) for k in data)
    assert len(world.listings) == 1  # the action still happened


def test_malformed_list_result(world):
    world.faults = [{"tool": "list_rooms", "kind": "malformed", "times": 1}]
    r = rt.call(world, "list_rooms", {})
    assert r["ok"]
    rooms = r["data"].get("rooms")
    assert not (isinstance(rooms, list) and rooms and set(rooms[0]) == set(world.rooms[0]) - {"amenities", "photos", "price_basis", "address"})
