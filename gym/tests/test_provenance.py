"""Run summaries record exact inputs (leakage review #8) and the rerun rule is protocol 4.4. Offline."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

import ablate  # noqa: E402
import run_eval  # noqa: E402


def test_provenance_fields():
    p = run_eval.provenance(HERE / "tasks" / "v2" / "heldout.jsonl")
    assert len(p["commit"]) == 40 and isinstance(p["dirty"], bool) and p["describe"]
    assert p["tasks_sha256"] == "7c5a626f872e0c987dc6564c1549a258564b293cb26f424dc741fcec23b33b00"   # protocol 6.1
    assert set(p["code_sha256"]) == {"gym/rentus_env", "tools", "operator", "serving"}


def test_summary_earned_reward_and_refusals():
    rows = [{"category": "leasing", "pass": False, "reward": 0.8, "reward_earned": 0.75, "pass_earned": False,
             "refused_by_rule": {"first_person": 2}, "checks": []},
            {"category": "leasing", "pass": True, "reward": 1.0, "checks": [], "refused_by_rule": {"first_person": 1}}]
    s = run_eval.summarize(rows, {})
    assert s["mean_reward_earned"] == 0.875 and s["refused_by_rule"] == {"first_person": 3}


def test_rerun_only_rollouts_that_never_reached_the_model():
    assert ablate.never_reached_model({"status": "model_error", "error": "APIConnectionError", "model_calls": 0, "steps": 0})
    assert not ablate.never_reached_model({"status": "error", "error": "Timeout", "model_calls": 4, "steps": 4})
    assert not ablate.never_reached_model({"status": "done", "error": None, "model_calls": 0})
