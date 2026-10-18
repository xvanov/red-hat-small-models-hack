"""Concierge / demand capture tools: disclosure, capture + match, sourcing, park, follow-ups, clusters, owner confirm."""
from datetime import date

import pytest

import rentus_tools as rt
from conftest import COMPLETE_GATE, call_err, call_ok
from rentus_tools.impl.demand import resolve_timeframe
from rentus_tools.impl.demand_match import pet_allowed, pet_kind, resolve_areas, room_fit
from rentus_tools.impl.demand_owner import owner_call


def _thread(tid, name, room_id=None, lang="en", text="Hi, is this still available?", channel="marketplace", listing_id=None):
    t = {"thread_id": tid, "channel": channel, "renter_name": name, "language": lang,
         "messages": [{"from": "renter", "text": text}]}
    if room_id:
        t["room_id"] = room_id
    if listing_id:
        t["listing_id"] = listing_id
    return t


# ----------------------------------------------------------------------------- disclosure

@pytest.mark.parametrize("room_id", ["R001", "R005", "R010", "R020", "R023", "R030"])
@pytest.mark.parametrize("lang", ["en", "es"])
def test_disclosure_messages_pass_send_message(room_id, lang):
    text = "Hi, is this still available?" if lang == "en" else "Hola, ¿todavía está disponible el cuarto?"
    w = rt.load(patch={"threads": [_thread("T9", "Ana", room_id, lang, text)], "clock": {"now": "2026-10-17T09:00:00"}})
    d = call_ok(w, "listing_disclosure", {"thread_id": "T9"})
    assert d["language"] == lang
    room = w.get("rooms", room_id)
    house_no = room["address"].split()[0]
    for m in d["messages"] + d["house_rules"]:
        assert "?" not in m and house_no not in m
        call_ok(w, "send_message", {"thread_id": "T9", "text": m})
    joined = " ".join(d["messages"])
    assert f"${room['rent']:,}" in joined and room["address"].split(",")[0].split(" ", 1)[1] in joined


def test_disclosure_available_now_never_past_date():
    w = rt.load(patch={"rooms": [{"room_id": "R023", "available_from": "2026-09-01"}], "clock": {"now": "2026-10-17T09:00:00"}})
    d = call_ok(w, "listing_disclosure", {"room_id": "R023"})
    assert any("available now" in m for m in d["messages"])
    assert not any("September" in m for m in d["messages"])


def test_disclosure_skips_unconfirmed_fields():
    w = rt.load(patch={"rooms": [{"room_id": "R023", "unconfirmed": ["deposit", "pets"]}]})
    d = call_ok(w, "listing_disclosure", {"room_id": "R023"})
    assert "deposit" not in " ".join(d["messages"]).lower()
    assert "confirm" in d["house_rules"][0]


# ----------------------------------------------------------------------------- matching helpers

def test_area_resolver():
    assert resolve_areas("near the airport")[0] == "Morrisville"
    assert set(resolve_areas("near RDU")) == {"Morrisville", "Cary", "Raleigh", "Durham"}
    assert set(resolve_areas("between the airport and Garner")) == {"Morrisville", "Cary", "Raleigh", "Garner"}
    assert resolve_areas("near Duke") == ["Durham"]
    assert resolve_areas("Durham or Chapel Hill") == ["Durham", "Chapel Hill"]
    assert resolve_areas("somewhere nice") == []


def test_pet_rules():
    assert pet_kind("a leopard gecko in a terrarium") == "enclosed"
    assert pet_kind("my rabbit") == "rodent_rabbit"
    assert pet_allowed("small dogs ok", "enclosed") is True
    assert pet_allowed("cats ok", "rodent_rabbit") is False
    assert pet_allowed("no", "enclosed") is False
    assert pet_allowed("cats ok", "dog") is False
    assert pet_allowed("case by case", "dog") is None


def test_room_fit_hard_gates():
    room = {"room_id": "X", "area": "Durham", "type": "room in house", "rent": 800, "private_bath": False,
            "max_occupants": 1, "pets": "no", "lease_min_months": 12, "available_from": "2026-11-01"}
    assert room_fit(room, {"budget": 700, "areas": ["Durham"]})[0] is True        # within 15%
    assert room_fit(room, {"budget": 650})[0] is False                            # >15% below
    assert room_fit(room, {"type": "apartment"})[0] is False                       # whole unit seeker
    assert room_fit(room, {"occupants": 2})[0] is False
    assert room_fit(room, {"pets": "dog"})[0] is False
    assert room_fit(room, {"stay_months": 3})[0] is False
    assert room_fit(room, {"private_bath": True})[0] is False
    assert room_fit(room, {"areas": ["Raleigh"]})[0] is False
    assert room_fit(room, {"areas": ["Chapel Hill"]})[0] is True                  # adjacent is a soft match
    assert room_fit({**room, "pets": "case by case"}, {"pets": "dog"})[0] is True  # unknown policy never disqualifies


