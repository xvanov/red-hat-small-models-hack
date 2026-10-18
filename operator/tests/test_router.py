"""Triage router: deterministic signals, each decision, and the event-driven driver (stub Lightning).

Runs on the real tools package only (the router needs read_reply and the rule reader as a cross-check).
The 0.6B model reader is replaced by a patched `_http_read`, so no endpoint is needed.
"""
import json

import pytest

from rentus_operator import RunConfig, run, toolbox
from rentus_operator import router as RT
from rentus_operator.stub_model import StubClient, call, turn

rt = pytest.importorskip("rentus_tools")
from rentus_tools.impl import reader as reader_impl  # noqa: E402

T = "T001"


def world_with(msgs, **patch):
    thread = {"thread_id": T, "channel": "marketplace", "renter_name": "Ana Ruiz", "language": "en",
              "messages": [{"id": f"m{i}", "from": who, "text": text, "attachments": [], "ts": "2026-10-17T09:00:00"}
                           for i, (who, text) in enumerate(msgs)]}
    return rt.load(patch={"threads": [thread], **patch})


def model_reader(monkeypatch, edit=None):
    """The 'model' reader = the rule reader's answer, optionally edited, marked as coming from the model."""
    calls = []

    def fake(inp):
        calls.append(inp)
        out = reader_impl.read_reply_fallback(inp["message"], context=inp.get("context"), today=inp["today"])
        return edit(inp, out) if edit else out
    monkeypatch.setattr(reader_impl, "_http_read", fake)
    return calls


def route(w, sink=None):
    sink = sink or rt.EventSink(run_id="t")
    r = RT.Router(w, rt, sink, RunConfig(router=True))
    return r.route(T), sink


def reg(w):
    return RT.renter_row(w, T)


# ------------------------------------------------------------------------------- signals
def test_signals():
    assert RT.is_system_text("Ana reacted 👍 to your message")
    assert RT.is_system_text("Sam liked a message")
    assert RT.is_system_text("You are now connected on Messenger")
    assert not RT.is_system_text("I liked the photos, is it still available?")
    assert RT.is_ack("🙏🙏") and RT.is_ack("thanks!!") and RT.is_ack("Ok gracias")
    assert not RT.is_ack("thanks, my number is 919-555-0166")
    assert RT.is_abusive("this is a fucking scam") and not RT.is_abusive("is it a scam-free listing?")
    assert RT.question_pending([{"from": "operator", "text": "What is your move-in date?"}])
    assert not RT.question_pending([{"from": "operator", "text": "Great, talk soon."}, {"from": "renter", "text": "ok"}])


def test_merge_parses_takes_decisive_status_and_unions_intents():
    a = {"lease": {"status": "vague", "value": None}, "intents": ["small_talk"], "language": "en"}
    b = {"lease": {"status": "answered", "value": True}, "intents": ["question"], "language": "en"}
    m = RT.merge_parses([a, b])
    assert m["lease"]["status"] == "answered" and m["intents"] == ["question"]


# ------------------------------------------------------------------------------- decisions
def test_noop_ack_with_no_question_pending(monkeypatch):
    calls = model_reader(monkeypatch)
    w = world_with([("renter", "hi"), ("operator", "Your showing is proposed for Saturday at 10 AM."), ("renter", "thanks 🙏")])
    d, sink = route(w)
    assert d.decision == RT.NO_OP and not d.invoke_lightning and not calls
    ev = [e for e in sink.events if e["actor"] == "router" and e["data"].get("stage") == "router"]
    assert ev and ev[0]["actor"] == "router" and ev[0]["data"]["decision"] == "NO_OP"


def test_ack_while_question_pending_goes_to_lightning(monkeypatch):
    model_reader(monkeypatch)
    w = world_with([("renter", "hi"), ("operator", "What is the best phone number to reach you?"), ("renter", "thanks!!")])
    d, _ = route(w)
    assert d.decision == RT.LIGHTNING and d.invoke_lightning and "phone" in d.note


def test_noop_system_text_and_duplicate(monkeypatch):
    model_reader(monkeypatch)
    w = world_with([("renter", "is it available?"), ("operator", "Yes, how long do you want to stay?"),
                    ("renter", "Ana reacted ❤️ to your message")])
    assert route(w)[0].decision == RT.NO_OP
    w = world_with([("renter", "is it available?"), ("renter", "is it available?")])
    r = RT.Router(w, rt, None, RunConfig(router=True))
    r.seen.add("m0")           # the first copy was already routed
    d = r.route(T)
    assert d.decision == RT.NO_OP and "duplicate" in d.reason


