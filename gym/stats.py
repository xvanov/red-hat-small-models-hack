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
Confirmatory analysis (protocol Amendment 1, docs/eval-protocol.md): every confirmatory hypothesis is a
ONE-SIDED test at familywise alpha = 0.025 (Holm over a family fixed in gym/confirmatory_v3.json):
  superiority / non-inferiority on mean reward   H0: true paired mean difference <= -margin (margin 0 for
                 superiority, delta for non-inferiority). p = max(bootstrap p, paired-t p), the more
                 conservative of the two (the bootstrap undercovers on skewed differences at n ~ 40).
                 bootstrap p = (#{boot mean <= -margin} + 1) / (B + 1)   (percentile test inversion).
  fewer calls    H0: paired mean difference of model_calls >= 0; same machinery with the sign flipped.
  reader         paired CLUSTER bootstrap over threads (resample threads, recompute the exact-match
                 difference); row-level exact McNemar is printed as a sensitivity column only.
  untested       a hypothesis whose inputs are missing stays in the family with p = 1.
  kappa          Cohen's kappa with a bootstrap CI over transcripts, on a simple random sample.
  power          `--power` simulates the decision rules above with this file's own code.
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


STRICT = False   # --strict: a task missing from any run is an error, not a warning (protocol finding stats-11)


class MissingTasks(SystemExit):
    pass


@dataclass
class Config:
    """K runs of one config. `tasks` = task ids present in every run (in first-run order)."""
    label: str
    runs: list[str]
    data: list[dict[str, dict]] = field(default_factory=list)
    strict: bool | None = None

    def __post_init__(self):
        if not self.data:
            self.data = [load_run(r) for r in self.runs]
        first = list(self.data[0])
        common = set(first).intersection(*[set(d) for d in self.data[1:]]) if len(self.data) > 1 else set(first)
        self.tasks = [t for t in first if t in common]
        dropped = set().union(*[set(d) for d in self.data]) - common
        if dropped and (self.strict if self.strict is not None else STRICT):
            raise MissingTasks(f"[{self.label}] --strict: {len(dropped)} task(s) missing from some run: {sorted(dropped)[:5]}")
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

    def metric(self, t: str, name: str) -> list[float]:
        out = []
        for d in self.data:
            v = d[t].get(name)
            if v is None:
                raise SystemExit(f"[{self.label}] task {t} has no {name!r} in per_task.jsonl")
            out.append(float(v))
        return out

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


def compare(a: Config, b: Config, seed: int = 0, n_boot: int = N_BOOT, delta: float | None = None) -> dict:
    """Paired comparison of A vs B on the tasks both ran. With `delta`, also the one-sided non-inferiority
    test of Amendment 1 (`ni`: p, bootstrap and paired-t lower bounds at alpha = 0.025)."""
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
    extra = {"ni": one_sided_test(d, delta, n_boot=n_boot, seed=seed)} if delta is not None and n >= 2 else {}
    return {**extra, "a": a.label, "b": b.label, "tasks": n, "ka": a.k, "kb": b.k,
            "d_reward": obs, "d_reward_ci": ci, "p_reward": min(1.0, p_boot),
            "d_pass": statistics.fmean(pa) - statistics.fmean(pb) if n else 0.0,
            "a_better": b_only, "b_better": c_only, "p_pass": binom_two_sided(b_only, c_only),
            "test_pass": "exact McNemar" if a.k == b.k == 1 else "exact sign test on per-task pass fraction (not McNemar)"}


# ---------------------------------------------------------------- confirmatory tests (Amendment 1)
ALPHA_FW = 0.025   # familywise, one-sided (the two-sided 0.05 convention, stated as one-sided tests)
DELTA = 0.05       # non-inferiority margin on mean reward, fixed in Amendment 1 before any v3 run


def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the regularized incomplete beta (Numerical Recipes, Lentz)."""
    tiny, qab, qap, qam = 1e-300, a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 300):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c if abs(1.0 + aa / c) > tiny else tiny
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c if abs(1.0 + aa / c) > tiny else tiny
        de = d * c
        h *= de
        if abs(de - 1.0) < 1e-12:
            break
    return h


def betainc(a: float, b: float, x: float) -> float:
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    lbt = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x)
    if x < (a + 1) / (a + b + 2):
        return math.exp(lbt) * _betacf(a, b, x) / a
    return 1.0 - math.exp(lbt) * _betacf(b, a, 1 - x) / b


def t_cdf(t: float, df: float) -> float:
    x = df / (df + t * t)
    tail = 0.5 * betainc(df / 2, 0.5, x)
    return 1.0 - tail if t > 0 else tail


def t_ppf(p: float, df: float) -> float:
    lo, hi = -1e3, 1e3
    for _ in range(200):
        mid = (lo + hi) / 2
        if t_cdf(mid, df) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def boot_means(values: list[float], n_boot: int = N_BOOT, seed: int = 0) -> list[float]:
    rng = random.Random(seed)
    n = len(values)
    return sorted(statistics.fmean([values[rng.randrange(n)] for _ in range(n)]) for _ in range(n_boot))


def one_sided_test(d: list[float], margin: float = 0.0, alpha: float = ALPHA_FW, n_boot: int = N_BOOT,
                   seed: int = 0, boots: list[float] | None = None) -> dict:
    """H0: true mean of d <= -margin  vs  H1: mean > -margin.

    margin = 0 is a one-sided superiority test; margin = delta is non-inferiority. The primary p is the
    LARGER of the percentile-bootstrap p and the paired-t p (pre-registered: if they disagree, the more
    conservative one decides). The matching (1 - alpha) lower confidence bounds are reported for both."""
    n = len(d)
    if n < 2:
        return {"n": n, "d": statistics.fmean(d) if d else 0.0, "p": 1.0, "p_boot": 1.0, "p_t": 1.0,
                "lb_boot": float("nan"), "lb_t": float("nan"), "margin": margin, "alpha": alpha}
    boots = boots if boots is not None else boot_means(d, n_boot, seed)
    B = len(boots)
    p_boot = (sum(1 for x in boots if x <= -margin) + 1) / (B + 1)
    m, sd = statistics.fmean(d), statistics.stdev(d)
    se = sd / math.sqrt(n)
    if se == 0:
        p_t = 0.0 if m > -margin else 1.0
        lb_t = m
    else:
        p_t = 1.0 - t_cdf((m + margin) / se, n - 1)
        lb_t = m - t_ppf(1 - alpha, n - 1) * se
    lb_boot = boots[max(0, min(B - 1, int(math.floor(alpha * B))))]
    p = max(p_boot, p_t)
    return {"n": n, "d": m, "sd": sd, "margin": margin, "alpha": alpha, "p": p, "p_boot": p_boot, "p_t": p_t,
            "lb_boot": lb_boot, "lb_t": lb_t, "lb": min(lb_boot, lb_t), "reject": p <= alpha}


def paired_diffs(a: "Config", b: "Config", metric: str = "reward") -> tuple[list[str], list[float]]:
    common = [t for t in a.tasks if t in set(b.tasks)]
    if metric == "reward":
        get = lambda c, t: statistics.fmean(c.rewards(t))
    elif metric == "pass":
        get = lambda c, t: statistics.fmean(c.passes(t))
    else:
        get = lambda c, t: statistics.fmean(c.metric(t, metric))
    return common, [get(a, t) - get(b, t) for t in common]


def noninferiority(a: "Config", b: "Config", delta: float = DELTA, metric: str = "reward",
                   alpha: float = ALPHA_FW, n_boot: int = N_BOOT, seed: int = 0) -> dict:
    """A is non-inferior to B by `delta` on `metric` (higher is better). delta = 0: A is superior."""
    tasks, d = paired_diffs(a, b, metric)
    return {"a": a.label, "b": b.label, "metric": metric, "tasks": len(tasks), "ka": a.k, "kb": b.k,
            **one_sided_test(d, delta, alpha, n_boot, seed)}


def fewer(a: "Config", b: "Config", metric: str = "model_calls", alpha: float = ALPHA_FW,
          n_boot: int = N_BOOT, seed: int = 0) -> dict:
    """A uses less of `metric` than B: H0 mean(A - B) >= 0. Tested as superiority on B - A."""
    tasks, d = paired_diffs(b, a, metric)
    r = one_sided_test(d, 0.0, alpha, n_boot, seed)
    return {"a": a.label, "b": b.label, "metric": metric, "tasks": len(tasks), **r,
            "d": -r["d"], "ub_boot": -r["lb_boot"], "ub_t": -r["lb_t"], "ub": -r.get("lb", float("nan"))}


# ---------------------------------------------------------------- reader: thread-clustered paired test
def load_reader_rows(path: str, field_name: str = "em_primary") -> dict[str, tuple[str, int]]:
    """id -> (cluster, correct) from a reader/eval.py preds file (rows carry `cluster` and `em_primary`)."""
    out = {}
    for line in open(path):
        if not line.strip():
            continue
        r = json.loads(line)
        if field_name not in r:
            raise SystemExit(f"{path}: row {r.get('id')} has no {field_name!r}; rescore it with the current reader/eval.py")
        out[r["id"]] = (str(r.get("cluster") or r["id"]), int(bool(r[field_name])))
    return out


def cluster_paired_test(rows: list[tuple[str, int, int]], alpha: float = ALPHA_FW, n_boot: int = N_BOOT,
                        seed: int = 0) -> dict:
    """rows = (cluster, a_correct, b_correct). H0: acc(A) - acc(B) <= 0. Resamples CLUSTERS (threads)."""
    by: dict[str, list[int]] = defaultdict(lambda: [0, 0])   # cluster -> [sum(a-b), rows]
    for c, x, y in rows:
        by[c][0] += x - y
        by[c][1] += 1
    cl = list(by.values())
    k, n = len(cl), len(rows)
    obs = sum(v[0] for v in cl) / n if n else 0.0
    rng = random.Random(seed)
    boots = []
    for _ in range(n_boot):
        s = m = 0
        for _ in range(k):
            v = cl[rng.randrange(k)]
            s += v[0]
            m += v[1]
        boots.append(s / m if m else 0.0)
    boots.sort()
    p_boot = (sum(1 for x in boots if x <= 0) + 1) / (n_boot + 1)
    b = sum(1 for _, x, y in rows if x > y)
    c = sum(1 for _, x, y in rows if x < y)
    p_mcn_one = sum(math.comb(b + c, i) for i in range(b, b + c + 1)) / 2 ** (b + c) if b + c else 1.0
    return {"rows": n, "threads": k, "rows_per_thread": n / k if k else 0.0, "d": obs,
            "acc_a": sum(x for _, x, _ in rows) / n if n else 0.0, "acc_b": sum(y for _, _, y in rows) / n if n else 0.0,
            "p": p_boot, "lb": boots[max(0, int(math.floor(alpha * n_boot)))],
            "ci95": (boots[int(0.025 * n_boot)], boots[min(n_boot - 1, int(0.975 * n_boot))]),
            "a_only": b, "b_only": c, "p_mcnemar_row_one_sided": p_mcn_one,
            "p_mcnemar_row_two_sided": binom_two_sided(b, c), "reject": p_boot <= alpha, "alpha": alpha}


def reader_compare(path_a: str, path_b: str, field_name: str = "em_primary", **kw) -> dict:
    a, b = load_reader_rows(path_a, field_name), load_reader_rows(path_b, field_name)
    ids = [i for i in a if i in b]
    if len(ids) != len(a) or len(ids) != len(b):
        raise SystemExit(f"reader preds cover different rows ({len(a)} vs {len(b)}, {len(ids)} shared)")
    return cluster_paired_test([(a[i][0], a[i][1], b[i][1]) for i in ids], **kw)


# ---------------------------------------------------------------- Holm over a FIXED family
def holm_family(pvals: dict[str, float | None], alpha: float = ALPHA_FW) -> list[dict]:
    """Holm step-down over a family fixed in advance. None = untested -> stays in m with p = 1."""
    names = list(pvals)
    ps = [1.0 if pvals[k] is None else float(pvals[k]) for k in names]
    adj = holm(ps)
    order = sorted(range(len(ps)), key=lambda i: ps[i])
    rank = {i: r for r, i in enumerate(order)}
    out, still = [], True
    for r, i in enumerate(order):
        lvl = alpha / (len(ps) - r)
        rej = still and ps[i] <= lvl
        still = rej
        out.append((i, rej, lvl))
    res = {i: (rej, lvl) for i, rej, lvl in out}
    return [{"hypothesis": names[i], "p": ps[i], "tested": pvals[names[i]] is not None, "holm_p": adj[i],
             "rank": rank[i] + 1, "alpha_at_rank": res[i][1], "reject": res[i][0]} for i in range(len(names))]


# ---------------------------------------------------------------- scorer agreement (kappa)
def simple_random_sample(ids: list[str], n: int, seed: int = 0) -> list[str]:
    """Simple random sample (NOT stratified) of n transcript ids, reproducible from the sorted id list."""
    pool = sorted(set(ids))
    return random.Random(seed).sample(pool, min(n, len(pool)))


def cohen_kappa(a: list[int], b: list[int]) -> float:
    n = len(a)
    if n == 0 or n != len(b):
        return float("nan")
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    pa, pb = sum(a) / n, sum(b) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    return 1.0 if pe == 1 else (po - pe) / (1 - pe)


def kappa_report(scorer: list[int], human: list[int], n_boot: int = N_BOOT, seed: int = 0) -> dict:
    n = len(scorer)
    rng = random.Random(seed)
    ks = []
    for _ in range(n_boot):
        idx = [rng.randrange(n) for _ in range(n)]
        k = cohen_kappa([scorer[i] for i in idx], [human[i] for i in idx])
        if not math.isnan(k):
            ks.append(k)
    ks.sort()
    sp = [h for s, h in zip(scorer, human) if s]
    sf = [h for s, h in zip(scorer, human) if not s]
    return {"n": n, "kappa": cohen_kappa(scorer, human),
            "kappa_ci95": (ks[int(0.025 * len(ks))], ks[min(len(ks) - 1, int(0.975 * len(ks)))]) if ks else None,
            "agreement": sum(1 for x, y in zip(scorer, human) if x == y) / n if n else float("nan"),
            "p_human_accepts_given_scorer_pass": sum(sp) / len(sp) if sp else None,
            "p_human_rejects_given_scorer_fail": (len(sf) - sum(sf)) / len(sf) if sf else None,
            "scorer_pass_rate": sum(scorer) / n if n else None, "human_pass_rate": sum(human) / n if n else None}


# ---------------------------------------------------------------- power, by simulation of the rules above
def variance_components(a: "Config", b: "Config", metric: str = "reward") -> dict:
    """Split the paired per-task difference variance into task-level and seed-level parts."""
    common = [t for t in a.tasks if t in set(b.tasks)]
    get = (lambda c, t: c.rewards(t)) if metric == "reward" else (lambda c, t: c.metric(t, metric))
    wa = statistics.fmean(statistics.variance(get(a, t)) for t in common) if a.k > 1 else 0.0
    wb = statistics.fmean(statistics.variance(get(b, t)) for t in common) if b.k > 1 else 0.0
    d = [statistics.fmean(get(a, t)) - statistics.fmean(get(b, t)) for t in common]
    vd = statistics.variance(d)
    seed_part = wa / a.k + wb / b.k
    return {"tasks": len(common), "ka": a.k, "kb": b.k, "within_var_a": wa, "within_var_b": wb,
            "paired_var": vd, "seed_part": seed_part, "task_var": max(0.0, vd - seed_part), "mean_diff": statistics.fmean(d)}


def simulate_power(n_tasks: int, true_d: float, task_sd: float, seed_var_a: float, seed_var_b: float,
                   k_a: int, k_b: int, margin: float = DELTA, alpha: float = ALPHA_FW, sims: int = 300,
                   n_boot: int = 1000, seed: int = 0) -> float:
    """Share of simulated studies in which one_sided_test rejects (normal task and seed effects)."""
    rng = random.Random(seed)
    sd = math.sqrt(seed_var_a / k_a + seed_var_b / k_b)
    hits = 0
    for s in range(sims):
        d = [true_d + rng.gauss(0, task_sd) + rng.gauss(0, sd) for _ in range(n_tasks)]
        hits += one_sided_test(d, margin, alpha, n_boot, seed=seed + s + 1)["reject"]
    return hits / sims


def detectable(n_tasks: int, task_sd: float, seed_var_a: float, seed_var_b: float, k_a: int, k_b: int,
               margin: float, alpha: float, target: float = 0.8, lo: float = -0.06, hi: float = 0.30,
               iters: int = 8, **kw) -> float | None:
    """Smallest true difference with simulated power >= target (bisection; power rises with the difference)."""
    f = lambda g: simulate_power(n_tasks, g, task_sd, seed_var_a, seed_var_b, k_a, k_b, margin, alpha, **kw)
    if f(hi) < target:
        return None
    if f(lo) >= target:
        return lo
    for _ in range(iters):
        mid = (lo + hi) / 2
        lo, hi = (lo, mid) if f(mid) >= target else (mid, hi)
    return round(hi, 3)


def simulate_reader_power(threads: int, rows_per_thread: int, true_d: float, disagree: float,
                          cluster_sd: float = 0.15, alpha: float = ALPHA_FW, sims: int = 300, n_boot: int = 1000,
                          seed: int = 0) -> float:
    """Power of cluster_paired_test. Each row disagrees with prob `disagree`; among discordant rows A wins with
    prob 0.5 + true_d / (2 * disagree) plus a per-thread shift ~ N(0, cluster_sd) (clipped to [0, 1])."""
    rng = random.Random(seed)
    base = 0.5 + true_d / (2 * disagree)
    hits = 0
    for s in range(sims):
        rows = []
        for c in range(threads):
            pw = min(1.0, max(0.0, base + rng.gauss(0, cluster_sd)))
            for _ in range(rows_per_thread):
                if rng.random() < disagree:
                    w = rng.random() < pw
                    rows.append((str(c), int(w), int(not w)))
                else:
                    rows.append((str(c), 1, 1))
        hits += cluster_paired_test(rows, alpha, n_boot, seed + s + 1)["reject"]
    return hits / sims


# ---------------------------------------------------------------- confirmatory plan runner
def run_gate_problems(run: str, freeze: dict, same_frozen=None) -> list[str]:
    """Why run `run` may not count (Amendment 2, N4): gym/frozen.py run_problems on its summary.json."""
    import frozen
    try:
        d = resolve_run(run)
    except SystemExit:
        return ["missing"]
    sp = d / "summary.json"
    summary = json.loads(sp.read_text()) if sp.exists() else None
    return frozen.run_problems(summary, freeze, same_frozen or frozen.frozen_paths_identical)


def check_plan(plan: dict, gate: bool = True, freeze: dict | None = None, same_frozen=None) -> dict:
    """Every input the plan names, and what is wrong with it. `problems` empty = every hypothesis can be tested.

    Missing run names are listed explicitly so that a naming mismatch (round-2 N3: the frontier runs) can never
    turn a hypothesis into a silent 'not tested'."""
    if gate and freeze is None:
        import frozen
        freeze = frozen.freeze_state()
    runs, problems = {}, []
    for label, names in plan["configs"].items():
        for r in names:
            why = run_gate_problems(r, freeze, same_frozen) if gate else ([] if _run_exists(r) else ["missing"])
            runs[r] = why
            problems += [f"{label}: run {r}: {w}" for w in why]
    for h in plan["hypotheses"]:
        if h["test"] == "reader_superiority":
            for k in ("a", "b"):
                if not Path(h[k]).exists():
                    problems.append(f"{h['id']}: preds file {h[k]}: missing")
    return {"runs": runs, "problems": problems, "freeze_commit": (freeze or {}).get("commit")}


def _run_exists(r: str) -> bool:
    try:
        resolve_run(r)
        return True
    except SystemExit:
        return False


def run_plan(plan: dict, seed: int = 0, results_root: Path | None = None, gate: bool = True,
             freeze: dict | None = None, same_frozen=None) -> dict:
    """Evaluate every hypothesis in a pre-registered plan (gym/confirmatory_v3.json) and apply Holm once.

    Missing runs or preds files -> that hypothesis is untested (p = 1, stays in m). With gate=True (the default
    and the only mode `stats.py plan` offers) a run whose summary.json is void, has still_failed rollouts,
    recorded dirty frozen paths, or ran off the freeze commit's frozen paths makes its config untested too
    (Amendment 2, N4). gate=False is for exploratory reuse on runs made before the freeze (e.g. v2)."""
    alpha = float(plan.get("alpha_familywise_one_sided", ALPHA_FW))
    rows, pvals = [], {}
    chk = check_plan(plan, gate, freeze, same_frozen)

    def cfg(label):
        runs = plan["configs"][label]
        bad = {r: chk["runs"][r] for r in runs if chk["runs"].get(r)}
        if bad:
            r, why = next(iter(bad.items()))
            raise LookupError(f"{len(bad)} of {len(runs)} {label} run(s) missing or rejected, e.g. {r}: {'; '.join(why)}")
        try:
            return Config(label, runs, strict=True)
        except SystemExit as e:   # missing run dir or task -> untested
            raise LookupError(str(e))

    for h in plan["hypotheses"]:
        hid, kind = h["id"], h["test"]
        res: dict = {"id": hid, "test": kind, "claim": h.get("claim"), "confirmatory": h.get("confirmatory", True)}
        try:
            if kind in ("superiority", "noninferiority"):
                margin = 0.0 if kind == "superiority" else float(h.get("delta", plan.get("delta", DELTA)))
                res.update(noninferiority(cfg(h["a"]), cfg(h["b"]), margin, h.get("metric", "reward"), alpha, seed=seed))
            elif kind == "fewer":
                res.update(fewer(cfg(h["a"]), cfg(h["b"]), h.get("metric", "model_calls"), alpha, seed=seed))
            elif kind == "reader_superiority":
                for k in ("a", "b"):
                    if not Path(h[k]).exists():
                        raise LookupError(f"no preds file {h[k]}")
                res.update(reader_compare(h["a"], h["b"], alpha=alpha, seed=seed))
            else:
                raise ValueError(f"unknown test {kind}")
            res["tested"] = True
        except LookupError as e:
            res.update(tested=False, p=None, why=str(e)[:200])
        rows.append(res)
        if res["confirmatory"] and not h.get("co_primary_of"):
            pvals[hid] = res.get("p")
    # intersection-union: a hypothesis with co-primary parts takes the max p of its parts
    for h in plan["hypotheses"]:
        parent = h.get("co_primary_of")
        if parent:
            r = next(x for x in rows if x["id"] == h["id"])
            prev = pvals.get(parent, 0.0)
            pvals[parent] = None if (prev is None or r.get("p") is None) else max(prev, r["p"])
    fam = holm_family(pvals, alpha)
    return {"alpha_familywise_one_sided": alpha, "delta": plan.get("delta", DELTA), "tests": rows, "family": fam,
            "gate": gate, "freeze_commit": chk["freeze_commit"], "input_problems": chk["problems"]}


def md_plan(out: dict) -> str:
    lines = [f"Confirmatory family (Holm, familywise one-sided alpha = {out['alpha_familywise_one_sided']}, "
             f"m = {len(out['family'])}; untested hypotheses stay in m with p = 1):", "",
             "| hypothesis | tested | p | Holm p | alpha at rank | decision |", "|---|---|---|---|---|---|"]
    if out.get("input_problems"):
        lines[1:1] = ["", f"**{len(out['input_problems'])} input problem(s)** (missing or rejected runs/files; their "
                      "hypotheses are NOT TESTED): " + "; ".join(out["input_problems"][:12])
                      + (" ..." if len(out["input_problems"]) > 12 else "")]
    for f in out["family"]:
        lines.append(f"| {f['hypothesis']} | {'yes' if f['tested'] else 'NOT TESTED'} | {fmt_p(f['p'])} | {fmt_p(f['holm_p'])} "
                     f"| {f['alpha_at_rank']:.4f} | {'supported' if f['reject'] else 'not supported'} |")
    lines += ["", "| test | what | n | estimate | one-sided bound | p (boot / t or row McNemar) |", "|---|---|---|---|---|---|"]
    for r in out["tests"]:
        if not r.get("tested"):
            lines.append(f"| {r['id']} | {r['test']} | | not tested ({r.get('why', '')}) | | |")
        elif r["test"] == "reader_superiority":
            lines.append(f"| {r['id']} | reader exact match (reason scored on status), cluster bootstrap | {r['rows']} rows / "
                         f"{r['threads']} threads | {r['d']:+.3f} ({r['acc_a']:.3f} vs {r['acc_b']:.3f}) | lb {r['lb']:+.3f} | "
                         f"{fmt_p(r['p'])} / row McNemar {fmt_p(r['p_mcnemar_row_one_sided'])} (sensitivity) |")
        elif r["test"] == "fewer":
            lines.append(f"| {r['id']} | {r['metric']} {r['a']} - {r['b']} < 0 | {r['tasks']} | {r['d']:+.2f} | ub {r['ub']:+.2f} | "
                         f"{fmt_p(r['p_boot'])} / {fmt_p(r['p_t'])} |")
        else:
            lines.append(f"| {r['id']} | {r['metric']} {r['a']} - {r['b']} > {-r['margin']:+.3f} ({r['ka']}/{r['kb']} runs) | "
                         f"{r['tasks']} | {r['d']:+.3f} | lb {r['lb']:+.3f} (boot {r['lb_boot']:+.3f}, t {r['lb_t']:+.3f}) | "
                         f"{fmt_p(r['p_boot'])} / {fmt_p(r['p_t'])} |")
    return "\n".join(lines)


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
    head = ["A vs B", "runs (A/B)", "tasks", "Δ mean reward (95% paired bootstrap)", "p (reward)", "Holm p (this table)",
            "Δ pass rate", "tasks A better / B better", "p (pass: sign test; McNemar only at 1 run)", "Holm p (exploratory)"]
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
    ap.add_argument("--strict", action="store_true", help="exit non-zero if any task is missing from any run")
    ap.add_argument("--delta", type=float, default=None, help="also run the one-sided non-inferiority test at this margin")
    a = ap.parse_args(argv)
    global STRICT
    STRICT = a.strict
    cfgs = [parse_config(s) for s in a.config]
    by = {c.label: c for c in cfgs}
    summ = [summarize(c, seed=a.seed) for c in cfgs]
    comps = []
    for spec in a.compare:
        x, y = spec.split(":")
        comps.append(compare(by[x], by[y], seed=a.seed, delta=a.delta))
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
        if a.delta is not None:
            print(f"\nOne-sided non-inferiority, margin {a.delta} (alpha 0.025; p = max of bootstrap and paired-t):\n")
            print("| A vs B | Δ | lower bound (boot / t) | p (boot / t) |\n|---|---|---|---|")
            for r in comps:
                ni = r.get("ni")
                if ni:
                    print(f"| `{r['a']}` vs `{r['b']}` | {ni['d']:+.3f} | {ni['lb_boot']:+.3f} / {ni['lb_t']:+.3f} | "
                          f"{fmt_p(ni['p_boot'])} / {fmt_p(ni['p_t'])} |")
    if a.matrix:
        for c in cfgs:
            print("\n" + md_matrix(c))


def plan_main(argv=None):
    ap = argparse.ArgumentParser(description="Run the pre-registered confirmatory plan (Amendment 1)")
    ap.add_argument("plan", help="e.g. gym/confirmatory_v3.json")
    ap.add_argument("--md", action="store_true")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--check", action="store_true",
                    help="no statistics: list every missing or rejected run / preds file and exit 1 if there is any")
    a = ap.parse_args(argv)
    plan = json.loads(Path(a.plan).read_text())
    if a.check:
        chk = check_plan(plan)
        print(f"freeze commit: {chk['freeze_commit'] or 'NONE (docs/freeze-manifest.json not committed)'}")
        print(f"{sum(1 for v in chk['runs'].values() if not v)} of {len(chk['runs'])} runs count")
        for p_ in chk["problems"]:
            print("  " + p_)
        sys.exit(1 if chk["problems"] else 0)
    out = run_plan(plan, seed=a.seed)
    for p_ in out["input_problems"]:
        print(f"INPUT PROBLEM: {p_}", file=sys.stderr)
    print(md_plan(out) if a.md else json.dumps(out, indent=1, default=str))


def power_main(argv=None):
    """Power by simulation, inputs measured from committed v2 runs (Amendment 1, finding stats-4/6/7)."""
    ap = argparse.ArgumentParser(description=power_main.__doc__)
    ap.add_argument("--sims", type=int, default=200)
    ap.add_argument("--boot", type=int, default=500)
    a = ap.parse_args(argv)
    v2 = lambda p: [f"v2-heldout-{p}-s{i}" for i in (1, 2, 3)]
    base, final, router = (Config(n, v2(n)) for n in ("baseline", "final", "final-router"))
    vc_close, vc_far = variance_components(router, final), variance_components(final, base)
    print(json.dumps({"router_vs_final": vc_close, "final_vs_baseline": vc_far}, indent=1))
    kw = dict(sims=a.sims, n_boot=a.boot)
    rows = []
    for n in (33, 40, 60):
        for k in (3, 5):
            for name, vc, margin in (("H1 final vs baseline (superiority)", vc_far, 0.0),
                                     ("H3(ii) router vs final (NI, delta 0.05)", vc_close, DELTA),
                                     ("H4 local vs frontier (NI, delta 0.05; frontier seed var = router's)", 
                                      {**vc_close, "within_var_a": vc_close["within_var_b"], "within_var_b": vc_close["within_var_a"]}, DELTA)):
                tsd = math.sqrt(vc["task_var"])
                for alpha, lab in ((ALPHA_FW, "alpha 0.025 (Holm rank m)"), (ALPHA_FW / 5, "alpha 0.005 (Holm rank 1, m=5)")):
                    g = detectable(n, tsd, vc["within_var_a"], vc["within_var_b"], k, k, margin, alpha, **kw)
                    rows.append((name, n, k, lab, g))
                    print(f"| {name} | {n} | {k} | {lab} | {'none in grid' if g is None else f'{g:+.3f}'} |", flush=True)
    print("\nreader (cluster bootstrap), true difference needed for 80% power:")
    for threads, m in ((30, 6), (40, 8), (60, 8)):
        for q in (0.10, 0.20):
            for alpha in (ALPHA_FW, ALPHA_FW / 5):
                g = next((d for d in (0.02, 0.03, 0.04, 0.05, 0.06, 0.08, 0.10, 0.12, 0.15)
                          if simulate_reader_power(threads, m, d, q, alpha=alpha, **kw) >= 0.8), None)
                print(f"| {threads} threads x {m} rows | disagree {q:.0%} | alpha {alpha} | "
                      f"{'> 0.15' if g is None else f'{g:.2f}'} |", flush=True)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "plan":
        plan_main(sys.argv[2:])
    elif len(sys.argv) > 1 and sys.argv[1] == "power":
        power_main(sys.argv[2:])
    else:
        main()
