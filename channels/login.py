"""Open a headed browser on the owner's persistent profile for one platform, so he can log in by hand.

  channels/.venv/bin/python -m channels.login marketplace     (or roomies | craigslist | padsplit)

The profile lives in channels/.profiles/<platform>/ (gitignored). Close the browser window when
you're logged in; the adapters reuse the session from then on. Nothing is typed or submitted
by this script, and it never sees your password.
"""
from __future__ import annotations

import json
import sys

from .adapters.engine import PROFILES_DIR, SELECTORS_DIR

PLATFORMS = ("marketplace", "roomies", "craigslist", "padsplit")


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in PLATFORMS:
        print(__doc__)
        return 2
    platform = argv[0]
    spec = json.loads((SELECTORS_DIR / "live" / f"{platform}.json").read_text())
    from playwright.sync_api import sync_playwright

    prof = PROFILES_DIR / platform
    prof.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(str(prof), headless=False, viewport=None)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(spec["login_url"])
        print(f"Log in to {platform} in the browser window, then close the window.")
        try:
            page.wait_for_event("close", timeout=0)
        except Exception:
            pass
        try:
            ctx.close()
        except Exception:
            pass
    print(f"Saved session in {prof}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
