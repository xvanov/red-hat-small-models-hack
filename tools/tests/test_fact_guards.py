"""Unconfirmed-fact guard (post-freeze fix, Oct 18) and the short, grammatical disclosure messages."""
import copy
import sys
from pathlib import Path

import pytest

import rentus_tools as rt
from conftest import call_err, call_ok
from rentus_tools.impl.demand import disclosure_messages, room_kind
from rentus_tools.impl.fact_guards import unconfirmed_facts, unconfirmed_mentions

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from channels.pilot_post import ROOM  # noqa: E402  the owner-confirmed Appling Way record

# The live Assistant run that wrote the bug (Oct 18): lease length stated though unconfirmed.
APPLING_BODY = ("Private room on Appling Way in Durham, available Nov 1 for $750/month. Private bathroom and its own "
                "separate entrance. 1 year minimum lease. Message us for details.")
CLEAN_BODY = ("Private room on Appling Way in Durham, available Nov 1 for $750/month. Private bathroom and its own "
              "separate entrance. Message us for details.")


def _appling_world(thread=False):
    w = rt.load(patch={"clock": {"now": "2026-10-18T09:00:00"}})
    w.rooms[:] = [copy.deepcopy(ROOM)]
    if thread:
        w.threads.append({"thread_id": "TA", "channel": "sms", "renter_name": "Ana", "language": "en",
                          "room_id": "R_APPLING", "messages": [{"from": "renter", "text": "Hi, is the room still available?"}]})
    return w


def test_pilot_record_marks_unconfirmed():
    assert {"lease_min_months", "deposit", "utilities", "house_rules"} <= unconfirmed_facts(ROOM)


def test_absent_core_fields_count_as_unconfirmed():
    assert unconfirmed_facts({"room_id": "X", "rent": 700}) == {"lease_min_months", "deposit", "utilities"}
    assert unconfirmed_facts({"room_id": "X", "lease_min_months": 12, "deposit": 500, "utilities": "included"}) == set()


def test_appling_exact_case_create_listing_blocked():
    w = _appling_world()
    err = call_err(w, "create_listing", {"room_id": "R_APPLING", "title": "Room on Appling Way", "body": APPLING_BODY,
                                         "price": 750}, "POLICY_BLOCKED")
    assert "not confirmed by the owner" in err["hint"] and "message us for details" in err["hint"]
    assert not w.listings
    call_ok(w, "create_listing", {"room_id": "R_APPLING", "title": "Room on Appling Way", "body": CLEAN_BODY, "price": 750})


def test_update_and_publish_blocked():
    w = _appling_world()
    lid = call_ok(w, "create_listing", {"room_id": "R_APPLING", "title": "Room on Appling Way", "body": CLEAN_BODY,
                                        "price": 750})["listing"]["listing_id"]
    call_err(w, "update_listing", {"listing_id": lid, "fields": {"body": CLEAN_BODY + " Lease: 12 months."}}, "POLICY_BLOCKED")
    # a body edited around the tools still cannot be published
    w.get("listings", lid)["body"] = APPLING_BODY
    call_err(w, "publish_listing", {"listing_id": lid, "channel": "marketplace"}, "POLICY_BLOCKED")
    w.get("listings", lid)["body"] = CLEAN_BODY
    call_ok(w, "publish_listing", {"listing_id": lid, "channel": "marketplace"})


@pytest.mark.parametrize("text,fact", [
    ("1 year minimum lease.", "lease_min_months"),
    ("Lease: 12 months.", "lease_min_months"),
    ("One-year lease.", "lease_min_months"),
    ("Minimum lease applies.", "lease_min_months"),
    ("Month-to-month is fine.", "lease_min_months"),
    ("Annual lease required.", "lease_min_months"),
    ("Contrato de un año.", "lease_min_months"),
    ("El contrato mínimo es de 6 meses.", "lease_min_months"),
    ("6 meses.", "lease_min_months"),
    ("Deposit is $750.", "deposit"),
    ("$500 deposit to move in.", "deposit"),
    ("No deposit needed.", "deposit"),
    ("Deposit equal to one month's rent.", "deposit"),
    ("El depósito es de 750 dólares.", "deposit"),
    ("Utilities included.", "utilities"),
    ("Utilities are $75 a month.", "utilities"),
    ("Los servicios están incluidos.", "utilities"),
    ("Fully furnished.", "furnished"),
    ("El cuarto está amueblado.", "furnished"),
    ("Shared kitchen and living room.", "shared_spaces"),
    ("La cocina es compartida.", "shared_spaces"),
    ("No smoking, no parties.", "house_rules"),
    ("No se permite fumar.", "house_rules"),
])
def test_patterns_en_es(text, fact):
    assert fact in {f for f, _ in unconfirmed_mentions(text, ROOM)}


