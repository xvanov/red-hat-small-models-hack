"""Personal Messenger (web) channel on synthetic fixtures (fake names), served at facebook.com URLs via routing.
No network: every request is answered by page.route()."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from channels.messenger_web import adapter as A
from channels.messenger_web import common as C
from channels.messenger_web.worker import LoginRequired, Worker, read_messages, read_thread_list, unanswered_tail

FIX = Path(__file__).parent / "fixtures" / "messenger_web"


@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        yield b
        b.close()


def _page(browser, which: str = "inbox", busy: bool = False):
    ctx = browser.new_context(viewport={"width": 1280, "height": 900})
    page = ctx.new_page()
    html = (FIX / f"{which}.html").read_text()
    if busy:  # the owner has started typing in the box
        html = html.replace('aria-label="Message" style="min-height:20px;border:1px solid #ccc">',
                            'aria-label="Message" style="min-height:20px;border:1px solid #ccc">owner is typing')
    page.route("**/*", lambda route: route.fulfill(status=200, content_type="text/html", body=html))
    return page


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setenv("LIVE_DIR", str(tmp_path / "live"))
    monkeypatch.setenv("LIVE_ALLOW_MESSENGER_NAMES", "")
    return tmp_path / "live" / "messenger_web"


def _worker(page, root):
    return Worker(page, root, sleep=lambda s: None)


def test_thread_list(browser):
    page = _page(browser)
    page.goto("https://www.facebook.com/messages/")
    rows = read_thread_list(page, C.selectors())
    assert [r["thread_id"] for r in rows] == ["111", "222", "333"]
    assert rows[0]["name"] == "Jane Testrenter" and rows[0]["listing_title"] == "Private room near Duke"
    assert rows[0]["marketplace"] and not rows[1]["marketplace"]
    assert rows[1]["name"] == "Bob Example"


def test_read_messages_direction_and_system_filter(browser):
    page = _page(browser)
    page.goto("https://www.facebook.com/messages/t/111/")
    res = read_messages(page, C.selectors(), "Jane Testrenter")
    assert res["thread_id"] == "111"
    assert res["messages"] == [
        {"dir": "in", "text": "Hi! Is this still available?"},
        {"dir": "out", "text": "Yes it is. When would you like to move in?"},
        {"dir": "in", "text": "November 1st. Is parking included?"},
        {"dir": "in", "text": "Also, are pets ok?"},
    ]
    assert [m["text"] for m in unanswered_tail(res["messages"])] == [
        "November 1st. Is parking included?", "Also, are pets ok?"]


@pytest.mark.parametrize("which", ["login", "checkpoint"])
def test_login_wall_stops(browser, root, which):
    page = _page(browser, which)
    w = _worker(page, root)
    with pytest.raises(LoginRequired):
        w.poll_once()
    w.run(stop_after=1)
    st = json.loads((root / "status.json").read_text())
    assert st["state"] == "login_required" and "messenger_web login" in st["detail"]
    ok, detail = A.MessengerPersonal(root).connected()
    assert not ok and "login" in detail


def test_poll_and_adapter(browser, root):
    page = _page(browser)
    w = _worker(page, root)
    r = w.poll_once()
    assert r == {"rows": 3, "changed": 3, "opened": 3}
    assert w.poll_once()["opened"] == 0  # nothing changed: no thread reopened
    w.state = "running"
    w.write_status()
    ad = A.MessengerPersonal(root)
    assert ad.connected()[0]
    items = ad.poll(None, None, set())
    jane = [i for i in items if i["contact"] == "111"]
    assert [i["text"] for i in jane] == ["November 1st. Is parking included?", "Also, are pets ok?"]
    assert jane[0]["channel"] == "messenger_personal" and jane[0]["renter_name"] == "Jane Testrenter"
    assert jane[0]["meta"]["listing_title"] == "Private room near Duke" and jane[0]["meta"]["autosend"] is False
    assert ad.poll(None, None, {i["ext_id"] for i in items}) == []
    # ids are stable across re-reads
    w._read_thread("111", "x")
    assert {i["ext_id"] for i in ad.poll(None, None, set()) if i["contact"] == "111"} == {i["ext_id"] for i in jane}


def test_autosend_allowlist_by_name(browser, root, monkeypatch):
    w = _worker(_page(browser), root)
    w.poll_once()
    assert not A.allows_autosend("111", root)
    monkeypatch.setenv("LIVE_ALLOW_MESSENGER_NAMES", "someone else, jane  testrenter")
    assert A.allows_autosend("111", root) and not A.allows_autosend("222", root)
    assert not A.allows_autosend("999", root)


def test_send_through_outbox_verified(browser, root):
    page = _page(browser)
    w = _worker(page, root)
    w.poll_once()
    w.state = "running"
    w.write_status()
    ad = A.MessengerPersonal(root, send_wait=10, sleep=lambda s: w.process_outbox())
    res = ad.send("111", "Parking is included.\nPets: sorry, none.")
    assert res["ok"] and res["status"] == "sent" and res["provider_id"].startswith("mw:111:")
    assert page.evaluate("window.__sent") == 1
    done = list((root / "outbox").glob("*.done.json"))
    assert len(done) == 1 and json.loads(done[0].read_text())["text"] is None  # text not kept in the outbox
    log = [json.loads(x) for x in (root / "sends.jsonl").read_text().splitlines()]
    assert log[-1]["ok"] and log[-1]["verified"] and "text" not in log[-1]


def test_send_refusals(browser, root, monkeypatch):
    page = _page(browser)
    w = _worker(page, root)
    w.poll_once()
    assert w.send("999", "hi")["error_code"] == "unknown_thread"
    busy = _page(browser, busy=True)
    assert Worker(busy, root, sleep=lambda s: None).send("111", "hi")["error_code"] == "box_busy"
    assert not busy.evaluate("window.__sent")
    (root.parent / "STOP").touch()
    assert w.send("111", "hi")["error_code"] == "stopped"
    (root.parent / "STOP").unlink()
    monkeypatch.setenv("MESSENGER_WEB_MAX_SENDS_HOUR", "0")
    assert _worker(page, root).send("111", "hi")["error_code"] == "rate_cap"
    assert not page.evaluate("window.__sent")


def test_adapter_send_timeout_cancels(root):
    root.mkdir(parents=True)
    C.write_json(root / "threads.json", {"111": {"name": "Jane Testrenter", "messages": []}})
    C.write_json(root / "status.json", {"state": "running", "heartbeat_epoch": time.time()})
    res = A.MessengerPersonal(root, send_wait=0, sleep=lambda s: None).send("111", "hi")
    assert res["error_code"] == "timeout"
    assert list((root / "outbox").glob("*.cancelled.json")) and not list((root / "outbox").glob("*.pending.json"))


def test_adapter_not_running(root):
    ok, detail = A.MessengerPersonal(root).connected()
    assert not ok and "serve" in detail
    assert A.MessengerPersonal(root).send("111", "hi")["error_code"] == "worker_unavailable"


def test_message_ids_distinguish_repeats():
    ids = C.message_ids("1", [{"dir": "in", "text": "ok"}, {"dir": "in", "text": "ok"}, {"dir": "out", "text": "ok"}])
    assert len(set(ids)) == 3


def test_live_registry_factory_and_ids(browser, root, monkeypatch):
    w = _worker(_page(browser), root)
    w.poll_once()
    p = A.make_live_provider()
    assert p.channel == "messenger_personal" and callable(p.poll) and callable(p.send) and p.display
    monkeypatch.setenv("LIVE_ALLOW_MESSENGER_NAMES", "Bob Example")
    assert A.allowlisted_thread_ids(root) == {"222": "Bob Example"}
