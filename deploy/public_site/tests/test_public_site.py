"""Only the three read-only proxies + /api/online exist; every other console path 404s."""
import re

import pytest
from fastapi.testclient import TestClient

from deploy.public_site import app as site


@pytest.fixture()
def client(monkeypatch):
    calls = []

    def fake_fetch(path, ttl):
        calls.append(path)
        if path == "/api/status":
            return 200, b'{"badge":{"live":true,"backend_up":true},"secret_field":"x"}'
        return 200, b'{"configs":[]}'

    monkeypatch.setattr(site, "_fetch", fake_fetch)
    monkeypatch.setenv("PUBLIC_SMS_NUMBER", "+1 (888) 555-0100")
    site._hits.clear()
    c = TestClient(site.app)
    c.calls = calls
    return c


BLOCKED_GET = ["/api/live/threads", "/api/live/send", "/api/runs", "/api/runs/abc/view", "/approve",
               "/api/status", "/api/demo", "/api/runs/x/posts", "/static/../app.py", "/static/index.html",
               "/docs", "/openapi.json", "/api/results/../runs"]


@pytest.mark.parametrize("path", BLOCKED_GET)
def test_blocked_get(client, path):
    assert client.get(path).status_code == 404


@pytest.mark.parametrize("path", ["/", "/api/results", "/api/runs", "/api/live/send", "/approve", "/api/online"])
@pytest.mark.parametrize("method", ["post", "put", "delete", "patch"])
def test_no_writes(client, method, path):
    assert getattr(client, method)(path).status_code == 404


def test_only_whitelisted_upstream(client):
    for p in ["/api/results", "/api/trust", "/api/performance", "/api/online"]:
        assert client.get(p).status_code == 200
    assert set(client.calls) <= {"/api/results", "/api/trust", "/api/performance", "/api/status"}
    assert client.get("/api/online").json() == {"online": True}


def test_page_headers_and_no_secrets(client):
    r = client.get("/")
    assert r.status_code == 200
    csp = r.headers["content-security-policy"]
    assert "script-src 'self'" in csp and "form-action 'none'" in csp
    assert "<form" not in r.text and "<script>" not in r.text
    assert "(888) 555-0100" in r.text
    assert not re.search(r"(sk-|hf_|AC[0-9a-f]{32}|TWILIO_|API_KEY|TOKEN)", r.text)


def test_rate_limit(client):
    codes = [client.get("/api/results").status_code for _ in range(site.RATE_N + 3)]
    assert 429 in codes


def test_console_button_only_when_set(client, monkeypatch):
    monkeypatch.delenv("PUBLIC_CONSOLE_LINK", raising=False)
    r = client.get("/")
    assert "{{" not in r.text and "hero-cta" not in r.text
    assert r.headers["cache-control"].startswith("no-store")
    monkeypatch.setenv("PUBLIC_CONSOLE_LINK", "https://console.rentus.homes")
    r = client.get("/")
    assert 'href="https://console.rentus.homes"' in r.text and "{{" not in r.text
    monkeypatch.setenv("PUBLIC_CONSOLE_LINK", "javascript:alert(1)")
    assert "hero-cta" not in client.get("/").text


def test_no_raw_placeholder_ever():
    # A template newer than the code (unknown placeholders) must not leak "{{...}}".
    out = site.render_page(site.TEMPLATE + '<a href="{{SOMETHING_NEW}}">x</a> {{OTHER}}')
    assert "{{" not in out and "}}" not in out
