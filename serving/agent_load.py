"""Realistic load test: N concurrent full operator conversations against the live vLLM servers.

    gym/.venv/bin/python serving/agent_load.py --levels 1,8,32,64,128 --label baseline
    gym/.venv/bin/python serving/agent_load.py --levels 1 --convs 1 --label smoke      # quick plumbing check

Each conversation is one Gym task run end to end by the real operator: rentus_operator.run (final config:
prompt v3, renter guard, style pre-check, reasoning kept in history, verifier on), the sandbox tools via
gym/rentus_env.RolloutSession, scripted renters/vendors (no model), and read_reply on the fine-tuned reader
(second vLLM server) when READER_BASE_URL is set. Tasks come from --tasks (default gym/tasks/v2/train.jsonl)
and are cycled, each conversation in its own fresh World.

Per level: conversations completed per hour (whole run incl. drain, and steady state up to the last start),
tool calls/s, model turn latency p50/p95 (client side, non-streamed, as the loop calls it), server-side TTFT
and queue time from /metrics, tokens/s, prefix-cache hit rate, KV-cache usage (sampled), errors and retries,
scorer pass rate and mean reward (quality under load), and the lead economics:
  leads/hour            = leasing conversations completed per hour
  qualified leads/hour  = leasing conversations whose renter finished the 5-item gate (register state)
  cost per qualified    = GPU $/hr / qualified leads per hour
Results append to serving/results/agent_load.jsonl.
"""
from __future__ import annotations

