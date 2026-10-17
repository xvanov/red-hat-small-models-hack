"""Train-split failure diagnosis (never run on held-out while designing changes).

    python gym/results/_p21/diagnose.py gym/results/train-baseline [--nemo]
"""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

d = Path(sys.argv[1])
s = json.loads((d / "summary.json").read_text())
assert s["split"] == "train", "diagnosis is train-only"
rows = [json.loads(l) for l in open(d / "per_task.jsonl")]
print(d.name, "pass", s["pass_rate"], "reward", s["mean_reward"])
print("by_category", {k: (v["pass_rate"], v["mean_reward"]) for k, v in s["by_category"].items()})
print("check_pass_rate", s["check_pass_rate"])
fail = Counter()
for r in rows:
    for c in r.get("checks") or []:
        if not c["pass"]:
            fail[(r["category"], c["name"])] += 1
print("\nfailing checks (category, check) -> count")
for k, v in fail.most_common(40):
    print(f"  {v:3d}  {k}")

tdir = d / "transcripts"
if tdir.exists():
    print("\nper-task behaviour (local runner)")
    beh = Counter()
    for r in rows:
        t = json.loads((tdir / f"{r['task_id']}.json").read_text())
        tools = [e["tool"] for e in t["trace"]]
        sends = tools.count("send_message")
        msgs = t["messages"]
        plain = [m for m in msgs if m["role"] == "assistant" and not m.get("tool_calls") and (m.get("content") or "").strip()]
        verif = [m for m in msgs if m["role"] == "user" and str(m.get("content", "")).startswith("[verifier]")]
        tag = []
        if r["category"] == "leasing":
            tag.append("no_send" if sends == 0 else f"sends={sends}")
        tag.append(f"status={t['status']}")
        if verif:
            tag.append(f"selfcheck_bounces={len(verif)}")
        beh[(r["category"], tag[0])] += 1
        print(f"  {r['task_id']:40s} r={r['reward']:.2f} {' '.join(tag)} tools={len(tools)} "
              f"last_plain={(plain[-1]['content'][:90] if plain else '').replace(chr(10), ' ')!r}")
    print("\nbehaviour counts", dict(beh))