@pytest.mark.parametrize("text", [
    "Private room on Appling Way, $750/month, available Nov 1.",
    "Private bathroom and separate entrance. Message us for details.",
    "Rent is $750 a month.",
    "It's available from November 1.",
    "Message us for details on furnishing and house rules.",
    "Escríbenos para más detalles sobre los servicios.",
    "Disponible el 1 de noviembre, $750 al mes.",
])
def test_allowed_text_passes(text):
    assert unconfirmed_mentions(text, ROOM) == []


def test_confirmed_facts_pass_unchanged(world):
    # R023 confirms lease, deposit and utilities: the same wording is fine there.
    room = world.get("rooms", "R023")
    text = "Lease: 1 year. Deposit is $%d. Utilities split evenly." % room["deposit"]
    assert unconfirmed_mentions(text, room) == []
    call_ok(world, "create_listing", {"room_id": "R023", "title": "Room on Appling Way", "body": text, "price": room["rent"]})


def test_send_message_refuses_unconfirmed_lease_but_allows_gate_question():
    w = _appling_world(thread=True)
    call_err(w, "send_message", {"thread_id": "TA", "text": "It's available from November 1, and the lease is 1 year."},
             "POLICY_BLOCKED")
    call_err(w, "send_message", {"thread_id": "TA", "text": "El contrato es de un año."}, "POLICY_BLOCKED")
    call_err(w, "send_message", {"thread_id": "TA", "text": "Utilities are included."}, "POLICY_BLOCKED")
    call_ok(w, "send_message", {"thread_id": "TA", "text": "It's available from November 1."})
    call_ok(w, "send_message", {"thread_id": "TA", "text": "How long do you want to stay? Is a one year lease okay with you?"})


# ----------------------------------------------------------------------------- disclosure

@pytest.mark.parametrize("rtype,en,es", [
    ("bedroom in house", "a bedroom in a shared house", "una habitación en una casa compartida"),
    ("room in house", "a private room in a shared house", "un cuarto privado en una casa compartida"),
    ("room in townhouse", "a private room in a shared townhouse", "un cuarto privado en una casa adosada compartida"),
    ("room in duplex", "a private room in a shared duplex", "un cuarto privado en un dúplex compartido"),
    ("basement suite", "a basement suite in a house", "un sótano independiente en una casa"),
    ("loft in house", "a loft in a house", "un cuarto"),
])
def test_room_kind_has_articles(rtype, en, es):
    assert room_kind(rtype, "en") == en and room_kind(rtype, "es") == es


@pytest.mark.parametrize("lang", ["en", "es"])
def test_appling_disclosure_short_confirmed_only(lang):
    w = _appling_world(thread=True)
    d = disclosure_messages(w, ROOM, lang)
    seq = d["sequence"]
    assert seq == d["messages"] + d["house_rules"] and len(d["house_rules"]) >= 1
    first = d["messages"][0]
    assert first.startswith("It's a bedroom in a house on Appling Way" if lang == "en" else
                            "Es una habitación en una casa en Appling Way")
    joined = " ".join(seq).lower()
    for word in ("lease", "contrato", "deposit", "depósito", "utilities", "servicios", "shared", "compartid", "smok", "fuma"):
        assert word not in joined
    for m in seq:
        assert len(m) <= 160 and unconfirmed_mentions(m, ROOM) == []
    w.threads[0]["language"] = lang
    w.threads[0]["messages"][0]["text"] = ("Hi, is the room still available?" if lang == "en"
                                           else "Hola, ¿todavía está disponible el cuarto?")
    for m in seq:
        call_ok(w, "send_message", {"thread_id": "TA", "text": m})


@pytest.mark.parametrize("lang", ["en", "es"])
def test_disclosure_messages_short_for_every_inventory_room(lang):
    w = rt.load(patch={"clock": {"now": "2026-10-17T09:00:00"}})
    from rentus_tools.impl.style import sentences
    for room in w.rooms:
        d = disclosure_messages(w, room, lang)
        for m in d["sequence"]:
            assert len(m) <= 160, (room["room_id"], m)
            assert len(sentences(m)) <= 2, (room["room_id"], m)
        assert any(("1 year" in m or "1 año" in m) for m in d["messages"])  # confirmed lease still stated
