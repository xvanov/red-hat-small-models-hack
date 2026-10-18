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

from channels.live import api, config, daemon, demo, outbound  # noqa: E402
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

    def poll(self, allow, since, seen, include_unlisted=False):  # like Twilio: From=allowlisted unless demo mode
        return [m for m in self.inbox if m["ext_id"] not in seen
                and (include_unlisted or config.normalize_phone(m["contact"]) in allow.phones)]

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

    def send(self, to, text, *, subject, in_reply_to=None, references=None, html=None, extra_headers=None,
             reply_to=None):
        self.sent.append({"to": to, "text": text, "subject": subject, "in_reply_to": in_reply_to,
                          "references": references, "html": html, "headers": extra_headers, "reply_to": reply_to})
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
    for k in ("LIVE_PUBLIC_MODE", "LIVE_PUBLIC_DEMO", "LIVE_ROLE_SMS", "LIVE_ROLE_EMAIL", "LIVE_ROLE_MESSENGER",
              "LIVE_LEASE_LINK_URL", "LIVE_DEMO_EMAIL_TO"):
        monkeypatch.setenv(k, "")
    monkeypatch.setenv("LIVE_DEBOUNCE_S", "0")
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
    first = env["email"].sent[0]
    assert first["subject"] == "Your room at Appling Way \u2013 next steps" and "[ref" not in first["subject"]
    assert first["in_reply_to"] is None and first["headers"]["X-Rentus-Ref"]
    env["email"].inbox.append({"channel": "email", "contact": OWNER_EMAIL, "text": "Is the room available?",
                               "ext_id": "<abc@mail.gmail.com>", "ts": "2026-10-18T08:10:00-04:00",
                               "line": "info@rentus.homes", "line_last4": None, "renter_name": "Kalin Ivanov",
                               "meta": {"subject": "Re: " + first["subject"], "message_id": "<abc@mail.gmail.com>",
                                        "references": ["<first@resend>"]}})
    daemon.poll_all(env["store"])
    assert len(api.list_threads()) == 1
    api.send_owner_message(r["thread_id"], "Yes it is.\n\nHere's the link to complete your application: https://x.test/apply")
    last = env["email"].sent[-1]
    assert last["subject"] == "Re: " + first["subject"] and last["in_reply_to"] == "<abc@mail.gmail.com>"
    assert last["references"] == ["<first@resend>", "<abc@mail.gmail.com>"]
    body = last["text"]
    assert body.startswith("Hi Kalin,\n\nYes it is.") and "Best,\nKalin\nRentus Homes" in body
    assert "wrote:\n> Is the room available?" in body and "On Sun, Oct 18, 2026 at 8:10 AM, Kalin Ivanov" in body
    assert '<a href="https://x.test/apply">' in last["html"] and "<blockquote" in last["html"]


def test_new_email_from_renter_keeps_their_subject(env):
    env["email"].inbox.append({"channel": "email", "contact": OWNER_EMAIL, "text": "Ready to sign",
                               "ext_id": "<m1@mail>", "ts": None, "line": "info@rentus.homes", "line_last4": None,
                               "renter_name": "Kalin", "meta": {"subject": "Lease", "message_id": "<m1@mail>",
                                                                "references": []}})
    daemon.poll_all(env["store"])
    api.send_owner_message(api.list_threads()[0]["thread_id"], "Sure.")
    assert env["email"].sent[-1]["subject"] == "Re: Lease"


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
         "Rent is $750 a month.", "It's available from November 1.",
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
    assert h[0]["role"] == "system" and compose.LIVE_NOTE in h[0]["content"]
    old = [{"role": "system", "content": "old prompt"}, {"role": "user", "content": "x"}]
    h2 = daemon.with_live_note(old, None, w)
    assert compose.LIVE_NOTE in h2[0]["content"] and h2[1] == old[1]
    assert daemon.with_live_note(h2, None, w)[0]["content"].count(compose.LIVE_NOTE) == 1


