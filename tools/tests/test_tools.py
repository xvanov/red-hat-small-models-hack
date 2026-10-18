"""Happy path and policy refusals for every tool."""
import pytest

import rentus_tools as rt
from rentus_tools import live

from conftest import COMPLETE_GATE, call_err, call_ok

LISTING = {"room_id": "R023", "title": "Private room with private bath, $750", "body": "Furnished room near Duke. $750 a month, deposit $750.", "price": 750}


# ---------------------------------------------------------------- inventory

def test_list_rooms_filters(world):
    all_ = call_ok(world, "list_rooms", {})
    assert all_["count"] == 30 and "amenities" not in all_["rooms"][0]
    d = call_ok(world, "list_rooms", {"area": "durham", "available_by": "2026-11-01"})
    assert d["count"] > 0 and all(r["area"] == "Durham" and r["available_from"] <= "2026-11-01" for r in d["rooms"])
    z = call_ok(world, "list_rooms", {"area": "27514"})
    assert all(r["zip"] == "27514" for r in z["rooms"]) and z["count"] == 2


def test_get_and_update_room(world):
    room = call_ok(world, "get_room", {"room_id": "R023"})["room"]
    assert room["rent"] == 750 and "price_basis" not in room
    up = call_ok(world, "update_room", {"room_id": "R023", "fields": {"rent": 775, "available_from": "2026-11-01", "private_bath": True}})
    assert up["room"]["rent"] == 775
    call_err(world, "update_room", {"room_id": "R023", "fields": {"room_id": "X"}}, "INVALID_ARGS")
    call_err(world, "update_room", {"room_id": "R023", "fields": {"rent": -5}}, "INVALID_ARGS")
    call_err(world, "update_room", {"room_id": "R023", "fields": {"available_from": "soon"}}, "INVALID_ARGS")
    call_err(world, "update_room", {"room_id": "R023", "fields": {}}, "INVALID_ARGS")


# ---------------------------------------------------------------- listings

def test_listing_lifecycle(world):
    d = call_ok(world, "create_listing", LISTING)
    lid = d["listing"]["listing_id"]
    assert d["listing"]["status"] == "draft" and d["compliance"]["ok"]
    pub = call_ok(world, "publish_listing", {"listing_id": lid, "channel": "marketplace"})
    assert pub["status"] == "live" and pub["post_id"] and pub["url"].startswith("https://")
    call_ok(world, "publish_listing", {"listing_id": lid, "channel": "roomies"})
    assert world.get("listings", lid)["status"] == "live"
    assert len(world.channels["roomies"]["posts"]) == 1
    call_err(world, "publish_listing", {"listing_id": lid, "channel": "marketplace"}, "CONFLICT")
    up = call_ok(world, "update_listing", {"listing_id": lid, "fields": {"title": "Sunny room, private bath"}})
    assert up["listing"]["title"] == "Sunny room, private bath"
    filled = call_ok(world, "mark_filled", {"listing_id": lid})["listing"]
    assert filled["status"] == "filled"
    assert all(c["status"] == "removed" for c in filled["channels"].values())
    assert all(p["status"] == "removed" for p in world.channels["marketplace"]["posts"])
    call_err(world, "publish_listing", {"listing_id": lid, "channel": "craigslist"}, "CONFLICT")
    call_err(world, "mark_filled", {"listing_id": lid}, "CONFLICT")


def test_create_listing_refusals(world):
    e = call_err(world, "create_listing", {**LISTING, "price": 700}, "POLICY_BLOCKED")
    assert "update_room" in e["hint"]
    e = call_err(world, "create_listing", {**LISTING, "body": "Only $700 for the first month!"}, "POLICY_BLOCKED")
    assert "$700" in e["message"]
    call_ok(world, "create_listing", LISTING)
    call_err(world, "create_listing", LISTING, "CONFLICT")
    call_err(world, "create_listing", {**LISTING, "room_id": "R404"}, "NOT_FOUND")


def test_owner_price_change_flow(world):
    call_ok(world, "update_room", {"room_id": "R001", "fields": {"rent": 900}})
    call_ok(world, "create_listing", {"room_id": "R001", "title": "Basement suite $900", "body": "Own entrance.", "price": 900})


