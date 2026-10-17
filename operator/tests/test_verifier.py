"""Unit tests for the deterministic verifier (no loop, no model)."""
from rentus_operator import shim
from rentus_operator import verifier as V

CHECK = V.CallChecker(shim.TOOLS)


def test_valid_call_passes_untouched():
    c = CHECK.check("get_room", '{"room_id": "R001"}')
    assert c.ok and c.args == {"room_id": "R001"} and not c.repaired


def test_trivial_json_damage_is_repaired_once():
    for raw in ['{"room_id": "R001",}', "{'room_id': 'R001'}", '```json\n{"room_id": "R001"}\n```',
                '{"room_id": "R001"', '"{\\"room_id\\": \\"R001\\"}"']:
        c = CHECK.check("get_room", raw)
        assert c.ok, raw
        assert c.args == {"room_id": "R001"}
        assert c.repaired, raw


def test_python_literals_and_type_coercion():
    c = CHECK.check("list_threads", '{"unanswered_only": True}')
    assert c.ok and c.args["unanswered_only"] is True
    c = CHECK.check("create_listing", '{"room_id": "R1", "title": "t", "body": "b", "price": "750"}')
    assert c.ok and c.args["price"] == 750 and any("coerced" in r for r in c.repaired)


def test_unrepairable_and_schema_errors_give_feedback():
    c = CHECK.check("get_room", '{"room_id": }')
    assert not c.ok and "not valid JSON" in c.problems[0]
    c = CHECK.check("get_room", '{"id": "R001"}')
    assert not c.ok
    assert any("room_id is required" in p for p in c.problems)
    assert any("args.id is not a parameter" in p for p in c.problems)
    c = CHECK.check("publish_listing", '{"listing_id": "L1", "channel": "myspace"}')
    assert not c.ok and "must be one of" in c.problems[0]
    c = CHECK.check("get_rooms", "{}")
    assert not c.ok and "unknown tool" in c.problems[0]
    fb = c.feedback()
    assert fb["ok"] is False and fb["error"]["code"] == "INVALID_ARGS" and fb["verifier"]["problems"]


def test_result_envelope_and_data_shapes():
    room = {"room_id": "R1", "rent": 750, "address": "Appling Way", "private_bath": True}
    assert V.check_result("get_room", {"ok": True, "data": {"room": room}}) == []
    assert V.check_result("get_room", {"ok": True, "data": {"room": {**room, "private_bath": "yes"}}})
    assert V.check_result("get_room", {"ok": True, "data": {"room": {"room_id": "R1", "rent": 750}}})
    assert V.check_result("get_room", {"data": {}})  # no ok
    assert V.check_result("get_room", {"ok": False, "error": {"code": "WAT"}})
    assert V.check_result("get_room", {"ok": True, "data": {"room": None}})
    assert V.check_result("list_rooms", {"ok": True, "data": {"rooms": "not-a-list"}})
    assert V.check_result("get_market_rent", {"ok": True, "data": {"zori": "N/A"}})
    # flat object where the contract shows a wrapper is tolerated
    assert V.check_result("request_quote", {"ok": True, "data": {"quote_id": "Q1", "vendor_id": "V1", "amount": 120}}) == []
    bad_reader = {"lease": {"status": "maybe"}, "move_in": {"status": "answered", "date": "Nov 1"}, "phone": {},
                  "occupants": {}, "reason": {}, "intents": [], "language": "en"}
    probs = V.check_result("read_reply", {"ok": True, "data": bad_reader})
    assert any("lease.status" in p for p in probs) and any("YYYY-MM-DD" in p for p in probs)


def test_retry_policy_per_code():
    kw = dict(max_retries=2, backoff_base_s=0.5)
    d = V.decide("list_rooms", {}, {"code": "RATE_LIMITED", "retryable": True}, 0, **kw)
    assert d.action == "retry" and d.delay_s == 0.5
    assert V.decide("list_rooms", {}, {"code": "RATE_LIMITED"}, 1, **kw).delay_s == 1.0
    assert V.decide("list_rooms", {}, {"code": "RATE_LIMITED"}, 2, **kw).action == "feedback"
    d = V.decide("send_message", {}, {"code": "POLICY_BLOCKED", "message": "long dash", "hint": "use a comma"}, 0, **kw)
    assert d.action == "feedback" and d.suggestion == "use a comma"
    assert V.decide("book_vendor", {}, {"code": "BUDGET_EXCEEDED", "retryable": False}, 0, **kw).action == "feedback"
    d = V.decide("publish_listing", {"listing_id": "L1", "channel": "marketplace"}, {"code": "PAGE_CHANGED"}, 0,
                 tried_channels={"marketplace"}, **kw)
    assert d.action == "fallback" and "marketplace" not in d.alternatives and "roomies" in d.alternatives
    assert V.decide("request_quote", {}, {"code": "TIMEOUT", "retryable": True}, 0, **kw).action == "fallback"


def test_loop_guard_counts_identical_failures():
    g = V.LoopGuard(3)
    s = V.signature("get_room", {"room_id": "X"})
    assert not g.failed(s) and not g.failed(s) and g.failed(s)
    assert V.signature("a", {"x": 1, "y": 2}) == V.signature("a", {"y": 2, "x": 1})


def test_self_check_claims_vs_world():
    before = {"listings": [], "jobs": [], "calendar": [], "escalations": [], "threads": []}
    after = {"listings": [{"listing_id": "L1", "channels": {"marketplace": {"status": "live"}}}],
             "jobs": [], "calendar": [], "escalations": [], "threads": []}
    led = [{"name": "publish_listing", "args": {"listing_id": "L1", "channel": "marketplace"}, "data": {}}]
    assert V.self_check(before, after, led, "I published the listing on marketplace.") == []
    p = V.self_check(before, after, led, "I posted it on marketplace and craigslist.")
    assert p == ["summary says the listing is live on craigslist, but it is not"]
    assert V.self_check(before, after, led, "Craigslist could not be published, I will retry.") == []
    p = V.self_check(before, before, [], "I booked the plumber and escalated the quote.")
    assert any("booked" in x for x in p) and any("escalat" in x for x in p)
    # a successful call whose effect is missing from the world
    p = V.self_check(before, before, led, "Done.")
    assert p and "not live on marketplace" in p[0]