def test_compose_drops_a_restated_fact_but_keeps_different_numbers():
    from channels.live import compose
    out = " ".join(compose.compose(["I have a room on Appling Way with a private bath for $750 a month.",
                                    "Rent is $750 a month.", "Rent is $850 for the other room.", "Okay?"], "sms"))
    assert out.count("$750") == 1 and "$850" in out


# ---------------------------------------------------------------- round 4: roles (tenant, lease signing)

def test_tenant_role_seeds_tenant_record_and_stage(env, monkeypatch):
    import rentus_tools as rt
    monkeypatch.setenv("LIVE_ROLE_SMS", "tenant")
    daemon.register_adapters(env["store"])
    env["tf"].push(OWNER_PHONE, "hey my kitchen sink is leaking", "SM-70")
    daemon.poll_all(env["store"])
    s = api.list_threads()[0]
    assert s["role"] == "tenant" and s["stage"] == "tenant" and "Current tenant" in s["context"]

    def runner(w, inbound, h):
        assert w.tenants[0]["tenant_id"] == "TEN_KALIN" and w.tenants[0]["lease"]["rent"] == 750
        env_ = rt.call(w, "get_ledger", {"thread_id": inbound["thread_id"]})
        assert env_["ok"], env_
        assert rt.call(w, "triage_maintenance", {"thread_id": inbound["thread_id"]})["ok"]
        return _Res([])

    assert daemon.run_turn(env["store"], s["thread_id"], runner=runner)["ok"]
    assert api.get_thread(s["thread_id"])["stage"] == "tenant"


def test_lease_signing_tool_adds_link_to_one_email(env, monkeypatch):
    import rentus_tools as rt
    monkeypatch.setenv("LIVE_ROLE_EMAIL", "lease_signing")
    monkeypatch.setenv("LIVE_LEASE_LINK_URL", "https://app.rentus.homes/sign/TESTTOKEN")
    daemon.register_adapters(env["store"])
    env["email"].inbox.append({"channel": "email", "contact": OWNER_EMAIL, "text": "I'm ready to sign, can you send the lease?",
                               "ext_id": "<x1@mail>", "ts": None, "line": "info@rentus.homes", "line_last4": None,
                               "renter_name": "Kalin", "meta": {"subject": "Lease", "message_id": "<x1@mail>", "references": []}})
    daemon.poll_all(env["store"])
    s = api.list_threads()[0]
    assert s["stage"] == "lease_signing" and "Approved applicant" in s["context"]

    def runner(w, inbound, h):
        assert next(r for r in w.register if inbound["thread_id"] in r["thread_ids"])["status"] == "applied"
        e = rt.call(w, "send_lease_link", {"thread_id": inbound["thread_id"]})
        assert e["ok"], e
        assert rt.call(w, "send_message", {"thread_id": inbound["thread_id"], "text": "The lease link is included in this message."})["ok"]
        return _Res([])

    daemon.run_turn(env["store"], s["thread_id"], runner=runner)
    assert len(env["email"].sent) == 1
    body = env["email"].sent[0]["text"]
    assert "Here's the link to review and sign your lease: https://app.rentus.homes/sign/TESTTOKEN" in body
    assert "included" not in body and env["email"].sent[0]["subject"] == "Re: Lease"
    s = api.list_threads()[0]
    assert s["stage"] == "lease_sent" and "lease link sent" in s["context"]


def test_lease_tool_refuses_non_applicants(env):
    import rentus_tools as rt
    daemon.register_adapters(env["store"])
    w = daemon._new_world({"thread_id": "sms:0001:abc", "channel": "sms", "renter_name": "", "role": "prospect"})
    e = rt.call(w, "send_lease_link", {"thread_id": w.threads[0]["thread_id"]})
    assert not e["ok"] and e["error"]["code"] == "POLICY_BLOCKED"


def test_lease_link_falls_back_to_public_apply_page(env, monkeypatch):
    from channels.live import lease_link
    monkeypatch.delenv("LIVE_LEASE_LINK_URL", raising=False)
    monkeypatch.setenv("LIVE_LEASE_LINK_URL", "")
    assert lease_link.get_link().endswith("/apply") and lease_link.get_link().startswith("https://")



