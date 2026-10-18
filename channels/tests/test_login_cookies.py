"""Headless login for the listing adapters: cookie-export import, profile locks, the headless refusal, and
values.py filling only owner-confirmed room facts. Fake cookie values; no real site is opened."""
from __future__ import annotations

import json
import os
import socket

import pytest

from channels import login as L
from channels.adapters.values import prepare

EXPORT = [
    {"domain": ".facebook.com", "name": "c_user", "value": "100000000000001", "path": "/", "secure": True,
     "sameSite": "no_restriction", "expirationDate": 1830000000.5, "session": False},
    {"domain": ".facebook.com", "name": "xs", "value": "fake%3Axs", "path": "/", "secure": True, "httpOnly": True,
     "sameSite": "no_restriction", "expirationDate": 1830000000, "session": False},
    {"domain": ".messenger.com", "name": "c_user", "value": "1", "path": "/", "sameSite": "lax"},
    {"domain": ".roomies.com", "name": "roomies_session", "value": "r", "path": "/", "sameSite": "lax"},
    {"domain": "accounts.craigslist.org", "name": "cl_session", "value": "c", "path": "/"},
    {"domain": ".padsplit.com", "name": "ps", "value": "p", "path": "/", "session": True},
    {"domain": ".notfacebook.com", "name": "c_user", "value": "evil", "path": "/"},
    {"domain": ".google.com", "name": "SID", "value": "nope", "path": "/"},
]


def test_filter_per_site():
    fb = L.cookies_from_export(EXPORT, L.DOMAINS["marketplace"])
    assert [c["name"] for c in fb] == ["c_user", "xs"]  # not messenger.com, not notfacebook.com
    assert fb[0]["sameSite"] == "None" and fb[0]["expires"] == 1830000000.5
    assert len(L.cookies_from_export(EXPORT, L.DOMAINS["messenger_web"])) == 3
    for site, name in (("roomies", "roomies_session"), ("craigslist", "cl_session"), ("padsplit", "ps")):
        assert [c["name"] for c in L.cookies_from_export({"cookies": EXPORT}, L.DOMAINS[site])] == [name]
    assert "expires" not in L.cookies_from_export(EXPORT, L.DOMAINS["padsplit"])[0]


def test_aliases_and_required():
    assert L.site_name("facebook") == "marketplace" and L.site_name("Roomies") == "roomies"
    assert L.site_name("zillow") is None
    assert L.missing_required("marketplace", L.cookies_from_export(EXPORT[2:], ("facebook.com",))) == {"c_user", "xs"}
    assert L.missing_required("roomies", []) == set()


@pytest.fixture
def profiles(tmp_path, monkeypatch):
    monkeypatch.setattr(L, "PROFILES_DIR", tmp_path / "profiles")
    monkeypatch.setenv("MESSENGER_WEB_PROFILE", str(tmp_path / "profiles" / "messenger_web"))
    return tmp_path / "profiles"


def test_import_refuses_without_facebook_session(tmp_path, profiles, capsys):
    f = tmp_path / "fb.json"
    f.write_text(json.dumps(EXPORT[1:]))  # xs but no c_user
    assert L.main(["import-cookies", "marketplace", str(f)]) == 1
    out = capsys.readouterr().out
    assert "c_user" in out and "fake" not in out
    assert f.exists()  # a failed import leaves the file alone


def test_import_rejects_non_export(tmp_path, profiles, capsys):
    f = tmp_path / "x.json"
    f.write_text("not json")
    assert L.main(["import-cookies", "roomies", str(f)]) == 1
    assert "not a cookie JSON export" in capsys.readouterr().out