def test_publish_refuses_noncompliant_text(world):
    lid = call_ok(world, "create_listing", {**LISTING, "body": "Christian home, no kids. $750."})["listing"]["listing_id"]
    e = call_err(world, "publish_listing", {"listing_id": lid, "channel": "marketplace"}, "POLICY_BLOCKED")
    assert e["details"]["findings"] and "update_listing" in e["hint"]
    call_ok(world, "update_listing", {"listing_id": lid, "fields": {"body": "Quiet room, max 1 occupant. $750."}})
    call_ok(world, "publish_listing", {"listing_id": lid, "channel": "marketplace"})


def test_update_listing_refusals(world):
    lid = call_ok(world, "create_listing", LISTING)["listing"]["listing_id"]
    call_err(world, "update_listing", {"listing_id": lid, "fields": {"price": 700}}, "POLICY_BLOCKED")
    call_err(world, "update_listing", {"listing_id": lid, "fields": {"status": "live"}}, "INVALID_ARGS")
    call_err(world, "update_listing", {"listing_id": lid, "fields": {"body": "Now $699!"}}, "POLICY_BLOCKED")


def test_live_mode_routes_to_adapter(world):
    world.mode = "live"
    lid = call_ok(world, "create_listing", LISTING)["listing"]["listing_id"]
    pub = call_ok(world, "publish_listing", {"listing_id": lid, "channel": "padsplit"})
    assert pub["status"] == "ready_to_submit" and pub["screenshot"].endswith(".png")
    assert world.get("listings", lid)["status"] == "draft"  # nothing is live until the owner submits
    sent = call_ok(world, "send_message", {"thread_id": "T001", "text": "Yes, it is still available."})
    assert sent["status"] == "ready_to_submit"

    class Fake:
        def publish_listing(self, world, listing, channel):
            return {"status": "ready_to_submit", "screenshot": "x.png", "post_id": "fb-1", "url": None}

        def send_message(self, world, thread, text, attachments):
            return {"status": "ready_to_submit", "screenshot": "y.png"}
    live.register("roomies", Fake())
    try:
        assert call_ok(world, "publish_listing", {"listing_id": lid, "channel": "roomies"})["screenshot"] == "x.png"
    finally:
        live.ADAPTERS.pop("roomies")


def test_listing_media(world):
    photos = call_ok(world, "get_listing_media", {"room_id": "R023"})["photos"]
    assert photos and all(p["url"].endswith(p["name"]) for p in photos)


# ---------------------------------------------------------------- compliance

@pytest.mark.parametrize("text,rule", [
    ("No kids please", "familial_status"), ("Adults only building", "familial_status"),
    ("Ideal for single professionals", "familial_status"), ("Christian home, quiet", "religion"),
    ("Must speak English", "race_color_national_origin"), ("No wheelchairs, stairs only", "handicap"),
    ("No emotional support animals", "handicap"), ("Sin niños", "familial_status"), ("Hogar cristiano", "religion"),
])
def test_compliance_violations(world, text, rule):
    d = call_ok(world, "check_listing_compliance", {"text": text})
    assert d["ok"] is False and d["findings"][0]["rule"] == rule and d["findings"][0]["suggestion"]


def test_compliance_clean_and_cautions(world):
    clean = call_ok(world, "check_listing_compliance", {"text": "Private room near a church and Duke, max 2 occupants, no pets."})
    assert clean == {"ok": True, "findings": []}
    soi = call_ok(world, "check_listing_compliance", {"text": "No Section 8."})
    assert soi["ok"] is True and soi["findings"][0]["severity"] == "caution"
    world.policy["source_of_income_protected"] = True
    assert call_ok(world, "check_listing_compliance", {"text": "No Section 8."})["ok"] is False
    # Owner decision D23 (b): gender wording in a shared room is a warning the owner decides, not a block
    for text in ("Female roommates only for shared bath", "Males only.", "females only", "Solo mujeres."):
        fem = call_ok(world, "check_listing_compliance", {"text": text})
        assert fem["ok"] is True and fem["findings"][0]["rule"] == "sex"
        assert fem["findings"][0]["severity"] == "warning" and fem["findings"][0]["owner_decides"] is True
    mixed = call_ok(world, "check_listing_compliance", {"text": "Males only, no kids."})
    assert mixed["ok"] is False and {f["severity"] for f in mixed["findings"]} == {"warning", "violation"}


