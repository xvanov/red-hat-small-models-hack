"""Smoke test: start the real app under uvicorn and hit every endpoint.

Run from the repo root:  python -m pytest console/tests -q
Forces the stub driver so it never depends on a GPU or on other workstreams.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

REPO = Path(__file__).resolve().parents[2]


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="module")
def base(tmp_path_factory):
    port = _free_port()
    runs = tmp_path_factory.mktemp("runs")
    env = {**os.environ, "CONSOLE_FORCE_STUB": "1", "OPERATOR_BASE_URL": "", "CONSOLE_RUNS_DIR": str(runs),
           "CONSOLE_LIVE_MODULE": "console.tests.fake_live", "CONSOLE_FB_MODULE": "console.tests.fake_fb"}
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "console.app:app", "--port", str(port),
                             "--log-level", "warning"], cwd=REPO, env=env)
    url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            if httpx.get(url + "/api/status", timeout=0.5).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.1)
    else:
        proc.kill()
        pytest.fail("console did not start")
    yield url, runs
    proc.terminate()
    proc.wait(timeout=5)


def _wait(cond, timeout=20.0):
    end = time.time() + timeout
    while time.time() < end:
        v = cond()
        if v:
            return v
        time.sleep(0.2)
    return None


def test_page_and_status(base):
    base, _ = base
    r = httpx.get(base + "/")
    assert r.status_code == 200 and "Rentus" in r.text
    assert httpx.get(base + "/static/app.js").status_code == 200
    s = httpx.get(base + "/api/status").json()
    assert s["badge"]["live"] is False and "stub" in s["badge"]["label"]
    assert isinstance(httpx.get(base + "/api/scenarios").json(), list)
    assert isinstance(httpx.get(base + "/api/scoreboard").json(), list)


def test_full_loop_with_fault_and_escalation(base):
    base, runs = base
    r = httpx.post(base + "/api/runs", json={"goal": "Appling Way room free Nov 1, $750, private bath", "speed": 10})
    assert r.status_code == 200
    rid = r.json()["run_id"]
    assert r.json()["mode"] == "stub"
    f = httpx.post(base + f"/api/runs/{rid}/faults", json={"kind": "timeout", "tool": "send_message"})
    assert f.json()["fault"]["tool"] == "send_message"
    a = httpx.get(base + "/api/approvals").json()
    assert a["run_id"] == rid and isinstance(a["items"], list)

    def view():
        return httpx.get(base + f"/api/runs/{rid}/view").json()

    v = _wait(lambda: (lambda v: v if v["lanes"]["marketplace"]["posts"] and v["register"] else None)(view()))
    assert v, "listing never posted or no renter registered"
    assert any(p["price"] == 750 for p in v["lanes"]["marketplace"]["posts"])
    esc = _wait(lambda: [e for e in view()["escalations"] if e.get("status") == "open"])
    assert esc, "price negotiation should escalate"
    d = httpx.post(base + f"/api/runs/{rid}/escalations/{esc[0]['esc_id']}", json={"decision": "approve"})
    assert d.status_code == 200
    assert _wait(lambda: any(r["status"] == "showing_proposed" for r in view()["register"]), 30)

    assert httpx.post(base + f"/api/runs/{rid}/speed", json={"speed": 4}).json()["speed"] == 4
    assert httpx.post(base + f"/api/runs/{rid}/owner", json={"text": "Sink is leaking at Appling Way, find a plumber"}).status_code == 200
    assert _wait(lambda: any(j["status"] == "booked" for j in view()["jobs"]), 30)

    events = [json.loads(l) for l in (runs / rid / "events.jsonl").read_text().splitlines()]
    types = {e["type"] for e in events}
    assert {"tool_call", "tool_result", "verifier", "retry", "renter_message", "owner_message"} <= types
    assert all(set(e) >= {"ts", "run_id", "seq", "type", "actor", "data"} for e in events)

    # SSE delivers the same events
    with httpx.stream("GET", base + f"/api/runs/{rid}/events", timeout=5) as s:
        got = []
        for line in s.iter_lines():
            if line.startswith("data: "):
                got.append(json.loads(line[6:]))
            if len(got) >= 5:
                break
    assert got and got[0]["_src"] in ("run", "console")
    assert httpx.post(base + f"/api/runs/{rid}/stop").status_code == 200
    assert any(r["run_id"] == rid for r in httpx.get(base + "/api/runs").json())


def test_bad_inputs(base):
    base, _ = base
    assert httpx.get(base + "/api/runs/nope/view").status_code == 404
    rid = httpx.post(base + "/api/runs", json={"goal": ""}).json()["run_id"]
    assert httpx.post(base + f"/api/runs/{rid}/faults", json={"kind": "meteor"}).status_code == 400
    assert httpx.post(base + f"/api/runs/{rid}/escalations/X1", json={"decision": "maybe"}).status_code == 400
    assert httpx.get(base + "/api/file", params={"path": "../.env"}).status_code == 404


def _ok(u):
    try:
        return httpx.get(u, timeout=0.5).status_code == 200
    except httpx.HTTPError:
        return False


def test_operator_stub_mode(tmp_path):
    """Real rentus_operator + rentus_tools + gym session, with the operator's scripted stub model."""
    port = _free_port()
    env = {**os.environ, "CONSOLE_STUB": "operator", "OPERATOR_BASE_URL": "http://127.0.0.1:9/v1",
           "CONSOLE_RUNS_DIR": str(tmp_path)}
    env.pop("CONSOLE_FORCE_STUB", None)
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "console.app:app", "--port", str(port),
                             "--log-level", "warning"], cwd=REPO, env=env)
    url = f"http://127.0.0.1:{port}"
    try:
        assert _wait(lambda: _ok(url + "/api/status"), 10)
        s = httpx.get(url + "/api/status").json()
        if s["mode"] != "operator-stub":
            pytest.skip(f"operator packages not importable here: {s['packages']}")
        rid = httpx.post(url + "/api/runs", json={"goal": "Appling Way room free Nov 1, $750, private bath",
                                                  "speed": 10}).json()["run_id"]
        view = lambda: httpx.get(url + f"/api/runs/{rid}/view").json()  # noqa: E731
        v = _wait(lambda: (lambda v: v if v["lanes"]["marketplace"]["posts"] else None)(view()), 20)
        assert v and v["mode"] == "operator-stub"
        assert _wait(lambda: any(l["threads"] for l in view()["lanes"].values()), 20), "renters never arrived"
        sc = httpx.get(url + "/api/scenarios").json()
        if sc:
            r = httpx.post(url + "/api/runs", json={"scenario_id": sc[0]["id"], "speed": 10})
            assert r.status_code == 200
            rid2 = r.json()["run_id"]
            assert _wait(lambda: (tmp_path / rid2 / "events.jsonl").exists(), 10)
            f = httpx.post(url + f"/api/runs/{rid2}/faults", json={"kind": "page_changed", "tool": "publish_listing"})
            assert f.status_code == 200
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_evidence_panels_and_phone_view(base):
    base, _ = base
    assert "Needs you" in httpx.get(base + "/approve").text
    t = httpx.get(base + "/api/trust").json()
    assert t["budget"]["used_b"] <= t["budget"]["limit_b"] == 33.0
    assert [r["who"] for r in t["roles"]] == ["Operator", "Reader", "Verifier"]
    rw = httpx.get(base + "/api/realworld").json()
    assert set(rw) >= {"post", "stats", "thumb"}
    if rw["stats"]:
        assert all(isinstance(v, (int, float)) for k, v in rw["stats"].items() if k != "updated_at")
    sb = httpx.get(base + "/api/scoreboard").json()
    assert all({"label", "pass_rate", "mean_reward", "tasks"} <= set(r) for r in sb)
    # the demo needs the real operator package; the forced stub refuses it cleanly
    assert httpx.post(base + "/api/demo", json={}).status_code == 409
    assert httpx.post(base + "/api/reset").json()["ok"] is True
    assert httpx.get(base + "/api/status").json()["active_run"] is None


