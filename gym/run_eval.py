"""Score a model config on a task split.

    python gym/run_eval.py --split heldout --run-name baseline                    # local loop, vLLM endpoint
    python gym/run_eval.py --split heldout --run-name baseline --via nemo         # NeMo Gym rollout collection
    python gym/run_eval.py --split heldout --run-name stub-smoke --stub           # no GPU: stub endpoint

Writes results/<run_name>/{summary.json, per_task.jsonl} (plus nemo/ artifacts for --via nemo).

Two runners, one scorer:
  local  gym/rentus_env RolloutSession + rentus_operator.run (the real operator harness: prompt,
         tool-description variant, verifier, reader, retries). Fast, and every RunConfig knob applies.
  nemo   NeMo Gym 0.6.0 `gym eval run` with our resources server (resources_servers/rentus) and the
         built-in simple_agent + vllm_model. The harness is NeMo's simple_agent, so the `verifier`
         knob does not apply there; prompt, tool descriptions and reader do.
Both call rentus_env.verify on the same trace format, so a task scores the same either way.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import tempfile
import sys
import threading
import time
import traceback
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
for p in (HERE, REPO / "tools", REPO / "operator"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from rentus_env import RolloutSession, verify  # noqa: E402
from rentus_env.backend import Backend  # noqa: E402

RESULTS = HERE / "results"
NEMO_VENV = HERE / ".venv-nemo"


# ------------------------------------------------------------------------------------ config
def load_env_file():
    f = REPO / ".env"
    if f.exists():
        for line in f.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def make_config(args):
    from rentus_operator import RunConfig
    cfg = RunConfig(prompt_version=args.prompt, tool_descriptions=args.tools, verifier=not args.no_verifier,
                    reader=not args.no_reader, max_steps=args.max_steps, temperature=args.temperature,
                    reasoning={"on": True, "off": False}.get(args.reasoning))
    if getattr(args, "api", "openai") == "anthropic":   # REFERENCE ONLY (frontier model), never the running system
        from rentus_operator.anthropic_client import DEFAULT_MODEL
        cfg = cfg.with_(api="anthropic", model=args.model or DEFAULT_MODEL, effort=args.effort,
                        base_url="https://opencode.ai/zen")
        return cfg
    if getattr(args, "api", "openai") == "claude_code":   # REFERENCE ONLY: frontier via the local Claude Code CLI
        from rentus_operator.claude_code import DEFAULT_MODEL, check_model
        return cfg.with_(api="claude_code", model=check_model(args.model or DEFAULT_MODEL), effort=args.effort,
                         base_url="claude-code-cli")
    if args.base_url:
        cfg = cfg.with_(base_url=args.base_url)
    if args.model:
        cfg = cfg.with_(model=args.model)
    return cfg


def probe_models(base_url: str, api_key: str = "EMPTY", timeout=3.0) -> list[str] | None:
    import urllib.request
    try:
        req = urllib.request.Request(base_url.rstrip("/") + "/models", headers={"Authorization": f"Bearer {api_key}"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return [m["id"] for m in json.load(r).get("data", [])]
    except Exception:  # noqa: BLE001
        return None


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def start_stub() -> str:
    import stub_endpoint
    port = free_port()
    threading.Thread(target=stub_endpoint.serve, args=(port,), daemon=True).start()
    for _ in range(50):
        if probe_models(f"http://127.0.0.1:{port}/v1"):
            break
        time.sleep(0.05)
    return f"http://127.0.0.1:{port}/v1"


TASKS_PATH = None


def load_tasks(split: str, ids: list[str] | None = None, limit: int | None = None,
               version: str = "v1", tasks_file: str | None = None) -> list[dict]:
    """v1 = gym/tasks/{split}.jsonl (the set every committed result used); v2 = gym/tasks/v2/{split}.jsonl.
    `tasks_file` (any JSONL of tasks, e.g. gym/tasks/llm_renter/demo_train.jsonl) overrides split/version."""
    path = Path(tasks_file) if tasks_file else \
        HERE / "tasks" / (f"{split}.jsonl" if version == "v1" else f"{version}/{split}.jsonl")
    tasks = [json.loads(l) for l in open(path)]
    global TASKS_PATH
    TASKS_PATH = path
    if ids:
        tasks = [t for t in tasks if t["id"] in ids]
    return tasks[:limit] if limit else tasks


def opening_goal(task: dict, s: RolloutSession):
    """What the operator is told at the start (same text in both runners)."""
    if task.get("owner_instruction"):
        return task["owner_instruction"]
    cp = next(iter(s.counterparts.values()))
    said = " ".join(l["say"] for l in cp.script if l.get("after") == "start")
    return {"thread_id": cp.thread_id, "channel": cp.channel, "renter_name": cp.name, "text": said}


def opening_text(goal) -> str:
    from rentus_operator.loop import _opening
    return _opening(goal)[0]


# ------------------------------------------------------------------------------------ local
OPERATOR_SEED: int | None = None   # set by evaluate() from --seed


class _SeededCompletions:
    def __init__(self, inner, seed: int):
        self._inner, self._seed = inner, seed

    def create(self, **kw):
        kw.setdefault("seed", self._seed)
        return self._inner.create(**kw)

    def __getattr__(self, k):
        return getattr(self._inner, k)


class SeededClient:
    """Wraps an OpenAI client so every chat.completions.create carries `seed` (vLLM: per-request sampler seed).
    Same seed + same inputs gives the same sample on one vLLM server, up to batch-level numeric noise."""

    def __init__(self, inner, seed: int):
        self._inner = inner
        self.chat = type("Chat", (), {})()
        self.chat.completions = _SeededCompletions(inner.chat.completions, seed)

    def __getattr__(self, k):
        return getattr(self._inner, k)


def _timed(s: RolloutSession, name, fn):
    """Record wall-clock start/end of every tool call on s.timing (reply-latency metric only)."""
    t0 = time.time()
    env = fn()
    s.__dict__.setdefault("timing", []).append({"tool": name, "t0": t0, "t1": time.time(), "i": len(s.trace) - 1})
    return env


def reply_latencies(s: RolloutSession, t_start: float) -> list[float]:
    """Seconds from each renter message arriving (the rollout start for the opening, the end of the
    send_message that drew a reply otherwise) to the next delivered send_message on that thread."""
    timing = {x["i"]: x for x in getattr(s, "timing", [])}
    arrivals, out = {}, []
    for tid in s.counterparts:
        arrivals[tid] = t_start
    for e in s.trace:
        if e.get("tool") != "send_message" or not e.get("ok"):
            continue
        tid, tm = (e.get("args") or {}).get("thread_id"), timing.get(e["i"])
        if tm is None or tid not in arrivals:
            continue
        if arrivals[tid] is not None:
            out.append(round(tm["t1"] - arrivals[tid], 2))
        arrivals[tid] = tm["t1"] if e.get("reply") else None
    return out


def operator_backend(s: RolloutSession):
    """A module-like backend for rentus_operator.run that routes every call through the session."""
    be = s.backend
    return SimpleNamespace(
        __name__=f"gym[{be.name}]",
        TOOLS=be.TOOLS,
        tool_schemas=be.tool_schemas,
        EventSink=getattr(be.mod, "EventSink", None),
        load=lambda patch=None: be.new_world(patch),
        call=lambda world, name, args, sink=None, actor="operator", call_id=None: _timed(s, name, lambda:
            s.call(name, args, **({} if be.name == "shim" else {"sink": sink, "actor": actor, "call_id": call_id}))),
    )


def run_local_task(task: dict, cfg, run_dir: Path) -> dict:
    from rentus_operator import run
    from rentus_operator.loop import make_client
    t0 = time.time()
    s = RolloutSession(task, backend=Backend())
    goal = opening_goal(task, s)
    client = make_client(cfg, timeout=180, max_retries=1)
    if OPERATOR_SEED is not None and cfg.api == "openai":
        client = SeededClient(client, OPERATOR_SEED)
    run_id = f"{task['id']}-{uuid.uuid4().hex[:6]}"
    status, final_text, steps, err, messages, decisions = "error", "", 0, None, [], None
    tcfg = cfg.with_(max_steps=min(cfg.max_steps, task.get("max_turns", 30)))
    try:
        if getattr(cfg, "router", False) and isinstance(goal, dict) and goal.get("thread_id"):
            # router on: event-driven; each renter message is routed, Lightning's turn ends on its send_message
            from rentus_operator.router import run_conversation
            res = run_conversation(s.world, goal, client=client, config=tcfg, backend=operator_backend(s), run_id=run_id)
            decisions = res.decisions
        else:
            res = run(s.world, goal, client=client, config=tcfg, backend=operator_backend(s), run_id=run_id)
        status, final_text, steps, messages = res.status, res.final_text, res.steps, res.messages
    except Exception as e:  # noqa: BLE001 - a crashed rollout scores what it did
        err = f"{type(e).__name__}: {e}"
        traceback.print_exc()
    r = verify(task, s.trace, s.final_state(), final_text)
    (run_dir / "transcripts").mkdir(exist_ok=True)
    (run_dir / "transcripts" / f"{task['id']}.json").write_text(json.dumps(
        {"task_id": task["id"], "status": status, "messages": messages, "trace": s.trace, "renter_view": s.transcript,
         **({"simulator": s.simulator_log()} if s.simulator_log() else {}),
         **({"router_decisions": decisions} if decisions is not None else {})},
        default=str, ensure_ascii=False, indent=1))
    out = {**r, "subcategory": task.get("subcategory"), "status": status, "steps": steps, "error": err,
           "final_text": final_text[:2000], "seconds": round(time.time() - t0, 2),
           "reply_latency_s": reply_latencies(s, t0)}
    if decisions is not None:
        out["router_decisions"] = [d["decision"] for d in decisions]
    if getattr(client, "calls", None) is not None:   # reference backend: per-task model cost and latency
        out["model_calls"] = len(client.calls)
        out["cost_usd"] = round(sum(c.get("cost_usd") or 0 for c in client.calls), 5)
        out["model_latency_s"] = round(sum(c.get("latency_s") or 0 for c in client.calls), 2)
        out["usage"] = {k: sum((c.get("usage") or {}).get(k) or 0 for c in client.calls)
                        for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")}
    if getattr(client, "meta", None):   # claude_code reference: which model actually answered, CLI version, auth source
        out["model_meta"] = {k: sorted(v) if isinstance(v, set) else v for k, v in client.meta.items()}
    return out


def run_local(tasks, cfg, run_dir: Path, workers: int) -> list[dict]:
    with ThreadPoolExecutor(max_workers=workers) as ex:
        out = list(ex.map(lambda t: run_local_task(t, cfg, run_dir), tasks))
    return out


# ------------------------------------------------------------------------------------ nemo
def responses_tools(chat_tools: list[dict]) -> list[dict]:
    out = []
    for t in chat_tools:
        f = t.get("function", t)
        out.append({"type": "function", "name": f["name"], "description": f.get("description", ""),
                    "parameters": f.get("parameters", {"type": "object", "properties": {}}), "strict": False})
    return out


def nemo_rows(tasks, cfg) -> list[dict]:
    from rentus_operator.config import load_prompt
    from rentus_operator import toolbox
    rows = []
    for t in tasks:
        s = RolloutSession(t, backend=Backend())
        tools = toolbox.tool_schemas(operator_backend(s), cfg.tool_descriptions, cfg.reader)
        facts = s.world_facts()
        sh = facts.get("showing_hours")
        if isinstance(sh, dict):
            facts["showing_hours"] = f"{sh.get('start')} to {sh.get('end')}"
        rows.append({"responses_create_params": {
                         "input": [{"role": "system", "content": load_prompt(cfg, facts)},
                                   {"role": "user", "content": opening_text(opening_goal(t, s))}],
                         "tools": responses_tools(tools), "temperature": cfg.temperature,
                         "max_output_tokens": cfg.max_tokens},
                     "task": t, "task_id": t["id"]})
    return rows


def run_nemo(tasks, cfg, run_dir: Path, workers: int) -> list[dict]:
    gym_bin = NEMO_VENV / "bin" / "gym"
    if not gym_bin.exists():
        raise SystemExit(f"NeMo Gym is not installed at {NEMO_VENV}; run gym/setup_nemo_gym.sh first")
    nd = run_dir / "nemo"
    nd.mkdir(parents=True, exist_ok=True)
    inp = nd / "input.jsonl"
    with open(inp, "w") as f:
        for row in nemo_rows(tasks, cfg):
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    out = nd / "rollouts.jsonl"
    for p in nd.glob("rollouts*"):
        p.unlink()
    env = {**os.environ, "PATH": f"{NEMO_VENV / 'bin'}:{os.environ.get('PATH', '')}", "VIRTUAL_ENV": str(NEMO_VENV),
           "MLFLOW_DISABLE_AGENT_HINT": "1"}
    # The vLLM key goes in a 0600 temp config (NeMo Gym merges every --config into the global config, where
    # `policy_api_key` is what --model-api-key sets), so it never appears in the process list or command.txt.
    key_fd, key_cfg = tempfile.mkstemp(prefix="rentus-nemo-key-", suffix=".yaml")
    with os.fdopen(key_fd, "w") as f:
        f.write(f"policy_api_key: {json.dumps(cfg.api_key or 'EMPTY')}\n")
    start = [str(gym_bin), "env", "start", "--config", "resources_servers/rentus/configs/rentus.yaml",
             "--config", key_cfg, "--model-type", "vllm_model", "--model", cfg.model, "--model-url", cfg.base_url]
    collect = [str(gym_bin), "eval", "run", "--no-serve", "--agent", "rentus_simple_agent",
               "--input", str(inp), "--output", str(out), "--num-repeats", "1", "--concurrency", str(workers),
               "--no-health-check"]
    (nd / "command.txt").write_text(" ".join(start).replace(key_cfg, "<0600 key config>") + "\n" + " ".join(collect) + "\n")
    t0 = time.time()
    env_log = open(nd / "gym_env.log", "w")
    server = subprocess.Popen(start, cwd=HERE, env=env, stdout=env_log, stderr=subprocess.STDOUT, start_new_session=True)
    try:
        deadline = time.time() + 900
        while True:
            text = (nd / "gym_env.log").read_text(errors="replace")
            if "servers ready!" in text:
                break
            if server.poll() is not None or "finished unexpectedly" in text or time.time() > deadline:
                raise SystemExit(f"gym env start failed; see {nd / 'gym_env.log'}\n{text[-3000:]}")
            time.sleep(2)
        with open(nd / "gym_eval.log", "w") as log:
            rc = subprocess.run(collect, cwd=HERE, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=3600).returncode
    finally:
        try:
            os.killpg(server.pid, signal.SIGTERM)
            server.wait(timeout=60)
        except Exception:  # noqa: BLE001
            try:
                os.killpg(server.pid, signal.SIGKILL)
            except Exception:  # noqa: BLE001
                pass
        env_log.close()
        Path(key_cfg).unlink(missing_ok=True)
    if rc != 0 or not out.exists():
        tail = (nd / "gym_eval.log").read_text()[-3000:]
        raise SystemExit(f"gym eval run failed (rc={rc}); see {nd / 'gym_eval.log'}\n{tail}")
    by_id = {t["id"]: t for t in tasks}
    results = []
    for line in open(out):
        r = json.loads(line)
        task = by_id.get(r.get("task_id")) or r.get("task")
        results.append({"task_id": task["id"], "category": task.get("category"), "subcategory": task.get("subcategory"),
                        "reward": r.get("reward", 0.0), "pass": bool(r.get("task_pass")),
                        "checks_passed": r.get("checks_passed"), "checks_total": r.get("checks_total"),
                        "checks": r.get("checks", []), "tool_calls": r.get("tool_calls"), "status": "nemo",
                        "steps": None, "error": None, "final_text": "", "seconds": None})
    seen = {r["task_id"] for r in results}
    for t in tasks:  # a rollout NeMo dropped counts as a zero
        if t["id"] not in seen:
            results.append({"task_id": t["id"], "category": t["category"], "subcategory": t.get("subcategory"),
                            "reward": 0.0, "pass": False, "checks_passed": 0, "checks_total": len(t["checks"]),
                            "checks": [], "tool_calls": 0, "status": "missing", "error": "no rollout"})
    print(f"nemo rollouts: {len(results)} in {time.time() - t0:.0f}s")
    return results


# ------------------------------------------------------------------------------------ summary
def summarize(results: list[dict], meta: dict) -> dict:
    n = len(results)
    cat = defaultdict(list)
    for r in results:
        cat[r["category"]].append(r)
    checks = defaultdict(lambda: [0, 0])
    for r in results:
        for c in r.get("checks") or []:
            checks[c["type"]][0] += c["pass"]
            checks[c["type"]][1] += 1
    return {**meta, "tasks": n,
            "pass_rate": round(sum(r["pass"] for r in results) / n, 4) if n else 0.0,
            "mean_reward": round(sum(r["reward"] for r in results) / n, 4) if n else 0.0,
            "by_category": {k: {"tasks": len(v), "pass_rate": round(sum(r["pass"] for r in v) / len(v), 4),
                                "mean_reward": round(sum(r["reward"] for r in v) / len(v), 4)} for k, v in sorted(cat.items())},
            "check_pass_rate": {k: round(a / b, 4) for k, (a, b) in sorted(checks.items())},
            # Amendment 1: reward without the checks a send_message guard makes impossible to fail, and the
            # attempted violations those guards stopped (refused drafts by rule)
            "mean_reward_earned": round(sum(r.get("reward_earned", r["reward"]) for r in results) / n, 4) if n else 0.0,
            "pass_rate_earned": round(sum(bool(r.get("pass_earned", r["pass"])) for r in results) / n, 4) if n else 0.0,
            "refused_by_rule": dict(sorted(_sum_counts(r.get("refused_by_rule") for r in results).items())),
            "errors": sum(1 for r in results if r.get("error"))}


def _sum_counts(dicts) -> dict:
    out: dict = defaultdict(int)
    for d in dicts:
        for k, v in (d or {}).items():
            out[k] += v
    return out


def sha256_file(path) -> str | None:
    import hashlib
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def tree_sha256(*rels: str) -> str:
    """sha256 over (path, file sha256) of every tracked-or-not .py/.md/.json file under the given repo paths."""
    import hashlib
    h = hashlib.sha256()
    for rel in rels:
        for f in sorted((REPO / rel).rglob("*")):
            if f.is_file() and f.suffix in (".py", ".md", ".json", ".jsonl", ".sh") and "__pycache__" not in f.parts:
                h.update(str(f.relative_to(REPO)).encode() + b"\0" + (sha256_file(f) or "").encode() + b"\n")
    return h.hexdigest()


def provenance(tasks_path) -> dict:
    """Exact inputs of a run (leakage review #8): commit, dirty flag, task file and code-tree hashes."""
    def git(*a):
        try:
            return subprocess.check_output(["git", *a], cwd=REPO, text=True, stderr=subprocess.DEVNULL).strip()
        except Exception:  # noqa: BLE001
            return None
    status = git("status", "--porcelain", "--", "gym/rentus_env", "gym/tasks", "tools", "operator", "reader/prompt.py",
                 "serving", "data/twins")
    return {"commit": git("rev-parse", "HEAD"), "describe": git("describe", "--always", "--dirty"),
            "dirty": bool(git("status", "--porcelain")), "dirty_frozen_paths": bool(status),
            "dirty_files": (status or "").splitlines()[:50],
            "tasks_path": str(tasks_path), "tasks_sha256": sha256_file(tasks_path),
            "code_sha256": {"gym/rentus_env": tree_sha256("gym/rentus_env"), "tools": tree_sha256("tools"),
                            "operator": tree_sha256("operator"), "serving": tree_sha256("serving")}}


def git_head() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=REPO, text=True).strip()
    except Exception:  # noqa: BLE001
        return None