# ---------------------------------------------------------------- market

def test_market_rent(world):
    d = call_ok(world, "get_market_rent", {"zip": "27701", "bedrooms": 1})
    assert d["zori"] > 1000 and "Zillow" in d["source"] and d["as_of"].startswith("20")
    e = call_err(world, "get_market_rent", {"zip": "90210"}, "NOT_FOUND")
    assert e["hint"]
    call_err(world, "get_market_rent", {"zip": "277"}, "INVALID_ARGS")


def test_market_table_fallback(monkeypatch):
    from rentus_tools.impl import market
    market.zori_table.cache_clear()
    monkeypatch.setattr(market, "find_repo_root", lambda: None)
    try:
        table, origin = market.zori_table()
        assert origin == "table" and "27701" in table
    finally:
        market.zori_table.cache_clear()


# ---------------------------------------------------------------- inbox

def test_threads(world):
    th = call_ok(world, "list_threads", {"unanswered_only": True})["threads"]
    assert th[0]["thread_id"] == "T001" and th[0]["unanswered"]
    assert call_ok(world, "list_threads", {"channel": "sms"})["threads"] == []
    full = call_ok(world, "read_thread", {"thread_id": "T001"})["thread"]
    assert full["messages"][0]["from"] == "renter"
    sent = call_ok(world, "send_message", {"thread_id": "T001", "text": "Yes, it is available at $750 a month. Are you okay with a 12-month lease?",
                                           "attachments": ["r023_room.jpg"]})
    assert sent["message_id"] == "T001-m2"
    assert call_ok(world, "list_threads", {"unanswered_only": True})["threads"] == []
    call_err(world, "read_thread", {"thread_id": "T404"}, "NOT_FOUND")


@pytest.mark.parametrize("text,rule", [
    ("Hi Maria. It is available. Want to see it?", "max_two_sentences"),
    ("Is Nov 1 ok? And how many people?", "one_question"),
    ("It is available — want to see it?", "no_long_dashes"),
    ("It is available – want to see it?", "no_long_dashes"),
])
def test_send_message_style_refusals(world, text, rule):
    e = call_err(world, "send_message", {"thread_id": "T001", "text": text}, "POLICY_BLOCKED")
    assert rule in e["details"]["rules"] and e["hint"]


def test_send_message_sentence_counting_is_not_fooled(world):
    for text in ["The room is on Cobbleford St. in Durham, showings 10 a.m. to 6 p.m. daily.",
                 "Rent is $750.00 a month. See https://sandbox.rentus.local/marketplace/L001 for photos.",
                 "Hola María, sí está disponible. ¿Está de acuerdo con un contrato de 12 meses?"]:
        if text.startswith("Hola"):  # replies follow the renter's language (send_message language guard)
            _renter_says(world, "Hola, ¿sigue disponible el cuarto?")
        call_ok(world, "send_message", {"thread_id": "T001", "text": text})


def test_send_message_price_and_term_refusals(world):
    e = call_err(world, "send_message", {"thread_id": "T001", "text": "I can do $700 for you."}, "POLICY_BLOCKED")
    assert "price_not_in_record" in e["details"]["rules"] and "escalate" in e["hint"]
    call_err(world, "send_message", {"thread_id": "T001", "text": "We can do 700 dollars."}, "POLICY_BLOCKED")
    e = call_err(world, "send_message", {"thread_id": "T001", "text": "A 6-month lease works for us."}, "POLICY_BLOCKED")
    assert "lease_floor_not_requested" in e["details"]["rules"]
    e = call_err(world, "send_message", {"thread_id": "T001", "text": "Month-to-month is fine."}, "POLICY_BLOCKED")
    assert "lease_term_not_in_record" in e["details"]["rules"]
    call_ok(world, "send_message", {"thread_id": "T001", "text": "The lease is 12 months and the deposit is $750."})
    call_err(world, "send_message", {"thread_id": "T001", "text": "Here you go.", "attachments": ["nope.jpg"]}, "INVALID_ARGS")
    call_err(world, "send_message", {"thread_id": "T001", "text": "   "}, "INVALID_ARGS")


