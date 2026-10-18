"""Personal Facebook Messenger over the web (the owner's own account; Marketplace inquiries land here).

  channels/.venv/bin/python -m channels.messenger_web login    open a visible browser on facebook.com; log in
                                                              by hand, then close the window
  channels/.venv/bin/python -m channels.messenger_web check    is the session logged in? thread counts only
  channels/.venv/bin/python -m channels.messenger_web serve    the browser worker: polls the inbox (>= 20 s),
                                                              runs approved sends; keep it running next to
                                                              `python -m channels.live`
  channels/.venv/bin/python -m channels.messenger_web read     one poll now, then print counts (no text)
  channels/.venv/bin/python -m channels.messenger_web test-send <thread_id> "<text>"
                                                              send once through the worker; refused unless the
                                                              thread's name is in LIVE_ALLOW_MESSENGER_NAMES

The profile lives in channels/.profiles/messenger_web/ (gitignored). Nothing here types a password.
"""
from __future__ import annotations

import contextlib
import json
import sys

from . import common as C


@contextlib.contextmanager
def browser(headless: bool | None = None):
    from playwright.sync_api import sync_playwright

    if headless is None:
        headless = C.env("MESSENGER_WEB_HEADLESS", "0") == "1"
    prof = C.profile_dir()
    prof.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(str(prof), headless=headless,
                                                    viewport={"width": 1280, "height": 900})
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.on("dialog", lambda d: d.dismiss())
            page.on("filechooser", lambda fc: None)
            yield page
        finally:
            with contextlib.suppress(Exception):
                ctx.close()


def cmd_login() -> int:
    from playwright.sync_api import sync_playwright

    prof = C.profile_dir()
    prof.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(str(prof), headless=False, viewport=None)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(C.selectors()["inbox_url"])
        print("Log in to Facebook in the browser window (your personal account), open Messages once, "
              "then close the window.")
        with contextlib.suppress(Exception):
            page.wait_for_event("close", timeout=0)
        with contextlib.suppress(Exception):
            ctx.close()
    print(f"Saved session in {prof}. Next: channels/.venv/bin/python -m channels.messenger_web check")
    return 0


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    cmd = argv[0]
    if cmd == "login":
        return cmd_login()
    from .worker import Worker

    if cmd == "check":
        with browser() as page:
            print(json.dumps(Worker(page).check()))
        return 0
    if cmd == "read":
        with browser() as page:
            w = Worker(page)
            try:
                r = w.poll_once()
            except Exception as e:
                print(json.dumps({"state": "error", "detail": f"{type(e).__name__}: {str(e)[:200]}"}))
                return 1
            db = w.threads()
            msgs = [m for t in db.values() for m in t.get("messages", [])]
            print(json.dumps({**r, "threads_tracked": len(db), "threads_read": sum(1 for t in db.values() if t.get("read_at")),
                              "marketplace": sum(1 for t in db.values() if t.get("marketplace")),
                              "messages_in": sum(m["dir"] == "in" for m in msgs),
                              "messages_out": sum(m["dir"] == "out" for m in msgs)}))
        return 0
    if cmd == "serve":
        with browser() as page:
            print("messenger_web worker: polling facebook.com/messages; Ctrl-C to stop", flush=True)
            try:
                Worker(page).run()
            except KeyboardInterrupt:
                pass
        return 0
    if cmd == "test-send":
        if len(argv) != 3:
            print(__doc__)
            return 2
        from .adapter import MessengerPersonal, allows_autosend, thread_name

        tid, text = argv[1], argv[2]
        if not allows_autosend(tid):
            print(json.dumps({"ok": False, "error": "thread name not in LIVE_ALLOW_MESSENGER_NAMES; refused",
                              "known_thread": thread_name(tid) is not None}))
            return 1
        print(json.dumps(MessengerPersonal().send(tid, text)))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
