"""Data for the console's evidence panels. Every number is read from a committed result file or a
runtime file at request time; nothing here is typed in by hand except model-card facts, which carry
their source link.

  realworld()   the live Facebook Page post (docs/DECISIONS.md D20) + aggregate pilot counters
  trust()       which model does what, the 33B budget, held-out scores vs the Opus 5.5 reference
  scoreboard()  held-out ablation ladder from gym/results/*/summary.json (baseline -> final)
"""
from __future__ import annotations

import json
import re
import statistics
from pathlib import Path

from . import integration as integ

REPO = integ.REPO
GYM = REPO / "gym" / "results"
READER = REPO / "reader" / "results"
PILOT = REPO / "runs" / "pilot"

LIGHTNING_CARD = "https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-BF16"
READER_HF = "https://huggingface.co/xvanov/rentus-reader-qwen3-0.6b"
# Model-card parameter counts (the rule uses the card's number; docs/hackathon/README.md section 2.1).
CARD_PARAMS_B = {"Qwen/Qwen3-0.6B": 0.6}
LIGHTNING_PARAMS_B = 30.0
BUDGET_B = 33.0


def _json(p: Path):
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def _rows(p: Path) -> list[dict]:
    try:
        return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
    except Exception:
        return []


# ------------------------------------------------------------------ real world
def realworld() -> dict:
    out = {"post": None, "stats": None, "thumb": None, "shadow": "channels/pilot_shadow.py drafts in shadow, never sends"}
    m = None
    dec = REPO / "docs" / "DECISIONS.md"
    if dec.exists():
        for line in dec.read_text().splitlines():
            if line.startswith("| D20 "):
                m = re.search(r"Permalink: (https://www\.facebook\.com/\S+?)\s", line)
                text = re.search(r'PUBLISHED Page post at (.+? UTC): "(.+?)" \d', line)
                out["post"] = {"permalink": m.group(1) if m else None,
                               "posted": text.group(1) if text else None,
                               "text": text.group(2) if text else None, "decision": "D20"}
    pub = _json(PILOT / "published.json")
    if pub and out["post"] is not None:
        out["post"]["permalink"] = out["post"]["permalink"] or pub.get("permalink_url")
        out["post"]["is_published"] = pub.get("is_published")
        out["post"]["photos"] = len(pub.get("photo_ids") or [])
    st = _json(PILOT / "stats.json")
    if isinstance(st, dict):  # counts only: never forward renter text
        out["stats"] = {k: v for k, v in st.items() if isinstance(v, (int, float)) or k == "updated_at"}
    if (PILOT / "thumb.jpg").exists():
        out["thumb"] = "runs/pilot/thumb.jpg"
    return out


# ------------------------------------------------------------------ held-out results
def _summary(name: str) -> dict | None:
    d = _json(GYM / name / "summary.json")
    if not d or d.get("invalid"):
        return None
    return d


def _seeds(name: str) -> list[dict]:
    """A config and its repeat (-s2), if present."""
    return [d for d in (_summary(name), _summary(name + "-s2")) if d]


def _task_seconds(names: list[str]) -> list[float]:
    secs = []
    for n in names:
        secs += [r["seconds"] for r in _rows(GYM / n / "per_task.jsonl") if isinstance(r.get("seconds"), (int, float))]
    return secs


def _agg(name: str, label: str, kind: str, runner: str = "local") -> dict | None:
    runs = _seeds(name)
    if not runs:
        return None
    n = runs[0].get("tasks") or 0
    pr = statistics.mean(r["pass_rate"] for r in runs)
    return {"name": name, "label": label, "kind": kind, "runner": runner, "runs": len(runs), "tasks": n,
            "pass_rate": pr, "passed": round(pr * n, 1), "mean_reward": statistics.mean(r["mean_reward"] for r in runs),
            "reward_range": [min(r["mean_reward"] for r in runs), max(r["mean_reward"] for r in runs)],
            "by_category": {c: statistics.mean(r["by_category"][c]["mean_reward"] for r in runs)
                            for c in (runs[0].get("by_category") or {})},
            "checks": runs[0].get("check_pass_rate") or {}, "model": runs[0].get("model")}


