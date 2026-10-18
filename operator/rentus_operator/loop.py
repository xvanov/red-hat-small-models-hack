"""The operator's agent loop over an OpenAI-compatible chat-completions endpoint.

run(world, goal_or_inbound, client, model, max_steps) drives one task: the model
talks and calls tools in the same turn; every call goes through the verifier
(unless RunConfig.verifier is False); events go to the tools package EventSink.
"""
from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass, field

from . import toolbox
from . import verifier as V
from .config import RunConfig, load_prompt


@dataclass
class RunResult:
    run_id: str
    status: str                     # done | done_unverified | max_steps | model_error
    final_text: str
    steps: int
    tool_calls: int
    messages: list[dict]
    ledger: list[dict]
    self_check: list[str] = field(default_factory=list)
    escalations: list[str] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    config: str = ""


# --------------------------------------------------------------------------- response parsing

THINK = re.compile(r"<think>.*?</think>", re.S)
INLINE_JSON_CALL = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.S)
INLINE_XML_CALL = re.compile(r"<tool_call>\s*<function=([\w.-]+)>(.*?)</function>\s*</tool_call>", re.S)
XML_PARAM = re.compile(r"<parameter=([\w.-]+)>\s*(.*?)\s*</parameter>", re.S)


def _as_dict(obj) -> dict:
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    for m in ("model_dump", "dict"):
        f = getattr(obj, m, None)
        if callable(f):
            try:
                return f()
            except TypeError:
                pass
    return dict(vars(obj))


def split_reasoning(content: str | None, msg: dict) -> tuple[str, str]:
    """Return (visible content, reasoning). Handles a reasoning parser (separate
    field) and raw <think> blocks left in the content."""
    reasoning = msg.get("reasoning_content") or msg.get("reasoning") or ""
    text = content or ""
    inline = "".join(m.group(0) for m in THINK.finditer(text))
    text = THINK.sub("", text)
    if "</think>" in text:  # opening tag eaten by the template
        head, _, text = text.partition("</think>")
        inline += head
    return text.strip(), (reasoning + "\n" + re.sub(r"</?think>", "", inline)).strip()


def inline_tool_calls(text: str) -> tuple[list[dict], str]:
    """Tool calls the server's parser missed and left in the content."""
    calls = []
    for m in INLINE_JSON_CALL.finditer(text):
        try:
            obj = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "name" in obj:
            args = obj.get("arguments", obj.get("parameters", {}))
            calls.append({"name": obj["name"], "arguments": args if isinstance(args, str) else json.dumps(args)})
    for m in INLINE_XML_CALL.finditer(text):
        args = {}
        for k, v in XML_PARAM.findall(m.group(2)):
            try:
                args[k] = json.loads(v)
            except json.JSONDecodeError:
                args[k] = v
        calls.append({"name": m.group(1), "arguments": json.dumps(args)})
    if calls:
        text = INLINE_XML_CALL.sub("", INLINE_JSON_CALL.sub("", text)).strip()
    return [{"id": f"inline_{uuid.uuid4().hex[:8]}", "type": "function", "function": c} for c in calls], text


def normalize(resp) -> dict:
    r = _as_dict(resp)
    choices = r.get("choices") or []
    msg = _as_dict(choices[0].get("message") if isinstance(choices[0], dict) else choices[0].message) if choices else {}
    content, reasoning = split_reasoning(msg.get("content"), msg)
    calls = []
    for i, tc in enumerate(msg.get("tool_calls") or []):
        tc = _as_dict(tc)
        fn = _as_dict(tc.get("function"))
        calls.append({"id": tc.get("id") or f"call_{i}_{uuid.uuid4().hex[:6]}", "type": "function",
                      "function": {"name": fn.get("name", ""), "arguments": fn.get("arguments", "")}})
    return {"content": content, "reasoning": reasoning, "tool_calls": calls,
            "finish_reason": choices[0].get("finish_reason") if choices and isinstance(choices[0], dict) else None}


# --------------------------------------------------------------------------- the loop