def test_record_only_writes_confident_phone_and_still_owes_reply(monkeypatch):
    model_reader(monkeypatch)
    w = world_with([("renter", "hi, still available?"), ("operator", "Yes! What is the best phone number to reach you?"),
                    ("renter", "(919) 555-0166")])
    d, sink = route(w)
    assert d.decision == RT.RECORD_ONLY, d.reason
    assert reg(w)["gate"]["phone"]["value"] == "+19195550166"
    assert d.reply_owed and "do not record again" in d.note and "phone=" in d.note
    tc = [e for e in sink.events if e["type"] == "tool_call" and e["data"].get("tool") == "upsert_renter"]
    assert tc and tc[0]["actor"] == "router"


def test_record_only_without_reply_when_file_closed(monkeypatch):
    model_reader(monkeypatch)
    w = world_with([("renter", "hi"), ("operator", "Your showing is proposed, I will confirm soon."),
                    ("renter", "my number is 919-555-0166")])
    toolbox.call(rt, w, "upsert_renter", {"thread_id": T, "fields": {"status": "showing_proposed"}})
    d, _ = route(w)
    assert d.decision == RT.RECORD_ONLY and not d.reply_owed and not d.invoke_lightning


def test_readers_disagree_nothing_recorded(monkeypatch):
    def wrong(inp, out):
        out["phone"] = {"status": "answered", "value": "+19195550199"}
        return out
    model_reader(monkeypatch, wrong)
    w = world_with([("renter", "hi"), ("operator", "What is the best number to reach you?"), ("renter", "919-555-0166")])
    d, _ = route(w)
    assert d.decision == RT.LIGHTNING and not d.recorded and reg(w) is None
    assert "+19195550199" in d.note      # Lightning still sees the model's parse


def test_model_reader_down_means_no_confident_writes(monkeypatch):
    monkeypatch.setattr(reader_impl, "_http_read", lambda inp: None)    # read_reply falls back to rules
    w = world_with([("renter", "hi"), ("operator", "What is the best number to reach you?"), ("renter", "919-555-0166")])
    d, _ = route(w)
    assert d.decision == RT.LIGHTNING and not d.recorded


def test_batch_merges_a_burst(monkeypatch):
    calls = model_reader(monkeypatch)
    w = world_with([("renter", "Hi, is the room on Quill Ln still available?"),
                    ("renter", "text me at 1-919-555-0160, a year works for me, I'm moving for a new job at Duke")])
    d, _ = route(w)
    assert d.decision == RT.BATCH and len(calls) == 2 and d.invoke_lightning
    assert reg(w)["gate"]["phone"]["value"] == "+19195550160"
    assert "2 messages" in d.note and "read_thread and get_room" in d.note


def test_hard_no_escalates_direct_and_lightning_writes_the_close(monkeypatch):
    model_reader(monkeypatch)
    w = world_with([("renter", "is it available?"), ("operator", "Yes, how long do you want to stay?"),
                    ("renter", "I found a place already, not interested anymore")])
    d, _ = route(w)
    assert d.decision == RT.ESCALATE_DIRECT, d.reason
    st = toolbox.state(w)
    assert st["escalations"] and st["escalations"][0]["ref_id"] == T and reg(w)["status"] == "lost"
    assert d.reply_owed and "closing reply" in d.note


def test_hard_no_only_from_model_goes_to_lightning(monkeypatch):
    def says_no(inp, out):
        out["intents"] = ["hard_no"]
        return out
    model_reader(monkeypatch, says_no)
    w = world_with([("renter", "hi"), ("operator", "How long do you want to stay?"), ("renter", "a year is fine")])
    d, _ = route(w)
    assert d.decision != RT.ESCALATE_DIRECT and not toolbox.state(w)["escalations"]


def test_abuse_escalates_without_reply(monkeypatch):
    model_reader(monkeypatch)
    w = world_with([("renter", "hi"), ("operator", "How long do you want to stay?"), ("renter", "this is a fucking joke")])
    d, _ = route(w)
    assert d.decision == RT.ESCALATE_DIRECT and not d.invoke_lightning and toolbox.state(w)["escalations"]


# ------------------------------------------------------------------------------- driver
def test_run_conversation_turn_ends_on_send(monkeypatch):
    model_reader(monkeypatch)
    w = world_with([("renter", "Hi, is the room still available?")])
    client = StubClient([turn(call("send_message", thread_id=T, text="Hi Ana, yes it is. Is a one year lease okay with you?")),
                         turn(content="should never be requested")])
    res = RT.run_conversation(w, {"thread_id": T, "channel": "marketplace", "renter_name": "Ana Ruiz"}, client=client,
                              config=RunConfig(model="stub", router=True), backend=rt, sink=rt.EventSink(run_id="t"))
    assert len(client.requests) == 1 and res.lightning_turns == 1 and res.status == "done"
    assert [d["decision"] for d in res.decisions] == ["LIGHTNING"]
    first_user = next(m for m in client.requests[0]["messages"] if m["role"] == "user")
    assert first_user["content"].startswith("[router]")
    assert "Router mode" in client.requests[0]["messages"][0]["content"]


