"""Reference-only frontier backend: the Anthropic adapter, offline, with a fake SDK (no network, no spend)."""
import json

import pytest

from rentus_operator import RunConfig, run
from rentus_operator.anthropic_client import AnthropicChatAdapter, BudgetExceeded, SpendMeter, call_cost


class _Raw:
    def __init__(self, data):
        self._d = data

    def json(self):
        return self._d


class FakeSDK:
    """Mimics sdk.messages.with_raw_response.create(**body).json() with scripted Messages API responses."""

    def __init__(self, script):
        self.script, self.bodies = list(script), []
        outer = self

        class _WRR:
            def create(self, **body):
                outer.bodies.append(json.loads(json.dumps(body)))
                return _Raw(outer.script.pop(0))

        class _M:
            with_raw_response = _WRR()

        self.messages = _M()


def resp(*blocks, stop="end_turn", cost=0.01):
    return {"id": "msg_x", "model": "claude-opus-5-5", "content": list(blocks), "stop_reason": stop,
            "usage": {"input_tokens": 100, "output_tokens": 20}, "cost": cost}


def think(text="hmm", sig="SIG1"):
    return {"type": "thinking", "thinking": text, "signature": sig}


def tool_use(tid, name, **inp):
    return {"type": "tool_use", "id": tid, "name": name, "input": inp}


def adapter(script, cap=10.0):
    return AnthropicChatAdapter(sdk=FakeSDK(script), meter=SpendMeter(cap))


def test_translation_and_thinking_replay():
    a = adapter([resp(think(), {"type": "text", "text": "checking"}, tool_use("tu_1", "get_room", room_id="R001"),
                      stop="tool_use"),
                 resp(think("done", "SIG2"), {"type": "text", "text": "All set."})])
    tools = [{"type": "function", "function": {"name": "get_room", "description": "d",
                                               "parameters": {"type": "object", "properties": {"room_id": {"type": "string"}}}}}]
    msgs = [{"role": "system", "content": "SYS"}, {"role": "user", "content": "Owner: hi"}]
    r1 = a.chat.completions.create(model="x", messages=msgs, tools=tools, tool_choice="auto", temperature=0.2,
                                   max_tokens=2048, extra_body={"chat_template_kwargs": {}})
    m1 = r1["choices"][0]["message"]
    assert m1["tool_calls"][0]["id"] == "tu_1" and json.loads(m1["tool_calls"][0]["function"]["arguments"]) == {"room_id": "R001"}
    assert m1["reasoning_content"] == "hmm" and r1["choices"][0]["finish_reason"] == "tool_calls"
    b1 = a.sdk.bodies[0]
    assert "temperature" not in b1 and b1["tool_choice"] == {"type": "auto"} and b1["max_tokens"] >= 16000
    assert b1["system"][0]["text"] == "SYS" and b1["tools"][0]["input_schema"]["properties"]["room_id"]
    assert b1["output_config"] == {"effort": "high"}

    msgs += [{"role": "assistant", "content": m1["content"], "tool_calls": m1["tool_calls"], "reasoning_content": "hmm"},
             {"role": "tool", "tool_call_id": "tu_1", "content": '{"ok": true}'},
             {"role": "user", "content": "[harness] nudge"}]
    a.chat.completions.create(model="x", messages=msgs, tools=tools)
    b2 = a.sdk.bodies[1]["messages"]
    # the assistant turn is replayed verbatim, thinking signature included
    assert b2[1]["role"] == "assistant" and b2[1]["content"][0] == think()
    # tool result and the following user text share one user turn; tool_result comes first
    assert b2[2]["role"] == "user" and b2[2]["content"][0]["type"] == "tool_result"
    assert b2[2]["content"][1]["text"] == "[harness] nudge" and "cache_control" in b2[2]["content"][-1]
    assert a.meter.snapshot()["spent_usd"] == pytest.approx(0.02)


def test_budget_cap_stops_calls():
    a = adapter([resp(cost=1.0), resp(cost=1.0)], cap=1.0)
    a.chat.completions.create(model="x", messages=[{"role": "user", "content": "hi"}])
    with pytest.raises(BudgetExceeded):
        a.chat.completions.create(model="x", messages=[{"role": "user", "content": "hi"}])


def test_cost_falls_back_to_list_price():
    c, src = call_cost("claude-opus-5-5", {"usage": {"input_tokens": 1_000_000, "output_tokens": 100_000}})
    assert src == "computed" and c == pytest.approx(4.0 + 2.0)


def test_same_loop_runs_on_the_adapter(be, make_world):
    w = make_world()
    a = adapter([resp(think(), tool_use("tu_1", "get_room", room_id="R001"), stop="tool_use"),
                 resp({"type": "text", "text": "I read the room record."})])
    res = run(w, "Owner task", client=a, backend=be, sink=be.EventSink(run_id="t"), sleep=lambda s: None,
              config=RunConfig(api="anthropic", model="claude-opus-5-5", prompt_version="v3", renter_guard=True,
                               style_precheck=True, keep_reasoning_in_history=True))
    assert res.status == "done" and res.tool_calls == 1
    assert [m["role"] for m in res.messages][:2] == ["system", "user"]
    assert "api=anthropic" in res.config