# ---------------------------------------------------------------- round 5

def test_readable_reasons_have_no_dangling_ids():
    r = daemon.readable("Kalin is ready to sign the lease for room R100. Lease link sent to owner.test@example.com.",
                        name="Kalin")
    assert r.endswith("Lease link sent to Kalin.") and "@" not in r
    r = daemon.readable("Tenant Kalin on thread t_sms_2046_633d2ea5d4 reported a leak (renter:kalin).", name="Kalin")
    assert r == "Tenant Kalin reported a leak."


def test_archive_hides_thread_and_next_message_starts_fresh(env):
    env["tf"].push(OWNER_PHONE, "first", "SM-80")
    daemon.poll_all(env["store"])
    old = api.list_threads()[0]["thread_id"]
    env["store"].add_approval(old, "x", "")
    assert api.archive_thread("all")["archived"] == [old]
    assert api.list_threads() == [] and api.list_approvals() == []
    assert len(api.list_threads(include_archived=True)) == 1
    env["tf"].push(OWNER_PHONE, "second", "SM-81")
    daemon.poll_all(env["store"])
    new = api.list_threads()
    assert len(new) == 1 and new[0]["thread_id"] == old + ":2"
    assert [m["text"] for m in api.get_thread(new[0]["thread_id"])["messages"]] == ["second"]
    assert api.unarchive_thread(old)["ok"] and len(api.list_threads()) == 2


def test_dismiss_approval(env, monkeypatch):
    r, ap = _blocked_approval(env, monkeypatch)
    assert api.dismiss_approval(ap["id"])["ok"] and api.list_approvals() == []
    assert api.dismiss_approval(ap["id"])["ok"] is False and env["tf"].sent == []


def test_local_910_line_is_opt_in(monkeypatch):
    monkeypatch.delenv("LIVE_SMS_LINES", raising=False)
    from channels.live import config as cfg
    monkeypatch.setattr(cfg, "_repo_env", lambda: {})
    assert all(l.name == "tollfree" for l in cfg.sms_lines())



# ---------------------------------------------------------------- public demo mode

@pytest.fixture
def demo_env(env, monkeypatch):
    import rentus_tools as rt
    monkeypatch.setenv("LIVE_PUBLIC_DEMO", "1")
    monkeypatch.setenv("LIVE_DEMO_CODE", "DEMO")
    daemon.register_adapters(env["store"])

    def runner(w, inbound, h):
        rt.call(w, "send_message", {"thread_id": inbound["thread_id"], "text": "Rent is $750 a month. When do you want to move in?"})
        return _Res([])

    env["runner"] = runner
    return env


def _tick(env):
    daemon.poll_all(env["store"])
    for t in env["store"].all_threads():
        if t.get("pending_turn"):
            daemon.run_turn(env["store"], t["thread_id"], runner=env["runner"])


def test_demo_off_by_default_ignores_code(env):
    env["tf"].push(STRANGER, "DEMO hi", "SM-d0")
    daemon.poll_all(env["store"])
    assert api.list_threads() == []


def test_demo_stranger_without_code_is_ignored_for_good(demo_env):
    demo_env["tf"].push(STRANGER, "Hi, is my rent due Friday?", "SM-d1")
    _tick(demo_env)
    demo_env["tf"].push(STRANGER, "demo", "SM-d2")  # code only counts in the FIRST message
    _tick(demo_env)
    assert api.list_threads() == [] and demo_env["tf"].sent == []
    assert "rent due Friday" not in _all_text(demo_env["dir"])


def test_demo_code_enrolls_and_discloses_once(demo_env):
    demo_env["tf"].push(STRANGER, "Demo: how much is the room?", "SM-d3")
    _tick(demo_env)
    s = api.list_threads()[0]
    assert s["demo"] is True and s["role"] == "prospect"
    assert demo_env["tf"].sent[0][1].startswith("You're chatting with Rentus Homes' AI assistant (demo). Reply STOP to end.")
    demo_env["tf"].push(STRANGER, "next month", "SM-d4")
    _tick(demo_env)
    assert len(demo_env["tf"].sent) == 2 and "AI assistant" not in demo_env["tf"].sent[1][1]
    assert not demo.has_code("DEMOS please") and demo.has_code("this is a demo.")


