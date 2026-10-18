"""Reference-only backend: a frontier model through the owner's local Claude Code install (`claude` CLI,
logged in to the owner's subscription; owner-approved 2026-10-18). Replaces the paid OpenCode Zen path
(anthropic_client.py) for the frontier comparison. Never part of the running system: nothing in the
default config touches it (RunConfig.api defaults to "openai").

Two entry points:

  print_json(system, user, model, effort)   one headless `claude -p` call with no tools (reader reference)
  run_operator(...)                          the operator task, with NATIVE tool use: the Claude Agent SDK
                                             (claude-agent-sdk 0.2.163, released 2026-09-30) drives the
                                             local CLI, and our sandbox tools are in-process SDK MCP tools
                                             whose handlers go through the same _Runner.execute path as
                                             the Lightning runs (verifier, style pre-check, loop guard),
                                             so every call still lands in rentus_tools via the session.

Only truly frontier models are allowed (FRONTIER_MODELS). Auth is the CLI's own login: ANTHROPIC_API_KEY,
ANTHROPIC_AUTH_TOKEN and ANTHROPIC_BASE_URL are removed from the child environment so nothing is billed
to an API key, and the parent Claude Code session variables are removed so the child is a clean session.
No user/project settings, CLAUDE.md, hooks, plugins or built-in tools are loaded (setting_sources=[],
tools=[], strict MCP config). Rate limits: back off 60/120/240 s, then trip a process-wide breaker so the
rest of the run fails fast instead of looping on errors.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path

FRONTIER_MODELS = ("claude-opus-5-5", "claude-fable-5-1")
DEFAULT_MODEL = "claude-opus-5-5"
BACKOFF_S = (60, 120, 240)
_STRIP = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "CLAUDECODE")
_KEEP_CLAUDE = ("CLAUDE_CONFIG_DIR", "CLAUDE_CLI")


class RateLimited(RuntimeError):
    pass


class Breaker:
    """Process-wide: once rate limits outlast the backoff, every later call fails fast."""

    def __init__(self):
        self.tripped = False
        self.reason = ""
        self.lock = threading.Lock()

    def trip(self, why: str):
        with self.lock:
            self.tripped, self.reason = True, why[:300]

    def check(self):
        if self.tripped:
            raise RateLimited(f"breaker open: {self.reason}")


BREAKER = Breaker()


def cli_path() -> str:
    p = os.environ.get("CLAUDE_CLI") or shutil.which("claude") or str(Path.home() / ".local/bin/claude")
    if not Path(p).exists():
        raise SystemExit("claude CLI not found (set CLAUDE_CLI); the frontier reference needs a logged-in Claude Code")
    return p


def check_model(model: str | None) -> str:
    model = model or DEFAULT_MODEL
    if model not in FRONTIER_MODELS:
        raise SystemExit(f"frontier reference allows only {FRONTIER_MODELS}, got {model!r}")
    return model


def child_env() -> dict:
    """The environment for the CLI: no API keys (subscription login only), no parent-session plumbing."""
    env = {k: v for k, v in os.environ.items()
           if k not in _STRIP and not (k.startswith("CLAUDE") and k not in _KEEP_CLAUDE)}
    env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"   # no side calls (e.g. a small model titling the session)
    return env


def sanitize_process_env():
    """The Agent SDK builds the child env from os.environ, so strip it in this (reference-only) process."""
    keep = child_env()
    for k in list(os.environ):
        if k not in keep:
            os.environ.pop(k)
    os.environ.update(keep)


def cli_version() -> str:
    try:
        return subprocess.run([cli_path(), "--version"], capture_output=True, text=True, timeout=30,
                              env=child_env()).stdout.strip()
    except Exception as e:  # noqa: BLE001
        return f"unknown ({type(e).__name__})"


def sdk_version() -> str | None:
    try:
        import claude_agent_sdk
        return claude_agent_sdk.__version__
    except ImportError:
        return None


def _is_rate_limit(status, text: str) -> bool:
    t = (text or "").lower()
    return status == 429 or any(s in t for s in ("rate limit", "rate_limit", "usage limit", "overloaded", "429"))


_WORKDIR = None


def workdir() -> str:
    """An empty cwd, so no CLAUDE.md or project settings are discovered."""
    global _WORKDIR
    if _WORKDIR is None:
        _WORKDIR = tempfile.mkdtemp(prefix="rentus-frontier-")
    return _WORKDIR


# --------------------------------------------------------------------------- reader: one headless call

def print_json(system: str, user: str, model: str, effort: str | None = "medium", timeout: float = 300) -> dict:
    """`claude -p` with no tools; returns the CLI's JSON result (result text, usage, modelUsage, cost).
    Backs off on rate limits, raises RateLimited when the backoff is exhausted (and trips the breaker)."""
    model = check_model(model)
    cmd = [cli_path(), "-p", "--model", model, "--output-format", "json", "--system-prompt", system,
           "--tools", "", "--setting-sources", "", "--strict-mcp-config", "--no-session-persistence"]
    if effort:
        cmd += ["--effort", effort]
    last = ""
    for attempt in range(len(BACKOFF_S) + 1):
        BREAKER.check()
        t0 = time.time()
        p = subprocess.run(cmd, input=user, capture_output=True, text=True, timeout=timeout,
                           env=child_env(), cwd=workdir())
        try:
            data = json.loads(p.stdout)
        except json.JSONDecodeError:
            data = {"is_error": True, "result": (p.stdout or p.stderr)[-500:]}
        data["_latency_s"] = round(time.time() - t0, 3)
        if not data.get("is_error") and p.returncode == 0:
            return data
        last = f"{data.get('api_error_status')}: {str(data.get('result') or data.get('errors') or p.stderr)[:300]}"
        if not _is_rate_limit(data.get("api_error_status"), last):
            raise RuntimeError(f"claude -p failed: {last}")
        if attempt < len(BACKOFF_S):
            time.sleep(BACKOFF_S[attempt])
    BREAKER.trip(last)
    raise RateLimited(last)


# --------------------------------------------------------------------------- operator: native tool use

class AgentClient:
    """Stands in for the model client in run_local_task: only .calls (per model call) and .meta are read."""

    def __init__(self, model: str, effort: str | None):
        self.model, self.effort = check_model(model), effort or "high"
        self.calls: list[dict] = []
        self.meta: dict = {}
        self.chat = None   # not an OpenAI client; rentus_operator.loop.run dispatches on cfg.api


PREFIX = "mcp__rentus__"


def run_operator(world, goal_or_inbound, client: AgentClient, cfg, sink, be, run_id: str, sleep):
    """One task through Claude Code. Mirrors loop.run: same system prompt, opening, tools and _Runner.execute
    (verifier, style pre-check, loop guard); the renter guard and the verifier self-check bounce the final
    text back as a new user turn in the same session, exactly as the loop appends them."""
    from . import toolbox
    from . import verifier as V
    from .config import load_prompt
    from .loop import RunResult, _opening, _Runner, renter_guard_feedback, renter_unanswered

    R = _Runner(world, client, cfg, sink, be, sleep)
    st = toolbox.state(world)
    pol = st.get("policy") or {}
    facts = {"today": toolbox.today(world), "spend_limit_usd": pol.get("spend_limit_usd"),
             "showing_hours": pol.get("showing_hours")}
    system = load_prompt(cfg, facts)
    opening, who = _opening(goal_or_inbound)
    messages = [{"role": "system", "content": system}, {"role": "user", "content": opening}]
    if who == "owner":
        R.emit("owner_message", "owner", {"text": opening[len("Owner: "):]})
    before = toolbox.snapshot(world)
    renter_thread = goal_or_inbound.get("thread_id") if (who is None and isinstance(goal_or_inbound, dict)) else None

    state = {"status": "max_steps", "final_text": "", "checks": [], "steps": 0, "over": False}
    last_err = None
    for attempt in range(len(BACKOFF_S) + 1):
        try:
            BREAKER.check()
            asyncio.run(_drive(R, cfg, client, system, opening, messages, state, before, renter_thread,
                               V, toolbox, renter_guard_feedback, renter_unanswered))
            last_err = None
            break
        except RateLimited as e:
            last_err = f"RateLimited: {e}"
            if state["steps"] > 0 or BREAKER.tripped:
                break
            if attempt < len(BACKOFF_S):
                time.sleep(BACKOFF_S[attempt])
            else:
                BREAKER.trip(str(e))
        except Exception as e:  # noqa: BLE001 - CLI / transport errors: scored as they are, never looped
            last_err = f"{type(e).__name__}: {str(e)[:300]}"
            break
    if last_err is not None:
        # never reached the model -> model_error (the rerun rule may retry it); otherwise scored as it is
        state["status"] = "model_error" if state["steps"] == 0 else "mid_rollout_error"
        state["final_text"] = state["final_text"] or last_err
        R.emit("retry", "verifier", {"tool": "<model>", "attempt": 1, "error": last_err})

    if state["status"] == "max_steps" and cfg.verifier:
        R._force_escalate("__max_steps__", "run", {}, "",
                          reason=f"step limit {cfg.max_steps} reached before the task finished")
    return RunResult(run_id=run_id, status=state["status"], final_text=state["final_text"], steps=state["steps"],
                     tool_calls=R.n_calls, messages=messages, ledger=R.ledger, self_check=state["checks"],
                     escalations=R.escalations, events=list(getattr(sink, "events", []) or []), config=cfg.label())


async def _drive(R, cfg, client, system, opening, messages, state, before, renter_thread,
                 V, toolbox, renter_guard_feedback, renter_unanswered):
    from claude_agent_sdk import (AssistantMessage, ClaudeAgentOptions, ClaudeSDKClient, RateLimitEvent,
                                  ResultMessage, SystemMessage, TextBlock, ThinkingBlock, ToolAnnotations,
                                  ToolResultBlock, ToolUseBlock, UserMessage, create_sdk_mcp_server, tool)
    sanitize_process_env()

    def make_handler(name):
        async def handler(args):
            if state["over"]:   # a model call past max_steps: the loop would never have made it, so nothing runs
                return {"content": [{"type": "text", "text": json.dumps({"ok": False, "error": {
                    "code": "POLICY_BLOCKED", "message": "step limit reached", "retryable": False}})}]}
            # synchronous on purpose: parallel tool_use blocks run one after another, in order, like the loop
            out = R.execute({"id": f"cc_{uuid.uuid4().hex[:8]}", "type": "function",
                             "function": {"name": name, "arguments": json.dumps(args or {}, ensure_ascii=False)}})
            return {"content": [{"type": "text", "text": json.dumps(out, default=str, ensure_ascii=False)}]}
        return handler

    sdk_tools = []
    for t in R.tools:
        f = t.get("function", t)
        sdk_tools.append(tool(f["name"], f.get("description", ""),
                              f.get("parameters") or {"type": "object", "properties": {}},
                              annotations=ToolAnnotations(maxResultSizeChars=500_000))(make_handler(f["name"])))
    server = create_sdk_mcp_server("rentus", tools=sdk_tools)
    names = [PREFIX + (t.get("function", t))["name"] for t in R.tools]
    opts = ClaudeAgentOptions(model=client.model, effort=client.effort, cli_path=cli_path(), tools=[],
                              mcp_servers={"rentus": server}, allowed_tools=names, strict_mcp_config=True,
                              system_prompt=system, setting_sources=[], max_turns=cfg.max_steps,
                              permission_mode="dontAsk", cwd=workdir(),
                              env={"CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"})
    seen_ids: set = set()
    by_id: dict = {}

    async def consume(c) -> "ResultMessage | None":
        result = None
        async for m in c.receive_response():
            if isinstance(m, SystemMessage) and m.subtype == "init":
                client.meta.update({"init_model": m.data.get("model"), "cli_version": m.data.get("claude_code_version"),
                                    "api_key_source": m.data.get("apiKeySource"),
                                    "tools": [x.removeprefix(PREFIX) for x in m.data.get("tools") or []]})
            elif isinstance(m, RateLimitEvent):
                if getattr(m.rate_limit_info, "status", None) == "rejected":
                    raise RateLimited(f"rate limit rejected ({getattr(m.rate_limit_info, 'rate_limit_type', '?')})")
            elif isinstance(m, AssistantMessage) and m.parent_tool_use_id is None:
                if m.error:
                    if _is_rate_limit(None, str(m.error)):
                        raise RateLimited(str(m.error))
                mid = m.message_id or m.uuid or uuid.uuid4().hex
                client.meta.setdefault("response_models", set()).add(m.model)
                if mid not in seen_ids and state["steps"] >= cfg.max_steps:
                    # call max_steps + 1: the loop stops before it, so it is dropped and its tools never run
                    seen_ids.add(mid)
                    state["over"] = True
                    await c.interrupt()
                    continue
                if mid in seen_ids and state["over"] and mid not in by_id:
                    continue
                if mid not in seen_ids:
                    seen_ids.add(mid)
                    state["steps"] += 1
                    am = {"role": "assistant", "content": "", "_message_id": mid}
                    messages.append(am)
                    by_id[mid] = am
                    client.calls.append({"latency_s": None, "cost_usd": None, "usage": dict(m.usage or {}),
                                         "stop_reason": m.stop_reason})
                else:
                    client.calls[-1]["usage"] = dict(m.usage or client.calls[-1]["usage"])
                am = by_id[mid]
                for b in m.content:
                    if isinstance(b, TextBlock):
                        am["content"] = (am["content"] + "\n" + b.text).strip()
                    elif isinstance(b, ThinkingBlock):
                        am["reasoning_content"] = ((am.get("reasoning_content") or "") + "\n" + b.thinking).strip()
                    elif isinstance(b, ToolUseBlock):
                        am.setdefault("tool_calls", []).append(
                            {"id": b.id, "type": "function", "function": {"name": b.name.removeprefix(PREFIX),
                             "arguments": json.dumps(b.input, ensure_ascii=False)}})
                R.emit("model_message", "operator", {"text": am["content"], "step": state["steps"],
                                                     "tool_calls": [x["function"]["name"] for x in am.get("tool_calls", [])]})
            elif isinstance(m, UserMessage) and isinstance(m.content, list) and not state["over"]:
                for b in m.content:
                    if isinstance(b, ToolResultBlock):
                        txt = b.content if isinstance(b.content, str) else "".join(
                            x.get("text", "") for x in (b.content or []) if isinstance(x, dict))
                        messages.append({"role": "tool", "tool_call_id": b.tool_use_id, "content": txt})
            elif isinstance(m, ResultMessage):
                result = m
        return result

    async with ClaudeSDKClient(options=opts) as c:
        prompt, guard_left, rounds_left = opening, (cfg.renter_guard_rounds if cfg.renter_guard else 0), cfg.self_check_rounds
        while True:
            await c.query(prompt)
            res = await consume(c)
            if res is not None:
                if client.calls:
                    client.calls[-1]["cost_usd"] = (client.calls[-1]["cost_usd"] or 0) + (res.total_cost_usd or 0)
                    client.calls[-1]["latency_s"] = round((res.duration_ms or 0) / 1000, 3)
                client.meta.setdefault("model_usage", set()).update((res.model_usage or {}).keys())
            if state["over"]:
                state["status"] = "max_steps"
                return
            if res is None or res.is_error:
                why = f"{getattr(res, 'subtype', 'no result')}: {getattr(res, 'errors', None) or getattr(res, 'result', '')}"
                if res is not None and res.subtype == "error_max_turns":
                    state["status"] = "max_steps"
                    return
                if _is_rate_limit(getattr(res, "api_error_status", None), why):
                    raise RateLimited(why)
                if state["steps"] >= cfg.max_steps:
                    state["status"] = "max_steps"
                    return
                raise RuntimeError(why[:300])
            if state["steps"] >= cfg.max_steps and messages[-1]["role"] == "tool":
                state["status"] = "max_steps"
                return
            state["final_text"] = (res.result or "").strip()
            if guard_left > 0 and renter_unanswered(R.world, renter_thread):
                guard_left -= 1
                R.emit("verifier", "harness", {"stage": "renter-guard", "ok": False, "thread_id": renter_thread,
                                               "problems": ["run ended on plain text with the renter unanswered"]})
                prompt = renter_guard_feedback(renter_thread)
                messages.append({"role": "user", "content": prompt})
                continue
            if not cfg.verifier:
                state["status"] = "done"
                return
            state["checks"] = V.self_check(before, toolbox.snapshot(R.world), R.ledger, state["final_text"])
            R.emit("verifier", "verifier", {"stage": "self-check", "ok": not state["checks"], "problems": state["checks"]})
            if not state["checks"]:
                state["status"] = "done"
                return
            if rounds_left <= 0:
                state["status"] = "done_unverified"
                return
            rounds_left -= 1
            prompt = ("[verifier] Your summary does not match the world state: " + "; ".join(state["checks"])
                      + ". Do the missing actions now with tools, or correct the summary so it only states what "
                      "actually happened.")
            messages.append({"role": "user", "content": prompt})
