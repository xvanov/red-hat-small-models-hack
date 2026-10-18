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
