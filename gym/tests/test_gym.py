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


# ----------------------------------------------------------------------------- task set v2
from datetime import date  # noqa: E402

from rentus_env.counterparts import Counterpart  # noqa: E402

INV = {r["room_id"]: r for r in json.loads((HERE.parent / "data" / "published" / "inventory.json").read_text())["rooms"]}


def tasks_v2(split):
    return [json.loads(l) for l in open(HERE / "tasks" / "v2" / f"{split}.jsonl")]


def test_v2_build_is_reproducible():
    before = {s: (HERE / "tasks" / "v2" / f"{s}.jsonl").read_text() for s in ("train", "heldout")}
    subprocess.run([sys.executable, str(HERE / "build_tasks.py")], check=True, capture_output=True)
    for s, text in before.items():
        assert (HERE / "tasks" / "v2" / f"{s}.jsonl").read_text() == text


def test_v2_counts_and_no_overlap():
    tr, ho = tasks_v2("train"), tasks_v2("heldout")
    assert len(tr) >= 50 and len(ho) >= 30
    src = lambda ts: {l["src"] for t in ts for c in t["counterparts"] for l in c["script"] if "src" in l}
    assert not (src(tr) & src(ho))
    test_ids = {json.loads(l)["id"] for l in open(HERE.parent / "data" / "published" / "reader" / "test.jsonl")}
    assert src(ho) <= test_ids  # held-out phrasings only from the reader test split


def test_v2_oracle_passes_everything():
    for t in tasks_v2("heldout") + tasks_v2("train"):
        r = oracle.play(t)
        assert r["pass"], (t["id"], [c for c in r["checks"] if not c["pass"]])


def test_v2_do_nothing_scores_low():
    rewards = []
    for t in tasks_v2("heldout"):
        s = RolloutSession(t)
        rewards.append(verify(t, s.trace, s.final_state())["reward"])
    assert sum(rewards) / len(rewards) < 0.5
    assert not any(r == 1.0 for r in rewards)


def test_v2_move_in_never_before_availability():
    for t in tasks_v2("train") + tasks_v2("heldout"):
        cp = (t["counterparts"] or [{}])[0]
        if "room_of_interest" not in cp:
            continue
        room = dict(INV[cp["room_of_interest"]])
        for p in t["initial_state"].get("rooms", []):
            room.update(p)
        want = next((c["equals"] for c in t["checks"] if c.get("path", "").endswith(".gate.move_in.date")), None)
        if want:
            assert date.fromisoformat(want) >= date.fromisoformat(room["available_from"]), t["id"]
        occ = next((c["equals"] for c in t["checks"] if c.get("path", "").endswith(".gate.occupants.value")), None)
        if occ:
            assert occ <= room["max_occupants"], t["id"]


def test_v2_one_name_per_renter():
    from build_tasks import _NAME_RE
    for t in tasks_v2("train") + tasks_v2("heldout"):
        for cp in t["counterparts"]:
            names = {m.group(1).lower() for ln in cp["script"] for m in _NAME_RE.finditer(ln["say"])}
            assert len(names) <= 1, (t["id"], names)


def test_counterpart_fallbacks():
    cp = Counterpart({"id": "renter:x", "classifier": "v2", "script": [
        {"after": "start", "say": "hi"},
        {"when_asked": "move_in", "say": "dec 1"},
        {"when_asked": "move_in", "say": "Yes, December 1 is my move-in date.", "reuse": True},
        {"when_asked": "any", "say": "What else do you need?", "reuse": True}]})
    cp.opening()
    assert cp.respond("Thanks, the room is available.") == (None, None)  # no question: a fallback stays quiet
    assert cp.respond("What is your exact intended move-in date?")[1] == "dec 1"
    assert cp.respond("Just to confirm, your move-in date is December 1?")[1].startswith("Yes, December 1")
    assert cp.respond("The room is free from December 1, would that work?")[1].startswith("Yes, December 1")
    assert cp.respond("Do you have a car?")[1] == "What else do you need?"
    assert cp.respond("Do you have a car?")[1] == "What else do you need?"  # reusable
    nn = Counterpart({"id": "renter:y", "script": [{"when_asked": "any", "say": "not now"},
                                                   {"when_asked": ["other", "move_in"], "say": "around January"}]})
    assert nn.respond("Thanks for writing.")[1] == "not now"
    assert nn.respond("When do you think you'll start looking again?")[1] == "around January"


def test_v1_classifier_unchanged_for_availability_questions():
    assert classify_question("The room is free from December 1, would that work?") == "other"
    assert classify_question("The room is free from December 1, would that work?", "v2") == "move_in"


def test_scorer_style_matches_the_send_tool():
    from rentus_env.verify import check_style, sentences
    assert len(sentences("The room at 494 Tillbrook Ct. is free. Rent is $875.00 a month.")) == 2
    ctx = lambda text: {"trace": [{"i": 0, "tool": "send_message", "ok": True, "args": {"thread_id": "t", "text": text}}]}
    fp = {"rule": "first_person", "thread": "t"}
    assert check_style(fp, ctx("I'm the owner, so I can answer that."))[0]
    assert not check_style(fp, ctx("I will check with the owner."))[0]
    assert not check_style(fp, ctx("Le pregunto al dueño."))[0]
    assert not check_style({"rule": "no_long_dash", "thread": "t"}, ctx("Sure -- see you then."))[0]
