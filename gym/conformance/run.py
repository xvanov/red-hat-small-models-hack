"""Run the Messenger conformance suite for one operator config and print a per-item table.

    python gym/conformance/run.py --reference                       # privileged reference player (no model)
    python gym/conformance/run.py --variant guard+prompt3+style+rhist+readermodel --workers 8   # the final config
    python gym/conformance/run.py --variant base --items C14,C23 --workers 4
    python gym/conformance/run.py --reference --stages gate,scheduling

Item verdicts: PASS (every named check in every scenario that tests the item passed), FAIL, BLOCKED (a
feature the item needs is missing; see features.py). Writes gym/results/conformance/<config>/summary.json,
per_scenario.jsonl and transcripts/. Rebuild scenarios first if build.py changed: python gym/conformance/build.py
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
GYM = HERE.parent
REPO = GYM.parent
for p in (HERE, GYM, REPO / "tools", REPO / "operator"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import build  # noqa: E402
from engine import Play  # noqa: E402
from features import probe_all  # noqa: E402

TASKS = GYM / "tasks" / "messenger"
OUT = GYM / "results" / "conformance"


def load_scenarios() -> dict[str, dict]:
    out = {}
    for f in sorted(TASKS.glob("*.jsonl")):
        for line in open(f):
            t = json.loads(line)
            out[t["id"]] = t
    return out


def is_model_error(r: dict) -> bool:
    err = (r.get("error") or "") + " " + " ".join(str((m or {}).get("status")) for m in [])
    return any(k in err for k in ("APIConnectionError", "APITimeoutError", "InternalServerError", "ServiceUnavailable",
                                  "Connection refused", "RemoteProtocolError", "cannot generate"))


def run_one(task: dict, mode: str, cfg, run_dir: Path) -> dict:
    client = None
    if mode == "operator" and task.get("kind") != "tool_probe":
        from rentus_operator.loop import make_client
        client = make_client(cfg, timeout=180, max_retries=1)
    r = Play(json.loads(json.dumps(task))).play("reference" if mode == "reference" else "operator", cfg, client)
    for ph in r["_transcript"].get("operator") or []:
        if ph.get("status") in ("model_error", "error") and not r.get("error"):
            r["error"] = f"operator phase {ph['phase']} status {ph['status']}: {(ph.get('final_text') or '')[:200]}"
    (run_dir / "transcripts").mkdir(parents=True, exist_ok=True)
    (run_dir / "transcripts" / f"{task['id']}.json").write_text(json.dumps(r.pop("_transcript"), default=str,
                                                                           ensure_ascii=False, indent=1))
    return r


def item_verdicts(items, results: dict[str, dict], feats: dict) -> list[dict]:
    rows = []
    for it in items:
        missing = [f for f in it["requires"] if not feats.get(f, {}).get("ok")]
        if missing:
            rows.append({**it, "verdict": "BLOCKED", "detail": "blocked: needs " + "; ".join(feats[f]["need"] for f in missing)})
            continue
        fails, ran = [], True
        for t in it["tests"]:
            r = results.get(t["scenario"])
            if r is None:
                ran = False
                continue
            by = {c["name"]: c for c in r["checks"]}
            for name in t["checks"]:
                c = by.get(name)
                if c is None or not c["pass"]:
                    fails.append(f"{t['scenario']}:{name} ({c['detail'] if c else 'missing'})")
            pre = by.get("precondition")
            if pre and not pre["pass"]:
                fails.append(f"{t['scenario']}: {pre['detail']}")
            if r.get("error"):
                fails.append(f"{t['scenario']}: {r['error'][:160]}")
        if not ran:
            rows.append({**it, "verdict": "SKIPPED", "detail": "not selected"})
        else:
            rows.append({**it, "verdict": "PASS" if not fails else "FAIL", "detail": "; ".join(fails)[:600]})
    return rows


def print_table(rows, stage_summary):
    print(f"\n{'item':5s} {'stage':15s} {'verdict':8s} detail")
    for r in rows:
        if r["verdict"] == "SKIPPED":
            continue
        d = r["detail"] if r["verdict"] != "PASS" else ""
        print(f"{r['id']:5s} {r['stage']:15s} {r['verdict']:8s} {d[:150]}")
    print(f"\n{'stage':28s} pass fail blocked")
    for st, s in stage_summary.items():
        print(f"{build.STAGES.get(st, st):28s} {s['PASS']:4d} {s['FAIL']:4d} {s['BLOCKED']:7d}")


def git_head() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=REPO, text=True).strip()
    except Exception:  # noqa: BLE001
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--reference", action="store_true", help="privileged reference player instead of a model")
    ap.add_argument("--variant", default="guard+prompt3+style+rhist+readermodel",
                    help="gym/ablate.py VARIANTS spec (default: the final config in docs/results.md)")
    ap.add_argument("--name", default=None, help="results folder name (default: reference or the variant)")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--items", default=None, help="comma-separated item ids, e.g. C14,C23")
    ap.add_argument("--stages", default=None)
    ap.add_argument("--retry-errors", type=int, default=2, help="rerun scenarios that never reached the model")
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                    help="extra RunConfig override on top of the variant, e.g. --set prompt_version=v4 --set tool_descriptions=concierge")
    ap.add_argument("--base-url", default=None)
    ap.add_argument("--model", default=None)
    a = ap.parse_args()
    if a.workers > 8:
        raise SystemExit("keep model concurrency at 8 or less (docs/PARALLEL.md)")

    items = build.checklist()
    if a.items:
        want = set(a.items.split(","))
        items = [i for i in items if i["id"] in want]
    if a.stages:
        want = set(a.stages.split(","))
        items = [i for i in items if i["stage"] in want]
    feats = probe_all()
    scen = load_scenarios()
    needed = []
    for it in items:
        if any(not feats.get(f, {}).get("ok") for f in it["requires"]):
            continue
        for t in it["tests"]:
            if t["scenario"] not in needed:
                needed.append(t["scenario"])
    tasks = [scen[s] for s in needed]

    cfg, mode, cfg_d = None, "reference", None
    if not a.reference:
        import ablate
        import run_eval
        run_eval.load_env_file()
        pa = run_eval.build_parser().parse_args(["--run-name", "_conformance"])
        if a.base_url:
            pa.base_url = a.base_url
        if a.model:
            pa.model = a.model
        cfg, backend = ablate.variant_config(pa, a.variant)
        for kv in a.set:
            k, v = kv.split("=", 1)
            v = {"true": True, "false": False}.get(v.lower(), v)
            if isinstance(v, str) and v.replace(".", "", 1).isdigit():
                v = float(v) if "." in v else int(v)
            cfg = cfg.with_(**{k: v})
        models = run_eval.probe_models(cfg.base_url, cfg.api_key) or []
        if not a.model and models and cfg.model not in models:
            cfg = cfg.with_(model=models[0])
        reader_url = os.environ.get("READER_BASE_URL", "")
        if backend == "model" and not reader_url:
            raise SystemExit("variant wants the model reader but READER_BASE_URL is not set in .env")
        os.environ["READER_BASE_URL"] = reader_url if backend == "model" else ""
        ablate.wait_endpoint(cfg, max_wait_s=600)
        mode = "operator"
        cfg_d = {k: v for k, v in asdict(cfg).items() if k != "api_key"}
    name = a.name or ("reference" if a.reference else a.variant)
    run_dir = OUT / name
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True)

    t0 = time.time()
    print(f"conformance: {len(items)} items, {len(tasks)} scenarios, mode={mode}" + (f", config={cfg.label()}" if cfg else ""), flush=True)
    results: dict[str, dict] = {}

    def go(t):
        r = run_one(t, mode, cfg, run_dir)
        print(f"  {t['id']:28s} {'pass' if r['pass'] else 'FAIL'} {r['checks_passed']}/{r['checks_total']} {r['seconds']:.0f}s"
              + (f"  error: {r['error'][:80]}" if r.get("error") else ""), flush=True)
        return r

    with ThreadPoolExecutor(max_workers=1 if mode == "reference" else a.workers) as ex:
        for r in ex.map(go, tasks):
            results[r["scenario"]] = r
    for attempt in range(a.retry_errors if mode == "operator" else 0):
        bad = [s for s, r in results.items() if r.get("error") and is_model_error(r)]
        if not bad:
            break
        print(f"retry {attempt + 1}: {len(bad)} scenarios hit endpoint errors: {bad}")
        import ablate
        ablate.wait_endpoint(cfg, max_wait_s=1200)
        with ThreadPoolExecutor(max_workers=a.workers) as ex:
            for r in ex.map(go, [scen[s] for s in bad]):
                r["retried"] = True
                results[r["scenario"]] = r

    rows = item_verdicts(items, results, feats)
    stage_summary: dict[str, dict] = defaultdict(lambda: {"PASS": 0, "FAIL": 0, "BLOCKED": 0, "SKIPPED": 0})
    for r in rows:
        stage_summary[r["stage"]][r["verdict"]] += 1
    stage_summary = {st: stage_summary[st] for st in build.STAGES if st in stage_summary}
    print_table(rows, stage_summary)
    n = defaultdict(int)
    for r in rows:
        n[r["verdict"]] += 1
    testable = n["PASS"] + n["FAIL"]
    print(f"\nitems: {len(rows)}  testable {testable}  PASS {n['PASS']}  FAIL {n['FAIL']}  BLOCKED {n['BLOCKED']}"
          + (f"  ({n['PASS'] / testable:.0%} of testable)" if testable else ""))

    with open(run_dir / "per_scenario.jsonl", "w") as f:
        for s in needed:
            f.write(json.dumps(results[s], ensure_ascii=False, default=str) + "\n")
    summary = {"name": name, "mode": mode, "variant": None if a.reference else a.variant, "overrides": a.set,
               "config_label": cfg.label() if cfg else "reference player (privileged, not a model)", "config": cfg_d,
               "model": cfg.model if cfg else None, "base_url_set": bool(cfg and cfg.base_url),
               "git": git_head(), "started": datetime.fromtimestamp(t0, timezone.utc).isoformat(timespec="seconds"),
               "seconds": round(time.time() - t0, 1),
               "items_total": len(rows), "testable": testable, "pass": n["PASS"], "fail": n["FAIL"], "blocked": n["BLOCKED"],
               "pass_rate_of_testable": round(n["PASS"] / testable, 4) if testable else None,
               "by_stage": stage_summary, "features": feats,
               "scenarios": {"run": len(tasks), "passed": sum(1 for r in results.values() if r["pass"]),
                             "errors": [s for s, r in results.items() if r.get("error")],
                             "retried": [s for s, r in results.items() if r.get("retried")]},
               "items": [{k: r[k] for k in ("id", "stage", "text", "source", "requires", "verdict", "detail")} for r in rows]}
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False) + "\n")
    print(f"wrote {run_dir / 'summary.json'}")


if __name__ == "__main__":
    main()
