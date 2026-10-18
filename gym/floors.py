"""Trivial-agent floors for a task file (protocol Amendment 1, scorer review #4). No model calls.

Four scripted non-agents play every task through the real tools and scorer:
  do_nothing     no tool calls
  greet_only     one greeting in the renter's language
  escalate_all   escalates every thread to the owner with a price-worded reason, sends nothing
  mark_lost      records every renter as lost / not_now (whichever the task's subcategory suggests), sends nothing
A task where any of them passes is FLAGGED; pass rates are reported with and without flagged tasks.

    gym/.venv/bin/python gym/floors.py --tasks-file gym/tasks/v3/heldout.jsonl [--json]
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from rentus_env import RolloutSession, verify  # noqa: E402

GREET = {"en": "Hi, thanks for reaching out about the room.", "es": "Hola, gracias por escribir sobre el cuarto."}


def play(task: dict, agent: str) -> dict:
    s = RolloutSession(task)
    for tid, cp in s.counterparts.items():
        if agent == "greet_only":
            s.call("send_message", {"thread_id": tid, "text": GREET.get(cp.language, GREET["en"])})
        elif agent == "escalate_all":
            s.call("escalate_to_owner", {"reason": "price, discount or rent question; please advise", "ref_id": tid})
        elif agent == "mark_lost":
            status = "not_now" if "not_now" in (task.get("subcategory") or "") else "lost"
            s.call("upsert_renter", {"thread_id": tid, "fields": {"status": status}})
    return verify(task, s.trace, s.final_state())


AGENTS = ("do_nothing", "greet_only", "escalate_all", "mark_lost")


def floors(tasks: list[dict]) -> dict:
    per = {a: {t["id"]: play(t, a) for t in tasks} for a in AGENTS}
    flagged = sorted({tid for a in AGENTS for tid, r in per[a].items() if r["pass"]})
    out = {"tasks": len(tasks), "flagged_tasks": flagged, "agents": {}}
    for a in AGENTS:
        rs = list(per[a].values())
        out["agents"][a] = {"mean_reward": round(statistics.fmean(r["reward"] for r in rs), 4) if rs else None,
                            "pass_rate": round(statistics.fmean(r["pass"] for r in rs), 4) if rs else None,
                            "passes": [r["task_id"] for r in rs if r["pass"]]}
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tasks-file", required=True)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    tasks = [json.loads(l) for l in open(a.tasks_file) if l.strip()]
    out = floors(tasks)
    if a.json:
        print(json.dumps(out, indent=1))
        return
    print(f"{out['tasks']} tasks; flagged (a trivial agent passes): {len(out['flagged_tasks'])} {out['flagged_tasks']}")
    print("| trivial agent | mean reward | pass rate |\n|---|---|---|")
    for k, v in out["agents"].items():
        print(f"| {k} | {v['mean_reward']:.3f} | {v['pass_rate']:.1%} |")


if __name__ == "__main__":
    main()