def _renter_says(world, text):
    world.threads[0]["messages"].append({"from": "renter", "text": text, "id": f"r{len(world.threads[0]['messages'])}",
                                         "attachments": [], "ts": "t"})


@pytest.mark.parametrize("text", ["The shortest lease I can do is a 6-month lease.", "6 months is the shortest I can do.",
                                  "The minimum is six months.", "El contrato más corto es de 6 meses."])
def test_six_month_floor_only_after_renter_asks(world, text):
    """Owner decision D23 (a): the 6-month floor is named only after the renter asks for a shorter lease."""
    es = text.startswith("El ")
    if es:  # replies follow the renter's language (send_message language guard)
        _renter_says(world, "Hola, ¿el cuarto sigue disponible?")
    e = call_err(world, "send_message", {"thread_id": "T001", "text": text}, "POLICY_BLOCKED")
    assert "lease_floor_not_requested" in e["details"]["rules"]
    _renter_says(world, "¿puede ser por 9 meses?" if es else "could I sign for 9 months instead?")
    call_ok(world, "send_message", {"thread_id": "T001", "text": text})
    # below the floor stays blocked even after the request
    short = "Un contrato de 3 meses está bien." if es else "A 3-month lease works."
    e = call_err(world, "send_message", {"thread_id": "T001", "text": short}, "POLICY_BLOCKED")
    assert "lease_term_not_in_record" in e["details"]["rules"]


@pytest.mark.parametrize("ask", ["no, not a full year", "¿puede ser por menos tiempo?", "only need it for the semester",
                                 "Is month-to-month possible?"])
def test_shorter_lease_request_phrasings(world, ask):
    _renter_says(world, ask)
    reply = ("El contrato más corto que puedo hacer es de 6 meses." if ask.startswith("¿")
             else "The shortest lease I can do is a 6-month lease.")
    call_ok(world, "send_message", {"thread_id": "T001", "text": reply})


def test_renter_accepting_six_months_passes_the_gate(world):
    """Owner decision D23 (a): a renter who accepts 6 months or more passes the lease item."""
    six = {"status": "answered", "value": False, "months": 6}
    d = call_ok(world, "upsert_renter", {"thread_id": "T001", "fields": {"gate": {**COMPLETE_GATE, "lease": six}}})
    assert d["gate_missing"] == [] and rt.gate_complete(world, d["renter"]["renter_id"])
    call_ok(world, "propose_showing", {"renter_id": d["renter"]["renter_id"], "room_id": "R023", "start": "2026-10-18T11:00"})
    three = {"status": "answered", "value": True, "months": 3}
    d = call_ok(world, "upsert_renter", {"thread_id": "T001", "fields": {"gate": {**COMPLETE_GATE, "lease": three}}})
    assert d["gate_missing"] == ["lease"]
    call_err(world, "upsert_renter", {"thread_id": "T001", "fields": {"gate": {"lease": {"status": "answered", "months": "six"}}}},
             "INVALID_ARGS")


def test_send_message_unlinked_thread_allows_any_record_figure():
    w = rt.load(patch={"threads": [{"thread_id": "T9", "channel": "sms", "renter_name": "A", "messages": [{"from": "renter", "text": "hi"}]}]})
    call_ok(w, "send_message", {"thread_id": "T9", "text": "We have rooms from $725 a month."})
    call_err(w, "send_message", {"thread_id": "T9", "text": "We have rooms from $10 a month."}, "POLICY_BLOCKED")


# ---------------------------------------------------------------- reader tool

def test_read_reply_from_thread_and_text(world, monkeypatch):
    monkeypatch.delenv("READER_BASE_URL", raising=False)
    world.threads[0]["messages"].append({"from": "operator", "text": "Are you okay with a 12-month lease?", "id": "x", "attachments": [], "ts": "t"})
    world.threads[0]["messages"].append({"from": "renter", "text": "yes", "id": "y", "attachments": [], "ts": "t"})
    d = call_ok(world, "read_reply", {"thread_id": "T001"})
    assert d["lease"] == {"status": "answered", "value": True} and d["backend"] == "fallback"
    d = call_ok(world, "read_reply", {"text": "moving next month, (919) 555-0123", "pending_item": "move_in"})
    assert d["move_in"]["status"] == "vague" and d["phone"]["value"] == "+19195550123"
    call_err(world, "read_reply", {}, "INVALID_ARGS")
    call_err(world, "read_reply", {"thread_id": "T001", "text": "x"}, "INVALID_ARGS")


