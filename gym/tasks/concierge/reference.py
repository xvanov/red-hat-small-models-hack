"""Privileged reference player for the concierge tasks. It is NOT a model and is never reported as one:
it replays each task's `reference` steps through the real sandbox tools (RolloutSession, scripted
counterparts) and scores the run with the real scorer, to prove every task is solvable under the
tools' rules and that a correct run scores 1.0.

    python gym/tasks/concierge/reference.py [--id concierge-park-001] [-v]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

from rentus_env import RolloutSession, verify  # noqa: E402


def _get(data, dotted: str):
    for k in dotted.split("."):
        data = data.get(k) if isinstance(data, dict) else None
    return data


def _sub(v, env: dict):
    if isinstance(v, str) and v.startswith("$") and v[1:] in env:
        return env[v[1:]]
    if isinstance(v, dict):
        return {k: _sub(x, env) for k, x in v.items()}
    if isinstance(v, list):
        return [_sub(x, env) for x in v]
    return v


def play(task: dict, verbose: bool = False) -> dict:
    s = RolloutSession(task)
    env: dict = {}
    for step in task["reference"]:
        if "send_each" in step:
            calls = [("send_message", {"thread_id": step["thread_id"], "text": t}) for t in _sub(step["send_each"], env)]
        else:
            calls = [(step["call"], _sub(step.get("args") or {}, env))]
        for name, args in calls:
            r = s.call(name, args)
            if verbose or not r.get("ok"):
                print(f"  {name} {json.dumps(args, ensure_ascii=False)[:140]} -> "
                      f"{'ok' if r.get('ok') else r['error']}", file=sys.stderr)
            if r.get("ok") and step.get("save"):
                for var, path in step["save"].items():
                    env[var] = _get(r["data"], path)
    return verify(task, s.trace, s.final_state())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=str(HERE / "train.jsonl"))
    ap.add_argument("--id")
    ap.add_argument("-v", action="store_true")
    a = ap.parse_args()
    tasks = [json.loads(l) for l in open(a.file)]
    bad = 0
    for t in tasks:
        if a.id and t["id"] != a.id:
            continue
        r = play(t, a.v)
        if not r["pass"]:
            bad += 1
            print(f"{t['id']}: {r['reward']:.2f} FAIL {[(c['name'], c['detail']) for c in r['checks'] if not c['pass']]}")
        elif a.v:
            print(f"{t['id']}: pass")
    n = len(tasks) if not a.id else 1
    print(f"reference: {n - bad}/{n} concierge tasks pass")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
