"""Gap 1: send_message refuses third-person references to the owner, with a first-person rewrite hint."""
import pytest

from conftest import call_err, call_ok
from rentus_tools.impl.demand_guards import third_person_refs

THIRD = [
    "I proposed Saturday at 11 AM, pending the owner's confirmation.",
    "The owner will confirm the time shortly.",
    "My landlord will get back to you about the price.",
    "Let me check with my manager about that.",
    "The property manager can show you the room.",
    "Kalin will confirm the showing.",
    "El dueño te confirma la hora pronto.",
    "Lo consulto con la propietaria y te aviso.",
    "Propuse el sábado a las 11, pendiente de confirmación del dueño.",
]
FIRST = [
    "I proposed Saturday at 11 AM, pending my confirmation.",
    "I'll confirm it shortly.",
    "I'm the owner, so you can ask me anything about the room.",
    "Soy el dueño, te confirmo en breve.",
    "Your phone number is noted, thanks.",
    "Will your manager write an employment letter?",
]


@pytest.mark.parametrize("text", THIRD)
def test_third_person_detected(text):
    assert third_person_refs(text), text


@pytest.mark.parametrize("text", FIRST)
def test_first_person_passes(text):
    assert third_person_refs(text) == [], text


def test_send_message_blocks_third_person_with_hint(world):
    err = call_err(world, "send_message", {"thread_id": "T001",
                                          "text": "I proposed Saturday at 11 AM, pending the owner's confirmation."},
                   "POLICY_BLOCKED")
    assert err["details"]["rules"] == ["first_person"]
    assert err["details"]["rewrite"] is True
    assert "first person" in err["hint"] and "my confirmation" in err["hint"]
    assert len(world.threads[0]["messages"]) == 1  # nothing was sent


def test_send_message_owner_name_from_policy(world):
    world.policy["owner_names"] = ["Dana"]
    call_err(world, "send_message", {"thread_id": "T001", "text": "Dana will be at the showing."}, "POLICY_BLOCKED")
    call_ok(world, "send_message", {"thread_id": "T001", "text": "I'll be at the showing, see what time works for you."})


def test_send_message_first_person_passes(world):
    out = call_ok(world, "send_message", {"thread_id": "T001", "text": "Yes, it is available. I'll confirm the details shortly."})
    assert out["status"] == "sent"


# ----------------------------------------------------------------------------- canonical lease question

LEASE_OK = [
    "How long do you want to stay? Is a one year lease okay with you?",
    "How long would you like to stay? Is a 1 year lease ok with you?",
    "Thanks Sam. How long do you want to stay? Would a one-year lease work for you?",
    "¿Cuánto tiempo quieres quedarte? ¿Te funciona un contrato de un año?",
    "Cuánto tiempo piensas quedarte? ¿Te parece bien un contrato de 1 año?",
]
STILL_TWO = [
    "How long do you want to stay? What is your exact move-in date?",
    "How long do you want to stay? Is a one year lease okay with you? What is your phone?",
    "Is a one year lease okay with you? How long do you want to stay?",
]


@pytest.mark.parametrize("text", LEASE_OK)
def test_canonical_lease_question_is_one_item(world, text):
    from rentus_tools.impl.style import style_violations
    assert style_violations(text) == [], text


@pytest.mark.parametrize("text", STILL_TWO)
def test_other_double_questions_still_refused(text):
    from rentus_tools.impl.style import style_violations
    assert "one_question" in [r for r, _ in style_violations(text)], text


def test_send_message_accepts_canonical_lease_question(world):
    call_ok(world, "send_message", {"thread_id": "T001", "text": LEASE_OK[0]})