def test_demo_per_contact_daily_cap(demo_env, monkeypatch):
    monkeypatch.setenv("LIVE_DEMO_MAX_PER_DAY", "2")
    for i, txt in enumerate(["DEMO hi", "a", "b", "c"]):
        demo_env["tf"].push(STRANGER, txt, f"SM-c{i}")
        _tick(demo_env)
    assert len(demo_env["tf"].sent) == 2 and api.list_approvals() == []


def test_demo_stop_ends_it(demo_env):
    demo_env["tf"].push(STRANGER, "DEMO hi", "SM-s1")
    _tick(demo_env)
    demo_env["tf"].push(STRANGER, "STOP", "SM-s2")
    demo_env["tf"].push(STRANGER, "hello again", "SM-s3")
    _tick(demo_env)
    assert len(demo_env["tf"].sent) == 1 and api.list_threads()[0]["opted_out"]


# ---------------------------------------------------------------- public OPEN mode (owner decision: no keyword)

@pytest.fixture
def open_env(demo_env, monkeypatch):
    monkeypatch.setenv("LIVE_PUBLIC_DEMO", "0")
    monkeypatch.setenv("LIVE_PUBLIC_MODE", "open")
    return demo_env


def _push_at(fake, frm, text, sid, ts):
    fake.push(frm, text, sid)
    fake.inbox[-1]["ts"] = ts


def test_open_mode_enrolls_anyone_and_discloses(open_env):
    from datetime import datetime, timezone
    _push_at(open_env["tf"], STRANGER, "how much is the room?", "SM-o1", datetime.now(timezone.utc).isoformat())
    _tick(open_env)
    s = api.list_threads()[0]
    assert s["demo"] and s["role"] == "prospect"
    assert open_env["tf"].sent[0][1].startswith("Hi, you're chatting with Rentus Homes' AI assistant. Rent is $750")
    assert demo.max_per_day() == 30


def test_open_mode_skips_backlog_short_codes_and_bots(open_env):
    from datetime import datetime, timedelta, timezone
    old = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    with open_env["store"].locked():
        demo.open_since(open_env["store"])  # open mode switched on now
    _push_at(open_env["tf"], STRANGER, "old message", "SM-o2", old)
    _push_at(open_env["tf"], "72345", "Your code is 1234", "SM-o3", datetime.now(timezone.utc).isoformat())
    _tick(open_env)
    assert api.list_threads() == [] and open_env["tf"].sent == []
    assert demo.is_automated("email", "no-reply@zillow.com") and demo.is_automated("email", "MAILER-DAEMON@x.com")
    assert demo.is_automated("email", "jane@example.com", {"automated": True})
    assert not demo.is_automated("email", "jane@example.com") and not demo.is_automated("sms", "+19195550199")


def test_open_mode_global_cap_default(open_env, monkeypatch):
    monkeypatch.delenv("LIVE_MAX_PER_HOUR")
    monkeypatch.setattr(config, "_repo_env", lambda: {})
    assert config.max_per_hour() == 150


def test_open_mode_owner_contacts_keep_their_role(open_env, monkeypatch):
    from datetime import datetime, timezone
    monkeypatch.setenv("LIVE_ROLE_SMS", "tenant")
    _push_at(open_env["tf"], OWNER_PHONE, "sink leaking", "SM-o4", datetime.now(timezone.utc).isoformat())
    daemon.poll_all(open_env["store"])
    s = api.list_threads()[0]
    assert s["role"] == "tenant" and not s["demo"]


# ---------------------------------------------------------------- Zoho info@ inbox (read-only) + skip rules

def _raw(frm, subject="Room on Appling Way", body="Hi, is the room still available?", **headers):
    from email.message import EmailMessage
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = frm, "info@rentus.homes", subject
    m["Message-ID"] = f"<{abs(hash((frm, subject)))}@mail.example>"
    m["Date"] = "Sun, 18 Oct 2026 08:30:00 -0400"
    for k, v in headers.items():
        m[k.replace("_", "-")] = v
    m.set_content(body)
    return m