def evaluate(args, cfg=None) -> dict:
    global OPERATOR_SEED
    load_env_file()
    OPERATOR_SEED = getattr(args, "seed", None)
    cfg = cfg or make_config(args)
    stub = args.stub
    if stub:
        cfg = cfg.with_(base_url=start_stub() if args.via == "local" else cfg.base_url, model="stub")
    if cfg.api == "anthropic" and not stub:
        from rentus_operator.anthropic_client import zen_api_key
        if not zen_api_key():
            raise SystemExit("api=anthropic needs OPENCODE_API_KEY (env, or the file named by $FRONTIER_ENV_FILE)")
    elif cfg.api == "claude_code" and not stub:
        from rentus_operator.claude_code import cli_path, sdk_version
        cli_path()
        if not sdk_version():
            raise SystemExit("api=claude_code needs claude-agent-sdk (gym/.venv-frontier; see scripts/frontier_ref.sh)")
    elif not stub:
        models = probe_models(cfg.base_url, cfg.api_key)
        if models is None:
            raise SystemExit(f"model endpoint {cfg.base_url} is not reachable; rerun with --stub to test plumbing")
        if not args.model and "OPERATOR_MODEL" not in os.environ and models:
            cfg = cfg.with_(model=models[0])
        from openai import OpenAI
        try:  # preflight: /models can answer while generation is down
            OpenAI(base_url=cfg.base_url, api_key=cfg.api_key, timeout=60, max_retries=1).chat.completions.create(
                model=cfg.model, messages=[{"role": "user", "content": "ping"}], max_tokens=1)
        except Exception as e:  # noqa: BLE001
            raise SystemExit(f"model endpoint {cfg.base_url} cannot generate: {type(e).__name__}: {e}")
    tasks = load_tasks(args.split, args.ids.split(",") if args.ids else None, args.limit,
                       getattr(args, "tasks_version", "v1"), getattr(args, "tasks_file", None))
    run_dir = RESULTS / args.run_name
    if run_dir.exists() and not args.keep:
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    stub_proc = None
    if stub and args.via == "nemo":
        port = free_port()
        stub_proc = subprocess.Popen([sys.executable, str(HERE / "stub_endpoint.py"), "--port", str(port)])
        time.sleep(0.5)
        cfg = cfg.with_(base_url=f"http://127.0.0.1:{port}/v1")
    t0 = time.time()
    try:
        results = (run_nemo if args.via == "nemo" else run_local)(tasks, cfg, run_dir, args.workers)
    finally:
        if stub_proc:
            stub_proc.terminate()
    order = {t["id"]: i for i, t in enumerate(tasks)}
    results.sort(key=lambda r: order.get(r["task_id"], 1e9))
    with open(run_dir / "per_task.jsonl", "w") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
    cfg_d = {k: v for k, v in asdict(cfg).items() if k != "api_key"}
    meta = {"run_name": args.run_name, "split": args.split, "tasks_version": getattr(args, "tasks_version", "v1"),
            "tasks_file": getattr(args, "tasks_file", None), "operator_seed": getattr(args, "seed", None),
            "via": args.via, "stub": stub,
            "model": cfg.model, "base_url": cfg.base_url, "config_label": cfg.label(), "config": cfg_d,
            "tools_backend": Backend().name, "git": git_head(), "provenance": provenance(TASKS_PATH),
            "nemo_gym_version": "0.6.0" if args.via == "nemo" else None,
            "started": datetime.fromtimestamp(t0, timezone.utc).isoformat(timespec="seconds"),
            "seconds": round(time.time() - t0, 1)}
    summary = summarize(results, meta)
    if cfg.api == "anthropic":
        from rentus_operator.anthropic_client import METER
        costs = [r.get("cost_usd") or 0 for r in results]
        secs = sorted(r.get("seconds") or 0 for r in results)
        summary["reference_model"] = {
            "note": "REFERENCE ONLY: frontier model on the same harness, not part of the running system",
            "provider": "OpenCode Zen (Anthropic Messages API)", "model": cfg.model, "effort": cfg.effort or "high",
            "run_cost_usd": round(sum(costs), 4), "cost_per_task_usd": round(sum(costs) / len(costs), 4) if costs else None,
            "task_seconds_p50": secs[len(secs) // 2] if secs else None, "task_seconds_mean": round(sum(secs) / len(secs), 1) if secs else None,
            "model_calls": sum(r.get("model_calls") or 0 for r in results), "process_spend": METER.snapshot()}
    if cfg.api == "claude_code":
        from rentus_operator.claude_code import BREAKER, cli_version, sdk_version
        costs = [r.get("cost_usd") or 0 for r in results]
        secs = sorted(r.get("seconds") or 0 for r in results)
        metas = [r.get("model_meta") or {} for r in results]
        summary["reference_model"] = {
            "note": "REFERENCE ONLY: frontier model on the same tools/prompt/scorer, not part of the running system",
            "provider": "local Claude Code CLI (owner's subscription login) via claude-agent-sdk, native tool use",
            "model": cfg.model, "effort": cfg.effort or "high", "cli_version": cli_version(), "sdk_version": sdk_version(),
            "response_models": sorted({m for x in metas for m in x.get("response_models", [])}),
            "model_usage_models": sorted({m for x in metas for m in x.get("model_usage", [])}),
            "api_key_sources": sorted({str(x.get("api_key_source")) for x in metas if x}),
            "notional_cost_usd": round(sum(costs), 4),
            "notional_cost_note": "Claude Code's list-price estimate; billed to the subscription, not per call",
            "task_seconds_p50": secs[len(secs) // 2] if secs else None,
            "task_seconds_mean": round(sum(secs) / len(secs), 1) if secs else None,
            "model_calls": sum(r.get("model_calls") or 0 for r in results),
            "statuses": {st: sum(1 for r in results if r.get("status") == st) for st in sorted({r.get("status") for r in results})},
            "rate_limit_breaker": {"tripped": BREAKER.tripped, "reason": BREAKER.reason}}
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    print(json.dumps({k: summary[k] for k in ("run_name", "via", "model", "config_label", "tasks", "pass_rate",
                                              "mean_reward", "by_category", "check_pass_rate", "errors")}, indent=1))
    return summary


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--split", default="heldout", choices=["train", "heldout"])
    ap.add_argument("--tasks-version", default="v1", choices=["v1", "v2"],
                    help="task set: v1 (all committed results) or v2 (docs/task-v2-changes.md)")
    ap.add_argument("--tasks-file", default=None, help="JSONL of tasks; overrides --split/--tasks-version")
    ap.add_argument("--seed", type=int, default=None,
                    help="operator sampling seed, sent as the OpenAI `seed` field on every model call (vLLM honours it)")
    ap.add_argument("--run-name", required=True)
    ap.add_argument("--via", default="local", choices=["local", "nemo"])
    ap.add_argument("--stub", action="store_true", help="use gym/stub_endpoint.py instead of a model (plumbing only)")
    ap.add_argument("--base-url", default=None, help="default: $OPERATOR_BASE_URL or http://localhost:8000/v1")
    ap.add_argument("--model", default=None, help="default: $OPERATOR_MODEL or the endpoint's first model")
    ap.add_argument("--prompt", default="v1")
    ap.add_argument("--tools", default="verbose", choices=["verbose", "terse"])
    ap.add_argument("--no-verifier", action="store_true")
    ap.add_argument("--no-reader", action="store_true")
    ap.add_argument("--reasoning", default="default", choices=["on", "off", "default"])
    ap.add_argument("--temperature", type=float, default=0.2)
    ap.add_argument("--api", default="openai", choices=["openai", "anthropic", "claude_code"],
                    help="anthropic / claude_code = REFERENCE-ONLY frontier backends (OpenCode Zen / local Claude Code "
                         "CLI), never the running system")
    ap.add_argument("--effort", default=None, help="api=anthropic: output_config.effort (default high)")
    ap.add_argument("--max-steps", type=int, default=30)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--ids", default=None, help="comma-separated task ids")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--keep", action="store_true", help="do not wipe an existing results dir")
    return ap


if __name__ == "__main__":
    evaluate(build_parser().parse_args())