# ----------------------------------------------------------------------------- capture

def test_capture_creates_demand_record_and_continues_when_room_fits(world):
    out = call_ok(world, "capture_demand", {"thread_id": "T001", "criteria": {"area": "Raleigh", "budget": 800, "occupants": 1}})
    assert out["created"] and out["matchable"]
    row = world.get("register", out["renter_id"])
    d = row["demand"]
    assert d["criteria"]["areas"] == ["Raleigh"] and d["criteria"]["budget"] == 800
    assert d["sources"][0]["channel"] == "marketplace" and d["listing_of_interest"] == "R023"
    assert row["wants"]["budget"] == 800
    assert out["asked"]["room_id"] == "R023" and out["asked"]["available"]
    assert "listing_disclosure" in out["next_step"]


def test_capture_offers_other_rooms_when_asked_room_is_filled():
    w = rt.load(patch={"threads": [_thread("T1", "Ben", "R023")],
                       "listings": [{"listing_id": "L9", "room_id": "R023", "status": "filled", "title": "t", "body": "b",
                                     "price": 750, "channels": {}}]})
    room = w.get("rooms", "R023")
    out = call_ok(w, "capture_demand", {"thread_id": "T1", "criteria": {"area": room["area"], "budget": 1100}})
    assert out["asked"]["available"] is False
    assert out["alternatives"] and all(a["room_id"] != "R023" for a in out["alternatives"])
    assert all(a["area"] == room["area"] or a["area"] in ("Chapel Hill", "Durham") for a in out["alternatives"])
    assert "offer the alternatives" in out["next_step"]


def test_capture_no_fit_points_to_sourcing():
    w = rt.load(patch={"threads": [_thread("T1", "Cy")]})
    out = call_ok(w, "capture_demand", {"thread_id": "T1", "criteria": {"area": "Apex", "budget": 800,
                                                                           "private_bath": True, "type": "room"}})
    assert out["alternatives"] == [] and "search_external_rooms" in out["next_step"]
    s = call_ok(w, "search_external_rooms", {"renter_id": out["renter_id"]})
    assert s["status"] == "sourcing" and s["leads"]
    assert [l["ext_id"] for l in s["leads"]] == ["X09", "X02"]  # exact area first, adjacent Cary second
    row = w.get("register", out["renter_id"])
    assert row["demand"]["sourcing"]["due_at"].startswith("2026-10-20")
    assert row["demand"]["followup"]["kind"] == "sourcing_due"


def test_capture_needs_two_stated_criteria():
    w = rt.load(patch={"threads": [_thread("T1", "Di")]})
    out = call_ok(w, "capture_demand", {"thread_id": "T1", "criteria": {"budget": 700}})
    assert out["matchable"] is False and "area or budget" in out["next_step"]


def test_capture_merges_second_channel_by_phone():
    w = rt.load(patch={"threads": [_thread("T1", "Eva"), _thread("T2", "Eva", channel="sms")]})
    a = call_ok(w, "capture_demand", {"thread_id": "T1", "criteria": {"area": "Raleigh", "budget": 700}, "phone": "919-555-0101"})
    b = call_ok(w, "capture_demand", {"thread_id": "T2", "criteria": {"private_bath": True}, "phone": "(919) 555-0101"})
    assert b["renter_id"] == a["renter_id"] and b["merged_into"] == a["renter_id"]
    row = w.get("register", a["renter_id"])
    assert {s["channel"] for s in row["demand"]["sources"]} == {"marketplace", "sms"}
    assert row["demand"]["criteria"]["private_bath"] is True and row["demand"]["criteria"]["budget"] == 700
    assert len(w.register) == 1


def test_capture_rejects_unknown_criteria(world):
    call_err(world, "capture_demand", {"thread_id": "T001", "criteria": {"gender": "male"}}, "INVALID_ARGS")


def test_interest_history_kept(world):
    call_ok(world, "capture_demand", {"thread_id": "T001", "criteria": {"area": "Durham", "budget": 900}})
    out = call_ok(world, "capture_demand", {"thread_id": "T001", "listing_of_interest": "R005"})
    d = world.get("register", out["renter_id"])["demand"]
    assert d["listing_of_interest"] == "R005" and d["interest_history"][0]["listing"] == "R023"


