"""H2 on the combined 90 owner-labeled messages (eval-protocol Amendment 7) and the confirmatory family with it.

    gym/.venv/bin/python gym/h2_combined.py --md            # family: H1/H3/H4 from the frozen plan, H2a/H2b combined
    gym/.venv/bin/python gym/h2_combined.py --md --json out.json

Preds: reader/results/{finetuned,lightning,frontier}-twin.owner_gold_combined.preds.jsonl from
`reader/eval.py --rows-file data/published/owner_gold_combined.jsonl`. They count only if their metrics file scored
the combined gold whose sha256 is recorded in data/published/owner_gold_combined.json (committed before any prediction).

Primary H2 test: exact match (`em_primary`, reason on status), one-sided H0 acc(A) - acc(B) <= 0, cluster bootstrap
over threads stratified by source (real_twin / pilot), 10,000 resamples, seed 0; p = max(bootstrap p, cluster-robust
paired-t p). Secondary (uncorrected): real_twin only, pilot only, informative rows only (stratified), per field.
No model calls.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
import stats  # noqa: E402

GOLD = REPO / "data/published/owner_gold_combined.jsonl"
RECORD = REPO / "data/published/owner_gold_combined.json"
PRED = "reader/results/{}-twin.owner_gold_combined.preds.jsonl"
PAIRS = {"H2a": ("finetuned", "lightning"), "H2b": ("finetuned", "frontier")}


def t_sf(t: float, df: int) -> float:
    """One-sided upper tail of Student t (stats.py's helper if present, else normal approx for df>=30)."""
    if hasattr(stats, "t_sf"):
        return stats.t_sf(t, df)
    x = df / (df + t * t)   # regularized incomplete beta via continued fraction is overkill here; use normal for safety
    return 0.5 * math.erfc(t / math.sqrt(2))


def stratified_test(rows, alpha=stats.ALPHA_FW, n_boot=10_000, seed=0) -> dict:
    """rows = (stratum, cluster, a_correct, b_correct)."""
    cl = defaultdict(lambda: [0, 0, None])
    for s, c, x, y in rows:
        cl[c][0] += x - y
        cl[c][1] += 1
        cl[c][2] = s
    strata = defaultdict(list)
    for v in cl.values():
        strata[v[2]].append(v)
    n = len(rows)
    d = sum(v[0] for v in cl.values()) / n if n else 0.0
    rng = random.Random(seed)
    boots = []
    for _ in range(n_boot):
        s = m = 0
        for vs in strata.values():
            for _ in range(len(vs)):
                v = vs[rng.randrange(len(vs))]
                s += v[0]
                m += v[1]
        boots.append(s / m if m else 0.0)
    boots.sort()
    p_boot = (sum(1 for x in boots if x <= 0) + 1) / (n_boot + 1)
    k = len(cl)
    var = sum((v[0] - d * v[1]) ** 2 for v in cl.values()) / n ** 2 * (k / (k - 1)) if k > 1 else 0.0
    se = math.sqrt(var)
    p_t = (0.0 if d > 0 else 1.0) if se == 0 else t_sf(d / se, k - 1)
    p = max(p_boot, p_t)
    b = sum(1 for *_, x, y in rows if x > y)
    c = sum(1 for *_, x, y in rows if x < y)
    return {"rows": n, "threads": k, "strata": {s: len(v) for s, v in strata.items()}, "d": d,
            "acc_a": sum(r[2] for r in rows) / n if n else 0.0, "acc_b": sum(r[3] for r in rows) / n if n else 0.0,
            "p_boot": p_boot, "p_t": p_t, "p": p, "lb": boots[max(0, int(math.floor(alpha * n_boot)))],
            "ci95": (boots[int(0.025 * n_boot)], boots[min(n_boot - 1, int(0.975 * n_boot))]),
            "a_only": b, "b_only": c, "reject": p <= alpha, "alpha": alpha}


def load(label: str, want_sha: str) -> dict:
    p = REPO / PRED.format(label)
    mp = Path(str(p).replace(".preds.jsonl", ".metrics.json"))
    if not p.exists() or not mp.exists():
        raise LookupError(f"missing {p.name} or its metrics")
    got = (json.loads(mp.read_text()).get("provenance") or {}).get("data_sha256")
    if got != want_sha:
        raise LookupError(f"{p.name} scored rows {str(got)[:12]}, not the recorded combined gold {want_sha[:12]}")
    return {json.loads(l)["id"]: json.loads(l) for l in open(p) if l.strip()}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", default=str(HERE / "confirmatory_v3.json"))
    ap.add_argument("--md", action="store_true")
    ap.add_argument("--json", default=None)
    a = ap.parse_args(argv)
    rec = json.loads(RECORD.read_text())
    gold = {json.loads(l)["id"]: json.loads(l) for l in open(GOLD)}
    if stats.sha256_file(GOLD) if hasattr(stats, "sha256_file") else None:
        pass
    import hashlib
    if hashlib.sha256(GOLD.read_bytes()).hexdigest() != rec["sha256"]:
        raise SystemExit("combined gold differs from its committed record")
    plan = json.loads(Path(a.plan).read_text())
    base = stats.run_plan(plan)   # gated H1/H3/H4 exactly as pre-registered
    preds, why = {}, {}
    for lab in ("finetuned", "lightning", "frontier"):
        try:
            preds[lab] = load(lab, rec["sha256"])
        except LookupError as e:
            why[lab] = str(e)
    out = {"h2": {}, "secondary": {}}
    subsets = {"all_90": lambda g: True, "real_twin_61": lambda g: g["meta"]["h2_source"] == "real_twin",
               "pilot_29": lambda g: g["meta"]["h2_source"] == "pilot", "informative": lambda g: g["meta"]["informative"]}
    for hid, (la, lb) in PAIRS.items():
        for name, keep in subsets.items():
            if la not in preds or lb not in preds:
                res = {"tested": False, "why": why.get(la) or why.get(lb)}
            else:
                ids = [i for i in gold if keep(gold[i])]
                miss = [i for i in ids if i not in preds[la] or i not in preds[lb]]
                if miss:
                    res = {"tested": False, "why": f"{len(miss)} rows missing from preds"}
                else:
                    rows = [(gold[i]["meta"]["h2_source"], gold[i]["meta"]["twin_id"],
                             int(bool(preds[la][i]["em_primary"])), int(bool(preds[lb][i]["em_primary"]))) for i in ids]
                    res = {"tested": True, **stratified_test(rows)}
            (out["h2"] if name == "all_90" else out["secondary"]).setdefault(hid, {})[name] = res
    pvals = {}
    for f in base["family"]:
        h = f["hypothesis"]
        pvals[h] = (out["h2"][h]["all_90"].get("p") if out["h2"][h]["all_90"]["tested"] else None) if h in PAIRS else f["p"] if f["tested"] else None
    out["family"] = stats.holm_family(pvals, base["alpha_familywise_one_sided"])
    out["family_preregistered_h2_real_twin_only"] = base["family"]
    out["plan_tests"] = base["tests"]
    out["input_problems"] = base["input_problems"]
    out["per_field"] = {}
    for lab, pr in preds.items():
        fa = defaultdict(lambda: [0, 0])
        for i, p in pr.items():
            for f, v in (p.get("field_correct") or {}).items():
                fa[f][0] += int(bool(v))
                fa[f][1] += 1
        out["per_field"][lab] = {f: round(c / n, 3) for f, (c, n) in fa.items() if n}
        out["per_field"][lab]["em_primary"] = round(sum(int(bool(p["em_primary"])) for p in pr.values()) / len(pr), 3)
    if a.json:
        Path(a.json).write_text(json.dumps(out, indent=1, default=str) + "\n")
    if a.md:
        L = [f"Confirmatory family with H2 on the combined 90 rows (Amendment 7), Holm one-sided alpha {base['alpha_familywise_one_sided']}, m = {len(out['family'])}:", "",
             "| hypothesis | tested | p | Holm p | alpha at rank | decision |", "|---|---|---|---|---|---|"]
        for f in out["family"]:
            L.append(f"| {f['hypothesis']} | {'yes' if f['tested'] else 'NOT TESTED'} | {stats.fmt_p(f['p'])} | {stats.fmt_p(f['holm_p'])} | "
                     f"{f['alpha_at_rank']:.4f} | {'supported' if f['reject'] else 'not supported'} |")
        L += ["", "| H2 | rows | n (rows / threads) | reader acc | comparator acc | Δ (95% CI) | one-sided lb | p (boot / t) | reader-only / comparator-only rows |",
              "|---|---|---|---|---|---|---|---|---|"]
        for hid in PAIRS:
            for name in subsets:
                r = (out["h2"] if name == "all_90" else out["secondary"])[hid][name]
                if not r["tested"]:
                    L.append(f"| {hid} | {name} | not tested: {r['why']} | | | | | | |")
                    continue
                L.append(f"| {hid} | {name}{' (primary)' if name == 'all_90' else ' (secondary)'} | {r['rows']} / {r['threads']} | {r['acc_a']:.3f} | {r['acc_b']:.3f} | "
                         f"{r['d']:+.3f} ({r['ci95'][0]:+.3f} to {r['ci95'][1]:+.3f}) | {r['lb']:+.3f} | {stats.fmt_p(r['p_boot'])} / {stats.fmt_p(r['p_t'])} | {r['a_only']} / {r['b_only']} |")
        if out["per_field"]:
            fields = sorted({f for v in out["per_field"].values() for f in v})
            L += ["", "Per-field accuracy, all 90 rows (secondary): ", "", "| system | " + " | ".join(fields) + " |", "|---|" + "---|" * len(fields)]
            for lab, v in out["per_field"].items():
                L.append(f"| {lab} | " + " | ".join(f"{v.get(f, float('nan')):.3f}" for f in fields) + " |")
        print("\n".join(L))
    return 0


if __name__ == "__main__":
    sys.exit(main())
