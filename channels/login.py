"""Log the live listing adapters in to the owner's accounts, one saved browser profile per site.

  channels/.venv/bin/python -m channels.login import-cookies <site> <file.json|-> [--keep] [--no-messenger]
        headless login (no screen needed): load a Cookie-Editor / EditThisCookie JSON export, made on the
        owner's laptop while logged in, into channels/.profiles/<site>/. Only the site's own cookies are
        kept; the file is deleted afterwards (--keep keeps it). A marketplace (Facebook) export also logs
        in channels/.profiles/messenger_web/, so Facebook is exported once (--no-messenger skips that).
  channels/.venv/bin/python -m channels.login check <site>
        headless: open the site's listing form with the saved profile and say logged in yes / no
  channels/.venv/bin/python -m channels.login login <site>     (or just: channels.login <site>)
        open a visible browser to log in by hand; needs a screen, refuses on a headless machine

  <site> is one of: marketplace, roomies, padsplit, craigslist  ("facebook" = marketplace)

Profiles live in channels/.profiles/ (gitignored). Nothing here types a password or prints a cookie value.
See channels/LOGIN.md, "Headless login".
"""
from __future__ import annotations

import contextlib
import json
import os
import socket
import sys
from pathlib import Path

from .adapters.engine import PROFILES_DIR, SELECTORS_DIR

PLATFORMS = ("marketplace", "roomies", "craigslist", "padsplit")
ALIASES = {"facebook": "marketplace", "fb": "marketplace"}

# Cookie domains each profile keeps (a cookie matches a domain or any subdomain of it).
DOMAINS = {
    "marketplace": ("facebook.com",),
    "messenger_web": ("facebook.com", "messenger.com"),
    "roomies": ("roomies.com",),
    "padsplit": ("padsplit.com",),
    "craigslist": ("craigslist.org",),
}
# Session cookies that must be in the export, where they are known. Other sites: any site cookie, then
# `check` tells whether the session is really logged in.
REQUIRED = {"marketplace": {"c_user", "xs"}}
SAMESITE = {"no_restriction": "None", "none": "None", "lax": "Lax", "strict": "Strict", "unspecified": None}


class ProfileBusy(RuntimeError):
    pass


def site_name(arg: str | None) -> str | None:
    if not arg:
        return None
    a = ALIASES.get(arg.lower(), arg.lower())
    return a if a in PLATFORMS else None


def has_display() -> bool:
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def profile_dir(name: str) -> Path:
    if name == "messenger_web":
        from .messenger_web import common as C
        return C.profile_dir()
    return PROFILES_DIR / name


def ensure_profile_free(prof: Path) -> None:
    """Chromium allows one process per profile. Refuse clearly if a live process holds it; clear a stale lock
    (left by a crashed or killed browser) so the next launch does not fail with 'profile in use'."""
    lock = prof / "SingletonLock"
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
        raise ProfileBusy(f"the browser profile {prof.name} is in use by process {pid} (a running adapter, login "
                          f"or check). Stop it first (kill {pid}), then retry.")
    for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        with contextlib.suppress(FileNotFoundError):
            os.unlink(prof / name)


def _domain_ok(dom: str, domains: tuple[str, ...]) -> bool:
    d = dom.strip().lstrip(".").lower()
    return any(d == x or d.endswith("." + x) for x in domains)


def cookies_from_export(data, domains: tuple[str, ...]) -> list[dict]:
    """Cookie-Editor / EditThisCookie JSON export (a list of cookie objects, or {"cookies": [...]}) ->
    Playwright cookies, keeping only `domains`."""
    if isinstance(data, dict):
        data = data.get("cookies") or []
    if not isinstance(data, list):
        raise TypeError("expected a list of cookies")
    out = []
    for c in data:
        if not isinstance(c, dict) or not c.get("name"):
            continue
        dom = str(c.get("domain") or "").strip()
        if not _domain_ok(dom, domains):
            continue
        ck = {"name": str(c["name"]), "value": str(c.get("value", "")), "domain": dom, "path": c.get("path") or "/",
              "httpOnly": bool(c.get("httpOnly")), "secure": bool(c.get("secure", True))}
        exp = c.get("expirationDate", c.get("expires"))
        if exp not in (None, "", -1) and not c.get("session"):
            with contextlib.suppress(TypeError, ValueError):
                if float(exp) > 0:
                    ck["expires"] = float(exp)
        ss = SAMESITE.get(str(c.get("sameSite") or "").lower())
        if ss:
            ck["sameSite"] = ss
            if ss == "None":
                ck["secure"] = True
        out.append(ck)
    return out


def missing_required(site: str, cookies: list[dict]) -> set[str]:
    return REQUIRED.get(site, set()) - {c["name"] for c in cookies}


@contextlib.contextmanager
def _context(prof: Path, headless: bool = True):
    from playwright.sync_api import sync_playwright

    prof.mkdir(parents=True, exist_ok=True)
    ensure_profile_free(prof)
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(str(prof), headless=headless,
                                                    viewport={"width": 1280, "height": 900})
        try:
            yield ctx
        finally:
            with contextlib.suppress(Exception):
                ctx.close()


def write_cookies(prof: Path, cookies: list[dict]) -> None:
    """Add cookies to a persistent profile (headless; no page is opened)."""
    with _context(prof) as ctx:
        ctx.add_cookies(cookies)


def _spec(site: str) -> dict:
    return json.loads((SELECTORS_DIR / "live" / f"{site}.json").read_text())


