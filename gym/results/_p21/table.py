"""Markdown results table from run summaries. Groups repeats (<name>, <name>-s2, ...) and reports the mean.

    python gym/results/_p21/table.py heldout-base heldout-guard ...   (run names without the -sN suffix)
"""
import json
import re
import sys
from pathlib import Path
from statistics import mean

R = Path(__file__).resolve().parent.parent
CATS = ["leasing", "listing", "ops", "recovery"]


def runs(name):
    out = []
    for d in sorted(R.iterdir()):
        if d.name == name or re.fullmatch(re.escape(name) + r"-s\d+", d.name):
            f = d / "summary.json"
            if f.exists():
                out.append(json.loads(f.read_text()))
    return out


def row(name):
    ss = runs(name)
    if not ss:
        return f"| {name} | (missing) |"
    pr = [s["pass_rate"] for s in ss]
    mr = [s["mean_reward"] for s in ss]
    n = ss[0]["tasks"]
    cat = [f"{mean(s['by_category'][c]['mean_reward'] for s in ss):.3f}" for c in CATS]
    spread = f" ({min(mr):.3f} to {max(mr):.3f})" if len(ss) > 1 else ""
    reruns = sum(len((s.get("model_error_retries") or {}).get("tasks_rerun", [])) for s in ss)
    return (f"| `{name}` | {ss[0]['via']} | {len(ss)} | {mean(pr) * n:.1f}/{n} ({mean(pr) * 100:.1f}%) | "
            f"{mean(mr):.3f}{spread} | " + " | ".join(cat) + f" | {reruns} |")


print("| config | runner | runs | pass (mean) | mean reward (range) | " + " | ".join(CATS) + " | rollouts re-run after outages |")
print("|" + "---|" * (6 + len(CATS)))
for n in sys.argv[1:]:
    print(row(n))