def test_live_channels_api(base):
    """The /api/live/* wrappers over channels.live.api (here the in-memory fake)."""
    base, _ = base
    st = httpx.get(base + "/api/live/status").json()
    assert st["available"] and {c["channel"] for c in st["channels"]} >= {"messenger", "sms"}
    th = httpx.get(base + "/api/live/threads").json()
    assert th["available"] and len(th["items"]) >= 2
    assert all(set(t["gate"]) == {"lease", "move_in", "phone", "reason", "people"} for t in th["items"])
    t = httpx.get(base + "/api/live/threads/t_test_sam").json()
    assert t["messages"] and t["trace"]
    assert httpx.get(base + "/api/live/threads/nope").status_code == 404
    r = httpx.post(base + "/api/live/threads/t_test_lee/reply", json={"text": "See you Saturday."}).json()
    assert r["ok"] and r["sent"] and r["status"] == "sent"
    r = httpx.post(base + "/api/live/threads/t_test_lee/reply", json={"text": "BLOCKED test"}).json()
    assert not r["ok"] and not r["sent"] and "kill switch" in r["error"]
    assert httpx.get(base + "/api/live/threads/t_test_lee").json()["messages"][-1]["text"] == "See you Saturday."
    ap = httpx.get(base + "/api/live/approvals").json()["items"]
    live = [a for a in ap if a["source"] == "live"]
    assert {a["id"] for a in live} >= {"ap_1", "ap_2", "ap_3"}
    assert next(a for a in live if a["id"] == "ap_3")["kind"] == "report"
    assert httpx.post(base + "/api/live/approvals/ap_1", json={"decision": "edit"}).status_code == 400
    assert httpx.post(base + "/api/live/approvals/ap_1", json={"decision": "edit", "text": "Rent is $750, firm."}).json()["ok"]
    assert httpx.get(base + "/api/live/threads/t_test_sam").json()["messages"][-1]["text"] == "Rent is $750, firm."
    assert httpx.post(base + "/api/live/approvals/ap_2", json={"decision": "deny"}).json()["ok"]
    d = httpx.post(base + "/api/live/approvals/ap_3", json={"decision": "dismiss"}).json()  # a note: closed, nothing sent
    assert d["ok"] and d["status"] == "dismissed" and not d["sent"]
    assert not [a for a in httpx.get(base + "/api/live/approvals").json()["items"] if a["source"] == "live"]
    c = httpx.post(base + "/api/live/conversations", json={"channel": "sms", "to": "+15550000", "text": "Hi"}).json()
    assert c["ok"] and c["result"]["thread_id"]
    assert httpx.post(base + "/api/live/conversations", json={"channel": "sms"}).status_code == 400
    assert httpx.get(base + "/api/live/status").json()["can_archive"] is True
    assert httpx.post(base + f"/api/live/threads/{c['result']['thread_id']}/archive").json()["ok"]


