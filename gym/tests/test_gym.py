"""Gym self-tests: tasks build reproducibly, the oracle passes every task, a do-nothing run fails."""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

import oracle  # noqa: E402
from rentus_env import RolloutSession, verify  # noqa: E402
from rentus_env.counterparts import classify_question  # noqa: E402


def tasks(split):
    return [json.loads(l) for l in open(HERE / "tasks" / f"{split}.jsonl")]


def test_build_is_reproducible(tmp_path):
    before = {s: (HERE / "tasks" / f"{s}.jsonl").read_text() for s in ("train", "heldout")}
    subprocess.run([sys.executable, str(HERE / "build_tasks.py")], check=True, capture_output=True)
    for s, text in before.items():
        assert (HERE / "tasks" / f"{s}.jsonl").read_text() == text


def test_counts_and_no_overlap():
    tr, ho = tasks("train"), tasks("heldout")
    assert len(tr) >= 40 and len(ho) >= 25
    src = lambda ts: {l["src"] for t in ts for c in t["counterparts"] for l in c["script"] if "src" in l}
    assert not (src(tr) & src(ho))
    assert {t["category"] for t in ho} == {"leasing", "listing", "ops", "recovery"}


def test_oracle_passes_everything():
    for t in tasks("heldout") + tasks("train"):
        r = oracle.play(t)
        assert r["pass"], (t["id"], [c for c in r["checks"] if not c["pass"]])


def test_do_nothing_scores_low():
    rewards = []
    for t in tasks("heldout"):
        s = RolloutSession(t)
        rewards.append(verify(t, s.trace, s.final_state())["reward"])
    assert sum(rewards) / len(rewards) < 0.5
    assert not any(r == 1.0 for r in rewards)


def test_question_classifier():
    assert classify_question("Great. How many people will be moving in?") == "occupants"
    assert classify_question("What is your exact intended move-in date?") == "move_in"
    assert classify_question("Is a one year lease okay with you?") == "lease"
    assert classify_question("¿Cuál es tu número de teléfono?") == "phone"
    assert classify_question("Why are you moving?") == "reason"
    assert classify_question("Thanks, noted.") is None