def check(site: str) -> dict:
    """Open the site's start page headless with its saved profile, as the adapters do; logged in yes/no only."""
    from .adapters.engine import AdapterError, Runner, browser_page, spec_path

    spec = _spec(site)
    ensure_profile_free(profile_dir(site))
    with browser_page(site, "live", headless=True) as page:
        try:
            page.goto(spec["start_url"], wait_until="domcontentloaded", timeout=30000)
            with contextlib.suppress(Exception):
                page.wait_for_load_state("networkidle", timeout=int(spec.get("settle_ms", 6000)))
        except Exception as e:
            return {"site": site, "logged_in": False, "reason": f"could not load the page ({type(e).__name__})"}
        if site == "marketplace":  # Facebook: the session cookie must have survived the load
            names = {c["name"] for c in page.context.cookies("https://www.facebook.com")}
            if not {"c_user", "xs"} <= names:
                return {"site": site, "logged_in": False, "reason": "facebook session cookies missing or expired"}
        try:
            Runner(page, spec, spec_path(site, "live"), platform=site, target="live").check_login()
        except AdapterError as e:
            return {"site": site, "logged_in": False, "reason": (e.details or {}).get("reason", e.code)}
        return {"site": site, "logged_in": True}


def cmd_import_cookies(site: str, path: str, *, keep: bool = False, messenger: bool = True) -> int:
    try:
        raw = sys.stdin.read() if path == "-" else Path(path).expanduser().read_text()
    except OSError as e:
        print(json.dumps({"ok": False, "error": f"cannot read {path} ({type(e).__name__})"}))
        return 1
    try:
        data = json.loads(raw)
        cookies = cookies_from_export(data, DOMAINS[site])
    except (json.JSONDecodeError, TypeError, AttributeError) as e:
        print(json.dumps({"ok": False, "error": f"not a cookie JSON export ({type(e).__name__})"}))
        return 1
    if not cookies:
        print(json.dumps({"ok": False, "error": f"no {'/'.join(DOMAINS[site])} cookies in the export: export while "
                          f"on the {site} site, logged in"}))
        return 1
    miss = missing_required(site, cookies)
    if miss:
        print(json.dumps({"ok": False, "error": f"export lacks the login cookies {sorted(miss)}: export while logged "
                          f"in on www.facebook.com", "site_cookies": len(cookies)}))
        return 1
    out: dict = {"site": site, "imported": len(cookies)}
    write_cookies(profile_dir(site), cookies)
    if site == "marketplace" and messenger:
        mcookies = cookies_from_export(data, DOMAINS["messenger_web"])
        try:
            write_cookies(profile_dir("messenger_web"), mcookies)
            out["messenger_web_imported"] = len(mcookies)
        except ProfileBusy as e:  # the messenger worker is running: it keeps its own session
            out["messenger_web_imported"] = 0
            out["messenger_web_note"] = str(e)
    if path != "-" and not keep:
        with contextlib.suppress(OSError):
            os.unlink(Path(path).expanduser())  # holds the live session: don't leave it lying around
    out["file_deleted"] = path != "-" and not keep
    res = check(site)
    out.update(logged_in=res["logged_in"], **({"reason": res["reason"]} if "reason" in res else {}))
    if site == "roomies" and not res["logged_in"]:
        out["note"] = ("Roomies sits behind Cloudflare; its clearance cookie is tied to the browser and network it "
                       "was issued to, so an imported session may still meet the bot check here.")
    out["ok"] = bool(res["logged_in"])
    print(json.dumps(out))
    return 0 if out["ok"] else 1


def headless_refusal(site: str) -> str:
    return (f"No display on this machine, so a login window cannot open. Log in headlessly instead:\n"
            f"  1. On your laptop, open {_spec(site)['start_url']} logged in, then Cookie-Editor > Export > JSON.\n"
            f"  2. ssh k@100.64.38.18 'cat > ~/{site}-cookies.json'   (paste, then Ctrl-D)\n"
            f"  3. channels/.venv/bin/python -m channels.login import-cookies {site} ~/{site}-cookies.json\n"
            f"See channels/LOGIN.md, 'Headless login'.")


def cmd_login(site: str) -> int:
    if not has_display():
        print(headless_refusal(site))
        return 2
    spec = _spec(site)
    prof = profile_dir(site)
    prof.mkdir(parents=True, exist_ok=True)
    ensure_profile_free(prof)
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(str(prof), headless=False, viewport=None)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(spec["login_url"])
        print(f"Log in to {site} in the browser window, then close the window.")
        with contextlib.suppress(Exception):
            page.wait_for_event("close", timeout=0)
        with contextlib.suppress(Exception):
            ctx.close()
    print(f"Saved session in {prof}. Next: channels/.venv/bin/python -m channels.login check {site}")
    return 0


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    cmd, rest = argv[0], argv[1:]
    try:
        if cmd == "import-cookies":
            args = [a for a in rest if not a.startswith("--")]
            site = site_name(args[0] if args else None)
            if not site or len(args) != 2:
                print(__doc__)
                return 2
            return cmd_import_cookies(site, args[1], keep="--keep" in rest, messenger="--no-messenger" not in rest)
        if cmd == "check":
            site = site_name(rest[0] if rest else None)
            if not site:
                print(__doc__)
                return 2
            res = check(site)
            print(json.dumps(res))
            return 0 if res["logged_in"] else 1
        if cmd == "login":
            cmd, rest = (rest[0] if rest else ""), rest[1:]
        site = site_name(cmd)
        if not site:
            print(__doc__)
            return 2
        return cmd_login(site)
    except ProfileBusy as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        return 3


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
