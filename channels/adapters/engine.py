"""Selector-file driven browser runner.

A platform's behaviour lives in a selector file (channels/adapters/selectors/<target>/<platform>.json):
  elements  key -> {selector, action, description, ...}   (what to find; repairable)
  flow      ordered steps {do, el, value?, optional?}     (what to do with it)
The code here never names a platform's DOM. When a selector stops matching, the Runner hands
the element to the repair loop (channels.repair), which proposes, validates and writes back
a new selector, then the Runner retries.
"""
from __future__ import annotations

import json
import os
import re
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

CHANNELS_DIR = Path(__file__).resolve().parent.parent
SELECTORS_DIR = Path(__file__).resolve().parent / "selectors"
PROFILES_DIR = CHANNELS_DIR / ".profiles"
SCREENSHOTS_DIR = CHANNELS_DIR / "screenshots"
DESKTOP_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/141.0.0.0 Safari/537.36")


class AdapterError(Exception):
    """Mapped to the contract's error envelope by api.py."""

    def __init__(self, code: str, message: str, hint: str | None = None, retryable: bool = False,
                 details: dict | None = None):
        super().__init__(message)
        self.code, self.message, self.hint, self.retryable, self.details = code, message, hint, retryable, details

    def envelope(self) -> dict:
        err: dict[str, Any] = {"code": self.code, "message": self.message, "retryable": self.retryable}
        if self.hint:
            err["hint"] = self.hint
        if self.details:
            err["details"] = self.details
        return {"ok": False, "error": err}


# ---------------------------------------------------------------- selector files

def spec_path(platform: str, target: str, selectors_dir: Path | None = None) -> Path:
    return Path(selectors_dir or SELECTORS_DIR) / target / f"{platform}.json"


def load_spec(platform: str, target: str, selectors_dir: Path | None = None) -> tuple[dict, Path]:
    p = spec_path(platform, target, selectors_dir)
    if not p.exists():
        raise AdapterError("NOT_FOUND", f"no selector file for {platform} ({target})")
    return json.loads(p.read_text()), p


def save_spec(path: Path, spec: dict) -> None:
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n")
    tmp.replace(path)


# ---------------------------------------------------------------- browser sessions

