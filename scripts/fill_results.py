#!/usr/bin/env python3
"""Fill the {{PLACEHOLDER}} result slots in the submission docs from the committed result files.

    gym/.venv/bin/python scripts/fill_results.py                      # dry run: every placeholder, its value or why it is missing
    gym/.venv/bin/python scripts/fill_results.py --write              # replace every placeholder that has a value
    gym/.venv/bin/python scripts/fill_results.py --write --video-url https://youtu.be/...
    gym/.venv/bin/python scripts/fill_results.py --compute            # no confirmatory JSON yet: compute it in memory
    gym/.venv/bin/python scripts/fill_results.py --results-root ../rh-freeze-c81cb21/gym/results   # preview from a worktree

Sources (no model calls, stdlib only; statistics come from gym/stats.py and gym/h2_combined.py, never re-implemented):
  confirmatory family   gym/results/v3-confirmatory.json, written by `gym/h2_combined.py --json gym/results/v3-confirmatory.json`
                        (H1/H3/H4 from the frozen plan gym/confirmatory_v3.json, H2a/H2b on the 90 owner-labeled rows,
                        Amendment 7). With --compute and no file, the same code runs in memory.
  descriptive rows      gym/results/<run>/per_task.jsonl for every run in the plan that passes the freeze gate
                        (stats.check_plan); Lightning configs use the largest common complete seed prefix (Amendment 8
                        stopping rule), the frontier its complete repeats.
  scorer validation     gym/results/v3-kappa.json (stats.kappa_report output), optional
  H5 serving bench      serving/results/serve_bench.jsonl rows labeled on-r1..3 / off-r1..3 (protocol Amendment 1 A8)

Placeholders that have no value stay in the file untouched, so a partial fill is safe and can be re-run.
Exit code: 0 if every placeholder found has a value, 1 otherwise (dry run and --write alike).
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import re
import statistics
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GYM = REPO / "gym"
TARGETS = ["README.md", "docs/submission.md", "docs/demo-script.md"]
PLAN = GYM / "confirmatory_v3.json"
CONF_JSON = GYM / "results" / "v3-confirmatory.json"
KAPPA_JSON = GYM / "results" / "v3-kappa.json"
BENCH = REPO / "serving" / "results" / "serve_bench.jsonl"
PH = re.compile(r"\{\{([A-Z0-9_]+)\}\}")
LIGHTNING = ("baseline", "final", "router")
N_TASKS_EXPECTED = 46

sys.path.insert(0, str(GYM))


class Missing(Exception):
    pass


def fail(msg: str):
    raise Missing(msg)


# ----------------------------------------------------------------------------------------- formatting
def p_(p) -> str:
    if p is None:
        return "n/a"
    return "<0.001" if p < 0.001 else f"{p:.3f}"


def peq(p) -> str:
    """'= 0.023' or '< 0.001', for running text."""
    s = p_(p)
    return s.replace("<", "< ") if s.startswith("<") else f"= {s}"


def decision(fam_row: dict | None) -> str:
    if not fam_row or not fam_row.get("tested"):
        return "not tested"
    return "supported" if fam_row.get("reject") else "not supported"


def fam_line(fam_row: dict | None) -> str:
    if not fam_row or not fam_row.get("tested"):
        return "not tested (p = 1 in the Holm family)"
    return f"p {peq(fam_row['p'])}, Holm p {peq(fam_row['holm_p'])}: **{decision(fam_row)}**"


# ----------------------------------------------------------------------------------------- loaders
def load_confirmatory(path: Path, compute: bool, results_root: Path | None) -> dict:
    if path.exists():
        return json.loads(path.read_text())
    if not compute:
        raise Missing(f"{path.relative_to(REPO)} not found (run `gym/.venv/bin/python gym/h2_combined.py --json "
                      f"{path.relative_to(REPO)}`, or pass --compute)")
    import stats
    if results_root:
        stats.RESULTS = results_root
    import h2_combined
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "conf.json"
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                h2_combined.main(["--json", str(out)])
        except SystemExit as e:
            raise Missing(f"h2_combined refused: {e}")
        return json.loads(out.read_text())


def run_ok(chk: dict, run: str) -> bool:
    return run in chk["runs"] and not chk["runs"][run]


def describe_configs(plan: dict, results_root: Path | None) -> tuple[dict, dict, str]:
    """{label: summarize() + calls}, {"final:baseline": compare()}, seeds sentence."""
    import stats
    if results_root:
        stats.RESULTS = results_root
    try:
        chk = stats.check_plan(plan)
    except Exception as e:   # no freeze manifest etc.
        raise Missing(f"freeze gate unavailable: {e}")
    counted = {lab: [r for r in runs if run_ok(chk, r)] for lab, runs in plan["configs"].items()}

    def prefix(lab):
        k = 0
        for r in plan["configs"][lab]:
            if r in counted[lab]:
                k += 1
            else:
                break
        return k

    k_light = min(prefix(lab) for lab in LIGHTNING)
    k_front = prefix("frontier")
    out, cfgs = {}, {}
    for lab in plan["configs"]:
        k = k_front if lab == "frontier" else k_light
        if k == 0:
            continue
        cfg = stats.Config(lab, plan["configs"][lab][:k], strict=False)
        s = stats.summarize(cfg)
        try:
            s["calls"] = statistics.fmean(statistics.fmean(cfg.metric(t, "model_calls")) for t in cfg.tasks)
        except SystemExit:
            s["calls"] = None
        out[lab], cfgs[lab] = s, cfg
    comps = {}
    for a, b in (("final", "baseline"), ("router", "final"), ("final", "frontier")):
        if a in cfgs and b in cfgs:
            comps[f"{a}:{b}"] = stats.compare(cfgs[a], cfgs[b])
    seeds = (f"{k_light} operator seed{'s' if k_light != 1 else ''} per Lightning config (seeds 1 to {k_light}) and "
             f"{k_front} frontier repeat{'s' if k_front != 1 else ''}") if k_light else ""
    return out, comps, seeds


# ----------------------------------------------------------------------------------------- values
def build_values(a) -> tuple[dict, dict]:
    vals, why = {}, {}
    plan = json.loads(PLAN.read_text())
    rr = Path(a.results_root).resolve() if a.results_root else None

    def put(name, fn):
        try:
            v = fn()
            if v is None or v == "":
                raise Missing("no value")
            vals[name] = v
        except Missing as e:
            why[name] = str(e)
        except (KeyError, TypeError, ValueError, ZeroDivisionError) as e:
            why[name] = f"{type(e).__name__}: {e}"

    if a.video_url:
        vals["VIDEO_URL"] = a.video_url
    else:
        why["VIDEO_URL"] = "pass --video-url"

    # descriptive per-config rows
    try:
        desc, comps, seeds = describe_configs(plan, rr)
        desc_err = None
    except Missing as e:
        desc, comps, seeds, desc_err = {}, {}, "", str(e)

    def need(lab):
        if desc_err:
            raise Missing(desc_err)
        if lab not in desc:
            raise Missing(f"no complete {lab} run passes the freeze gate yet")
        return desc[lab]

    put("V3_SEEDS", lambda: seeds or fail(desc_err or "no complete runs"))
    for lab in plan["configs"]:
        L = lab.upper()
        put(f"V3_{L}_PASS", lambda lab=lab: (lambda s: f"{s['passes_mean']:.1f}/{s['tasks']} = {s['pass_rate'] * 100:.1f}% "
                                                         f"({s['pass_ci'][0] * 100:.0f} to {s['pass_ci'][1] * 100:.0f}%)")(need(lab)))
        put(f"V3_{L}_PASSPCT", lambda lab=lab: f"{need(lab)['pass_rate'] * 100:.0f} percent")
        put(f"V3_{L}_REWARD", lambda lab=lab: (lambda s: f"{s['mean_reward']:.3f} ({s['reward_ci'][0]:.3f} to "
                                                           f"{s['reward_ci'][1]:.3f})")(need(lab)))
        put(f"V3_{L}_PASSALL", lambda lab=lab: (lambda s: f"{s['pass_hat'][s['k']][0] * 100:.1f}%" if s["k"] > 1
                                                else "n/a (1 run)")(need(lab)))
        put(f"V3_{L}_CALLS", lambda lab=lab: (lambda s: f"{s['calls']:.1f}" if s.get("calls") is not None
                                              else fail("no model_calls"))(need(lab)))

    def comp(key):
        if desc_err:
            raise Missing(desc_err)
        if key not in comps:
            raise Missing(f"{key} needs both configs")
        return comps[key]

    put("H1_CI", lambda: (lambda c: f"{c['d_reward']:+.3f} ({c['d_reward_ci'][0]:+.3f} to {c['d_reward_ci'][1]:+.3f})")(comp("final:baseline")))
    put("H1_DPASS", lambda: (lambda c: f"{c['d_pass'] * 100:+.1f} points ({c['a_better']} tasks better, {c['b_better']} worse)")(comp("final:baseline")))
    put("H4_CI", lambda: (lambda c: f"{c['d_reward']:+.3f} ({c['d_reward_ci'][0]:+.3f} to {c['d_reward_ci'][1]:+.3f})")(comp("final:frontier")))

    # confirmatory family
    try:
        conf = load_confirmatory(Path(a.confirmatory_json) if a.confirmatory_json else CONF_JSON, a.compute, rr)
        conf_err = None
    except Missing as e:
        conf, conf_err = {}, str(e)

    def C():
        if conf_err:
            raise Missing(conf_err)
        return conf

    def fam(h):
        return next((f for f in C()["family"] if f["hypothesis"] == h), None)

    def test(tid):
        return next((t for t in C()["plan_tests"] if t["id"] == tid), None)

    def reward_line(tid, famid, label):
        t = test(tid)
        if not t or not t.get("tested"):
            return f"not tested ({(t or {}).get('why', 'missing')}); {fam_line(fam(famid))}"
        return (f"Δ mean reward {t['d']:+.3f} ({label}; {t['ka']} vs {t['kb']} runs, {t['tasks']} tasks), one-sided "
                f"lower bound {t['lb']:+.3f}; {fam_line(fam(famid))}")

    put("H1_RESULT", lambda: reward_line("H1", "H1", "final − baseline"))
    put("H4_RESULT", lambda: reward_line("H4", "H4", "final − frontier, margin −0.05"))
    put("H3II_RESULT", lambda: (lambda t: "not tested" if not t or not t.get("tested") else
                                f"Δ mean reward {t['d']:+.3f} (router − final, margin −0.05), one-sided lower bound {t['lb']:+.3f}, "
                                f"p {peq(t['p'])}")(test("H3ii")))
    put("H3I_RESULT", lambda: (lambda t: "not tested" if not t or not t.get("tested") else
                               f"{t['d']:+.2f} Lightning calls per task (router − final), one-sided upper bound {t['ub']:+.2f}, "
                               f"p {peq(t['p'])}")(test("H3i")))
    put("H3_DECISION", lambda: f"{fam_line(fam('H3'))} (p = the larger of the two parts)")
    for h in ("H1", "H4"):
        put(f"{h}_DECISION", lambda h=h: decision(fam(h)))

    def h2(hid, subset="all_90", short=False):
        sec = C()["h2"] if subset == "all_90" else C()["secondary"]
        r = sec[hid][subset]
        if not r.get("tested"):
            return f"not tested ({r.get('why', 'missing')})"
        core = (f"{r['acc_a']:.3f} vs {r['acc_b']:.3f}, Δ {r['d']:+.3f} (95% CI {r['ci95'][0]:+.3f} to {r['ci95'][1]:+.3f}), "
                f"{r['rows']} rows / {r['threads']} threads")
        if short:
            return core + f", p {peq(r['p'])} (uncorrected, secondary)"
        return core + f", one-sided lower bound {r['lb']:+.3f}; {fam_line(fam(hid))}"

    put("H2A_RESULT", lambda: h2("H2a"))
    put("H2B_RESULT", lambda: h2("H2b"))
    put("H2A_DECISION", lambda: decision(fam("H2a")))
    put("H2B_DECISION", lambda: decision(fam("H2b")))
    put("H2A_REAL61", lambda: h2("H2a", "real_twin_61", True))
    put("H2B_REAL61", lambda: h2("H2b", "real_twin_61", True))
    put("H2A_INFORMATIVE", lambda: h2("H2a", "informative", True))
    put("H2B_INFORMATIVE", lambda: h2("H2b", "informative", True))
    for lab in ("finetuned", "lightning", "frontier"):
        put(f"READER_EM_{lab.upper()}", lambda lab=lab: (lambda pf: f"{pf['em_primary']:.3f}" if pf
                                                          else fail(f"no {lab} preds"))(C()["per_field"].get(lab)))

    def holm_table():
        rows = ["| hypothesis | tested | p (one-sided) | Holm p | α at rank | decision |", "|---|---|---|---|---|---|"]
        for f in C()["family"]:
            rows.append(f"| {f['hypothesis']} | {'yes' if f['tested'] else 'NOT TESTED'} | {p_(f['p']) if f['tested'] else '1 (untested)'} "
                        f"| {p_(f['holm_p'])} | {f['alpha_at_rank']:.4f} | {decision(f)} |")
        if C().get("input_problems"):
            rows.append("")
            rows.append(f"Input problems reported by the gate ({len(C()['input_problems'])}): "
                        + "; ".join(C()["input_problems"][:6]) + (" ..." if len(C()["input_problems"]) > 6 else ""))
        return "\n".join(rows)
    put("HOLM_TABLE", holm_table)

    # scorer validation (owner grading, protocol A5)
    def kappa():
        if not KAPPA_JSON.exists():
            raise Missing(f"{KAPPA_JSON.relative_to(REPO)} not found (owner grading not done)")
        k = json.loads(KAPPA_JSON.read_text())
        ci = k.get("kappa_ci95") or (float("nan"), float("nan"))
        gate = "meets" if k["kappa"] >= 0.60 else "is below"
        return (f"Cohen's κ = {k['kappa']:.2f} (95% CI {ci[0]:.2f} to {ci[1]:.2f}, n = {k['n']} transcripts), which {gate} "
                f"the pre-set 0.60 gate" + ("" if k["kappa"] >= 0.60 else "; pass rates are therefore \"scorer-defined\""))
    put("KAPPA_RESULT", kappa)

    # H5 serving bench, 3 paired repetitions at N = 32
    def h5():
        if not BENCH.exists():
            raise Missing("no serve_bench.jsonl")
        tok = {}
        for line in BENCH.read_text().splitlines():
            if not line.strip():
                continue
            d = json.loads(line)
            m = re.fullmatch(r"(on|off)-r(\d)", str(d.get("label", "")))
            if m and int(d.get("concurrency", 0)) == 32 and not d.get("errors"):
                tok[(m.group(1), int(m.group(2)))] = float(d["agg_out_tok_s"])
        reps = sorted({r for (_, r) in tok if ("on", r) in tok and ("off", r) in tok})
        if len(reps) < 3:
            raise Missing(f"{len(reps)} of 3 paired repetitions (labels on-rN / off-rN at N=32) in serve_bench.jsonl")
        gains = [tok[("on", r)] / tok[("off", r)] - 1 for r in reps[:3]]
        ok = all(g > 0 for g in gains) and statistics.fmean(gains) >= 0.25
        return (f"+{statistics.fmean(gains) * 100:.0f}% mean output tok/s at N = 32 (repetitions: "
                + ", ".join(f"{g * 100:+.0f}%" for g in gains) + f"): {'supported' if ok else 'not supported'}")
    put("H5_RESULT", h5)
    return vals, why


# ----------------------------------------------------------------------------------------- main
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--write", action="store_true", help="replace placeholders in the target files (default: dry run)")
    ap.add_argument("--compute", action="store_true", help="compute the confirmatory JSON in memory if it is missing")
    ap.add_argument("--confirmatory-json", default=None, help=f"default {CONF_JSON.relative_to(REPO)}")
    ap.add_argument("--results-root", default=None, help="where run dirs live (default gym/results)")
    ap.add_argument("--video-url", default=None)
    ap.add_argument("--files", nargs="*", default=TARGETS)
    a = ap.parse_args(argv)
    os.chdir(REPO)   # the plan's reader preds paths are relative to the repo root

    vals, why = build_values(a)
    found: dict[str, list[str]] = {}
    texts = {}
    for f in a.files:
        t = (REPO / f).read_text()
        texts[f] = t
        for m in PH.finditer(t):
            found.setdefault(m.group(1), [])
            if f not in found[m.group(1)]:
                found[m.group(1)].append(f)

    missing = []
    print(f"{'placeholder':<20} {'status':<8} value / reason")
    for name in sorted(found):
        where = ", ".join(found[name])
        if name in vals:
            v = vals[name].replace("\n", " ⏎ ")
            print(f"{name:<20} {'FILL':<8} {v[:110]}{'…' if len(v) > 110 else ''}   [{where}]")
        else:
            missing.append(name)
            print(f"{name:<20} {'MISSING':<8} {why.get(name, 'no source for this placeholder')}   [{where}]")
    print(f"\n{len(found) - len(missing)} of {len(found)} placeholders have a value; {len(missing)} missing.")

    if a.write:
        for f, t in texts.items():
            new = PH.sub(lambda m: vals.get(m.group(1), m.group(0)), t)
            if new != t:
                (REPO / f).write_text(new)
                print(f"wrote {f}")
    else:
        print("dry run: nothing written (use --write).")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