LADDER = [  # (run name, label, kind, runner)  held-out, 31 tasks, docs/results.md order
    ("baseline", "Baseline (our loop)", "baseline", "local"),
    ("heldout-guard", "+ renter guard (harness)", "step", "local"),
    ("heldout-guard+prompt3", "+ prompt v3", "step", "local"),
    ("heldout-guard+prompt3+style", "+ style pre-check (verifier)", "step", "local"),
    ("heldout-guard+prompt3+style+rhist", "+ reasoning history = final", "final", "local"),
    ("heldout-guard+prompt3+style+rhist+readermodel-rerun", "final + fine-tuned reader", "final", "local"),
    ("baseline-nemo", "NeMo Gym simple_agent, baseline", "baseline", "nemo"),
    ("heldout-nemo-prompt3", "NeMo Gym simple_agent + prompt v3", "step", "nemo"),
    ("heldout-frontier-opus55-guard+prompt3+style+rhist", "Claude Opus 5.5, same harness (reference)", "reference", "local"),
]


def scoreboard() -> list[dict]:
    rows = []
    base = None
    for name, label, kind, runner in LADDER:
        if name == "baseline":  # the baseline exists as two separate runs: baseline + heldout-base
            runs = [d for d in (_summary("baseline"), _summary("heldout-base")) if d]
            if not runs:
                continue
            a = _agg("baseline", label, kind, runner)
            a["runs"] = len(runs)
            a["pass_rate"] = statistics.mean(r["pass_rate"] for r in runs)
            a["passed"] = round(a["pass_rate"] * a["tasks"], 1)
            a["mean_reward"] = statistics.mean(r["mean_reward"] for r in runs)
        else:
            a = _agg(name, label, kind, runner)
        if not a:
            continue
        if name == "baseline":
            base = a
        if base and kind != "baseline":
            a["delta_reward"] = a["mean_reward"] - base["mean_reward"]
        rows.append(a)
    return rows


def trust() -> dict:
    final_names = ["heldout-guard+prompt3+style+rhist", "heldout-guard+prompt3+style+rhist-s2"]
    ours = _agg(final_names[0], "Lightning 30B-A3B + our harness", "final")
    secs = _task_seconds([n for n in final_names if _summary(n)])
    if ours and secs:
        ours["task_seconds_p50"] = statistics.median(secs)
        ours["task_seconds_mean"] = statistics.mean(secs)
        ours["cost_per_task_usd"] = 0.0
    opus = _summary("heldout-frontier-opus55-guard+prompt3+style+rhist")
    ref = None
    if opus:
        rm = opus.get("reference_model") or {}
        ref = {"label": f"Claude {opus.get('model')} (reference only)", "model": opus.get("model"),
               "runs": 1, "tasks": opus.get("tasks"), "pass_rate": opus["pass_rate"],
               "passed": round(opus["pass_rate"] * opus["tasks"]), "mean_reward": opus["mean_reward"],
               "cost_per_task_usd": rm.get("cost_per_task_usd"), "task_seconds_p50": rm.get("task_seconds_p50"),
               "task_seconds_mean": rm.get("task_seconds_mean"), "run_cost_usd": rm.get("run_cost_usd")}

    rinfo = _json(READER / "finetuned.train_info.json") or {}
    rfull = _json(READER / "finetuned.test.metrics.json") or {}
    ropus = _json(READER / "frontier-opus-5-5.test.sample400.metrics.json") or {}
    same = ropus.get("same_sample_baselines") or {}
    base_model = rinfo.get("base_model", "Qwen/Qwen3-0.6B")
    reader_b = CARD_PARAMS_B.get(base_model)
    reader = {
        "base_model": base_model, "params_b": reader_b, "hf": READER_HF, "train_rows": rinfo.get("train_rows"),
        "train_minutes": round(rinfo["train_seconds"] / 60) if rinfo.get("train_seconds") else None,
        "gpu": rinfo.get("gpu"),
        "test_rows": rfull.get("n"), "exact_match_full": rfull.get("exact_match"),
        "latency_p50_s": (rfull.get("latency_s") or {}).get("p50"),
        "sample_n": (ropus.get("sample") or {}).get("n"),
        "sample": {k: (same.get(k) or {}).get("exact_match") for k in ("finetuned", "fallback", "lightning", "base")},
        "opus_exact_match": ropus.get("exact_match"), "opus_cost_per_read_usd": ropus.get("cost_per_row_usd"),
        "opus_latency_p50_s": (ropus.get("latency_s") or {}).get("p50"),
        "opus_model": ropus.get("model"),
        "owner_gold": [{"who": who, "model": m.get("model"), "n": m.get("n"), "exact_match": m.get("exact_match")}
                       for who, m in ((w, _json(READER / f"{f}.owner_gold_combined.metrics.json") or {})
                                      for w, f in (("ours", "finetuned-twin"), ("frontier", "frontier-twin"), ("lightning", "lightning-twin")))
                       if m.get("n")],
    }
    total = LIGHTNING_PARAMS_B + (reader_b or 0)
    return {
        "roles": [
            {"who": "Operator", "model": "Nemotron 3.5 Lightning 30B-A3B", "params_b": LIGHTNING_PARAMS_B,
             "served": "vLLM, NVFP4, one RTX Pro 6000", "does": "talks to the owner and renters and makes every tool call",
             "link": LIGHTNING_CARD},
            {"who": "Reader", "model": f"rentus-reader ({base_model} + SFT)", "params_b": reader_b,
             "served": "vLLM, same GPU", "does": "turns a renter's message into exact JSON (lease, date, phone, ...)",
             "link": READER_HF},
            {"who": "Verifier", "model": "plain code, no model", "params_b": 0,
             "served": "in the loop", "does": "schema and style checks, retries, fallbacks, escalation guard",
             "link": None},
        ],
        "budget": {"used_b": total, "limit_b": BUDGET_B,
                   "note": "model-card counts; the Opus reference is never loaded by the running system"},
        "heldout": {"ours": ours, "reference": ref,
                    "baseline": next((r for r in scoreboard() if r["name"] == "baseline"), None)},
        "reader": reader,
        "sources": ["docs/results.md", "gym/results/*/summary.json", "reader/results/*.metrics.json"],
    }