# ----------------------------------------------------------------------------- park + follow-ups

@pytest.mark.parametrize("tf,want,how", [
    ("January", date(2027, 1, 1), "named_month"),
    ("not until enero", date(2027, 1, 1), "named_month"),
    ("December 2026", date(2026, 12, 1), "named_month"),
    ("2027-02-15", date(2027, 2, 15), "exact_date"),
    ("around March 10th", date(2027, 3, 10), "exact_date"),
    ("next month", date(2026, 11, 1), "next_month"),
    ("in 2 weeks", date(2026, 10, 31), "relative"),
    ("I don't know yet", date(2026, 11, 16), "default_30_days"),
    (None, date(2026, 11, 16), "default_30_days"),
])
def test_resolve_timeframe(tf, want, how):
    assert resolve_timeframe(tf, date(2026, 10, 17)) == (want, how)


def test_park_and_due_reconnect(world):
    rid = call_ok(world, "capture_demand", {"thread_id": "T001", "criteria": {"area": "Durham", "budget": 900}})["renter_id"]
    out = call_ok(world, "park_prospect", {"renter_id": rid, "reason": "not looking until January", "timeframe": "January"})
    assert out["reconnect_at"] == "2027-01-01" and out["status"] == "not_now" and out["demand_status"] == "parked"
    row = world.get("register", rid)
    assert row["paused_reason"] == "not looking until January" and row["reconnect_at"] == "2027-01-01"
    assert call_ok(world, "due_followups", {"now": "2026-12-31"})["count"] == 0
    due = call_ok(world, "due_followups", {"now": "2027-01-01T10:00"})["due"]
    assert due[0]["renter_id"] == rid and due[0]["kind"] == "reconnect" and due[0]["room_still_available"] is True
    call_ok(world, "log_followup", {"renter_id": rid, "event": "reconnect_sent"})
    assert world.get("register", rid)["status"] == "qualifying"


def test_park_without_timeframe_is_30_days(world):
    rid = call_ok(world, "capture_demand", {"thread_id": "T001", "criteria": {"budget": 900, "occupants": 1}})["renter_id"]
    assert call_ok(world, "park_prospect", {"renter_id": rid, "reason": "maybe later"})["reconnect_at"] == "2026-11-16"


def test_park_refuses_closed_row(world):
    rid = call_ok(world, "upsert_renter", {"thread_id": "T001", "fields": {"status": "lost"}})["renter"]["renter_id"]
    call_err(world, "park_prospect", {"renter_id": rid, "reason": "x"}, "CONFLICT")


