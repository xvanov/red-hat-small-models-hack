"""Live-target safety in the engine, exercised on local HTML (no network, no real site)."""
import pytest

from channels.adapters.engine import AdapterError, Runner


@pytest.fixture
def page():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        pg = b.new_page()
        yield pg
        b.close()


def runner(page, spec, target="live"):
    return Runner(page, spec, None, platform="craigslist", target=target, timeout_ms=500)


def test_click_guard_refuses_publish_on_live(page):
    page.set_content('<button id="b">Publish listing</button>')
    spec = {"elements": {"next": {"selector": "#b", "action": "click", "description": "next"}},
            "flow": [{"do": "click", "el": "next"}, {"do": "stop_before", "el": "next"}]}
    with pytest.raises(AdapterError) as e:
        runner(page, spec).run_flow({})
    assert e.value.code == "POLICY_BLOCKED"


def test_click_guard_refuses_on_preview_url(page):
    page.set_content('<button id="b">continue</button>')
    spec = {"forbidden_click_url": "about:blank|s=preview",
            "elements": {"next": {"selector": "#b", "action": "click", "description": "next"}},
            "flow": [{"do": "click", "el": "next"}, {"do": "stop_before", "el": "next"}]}
    with pytest.raises(AdapterError) as e:
        runner(page, spec).run_flow({})
    assert e.value.code == "POLICY_BLOCKED"


def test_bot_check_and_redirect_are_login_required(page):
    page.set_content("<title>Just a moment...</title><p>checking</p>")
    with pytest.raises(AdapterError) as e:
        runner(page, {"bot_wall_title": "just a moment", "elements": {}, "flow": []}).check_login()
    assert e.value.code == "LOGIN_REQUIRED" and e.value.details["reason"] == "bot_challenge"
    assert "channels.login import-cookies craigslist" in e.value.hint
    page.set_content("<p>home</p>")
    with pytest.raises(AdapterError) as e:
        runner(page, {"expect_url_contains": "/host", "elements": {}, "flow": []}).check_login()
    assert e.value.details["reason"] == "redirected"


def test_stop_if_empty_and_url_conditions(page):
    page.set_content('<input name="t"><input name="email"><button id="go">continue</button>')
    spec = {"elements": {"t": {"selector": "input[name=t]", "action": "fill", "description": "title"},
                         "email": {"selector": "input[name=email]", "action": "fill", "description": "email"},
                         "go": {"selector": "#go", "action": "click", "description": "continue"}},
            "flow": [{"do": "click", "el": "go", "url_contains": "s=type"},  # skipped: wrong page
                     {"do": "fill", "el": "t", "value": "title"},
                     {"do": "stop_if_empty", "el": "email", "value": "email", "stage": "details", "needs": "login"},
                     {"do": "click", "el": "go"}, {"do": "stop_before", "el": "go"}]}
    res = runner(page, spec).run_flow({"title": "Room", "email": None})
    assert res["status"] == "ready_to_submit" and res["stage"] == "details" and res["needs"] == "login"
    assert page.locator("input[name=t]").input_value() == "Room"