# ------------------------------------------------------------------ v2 held-out results with CIs
_STATS = {"mod": None}
_RESULTS_CACHE: dict = {"key": None, "value": None}
V2_RE = re.compile(r"^v(?P<ver>[2-9])-heldout-(?P<name>.+?)(?:-s(?P<seed>\d+))?$")
V2_LABELS = {  # run-name stem -> (label, kind); unknown stems are shown by name
    "baseline": ("Baseline", "baseline"),
    "final": ("Final", "final"),
    "final-router": ("Final + router", "variant"),
    "final-nemo": ("Final on NeMo Gym simple_agent", "variant"),
    "frontier-cc-guard+prompt3+style+rhist+readermodel": ("Claude Opus 5.5, same harness (reference)", "reference"),
}


def _stats():
    """gym/stats.py (owned by the coordinator), imported by path so no other `stats` module shadows it."""
    if _STATS["mod"] is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("rentus_gym_stats", REPO / "gym" / "stats.py")
        mod = importlib.util.module_from_spec(spec)
        import sys
        sys.modules["rentus_gym_stats"] = mod  # dataclasses look the module up by name
        spec.loader.exec_module(mod)
        _STATS["mod"] = mod
    return _STATS["mod"]


def _v2_groups() -> dict[str, list[Path]]:
    """Held-out run groups of the newest protocol version that has both a baseline and a final run
    (v3 once its runs land, v2 until then). Runs still in progress (no summary.json yet) are skipped."""
    by_ver: dict[str, dict[str, list[Path]]] = {}
    if not GYM.is_dir():
        return {}
    for d in sorted(GYM.iterdir()):
        m = V2_RE.match(d.name)
        if not (m and d.is_dir() and (d / "per_task.jsonl").exists() and (d / "summary.json").exists()):
            continue
        s = _json(d / "summary.json") or {}
        if s.get("invalid") or s.get("stub") or s.get("void") or s.get("still_failed"):
            continue
        by_ver.setdefault(m.group("ver"), {}).setdefault(m.group("name"), []).append(d)
    for ver in sorted(by_ver, reverse=True):
        if {"baseline", "final"} <= set(by_ver[ver]):
            _RESULTS_CACHE["ver"] = ver
            return by_ver[ver]
    return {}


