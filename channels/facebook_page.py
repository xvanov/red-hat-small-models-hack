"""Facebook Page adapter (Graph API). Unpublished posts only, conversation COUNT only.

Credentials: FACEBOOK_PAGE_ID and FACEBOOK_PAGE_ACCESS_TOKEN, read from the process environment,
or loaded programmatically from the owner's existing env file (FB_ENV_FILE, default
~/rental-management/.env.production). Values are never printed, logged or returned; error
messages are scrubbed of the token before they leave this module.

  python -m channels.facebook_page check                 # token works? prints page name + id only
  python -m channels.facebook_page draft-post [photo]    # UNPUBLISHED photo post; prints its id
  python -m channels.facebook_page conversations         # number of Messenger conversations, no content

Safety: every post is created with published=false, so it is not visible on the Page. Nothing
here sends Messenger messages or reads message text.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx

GRAPH = "https://graph.facebook.com/v23.0"
DEFAULT_ENV_FILES = [Path.home() / "rental-management" / ".env.production",
                     Path.home() / "rental-management" / ".env.local"]
KEYS = ("FACEBOOK_PAGE_ID", "FACEBOOK_PAGE_ACCESS_TOKEN")
SAMPLE_PHOTO = Path(__file__).resolve().parent / "mock_sites" / "static" / "sample_photos" / "room-1-bed.png"


class FacebookError(Exception):
    pass


def _creds() -> tuple[str, str]:
    vals = {k: os.environ.get(k) for k in KEYS}
    if not all(vals.values()):
        from dotenv import dotenv_values

        files = [Path(os.environ["FB_ENV_FILE"])] if os.environ.get("FB_ENV_FILE") else DEFAULT_ENV_FILES
        for f in files:
            if f.exists():
                found = dotenv_values(f)
                for k in KEYS:
                    vals[k] = vals[k] or found.get(k)
            if all(vals.values()):
                break
    if not all(vals.values()):
        raise FacebookError(f"missing {', '.join(k for k in KEYS if not vals[k])}")
    return vals["FACEBOOK_PAGE_ID"], vals["FACEBOOK_PAGE_ACCESS_TOKEN"]


def _scrub(text: str, token: str) -> str:
    return text.replace(token, "***") if token else text


def _call(method: str, path: str, token: str, **kw) -> dict:
    params = dict(kw.pop("params", {}) or {})
    params["access_token"] = token
    try:
        r = httpx.request(method, f"{GRAPH}/{path}", params=params, timeout=60, **kw)
    except httpx.HTTPError as e:
        raise FacebookError(_scrub(f"network error: {e}", token)) from None
    try:
        body = r.json()
    except ValueError:
        body = {"raw": r.text[:300]}
    if r.status_code >= 400 or "error" in body:
        err = body.get("error", body)
        msg = {k: err.get(k) for k in ("message", "type", "code", "error_subcode")} if isinstance(err, dict) else err
        raise FacebookError(_scrub(json.dumps(msg), token))
    return body


def check() -> dict:
    page_id, token = _creds()
    me = _call("GET", page_id, token, params={"fields": "id,name"})
    return {"page_id": me.get("id"), "name": me.get("name")}


def create_unpublished_post(message: str, photo_path: str | Path | None = None) -> dict:
    """Upload the photo unpublished, then create an unpublished feed post that attaches it.

    Returns {"post_id", "photo_id", "is_published"} where is_published is read back from the Graph API."""
    page_id, token = _creds()
    photo_id = None
    if photo_path:
        p = Path(photo_path)
        with p.open("rb") as fh:
            up = _call("POST", f"{page_id}/photos", token, data={"published": "false", "temporary": "true"},
                       files={"source": (p.name, fh, "image/png" if p.suffix == ".png" else "image/jpeg")})
        photo_id = up.get("id")
    data = {"message": message, "published": "false"}
    if photo_id:
        data["attached_media[0]"] = json.dumps({"media_fbid": photo_id})
    post = _call("POST", f"{page_id}/feed", token, data=data)
    post_id = post.get("id")
    is_pub = None
    try:
        is_pub = _call("GET", post_id, token, params={"fields": "is_published"}).get("is_published")
    except FacebookError:
        pass
    return {"post_id": post_id, "photo_id": photo_id, "is_published": is_pub}


def conversations_count(max_pages: int = 20) -> dict:
    """Count Messenger conversations on the Page. Requests ids only; no message content is fetched."""
    page_id, token = _creds()
    n, pages = 0, 0
    params = {"fields": "id", "limit": 100, "platform": "messenger"}
    path = f"{page_id}/conversations"
    while path and pages < max_pages:
        body = _call("GET", path, token, params=params)
        n += len(body.get("data", []))
        pages += 1
        nxt = body.get("paging", {}).get("cursors", {}).get("after") if body.get("paging", {}).get("next") else None
        if not nxt:
            break
        params = {"fields": "id", "limit": 100, "platform": "messenger", "after": nxt}
    return {"conversations": n, "truncated": pages >= max_pages}


# contract-shaped wrappers ---------------------------------------------------------

def publish_listing(listing: dict, photo_path: str | None = None) -> dict:
    """Contract envelope; creates an UNPUBLISHED Page post (status ready_to_submit)."""
    text = f"{listing.get('title', '')}\n\n{listing.get('body', '')}".strip()
    if listing.get("price"):
        text += f"\n\n${listing['price']}/month"
    try:
        res = create_unpublished_post(text, photo_path or SAMPLE_PHOTO)
    except FacebookError as e:
        return {"ok": False, "error": {"code": "UPSTREAM_ERROR", "message": str(e), "retryable": False}}
    return {"ok": True, "data": {"post_id": res["post_id"], "url": None, "status": "ready_to_submit",
                                 "is_published": res["is_published"], "channel": "facebook_page",
                                 "note": "unpublished Page post; the owner publishes it from Meta Business Suite"}}


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "check"
    try:
        if cmd == "check":
            out = check()
        elif cmd == "draft-post":
            photo = argv[1] if len(argv) > 1 else SAMPLE_PHOTO
            out = create_unpublished_post(
                "[Draft, not published] Rentus Operator hackathon test: private room with own bath, "
                "Appling Way, Durham. Available Nov 1.", photo)
        elif cmd == "conversations":
            out = conversations_count()
        else:
            print(__doc__)
            return 2
    except FacebookError as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        return 1
    print(json.dumps({"ok": True, **out}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
