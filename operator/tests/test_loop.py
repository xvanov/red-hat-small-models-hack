"""Loop + verifier behaviour with the scripted stub model, on the shim and the real tools package."""
import json

from rentus_operator import RunConfig, run, toolbox
from rentus_operator import verifier as V
from rentus_operator.loop import inline_tool_calls, split_reasoning
from rentus_operator.stub_model import StubClient, call, raw_call, tool_data, turn


def go(be, world, script, goal="Owner task", fail_first=0, **cfg):
    client = StubClient(script, fail_first=fail_first)
    sink = be.EventSink(run_id="t")
    sleeps = []
    res = run(world, goal, client=client, backend=be, sink=sink, sleep=sleeps.append,
              config=RunConfig(model="stub", backoff_base_s=0.5, **cfg))
    return res, client, sink.events, sleeps


def kinds(events, t):
    return [e for e in events if e["type"] == t]


def tool_msgs(res):
    return [json.loads(m["content"]) for m in res.messages if m["role"] == "tool"]


def esc_count(world):
    return len(toolbox.state(world)["escalations"])


def test_happy_path_and_parallel_calls(be, make_world):
    w = make_world()
    res, client, ev, _ = go(be, w, [
        turn(call("get_room", room_id="R001"), call("get_listing_media", room_id="R001")),
        turn(content="I read the room record."),
    ])
    assert res.status == "done" and res.tool_calls == 2
    # both parallel calls answered, ids matched in order
    am = next(m for m in res.messages if m.get("tool_calls"))
    tids = [m["tool_call_id"] for m in res.messages if m["role"] == "tool"]
    assert tids == [tc["id"] for tc in am["tool_calls"]]
    assert {e["type"] for e in ev} >= {"model_message", "tool_call", "tool_result", "verifier"}
    # the model saw the tools and the v1 system prompt
    req = client.requests[0]
    assert req["messages"][0]["role"] == "system" and "qualifying gate" in req["messages"][0]["content"]
    assert any(t["function"]["name"] == "read_reply" for t in req["tools"])


def test_malformed_args_repaired_or_fed_back(be, make_world):
    w = make_world()
    res, _, ev, _ = go(be, w, [
        turn(raw_call("get_room", '{"room_id": "R001",}')),        # trailing comma: repaired, executed
        turn(raw_call("get_room", '{"room_id": }')),               # unrepairable: feedback, not executed
        turn(raw_call("get_room", '{"id": "R001"}')),              # schema error: feedback, not executed
        turn(content="Done reading."),
    ])
    out = tool_msgs(res)
    assert out[0]["ok"] is True
    assert out[1]["ok"] is False and out[1]["error"]["code"] == "INVALID_ARGS" and out[1]["verifier"]["problems"]
    assert "room_id is required" in json.dumps(out[2])
    assert res.tool_calls == 1  # only the repaired call reached the tools
    assert any(e["data"].get("repaired") for e in kinds(ev, "verifier"))


def test_malformed_result_detected_and_retried(be, make_world):
    w = make_world(faults=[{"tool": "get_room", "kind": "malformed", "times": 1}])
    res, _, ev, sleeps = go(be, w, [turn(call("get_room", room_id="R001")), turn(content="Read it.")])
    out = tool_msgs(res)
    assert out[0]["ok"] is True and out[0]["data"]["room"]["room_id"] == "R001"
    assert any(e["data"].get("stage") == "result" and not e["data"]["ok"] for e in kinds(ev, "verifier"))
    assert len(kinds(ev, "retry")) == 1 and sleeps == [0.5]


def test_malformed_result_passes_through_when_verifier_off(be, make_world):
    w = make_world(faults=[{"tool": "get_room", "kind": "malformed", "times": 1}])
    res, _, ev, _ = go(be, w, [turn(call("get_room", room_id="R001")), turn(content="Read it.")], verifier=False)
    out = tool_msgs(res)
    assert out[0]["ok"] is True and V.check_result("get_room", out[0])  # corrupt data reached the model
    assert not kinds(ev, "retry") and not kinds(ev, "verifier")