def test_read_reply_http_backend_falls_back(world, monkeypatch):
    monkeypatch.setenv("READER_BASE_URL", "http://127.0.0.1:9/v1")
    monkeypatch.setenv("READER_TIMEOUT", "0.5")
    d = call_ok(world, "read_reply", {"text": "just me"})
    assert d["backend"] == "fallback" and d["occupants"]["value"] == 1


def test_read_reply_http_backend_used(world, monkeypatch):
    from rentus_tools.impl import reader
    good = reader.empty_output("en") | {"phone": {"status": "answered", "value": "+19195550100"}}
    monkeypatch.setattr(reader, "_http_read", lambda inp: good)
    d = call_ok(world, "read_reply", {"text": "anything"})
    assert d["backend"] == "model" and d["phone"]["value"] == "+19195550100"


# ---------------------------------------------------------------- register

def test_upsert_renter_create_update_and_gate(world):
    d = call_ok(world, "upsert_renter", {"thread_id": "T001", "fields": {"name": "Maria", "gate": {"lease": True},
                                                                         "wants": {"budget": 800, "area": "Durham", "private_bath": True}}})
    rid = d["renter"]["renter_id"]
    assert rid == "renter:maria" and d["created"] and d["renter"]["status"] == "qualifying"
    assert d["gate_missing"] == ["move_in", "phone", "reason", "occupants"]
    d = call_ok(world, "upsert_renter", {"thread_id": "T001", "fields": {"gate": {k: v for k, v in COMPLETE_GATE.items() if k != "lease"}}})
    assert not d["created"] and d["gate_missing"] == [] and d["renter"]["status"] == "qualified"
    assert d["renter"]["phone"] == "+19195550123"
    assert rt.gate_complete(world, rid)


def test_upsert_renter_validation(world):
    call_err(world, "upsert_renter", {"thread_id": "T001", "fields": {"age": 30}}, "INVALID_ARGS")
    call_err(world, "upsert_renter", {"thread_id": "T001", "fields": {"gate": {"credit": 700}}}, "INVALID_ARGS")
    call_err(world, "upsert_renter", {"thread_id": "T001", "fields": {"gate": {"move_in": "next month"}}}, "INVALID_ARGS")
    call_err(world, "upsert_renter", {"thread_id": "T001", "fields": {"gate": {"phone": "555"}}}, "INVALID_ARGS")
    call_err(world, "upsert_renter", {"thread_id": "T001", "fields": {"gate": {"lease": {"status": "maybe"}}}}, "INVALID_ARGS")
    call_err(world, "upsert_renter", {"thread_id": "T001", "fields": {"status": "happy"}}, "INVALID_ARGS")
    call_err(world, "upsert_renter", {"thread_id": "T404", "fields": {}}, "NOT_FOUND")
    assert world.register == []  # nothing half-written
    vague = call_ok(world, "upsert_renter", {"thread_id": "T001", "fields": {"gate": {"move_in": {"status": "vague", "date": None, "raw": "next month"}}}})
    assert "move_in" in vague["gate_missing"]


def test_renter_id_slug_transliterates_accents(world):
    from rentus_tools.impl.register import _slug
    assert _slug("María") == "maria"
    assert _slug("José Núñez-Peña") == "jose-nunez-pena"
    assert _slug("Zoë Strauß") == "zoe-strauss"
    assert _slug("Łukasz Øvergård") == "lukasz-overgard"
    assert _slug("李 Wei") == "李-wei"  # no ASCII form: kept, not dropped
    assert _slug("  ") == "renter"
    d = call_ok(world, "upsert_renter", {"thread_id": "T001", "fields": {"name": "María"}})
    assert d["renter"]["renter_id"] == "renter:maria"


