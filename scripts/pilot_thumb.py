"""Cache a thumbnail of the real-world pilot post (D20) for the console's "Real world" panel.

    .venv/bin/python scripts/pilot_thumb.py

Read-only: one Graph API GET for the post's first photo, then a download of that image to
runs/pilot/thumb.jpg (gitignored). The photo is already public on the Page post. Credentials come
from channels.facebook_page._creds() and are never printed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from channels.facebook_page import _call, _creds  # noqa: E402

OUT = REPO / "runs" / "pilot" / "thumb.jpg"


def main() -> int:
    pub = json.loads((REPO / "runs" / "pilot" / "published.json").read_text())
    photo_id = (pub.get("photo_ids") or [None])[0]
    if not photo_id:
        print("no photo ids in runs/pilot/published.json")
        return 1
    _, token = _creds()
    body = _call("GET", photo_id, token, params={"fields": "images"})
    images = sorted(body.get("images") or [], key=lambda i: i.get("width", 0))
    pick = next((i for i in images if i.get("width", 0) >= 480), images[-1] if images else None)
    if not pick:
        print("photo has no images")
        return 1
    r = httpx.get(pick["source"], timeout=30)
    r.raise_for_status()
    OUT.write_bytes(r.content)
    print(f"saved {OUT.relative_to(REPO)} ({pick.get('width')}x{pick.get('height')}, {len(r.content)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
