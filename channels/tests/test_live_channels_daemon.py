"""channels.live with fake providers (no network): allowlist filtering, threading, rate cap, kill switch,
operator turn routing send_message to the real-send path, approvals, opt-out."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
for p in (REPO, REPO / "tools", REPO / "operator"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from channels.live import api, config, daemon, outbound  # noqa: E402
from channels.live.store import Store  # noqa: E402

OWNER_PHONE = "+12135550100"
STRANGER = "+19195550199"
OWNER_EMAIL = "owner.test@example.com"


class FakeLine:
    def __init__(self, name, number):
        self.name, self.number = name, number
        self.last4 = number[-4:]


class FakeSms:
    channel = "sms"

    def __init__(self, name, number):
        self.line = FakeLine(name, number)
        self.inbox: list[dict] = []
        self.sent: list[tuple] = []
        self.display = number

    def connected(self):
        return True, "fake"

    def poll(self, allow, since, seen):  # like Twilio: provider filters From=allowlisted
        return [m for m in self.inbox if m["ext_id"] not in seen and config.normalize_phone(m["contact"]) in allow.phones]

    def push(self, frm, text, sid):
        self.inbox.append({"channel": "sms", "contact": frm, "text": text, "ext_id": sid,
                           "ts": datetime.now(timezone.utc).isoformat(), "line": self.line.name,
                           "line_last4": self.line.last4, "renter_name": None, "meta": {}})

    def send(self, to, text):
        self.sent.append((to, text))
        return {"ok": True, "provider_id": f"SM{len(self.sent)}", "status": "queued"}


class FakeEmail:
    channel = "email"
    display = "info@rentus.homes"

    def __init__(self):
        self.inbox, self.sent = [], []

    def connected(self):
        return True, "fake"

    def poll(self, allow, since, seen):
        return [m for m in self.inbox if m["ext_id"] not in seen]

    def send(self, to, text, *, subject, in_reply_to=None, references=None):
        self.sent.append({"to": to, "text": text, "subject": subject, "in_reply_to": in_reply_to})
        return {"ok": True, "provider_id": f"em{len(self.sent)}", "status": "accepted"}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("LIVE_DIR", str(tmp_path / "live"))
    monkeypatch.setenv("DEMO_TEST_PHONE", OWNER_PHONE)
    monkeypatch.setenv("DEMO_TEST_EMAIL", OWNER_EMAIL)
    monkeypatch.setenv("LIVE_ALLOW_PHONES", "")
    monkeypatch.setenv("LIVE_ALLOW_EMAILS", "")
    monkeypatch.setenv("LIVE_ALLOW_MESSENGER_PSIDS", "")
    monkeypatch.setenv("LIVE_SEND_ENABLED", "1")
    monkeypatch.setenv("LIVE_MAX_PER_HOUR", "30")
    tf, loc, em = FakeSms("tollfree", "+18885550001"), FakeSms("local", "+19105550002"), FakeEmail()
    outbound.set_providers({"sms": {"tollfree": tf, "local": loc}, "email": em, "messenger": None})
    yield {"store": Store(), "tf": tf, "loc": loc, "email": em, "dir": tmp_path / "live"}
    outbound.set_providers(None)


def _all_text(d: Path) -> str:
    return "\n".join(p.read_text() for p in d.rglob("*") if p.is_file())


def test_allowlist_filters_strangers_entirely(env):
    tf = env["tf"]
    tf.push(OWNER_PHONE, "Hi, is the room available?", "SM-a")
    # a stranger's text that a provider might still hand back: dropped before storing
    tf.inbox.append({"channel": "sms", "contact": STRANGER, "text": "SECRET stranger text", "ext_id": "SM-b",
                     "ts": None, "line": "tollfree", "line_last4": "0001", "renter_name": None, "meta": {}})
    allow = config.Allowlist.load()
    allow.phones.add(STRANGER)  # provider-side filter passes it ...
    touched = daemon.poll_all(env["store"], allow=config.Allowlist.load())  # ... but the daemon re-checks
    assert len(touched) == 1
    threads = api.list_threads()
    assert len(threads) == 1 and threads[0]["contact_display"].endswith("0100")
    assert "SECRET stranger text" not in _all_text(env["dir"])


def test_threading_per_line_and_contact_and_restart(env):
    env["tf"].push(OWNER_PHONE, "first", "SM-1")
    env["tf"].push(OWNER_PHONE, "second", "SM-2")
    env["loc"].push(OWNER_PHONE, "other line", "SM-3")
    daemon.poll_all(env["store"])
    daemon.poll_all(Store())  # restart: same messages are not duplicated
    ids = sorted(t["thread_id"] for t in api.list_threads())
    assert ids == sorted([f"sms:0001:{ids[0].split(':')[2]}", f"sms:0002:{ids[0].split(':')[2]}"])
    t = api.get_thread([i for i in ids if ":0001:" in i][0])
    assert [m["text"] for m in t["messages"]] == ["first", "second"]
    assert t["unread"] == 2 and api.get_thread(t["thread_id"])["unread"] == 0


def test_email_reply_threads_and_keeps_subject(env):
    r = api.start_conversation("email", OWNER_EMAIL, "Hi, this is Rentus Homes testing our assistant.")
    assert r["status"] == "sent"
    first_subject = env["email"].sent[0]["subject"]
    assert "[ref " in first_subject
    env["email"].inbox.append({"channel": "email", "contact": OWNER_EMAIL, "text": "Is the room available?",
                               "ext_id": "<abc@mail.gmail.com>", "ts": None, "line": "info@rentus.homes",
                               "line_last4": None, "renter_name": "Owner",
                               "meta": {"subject": "Re: " + first_subject, "message_id": "<abc@mail.gmail.com>",
                                        "references": []}})
    daemon.poll_all(env["store"])
    assert len(api.list_threads()) == 1
    api.send_owner_message(r["thread_id"], "Yes it is.")
    last = env["email"].sent[-1]
    assert last["subject"] == "Re: " + first_subject and last["in_reply_to"] == "<abc@mail.gmail.com>"


def test_start_conversation_refuses_non_allowlisted(env):
    r = api.start_conversation("sms", STRANGER, "hello")
    assert r["ok"] is False and env["tf"].sent == []


def test_rate_cap(env, monkeypatch):
    monkeypatch.setenv("LIVE_MAX_PER_HOUR", "2")
    r = api.start_conversation("sms", OWNER_PHONE, "one")
    api.send_owner_message(r["thread_id"], "two")
    third = api.send_owner_message(r["thread_id"], "three")
    assert len(env["tf"].sent) == 2
    assert third["status"] == "awaiting_approval" and "rate cap" in third["error"]
    assert [a["draft_text"] for a in api.list_approvals()] == ["three"]


@pytest.mark.parametrize("how", ["env", "file"])
def test_kill_switch(env, monkeypatch, how):
    if how == "env":
        monkeypatch.setenv("LIVE_SEND_ENABLED", "0")
    else:
        env["dir"].mkdir(parents=True, exist_ok=True)
        (env["dir"] / "STOP").touch()
    r = api.start_conversation("sms", OWNER_PHONE, "hello")
    assert r["status"] == "awaiting_approval" and env["tf"].sent == []
    ap = api.list_approvals()[0]
    d = api.decide(ap["id"], "approve")
    assert d["ok"] is False and env["tf"].sent == [] and len(api.list_approvals()) == 1
    if how == "env":
        monkeypatch.setenv("LIVE_SEND_ENABLED", "1")
    else:
        (env["dir"] / "STOP").unlink()
    d = api.decide(ap["id"], "edit", "hello, edited")
    assert d["sent"] is True and env["tf"].sent == [(OWNER_PHONE, "hello, edited")]
    assert api.list_approvals() == []
    msgs = api.get_thread(r["thread_id"])["messages"]
    assert [(m["text"], m["status"]) for m in msgs] == [("hello, edited", "sent")]


def test_opt_out_stops_sending(env):
    env["tf"].push(OWNER_PHONE, "STOP", "SM-9")
    daemon.poll_all(env["store"])
    tid = api.list_threads()[0]["thread_id"]
    assert not env["store"].get_thread(tid).get("pending_turn")
    r = api.send_owner_message(tid, "hello?")
    assert r["ok"] is False and env["tf"].sent == []


class _Res:
    def __init__(self, events):
        self.messages, self.events, self.status = [{"role": "user", "content": "x"}], events, "done"


def test_operator_turn_sends_for_real_and_escalates(env):
    import rentus_tools as rt

    daemon.register_adapters(env["store"])
    env["tf"].push(OWNER_PHONE, "Hi, is the room still available?", "SM-10")
    daemon.poll_all(env["store"])
    tid = api.list_threads()[0]["thread_id"]

    def runner(w, inbound, history):
        assert w.mode == "live" and inbound["text"] == "Hi, is the room still available?"
        wid = inbound["thread_id"]
        assert ":" not in wid
        e1 = rt.call(w, "send_message", {"thread_id": wid, "text": "Yes, it is available Nov 1. When are you looking to move in?"})
        e2 = rt.call(w, "escalate_to_owner", {"reason": "asks about pets", "ref_id": wid, "draft": "Let me check on pets."})
        return _Res([{"type": "tool_result", "data": {"tool": "send_message", "result": e1}},
                     {"type": "tool_result", "data": {"tool": "escalate_to_owner", "result": e2}}])

    out = daemon.run_turn(env["store"], tid, runner=runner)
    assert out["ok"], out
    assert env["tf"].sent == [(OWNER_PHONE, "Yes, it is available Nov 1. When are you looking to move in?")]
    t = api.get_thread(tid)
    assert [m["direction"] for m in t["messages"]] == ["in", "out"] and t["messages"][1]["status"] == "sent"
    assert t["needs_owner"] and {x["name"] for x in t["trace"]} == {"send_message", "escalate_to_owner", "deliver_reply"}
    aps = api.list_approvals()
    assert aps[0]["draft_text"] == "Let me check on pets."
    assert api.decide(aps[0]["id"], "deny")["ok"]
    assert not api.get_thread(tid)["needs_owner"]
    # the world and history persist: a second inbound message continues the same World thread
    env["tf"].push(OWNER_PHONE, "Next month", "SM-11")
    daemon.poll_all(env["store"])
    seen = {}

    def runner2(w, inbound, history):
        seen["n"] = len(next(x for x in w.threads if x["thread_id"] == inbound["thread_id"])["messages"])
        seen["history"] = history
        return _Res([])

    daemon.run_turn(env["store"], tid, runner=runner2)
    assert seen["n"] == 3 and seen["history"] == [{"role": "user", "content": "x"}]


def test_turn_error_retries_then_asks_owner(env):
    env["tf"].push(OWNER_PHONE, "hello", "SM-20")
    daemon.poll_all(env["store"])
    tid = api.list_threads()[0]["thread_id"]

    def boom(w, inbound, history):
        raise RuntimeError("endpoint down")

    for _ in range(daemon.MAX_TURN_ATTEMPTS):
        assert daemon.run_turn(env["store"], tid, runner=boom)["ok"] is False
    t = env["store"].get_thread(tid)
    assert not t["pending_turn"] and t["needs_owner"]
    assert api.list_approvals()[0]["reason"].startswith("The assistant could not answer")


class FakePersonal:
    display = "owner's Messenger"

    def __init__(self):
        self.inbox, self.sent = [], []

    def connected(self):
        return True, "fake"

    def poll(self, allow, since, seen):
        return [m for m in self.inbox if m["ext_id"] not in seen]

    def send(self, contact, text):
        self.sent.append((contact, text))
        return {"ok": True, "provider_id": "pm1", "status": "sent"}


@pytest.mark.parametrize("drafts", ["0", "1"])
def test_personal_channel_unlisted_drafts_only(env, monkeypatch, drafts):
    from channels.live import registry
    import rentus_tools as rt

    monkeypatch.setenv("LIVE_PERSONAL_DRAFTS", drafts)
    prov = FakePersonal()
    registry.register_channel("messenger_personal", prov)
    try:
        prov.inbox.append({"channel": "messenger_personal", "contact": "fb-user-77", "text": "Is this available?",
                           "ext_id": "pm-1", "ts": None, "renter_name": "Dana R", "meta": {}})
        daemon.register_adapters(env["store"])
        daemon.poll_all(env["store"])
        threads = api.list_threads()
        if drafts == "0":
            assert threads == [] and "Is this available" not in _all_text(env["dir"])
            return
        assert len(threads) == 1 and threads[0]["channel"] == "messenger_personal"
        tid = threads[0]["thread_id"]

        def runner(w, inbound, history):
            assert next(x for x in w.threads if x["thread_id"] == inbound["thread_id"])["channel"] == "marketplace"
            rt.call(w, "send_message", {"thread_id": inbound["thread_id"], "text": "Yes, it is available Nov 1. When would you move in?"})
            return _Res([])

        daemon.run_turn(env["store"], tid, runner=runner)
        assert prov.sent == []
        msg = api.get_thread(tid)["messages"][-1]
        assert msg["status"] == "awaiting_approval"
        ap = api.list_approvals()[0]
        assert api.decide(ap["id"], "approve")["sent"] is True
        assert prov.sent == [("fb-user-77", "Yes, it is available Nov 1. When would you move in?")]
    finally:
        registry.unregister("messenger_personal")


# ---------------------------------------------------------------- review round 2 regressions

def _blocked_approval(env, monkeypatch):
    monkeypatch.setenv("LIVE_SEND_ENABLED", "0")
    r = api.start_conversation("sms", OWNER_PHONE, "draft one")
    monkeypatch.setenv("LIVE_SEND_ENABLED", "1")
    return r, api.list_approvals()[0]


def test_1_approve_sends_once_and_uses_given_text(env, monkeypatch):
    r, ap = _blocked_approval(env, monkeypatch)
    first = api.decide(ap["id"], "approve", "owner's wording")
    second = api.decide(ap["id"], "approve")
    assert first["sent"] is True and second["ok"] is False
    assert env["tf"].sent == [(OWNER_PHONE, "owner's wording")]


def test_1_claimed_approval_cannot_be_decided_again(env, monkeypatch):
    r, ap = _blocked_approval(env, monkeypatch)
    st = env["store"]
    with st.locked():  # another process has claimed it and is sending right now
        items = st.approvals()
        items[0]["status"] = "sending"
        st.save_approvals(items)
    assert api.decide(ap["id"], "approve")["ok"] is False and env["tf"].sent == []


def test_2_owner_sends_still_respect_kill_switch_optout_and_cap(env, monkeypatch):
    from channels.live import config as cfg
    r = api.start_conversation("sms", OWNER_PHONE, "one")
    tid = r["thread_id"]
    st = env["store"]
    t = st.get_thread(tid)
    t["contact"] = STRANGER  # not allowlisted: skip_allowlist lifts only that check
    allow = cfg.Allowlist.load()
    assert outbound._gate(st, t, allow, skip_allowlist=True) is None
    (env["dir"] / "STOP").touch()
    assert "switched off" in outbound._gate(st, t, allow, skip_allowlist=True)
    assert api.send_owner_message(tid, "two")["status"] == "awaiting_approval"
    (env["dir"] / "STOP").unlink()
    monkeypatch.setenv("LIVE_MAX_PER_HOUR", "1")
    assert "rate cap" in outbound._gate(st, t, allow, skip_allowlist=True)
    assert api.send_owner_message(tid, "three")["status"] == "awaiting_approval"
    monkeypatch.setenv("LIVE_MAX_PER_HOUR", "30")
    with st.locked():
        tt = st.get_thread(tid)
        tt["opted_out"] = True
        st.save_thread(tt)
    assert api.send_owner_message(tid, "four")["status"] == "failed"
    assert env["tf"].sent == [(OWNER_PHONE, "one")]


def test_3_model_error_is_a_failed_attempt(env):
    env["tf"].push(OWNER_PHONE, "hello", "SM-30")
    daemon.poll_all(env["store"])
    tid = api.list_threads()[0]["thread_id"]
    daemon._MODEL["model"] = "cached"

    class Bad:
        messages, events, status, final_text = [], [], "model_error", "HTTP 500"

    for i in range(daemon.MAX_TURN_ATTEMPTS):
        assert daemon.run_turn(env["store"], tid, runner=lambda w, i_, h: Bad())["ok"] is False
        assert "model" not in daemon._MODEL  # re-probed next time
        t = env["store"].get_thread(tid)
        assert t.get("world_synced", []) == [] and not t["busy"]
    assert not t["pending_turn"] and api.list_approvals()[0]["kind"] == "error"
    assert "reply by hand" in api.list_approvals()[0]["reason"]


def test_6_single_daemon_lock(env):
    st = env["store"]
    fh = daemon.acquire_daemon_lock(st)
    try:
        with pytest.raises(daemon.DaemonRunning):
            daemon.acquire_daemon_lock(Store())
        assert daemon.main(once=True) == 3
    finally:
        fh.close()
    daemon.acquire_daemon_lock(st).close()


def test_6_busy_marker_blocks_a_second_turn_and_is_exposed(env):
    import os
    env["tf"].push(OWNER_PHONE, "hello", "SM-40")
    daemon.poll_all(env["store"])
    tid = api.list_threads()[0]["thread_id"]
    st = env["store"]
    with st.locked():
        t = st.get_thread(tid)
        t.update(busy=True, busy_since="2026-10-18T08:00:00-04:00", turn_owner=os.getppid())  # a live other pid
        st.save_thread(t)
    s = api.list_threads()[0]
    assert s["busy"] is True and s["busy_since"] and s["queued"] is False
    called = []
    assert daemon.run_turn(st, tid, runner=lambda w, i, h: called.append(1) or _Res([]))["skipped"]
    seen = {}

    def runner(w, i, h):
        seen["busy"] = api.get_thread(tid)["busy"]
        return _Res([])

    with st.locked():
        t = st.get_thread(tid)
        t["turn_owner"] = 2 ** 22 + 12345  # dead pid: stale marker is taken over
        st.save_thread(t)
    assert daemon.run_turn(st, tid, runner=runner)["ok"] and seen["busy"] is True and not called
    assert api.get_thread(tid)["busy"] is False


def test_9_thread_id_validation(env):
    assert env["store"].get_thread("../../etc/passwd") is None
    assert api.get_thread("sms:../x").get("error")
    with pytest.raises(ValueError):
        env["store"]._tpath("email:a/b")


def test_c_one_readable_report_per_thread(env):
    import rentus_tools as rt
    daemon.register_adapters(env["store"])
    env["tf"].push(OWNER_PHONE, "hello", "SM-50")
    daemon.poll_all(env["store"])
    tid = api.list_threads()[0]["thread_id"]

    def runner(w, inbound, h):
        rt.call(w, "report_to_owner", {"summary": f"New inquiry on thread {inbound['thread_id']} (renter:renter)."})
        rt.call(w, "report_to_owner", {"summary": "Asked for move-in date."})
        return _Res([])

    daemon.run_turn(env["store"], tid, runner=runner)
    env["tf"].push(OWNER_PHONE, "again", "SM-51")
    daemon.poll_all(env["store"])
    daemon.run_turn(env["store"], tid, runner=runner)
    reps = [a for a in api.list_approvals() if a["kind"] == "report"]
    assert len(reps) == 1
    assert "t_sms" not in reps[0]["reason"] and "renter:" not in reps[0]["reason"]
    assert "Asked for move-in date." in reps[0]["reason"]


# ---------------------------------------------------------------- round 3: one reply per turn, answer first

BURST = ["It's a bedroom in a house on Appling Way in Durham, with a private bathroom and its own entrance.",
         "Rent is $750 a month.", "It's available from November 1, and the lease is 1 year.",
         "How long do you want to stay? Is a one year lease okay with you?",
         "Is a one year lease okay with you?"]


def test_compose_dedupes_keeps_last_question_and_answers_first():
    from channels.live import compose
    parts = compose.compose(BURST, "sms", "Hello, how much is the rent?")
    text = " ".join(parts)
    assert text.startswith("Rent is $750 a month.")
    assert text.count("?") == 1 and text.endswith("Is a one year lease okay with you?")
    assert len(parts) == 1 and len(parts[0]) <= compose.SMS_MAX
    assert compose.compose(["Hi there.", "hi there!"], "sms") == ["Hi there."]


def test_compose_splits_long_sms_in_two_and_email_is_one():
    from channels.live import compose
    long = [f"Fact number {i} about the room is quite a long sentence to read." for i in range(8)] + ["Okay?"]
    sms = compose.compose(long, "sms")
    assert len(sms) == 2 and sms[1].endswith("Okay?")
    assert len(compose.compose(long, "email")) == 1
    assert len(compose.compose(long, "messenger")) <= 2


def test_burst_of_sends_goes_out_as_one_sms(env):
    import rentus_tools as rt
    daemon.register_adapters(env["store"])
    env["tf"].push(OWNER_PHONE, "Hello, how much is the rent?", "SM-60")
    daemon.poll_all(env["store"])
    tid = api.list_threads()[0]["thread_id"]

    def runner(w, inbound, h):
        for text in BURST[1:4]:
            assert rt.call(w, "send_message", {"thread_id": inbound["thread_id"], "text": text})["ok"]
        return _Res([])

    daemon.run_turn(env["store"], tid, runner=runner)
    assert len(env["tf"].sent) == 1
    sent = env["tf"].sent[0][1]
    assert sent.startswith("Rent is $750 a month.") and sent.count("?") == 1
    outs = [m for m in api.get_thread(tid)["messages"] if m["direction"] == "out"]
    assert len(outs) == 1 and outs[0]["status"] == "sent"


def test_live_note_is_added_to_the_system_prompt(env):
    from channels.live import compose
    from rentus_operator.config import RunConfig
    w = daemon._new_world({"thread_id": "sms:0001:abc", "channel": "sms", "renter_name": ""})
    h = daemon.with_live_note(None, RunConfig(**daemon.FINAL_CONFIG), w)
    assert h[0]["role"] == "system" and h[0]["content"].endswith(compose.LIVE_NOTE)
    old = [{"role": "system", "content": "old prompt"}, {"role": "user", "content": "x"}]
    h2 = daemon.with_live_note(old, None, w)
    assert compose.LIVE_NOTE in h2[0]["content"] and h2[1] == old[1]
    assert daemon.with_live_note(h2, None, w)[0]["content"].count(compose.LIVE_NOTE) == 1


def test_compose_drops_a_restated_fact_but_keeps_different_numbers():
    from channels.live import compose
    out = " ".join(compose.compose(["I have a room on Appling Way with a private bath for $750 a month.",
                                    "Rent is $750 a month.", "Rent is $850 for the other room.", "Okay?"], "sms"))
    assert out.count("$750") == 1 and "$850" in out
