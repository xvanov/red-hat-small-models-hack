"""Stats harness and llm_renter mode: offline tests (no model, a fake simulator client)."""
import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

import llm_renter_tasks  # noqa: E402
import stats  # noqa: E402
from rentus_env import RolloutSession, verify  # noqa: E402
from rentus_env.llm_renter import LLMRenter, phone_digits  # noqa: E402


# ------------------------------------------------------------------------------------- stats
def test_wilson_known_value():
    lo, hi = stats.wilson(0.5, 10)
    assert math.isclose(lo, 0.2366, abs_tol=1e-3) and math.isclose(hi, 0.7634, abs_tol=1e-3)
    assert stats.wilson(0.0, 31)[0] == 0.0


def test_exact_mcnemar():
    assert stats.binom_two_sided(0, 0) == 1.0
    assert math.isclose(stats.binom_two_sided(10, 0), 2 / 1024)
    assert math.isclose(stats.binom_two_sided(3, 1), 0.625)


def test_pass_hat_and_at_k():
    assert stats.pass_hat_k(2, 2, 2) == 1.0 and stats.pass_hat_k(1, 2, 2) == 0.0
    assert stats.pass_hat_k(2, 4, 2) == 1 / 6
    assert stats.pass_at_k(1, 2, 2) == 1.0 and stats.pass_at_k(0, 3, 2) == 0.0


def test_holm_monotone():
    adj = stats.holm([0.01, 0.04, 0.03])
    assert adj == [0.03, 0.06, 0.06]


def _cfg(label, runs):
    data = [{f"t{i}": {"task_id": f"t{i}", "category": "c", "pass": p, "reward": r} for i, (p, r) in enumerate(run)}
            for run in runs]
    return stats.Config(label, [f"{label}-{i}" for i in range(len(runs))], data)


def test_summary_and_paired_compare():
    a = _cfg("a", [[(1, 1.0)] * 20, [(1, 1.0)] * 19 + [(0, 0.5)]])
    b = _cfg("b", [[(0, 0.5)] * 20])
    s = stats.summarize(a)
    assert math.isclose(s["pass_rate"], 39 / 40) and math.isclose(s["pass_hat"][2][0], 19 / 20)
    assert s["flaky_tasks"] == 1 and s["run_sd_pass"] > 0
    c = stats.compare(a, b)
    assert c["a_better"] == 20 and c["b_better"] == 0 and c["p_pass"] < 1e-5 and c["p_reward"] < 0.01
    same = stats.compare(b, b)
    assert same["p_pass"] == 1.0 and same["d_reward"] == 0.0


def test_v1_stored_runs_load():
    """The re-analysis in docs/eval-method.md reads these committed runs."""
    if not (HERE / "results" / "heldout-base" / "per_task.jsonl").exists():
        return
    base = stats.parse_config("base=baseline,heldout-base")
    assert base.k == 2 and len(base.tasks) == 31


# ---------------------------------------------------------------------------------- llm_renter
class FakeSim:
    """Answers like a well-behaved renter from the truth sheet; can be told to lie about the phone."""

    def __init__(self, truth, lie_phone=False):
        self.truth, self.lie_phone, self.calls = truth, lie_phone, []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kw):
        self.calls.append(kw)
        assert kw["temperature"] == 0.0 and "seed" in kw
        last = kw["messages"][-1]["content"].lower()
        d = phone_digits(self.truth["phone"])[0]
        if "phone" in last or "number" in last:
            reply = "it's 555-555-5555" if self.lie_phone else f"{d[:3]}-{d[3:6]}-{d[6:]}"
            rev = ["phone"]
        elif "move" in last:
            reply, rev = "oct 7", ["move_in"]
        else:
            reply, rev = "sure", ["none"]
        msg = SimpleNamespace(content=json.dumps({"reply": reply, "revealed": rev}))
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=None)


def _demo_task():
    src = {json.loads(l)["id"]: json.loads(l) for l in open(HERE / "tasks" / "v2" / "train.jsonl")}
    return llm_renter_tasks.convert(src["lease-full-train-001"])


def test_converter_keeps_world_and_checks():
    src = {json.loads(l)["id"]: json.loads(l) for l in open(HERE / "tasks" / "v2" / "train.jsonl")}
    for tid in llm_renter_tasks.DEMO_IDS:
        t = llm_renter_tasks.convert(src[tid])
        assert t["checks"] == src[tid]["checks"] and t["initial_state"] == src[tid]["initial_state"]
        cp = t["counterparts"][0]
        assert cp["mode"] == "llm_renter" and cp["truth"]["move_in"] and cp["truth"]["phone"]
    assert llm_renter_tasks.convert(src["lease-early_date-train-001"])["counterparts"][0]["truth"]["move_in_first"]["date"] == "2027-01-30"


def test_session_uses_llm_renter_and_logs_events():
    t = _demo_task()
    s = RolloutSession(t)
    cp = next(iter(s.counterparts.values()))
    assert isinstance(cp, LLMRenter)
    cp._client = FakeSim(cp.truth)
    cp.sim["model"] = "fake"
    env = s.call("send_message", {"thread_id": cp.thread_id, "text": "Hi! What's the best phone number to reach you?"})
    assert env["ok"] and env["data"]["replies"][0]["text"] == "984-555-0134"
    log = s.simulator_log()
    ev = log["events"][0]
    assert ev["actor"] == "renter:kevin" and ev["type"] == "renter_message" and ev["data"]["asked"] == "phone"
    assert s.trace[-1]["asked"] == "phone"
    r = verify(t, s.trace, s.final_state(), "")
    assert 0 <= r["reward"] < 1   # same scorer, unchanged


def test_consistency_guard_falls_back_to_truth():
    t = _demo_task()
    cp = LLMRenter(t["counterparts"][0], t, client=FakeSim(t["counterparts"][0]["truth"], lie_phone=True))
    cp.sim["model"] = "fake"
    asked, reply = cp.respond("What's the best phone number to reach you?")
    assert asked == "phone" and "984-555-0134" in reply and cp.log[-1]["fallback"]
    assert len(cp.log[-1]["attempts"]) == 2 and "not your number" in cp.log[-1]["attempts"][0]["rejected"]


def test_ghost_after_n_replies():
    t = _demo_task()
    spec = {**t["counterparts"][0], "behaviors": {"ghost_after": 1}}
    cp = LLMRenter(spec, t, client=FakeSim(spec["truth"]))
    cp.sim["model"] = "fake"
    assert cp.respond("When would you like to move in?")[1] == "oct 7"
    assert cp.respond("And your phone number?")[1] is None and cp.ghosted


def test_scripted_mode_is_default():
    t = json.loads(open(HERE / "tasks" / "v2" / "train.jsonl").readline())
    s = RolloutSession(t)
    assert not any(isinstance(c, LLMRenter) for c in s.counterparts.values()) and s.simulator_log() is None


def test_echo_is_rejected():
    t = _demo_task()
    cp = LLMRenter(t["counterparts"][0], t, client=FakeSim(t["counterparts"][0]["truth"]))
    assert cp.consistency_problem("Great, see you at 10:30!", "great, see you at 10:30") is not None
    assert cp.consistency_problem("yes that works", "Does 10:30 work?") is None