def _opening(goal) -> tuple[str, str | None]:
    if isinstance(goal, str):
        return f"Owner: {goal}", "owner"
    g = dict(goal)
    if g.get("router_note"):   # router on: the router's note (reader parse, what it recorded) opens the turn
        return g["router_note"], None
    if g.get("owner_instruction"):
        return f"Owner: {g['owner_instruction']}", "owner"
    if g.get("thread_id"):
        who = g.get("renter_name") or "a renter"
        said = f': "{g["text"]}"' if g.get("text") else ""
        return (f"New renter message on {g.get('channel', 'a channel')} thread {g['thread_id']} from {who}{said}. "
                "Read the thread and handle it."), None
    return json.dumps(g), None


def _thread_messages(st: dict, thread_id: str) -> list[dict]:
    threads = list(st.get("threads", []) or [])
    for ch in (st.get("channels") or {}).values():
        if isinstance(ch, dict):
            threads += [t for t in ch.get("threads", []) or [] if isinstance(t, dict)]
    if isinstance(st.get("threads"), dict):
        threads = list(st["threads"].values())
    for t in threads:
        if isinstance(t, dict) and t.get("thread_id") == thread_id:
            return list(t.get("messages", []) or [])
    return []


def renter_unanswered(world, thread_id: str | None) -> bool:
    """True when the thread's last message is from the renter (nothing the operator sent answers it)."""
    if not thread_id:
        return False
    msgs = _thread_messages(toolbox.state(world), thread_id)
    return bool(msgs) and msgs[-1].get("from") not in ("operator", "owner")


def renter_guard_feedback(thread_id: str) -> str:
    return (f"[harness] Plain text is not delivered: the renter on thread {thread_id} never sees it, and their last "
            f"message is still unanswered. Send your reply now with send_message (thread_id \"{thread_id}\"), "
            "keeping every style rule. Finish with plain text, a short summary for the owner, only after the renter "
            "has your reply.")