def test_zoho_parse_and_skip_rules():
    from channels.live import providers as pv
    ours = {"info@rentus.homes"}
    human = pv.parse_inbox_message(bytes(_raw("Jane Doe <jane@example.com>")), ours=ours)
    assert human["contact"] == "jane@example.com" and not human["meta"]["automated"]
    assert human["renter_name"] == "Jane Doe" and human["meta"]["inbox"] == "zoho"
    assert pv.parse_inbox_message(bytes(_raw("Rentus Homes <info@rentus.homes>")), ours=ours) is None
    bots = [_raw("Jane <jane@example.com>", Auto_Submitted="auto-replied"),
            _raw("News <jane@example.com>", List_Unsubscribe="<mailto:x@y>"),
            _raw("Jane <jane@example.com>", Precedence="bulk"),
            _raw("No Reply <no-reply@example.com>"),
            _raw("Zillow <notifications@zillow.com>"),
            _raw("FF <leads@furnishedfinder.com>"),
            _raw("Jane <jane@example.com>", subject="Invitation: Showing @ Sat"),
            _raw("Jane <jane@example.com>", subject="Automatic reply: Room")]
    cal = _raw("Jane <jane@example.com>")
    cal.add_attachment(b"BEGIN:VCALENDAR", maintype="text", subtype="calendar", filename="invite.ics")
    bots.append(cal)
    for b in bots:
        assert pv.parse_inbox_message(bytes(b), ours=ours)["meta"]["automated"], b["From"]
    assert demo.is_automated("email", "jane@example.com", {"automated": True})


class FakeImap:
    def __init__(self, msgs):
        self.msgs, self.calls = msgs, []

    def login(self, u, p):
        pass

    def select(self, box, readonly=False):
        assert readonly is True
        return "OK", [str(len(self.msgs)).encode()]

    def uid(self, cmd, *args):
        self.calls.append((cmd, args))
        if cmd == "SEARCH":
            return "OK", [" ".join(str(i + 1) for i in range(len(self.msgs))).encode()]
        assert "BODY.PEEK[]" in args[1] and "INTERNALDATE" in args[1]
        idate, raw = self.msgs[int(args[0]) - 1]
        return "OK", [(f'{args[0].decode()} (INTERNALDATE "{idate}" BODY[] {{1}}'.encode(), raw), b")"]

    def logout(self):
        pass


def test_zoho_poll_is_read_only_and_skips_backlog():
    from datetime import datetime, timezone
    from channels.live import providers as pv
    imap = FakeImap([("18-Oct-2026 07:00:00 -0400", bytes(_raw("Old <old@example.com>", subject="old"))),
                     ("18-Oct-2026 08:30:00 -0400", bytes(_raw("Jane <jane@example.com>"))),
                     ("18-Oct-2026 08:31:00 -0400", bytes(_raw("Rentus <info@rentus.homes>", subject="copy")))])
    z = pv.ZohoInbox("info@rentus.homes", "pw", {"info@rentus.homes"}, imap_factory=lambda: imap)
    since = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)  # 08:00 ET
    items = z.poll(config.Allowlist(), since, set(), include_unlisted=True)
    assert [i["contact"] for i in items] == ["jane@example.com"]
    assert z.poll(config.Allowlist(), since, set(), include_unlisted=False) == []
    assert all(c[0] in ("SEARCH", "FETCH") for c in imap.calls)