def test_live_unavailable_degrades(tmp_path):
    """No live module: every /api/live endpoint answers cleanly instead of failing."""
    port = _free_port()
    env = {**os.environ, "CONSOLE_FORCE_STUB": "1", "OPERATOR_BASE_URL": "", "CONSOLE_RUNS_DIR": str(tmp_path),
           "CONSOLE_LIVE_MODULE": "no_such_live_module"}
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "console.app:app", "--port", str(port), "--log-level", "warning"],
                            cwd=REPO, env=env)
    url = f"http://127.0.0.1:{port}"
    try:
        assert _wait(lambda: _ok(url + "/api/status"), 20)
        st = httpx.get(url + "/api/live/status").json()
        assert st["available"] is False and st["error"]
        th = httpx.get(url + "/api/live/threads").json()
        assert th["available"] is False and th["items"] == []
        assert httpx.get(url + "/api/live/approvals").json()["items"] == []
        assert httpx.get(url + "/api/live/threads/x").status_code == 503
        assert "Needs you" in httpx.get(url + "/approve").text
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def _ok(u):
    try:
        return httpx.get(u, timeout=0.5).status_code == 200
    except httpx.HTTPError:
        return False


def test_posting_status_and_facebook_publish_on_click(base):
    """Honest per-channel status of a run's listings; the Facebook Page path only on an explicit call (fake Page)."""
    base, _ = base
    rid = httpx.post(base + "/api/runs", json={"goal": "Appling Way room free Nov 1, $750, private bath"}).json()["run_id"]
    ls = _wait(lambda: httpx.get(base + f"/api/runs/{rid}/posts").json()["listings"], 30)
    assert ls, "the stub driver lists the room"
    rows = {r["channel"]: r for r in ls[0]["channels"]}
    assert rows["facebook_page"]["state"] == "not_prepared"
    assert all(r["label"] != "Posted" for r in rows.values() if r["channel"] != "facebook_page"), "sandbox posts are never shown as posted"
    lid = ls[0]["listing_id"]
    assert httpx.post(base + f"/api/runs/{rid}/listings/{lid}/facebook", json={"action": "nope"}).status_code == 400
    r = httpx.post(base + f"/api/runs/{rid}/listings/{lid}/facebook", json={"action": "prepare"}).json()
    assert r["state"] == "draft" and r["post_id"].startswith("fake_")
    r = httpx.post(base + f"/api/runs/{rid}/listings/{lid}/facebook", json={"action": "publish"}).json()
    assert r["state"] == "published" and r["permalink"].startswith("https://example.invalid/")
    httpx.post(base + f"/api/runs/{rid}/stop")