class _Runner:
    def __init__(self, world, client, cfg: RunConfig, sink, be, sleep):
        self.world, self.client, self.cfg, self.sink, self.be, self.sleep = world, client, cfg, sink, be, sleep
        self.tools = toolbox.tool_schemas(be, cfg.tool_descriptions, cfg.reader)
        self.checker = V.CallChecker(self.tools)
        self.guard = V.LoopGuard(cfg.loop_guard_repeats)
        self.ledger: list[dict] = []
        self.escalations: list[str] = []
        self.tried_channels: dict[str, set[str]] = {}
        self.n_calls = 0

    def emit(self, type, actor, data):
        toolbox.emit(self.sink, type, actor, data)

    # ---- one tool call -> the content of its tool message
    def execute(self, tc: dict) -> dict:
        name, raw = tc["function"]["name"], tc["function"]["arguments"]
        if not self.cfg.verifier:
            try:
                args = raw if isinstance(raw, dict) else json.loads(raw or "{}")
            except json.JSONDecodeError as e:
                return {"ok": False, "error": {"code": "INVALID_ARGS", "message": f"arguments are not JSON: {e.msg}",
                                               "retryable": True}}
            return self._call(name, args, tc["id"])

        chk = self.checker.check(name, raw)
        if not chk.ok:
            self.emit("verifier", "verifier", {"stage": "pre-call", "tool": name, "ok": False,
                                               "problems": chk.problems, "call_id": tc["id"]})
            sig = V.signature(name, chk.args if chk.args is not None else raw)
            if self.guard.failed(sig):
                return self._force_escalate(sig, name, chk.args, "; ".join(chk.problems))
            return chk.feedback()
        if chk.repaired:
            self.emit("verifier", "verifier", {"stage": "pre-call", "tool": name, "ok": True,
                                               "repaired": chk.repaired, "call_id": tc["id"]})
        args = chk.args
        sig = V.signature(name, args)
        if self.cfg.style_precheck and name == "send_message":
            fb = V.style_precheck(args)
            if fb is not None:
                self.emit("verifier", "verifier", {"stage": "pre-call", "tool": name, "ok": False,
                                                   "problems": [fb["error"]["message"]], "call_id": tc["id"]})
                if self.guard.failed(sig):
                    return self._force_escalate(sig, name, args, fb["error"]["message"])
                return fb
        if sig in self.guard.escalated:
            return {"ok": False, "error": {"code": "POLICY_BLOCKED", "message": "this call was already escalated to "
                                           "the owner after repeated failures", "retryable": False},
                    "verifier": {"action": "stop", "suggestion": "do not call it again; finish with a summary"}}
        if sig in self.guard.blocked:
            self.emit("verifier", "verifier", {"stage": "pre-call", "tool": name, "ok": False,
                                               "problems": ["identical call was already refused"]})
            if self.guard.failed(sig):
                return self._force_escalate(sig, name, args, "the same refused call was repeated")
            return {"ok": False, "error": {"code": "POLICY_BLOCKED", "message": "you already made this exact call and "
                                           "it was refused; repeating it will not work", "retryable": False},
                    "verifier": {"action": "change course",
                                 "suggestion": "fix what the refusal named, or escalate_to_owner"}}

        attempt = 0
        while True:
            env = self._call(name, args, tc["id"], attempt)
            problems = V.check_result(name, env)
            if problems:
                self.emit("verifier", "verifier", {"stage": "result", "tool": name, "ok": False, "problems": problems})
                error = {"code": "MALFORMED_RESULT", "message": "tool returned malformed data: " + "; ".join(problems),
                         "retryable": True}
            elif not env["ok"]:
                error = env["error"]
            else:
                self._record_success(name, args, env)
                return env
            if name == "publish_listing":
                self.tried_channels.setdefault(args.get("listing_id", ""), set()).add(args.get("channel"))
            d = V.decide(name, args, error, attempt, max_retries=self.cfg.max_retries,
                         backoff_base_s=self.cfg.backoff_base_s,
                         tried_channels=self.tried_channels.get(args.get("listing_id", ""), set()))
            self.emit("verifier", "verifier", {"stage": "policy", "tool": name, "code": error.get("code"),
                                               "action": d.action, "note": d.note})
            if d.action == "retry":
                self.emit("retry", "verifier", {"tool": name, "attempt": attempt + 1, "delay_s": d.delay_s,
                                                "code": error.get("code")})
                self.sleep(d.delay_s)
                attempt += 1
                continue
            if d.action == "fallback":
                self.emit("fallback", "verifier", {"tool": name, "code": error.get("code"), "note": d.note,
                                                   "suggestion": d.suggestion, "alternatives": d.alternatives})
            if error.get("code") in V.NO_RETRY:
                self.guard.blocked.add(sig)
            if self.guard.failed(sig):
                return self._force_escalate(sig, name, args, f"{error.get('code')}: {error.get('message')}")
            fb = {"action": d.action, "note": d.note, "attempts": attempt + 1}
            if d.suggestion:
                fb["suggestion"] = d.suggestion
            if d.alternatives:
                fb["alternatives"] = d.alternatives
            if error.get("code") == "MALFORMED_RESULT":
                fb["suggestion"] = "the data could not be trusted; do not use it, try another way or escalate"
            return {"ok": False, "error": error, "verifier": fb}

    def _call(self, name, args, call_id, attempt=0):
        """Run one tool through the backend, which emits tool_call/tool_result events."""
        self.n_calls += 1
        try:
            env = toolbox.call(self.be, self.world, name, args, sink=self.sink, actor="operator", call_id=call_id)
        except Exception as e:  # tools must not raise; if they do, treat as upstream error
            env = {"ok": False, "error": {"code": "UPSTREAM_ERROR", "message": f"{type(e).__name__}: {e}",
                                          "retryable": True}}
            self.emit("tool_result", "system", {"tool": name, "call_id": call_id, "result": env})
        if not self.cfg.verifier and isinstance(env, dict) and env.get("ok"):
            self._record_success(name, args, env)
        return env

    def _record_success(self, name, args, env):
        self.ledger.append({"name": name, "args": args, "data": env.get("data")})
        if name == "publish_listing":
            self.tried_channels.setdefault(args.get("listing_id", ""), set()).add(args.get("channel"))
        if name == "escalate_to_owner":
            esc = (env.get("data") or {}).get("escalation") or env.get("data") or {}
            self.escalations.append(esc.get("esc_id", "?"))

    def _force_escalate(self, sig, name, args, why, reason=None) -> dict:
        self.guard.escalated.add(sig)
        reason = (reason or f"{name} failed {self.guard.count(sig)} times: {why}")[:500]
        self.emit("verifier", "verifier", {"stage": "loop-guard", "ok": False, "tool": name,
                                           "problems": [reason], "action": "force escalate_to_owner"})
        env, ea = {}, {}
        for ref in V.ref_candidates(args, self.ledger, toolbox.state(self.world))[:6]:
            ea = {"reason": reason, "ref_id": ref}
            env = toolbox.call(self.be, self.world, "escalate_to_owner", ea, sink=self.sink, actor="verifier",
                               call_id=f"guard_{uuid.uuid4().hex[:6]}")
            if env.get("ok") or (env.get("error") or {}).get("code") != "NOT_FOUND":
                break
        data = (env or {}).get("data") or {}
        esc = data.get("escalation") or data
        if env.get("ok"):
            self.ledger.append({"name": "escalate_to_owner", "args": ea, "data": data})
            self.escalations.append(esc.get("esc_id", "?"))
        return {"ok": False, "error": {"code": "POLICY_BLOCKED", "message": reason, "retryable": False},
                "verifier": {"action": "escalated", "esc_id": esc.get("esc_id"),
                             "suggestion": "I escalated this to the owner. Do not call it again; continue with other "
                                           "work or finish with a summary."}}


