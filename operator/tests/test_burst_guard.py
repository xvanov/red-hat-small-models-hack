"""burst_guard / guard_stand_down helpers (loop.renter_stalled, loop.thread_stood_down) on a plain dict world."""
from rentus_operator import loop


def _world(last_text, status="qualifying", gate=None, stand_down=False):
    return {"threads": [{"thread_id": "t1", "stand_down": stand_down,
                         "messages": [{"from": "renter", "text": "hi"}, {"from": "operator", "text": last_text}]}],
            "register": [{"thread_ids": ["t1"], "status": status, "gate": gate or {}}]}


def _patch(monkeypatch):
    monkeypatch.setattr(loop.toolbox, "state", lambda w: w)


def test_stalled_when_no_question_and_gate_missing(monkeypatch):
    _patch(monkeypatch)
    assert loop.renter_stalled(_world("Rent is $850 a month."), "t1", escalated=False)


def test_not_stalled_with_question_or_closed_or_escalated(monkeypatch):
    _patch(monkeypatch)
    assert not loop.renter_stalled(_world("What is your move-in date?"), "t1", escalated=False)
    assert not loop.renter_stalled(_world("Good luck!", status="lost"), "t1", escalated=False)
    assert not loop.renter_stalled(_world("I'll check today."), "t1", escalated=True)
    assert not loop.renter_stalled(_world("ok", stand_down=True), "t1", escalated=False)


def test_stood_down(monkeypatch):
    _patch(monkeypatch)
    assert loop.thread_stood_down(_world("x", stand_down=True), "t1")
    assert not loop.thread_stood_down(_world("x"), "t1")