def test_application_cadence_and_reset(world):
    rid = call_ok(world, "upsert_renter", {"thread_id": "T001", "fields": {"gate": COMPLETE_GATE}})["renter"]["renter_id"]
    fu = call_ok(world, "log_followup", {"renter_id": rid, "event": "application_sent"})["followup"]
    assert fu["next_checkin_at"] == "2026-10-17T21:00:00"
    world.advance(minutes=12 * 60)
    assert call_ok(world, "due_followups", {})["due"][0]["kind"] == "checkin"
    hours = []
    for _ in range(7):
        fu = call_ok(world, "log_followup", {"renter_id": rid, "event": "checkin_sent"})["followup"]
        from datetime import datetime
        hours.append(int((datetime.fromisoformat(fu["next_checkin_at"]) - world.now()).total_seconds() // 3600))
    assert hours == [12, 12, 12, 24, 24, 48, 96]
    fu = call_ok(world, "log_followup", {"renter_id": rid, "event": "reply"})["followup"]
    assert fu["gap_index"] == 0
    out = call_ok(world, "log_followup", {"renter_id": rid, "event": "applied"})
    assert out["followup"]["next_checkin_at"] is None and out["status"] == "applied"


def test_due_followups_prefers_waiting_reply(world):
    rid = call_ok(world, "upsert_renter", {"thread_id": "T001", "fields": {"gate": COMPLETE_GATE}})["renter"]["renter_id"]
    call_ok(world, "log_followup", {"renter_id": rid, "event": "application_sent"})
    world.advance(minutes=60)
    world.threads[0]["messages"].append({"from": "renter", "text": "Still deciding", "ts": world.clock["now"]})
    world.advance(minutes=12 * 60)
    assert call_ok(world, "due_followups", {})["due"][0]["kind"] == "reply_waiting"


# ----------------------------------------------------------------------------- clusters

def _seed_cluster(n_qualified, n_unqualified, proxy=0):
    threads = [_thread(f"T{i}", f"P{i}") for i in range(n_qualified + n_unqualified + proxy)]
    w = rt.load(patch={"threads": threads})
    for i, t in enumerate(threads):
        crit = {"area": "near the airport", "budget": 800 + i, "type": "room", "private_bath": True}
        rid = call_ok(w, "capture_demand", {"thread_id": t["thread_id"], "criteria": crit,
                                            "proxy": i >= n_qualified + n_unqualified})["renter_id"]
        if i < n_qualified or i >= n_qualified + n_unqualified:
            gate = dict(COMPLETE_GATE, phone={"status": "answered", "value": f"+1919555{1000 + i}"})
            call_ok(w, "upsert_renter", {"thread_id": t["thread_id"], "fields": {"gate": gate}})
    return w


def test_cluster_supply_signal():
    rep = call_ok(_seed_cluster(5, 1), "cluster_report", {})
    sig = rep["supply_signals"]
    assert len(sig) == 1 and sig[0]["area"] == "Morrisville" and sig[0]["type"] == "room, private bath"
    assert sig[0]["budget_band"] == "$750 to $899" and sig[0]["qualified_count"] == 5
    assert rep["summary"].startswith("SUPPLY SIGNAL: 5 qualified people")


def test_cluster_nominal_five_is_not_a_signal():
    rep = call_ok(_seed_cluster(3, 1, proxy=1), "cluster_report", {})
    assert rep["supply_signals"] == []
    assert rep["clusters"][0]["label"] == "nominal 5, not a signal"


def test_cluster_watch():
    rep = call_ok(_seed_cluster(1, 2), "cluster_report", {})
    assert rep["clusters"][0]["label"] == "WATCH" and "WATCH" in rep["summary"]


# ----------------------------------------------------------------------------- owner confirm

def _proposed(world):
    rid = call_ok(world, "upsert_renter", {"thread_id": "T001", "fields": {"name": "Maria", "gate": COMPLETE_GATE}})["renter"]["renter_id"]
    ev = call_ok(world, "propose_showing", {"renter_id": rid, "room_id": "R023", "start": "2026-10-24T11:00"})["event"]
    return rid, ev["event_id"]


def test_owner_confirm_is_not_an_operator_tool(world):
    assert "owner_confirm_showing" not in rt.REGISTRY
    assert all(t["function"]["name"] != "owner_confirm_showing" for t in rt.tool_schemas("concierge"))
    rid, eid = _proposed(world)
    r = rt.call(world, "owner_confirm_showing", {"event_id": eid, "decision": "confirm"})
    assert not r["ok"] and r["error"]["code"] == "INVALID_ARGS"
    assert world.get("calendar", eid)["status"] == "proposed"


def test_owner_confirm_then_booking_claim_allowed(world, sink):
    rid, eid = _proposed(world)
    call_err(world, "send_message", {"thread_id": "T001", "text": "Your showing is confirmed for Saturday at 11 AM."}, "POLICY_BLOCKED")
    r = owner_call(world, "owner_confirm_showing", {"event_id": eid, "decision": "confirm"}, sink=sink)
    assert r["ok"] and r["data"]["event"]["status"] == "confirmed"
    assert r["data"]["event"]["on_the_way_by"] == "2026-10-24T10:00"
    assert world.get("register", rid)["status"] == "showing_confirmed"
    assert "one hour before" in r["data"]["next_step"]
    again = owner_call(world, "owner_confirm_showing", {"event_id": eid, "decision": "confirm"})
    assert again["data"]["already"] is True
    call_ok(world, "send_message", {"thread_id": "T001", "text": "Your showing is confirmed for Saturday at 11 AM."})
    assert any(e["type"] == "owner_message" and e["actor"] == "owner" for e in sink.events)


def test_owner_reject_frees_slot(world):
    rid, eid = _proposed(world)
    r = owner_call(world, "owner_confirm_showing", {"event_id": eid, "decision": "reject", "note": "busy"})
    assert r["ok"] and world.get("calendar", eid)["status"] == "rejected"
    assert world.get("register", rid)["status"] == "qualified"
    bad = owner_call(world, "owner_confirm_showing", {"event_id": eid, "decision": "confirm"})
    assert not bad["ok"] and bad["error"]["code"] == "CONFLICT"
    call_ok(world, "propose_showing", {"renter_id": rid, "room_id": "R023", "start": "2026-10-24T11:00"})


def test_owner_confirm_unknown_event(world):
    r = owner_call(world, "owner_confirm_showing", {"event_id": "E999", "decision": "confirm"})
    assert r["error"]["code"] == "NOT_FOUND"