class _MeteredCompletions:
    def __init__(self, inner, calls):
        self._inner, self._calls = inner, calls

    def create(self, **kw):
        t0 = time.time()
        resp = self._inner.create(**kw)
        u = _as_dict(getattr(resp, "usage", None) if not isinstance(resp, dict) else resp.get("usage"))
        self._calls.append({"latency_s": round(time.time() - t0, 3), "cost_usd": None,
                            "usage": {"input_tokens": u.get("prompt_tokens") or 0,
                                      "output_tokens": u.get("completion_tokens") or 0}})
        return resp


class MeteredClient:
    """Wraps an OpenAI-style client and records one entry per model call (usage, latency) in .calls,
    the same shape the reference Anthropic adapter keeps, so the Gym can count model calls and tokens."""

    def __init__(self, inner):
        self.inner, self.calls = inner, []
        self.chat = type("Chat", (), {})()
        self.chat.completions = _MeteredCompletions(inner.chat.completions, self.calls)


def make_client(cfg: RunConfig, timeout: float | None = None, max_retries: int | None = None):
    """The model client for cfg.api. "openai" (default) is the running system; "anthropic" is the
    reference-only frontier backend (rentus_operator.anthropic_client). Both keep per-call usage in .calls."""
    if cfg.api == "anthropic":
        from .anthropic_client import AnthropicChatAdapter
        return AnthropicChatAdapter(model=cfg.model, effort=cfg.effort or "high",
                                    max_tokens=max(cfg.max_tokens, 16000))
    from openai import OpenAI
    kw = {k: v for k, v in (("timeout", timeout), ("max_retries", max_retries)) if v is not None}
    return MeteredClient(OpenAI(base_url=cfg.base_url, api_key=cfg.api_key, **kw))


