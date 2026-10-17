"""Deterministic reader fallback: the schema rules in data/reader_schema.md."""
import pytest

from rentus_tools.impl.reader import read_reply_fallback as read, valid_reader_json

TODAY = "2026-10-17"  # a Saturday


def r(text, **kw):
    out = read(text, today=TODAY, **kw)
    assert valid_reader_json(out)
    return out


@pytest.mark.parametrize("text,status,date", [
    ("I'd like to move in Nov 1st", "answered", "2026-11-01"),
    ("me gustaría mudarme el primero de noviembre", "answered", "2026-11-01"),
    ("move in date would be the 15th", "answered", "2026-11-15"),
    ("planning to move 11/20", "answered", "2026-11-20"),
    ("I can move this Tuesday", "answered", "2026-10-20"),
    ("Nov 1 unless my current lease gets extended", "exception", "2026-11-01"),
    ("moving next month", "vague", None),
    ("a fines de mes", "vague", None),
    ("around the 15th", "vague", None),
    ("I'd like to move in 1/11", "vague", None),       # month/day order ambiguous
    ("I don't have a move in date yet", "no", None),
])
def test_move_in(text, status, date):
    m = r(text)["move_in"]
    assert (m["status"], m["date"]) == (status, date)


def test_visit_date_is_not_move_in():
    o = r("can I come see it Sunday at 3?")
    assert o["move_in"]["status"] == "absent" and "scheduling" in o["intents"]


@pytest.mark.parametrize("text,status,value", [
    ("(919) 555-0123", "answered", "+19195550123"),
    ("my cell is 919.555.0123", "answered", "+19195550123"),
    ("use +19195550123 for now, I'm getting a new number soon", "exception", "+19195550123"),
    ("my number starts with 919", "vague", None),
    ("I'd rather not share my number", "no", None),
])
def test_phone(text, status, value):
    assert r(text)["phone"] == {"status": status, "value": value}


def test_property_phone_question_is_not_renter_phone():
    o = r("what's your phone number?")
    assert o["phone"]["status"] == "absent" and "question" in o["intents"]


@pytest.mark.parametrize("text,status,value", [
    ("just me", "answered", 1), ("me and my dog", "answered", 1), ("me and my wife", "answered", 2),
    ("somos tres", "answered", 3), ("mi esposa, mi hija y yo", "answered", 3),
    ("maybe me and a friend", "vague", None),
    ("just me, but my boyfriend stays over on weekends", "exception", 1),
    ("why does it matter how many people?", "no", None),
])
def test_occupants(text, status, value):
    assert r(text)["occupants"] == {"status": status, "value": value}


@pytest.mark.parametrize("text,status,value", [
    ("a year works for me", "answered", True), ("sí, un año está bien", "answered", True),
    ("probably could do a year", "vague", None), ("I can't commit to a full year", "no", False),
    ("12 months ok as long as I can sublet over the summer", "exception", True),
])
def test_lease(text, status, value):
    assert r(text)["lease"] == {"status": status, "value": value}


def test_bare_yes_needs_the_question():
    assert r("yes")["lease"]["status"] == "absent"
    assert r("yes", pending_item="lease")["lease"] == {"status": "answered", "value": True}
    ctx = [{"role": "operator", "text": "Are you okay with a 12-month lease?"}]
    assert r("sí claro", context=ctx)["lease"]["value"] is True


@pytest.mark.parametrize("text,status,value", [
    ("I'm starting a new job at Duke", "answered", "new job at Duke"),
    ("my current lease is ending", "answered", "current lease ending"),
    ("me mudo desde Charlotte por trabajo", "answered", "relocating from Charlotte for work"),
    ("just need a change", "vague", None), ("I'd rather not say why", "no", None),
])
def test_reason(text, status, value):
    assert r(text)["reason"] == {"status": status, "value": value}


@pytest.mark.parametrize("text,intent", [
    ("could you go down to 700?", "price_negotiation"), ("can I come see it Sunday?", "scheduling"),
    ("thanks!!", "small_talk"), ("not moving until the spring", "not_now"), ("I found a place already", "hard_no"),
    ("can I do month to month?", "shorter_lease"), ("is it furnished?", "question"),
])
def test_intents(text, intent):
    assert intent in r(text)["intents"]


def test_language():
    assert r("Hola, ¿sigue disponible el cuarto?")["language"] == "es"
    assert r("Hi, is the room still available?")["language"] == "en"


def test_multi_field_message():
    o = r("hi! a year works for me, just me, (984) 555-0133, I'm starting a new job at Duke and I'd like to move in Nov 1st")
    assert o["lease"]["value"] is True and o["occupants"]["value"] == 1 and o["phone"]["value"] == "+19845550133"
    assert o["reason"]["value"] == "new job at Duke" and o["move_in"]["date"] == "2026-11-01" and o["intents"] == []
