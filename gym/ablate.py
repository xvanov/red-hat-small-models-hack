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
    a = ap.parse_args()
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