def test_zoho_stranger_reply_stays_on_info(open_env):
    from datetime import datetime, timezone
    item = {"channel": "email", "contact": "jane@example.com", "text": "Is the room available?",
            "ext_id": "<j1@mail>", "ts": datetime.now(timezone.utc).isoformat(), "line": "info@rentus.homes",
            "line_last4": None, "renter_name": "Jane Doe",
            "meta": {"subject": "Room on Appling Way", "message_id": "<j1@mail>", "references": [],
                     "automated": False, "inbox": "zoho"}}

    class Z:
        def poll(self, allow, since, seen, include_unlisted=False):
            return [item] if include_unlisted and item["ext_id"] not in seen else []

    outbound.get_providers()["email_zoho"] = Z()
    _tick(open_env)
    sent = open_env["email"].sent[-1]
    assert sent["to"] == "jane@example.com" and sent["reply_to"] == "info@rentus.homes"
    assert sent["subject"] == "Re: Room on Appling Way" and sent["in_reply_to"] == "<j1@mail>"
    assert sent["text"].startswith("Hi Jane,\n\nYou're chatting with Rentus Homes' AI assistant.")


# ---------------------------------------------------------------- round 8: per-source pollers, immediate turns

def test_sms_not_blocked_by_hanging_imap(env, monkeypatch):
    import threading
    import time as _t
    monkeypatch.setenv("LIVE_POLL_SMS", "0.1")
    hang = threading.Event()

    class HangingImap:
        def poll(self, *a, **k):
            hang.wait(30)  # an IMAP server that never answers
            return []

    outbound.get_providers()["email"] = HangingImap()
    outbound.get_providers()["email_zoho"] = HangingImap()
    daemon.register_adapters(env["store"])
    import rentus_tools as rt

    def turn(tid):
        def runner(w, inbound, h):
            rt.call(w, "send_message", {"thread_id": inbound["thread_id"], "text": "Rent is $750 a month."})
            return _Res([])
        return daemon.run_turn(env["store"], tid, runner=runner)

    r = daemon.Runner(env["store"], outbound.get_providers(), turn=turn, log=lambda *a: None).start()
    try:
        _t.sleep(0.3)
        t0 = _t.time()
        env["tf"].push(OWNER_PHONE, "how much?", "SM-r1")
        while not env["tf"].sent and _t.time() - t0 < 5:
            _t.sleep(0.05)
        assert env["tf"].sent and _t.time() - t0 < 2.0
    finally:
        r.close()
        hang.set()


# ---------------------------------------------------------------- live bug: duplicate sends / concurrent turns

def test_two_workers_cannot_run_the_same_thread(env):
    import threading
    import time as _t
    import rentus_tools as rt
    daemon.register_adapters(env["store"])
    env["tf"].push(OWNER_PHONE, "my toilet is leaking", "SM-x1")
    daemon.poll_all(env["store"])
    tid = api.list_threads()[0]["thread_id"]
    started = []

    def slow(w, inbound, h):
        started.append(1)
        _t.sleep(0.5)
        rt.call(w, "send_message", {"thread_id": inbound["thread_id"], "text": "Where is the water coming from?"})
        return _Res([])

    ths = [threading.Thread(target=daemon.run_turn, args=(env["store"], tid), kwargs={"runner": slow}) for _ in range(3)]
    for th in ths:
        th.start()
    for th in ths:
        th.join()
    assert len(started) == 1 and len(env["tf"].sent) == 1
    assert env["store"].get_thread(tid)["busy"] is False


def test_never_resend_one_of_the_last_three_replies(env):
    import rentus_tools as rt
    daemon.register_adapters(env["store"])
    q = "I'm sorry to hear about the leak. Where exactly is the water coming from?"
    for i, msg in enumerate(["Hi, my toilet is leaking", "Toilet"]):
        env["tf"].push(OWNER_PHONE, msg, f"SM-y{i}")
        daemon.poll_all(env["store"])
        tid = api.list_threads()[0]["thread_id"]
        daemon.run_turn(env["store"], tid, runner=lambda w, i_, h: (
            rt.call(w, "send_message", {"thread_id": i_["thread_id"], "text": q}), _Res([]))[1])
    assert len(env["tf"].sent) == 1
    # also outside a turn (unbuffered operator send)
    assert outbound.deliver(env["store"], tid, q.upper(), origin="operator")["status"] == "duplicate_skipped"
    assert len(env["tf"].sent) == 1



