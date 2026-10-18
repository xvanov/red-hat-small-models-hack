"""send_message guards: no booking claim before the owner confirms; reply in the renter's language."""
import pytest

import rentus_tools as rt
from conftest import COMPLETE_GATE, call_err, call_ok
from rentus_tools.impl.guards import booking_claims, detect_language_strict, language_mismatch

CLAIMS = [
    "Your showing is confirmed for Saturday at 11 AM.",
    "Great, the visit is booked for tomorrow at 3pm.",
    "Perfect, you're booked.",
    "Confirmed!",
    "It's scheduled for Sat Oct 24 at 11.",
    "We're all set for Saturday at 11 AM.",
    "I've booked the tour for Friday.",
    "See you Saturday at 11.",
    "Great, see you then.",
    "La visita está confirmada para el sábado a las 11.",
    "Perfecto, agendado.",
    "Quedamos el sábado a las 11.",
    "Nos vemos el sábado a las 11.",
    "Te confirmo la visita del lunes.",
    "Listo, la cita quedó reservada para mañana.",
]
NOT_CLAIMS = [
    "Please confirm your phone number.",
    "I'll confirm with the owner and get back to you.",
    "I proposed Saturday at 11 AM, pending the owner's confirmation.",
    "The showing time is not confirmed yet.",
    "The owner will confirm the showing time.",
    "Does Saturday at 11 AM work for a showing?",
    "Is the visit confirmed?",
    "Rent is set at $750 a month.",
    "Your phone number is confirmed, thanks.",
    "Thanks, you're all set. I can show the room Sat Oct 24 at 11 AM, does that work?",
    "Propuse el sábado a las 11, pendiente de confirmación del dueño.",
    "El dueño confirmará la hora de la visita.",
    "¿Quedamos el sábado a las 11?",
    "¿Me confirmas tu número de teléfono?",
    "The room is available Nov 1.",
]


@pytest.mark.parametrize("text", CLAIMS)
def test_booking_claims_detected(text):
    assert booking_claims(text), text


@pytest.mark.parametrize("text", NOT_CLAIMS)
def test_not_a_booking_claim(text):
    assert booking_claims(text) == [], text


def _with_showing(world, status):
    call_ok(world, "upsert_renter", {"thread_id": "T001", "fields": {"name": "Maria", "gate": COMPLETE_GATE}})
    renter_id = world.register[0]["renter_id"]
    ev = call_ok(world, "propose_showing", {"renter_id": renter_id, "room_id": "R023", "start": "2026-10-24T11:00"})["event"]
    if status == "confirmed":
        next(e for e in world.calendar if e["event_id"] == ev["event_id"])["status"] = "confirmed"
    return renter_id


def test_send_message_blocks_claim_without_confirmed_event(world):
    e = call_err(world, "send_message", {"thread_id": "T001", "text": "Your showing is confirmed for Saturday at 11 AM."},
                 "POLICY_BLOCKED")
    assert e["details"]["rules"] == ["showing_not_confirmed"]
    assert "confirm it shortly" in e["hint"] and "owner" not in e["hint"]
    _with_showing(world, "proposed")  # proposed is still not confirmed
    call_err(world, "send_message", {"thread_id": "T001", "text": "See you Saturday at 11."}, "POLICY_BLOCKED")
    call_ok(world, "send_message", {"thread_id": "T001",
                                    "text": "I proposed Saturday at 11 AM, pending the owner's confirmation."})


def test_send_message_allows_claim_after_owner_confirms(world):
    _with_showing(world, "confirmed")
    call_ok(world, "send_message", {"thread_id": "T001", "text": "Your showing is confirmed for Saturday at 11 AM."})


def test_confirmed_event_for_another_renter_does_not_count(world):
    world.calendar.append({"event_id": "E900", "status": "confirmed", "renter_id": "renter:someone_else",
                           "room_id": "R023", "start": "2026-10-24T11:00", "end": "2026-10-24T11:30"})
    call_err(world, "send_message", {"thread_id": "T001", "text": "You're booked for Saturday at 11."}, "POLICY_BLOCKED")


def test_send_message_allows_precise_non_claims(world):
    for text in ("Please confirm your phone number.", "I'll confirm with the owner and get back to you."):
        call_ok(world, "send_message", {"thread_id": "T001", "text": text})


# ----------------------------------------------------------------------------- language


def test_detect_language_strict():
    assert detect_language_strict("Yes, the room is still available, when would you like to move in?") == "en"
    assert detect_language_strict("Sí, el cuarto todavía está disponible, ¿cuándo te quieres mudar?") == "es"
    assert detect_language_strict("Ok") is None
    assert detect_language_strict("Appling Way, Durham NC 27703") is None
    # a Spanish sentence naming English places is never called English
    assert detect_language_strict("El cuarto está en Appling Way, cerca de The Streets at Southpoint.") != "en"
    # an English sentence naming a Spanish street stays English
    assert detect_language_strict("The room is on Calle del Sol and it is available now.") == "en"


def _spanish_thread(world, language="es", text="Hola, ¿sigue disponible el cuarto?"):
    world.threads.append({"thread_id": "T_ES", "channel": "marketplace", "renter_name": "Lucía", "language": language,
                          "room_id": "R023", "messages": [{"from": "renter", "text": text}]})


def test_english_draft_on_spanish_thread_is_sent_back(world):
    _spanish_thread(world)
    e = call_err(world, "send_message", {"thread_id": "T_ES", "text": "Yes, it is still available, when would you like to move in?"},
                 "POLICY_BLOCKED")
    assert e["details"]["rules"] == ["language_mismatch"] and e["details"]["language"] == "es"
    assert e["details"]["rewrite"] is True and "Spanish" in e["hint"]
    call_ok(world, "send_message", {"thread_id": "T_ES", "text": "Sí, sigue disponible, ¿cuándo te quieres mudar?"})


def test_spanish_draft_on_english_thread_is_sent_back(world):
    e = call_err(world, "send_message", {"thread_id": "T001", "text": "Sí, el cuarto sigue disponible, ¿cuándo te quieres mudar?"},
                 "POLICY_BLOCKED")
    assert e["details"]["language"] == "en"


def test_renter_switching_language_wins_over_thread_field(world):
    # thread started (or defaulted) in English, renter now writes Spanish: reply in Spanish
    _spanish_thread(world, language="en", text="Hola, me interesa el cuarto, ¿todavía está disponible?")
    call_ok(world, "send_message", {"thread_id": "T_ES", "text": "Sí, sigue disponible, ¿cuándo te quieres mudar?"})
    call_err(world, "send_message", {"thread_id": "T_ES", "text": "Yes, it is still available, when would you move in?"},
             "POLICY_BLOCKED")


def test_language_check_ignores_short_or_name_only_drafts():
    th = {"thread_id": "x", "language": "es", "messages": [{"from": "renter", "text": "Hola, ¿está disponible el cuarto?"}]}
    assert language_mismatch(th, "Ok, gracias Maria.") is None
    assert language_mismatch(th, "Appling Way, Durham.") is None
    assert language_mismatch(th, "Perfecto, el cuarto en Appling Way está disponible.") is None
    assert language_mismatch(th, "The room on Appling Way is available, when do you want to see it?") == ("es", "en")