def test_match_renters(world):
    world.threads.append({"thread_id": "T002", "channel": "sms", "renter_name": "Ben", "messages": []})
    call_ok(world, "upsert_renter", {"thread_id": "T001", "fields": {"gate": COMPLETE_GATE, "wants": {"budget": 800, "area": "Durham"}}})
    call_ok(world, "upsert_renter", {"thread_id": "T002", "fields": {"wants": {"budget": 500, "area": "Raleigh"}}})
    m = call_ok(world, "match_renters", {"room_id": "R023"})["matches"]
    assert [x["renter_id"] for x in m] == ["renter:maria", "renter:ben"]
    assert m[0]["score"] > m[1]["score"] and m[0]["reasons"]


# ---------------------------------------------------------------- calendar

def _qualified(world):
    return call_ok(world, "upsert_renter", {"thread_id": "T001", "fields": {"gate": COMPLETE_GATE}})["renter"]["renter_id"]


def test_showing_slots_and_propose(world):
    rid = _qualified(world)
    slots = call_ok(world, "find_showing_slots", {"room_id": "R023", "date_from": "2026-10-17", "date_to": "2026-10-18"})["slots"]
    assert slots and all(s["start"] > "2026-10-17T09:00" for s in slots)
    ev = call_ok(world, "propose_showing", {"renter_id": rid, "room_id": "R023", "start": slots[0]["start"]})["event"]
    assert ev["status"] == "proposed" and world.get("register", rid)["status"] == "showing_proposed"
    again = call_ok(world, "find_showing_slots", {"room_id": "R023", "date_from": "2026-10-17", "date_to": "2026-10-17"})["slots"]
    assert slots[0] not in again
    call_err(world, "propose_showing", {"renter_id": rid, "room_id": "R023", "start": slots[1]["start"]}, "CONFLICT")


def test_showing_slot_validation(world):
    rid = _qualified(world)
    call_err(world, "find_showing_slots", {"room_id": "R023", "date_from": "2026-10-20", "date_to": "2026-10-19"}, "INVALID_ARGS")
    call_err(world, "find_showing_slots", {"room_id": "R023", "date_from": "2026-10-01", "date_to": "2026-11-30"}, "INVALID_ARGS")
    call_err(world, "propose_showing", {"renter_id": rid, "room_id": "R023", "start": "2026-10-18T22:00"}, "CONFLICT")
    call_err(world, "propose_showing", {"renter_id": rid, "room_id": "R023", "start": "2026-10-16T12:00"}, "INVALID_ARGS")


def test_available_blocks_restrict_slots(world):
    world.calendar.append({"event_id": "B1", "title": "open", "start": "2026-10-18T14:00", "end": "2026-10-18T15:00",
                           "status": "available_block", "room_id": "R023"})
    slots = call_ok(world, "find_showing_slots", {"room_id": "R023", "date_from": "2026-10-18", "date_to": "2026-10-18"})["slots"]
    assert [s["start"] for s in slots] == ["2026-10-18T14:00", "2026-10-18T14:30"]


@pytest.mark.parametrize("item,bad", [
    ("lease", {"status": "exception", "value": True}),   # conditional yes is not explicit
    ("lease", {"status": "vague", "value": None}),
    ("move_in", {"status": "vague", "date": None, "raw": "next month"}),
    ("phone", {"status": "vague", "value": None}),
    ("reason", {"status": "vague", "value": None}),
    ("occupants", {"status": "absent", "value": None}),
])
def test_propose_showing_refuses_incomplete_gate(world, item, bad):
    gate = {**COMPLETE_GATE, item: bad}
    rid = call_ok(world, "upsert_renter", {"thread_id": "T001", "fields": {"gate": gate}})["renter"]["renter_id"]
    e = call_err(world, "propose_showing", {"renter_id": rid, "room_id": "R023", "start": "2026-10-18T11:00"}, "POLICY_BLOCKED")
    assert e["details"]["missing"] == [item] and item in e["hint"]
    assert world.calendar == []


def test_propose_showing_refuses_too_many_occupants(world):
    rid = call_ok(world, "upsert_renter", {"thread_id": "T001", "fields": {"gate": {**COMPLETE_GATE, "occupants": 5}}})["renter"]["renter_id"]
    call_err(world, "propose_showing", {"renter_id": rid, "room_id": "R023", "start": "2026-10-18T11:00"}, "POLICY_BLOCKED")


# ---------------------------------------------------------------- ops