def test_chat_history_lists_only_owner_chats(base):
    base, _ = base
    t = httpx.post(base + "/api/runs", json={"goal": "test run", "origin": "test"}).json()["run_id"]
    o = httpx.post(base + "/api/runs", json={"goal": "Owner asks something", "origin": "assistant"}).json()["run_id"]
    chats = httpx.get(base + "/api/chats").json()
    ids = [c["run_id"] for c in chats]
    assert o in ids and t not in ids
    assert next(c for c in chats if c["run_id"] == o)["title"] == "Owner asks something"
    httpx.post(base + "/api/reset")


MUTATING = [
    ("POST", "/api/runs"), ("POST", "/api/demo"), ("POST", "/api/demo/speed"), ("POST", "/api/reset"),
    ("POST", "/api/runs/r_x/owner"), ("POST", "/api/runs/r_x/escalations/ESC001"), ("POST", "/api/runs/r_x/faults"),
    ("POST", "/api/runs/r_x/speed"), ("POST", "/api/runs/r_x/stop"), ("POST", "/api/runs/r_x/listings/L001/facebook"),
    ("POST", "/api/live/threads/t_test_lee/reply"), ("POST", "/api/live/threads/t_test_lee/archive"),
    ("POST", "/api/live/conversations"), ("POST", "/api/live/approvals/ap_1"),
    ("PUT", "/api/runs"), ("DELETE", "/api/runs/r_x"),
]


def test_public_readonly_mode(tmp_path):
    """CONSOLE_PUBLIC_READONLY=1: every mutating route is 403 on the server, private data is filtered."""
    port = _free_port()
    env = {**os.environ, "CONSOLE_FORCE_STUB": "1", "OPERATOR_BASE_URL": "", "CONSOLE_RUNS_DIR": str(tmp_path),
           "CONSOLE_LIVE_MODULE": "console.tests.fake_live", "CONSOLE_FB_MODULE": "console.tests.fake_fb",
           "CONSOLE_PUBLIC_READONLY": "1"}
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "console.app:app", "--port", str(port), "--log-level", "warning"],
                            cwd=REPO, env=env)
    url = f"http://127.0.0.1:{port}"
    try:
        assert _wait(lambda: _ok(url + "/api/status"), 20)
        for method, path in MUTATING:
            r = httpx.request(method, url + path, json={"text": "x", "goal": "x", "decision": "approve", "action": "publish",
                                                       "channel": "sms", "to": "1", "kind": "timeout"})
            assert r.status_code == 403 and r.json()["error"] == "read-only public view", (method, path, r.status_code)
        for path in ("/approve", "/api/file?path=runs/x.png", "/api/approvals"):
            assert httpx.get(url + path).status_code == 403, path
        for path in ("/", "/api/status", "/api/results", "/api/trust", "/api/performance", "/api/chats", "/api/live/status",
                     "/api/live/threads", "/api/live/approvals", "/static/data.json"):
            assert httpx.get(url + path).status_code == 200, path
        assert httpx.get(url + "/api/status").json()["public_readonly"] is True
        th = httpx.get(url + "/api/live/threads").json()["items"]
        assert th and all(t["channel"] != "messenger_personal" for t in th)
        assert httpx.get(url + "/api/live/threads/t_test_mp").status_code == 404
        sam = next(t for t in th if t["thread_id"] == "t_test_sam")
        assert sam["contact_display"] == "Sam T." and "line" not in sam
        lee = next(t for t in th if t["thread_id"] == "t_test_lee")
        assert lee["contact_display"] == "+1 ••• ••• 0100"
        ap = httpx.get(url + "/api/live/approvals").json()["items"]
        assert all(a["thread_id"] != "t_test_mp" for a in ap) and all(not a["draft_text"] for a in ap)
    finally:
        proc.terminate()
        proc.wait(timeout=5)