def plain_label(name: str, config_label: str, spec: str) -> tuple[str, str]:
    """A name a non-expert can read, from the run name and its config string, plus one line on what it is."""
    cfg = dict(t.split("=", 1) for t in config_label.split() if "=" in t)
    prompt = cfg.get("prompt", "?")
    reader = "fine-tuned reader" if "readermodel" in spec or "readermodel" in name else "rule-based reader"
    tuned = f"v{prompt.lstrip('v')} prompt + guards + {reader}"
    if name == "baseline":
        return "Lightning · starting setup", f"Nemotron 3.5 Lightning with our first prompt ({prompt}), verbose tool descriptions and the rule-based reader"
    if name == "final":
        return f"Lightning · tuned ({tuned})", "Nemotron 3.5 Lightning with everything we built: " + tuned
    if name == "final-router":
        return "Lightning · tuned + router", f"The tuned setup ({tuned}) plus a router that picks the tools offered per step"
    if name == "final-nemo":
        return "Lightning · tuned, on NeMo Gym's own harness", "The tuned prompt run through NeMo Gym's simple_agent instead of our loop"
    if name.startswith("frontier"):
        return "Claude Opus 5.5 · same harness (reference only)", "A frontier model in the same loop and tools, for scale; never used by the running system"
    return name.replace("-", " "), config_label


FLOORS = GYM / "v3-floors.json"


def results_v2() -> dict:
    """Held-out v2 configs with 95% CIs and paired tests, computed by gym/stats.py from per_task.jsonl."""
    groups = _v2_groups()
    key = tuple((n, tuple((p.name, (p / "per_task.jsonl").stat().st_mtime) for p in ps)) for n, ps in sorted(groups.items()))
    if key == _RESULTS_CACHE["key"]:
        return _RESULTS_CACHE["value"]
    ver = _RESULTS_CACHE.get("ver") or "2"
    out = {"configs": [], "compare": [], "categories": {}, "version": f"v{ver}",
           "source": f"gym/results/v{ver}-heldout-*/per_task.jsonl via gym/stats.py", "doc": "docs/results.md"}
    if not groups:
        _RESULTS_CACHE.update(key=key, value=out)
        return out
    st = _stats()
    cfgs = {}
    order = list(V2_LABELS) + sorted(n for n in groups if n not in V2_LABELS)
    for name in order:
        if name not in groups:
            continue
        paths = groups[name]
        try:
            cfg = st.Config(name, [str(p) for p in paths])
        except BaseException:  # stats raises SystemExit on a missing run
            continue
        s = st.summarize(cfg)
        sums = [_json(p / "summary.json") or {} for p in paths]
        rows = [r for p in paths for r in _rows(p / "per_task.jsonl")]
        secs = [r["seconds"] for r in rows if isinstance(r.get("seconds"), (int, float))]
        calls = [r["model_calls"] for r in rows if isinstance(r.get("model_calls"), (int, float))]
        cost = [r["cost_usd"] for r in rows if isinstance(r.get("cost_usd"), (int, float))]
        label, kind = V2_LABELS.get(name, ("Claude Opus 5.5, same harness (reference)", "reference") if name.startswith("frontier")
                                    else (name.replace("-", " "), "variant"))
        plain, explain = plain_label(name, sums[0].get("config_label") or "", (sums[0].get("variant") or {}).get("spec") or "")
        k = s["k"]
        cfgs[name] = cfg
        out["configs"].append({
            "name": name, "label": label, "plain_label": plain, "explain": explain, "kind": kind, "runs": s["runs"] and len(s["runs"]), "tasks": s["tasks"],
            "pass_rate": s["pass_rate"], "pass_ci": list(s["pass_ci"]), "mean_reward": s["mean_reward"],
            "reward_ci": list(s["reward_ci"]), "pass_all_runs": s["pass_hat"][k][0] if k >= 2 else None,
            "pass_any_run": s["pass_at"][k] if k >= 2 else None, "flaky_tasks": s.get("flaky_tasks"),
            "model": sums[0].get("model"), "via": sums[0].get("via"), "config_label": sums[0].get("config_label"),
            "spec": (sums[0].get("variant") or {}).get("spec"), "git": sums[0].get("git"),
            "started": min((x.get("started") or "") for x in sums) or None,
            "task_seconds_p50": statistics.median(secs) if secs else None,
            "model_calls_mean": statistics.mean(calls) if calls else None,
            "cost_per_task_usd": statistics.mean(cost) if cost else None,
            "runs_dirs": [p.name for p in paths]})
    base = cfgs.get("baseline")
    final = cfgs.get("final")
    pairs = []
    if final and base:
        pairs.append((final, base))
    for n, c in cfgs.items():
        if final and c is not final and c is not base:
            pairs.append((c, final))
    cmps = [st.compare(a, b) for a, b in pairs]
    if cmps:
        adj_r = st.holm([c["p_reward"] for c in cmps])
        adj_p = st.holm([c["p_pass"] for c in cmps])
        for c, pr, pp in zip(cmps, adj_r, adj_p):
            lab = {x["name"]: x["label"] for x in out["configs"]}
            out["compare"].append({"a": lab.get(c["a"], c["a"]), "b": lab.get(c["b"], c["b"]), "tasks": c["tasks"],
                                   "d_reward": c["d_reward"], "d_reward_ci": list(c["d_reward_ci"]),
                                   "p_reward_holm": pr, "d_pass": c["d_pass"], "a_better": c["a_better"],
                                   "b_better": c["b_better"], "p_pass_holm": pp})
    for n in ("baseline", "final"):
        if n in cfgs:
            out["categories"][n] = {cat: {"tasks": v["tasks"], "pass_rate": v["pass_rate"], "pass_ci": list(v["pass_ci"]),
                                          "mean_reward": v["mean_reward"], "reward_ci": list(v["reward_ci"])}
                                    for cat, v in st.by_category(cfgs[n]).items()}
    fl = _json(FLOORS) or {}
    tasks = next((c["tasks"] for c in out["configs"] if c["kind"] == "final"), None)
    if fl.get("agents") and fl.get("tasks") == tasks:  # floors only when they were scored on this same task set
        names = {"do_nothing": "Does nothing", "greet_only": "Only says hello", "escalate_all": "Hands everything to the owner",
                 "mark_lost": "Marks every renter lost"}
        out["floors"] = [{"name": k, "label": names.get(k, k), "mean_reward": v.get("mean_reward"), "pass_rate": v.get("pass_rate")}
                         for k, v in fl["agents"].items()]
    _RESULTS_CACHE.update(key=key, value=out)
    return out