def test_import_facebook_once_fills_both_profiles(tmp_path, profiles, monkeypatch, capsys):
    """One Facebook export: marketplace + messenger_web profiles get their cookies, the file is deleted,
    and nothing printed contains a cookie value."""
    monkeypatch.setattr(L, "check", lambda site: {"site": site, "logged_in": True})
    f = tmp_path / "fb.json"
    f.write_text(json.dumps(EXPORT))
    assert L.main(["import-cookies", "facebook", str(f)]) == 0
    out = capsys.readouterr().out
    res = json.loads(out)
    assert res["imported"] == 2 and res["messenger_web_imported"] == 3 and res["file_deleted"] and res["ok"]
    assert not f.exists()
    assert "100000000000001" not in out and "fake" not in out
    for name, want in (("marketplace", {"c_user", "xs"}), ("messenger_web", {"c_user", "xs"})):
        with L._context(L.profile_dir(name)) as ctx:
            assert want <= {c["name"] for c in ctx.cookies("https://www.facebook.com")}
    with L._context(L.profile_dir("marketplace")) as ctx:
        assert not ctx.cookies("https://www.messenger.com")


def test_import_keep_and_not_logged_in(tmp_path, profiles, monkeypatch, capsys):
    monkeypatch.setattr(L, "check", lambda site: {"site": site, "logged_in": False, "reason": "bot_challenge"})
    f = tmp_path / "r.json"
    f.write_text(json.dumps(EXPORT))
    assert L.main(["import-cookies", "roomies", str(f), "--keep"]) == 1
    res = json.loads(capsys.readouterr().out)
    assert res["imported"] == 1 and not res["logged_in"] and res["reason"] == "bot_challenge" and "note" in res
    assert f.exists() and not res["file_deleted"]


def test_headed_login_refuses_without_display(profiles, monkeypatch, capsys):
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    assert L.main(["padsplit"]) == 2
    out = capsys.readouterr().out
    assert "import-cookies padsplit" in out and "ssh k@100.64.38.18" in out
    assert L.main(["login", "craigslist"]) == 2
    assert not (profiles / "craigslist").exists()


def test_profile_locks(tmp_path):
    prof = tmp_path / "p"
    prof.mkdir()
    os.symlink(f"{socket.gethostname()}-999999999", prof / "SingletonLock")
    L.ensure_profile_free(prof)
    assert not os.path.lexists(prof / "SingletonLock")
    os.symlink(f"{socket.gethostname()}-{os.getpid()}", prof / "SingletonLock")
    with pytest.raises(L.ProfileBusy):
        L.ensure_profile_free(prof)


# ---------------------------------------------------------------- values: owner-confirmed facts only

APPLING = {  # the shape of channels/pilot_post.py ROOM
    "room_id": "R_APPLING", "area": "Durham", "zip": "27703", "address_public": "Appling Way, Durham, NC 27703",
    "type": "bedroom in house", "private_bath": True, "rent": 750, "available_from": "2026-11-01",
    "amenities": ["Private bathroom", "Separate entrance"], "deposit": None, "utilities": None,
    "lease_min_months": None, "furnished": None, "pets": "unconfirmed",
    "unconfirmed": ["lease_min_months", "deposit", "utilities", "furnished", "shared_spaces", "house_rules", "pets"],
}


@pytest.mark.parametrize("platform", L.PLATFORMS)
def test_live_values_leave_unknown_facts_unset(platform):
    v = prepare(platform, {"title": "t", "body": "b", "price": 750, "room": APPLING, "photos": []}, target="live")
    for k in ("laundry_text", "parking_text", "min_stay", "lease_min_months", "room_size"):
        assert v[k] is None, k
    assert not v["furnished"] and not v["cat_friendly"] and not v["dog_friendly"]
    assert v["private_bath_text"] == "private bath" and v["housing_type_text"] == "house"


def test_values_use_explicit_facts():
    room = dict(APPLING, laundry="w/d in unit", parking="street parking", lease_min_months=6, furnished=True,
                unconfirmed=[], pets="cats ok")
    v = prepare("craigslist", {"title": "t", "body": "b", "price": 750, "room": room}, target="live")
    assert (v["laundry_text"], v["parking_text"], v["min_stay"]) == ("w/d in unit", "street parking", "6 months")
    assert v["furnished"] and v["cat_friendly"] and not v["dog_friendly"]
    # a fact the record lists as unconfirmed is not used even if a value is present
    v = prepare("roomies", {"room": dict(room, unconfirmed=["lease_min_months", "furnished"])}, target="live")
    assert v["min_stay"] is None and not v["furnished"]