@contextmanager
def browser_page(platform: str, target: str, headless: bool | None = None) -> Iterator[Any]:
    """mock: a throwaway headless browser. live: the owner's persistent profile for that platform."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        if target == "live":
            if headless is None:
                headless = os.environ.get("CHANNELS_HEADLESS", "0") == "1"
            prof = PROFILES_DIR / platform
            prof.mkdir(parents=True, exist_ok=True)
            # headless Chromium announces itself ("HeadlessChrome") and bot checks such as Cloudflare refuse it,
            # even with a valid imported session; present as the desktop Chrome the owner's cookies came from
            opts: dict[str, Any] = {"viewport": {"width": 1280, "height": 900}}
            if headless:
                opts.update(user_agent=os.environ.get("CHANNELS_USER_AGENT") or DESKTOP_UA, locale="en-US",
                            timezone_id="America/New_York",
                            args=["--disable-blink-features=AutomationControlled"])
            ctx = pw.chromium.launch_persistent_context(str(prof), headless=headless, **opts)
            try:
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                _guard(page)
                yield page
            finally:
                ctx.close()
        else:
            browser = pw.chromium.launch(headless=True if headless is None else headless)
            try:
                ctx = browser.new_context(viewport={"width": 1100, "height": 900})
                page = ctx.new_page()
                _guard(page)
                yield page
            finally:
                browser.close()


def _guard(page) -> None:
    """Swallow native file pickers (a stray click on a drop zone must not clear uploaded photos)
    and dismiss any beforeunload / alert dialogs."""
    page.on("filechooser", lambda fc: None)
    page.on("dialog", lambda d: d.dismiss())


def screenshot(page, platform: str, target: str, tag: str = "") -> str:
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    name = f"{platform}-{target}-{time.strftime('%Y%m%d-%H%M%S')}-{int(time.time() * 1000) % 1000:03d}{tag}.png"
    path = SCREENSHOTS_DIR / name
    page.screenshot(path=str(path), full_page=True)
    return str(path)


# ---------------------------------------------------------------- element checks shared with repair

KIND_JS = """el => ({tag: el.tagName.toLowerCase(), type: (el.getAttribute('type')||'').toLowerCase(),
  role: el.getAttribute('role')||'', editable: el.isContentEditable, disabled: !!el.disabled || el.getAttribute('aria-disabled')==='true'})"""


def kind_ok(action: str, k: dict) -> bool:
    tag, typ, role = k["tag"], k["type"], k["role"]
    if action == "fill":
        return (tag == "input" and typ in ("", "text", "number", "date", "email", "tel", "search", "url")) \
            or tag == "textarea" or k["editable"] or role in ("textbox", "combobox", "spinbutton")
    if action == "select":
        return tag == "select"
    if action == "choose":
        return tag == "select" or role in ("combobox", "listbox", "button")
    if action == "check":
        return (tag == "input" and typ in ("checkbox", "radio")) or role in ("checkbox", "switch", "radio")
    if action == "upload":
        return tag == "input" and typ == "file"
    if action in ("click", "submit"):
        return tag in ("button", "a") or (tag == "input" and typ in ("submit", "button")) \
            or role in ("button", "link", "menuitem", "tab")
    if action in ("exists", "rows"):
        return True
    return False


def try_selector(page, selector: str, el: dict, timeout_ms: int):
    """Return a Locator if `selector` finds exactly the element `el` describes, else None.

    Single elements must match exactly one visible element (file inputs: one attached element,
    since real sites hide them). `rows` elements must match one or more, and if they declare an
    `attr` with an `attr_pattern`, every match must carry a matching value.
    """
    import re

    from playwright.sync_api import Error as PwError

    action = el.get("action", "click")
    try:
        base = page.locator(selector)
        if action == "rows":
            base.first.wait_for(state="attached", timeout=timeout_ms)
            if base.count() < 1:
                return None
            if el.get("attr"):
                pat = re.compile(el.get("attr_pattern", ".+"))
                vals = base.evaluate_all(f"els => els.map(e => e.getAttribute({json.dumps(el['attr'])}))")
                if not vals or not all(v is not None and pat.search(v) for v in vals):
                    return None
            return base
        if action == "upload":
            base.first.wait_for(state="attached", timeout=timeout_ms)
            loc = base
        else:
            loc = base.filter(visible=True)
            loc.first.wait_for(state="visible", timeout=timeout_ms)
        if loc.count() != 1:
            return None
        k = loc.first.evaluate(KIND_JS)
        if not kind_ok(action, k):
            return None
        return loc.first
    except (PwError, ValueError):
        return None


# ---------------------------------------------------------------- the runner

class Runner:
    def __init__(self, page, spec: dict, path: Path, *, platform: str, target: str,
                 repairer=None, timeout_ms: int | None = None):
        self.page, self.spec, self.path = page, spec, path
        self.platform, self.target = platform, target
        self.repairer = repairer
        self.timeout_ms = timeout_ms or (int(os.environ.get("CHANNELS_TIMEOUT_MS", "0"))
                                         or (2500 if target == "mock" else 12000))
        self.repairs: list[dict] = []
        self.last_repair: dict | None = None
        self.filled: list[str] = []

    def url(self, key: str, base_url: str) -> str:
        return self.spec[key].replace("{base}", base_url.rstrip("/"))

    def login_hint(self) -> str:
        return (f"owner runs: channels/.venv/bin/python -m channels.login import-cookies {self.platform} "
                f"~/{self.platform}-cookies.json  (export the cookies on his laptop first: channels/LOGIN.md, "
                f"'Headless login')")

    def check_login(self) -> None:
        """Raise LOGIN_REQUIRED on a login page, or (live) on a bot challenge page such as Cloudflare's
        "Just a moment...": a headed login in the owner's profile clears both."""
        bot = self.spec.get("bot_wall_title")
        if bot and self.target == "live":
            try:
                title = self.page.title()
            except Exception:
                title = ""
            if re.search(bot, title or "", re.I):
                raise AdapterError(
                    "LOGIN_REQUIRED", f"{self.platform} shows a bot check ('{title}') instead of the page",
                    hint=self.login_hint() + "  (export the cookies after passing the check in your own browser)",
                    details={"reason": "bot_challenge", "url": self.page.url,
                             "screenshot": screenshot(self.page, self.platform, self.target, "-login")})
        want = self.spec.get("expect_url_contains")
        if want and self.target == "live" and want not in (self.page.url or ""):
            raise AdapterError(
                "LOGIN_REQUIRED", f"{self.platform} redirected away from the form (to {self.page.url}); not logged in",
                hint=self.login_hint(),
                details={"reason": "redirected", "url": self.page.url,
                         "screenshot": screenshot(self.page, self.platform, self.target, "-login")})
        sel = self.spec.get("login_wall")
        if not sel:
            return
        try:
            if self.page.locator(sel).filter(visible=True).count() > 0:
                raise AdapterError(
                    "LOGIN_REQUIRED", f"{self.platform} shows a login page",
                    hint=(self.login_hint() if self.target == "live"
                          else "mock login wall is on: switch it off at the mock control panel"),
                    details={"reason": "login_page", "url": self.page.url,
                             "screenshot": screenshot(self.page, self.platform, self.target, "-login")})
        except AdapterError:
            raise
        except Exception:
            return

    def locate(self, key: str, exclude: list[str] | None = None):
        self.last_repair = None
        el = self.spec["elements"][key]
        loc = try_selector(self.page, el["selector"], el, self.timeout_ms)
        if loc is not None:
            return loc
        if self.repairer is not None:
            fix = self.repairer.repair(self.page, self.spec, self.path, key,
                                       platform=self.platform, target=self.target, exclude=exclude)
            self.last_repair = fix
            if fix:
                self.repairs.append(fix)
                loc = try_selector(self.page, self.spec["elements"][key]["selector"], self.spec["elements"][key],
                                   self.timeout_ms)
                if loc is not None:
                    return loc
        raise AdapterError(
            "PAGE_CHANGED", f"{self.platform}: could not find '{key}' ({el.get('description', '')})",
            hint="the page layout changed; repair could not find a replacement selector",
            details={"element": key, "selector": el["selector"],
                     "screenshot": screenshot(self.page, self.platform, self.target, "-changed")})

    def _validation_error(self) -> str | None:
        sel = self.spec.get("validation_error")
        if not sel:
            return None
        try:
            for t in self.page.locator(sel).filter(visible=True).all_inner_texts():
                if t.strip():
                    return t.strip()
        except Exception:
            return None
        return None

    FORBIDDEN_CLICK = r"\b(publish|post (it|now|listing|ad)|submit|place (ad|listing)|go live|make (it )?live|send)\b"

    def guard_click(self, key: str, loc) -> None:
        """Live safety net: never click anything that reads like the final button, whatever the selector
        file or a repair says. The final button is only ever located by a stop_before step."""
        if self.target != "live":
            return
        pat = self.spec.get("forbidden_click", self.FORBIDDEN_CLICK)
        try:
            label = " ".join(x for x in (loc.inner_text(timeout=1000) or "",
                                         loc.get_attribute("value") or "", loc.get_attribute("aria-label") or "") if x)
        except Exception:
            label = ""
        url_pat = self.spec.get("forbidden_click_url")
        if re.search(pat, label, re.I) or (url_pat and re.search(url_pat, self.page.url)):
            raise AdapterError("POLICY_BLOCKED",
                               f"{self.platform}: refused to click '{key}' ('{label.strip()[:60]}') on a live site",
                               hint="the final button is the owner's click; the adapter stops before it",
                               details={"screenshot": screenshot(self.page, self.platform, self.target, "-blocked")})

    def _click_and_verify(self, key: str, loc, step: dict) -> None:
        """Click; if the selector was repaired just now, the page must visibly progress, else the
        repair is reverted and the repair loop runs again with that selector excluded."""
        from ..repair.snapshot import fingerprint

        rejected: list[str] = []
        for _attempt in range(3):
            entry = self.last_repair
            before = fingerprint(self.page)
            self.guard_click(key, loc)
            loc.click()
            self.page.wait_for_timeout(int(step.get("wait_ms", 150)))
            try:
                self.page.wait_for_load_state("domcontentloaded", timeout=self.timeout_ms)
            except Exception:
                pass
            self.check_login()
            msg = self._validation_error()
            if msg:
                raise AdapterError("INVALID_ARGS", f"{self.platform} rejected the form: {msg}",
                                   details={"screenshot": screenshot(self.page, self.platform, self.target)})
            if entry is None or fingerprint(self.page) != before:
                return
            from ..repair.loop import revert

            revert(self.spec, self.path, entry, "verifier: clicking it did not advance the page")
            if entry in self.repairs:
                self.repairs.remove(entry)
            rejected.append(entry["new"])
            loc = self.locate(key, exclude=rejected)
        raise AdapterError("PAGE_CHANGED", f"{self.platform}: no replacement for '{key}' advanced the page",
                           details={"rejected": rejected})

    def run_flow(self, values: dict, *, submit: bool = False) -> dict:
        result: dict[str, Any] = {}
        for step in self.spec["flow"]:
            do, key = step["do"], step.get("el")
            vkey = step.get("value")
            if step.get("url_contains") and step["url_contains"] not in self.page.url:
                continue
            if do == "stop_if_empty":
                # e.g. craigslist without an account (no contact email), or a room fact the site requires. Everything up to
                # here is filled; stop, screenshot, and tell the owner what unlocks the rest.
                # unless_present: a selector whose presence means the value is already known (e.g. the
                # logged-in account shown instead of an email field)
                if step.get("unless_present"):
                    try:
                        if self.page.locator(step["unless_present"]).count() > 0:
                            continue
                    except Exception:
                        pass
                el = self.spec["elements"][key]
                loc = try_selector(self.page, el["selector"], el, 800)
                have = values.get(vkey) not in (None, "") or (loc is not None and (loc.input_value() or "").strip())
                if have:
                    continue
                result.update(status="ready_to_submit", stage=step.get("stage", key),
                              screenshot=screenshot(self.page, self.platform, self.target, "-partial"),
                              needs=step.get("needs", f"'{vkey}'"), hint=step.get("hint") or self.login_hint())
                return result
            if vkey is not None and values.get(vkey) in (None, "", []) and do != "check":
                if step.get("optional", True) and not step.get("required"):
                    continue
                raise AdapterError("INVALID_ARGS", f"listing is missing '{vkey}' needed by {self.platform}")
            if step.get("if_present"):
                el = self.spec["elements"][key]
                if try_selector(self.page, el["selector"], el, 800) is None:
                    continue
            if do == "stop_before":
                loc = self.locate(key)
                loc.scroll_into_view_if_needed()
                k = loc.evaluate(KIND_JS)
                if k["disabled"]:
                    raise AdapterError("INVALID_ARGS", f"{self.platform}: final button is disabled",
                                       details={"screenshot": screenshot(self.page, self.platform, self.target)})
                result["screenshot"] = screenshot(self.page, self.platform, self.target, "-ready")
                if not submit:
                    result["status"] = "ready_to_submit"
                    return result
                if self.target != "mock":
                    raise AdapterError("POLICY_BLOCKED", "live submit is never automated; the owner clicks it")
                loc.click()
                done = self.locate(self.spec["after_submit"])
                result.update(status="live", post_id=done.get_attribute("data-listing-id"),
                              url=done.locator("a").first.get_attribute("href"))
                return result
            loc = self.locate(key)
            val = values.get(vkey) if vkey else None
            if do == "fill":
                loc.fill(str(val))
                if step.get("press"):
                    loc.press(step["press"])
            elif do == "fill_if_empty":
                if not (loc.input_value() or "").strip():
                    loc.fill(str(val))
            elif do == "select":
                try:
                    loc.select_option(label=str(val), timeout=2000)
                except Exception:
                    loc.select_option(value=str(val), timeout=2000)
            elif do == "choose":
                loc.click()
                self.page.get_by_role("option", name=str(val), exact=bool(step.get("exact"))).first.click(
                    timeout=self.timeout_ms)
            elif do == "check":
                loc.set_checked(bool(val) if vkey else True)
            elif do == "upload":
                loc.set_input_files(list(val))
            elif do == "click":
                self._click_and_verify(key, loc, step)
            else:
                raise AdapterError("INVALID_ARGS", f"unknown flow step '{do}'")
            if key not in self.filled and do != "click":
                self.filled.append(key)
        raise AdapterError("UPSTREAM_ERROR", "flow ended without a stop_before step")
