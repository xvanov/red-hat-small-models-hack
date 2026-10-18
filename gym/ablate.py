"""One-factor-at-a-time ablations on the held-out split.

    python gym/ablate.py                         # baseline + every factor, local runner
    python gym/ablate.py --factors tools,verifier --stub
    python gym/ablate.py --baseline-from results/baseline   # reuse an existing baseline run

Tasks and the scorer are fixed. The baseline is RunConfig() (prompt v1, verbose tool descriptions,
verifier on, reader on). Each variant flips exactly one knob, so each delta is that knob's effect
alone. Writes results/<prefix><factor>/ per run and results/ablations.md with the delta table.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import run_eval  # noqa: E402

PROMPTS = HERE.parent / "operator" / "prompts"

# factor -> (description, CLI-arg overrides applied on top of the baseline args)
FACTORS = {
    "prompt": ("system prompt v1 -> {alt}", lambda a, alt: setattr(a, "prompt", alt)),
    "tools": ("tool descriptions verbose -> terse", lambda a, _: setattr(a, "tools", "terse")),
    "verifier": ("deterministic verifier on -> off", lambda a, _: setattr(a, "no_verifier", True)),
    "reader": ("reader (read_reply + rules) on -> off", lambda a, _: setattr(a, "no_reader", True)),
    "reasoning": ("reasoning default -> off", lambda a, _: setattr(a, "reasoning", "off")),
}


# P2.1 named variants: RunConfig overrides on top of RunConfig() + the reader backend, pinned per run.
# reader_backend "fallback" = rule-based read_reply (what the committed baselines used), "model" = the
# fine-tuned reader at $READER_BASE_URL. Tasks and scorer are untouched by every variant.
VARIANTS = {
    "base": {},
    "guard": {"renter_guard": True},                                   # (a) harness: renter turn ends with send_message
    "prompt2": {"prompt_version": "v2"},                               # (b) system prompt v2, workflow per scenario
    "prompt3": {"prompt_version": "v3"},                               # (b2) v2 + vendor-id/zip, exact address, ask-as-question
    "tools2": {"tool_descriptions": "v2"},                             # (c) tool-description variant
    "rhist": {"keep_reasoning_in_history": True},                      # (g) reasoning kept in history, like NeMo's
    "facts": {"format_facts": True},                                   # (g) prompt facts formatted like the NeMo rows
    "think_off": {"reasoning": False},                                 # (e) reasoning off
    "style": {"style_precheck": True},                                 # (d) verifier style pre-check on send_message
    "noverif": {"verifier": False},                                    # verifier off
    "noreader": {"reader": False},                                     # (f) reader out of the loop
    "readermodel": {"_reader_backend": "model"},                       # (f) fine-tuned reader instead of fallback
    "router": {"router": True},                                        # triage router: reader reads every inbound first
}


def variant_config(a, spec: str):
    """spec = 'guard+prompt2' -> (cfg, reader_backend). Later parts override earlier ones."""
    over = {}
    for part in spec.split("+"):
        over.update(VARIANTS[part])
    backend = over.pop("_reader_backend", "fallback")
    return run_eval.make_config(a).with_(**over), backend


def never_reached_model(r: dict) -> bool:
    """Protocol 4.4: a rollout is rerun only if it returned zero model completions and failed on infrastructure."""
    failed = r.get("status") in ("model_error", "missing") or bool(r.get("error"))
    return failed and not (r.get("model_calls") or 0) and not (r.get("steps") or 0)


def run_variant(a, spec: str, run_name: str, reader_url: str | None) -> dict:
    import os
    cfg, backend = variant_config(a, spec)
    models = run_eval.probe_models(cfg.base_url, cfg.api_key) or []
    if not a.model and models and cfg.model not in models:
        cfg = cfg.with_(model=models[0])   # same resolution evaluate() does
    if backend == "model" and not reader_url:
        raise SystemExit("variant wants the model reader but READER_BASE_URL is not set in .env")
    os.environ["READER_BASE_URL"] = reader_url if backend == "model" else ""   # "" = rule-based fallback
    va = argparse.Namespace(**vars(a))
    va.run_name = run_name
    d = run_eval.RESULTS / run_name
    if a.retry_only and (d / "summary.json").exists():
        s = json.loads((d / "summary.json").read_text())
    else:
        s = run_eval.evaluate(va, cfg)
    retried = list((s.get("model_error_retries") or {}).get("tasks_rerun", []))
    for _ in range(a.retry_errors):  # endpoint outages: rerun only the rollouts that never reached the model
        rows = [json.loads(l) for l in open(d / "per_task.jsonl")]
        bad = [r["task_id"] for r in rows if never_reached_model(r)]
        if not bad:
            break
        wait_endpoint(cfg)
        retried += bad
        vr = argparse.Namespace(**vars(va))
        vr.run_name, vr.ids, vr.limit = f"_retry-{run_name}", ",".join(bad), None
        run_eval.evaluate(vr, cfg)
        rd = run_eval.RESULTS / vr.run_name
        new = {json.loads(l)["task_id"]: json.loads(l) for l in open(rd / "per_task.jsonl")}
        with open(d / "per_task.attempts.jsonl", "a") as fa:   # replaced attempts are kept, never overwritten
            for r in rows:
                if r["task_id"] in new:
                    fa.write(json.dumps({**r, "replaced_by_retry": True}, ensure_ascii=False, default=str) + "\n")
        rows = [new.get(r["task_id"], r) for r in rows]
        with open(d / "per_task.jsonl", "w") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
        for t in (rd / "transcripts").glob("*.json") if (rd / "transcripts").exists() else []:
            (d / "transcripts").mkdir(exist_ok=True)
            t.replace(d / "transcripts" / t.name)
        import shutil
        shutil.rmtree(rd, ignore_errors=True)
        meta = {k: v for k, v in s.items() if k not in ("tasks", "pass_rate", "mean_reward", "by_category",
                                                        "check_pass_rate", "errors")}
        s = run_eval.summarize(rows, meta)
    final_rows = [json.loads(l) for l in open(d / "per_task.jsonl")]
    mid = [r["task_id"] for r in final_rows if r.get("error") and not never_reached_model(r)]
    s["model_error_retries"] = {"rule": "protocol 4.4: rerun only rollouts with zero model completions",
                                "tasks_rerun": retried,
                                "still_failed": [r["task_id"] for r in final_rows if never_reached_model(r)],
                                "mid_rollout_drops": mid,
                                "void": len(mid) > 0.10 * max(1, len(final_rows))}
    s["variant"] = {"spec": spec, "reader_backend": backend}
    (d / "summary.json").write_text(json.dumps(s, indent=1) + "\n")
    return s


def wait_endpoint(cfg, max_wait_s: int = 1800):
    """Block until the model endpoint generates again (vLLM restarts / tunnel drops happen)."""
    if getattr(cfg, "api", "openai") != "openai":
        return   # reference backend: the SDK already retries; nothing to wait for
    import time
    from openai import OpenAI
    t0 = time.time()
    while time.time() - t0 < max_wait_s:
        try:
            OpenAI(base_url=cfg.base_url, api_key=cfg.api_key, timeout=30, max_retries=0).chat.completions.create(
                model=cfg.model, messages=[{"role": "user", "content": "ping"}], max_tokens=1)
            return
        except Exception:  # noqa: BLE001
            time.sleep(20)
    raise SystemExit("model endpoint did not come back")


def alt_prompt(base: str) -> str | None:
    versions = sorted(p.stem.split("_", 1)[1] for p in PROMPTS.glob("system_*.md"))
    others = [v for v in versions if v != base]
    return others[-1] if others else None


def fmt_delta(x: float) -> str:
    return f"{x * 100:+.1f}"


def table(base: dict, rows: list[tuple[str, str, dict]]) -> str:
    cats = sorted(base["by_category"])
    checks = sorted(base["check_pass_rate"])
    head = ["Variant", "Change", "Pass rate", "Δ pass", "Mean reward", "Δ reward"] + [f"Δ {c}" for c in cats]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]

    def line(name, change, s):
        d = [s["pass_rate"] - base["pass_rate"], s["mean_reward"] - base["mean_reward"]]
        cd = [s["by_category"].get(c, {}).get("mean_reward", 0) - base["by_category"][c]["mean_reward"] for c in cats]
        return ("| " + " | ".join([name, change, f"{s['pass_rate'] * 100:.1f}%", fmt_delta(d[0]),
                                   f"{s['mean_reward']:.3f}", fmt_delta(d[1])] + [fmt_delta(x) for x in cd]) + " |")

    lines.append(line("baseline", base["config_label"], base))
    for name, change, s in rows:
        lines.append(line(name, change, s))
    out = "\n".join(lines)
    ck = ["| Variant | " + " | ".join(checks) + " |", "|" + "---|" * (len(checks) + 1)]
    ck.append("| baseline | " + " | ".join(f"{base['check_pass_rate'][c] * 100:.0f}%" for c in checks) + " |")
    for name, _, s in rows:
        ck.append(f"| {name} | " + " | ".join(
            f"{s['check_pass_rate'].get(c, 0) * 100:.0f}% ({fmt_delta(s['check_pass_rate'].get(c, 0) - base['check_pass_rate'][c])})"
            for c in checks) + " |")
    return out + "\n\nPer-check-type pass rate (Δ vs baseline, points):\n\n" + "\n".join(ck)


def main():
    ap = run_eval.build_parser()
    ap.set_defaults(run_name="baseline")
    ap.add_argument("--factors", default="prompt,tools,verifier,reader")
    ap.add_argument("--prefix", default="ablate-")
    ap.add_argument("--baseline-from", default=None, help="existing results dir to use as the baseline")
    ap.add_argument("--out", default=str(run_eval.RESULTS / "ablations.md"))
    ap.add_argument("--variants", default=None,
                    help="comma list of named variants, '+' combines, e.g. base,guard,guard+prompt2")
    ap.add_argument("--retry-errors", type=int, default=3, help="rerun model_error rollouts up to N times")
    ap.add_argument("--retry-only", action="store_true", help="only rerun model_error rollouts of existing runs")
    ap.add_argument("--seed-tag", default="", help="suffix for run names, e.g. -s2 for a repeat")
    a = ap.parse_args()
    if a.variants:
        import os
        run_eval.load_env_file()
        reader_url = os.environ.get("READER_BASE_URL") or None
        for spec in [x.strip() for x in a.variants.split(",") if x.strip()]:
            name = f"{a.prefix}{spec}{a.seed_tag}"
            s = run_variant(a, spec, name, reader_url)
            print(f"VARIANT {name}: pass {s['pass_rate']} reward {s['mean_reward']}", flush=True)
        return
    if a.split != "heldout":
        print("note: ablations are meant for the held-out split", file=sys.stderr)

    if a.baseline_from:
        base = json.loads((Path(a.baseline_from) / "summary.json").read_text())
    else:
        base = run_eval.evaluate(a)
    rows = []
    for f in [x.strip() for x in a.factors.split(",") if x.strip()]:
        desc, apply = FACTORS[f]
        alt = None
        if f == "prompt":
            alt = alt_prompt(a.prompt)
            if alt is None:
                print("skip prompt: only one system prompt exists", file=sys.stderr)
                continue
        va = argparse.Namespace(**vars(a))
        apply(va, alt)
        va.run_name = f"{a.prefix}{f}"
        rows.append((f, desc.format(alt=alt), run_eval.evaluate(va)))

    md = [f"# Ablations on the held-out split ({base['tasks']} tasks)", "",
          f"Runner: `{base['via']}`, model: `{base['model']}`{' (STUB, plumbing only, not a model score)' if base.get('stub') else ''}, "
          f"tools backend: `{base['tools_backend']}`, git `{base.get('git')}`.",
          "Tasks and scorer fixed; each row flips exactly one RunConfig knob from the baseline. "
          "Δ columns are percentage points vs the baseline.", "",
          table(base, rows), "",
          "Reproduce: `python gym/ablate.py " + ("--stub " if base.get("stub") else "") + f"--factors {a.factors}`."]
    Path(a.out).write_text("\n".join(md) + "\n")
    print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
