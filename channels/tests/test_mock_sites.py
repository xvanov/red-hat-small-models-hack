import httpx

from channels.mock_sites.app import STATE
from channels.tests.conftest import set_layout


def test_form_has_steps_required_fields_and_photo_upload(base_url):
    html = httpx.get(base_url + "/marketplace/create").text
    assert html.count("class='step'") == 4
    assert "aria-label='Price per month'" in html and "type='file'" in html and "data-required" in html


def test_layout_switch_changes_selectors(base_url):
    set_layout(base_url, "v2", ["marketplace", "padsplit"])
    m = httpx.get(base_url + "/marketplace/create").text
    assert "Price per month" not in m and "aria-label='Monthly rent'" in m
    p = httpx.get(base_url + "/padsplit/create").text
    assert "weekly-price-input" not in p and "field--weekly_price" in p


def test_login_wall_and_login(base_url):
    httpx.post(base_url + "/_admin/config", json={"roomies": {"login_wall": "on"}})
    assert "id='login-wall'" in httpx.get(base_url + "/roomies/create").text
    with httpx.Client(base_url=base_url, follow_redirects=True) as c:
        r = c.post("/roomies/login", data={"next": "/roomies/create", "email": "x", "password": "y"})
        assert "listing-form" in r.text


def test_inbox_seed_and_inject(base_url):
    r = httpx.post(base_url + "/_admin/craigslist/threads", json={"renter_name": "Test", "text": "still available?"})
    tid = r.json()["thread_id"]
    html = httpx.get(base_url + "/craigslist/inbox").text
    assert tid in html and "still available?" in html
    assert len(STATE.threads["craigslist"]) == 2


def test_listing_api_stores_multipart(base_url):
    r = httpx.post(base_url + "/roomies/api/listings", data={"rent": "750"},
                   files={"photos": ("a.png", b"x", "image/png")})
    assert r.json()["status"] == "live"
    assert STATE.listings["roomies"][0]["photos"] == ["a.png"]
