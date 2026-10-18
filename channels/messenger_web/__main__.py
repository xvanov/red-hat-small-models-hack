"""Personal Facebook Messenger over the web (the owner's own account; Marketplace inquiries land here).

  channels/.venv/bin/python -m channels.messenger_web login    open a visible browser on facebook.com; log in
                                                              by hand, then close the window
  channels/.venv/bin/python -m channels.messenger_web import-cookies <file.json|->
                                                              headless login: load a Cookie-Editor / EditThisCookie
                                                              JSON export (facebook.com, messenger.com) into the
                                                              profile; the file is deleted afterwards (--keep to keep)
  channels/.venv/bin/python -m channels.messenger_web check    is the session logged in? thread counts only
  channels/.venv/bin/python -m channels.messenger_web serve    the browser worker: polls the inbox (>= 20 s),
                                                              runs approved sends; keep it running next to
                                                              `python -m channels.live`
  channels/.venv/bin/python -m channels.messenger_web read     one poll now, then print counts (no text)
  channels/.venv/bin/python -m channels.messenger_web ids      thread ids of the names in LIVE_ALLOW_MESSENGER_NAMES
                                                              (put them in LIVE_ALLOW_MESSENGER_PERSONAL_IDS)
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


class ProfileBusy(RuntimeError):
    pass


def ensure_profile_free() -> None:
    """Chromium allows one process per profile. Refuse clearly if a live one holds it; clear a stale lock."""
    import os
    import socket

    lock = C.profile_dir() / "SingletonLock"
    if not os.path.lexists(lock):
        return
    target = os.readlink(lock) if os.path.islink(lock) else ""
    host, _, pid = target.rpartition("-")
    alive = False
    if pid.isdigit() and host == socket.gethostname():
        try:
            os.kill(int(pid), 0)
            alive = True
        except ProcessLookupError:
            alive = False
        except PermissionError:
            alive = True
    if alive:
        raise ProfileBusy(f"the messenger_web browser profile is in use by process {pid} (a running login/serve/"
                          f"check). Stop it first (kill {pid}), then retry.")
    for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        with contextlib.suppress(FileNotFoundError):
            os.unlink(C.profile_dir() / name)


SAMESITE = {"no_restriction": "None", "none": "None", "lax": "Lax", "strict": "Strict"}


def cookies_from_export(data) -> list[dict]:
    """Cookie-Editor / EditThisCookie JSON export (a list of cookie objects) -> Playwright cookies, Facebook only."""
    if isinstance(data, dict):
        data = data.get("cookies") or []
    out = []
    for c in data:
        dom = (c.get("domain") or "").strip()
        if not (dom.endswith("facebook.com") or dom.endswith("messenger.com")) or not c.get("name"):
            continue
        ck = {"name": c["name"], "value": str(c.get("value", "")), "domain": dom, "path": c.get("path") or "/",
              "httpOnly": bool(c.get("httpOnly")), "secure": bool(c.get("secure", True))}
        exp = c.get("expirationDate", c.get("expires"))
        if exp and not c.get("session"):
            ck["expires"] = float(exp)
        ss = SAMESITE.get(str(c.get("sameSite") or "").lower())
        if ss:
            ck["sameSite"] = ss
            if ss == "None":
                ck["secure"] = True
        out.append(ck)
    return out


def cmd_import_cookies(path: str, keep: bool = False) -> int:
    import os
    from pathlib import Path

    raw = sys.stdin.read() if path == "-" else Path(path).expanduser().read_text()
    try:
        cookies = cookies_from_export(json.loads(raw))
    except (json.JSONDecodeError, TypeError, AttributeError) as e:
        print(json.dumps({"ok": False, "error": f"not a cookie JSON export ({type(e).__name__})"}))
        return 1
    names = {c["name"] for c in cookies if c["domain"].endswith("facebook.com")}
    if not {"c_user", "xs"} <= names:
        print(json.dumps({"ok": False, "error": "export lacks the facebook.com login cookies c_user and xs: export "
                          "while logged in on www.facebook.com", "facebook_cookies": len(cookies)}))
        return 1
    with browser(headless=True) as page:
        page.context.add_cookies(cookies)
        from .worker import Worker
        res = Worker(page).check()
    if path != "-" and not keep:
        with contextlib.suppress(OSError):
            os.unlink(Path(path).expanduser())  # holds the live session: don't leave it lying around
    print(json.dumps({"ok": res.get("state") == "ok", "imported": len(cookies), **res,
                      "file_deleted": path != "-" and not keep}))
    return 0 if res.get("state") == "ok" else 1


@contextlib.contextmanager
def browser(headless: bool | None = None):
    from playwright.sync_api import sync_playwright

    ensure_profile_free()

    if headless is None:
        import os
        no_display = not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
        headless = C.env("MESSENGER_WEB_HEADLESS", "0") == "1" or no_display
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

    import os
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        print("No display here (headless machine). Use cookie import instead: see "
              "channels/messenger_web/README.md, 'Headless login'.")
        return 2
    ensure_profile_free()
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
    try:
        return _dispatch(cmd, argv)
    except ProfileBusy as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        return 3


def _dispatch(cmd: str, argv: list[str]) -> int:
    if cmd == "login":
        return cmd_login()
    if cmd == "import-cookies":
        if len(argv) < 2:
            print(__doc__)
            return 2
        return cmd_import_cookies(argv[1], keep="--keep" in argv)
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
    if cmd == "ids":
        from .adapter import allowlisted_thread_ids
        ids = allowlisted_thread_ids()
        print(json.dumps({"names_set": len(C.allowed_names()), "matching_threads": ids,
                          "env_line": "LIVE_ALLOW_MESSENGER_PERSONAL_IDS=" + ",".join(ids)}, ensure_ascii=False))
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
