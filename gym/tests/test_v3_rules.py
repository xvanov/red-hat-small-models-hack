"""Amendment 1 scorer and counterpart rules for v3 twin tasks (gym/rentus_env/v3_rules.py). Offline, fixture data only."""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

from rentus_env import verify  # noqa: E402
from rentus_env.counterparts import Counterpart  # noqa: E402
from rentus_env.llm_renter import LLMRenter  # noqa: E402
from rentus_env.v3_rules import RULES_VERSION, apply_v3_rules  # noqa: E402

FIXTURE = HERE.parent / "data" / "twins" / "fixtures" / "out" / "published" / "gym_tasks_v3.jsonl"
TASKS = {json.loads(l)["subcategory"]: json.loads(l) for l in open(FIXTURE)}


def send(i, tid, text, ok=True, reply=None):
    e = {"i": i, "tool": "send_message", "args": {"thread_id": tid, "text": text}, "ok": ok, "gate_before": {}}
    if reply:
        e["asked"], e["reply"] = None, reply
    return e


def names(res):
    return {c["name"]: c for c in res["checks"]}


def test_non_v3_task_untouched():
    v2 = json.loads(open(HERE / "tasks" / "v2" / "heldout.jsonl").readline())
    assert apply_v3_rules(v2) is v2


def test_idempotent_and_historical_checks_dropped():
    t = apply_v3_rules(TASKS["twin_full"])
    assert t["rules"] == RULES_VERSION and apply_v3_rules(t) is t
    n = {c.get("name") for c in t["checks"]}
    assert "showing proposed" not in n and "showing proposed (rule)" in n
    g = apply_v3_rules(TASKS["twin_ghosted"])
    assert not any((c.get("name") or "").startswith("does not spam") for c in g["checks"])


def test_hard_no_answers_whatever_is_asked():
    """The historical owner asked move-in; a rule-following operator asking the lease first still gets the hard no."""
    t = apply_v3_rules(TASKS["twin_hard_no"])
    cp = Counterpart(t["counterparts"][0])
    cp.opening()
    _, say = cp.respond("How long do you want to stay? Is a one year lease okay with you?")
    assert say and "not looking" in say.lower()


def test_next_line_fires_at_its_reply_position_even_if_gate_lines_unused():
    t = apply_v3_rules(TASKS["twin_spanish"])
    cp = Counterpart(t["counterparts"][0])
    cp.opening()
    nxt = next(l for l in cp.script if l.get("when_asked") == "next")
    replies = [cp.respond("Hola, ¿todo bien?")[1] for _ in range(nxt["at_reply"])]
    assert replies[-1] == nxt["say"]


def test_greeting_alone_does_not_pass_a_ghosted_task():
    t = TASKS["twin_ghosted"]
    tid = t["counterparts"][0]["thread_id"]
    lang = t["counterparts"][0]["language"]
    hi = "¡Hola! Gracias por escribir." if lang == "es" else "Hi! Thanks for reaching out."
    res = verify(t, [send(0, tid, hi)], {"register": []})
    assert not res["pass"] and not names(res)["asks a missing gate item"]["pass"]
    ask = "¿Cuál es tu fecha exacta de mudanza?" if lang == "es" else "What is your exact intended move-in date?"
    res2 = verify(t, [send(0, tid, ask)], {"register": []})
    assert names(res2)["asks a missing gate item"]["pass"]


def test_invented_gate_value_fails():
    t = TASKS["twin_ghosted"]
    tid = t["counterparts"][0]["thread_id"]
    state = {"register": [{"renter_id": "r1", "thread_ids": [tid],
                           "gate": {"occupants": {"status": "answered", "value": 1}}}]}
    res = verify(t, [], state)
    c = names(res)["no invented gate values"]
    assert not c["pass"] and "occupants" in c["detail"]
    assert names(verify(t, [], {"register": []}))["no invented gate values"]["pass"]


def test_followups_cap_and_reask_counts_only_sent():
    t = TASKS["twin_full"]
    tid = t["counterparts"][0]["thread_id"]
    trace = [send(0, tid, "What is your exact intended move-in date?"),
             send(1, tid, "Are you still there?"), send(2, tid, "Should I close this out, or are you still looking?")]
    assert not names(verify(t, trace, {"register": []}))["at most one follow-up after an unanswered question"]["pass"]
    trace2 = [send(0, tid, "What is your exact intended move-in date?", reply="March 22"),
              send(1, tid, "Is a one year lease okay with you?"), send(2, tid, "Still there?")]
    assert names(verify(t, trace2, {"register": []}))["at most one follow-up after an unanswered question"]["pass"]
    # a REFUSED draft that re-asks move-in is not a re-ask (score what the renter received)
    refused = [send(0, tid, "What is your exact intended move-in date?", ok=False)] * 3
    assert names(verify(t, refused, {"register": []}))["does not re-ask move_in"]["pass"]


def test_guard_enforced_checks_reported_apart_and_refusals_counted():
    t = TASKS["twin_full"]
    tid = t["counterparts"][0]["thread_id"]
    e = send(0, tid, "The owner will confirm.", ok=False)
    e["refused_rules"] = ["first_person"]
    res = verify(t, [e, send(1, tid, "What is your exact intended move-in date?")], {"register": []})
    guarded = [c for c in res["checks"] if c.get("guard_enforced")]
    assert guarded and all(c["type"] == "style" for c in guarded)
    assert res["guard_enforced_checks"] == len(guarded) and "reward_earned" in res
    assert res["refused_by_rule"] == {"first_person": 1}


def test_price_escalation_needs_price_words():
    t = apply_v3_rules(TASKS["twin_price_push"])
    c = next(c for c in t["checks"] if c.get("name") == "price ask escalated")
    assert "discount" in c["reason_any"]


def test_model_played_renter_says_the_hard_no_verbatim():
    class NoModel:
        def __getattr__(self, k):
            raise AssertionError("the scripted key behaviour must not call the simulator")
    cp = dict(TASKS["twin_hard_no"]["counterparts"][0])
    r = LLMRenter(cp, TASKS["twin_hard_no"], client=NoModel())
    _, say = r.respond("Is a one year lease okay with you?")
    assert "not looking" in say.lower() and r.log[-1]["scripted_key_behavior"] == ["hard_no"]
    assert r.respond("Are you sure?")[1] is None      # then silent (ghost_after)


def test_model_played_renter_uses_gold_reason():
    cp = dict(TASKS["twin_full"]["counterparts"][0])
    gold = cp["twin_script"]["gold_facts"]["reason"]["value"]
    r = LLMRenter(cp, TASKS["twin_full"], client=object())
    assert r.truth["reason"] == gold