def run(world, goal_or_inbound, client=None, model: str | None = None, max_steps: int | None = None, *,
        config: RunConfig | None = None, sink=None, backend=None, history: list[dict] | None = None,
        run_id: str | None = None, sleep=time.sleep, end_on_send: str | None = None) -> RunResult:
    """end_on_send (router mode): the turn ends, without another model call, as soon as a send_message to
    that thread succeeds; the renter's replies are kept out of the tool result (they arrive as the next
    routed inbound message)."""
    cfg = config or RunConfig()
    if model:
        cfg = cfg.with_(model=model)
    if max_steps:
        cfg = cfg.with_(max_steps=max_steps)
    be = backend or toolbox.backend()
    run_id = run_id or f"r_{uuid.uuid4().hex[:8]}"
    if sink is None:
        sink = toolbox.make_sink(be, run_id)
    if client is None:
        client = make_client(cfg)
    R = _Runner(world, client, cfg, sink, be, sleep)

    st = toolbox.state(world)
    pol = st.get("policy") or {}
    facts = {"today": toolbox.today(world), "spend_limit_usd": pol.get("spend_limit_usd"),
             "showing_hours": pol.get("showing_hours")}
    if history:
        messages = list(history)
    else:
        messages = [{"role": "system", "content": load_prompt(cfg, facts)}]
    opening, who = _opening(goal_or_inbound)
    messages.append({"role": "user", "content": opening})
    if who == "owner":
        R.emit("owner_message", "owner", {"text": opening[len("Owner: "):]})
    before = toolbox.snapshot(world)

    status, final_text, checks, rounds_left, steps = "max_steps", "", [], cfg.self_check_rounds, 0
    renter_thread = goal_or_inbound.get("thread_id") if (who is None and isinstance(goal_or_inbound, dict)) else None
    guard_left = cfg.renter_guard_rounds if cfg.renter_guard else 0
    while steps < cfg.max_steps:
        steps += 1
        kw = {"model": cfg.model, "messages": messages, "tools": R.tools, "tool_choice": "auto",
              "temperature": cfg.temperature, "max_tokens": cfg.max_tokens}
        if cfg.reasoning is not None:
            kw["extra_body"] = {"chat_template_kwargs": {"enable_thinking": cfg.reasoning}}
        resp, err = None, None
        for attempt in range(cfg.max_retries + 1):
            try:
                resp = client.chat.completions.create(**kw)
                break
            except Exception as e:  # network / server errors
                err = f"{type(e).__name__}: {e}"
                R.emit("retry", "verifier", {"tool": "<model>", "attempt": attempt + 1, "error": err[:300]})
                sleep(min(cfg.backoff_base_s * (2 ** attempt), 8.0))
        if resp is None:
            status, final_text = "model_error", err or "model call failed"
            break
        m = normalize(resp)
        calls = m["tool_calls"]
        if not calls and cfg.verifier:
            calls, m["content"] = inline_tool_calls(m["content"]) if "<tool_call>" in m["content"] else ([], m["content"])
            if calls:
                R.emit("verifier", "verifier", {"stage": "parse", "ok": True,
                                                "repaired": [f"recovered {len(calls)} tool call(s) from text"]})
        R.emit("model_message", "operator", {"text": m["content"], "tool_calls": [c["function"]["name"] for c in calls],
                                             "reasoning": m["reasoning"][:2000] if m["reasoning"] else None,
                                             "step": steps})
        am = {"role": "assistant", "content": m["content"] or ""}
        if calls:
            am["tool_calls"] = calls
        if cfg.keep_reasoning_in_history and m["reasoning"]:
            am["reasoning_content"] = m["reasoning"]
        messages.append(am)

        if calls:
            sent = False
            for tc in calls:
                n_ledger = len(R.ledger)
                out = R.execute(tc)
                if end_on_send and tc["function"]["name"] == "send_message" and len(R.ledger) > n_ledger \
                        and (R.ledger[-1].get("args") or {}).get("thread_id") == end_on_send:
                    sent = True
                    if isinstance(out.get("data"), dict) and "replies" in out["data"]:
                        out = {**out, "data": {k: v for k, v in out["data"].items() if k != "replies"}}
                messages.append({"role": "tool", "tool_call_id": tc["id"],
                                 "content": json.dumps(out, default=str, ensure_ascii=False)})
            if sent:
                status, final_text = "done", m["content"]
                R.emit("verifier", "harness", {"stage": "end-on-send", "ok": True, "thread_id": end_on_send})
                break
            continue

        final_text = m["content"]
        if guard_left > 0 and renter_unanswered(world, renter_thread):
            guard_left -= 1
            R.emit("verifier", "harness", {"stage": "renter-guard", "ok": False, "thread_id": renter_thread,
                                           "problems": ["run ended on plain text with the renter unanswered"]})
            messages.append({"role": "user", "content": renter_guard_feedback(renter_thread)})
            continue
        if not cfg.verifier:
            status = "done"
            break
        checks = V.self_check(before, toolbox.snapshot(world), R.ledger, final_text)
        R.emit("verifier", "verifier", {"stage": "self-check", "ok": not checks, "problems": checks})
        if not checks:
            status = "done"
            break
        if rounds_left <= 0:
            status = "done_unverified"
            break
        rounds_left -= 1
        messages.append({"role": "user", "content": "[verifier] Your summary does not match the world state: "
                         + "; ".join(checks) + ". Do the missing actions now with tools, or correct the summary "
                         "so it only states what actually happened."})

    if status == "max_steps" and cfg.verifier:
        R._force_escalate("__max_steps__", "run", {}, "",
                          reason=f"step limit {cfg.max_steps} reached before the task finished")

    return RunResult(run_id=run_id, status=status, final_text=final_text, steps=steps, tool_calls=R.n_calls,
                     messages=messages, ledger=R.ledger, self_check=checks, escalations=R.escalations,
                     events=list(getattr(sink, "events", []) or []), config=cfg.label())
