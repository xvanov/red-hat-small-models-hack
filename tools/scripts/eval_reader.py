"""Score the deterministic reader fallback on a reader split (default dev; tune on dev, report test).

Usage: tools/.venv/bin/python tools/scripts/eval_reader.py [dev|test|train] [--show FIELD] [--n 20]
Passes today + context, as read_reply does inside the sandbox.
"""
import argparse
import collections
import json
import re
from pathlib import Path

from rentus_tools.impl.reader import FIELDS, INTENTS, read_reply_fallback

ROOT = Path(__file__).resolve().parents[2]


def norm(field, v):
    if v is None:
        return None
    if field == "reason":
        return re.sub(r"\s+", " ", str(v).strip().lower().rstrip("."))
    return v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("split", nargs="?", default="dev")
    ap.add_argument("--show", default=None)
    ap.add_argument("--n", type=int, default=15)
    ap.add_argument("--source", default=None)
    a = ap.parse_args()
    p = ROOT / "data" / "processed" / "reader" / f"{a.split}.jsonl"
    if not p.exists():
        p = ROOT / "data" / "published" / "reader" / f"{a.split}.jsonl"
    rows = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
    if a.source:
        rows = [r for r in rows if r["source"] == a.source]
    st = collections.Counter(); val = collections.Counter(); exact = 0
    tp = fp = fn = 0; lang = 0; bad = collections.defaultdict(list)
    for r in rows:
        inp = r["input"]
        pred = read_reply_fallback(inp["message"], context=inp["context"], today=inp["today"])
        gold = r["output"]
        ok_all = True
        for f in FIELDS:
            g, q = gold[f], pred[f]
            s_ok = g["status"] == q["status"]
            key = "date" if f == "move_in" else "value"
            v_ok = norm(f, g.get(key)) == norm(f, q.get(key))
            st[f] += s_ok; val[f] += s_ok and v_ok
            if not (s_ok and v_ok):
                ok_all = False
                bad[f].append((inp["message"], inp["today"], g, q))
        gi, pi = set(gold["intents"]), set(pred["intents"])
        tp += len(gi & pi); fp += len(pi - gi); fn += len(gi - pi)
        if gi != pi:
            ok_all = False
            bad["intents"].append((inp["message"], inp["today"], sorted(gi), sorted(pi)))
        lang += gold["language"] == pred["language"]
        if gold["language"] != pred["language"]:
            bad["language"].append((inp["message"], "", gold["language"], pred["language"]))
        exact += ok_all and gold["language"] == pred["language"]
    n = len(rows)
    print(f"{a.split}: n={n} exact={exact / n:.3f} lang={lang / n:.3f} intent_f1={2 * tp / max(1, 2 * tp + fp + fn):.3f}")
    for f in FIELDS:
        print(f"  {f:10s} status={st[f] / n:.3f} status+value={val[f] / n:.3f}")
    if a.show:
        for m, t, g, q in bad[a.show][:a.n]:
            print("-", repr(m[:160]), t, "\n    gold", json.dumps(g, ensure_ascii=False), "\n    pred", json.dumps(q, ensure_ascii=False))


if __name__ == "__main__":
    main()
