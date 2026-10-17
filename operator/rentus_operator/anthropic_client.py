"""Reference-only backend: an Anthropic Messages API client that looks like the OpenAI client the loop uses.

This exists for ONE purpose: running a frontier model (default `claude-opus-5-5` through OpenCode Zen)
on the exact same harness as Lightning, so docs/results.md can show where the local 30B + 0.6B system
lands against it. It is never part of the running system (organizers: the 33B limit covers only the
models loaded to run the app), and nothing in the default config touches it: RunConfig.api defaults
to "openai".

`AnthropicChatAdapter(...).chat.completions.create(**openai_kwargs)` translates an OpenAI
chat-completions request into a Messages API request (system -> top-level system, tool messages ->
tool_result blocks, OpenAI function schemas -> input_schema), sends it with the official `anthropic`
SDK, and returns an OpenAI-shaped dict that `loop.normalize` reads unchanged. So the loop, prompt v3,
tools, verifier, renter guard and style pre-check are the same code path as the Lightning runs.

Model-specific notes (Claude Opus 5.5): thinking is always on and is set with output_config.effort;
`temperature` is rejected, so the loop's temperature is dropped; thinking blocks must be passed back
unchanged, so the adapter keeps every assistant turn's raw content blocks and replays them when that
turn comes back in the history (the loop's history is append-only, which the API requires).

Spend: every call's cost (Zen's per-call `cost` field, else computed from usage at list price) goes
into a process-wide SpendMeter; once the cap is reached further calls raise BudgetExceeded, which
the loop records as a model_error. Usage and cost are appended to $FRONTIER_USAGE_LOG if set.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from types import SimpleNamespace

ZEN_BASE_URL = "https://opencode.ai/zen"          # the SDK appends /v1/messages
DEFAULT_MODEL = "claude-opus-5-5"

# USD per million tokens, list price (used only when the gateway returns no per-call cost)
PRICES = {
    "claude-opus-5-5": {"in": 4.00, "out": 20.00, "cache_read": 0.20, "cache_write": 5.00},
    "claude-fable-5-1": {"in": 10.00, "out": 50.00, "cache_read": 0.25, "cache_write": 12.50},
}


class BudgetExceeded(RuntimeError):
    pass


class SpendMeter:
    """Process-wide spend counter shared by every adapter (thread-safe)."""

    def __init__(self, cap_usd: float):
        self.cap_usd = cap_usd
        self.spent_usd = 0.0
        self.calls = 0
        self.usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0,
                      "cache_creation_input_tokens": 0}
        self.cost_source = {"gateway": 0, "computed": 0}
        self.lock = threading.Lock()

    def check(self):
        with self.lock:
            if self.spent_usd >= self.cap_usd:
                raise BudgetExceeded(f"frontier spend cap reached: ${self.spent_usd:.2f} of ${self.cap_usd:.2f}")

    def add(self, cost: float, usage: dict, source: str):
        with self.lock:
            self.spent_usd += cost
            self.calls += 1
            self.cost_source[source] += 1
            for k in self.usage:
                self.usage[k] += int(usage.get(k) or 0)

    def snapshot(self) -> dict:
        with self.lock:
            return {"spent_usd": round(self.spent_usd, 4), "cap_usd": self.cap_usd, "calls": self.calls,
                    "usage": dict(self.usage), "cost_source": dict(self.cost_source)}


METER = SpendMeter(float(os.environ.get("FRONTIER_BUDGET_USD", "25")))


def computed_cost(model: str, usage: dict) -> float:
    p = PRICES.get(model, PRICES[DEFAULT_MODEL])
    return ((usage.get("input_tokens") or 0) * p["in"] + (usage.get("output_tokens") or 0) * p["out"]
            + (usage.get("cache_read_input_tokens") or 0) * p["cache_read"]
            + (usage.get("cache_creation_input_tokens") or 0) * p["cache_write"]) / 1e6


def call_cost(model: str, data: dict) -> tuple[float, str]:
    """Zen's per-call cost if present (top-level `cost` or usage.cost), else list price from usage."""
    for v in (data.get("cost"), (data.get("usage") or {}).get("cost")):
        try:
            if v is not None:
                return float(v), "gateway"
        except (TypeError, ValueError):
            pass
    return computed_cost(model, data.get("usage") or {}), "computed"


