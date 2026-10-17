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
    env = {**os.environ, "CONSOLE_FORCE_STUB": "1", "OPERATOR_BASE_URL": "", "CONSOLE_RUNS_DIR": str(runs)}
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
    f = httpx.post(base + f"/api/runs/{rid}/faults", json={"kind": "timeout"})
    assert f.json()["fault"]["tool"] == "send_message"

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