def test_retryable_fault_bounded_backoff(be, make_world):
    w = make_world(faults=[{"tool": "list_rooms", "kind": "rate_limited", "times": 2}])
    res, _, ev, sleeps = go(be, w, [turn(call("list_rooms")), turn(content="Listed.")])
    assert tool_msgs(res)[0]["ok"] is True
    assert sleeps == [0.5, 1.0] and len(kinds(ev, "retry")) == 2

    w = make_world(faults=[{"tool": "list_rooms", "kind": "upstream_error", "times": 9}])
    res, _, ev, sleeps = go(be, w, [turn(call("list_rooms")), turn(content="It failed, I will try later.")])
    out = tool_msgs(res)[0]
    assert out["ok"] is False and out["verifier"]["action"] == "feedback" and len(sleeps) == 2


def test_page_changed_falls_back_to_other_channel(be, make_world):
    w = make_world(faults=[{"tool": "publish_listing", "kind": "page_changed", "times": 1}])

    def create(msgs):
        return turn(call("create_listing", room_id="R001", title="Private room, private bath",
                         body="Room with a private bath in Durham. 1 year minimum.", price=1050))

    def publish(ch):
        return lambda msgs: turn(call("publish_listing", listing_id=tool_data(msgs, "create_listing")["listing"]
                                      ["listing_id"], channel=ch))
    res, _, ev, sleeps = go(be, w, [create, publish("marketplace"), publish("roomies"),
                                    turn(content="I published the listing on roomies.")])
    out = tool_msgs(res)
    fb = out[1]
    assert fb["ok"] is False and fb["error"]["code"] == "PAGE_CHANGED" and "roomies" in fb["verifier"]["alternatives"]
    assert "marketplace" not in fb["verifier"]["alternatives"]
    assert len(kinds(ev, "fallback")) == 1 and not sleeps
    assert out[2]["ok"] is True and res.status == "done"


def test_policy_block_no_blind_retry_then_loop_guard(be, make_world):
    w = make_world()
    bad = call("send_message", thread_id="T001", text="Yes it is available — want to see it?")
    res, _, ev, _ = go(be, w, [turn(bad), turn(bad), turn(bad), turn(bad), turn(content="I escalated it.")])
    out = tool_msgs(res)
    assert out[0]["error"]["code"] == "POLICY_BLOCKED" and "verifier" in out[0]
    assert not kinds(ev, "retry")
    # only the first attempt reached the tool; repeats are refused by the verifier
    assert len([e for e in kinds(ev, "tool_call") if e["data"]["tool"] == "send_message"]) == 1
    assert "already made this exact call" in out[1]["error"]["message"]
    assert out[2]["verifier"]["action"] == "escalated"
    assert esc_count(w) == 1 and len(res.escalations) == 1
    assert "already escalated" in out[3]["error"]["message"]
    assert res.status == "done"


def test_loop_guard_same_failing_call_three_times(be, make_world):
    w = make_world()
    nf = call("get_room", room_id="R999")
    res, _, ev, _ = go(be, w, [turn(nf), turn(nf), turn(nf), turn(content="I escalated the missing room.")])
    out = tool_msgs(res)
    assert [o["ok"] for o in out] == [False, False, False]
    assert out[2]["verifier"]["action"] == "escalated"
    assert esc_count(w) == 1
    assert any(e["data"].get("stage") == "loop-guard" for e in kinds(ev, "verifier"))
    assert kinds(ev, "escalation") and kinds(ev, "escalation")[-1]["actor"] == "verifier"