import argparse
import datetime
import itertools
import json
import os
import sys
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
for p in (HERE, REPO / "gym", REPO / "operator", REPO / "tools"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import vllm_metrics as vm  # noqa: E402

RESULTS = HERE / "results"
GPU_USD_PER_HR = 2.63


class TimedClient:
    """Wraps an OpenAI client: times every chat.completions.create, keeps usage and exceptions."""

    def __init__(self, inner, log: list, lock: threading.Lock):
        self._inner, self._log, self._lock = inner, log, lock
        self.chat = self
        self.completions = self

    def create(self, **kw):
        t0 = time.perf_counter()
        try:
            resp = self._inner.chat.completions.create(**kw)
        except Exception as e:
            with self._lock:
                self._log.append({"lat": time.perf_counter() - t0, "error": f"{type(e).__name__}: {e}"[:200]})
            raise
        u = getattr(resp, "usage", None)
        with self._lock:
            self._log.append({"lat": time.perf_counter() - t0, "error": None,
                              "in": getattr(u, "prompt_tokens", 0) or 0, "out": getattr(u, "completion_tokens", 0) or 0})
        return resp


def final_config(model: str, reasoning: str):
    from rentus_operator import RunConfig
    cfg = RunConfig(prompt_version="v3", renter_guard=True, style_precheck=True, keep_reasoning_in_history=True,
                    model=model, base_url=os.environ.get("OPERATOR_BASE_URL") or "http://localhost:8000/v1",
                    api_key=os.environ.get("OPERATOR_API_KEY") or "EMPTY")
    if reasoning != "default":
        cfg = cfg.with_(reasoning=(reasoning == "on"))
    return cfg


def one_conversation(task: dict, cfg, calls: list, lock) -> dict:
    from openai import OpenAI
    from rentus_operator import run
    from rentus_env import RolloutSession, verify
    from rentus_env.backend import Backend
    import run_eval
    t0 = time.time()
    s = RolloutSession(task, backend=Backend())
    goal = run_eval.opening_goal(task, s)
    mine: list = []
    client = TimedClient(OpenAI(base_url=cfg.base_url, api_key=cfg.api_key, timeout=300, max_retries=0), mine, lock)
    status, final_text, err, retries = "error", "", None, 0
    try:
        res = run(s.world, goal, client=client, config=cfg.with_(max_steps=min(cfg.max_steps, task.get("max_turns", 30))),
                  backend=run_eval.operator_backend(s), run_id=f"load-{task['id']}-{uuid.uuid4().hex[:6]}")
        status, final_text = res.status, res.final_text
        retries = sum(1 for e in (res.events or []) if (e.get("type") if isinstance(e, dict) else None) == "retry")
    except Exception as e:  # noqa: BLE001 - a crashed conversation is counted, not fatal
        err = f"{type(e).__name__}: {e}"[:300]
        traceback.print_exc()
    r = verify(task, s.trace, s.final_state(), final_text)
    gates = s.gate_status()
    with lock:
        calls.extend(mine)
    return {"task_id": task["id"], "category": task.get("category"), "status": status, "error": err,
            "start": t0, "end": time.time(), "tool_calls": len(s.trace),
            "tool_errors": sum(1 for t in s.trace if not t.get("ok")), "model_calls": len(mine),
            "model_errors": sum(1 for c in mine if c["error"]), "loop_retries": retries,
            "passed": bool(r.get("passed")), "reward": r.get("reward"),
            "qualified": task.get("category") == "leasing" and bool(gates) and any(gates.values())}


def run_level(tasks, cfg, n: int, convs: int, base: str, key: str, label: str) -> dict:
    pool = itertools.cycle(tasks)
    todo = [next(pool) for _ in range(convs)]
    calls, lock = [], threading.Lock()
    snap0 = vm.scrape(base, key)
    sampler = vm.GaugeSampler(base, key, every=2.0).start()
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=n) as ex:
        convs_out = list(ex.map(lambda t: one_conversation(t, cfg, calls, lock), todo))
    wall = time.time() - t0
    gauges = sampler.stop()
    srv = vm.summarize(vm.delta(snap0, vm.scrape(base, key)))
    last_start = max(c["start"] for c in convs_out) - t0
    steady_done = sum(1 for c in convs_out if c["end"] - t0 <= max(last_start, 1e-6))
    ok_lat = [c["lat"] for c in calls if not c["error"]]
    leasing = [c for c in convs_out if c["category"] == "leasing"]
    per_hr = 3600 / wall
    qual_hr = sum(c["qualified"] for c in convs_out) * per_hr
    row = {
        "label": label, "concurrency": n, "conversations": convs, "wall_s": round(wall, 1),
        "conv_per_hr": round(len(convs_out) * per_hr, 1),
        "conv_per_hr_steady": round(steady_done * 3600 / last_start, 1) if last_start > 60 and steady_done else None,
        "conv_seconds_p50": round(vm.pct([c["end"] - c["start"] for c in convs_out], .5), 1),
        "tool_calls_per_s": round(sum(c["tool_calls"] for c in convs_out) / wall, 2),
        "model_calls": len(calls), "model_errors": sum(1 for c in calls if c["error"]),
        "loop_retries": sum(c["loop_retries"] for c in convs_out),
        "crashed_conversations": sum(1 for c in convs_out if c["error"]),
        "status_counts": {s: sum(1 for c in convs_out if c["status"] == s) for s in {c["status"] for c in convs_out}},
        "turn_p50_s": round(vm.pct(ok_lat, .5), 2) if ok_lat else None,
        "turn_p95_s": round(vm.pct(ok_lat, .95), 2) if ok_lat else None,
        "out_tok_per_s": round(sum(c.get("out", 0) for c in calls) / wall, 1),
        "in_tok_per_turn": round(sum(c.get("in", 0) for c in calls) / max(len(ok_lat), 1)),
        "pass_rate": round(sum(c["passed"] for c in convs_out) / len(convs_out), 3),
        "mean_reward": round(sum(c["reward"] or 0 for c in convs_out) / len(convs_out), 3),
        "leads_per_hr": round(len(leasing) * per_hr, 1),
        "qualified_leads_per_hr": round(qual_hr, 1),
        "usd_per_qualified_lead": round(GPU_USD_PER_HR / qual_hr, 4) if qual_hr else None,
        "server": srv, "gauges": gauges, "foreign_requests": max(0, srv["requests"] - len(calls)),
        "reader_backend": "model" if os.environ.get("READER_BASE_URL") else "fallback",
        "config": cfg.label(), "started": datetime.datetime.fromtimestamp(t0).astimezone().isoformat(timespec="seconds"),
    }
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--levels", default="1,8,32,64,128")
    ap.add_argument("--convs", type=int, help="conversations per level (default 2xN, min 4)")
    ap.add_argument("--tasks", default=str(REPO / "gym" / "tasks" / "v2" / "train.jsonl"))
    ap.add_argument("--category", help="only tasks of this category, e.g. leasing")
    ap.add_argument("--reasoning", choices=["on", "off", "default"], default="default")
    ap.add_argument("--reader", choices=["model", "fallback"], default="model")
    ap.add_argument("--model")
    a = ap.parse_args()

    import run_eval
    run_eval.load_env_file()
    if a.reader == "fallback":
        os.environ["READER_BASE_URL"] = ""
    base = os.environ.get("OPERATOR_BASE_URL") or "http://localhost:8000/v1"
    key = os.environ.get("OPERATOR_API_KEY") or "EMPTY"
    cfg = final_config(a.model or os.environ.get("OPERATOR_MODEL") or "nemotron-3.5-lightning", a.reasoning)
    tasks = [json.loads(l) for l in open(a.tasks)]
    if a.category:
        tasks = [t for t in tasks if t.get("category") == a.category]
    RESULTS.mkdir(exist_ok=True)
    for n in [int(x) for x in a.levels.split(",")]:
        row = run_level(tasks, cfg, n, a.convs or max(4, 2 * n), base, key, a.label)
        row["tasks_file"] = os.path.relpath(a.tasks, REPO)
        with open(RESULTS / "agent_load.jsonl", "a") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(json.dumps({k: v for k, v in row.items() if k not in ("server", "gauges")}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