def test_web_search_and_fetch(world):
    res = call_ok(world, "web_search", {"query": "plumber durham 27701"})["results"]
    assert res and all("plumber" in r["title"] for r in res)
    page = call_ok(world, "fetch_page", {"url": res[0]["url"]})
    assert "Phone:" in page["text"] and "quote_range" not in page["text"]
    call_err(world, "fetch_page", {"url": "https://example.com"}, "NOT_FOUND")
    assert call_ok(world, "web_search", {"query": "pizza"})["results"] == []


def test_find_vendors_hides_simulator_truth(world):
    v = call_ok(world, "find_vendors", {"trade": "plumbing", "zip": "27701"})["vendors"]
    assert len(v) == 4 and all("responds" not in x and "quote_range" not in x for x in v)
    assert v == sorted(v, key=lambda x: -x["rating"])
    call_err(world, "find_vendors", {"trade": "astrologer", "zip": "27701"}, "INVALID_ARGS")


def test_create_job_resolves_property_zip_and_address(world):
    r20 = world.get("rooms", "R020")
    street = r20["address"].split(",")[0]
    by_id = call_ok(world, "create_job", {"property": "r020", "issue": "leak", "severity": "medium"})
    j = by_id["job"]
    assert (j["room_id"], j["zip"], j["address"], j["area"]) == ("R020", r20["zip"], r20["address"], r20["area"])
    assert j["job_id"] in by_id["next"] and "hint" not in by_id
    by_addr = call_ok(world, "create_job", {"property": street, "issue": "dripping ceiling", "severity": "medium"})["job"]
    assert by_addr["zip"] == r20["zip"] and by_addr["address"] == r20["address"] and by_addr["room_id"] == "R020"
    full = call_ok(world, "create_job", {"property": f"Tenant at {street.upper()}, Raleigh", "issue": "x", "severity": "low"})["job"]
    assert full["zip"] == r20["zip"]
    z = call_ok(world, "create_job", {"property": "some house in 27701", "issue": "x", "severity": "low"})["job"]
    assert z["zip"] == "27701" and z["address"] is None
    miss = call_ok(world, "create_job", {"property": "1 Nowhere Lane", "issue": "x", "severity": "low"})
    assert miss["job"]["zip"] is None and "list_rooms" in miss["hint"]


def test_find_vendors_by_job_id(world):
    j = call_ok(world, "create_job", {"property": "R001", "issue": "sink leak", "severity": "medium"})["job"]
    by_job = call_ok(world, "find_vendors", {"trade": "plumber", "job_id": j["job_id"]})
    by_zip = call_ok(world, "find_vendors", {"trade": "plumber", "zip": j["zip"]})
    assert by_job["vendors"] == by_zip["vendors"] and by_job["zip"] == j["zip"] and by_job["job_id"] == j["job_id"]
    assert call_ok(world, "find_vendors", {"trade": "plumber", "zip": j["zip"], "job_id": j["job_id"]})["vendors"]
    e = call_err(world, "find_vendors", {"trade": "plumber", "zip": "27999", "job_id": j["job_id"]}, "INVALID_ARGS")
    assert e["details"]["job_zip"] == j["zip"] and "job_id alone" in e["hint"]
    call_err(world, "find_vendors", {"trade": "plumber", "job_id": "J999"}, "NOT_FOUND")


def test_find_vendors_invalid_args_say_how_to_get_a_zip(world):
    e = call_err(world, "find_vendors", {"trade": "plumber"}, "INVALID_ARGS")
    assert "job_id" in e["hint"] and "get_room" in e["hint"]
    e = call_err(world, "find_vendors", {"trade": "plumber", "zip": "Silverbell Run"}, "INVALID_ARGS")
    assert "5-digit" in e["message"] and "create_job" in e["hint"] and "never guess" in e["hint"]
    nz = call_ok(world, "create_job", {"property": "1 Nowhere Lane", "issue": "x", "severity": "low"})["job"]
    e = call_err(world, "find_vendors", {"trade": "plumber", "job_id": nz["job_id"]}, "INVALID_ARGS")
    assert "list_rooms" in e["hint"]
    # an explicit zip still works for a job whose property matched no room
    assert call_ok(world, "find_vendors", {"trade": "plumber", "job_id": nz["job_id"], "zip": "27701"})["vendors"]