def test_final_self_check_bounces_false_claim(be, make_world):
    w = make_world()

    def create(msgs):
        return turn(call("create_listing", room_id="R001", title="Private room, private bath",
                         body="Room with a private bath in Durham. 1 year minimum.", price=1050))

    def publish(msgs):
        return turn(call("publish_listing", listing_id=tool_data(msgs, "create_listing")["listing"]["listing_id"],
                         channel="craigslist"))
    claim = "I published the listing on craigslist."
    res, client, ev, _ = go(be, w, [create, turn(content=claim), publish, turn(content=claim)])
    sc = [e for e in kinds(ev, "verifier") if e["data"].get("stage") == "self-check"]
    assert [e["data"]["ok"] for e in sc] == [False, True]
    assert any("[verifier]" in (m.get("content") or "") for m in client.requests[2]["messages"])
    assert res.status == "done" and res.self_check == []

    # never fixed -> run ends flagged, not silently "done"
    w = make_world()
    res, _, _, _ = go(be, w, [turn(content=claim), turn(content=claim)])
    assert res.status == "done_unverified" and res.self_check


def test_max_steps_forces_escalation(be, make_world):
    w = make_world()
    res, _, _, _ = go(be, w, [turn(call("list_rooms"))] * 5, max_steps=3)
    assert res.status == "max_steps" and esc_count(w) == 1


def test_model_endpoint_error_retried(be, make_world):
    w = make_world()
    res, _, ev, sleeps = go(be, w, [turn(content="Hello.")], fail_first=1)
    assert res.status == "done" and len(kinds(ev, "retry")) == 1


def test_reasoning_stripped_and_inline_calls_recovered(be, make_world):
    w = make_world()
    res, client, ev, _ = go(be, w, [
        turn(content='<think>plan: read the room</think><tool_call>{"name": "get_room", "arguments": '
                     '{"room_id": "R001"}}</tool_call>', reasoning="separate reasoning field"),
        turn(content="<think>done</think>I read the room."),
    ])
    assert res.tool_calls == 1 and tool_msgs(res)[0]["ok"] is True
    hist = json.dumps(client.requests[-1]["messages"])
    assert "<think>" not in hist and "separate reasoning field" not in hist
    assert res.final_text == "I read the room."
    assert kinds(ev, "model_message")[0]["data"]["reasoning"]


def test_ablation_knobs(be, make_world):
    w = make_world()
    _, c_on, _, _ = go(be, w, [turn(content="ok")])
    _, c_off, _, _ = go(be, make_world(), [turn(content="ok")], reader=False, tool_descriptions="terse")
    names_on = {t["function"]["name"] for t in c_on.requests[0]["tools"]}
    names_off = {t["function"]["name"] for t in c_off.requests[0]["tools"]}
    assert names_on - names_off == {"read_reply"}
    total = lambda c: sum(len(t["function"]["description"]) for t in c.requests[0]["tools"])
    assert total(c_off) < total(c_on)
    assert "read_reply" in c_on.requests[0]["messages"][0]["content"]
    assert "read_reply" not in c_off.requests[0]["messages"][0]["content"]
    # verifier off: broken JSON is not repaired
    res, _, ev, _ = go(be, make_world(), [turn(raw_call("get_room", '{"room_id": "R001",}')), turn(content="x")],
                       verifier=False)
    assert tool_msgs(res)[0]["ok"] is False and not kinds(ev, "verifier")


def test_inbound_goal_and_history_continuation(be, make_world):
    w = make_world()
    res, client, _, _ = go(be, w, [turn(content="ok")],
                           goal={"thread_id": "T001", "channel": "marketplace", "renter_name": "Ana Ruiz",
                                 "text": "Hi, is the room still available?"})
    assert "thread T001" in client.requests[0]["messages"][1]["content"]
    client2 = StubClient([turn(content="again")])
    res2 = run(w, "Owner: next", client=client2, backend=be, history=res.messages,
               config=RunConfig(model="stub"), sink=be.EventSink(run_id="t2"))
    assert len(client2.requests[0]["messages"]) == len(res.messages) + 1


def test_split_and_inline_helpers():
    assert split_reasoning("abc</think>visible", {}) == ("visible", "abc")
    calls, rest = inline_tool_calls('<tool_call><function=get_room><parameter=room_id>R001</parameter></function>'
                                    '</tool_call>')
    assert calls[0]["function"]["name"] == "get_room" and json.loads(calls[0]["function"]["arguments"]) == \
        {"room_id": "R001"} and rest == ""