def test_signature_and_quote_are_stripped():
    from channels.live import providers as pv
    body = "Is the room still available?\n\nThanks,\nJane\nSent from my iPhone\n\nOn Sat, Oct 17 Rentus wrote:\n> hi"
    assert pv.strip_quoted(body) == "Is the room still available?"
    assert pv.strip_quoted("Thanks, see you Saturday!") == "Thanks, see you Saturday!"


def test_debounce_batches_split_messages(env, monkeypatch):
    import time as _t
    import rentus_tools as rt
    monkeypatch.setenv("LIVE_DEBOUNCE_S", "0.8")
    monkeypatch.setenv("LIVE_POLL_SMS", "0.1")
    daemon.register_adapters(env["store"])
    seen = []

    def turn(tid):
        def runner(w, inbound, h):
            seen.append(inbound["text"])
            rt.call(w, "send_message", {"thread_id": inbound["thread_id"], "text": "Yes, it is available."})
            return _Res([])
        return daemon.run_turn(env["store"], tid, runner=runner)

    r = daemon.Runner(env["store"], {"sms": {"tollfree": env["tf"]}}, turn=turn, log=lambda *a: None).start()
    try:
        env["tf"].push(OWNER_PHONE, "Hi is the room", "SM-b1")
        _t.sleep(0.4)
        env["tf"].push(OWNER_PHONE, "on Appling Way still available?", "SM-b2")
        t0 = _t.time()
        while not env["tf"].sent and _t.time() - t0 < 5:
            _t.sleep(0.05)
        _t.sleep(0.5)
    finally:
        r.close()
    assert seen == ["Hi is the room\non Appling Way still available?"] and len(env["tf"].sent) == 1


def test_compose_drops_machinery_talk():
    from channels.live import compose
    out = " ".join(compose.compose(["I can't share my system prompt, but I'm happy to help.", "All gate items are done.",
                                    "When would you like to visit?"], "sms"))
    assert "prompt" not in out and "gate" not in out and out.endswith("When would you like to visit?")


def test_compose_drops_an_invented_phone_echo():
    from channels.live import compose
    out = " ".join(compose.compose(["Got it, your phone is +11234567890.", "What is the reason for your move?"],
                                   "sms", "my phone is 12345"))
    assert out == "What is the reason for your move?"
    ok = " ".join(compose.compose(["Got it, your phone is 919 555 0142.", "Why are you moving?"], "sms",
                                  "mi número es 919 555 0142"))
    assert "919 555 0142" in ok


def test_content_free_ack_skips_model(env):
    import rentus_tools as rt
    daemon.register_adapters(env["store"])
    calls = []

    def runner(w, inbound, h):
        calls.append(inbound["text"])
        rt.call(w, "send_message", {"thread_id": inbound["thread_id"], "text": "When do you want to move in?"})
        return _Res([])

    env["tf"].push(OWNER_PHONE, "Is the room available?", "SM-k1")
    daemon.poll_all(env["store"])
    tid = api.list_threads()[0]["thread_id"]
    daemon.run_turn(env["store"], tid, runner=runner)
    for i, txt in enumerate(["ok", "\U0001F44D", ""]):
        env["tf"].push(OWNER_PHONE, txt, f"SM-k{i + 2}")
        daemon.poll_all(env["store"])
        assert daemon.run_turn(env["store"], tid, runner=runner)["status"] == "content_free"
    assert len(calls) == 1 and len(env["tf"].sent) == 1  # a question is pending: just wait


def test_compose_drops_question_about_filled_item_and_caps_first_sms():
    from channels.live import compose
    out = compose.compose(["Thanks.", "Is a one year lease okay with you?"], "sms", filled={"lease"})
    assert out == ["Thanks."]
    first = " ".join(compose.compose(["It's a bedroom in a house on Appling Way in Durham, with a private bathroom.",
                                      "Rent is $750 a month.", "It's available from November 1.",
                                      "House rules: no smoking inside and no parties.",
                                      "Is a one year lease okay with you?"], "sms", "how much?", first=True))
    assert first.startswith("Rent is $750 a month.") and "House rules" not in first and first.count(".") == 2