def test_find_vendors_and_create_job_descriptions_explain_zip():
    for variant in ("verbose", "terse"):
        tools = {t["function"]["name"]: t["function"] for t in rt.tool_schemas(variant)}
        fv, cj = tools["find_vendors"], tools["create_job"]
        assert fv["parameters"]["required"] == ["trade"] and {"zip", "job_id"} <= set(fv["parameters"]["properties"])
        assert "job_id" in fv["description"] and "zip" in cj["description"]
        assert fv["parameters"]["properties"]["job_id"].get("description")


def test_ops_quote_and_book_flow(world):
    job = call_ok(world, "create_job", {"property": "R001", "issue": "kitchen sink leaking", "severity": "medium"})["job"]
    q1 = call_ok(world, "request_quote", {"vendor_id": "V02", "job_id": job["job_id"], "description": "leak under sink"})["quote"]
    lo, hi = world.get("vendors", "V02")["quote_range"]
    assert lo <= q1["amount"] <= hi and q1["status"] == "offered"
    again = call_ok(world, "request_quote", {"vendor_id": "V02", "job_id": job["job_id"], "description": "x"})
    assert again["existing"] and again["quote"]["quote_id"] == q1["quote_id"]
    e = call_err(world, "request_quote", {"vendor_id": "V03", "job_id": job["job_id"], "description": "x"}, "TIMEOUT")
    assert e["retryable"] is False and "another vendor" in e["hint"]
    q2 = call_ok(world, "request_quote", {"vendor_id": "V01", "job_id": job["job_id"], "description": "x"})["quote"]
    booked = call_ok(world, "book_vendor", {"quote_id": q1["quote_id"]})["job"]
    assert booked["status"] == "booked" and booked["cost"] == q1["amount"] and booked["vendor_id"] == "V02"
    assert world.get("quotes", q2["quote_id"])["status"] == "declined"
    call_err(world, "book_vendor", {"quote_id": q2["quote_id"]}, "CONFLICT")


def test_book_vendor_budget_exceeded(world):
    job = call_ok(world, "create_job", {"property": "R001", "issue": "water heater replacement", "severity": "high"})["job"]
    q = call_ok(world, "request_quote", {"vendor_id": "V04", "job_id": job["job_id"], "description": "replace heater"})["quote"]
    assert q["amount"] > world.policy["spend_limit_usd"]
    e = call_err(world, "book_vendor", {"quote_id": q["quote_id"]}, "BUDGET_EXCEEDED")
    assert e["retryable"] is False and "escalate_to_owner" in e["hint"] and e["details"]["limit"] == 500
    assert world.get("jobs", job["job_id"])["status"] == "quoting"
    esc = call_ok(world, "escalate_to_owner", {"reason": "quote over limit", "ref_id": job["job_id"], "draft": "Approve $" + str(q["amount"]) + "?"})
    assert esc["escalation"]["job_id"] == job["job_id"]


def test_quote_amounts_are_deterministic():
    amounts = []
    for _ in range(2):
        w = rt.load()
        j = rt.call(w, "create_job", {"property": "R001", "issue": "no heat", "severity": "emergency"})["data"]["job"]
        amounts.append(rt.call(w, "request_quote", {"vendor_id": "V05", "job_id": j["job_id"], "description": "x"})["data"]["quote"]["amount"])
    assert amounts[0] == amounts[1]


# ---------------------------------------------------------------- owner

def test_escalate_and_report(world):
    e = call_ok(world, "escalate_to_owner", {"reason": "asks for 6-month lease", "ref_id": "T001", "draft": "Owner, ok?"})["escalation"]
    assert e["thread_id"] == "T001" and e["ref_type"] == "thread_id" and e["status"] == "open"
    dup = call_ok(world, "escalate_to_owner", {"reason": "asks for 6-month lease", "ref_id": "T001"})
    assert dup["existing"] and len(world.escalations) == 1
    call_err(world, "escalate_to_owner", {"reason": "x", "ref_id": "nope"}, "NOT_FOUND")
    call_err(world, "report_to_owner", {"summary": " "}, "INVALID_ARGS")
    assert call_ok(world, "report_to_owner", {"summary": "done"}) == {"ok": True}