# ------------------------------------------------------------------ vLLM serving performance
SERVING = REPO / "serving" / "results"


def performance() -> dict:
    """Serving numbers from serving/results/serve_bench.jsonl (docs/vllm.md explains the method)."""
    rows = _rows(SERVING / "serve_bench.jsonl")
    out = {"sweep": [], "prefix": [], "reasoning": [], "totals": None, "hardware": None,
           "source": "serving/results/serve_bench.jsonl", "doc": "docs/vllm.md"}
    if not rows:
        return out
    def slim(r):
        s, rd = r.get("server") or {}, r.get("reader") or {}
        return {"n": r.get("concurrency"), "tok_s": r.get("agg_out_tok_s"), "req_s": r.get("req_per_s"),
                "lat_p50_s": r.get("lat_p50_s"), "lat_p95_s": r.get("lat_p95_s"), "ttft_p50_ms": r.get("ttft_p50_ms"),
                "ttft_p95_ms": r.get("ttft_p95_ms"), "hit": s.get("prefix_cache_hit_rate"), "errors": r.get("errors"),
                "requests": r.get("requests"), "reader_p50_ms": rd.get("p50_ms"), "reader_p95_ms": rd.get("p95_ms"),
                "out_tok_mean": r.get("out_tok_mean"), "tool_call_share": r.get("tool_call_share"),
                "prompt_tok_mean": r.get("prompt_tok_mean"), "started": r.get("started")}
    sweep = {}
    for r in rows:  # the latest row per level wins (the N=32 clean re-run replaces the contaminated one)
        if r.get("label", "").startswith("baseline: prefix cache on") and r.get("mode") == "decode":
            sweep[r["concurrency"]] = slim(r)
    out["sweep"] = [sweep[k] for k in sorted(sweep)]
    on = {r["concurrency"]: slim(r) for r in rows if r.get("label", "").startswith("prefix reuse ON")}
    off = {r["concurrency"]: slim(r) for r in rows if r.get("label", "").startswith("prefix reuse OFF")}
    out["prefix"] = [{"n": n, "on": on[n], "off": off[n]} for n in sorted(set(on) & set(off))]
    out["reasoning"] = [{"reasoning": r.get("reasoning"), **slim(r)} for r in rows if r.get("mode") == "turn"]
    out["totals"] = {"requests": sum(r.get("requests") or 0 for r in rows), "errors": sum(r.get("errors") or 0 for r in rows),
                     "prompt_tokens": rows[-1].get("prompt_tok_mean"), "tools": rows[-1].get("tools")}
    doc = REPO / "docs" / "vllm.md"
    if doc.exists():
        m = re.search(r"One (\$[\d.]+/hr) (RTX Pro 6000[^\s,]*)", doc.read_text())
        if m:
            out["hardware"] = {"gpu": m.group(2), "price": m.group(1)}
    return out