def zen_api_key() -> str | None:
    """OPENCODE_API_KEY from the environment, else from the file named by $FRONTIER_ENV_FILE. Never printed."""
    key = os.environ.get("OPENCODE_API_KEY")
    f = os.environ.get("FRONTIER_ENV_FILE")
    if not key and f and Path(f).exists():
        for line in Path(f).read_text().splitlines():
            if line.startswith("OPENCODE_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
    return key or None


def make_sdk_client(api_key: str | None = None, base_url: str | None = None, timeout: float = 600, max_retries: int = 2):
    import anthropic
    return anthropic.Anthropic(api_key=api_key or zen_api_key(), base_url=base_url or ZEN_BASE_URL,
                               timeout=timeout, max_retries=max_retries)


def messages_create(sdk, meter: SpendMeter, log_path: str | None = None, **body) -> dict:
    """One Messages API call through the SDK; returns the response as a dict (keeps Zen's extra `cost`)."""
    meter.check()
    t0 = time.time()
    raw = sdk.messages.with_raw_response.create(**body)
    data = raw.json()
    cost, source = call_cost(body["model"], data)
    meter.add(cost, data.get("usage") or {}, source)
    data["_latency_s"] = round(time.time() - t0, 3)
    data["_cost_usd"] = cost
    log_path = log_path or os.environ.get("FRONTIER_USAGE_LOG")
    if log_path:
        with meter.lock, open(log_path, "a") as fh:
            fh.write(json.dumps({"t": time.time(), "model": data.get("model"), "latency_s": data["_latency_s"],
                                 "cost_usd": cost, "cost_source": source, "usage": data.get("usage"),
                                 "stop_reason": data.get("stop_reason")}) + "\n")
    return data


# --------------------------------------------------------------------------- OpenAI -> Anthropic

def _tools(openai_tools: list[dict] | None) -> list[dict]:
    out = []
    for t in openai_tools or []:
        f = t.get("function", t)
        out.append({"name": f["name"], "description": f.get("description", ""),
                    "input_schema": f.get("parameters") or {"type": "object", "properties": {}}})
    return out


def _args(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    try:
        v = json.loads(raw or "{}")
        return v if isinstance(v, dict) else {"_raw": v}
    except json.JSONDecodeError:
        return {"_raw": raw}


class _Completions:
    def __init__(self, adapter: "AnthropicChatAdapter"):
        self.a = adapter

    def create(self, **kw) -> dict:
        return self.a._create(**kw)


class AnthropicChatAdapter:
    """OpenAI-client look-alike: `.chat.completions.create(**kw)` -> OpenAI-shaped dict."""

    def __init__(self, model: str = DEFAULT_MODEL, effort: str | None = "high", api_key: str | None = None,
                 base_url: str | None = None, max_tokens: int = 16000, meter: SpendMeter | None = None,
                 sdk=None, cache: bool = True):
        self.model, self.effort, self.max_tokens, self.cache = model, effort, max_tokens, cache
        self.meter = meter or METER
        self.sdk = sdk or make_sdk_client(api_key, base_url)
        self.chat = SimpleNamespace(completions=_Completions(self))
        self._raw: dict[tuple, list[dict]] = {}     # assistant turn key -> raw content blocks (with thinking)
        self.calls: list[dict] = []                 # per-call latency / cost / usage, for the run summary

    @staticmethod
    def _key(content: str, tool_ids) -> tuple:
        return ((content or "").strip(), tuple(tool_ids))

    def to_messages(self, messages: list[dict]) -> tuple[list[dict], list[dict]]:
        system, out = [], []

        def push(role, blocks):
            if out and out[-1]["role"] == role:
                out[-1]["content"].extend(blocks)
            else:
                out.append({"role": role, "content": list(blocks)})

        for m in messages:
            role = m["role"]
            if role == "system":
                system.append({"type": "text", "text": m["content"]})
            elif role == "user":
                push("user", [{"type": "text", "text": m["content"] or "(empty)"}])
            elif role == "tool":
                push("user", [{"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": m["content"]}])
            elif role == "assistant":
                calls = m.get("tool_calls") or []
                raw = self._raw.get(self._key(m.get("content"), [c["id"] for c in calls]))
                if raw is None:  # a turn this adapter did not produce (e.g. passed-in history)
                    raw = ([{"type": "text", "text": m["content"]}] if (m.get("content") or "").strip() else [])
                    raw += [{"type": "tool_use", "id": c["id"], "name": c["function"]["name"],
                             "input": _args(c["function"]["arguments"])} for c in calls]
                push("assistant", raw or [{"type": "text", "text": "(no output)"}])
        if self.cache and system:
            system[-1] = {**system[-1], "cache_control": {"type": "ephemeral"}}
        if self.cache and out and out[-1]["role"] == "user":
            last = out[-1]["content"][-1]
            out[-1]["content"][-1] = {**last, "cache_control": {"type": "ephemeral"}}
        return system, out

    def _create(self, model=None, messages=None, tools=None, tool_choice="auto", temperature=None,
                max_tokens=None, extra_body=None, **_ignored) -> dict:
        system, msgs = self.to_messages(messages or [])
        body = {"model": self.model, "max_tokens": max(self.max_tokens, max_tokens or 0), "messages": msgs}
        if system:
            body["system"] = system
        if tools:
            body["tools"] = _tools(tools)
            body["tool_choice"] = {"type": "auto"}       # forced tool choice is a 400 on Opus 5.5
        body["thinking"] = {"type": "adaptive", "display": "summarized"}   # readable transcripts, same cost
        if self.effort:
            body["output_config"] = {"effort": self.effort}
        # temperature and chat_template_kwargs (vLLM) do not apply: Opus 5.5 rejects sampling params
        data = messages_create(self.sdk, self.meter, **body)
        blocks = data.get("content") or []
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()
        thinking = "\n".join(b.get("thinking", "") for b in blocks if b.get("type") == "thinking").strip()
        calls = [{"id": b["id"], "type": "function",
                  "function": {"name": b["name"], "arguments": json.dumps(b.get("input") or {}, ensure_ascii=False)}}
                 for b in blocks if b.get("type") == "tool_use"]
        self._raw[self._key(text, [c["id"] for c in calls])] = blocks
        self.calls.append({"latency_s": data.get("_latency_s"), "cost_usd": data.get("_cost_usd"),
                           "usage": data.get("usage"), "stop_reason": data.get("stop_reason")})
        finish = {"tool_use": "tool_calls", "end_turn": "stop", "max_tokens": "length"}.get(
            data.get("stop_reason"), data.get("stop_reason"))
        msg = {"role": "assistant", "content": text, "tool_calls": calls or None}
        if thinking:
            msg["reasoning_content"] = thinking
        return {"id": data.get("id"), "model": data.get("model"),
                "choices": [{"index": 0, "message": msg, "finish_reason": finish}],
                "usage": data.get("usage"), "cost": data.get("_cost_usd")}
