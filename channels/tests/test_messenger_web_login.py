"""Headless login helpers: cookie-export import mapping and the profile lock check (no browser, no network)."""
from __future__ import annotations

import json
import os
import socket

import pytest

from channels.messenger_web import __main__ as M

EXPORT = [  # Cookie-Editor style export, fake values
    {"domain": ".facebook.com", "name": "c_user", "value": "100000000000001", "path": "/", "secure": True,
     "httpOnly": False, "sameSite": "no_restriction", "expirationDate": 1830000000.5, "session": False},
    {"domain": ".facebook.com", "name": "xs", "value": "fake%3Axs", "path": "/", "secure": True, "httpOnly": True,
     "sameSite": "no_restriction", "expirationDate": 1830000000, "session": False},
    {"domain": ".facebook.com", "name": "presence", "value": "x", "path": "/", "secure": True, "sameSite": None,
     "session": True},
    {"domain": ".messenger.com", "name": "c_user", "value": "1", "path": "/", "sameSite": "lax"},
    {"domain": ".google.com", "name": "SID", "value": "nope", "path": "/"},
]


def test_cookie_export_mapping():
    cs = M.cookies_from_export(EXPORT)
    assert len(cs) == 4 and not any(c["domain"].endswith("google.com") for c in cs)
    cu = cs[0]
    assert cu["sameSite"] == "None" and cu["secure"] and cu["expires"] == 1830000000.5
    assert "expires" not in cs[2] and "sameSite" not in cs[2]  # session cookie, unspecified sameSite
    assert cs[3]["sameSite"] == "Lax"
    assert M.cookies_from_export({"cookies": EXPORT}) == cs  # wrapped export


def test_import_refuses_without_login_cookies(tmp_path, capsys):
    f = tmp_path / "c.json"
    f.write_text(json.dumps(EXPORT[2:]))
    assert M.cmd_import_cookies(str(f)) == 1
    assert "c_user and xs" in capsys.readouterr().out
    assert f.exists()  # a failed import leaves the file alone


@pytest.fixture
def prof(tmp_path, monkeypatch):
    monkeypatch.setenv("MESSENGER_WEB_PROFILE", str(tmp_path / "prof"))
    (tmp_path / "prof").mkdir()
    return tmp_path / "prof"


def test_profile_lock_live_refuses(prof):
    os.symlink(f"{socket.gethostname()}-{os.getpid()}", prof / "SingletonLock")
    with pytest.raises(M.ProfileBusy):
        M.ensure_profile_free()
    assert M.main(["check"]) == 3


def test_profile_lock_stale_removed(prof):
    os.symlink(f"{socket.gethostname()}-999999999", prof / "SingletonLock")
    M.ensure_profile_free()
    assert not os.path.lexists(prof / "SingletonLock")


def test_login_refuses_without_display(monkeypatch, capsys):
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    assert M.cmd_login() == 2 and "cookie import" in capsys.readouterr().out
