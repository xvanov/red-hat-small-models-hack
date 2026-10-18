"""Statistics over repeated Gym runs: confidence intervals, pass^k / pass@k, paired tests.

A *config* is one or more runs of the same RunConfig on the same task split (repeats with different
seeds, or plain re-runs at temperature > 0). Each run is a results dir with `per_task.jsonl`.

    # one config, several runs
    python gym/stats.py --config final=heldout-guard+prompt3+style+rhist,heldout-guard+prompt3+style+rhist-s2
    # several configs + paired comparisons, markdown for docs/
    python gym/stats.py --config base=baseline,heldout-base --config final=... --compare final:base --md
    # per-task pass matrix (rows = tasks, columns = runs)
    python gym/stats.py --config final=... --matrix

What is reported, and the unit of resampling (tasks are the independent unit; repeats only reduce
the within-task sampling noise, so every interval and test resamples or counts TASKS):
  pass rate      mean over tasks of the task's pass fraction across runs; 95% Wilson interval with
                 n = number of tasks (a deliberately conservative choice: k repeats of the same 31 tasks
                 are not 31*k independent draws).
  mean reward    mean over tasks of the task's mean reward across runs; 95% percentile bootstrap over
                 tasks (10,000 resamples, fixed seed).
  pass^k         tau-bench convention: the probability that a task passes in ALL of k independent runs,
                 estimated without bias per task as C(c,k)/C(n,k) (c passes in n runs), averaged over
                 tasks. pass^1 = pass rate. Bootstrap CI over tasks.
  pass@k         probability that a task passes in AT LEAST ONE of k runs: 1 - C(n-c,k)/C(n,k).
  run-to-run sd  sample standard deviation of the per-run pass rate and mean reward (needs >= 2 runs).
  paired A vs B  on the tasks both configs ran: per-task difference of mean reward, paired bootstrap over
                 tasks (CI and a two-sided p-value from the centred bootstrap distribution); for pass/fail,
                 an exact two-sided sign test on tasks whose pass fraction differs. With one run per
                 config this IS the exact McNemar test (b = A-only passes, c = B-only passes).
                 Holm-adjusted p-values across all comparisons in one invocation are also shown.
Pure Python (no numpy), deterministic for a given --seed.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
Z95 = 1.959963984540054
N_BOOT = 10_000


# ------------------------------------------------------------------------------------- loading
def resolve_run(name: str) -> Path:
    p = Path(name)
    for cand in (p, RESULTS / name):
        if (cand / "per_task.jsonl").exists():
            return cand
    raise SystemExit(f"no per_task.jsonl for run {name!r} (looked in {p} and {RESULTS / name})")


def load_run(name: str) -> dict[str, dict]:
    d = resolve_run(name)
    rows = [json.loads(l) for l in open(d / "per_task.jsonl") if l.strip()]
    return {r["task_id"]: r for r in rows}


@dataclass
class Config:
    """K runs of one config. `tasks` = task ids present in every run (in first-run order)."""
    label: str
    runs: list[str]
    data: list[dict[str, dict]] = field(default_factory=list)

    def __post_init__(self):
        if not self.data:
            self.data = [load_run(r) for r in self.runs]
        first = list(self.data[0])
        common = set(first).intersection(*[set(d) for d in self.data[1:]]) if len(self.data) > 1 else set(first)
        self.tasks = [t for t in first if t in common]
        dropped = set().union(*[set(d) for d in self.data]) - common
        if dropped:
            print(f"[{self.label}] {len(dropped)} task(s) not in every run, ignored: {sorted(dropped)[:5]}...",
                  file=sys.stderr)
        self.category = {t: self.data[0][t].get("category") or "?" for t in self.tasks}

    @property
    def k(self) -> int:
        return len(self.data)

    def passes(self, t: str) -> list[int]:
        return [int(bool(d[t]["pass"])) for d in self.data]

    def rewards(self, t: str) -> list[float]:
        return [float(d[t]["reward"]) for d in self.data]

    def pass_matrix(self) -> dict[str, list[int]]:
        return {t: self.passes(t) for t in self.tasks}


def parse_config(spec: str) -> Config:
    if "=" in spec:
        label, runs = spec.split("=", 1)
    else:
        label, runs = spec.split(",")[0], spec
    return Config(label.strip(), [r.strip() for r in runs.split(",") if r.strip()])


# ----------------------------------------------------------------------------------- estimators
def wilson(p_hat: float, n: int, z: float = Z95) -> tuple[float, float]:
    """Wilson score interval. p_hat may be fractional (mean of per-task pass fractions)."""
    if n == 0:
        return (0.0, 1.0)
    den = 1 + z * z / n
    centre = (p_hat + z * z / (2 * n)) / den
    half = z * math.sqrt(p_hat * (1 - p_hat) / n + z * z / (4 * n * n)) / den
    return (max(0.0, centre - half), min(1.0, centre + half))


def bootstrap_ci(values: list[float], stat=statistics.fmean, n_boot: int = N_BOOT, seed: int = 0,
                 alpha: float = 0.05) -> tuple[float, float]:
    if not values:
        return (float("nan"), float("nan"))
    rng = random.Random(seed)
    n = len(values)
    bs = sorted(stat([values[rng.randrange(n)] for _ in range(n)]) for _ in range(n_boot))
    return (bs[int(alpha / 2 * n_boot)], bs[min(n_boot - 1, int((1 - alpha / 2) * n_boot))])


def pass_hat_k(c: int, n: int, k: int) -> float:
    """tau-bench pass^k for one task: P(all k of k fresh runs pass), unbiased from c of n."""
    return math.comb(c, k) / math.comb(n, k) if k <= n else float("nan")


def pass_at_k(c: int, n: int, k: int) -> float:
    """P(at least one of k runs passes), unbiased from c of n (Chen et al. 2021)."""
    if k > n:
        return float("nan")
    return 1.0 - math.comb(n - c, k) / math.comb(n, k)


def binom_two_sided(b: int, c: int) -> float:
    """Exact two-sided sign test / McNemar: P(|X - n/2| >= |b - n/2|), X ~ Bin(b+c, 1/2)."""
    n = b + c
    if n == 0:
        return 1.0
    lo = min(b, c)
    p = sum(math.comb(n, i) for i in range(lo + 1)) / 2 ** n
    return min(1.0, 2 * p)


def holm(pvals: list[float]) -> list[float]:
    m = len(pvals)
    order = sorted(range(m), key=lambda i: pvals[i])
    adj, running = [0.0] * m, 0.0
    for rank, i in enumerate(order):
        running = max(running, (m - rank) * pvals[i])
        adj[i] = min(1.0, running)
    return adj


# ------------------------------------------------------------------------------------- analyses
def summarize(cfg: Config, tasks: list[str] | None = None, seed: int = 0) -> dict:
    tasks = tasks if tasks is not None else cfg.tasks
    n, k = len(tasks), cfg.k
    pf = [statistics.fmean(cfg.passes(t)) for t in tasks]          # per-task pass fraction
    rw = [statistics.fmean(cfg.rewards(t)) for t in tasks]         # per-task mean reward
    p = statistics.fmean(pf) if pf else 0.0
    out = {"label": cfg.label, "runs": cfg.runs, "k": k, "tasks": n,
           "pass_rate": p, "pass_ci": wilson(p, n), "passes_mean": p * n,
           "mean_reward": statistics.fmean(rw) if rw else 0.0, "reward_ci": bootstrap_ci(rw, seed=seed)}
    out["pass_hat"], out["pass_at"] = {}, {}
    for kk in range(1, k + 1):
        per = [pass_hat_k(sum(cfg.passes(t)), k, kk) for t in tasks]
        out["pass_hat"][kk] = (statistics.fmean(per), bootstrap_ci(per, seed=seed + kk))
        out["pass_at"][kk] = statistics.fmean(pass_at_k(sum(cfg.passes(t)), k, kk) for t in tasks)
    if k >= 2:
        per_run_p = [statistics.fmean(int(bool(d[t]["pass"])) for t in tasks) for d in cfg.data]
        per_run_r = [statistics.fmean(float(d[t]["reward"]) for t in tasks) for d in cfg.data]
        out["run_pass_rates"], out["run_rewards"] = per_run_p, per_run_r
        out["run_sd_pass"], out["run_sd_reward"] = statistics.stdev(per_run_p), statistics.stdev(per_run_r)
        out["flaky_tasks"] = sum(1 for t in tasks if 0 < sum(cfg.passes(t)) < k)
    return out


def by_category(cfg: Config, seed: int = 0) -> dict[str, dict]:
    cats = defaultdict(list)
    for t in cfg.tasks:
        cats[cfg.category[t]].append(t)
    return {c: summarize(cfg, ts, seed) for c, ts in sorted(cats.items())}


def compare(a: Config, b: Config, seed: int = 0, n_boot: int = N_BOOT) -> dict:
    """Paired comparison of A vs B on the tasks both ran."""
    common = [t for t in a.tasks if t in set(b.tasks)]
    d = [statistics.fmean(a.rewards(t)) - statistics.fmean(b.rewards(t)) for t in common]
    pa = [statistics.fmean(a.passes(t)) for t in common]
    pb = [statistics.fmean(b.passes(t)) for t in common]
    n = len(common)
    obs = statistics.fmean(d) if d else 0.0
    rng = random.Random(seed)
    boots = sorted(statistics.fmean([d[rng.randrange(n)] for _ in range(n)]) for _ in range(n_boot)) if n else [0.0]
    ci = (boots[int(0.025 * n_boot)], boots[min(n_boot - 1, int(0.975 * n_boot))]) if n else (0.0, 0.0)
    # centred bootstrap p-value: how often a resample under H0 (mean shifted to 0) is as extreme as observed
    p_boot = (sum(1 for x in boots if abs(x - obs) >= abs(obs) - 1e-12) + 1) / (len(boots) + 1) if n else 1.0
    b_only = sum(1 for x, y in zip(pa, pb) if x > y)
    c_only = sum(1 for x, y in zip(pa, pb) if x < y)
    return {"a": a.label, "b": b.label, "tasks": n, "ka": a.k, "kb": b.k,
            "d_reward": obs, "d_reward_ci": ci, "p_reward": min(1.0, p_boot),
            "d_pass": statistics.fmean(pa) - statistics.fmean(pb) if n else 0.0,
            "a_better": b_only, "b_better": c_only, "p_pass": binom_two_sided(b_only, c_only),
            "test_pass": "exact McNemar" if a.k == b.k == 1 else "exact sign test on per-task pass fraction"}


# --------------------------------------------------------------------------------------- output
def pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def ci_pct(ci) -> str:
    return f"{ci[0] * 100:.0f} to {ci[1] * 100:.0f}%"


def ci3(ci) -> str:
    return f"{ci[0]:.3f} to {ci[1]:.3f}"


def fmt_p(p: float) -> str:
    return "<0.001" if p < 0.001 else f"{p:.3f}"


def md_summary(rows: list[dict]) -> str:
    kmax = max(r["k"] for r in rows)
    head = ["config", "runs", "tasks", "pass rate (95% Wilson)", "mean reward (95% bootstrap)"]
    head += [f"pass^{k}" for k in range(2, kmax + 1)] + [f"pass@{k}" for k in range(2, kmax + 1)]
    head += ["run-to-run sd (pass / reward)", "tasks that flip"]
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for r in rows:
        cells = [f"`{r['label']}`", str(r["k"]), str(r["tasks"]),
                 f"{r['passes_mean']:.1f}/{r['tasks']} = {pct(r['pass_rate'])} ({ci_pct(r['pass_ci'])})",
                 f"{r['mean_reward']:.3f} ({ci3(r['reward_ci'])})"]
        cells += [f"{r['pass_hat'][k][0] * 100:.1f}%" if k in r["pass_hat"] else "" for k in range(2, kmax + 1)]
        cells += [f"{r['pass_at'][k] * 100:.1f}%" if k in r["pass_at"] else "" for k in range(2, kmax + 1)]
        cells.append(f"{r['run_sd_pass'] * 100:.1f} pts / {r['run_sd_reward']:.3f}" if "run_sd_pass" in r else "1 run")
        cells.append(str(r.get("flaky_tasks", "")) if "flaky_tasks" in r else "")
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out)


def md_categories(cfgs: list[Config], seed: int = 0) -> str:
    cats = sorted({c for cfg in cfgs for c in cfg.category.values()})
    head = ["config"] + [f"{c} ({sum(1 for v in cfgs[0].category.values() if v == c)})" for c in cats]
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for cfg in cfgs:
        bc = by_category(cfg, seed)
        cells = [f"`{cfg.label}`"]
        for c in cats:
            s = bc.get(c)
            cells.append("" if s is None else
                         f"pass {pct(s['pass_rate'])} ({ci_pct(s['pass_ci'])}); reward {s['mean_reward']:.3f} ({ci3(s['reward_ci'])})")
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out)


def md_compare(rows: list[dict]) -> str:
    adj_r = holm([r["p_reward"] for r in rows])
    adj_p = holm([r["p_pass"] for r in rows])
    head = ["A vs B", "runs (A/B)", "tasks", "Δ mean reward (95% paired bootstrap)", "p (reward)", "Holm p",
            "Δ pass rate", "tasks A better / B better", "p (pass, exact)", "Holm p"]
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for r, ar, ap in zip(rows, adj_r, adj_p):
        out.append("| " + " | ".join([
            f"`{r['a']}` vs `{r['b']}`", f"{r['ka']}/{r['kb']}", str(r["tasks"]),
            f"{r['d_reward']:+.3f} ({r['d_reward_ci'][0]:+.3f} to {r['d_reward_ci'][1]:+.3f})",
            fmt_p(r["p_reward"]), fmt_p(ar),
            f"{r['d_pass'] * 100:+.1f} pts", f"{r['a_better']} / {r['b_better']}", fmt_p(r["p_pass"]), fmt_p(ap)]) + " |")
    return "\n".join(out)


def md_matrix(cfg: Config) -> str:
    head = ["task", "category"] + [f"run {i + 1}" for i in range(cfg.k)] + ["mean reward"]
    out = [f"Pass matrix for `{cfg.label}` (1 = every check passed): " + ", ".join(f"run {i + 1} = `{r}`" for i, r in enumerate(cfg.runs)),
           "", "| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for t in cfg.tasks:
        out.append("| " + " | ".join([t, cfg.category[t]] + [str(x) for x in cfg.passes(t)]
                                      + [f"{statistics.fmean(cfg.rewards(t)):.3f}"]) + " |")
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", action="append", required=True,
                    help="label=run1,run2,... (run names under gym/results/ or paths); repeatable")
    ap.add_argument("--compare", action="append", default=[], help="A:B (config labels); repeatable")
    ap.add_argument("--categories", action="store_true", help="per-category table")
    ap.add_argument("--matrix", action="store_true", help="print each config's per-task pass matrix")
    ap.add_argument("--md", action="store_true", help="markdown tables (default: JSON)")
    ap.add_argument("--seed", type=int, default=0, help="bootstrap seed")
    a = ap.parse_args(argv)
    cfgs = [parse_config(s) for s in a.config]
    by = {c.label: c for c in cfgs}
    summ = [summarize(c, seed=a.seed) for c in cfgs]
    comps = []
    for spec in a.compare:
        x, y = spec.split(":")
        comps.append(compare(by[x], by[y], seed=a.seed))
    if not a.md:
        print(json.dumps({"summary": summ, "compare": comps,
                          "categories": {c.label: by_category(c, a.seed) for c in cfgs} if a.categories else None,
                          "matrix": {c.label: c.pass_matrix() for c in cfgs} if a.matrix else None},
                         indent=1, default=lambda o: list(o) if isinstance(o, tuple) else str(o)))
        return
    print(md_summary(summ))
    if a.categories:
        print("\nPer category (pass rate with 95% Wilson, mean reward with 95% bootstrap; n = tasks in the category):\n")
        print(md_categories(cfgs, a.seed))
    if comps:
        print("\nPaired comparisons (same tasks; resampling unit = task):\n")
        print(md_compare(comps))
    if a.matrix:
        for c in cfgs:
            print("\n" + md_matrix(c))


if __name__ == "__main__":
    main()