def test_run_conversation_routes_the_renter_reply(monkeypatch):
    """The renter answers during the turn (as a Gym counterpart would); that answer is the next inbound."""
    model_reader(monkeypatch)
    w = world_with([("renter", "Hi, is the room still available?")])
    real_call = rt.call

    def call_with_reply(world, name, args, **kw):
        env = real_call(world, name, args, **kw)
        if name == "send_message" and env.get("ok") and "phone" in args["text"]:
            t = RT.thread_of(world, T)
            world.threads[0]["messages"].append({"id": "r1", "from": "renter", "text": "919-555-0166",
                                                 "attachments": [], "ts": "2026-10-17T09:05:00"}) \
                if not isinstance(world, dict) and t else None
        return env
    be = type("BE", (), {"call": staticmethod(call_with_reply), "EventSink": rt.EventSink, "TOOLS": rt.TOOLS,
                         "tool_schemas": staticmethod(rt.tool_schemas)})
    client = StubClient([turn(call("send_message", thread_id=T, text="Yes it is. What is the best phone number to reach you?")),
                         turn(call("send_message", thread_id=T, text="Thanks, got it. Is a one year lease okay with you?"))])
    res = RT.run_conversation(w, {"thread_id": T}, client=client, config=RunConfig(model="stub", router=True),
                              backend=be, sink=rt.EventSink(run_id="t"))
    assert [d["decision"] for d in res.decisions] == ["LIGHTNING", "RECORD_ONLY"]
    assert len(client.requests) == 2 and reg(w)["gate"]["phone"]["value"] == "+19195550166"
    # the reply never leaked into the first turn's tool result
    tool_msgs = [json.loads(m["content"]) for m in res.messages if m["role"] == "tool"]
    assert all("replies" not in (t.get("data") or {}) for t in tool_msgs)


def test_router_off_is_unchanged(be, make_world):
    w = make_world()
    client = StubClient([turn(content="Nothing to do.")])
    res = run(w, "Owner task", client=client, backend=be, config=RunConfig(model="stub"))
    assert res.status == "done" and "Router mode" not in client.requests[0]["messages"][0]["content"]
    assert "router=on" not in RunConfig().label() and "router=on" in RunConfig(router=True).label()


def test_repeat_answering_a_new_question_is_not_a_duplicate(monkeypatch):
    model_reader(monkeypatch)
    w = world_with([("renter", "hi"), ("operator", "What is your move-in date?"), ("renter", "Not sure what you mean"),
                    ("operator", "What exact date would you move in?"), ("renter", "Not sure what you mean")])
    r = RT.Router(w, rt, None, RunConfig(router=True))
    r.seen.update({"m0", "m2"})
    assert r.route(T).decision != RT.NO_OP


def test_protect_gate_drops_value_less_overwrites():
    row = {"gate": {"lease": {"status": "answered", "value": True}, "phone": {"status": "answered", "value": "+19195550166"},
                    "move_in": {"status": "vague", "date": None, "raw": "soon"}}}
    args = {"thread_id": T, "fields": {"name": "Ana", "gate": {"lease": {"status": "answered", "months": 12},
                                                               "phone": "+19195550177", "move_in": "2026-11-01"}}}
    out, dropped = RT.protect_gate(args, row)
    assert dropped == ["lease"] and out["fields"]["gate"] == {"phone": "+19195550177", "move_in": "2026-11-01"}
    assert out["fields"]["name"] == "Ana"


def test_router_mode_refuses_an_erasing_upsert(monkeypatch):
    model_reader(monkeypatch)
    w = world_with([("renter", "hi")])
    toolbox.call(rt, w, "upsert_renter", {"thread_id": T, "fields": {"gate": {"lease": {"status": "answered", "value": True}}}})
    client = StubClient([turn(call("upsert_renter", thread_id=T, fields={"gate": {"lease": {"status": "answered"}}})),
                         turn(content="ok")])
    res = run(w, "Owner task", client=client, backend=rt, config=RunConfig(model="stub", router=True))
    assert reg(w)["gate"]["lease"]["value"] is True
    assert "already recorded" in json.dumps([m for m in res.messages if m["role"] == "tool"])
