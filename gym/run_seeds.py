"""Run one config K times (seeded repeats) and report the statistics from gym/stats.py.

    # K=3 seeded repeats of the final config on held-out v1, then the stats table
    python gym/run_seeds.py --variant guard+prompt3+style+rhist --split heldout --seeds 1,2,3 --prefix seeds-final
    # model-played renters (tasks with counterpart mode llm_renter), one run
    python gym/run_seeds.py --variant guard+prompt3+style+rhist --tasks-file gym/tasks/llm_renter/demo_train.jsonl \
        --seeds 1 --prefix llm-demo --workers 6
    # analysis only (no model calls) over runs that already exist
    python gym/run_seeds.py --prefix seeds-final --seeds 1,2,3 --analyze-only [--compare-to base=baseline,heldout-base]

Each repeat is a normal run dir, results/<prefix>-s<seed>/, written by ablate.run_variant (same retry rule
for endpoint outages as every committed run). The operator seed is sent as the OpenAI `seed` field on
every model call (run_eval.SeededClient), at the config's temperature (0.2 by default; --temperature to
change). For llm_renter tasks, --sim-seed overrides the simulator seed in every renter spec (default: keep
the task's own seed, so only the operator varies between repeats); --sim-seed-follow ties it to the
operator seed instead. A report (markdown) goes to results/<prefix>-report.md.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import ablate  # noqa: E402
import run_eval  # noqa: E402
import stats  # noqa: E402


def tasks_with_sim_seed(tasks_file: str | None, args, seed: int) -> str | None:
    """A temp copy of the tasks file with the simulator seed / endpoint overridden (source file untouched)."""
    if not tasks_file or (args.sim_seed is None and not args.sim_seed_follow and not args.sim_model and not args.sim_base_url):
        return tasks_file
    sim_seed = seed if args.sim_seed_follow else args.sim_seed
    out = Path(tempfile.mkstemp(prefix="rentus-tasks-", suffix=".jsonl")[1])
    with open(out, "w") as f:
        for line in open(tasks_file):
            t = json.loads(line)
            for cp in t.get("counterparts") or []:
                if cp.get("mode") == "llm_renter":
                    sim = cp.setdefault("simulator", {})
                    if sim_seed is not None:
                        sim["seed"] = sim_seed
                    if args.sim_model:
                        sim["model"] = args.sim_model
                    if args.sim_base_url:
                        sim["base_url"] = args.sim_base_url
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    return str(out)


def main():
    ap = run_eval.build_parser()
    ap.set_defaults(run_name="_", workers=4)
    for act in ap._actions:   # run names come from --prefix and --seeds here
        if act.dest == "run_name":
            act.required = False
    ap.add_argument("--variant", default="guard+prompt3+style+rhist", help="ablate.VARIANTS spec, '+' combines")
    ap.add_argument("--seeds", default="1,2,3", help="comma list of operator seeds (one run each)")
    ap.add_argument("--prefix", required=True, help="run dirs are results/<prefix>-s<seed>")
    ap.add_argument("--retry-errors", type=int, default=3)
    ap.add_argument("--retry-only", action="store_true")
    ap.add_argument("--analyze-only", action="store_true", help="no model calls: just the stats over existing runs")
    ap.add_argument("--compare-to", action="append", default=[], help="label=run1,run2 for a paired comparison")
    ap.add_argument("--sim-seed", type=int, default=None, help="llm_renter: force this simulator seed")
    ap.add_argument("--sim-seed-follow", action="store_true", help="llm_renter: simulator seed = operator seed")
    ap.add_argument("--sim-model", default=None, help="llm_renter: simulator model (default: endpoint's first)")
    ap.add_argument("--sim-base-url", default=None, help="llm_renter: simulator endpoint (default: local Lightning)")
    ap.add_argument("--print-run-names", action="store_true",
                    help="print the run names these flags would write, one per line, and exit (no model calls)")
    a = ap.parse_args()
    seeds = [int(s) for s in a.seeds.split(",") if s.strip()]
    runs = [f"{a.prefix}-s{s}" for s in seeds]
    if a.print_run_names:
        print("\n".join(runs))
        return
    if not a.analyze_only:
        run_eval.load_env_file()
        import os
        reader_url = os.environ.get("READER_BASE_URL") or None
        for seed, name in zip(seeds, runs):
            va = argparse.Namespace(**vars(a))
            va.seed = seed
            va.tasks_file = tasks_with_sim_seed(a.tasks_file, a, seed)
            s = ablate.run_variant(va, a.variant, name, reader_url)
            print(f"SEED {seed} -> {name}: pass {s['pass_rate']} reward {s['mean_reward']}", flush=True)
    label = a.prefix
    argv = ["--md", "--categories", "--matrix", "--config", f"{label}={','.join(runs)}"]
    for spec in a.compare_to:
        argv += ["--config", spec, "--compare", f"{label}:{spec.split('=', 1)[0]}"]
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        stats.main(argv)
    report = (f"# {a.prefix}: {len(runs)} run(s) of `{a.variant}`\n\n"
              f"Runs: {', '.join(f'`{r}`' for r in runs)}. Reproduce the table: "
              f"`python gym/stats.py {' '.join(argv)}`\n\n" + buf.getvalue())
    out = run_eval.RESULTS / f"{a.prefix}-report.md"
    out.write_text(report)
    print(report)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
