"""Channel adapters behind the contract's signatures (contracts/tools.md §4).

  publish_listing(listing, channel, target="mock"|"live")  -> {post_id, url, status, screenshot, ...}
  list_threads(channel, unanswered_only=False)              -> {threads: [...]}
  read_thread(thread_id)                                     -> {thread: {...}}
  send_message(thread_id, text)                              -> {message_id}

All return the contract envelope {"ok": true, "data": ...} | {"ok": false, "error": {...}} and never raise.

Safety: publish_listing fills everything, screenshots, and returns status "ready_to_submit"
before the final button. `submit=True` is honoured ONLY for target="mock". Inbox functions are
mock-only; nothing here sends a message on a real account.
"""
from __future__ import annotations

import os
import traceback
from typing import Any

from .engine import AdapterError, Runner, browser_page, load_spec
from .values import prepare


def classify_author(values: list[str]) -> str | None:
    """Fallback when an author marker value is not in from_map yet (e.g. first operator reply)."""
    from ..repair.proposers import OPERATOR_WORDS, RENTER_WORDS

    for v in values:
        lv = (v or "").lower()
        if lv in RENTER_WORDS:
            return "renter"
        if lv in OPERATOR_WORDS:
            return "operator"
    return None

PLATFORMS = ("marketplace", "roomies", "craigslist", "padsplit")


def mock_base_url() -> str:
    return os.environ.get("MOCK_BASE_URL", "http://127.0.0.1:8765")


def _repairer(repair: bool, proposer=None, changelog_path=None):
    if not repair:
        return None
    from ..repair.loop import Repairer
    from ..repair.proposers import default_proposer

    proposer = proposer or default_proposer()
    if proposer is None:
        return None
    return Repairer(proposer, changelog_path=changelog_path)


def _check_channel(channel: str, target: str) -> None:
    if channel not in PLATFORMS:
        raise AdapterError("INVALID_ARGS", f"unknown channel '{channel}'", hint=f"one of {', '.join(PLATFORMS)}")
    if target not in ("mock", "live"):
        raise AdapterError("INVALID_ARGS", "target must be 'mock' or 'live'")


def _wrap(fn, *a, **kw) -> dict:
    try:
        return {"ok": True, "data": fn(*a, **kw)}
    except AdapterError as e:
        return e.envelope()
    except Exception as e:  # browser crash, network, etc.
        name = type(e).__name__
        code = "TIMEOUT" if "Timeout" in name else "UPSTREAM_ERROR"
        return {"ok": False, "error": {"code": code, "message": f"{name}: {str(e)[:300]}", "retryable": True,
                                       "details": {"trace": traceback.format_exc(limit=3)[-800:]}}}


# ---------------------------------------------------------------- publish

def _publish(listing: dict, channel: str, target: str, base_url: str | None, submit: bool, repair: bool,
             proposer, selectors_dir, headless, changelog_path) -> dict:
    _check_channel(channel, target)
    if submit and target != "mock":
        raise AdapterError("POLICY_BLOCKED", "live listings are never submitted automatically",
                           hint="the adapter stops before the final button; the owner clicks it")
    spec, path = load_spec(channel, target, selectors_dir)
    values = prepare(channel, listing, target=target)
    if not values.get("photos"):
        raise AdapterError("INVALID_ARGS", "no photo files found for this listing")
    base = base_url or mock_base_url()
    with browser_page(channel, target, headless=headless) as page:
        r = Runner(page, spec, path, platform=channel, target=target,
                   repairer=_repairer(repair, proposer, changelog_path))
        page.goto(r.url("start_url", base), wait_until="domcontentloaded")
        r.check_login()
        res = r.run_flow(values, submit=submit)
        data: dict[str, Any] = {"post_id": res.get("post_id"), "url": res.get("url") or page.url,
                                "status": res["status"], "screenshot": res["screenshot"], "channel": channel,
                                "target": target, "filled": r.filled, "repairs": r.repairs}
        if res["status"] == "ready_to_submit":
            data["note"] = "form filled; stopped before the final button. Nothing was posted."
        return data


def publish_listing(listing: dict, channel: str, target: str = "mock", *, base_url: str | None = None,
                    submit: bool = False, repair: bool = True, proposer=None, selectors_dir=None,
                    headless: bool | None = None, changelog_path=None) -> dict:
    return _wrap(_publish, listing, channel, target, base_url, submit, repair, proposer, selectors_dir,
                 headless, changelog_path)


# ---------------------------------------------------------------- inbox (mock only)

def _split(thread_id: str) -> tuple[str, str]:
    if ":" not in thread_id:
        raise AdapterError("INVALID_ARGS", "thread_id must look like '<channel>:<id>'")
    ch, tid = thread_id.split(":", 1)
    return ch, tid


def _inbox_guard(channel: str, target: str) -> None:
    _check_channel(channel, target)
    if target != "mock":
        raise AdapterError("UPSTREAM_ERROR", f"live inbox for {channel} is not automated",
                           hint="live replies are drafted for the owner; the Facebook Page adapter reports a "
                                "conversation count only")


def _list(channel: str, unanswered_only: bool, target: str, base_url, repair, proposer, selectors_dir,
          changelog_path) -> dict:
    _inbox_guard(channel, target)
    spec, path = load_spec(channel, target, selectors_dir)
    base = base_url or mock_base_url()
    with browser_page(channel, target) as page:
        r = Runner(page, spec, path, platform=channel, target=target,
                   repairer=_repairer(repair, proposer, changelog_path))
        page.goto(r.url("inbox_url", base), wait_until="domcontentloaded")
        r.check_login()
        rows = r.locate("thread_row")
        el = spec["elements"]["thread_row"]
        threads = []
        for i in range(rows.count()):
            row = rows.nth(i)
            tid = row.get_attribute(el["attr"])
            text = row.inner_text().strip()
            name = None
            if el.get("name_selector"):
                try:
                    n = row.locator(el["name_selector"])
                    if n.count():
                        name = n.first.inner_text().strip()
                except Exception:
                    name = None
            if not name:
                name = text.splitlines()[0].replace("●", "").replace("New", "").strip() if text else ""
            ua = None
            if el.get("unanswered_attr"):
                raw = row.get_attribute(el["unanswered_attr"])
                if raw is not None:
                    ua = raw == el.get("unanswered_true", "1")
            threads.append({"thread_id": f"{channel}:{tid}", "channel": channel, "renter_name": name,
                            "snippet": text[-120:], "unanswered": ua})
        for t in threads:
            if t["unanswered"] is None:  # marker gone after a redesign: read the thread to decide
                th = _read_on(page, r, spec, channel, t["thread_id"].split(":", 1)[1], base)
                t["unanswered"] = bool(th["messages"]) and th["messages"][-1]["from"] == "renter"
        if unanswered_only:
            threads = [t for t in threads if t["unanswered"]]
        return {"threads": threads, "repairs": r.repairs}


def _read_on(page, r: Runner, spec: dict, channel: str, tid: str, base: str) -> dict:
    page.goto(r.url("thread_url", base).replace("{id}", tid), wait_until="domcontentloaded")
    r.check_login()
    msgs = r.locate("message")
    el = spec["elements"]["message"]
    out = []
    fmap = el.get("from_map") or {}
    for i in range(msgs.count()):
        m = msgs.nth(i)
        if el.get("from_attr") == "class":
            raw_vals = (m.get_attribute("class") or "").split()
        else:
            raw_vals = [m.get_attribute(el.get("from_attr", "data-from")) or ""]
        who = next((fmap[v] for v in raw_vals if v in fmap), None) or classify_author(raw_vals)
        ts = m.get_attribute("data-ts")
        out.append({"id": m.get_attribute(el["attr"]), "from": who, "text": m.inner_text().strip(),
                    "attachments": [], "ts": int(ts) if ts and ts.isdigit() else ts})
    name = page.title().split(" | ")[0]
    return {"thread_id": f"{channel}:{tid}", "channel": channel, "renter_name": name, "messages": out}


def _read(thread_id: str, target: str, base_url, repair, proposer, selectors_dir, changelog_path) -> dict:
    channel, tid = _split(thread_id)
    _inbox_guard(channel, target)
    spec, path = load_spec(channel, target, selectors_dir)
    with browser_page(channel, target) as page:
        r = Runner(page, spec, path, platform=channel, target=target,
                   repairer=_repairer(repair, proposer, changelog_path))
        th = _read_on(page, r, spec, channel, tid, base_url or mock_base_url())
        return {"thread": th, "repairs": r.repairs}


def _send(thread_id: str, text: str, target: str, base_url, repair, proposer, selectors_dir, changelog_path) -> dict:
    channel, tid = _split(thread_id)
    _inbox_guard(channel, target)  # live is refused above: no real messages, ever
    spec, path = load_spec(channel, target, selectors_dir)
    base = base_url or mock_base_url()
    with browser_page(channel, target) as page:
        r = Runner(page, spec, path, platform=channel, target=target,
                   repairer=_repairer(repair, proposer, changelog_path))
        before = _read_on(page, r, spec, channel, tid, base)
        r.locate("reply_box").fill(text)
        with page.expect_navigation(wait_until="domcontentloaded"):
            r.locate("send_button").click()
        after = _read_on(page, r, spec, channel, tid, base)
        new = [m for m in after["messages"] if m["id"] not in {x["id"] for x in before["messages"]}]
        if not new:
            raise AdapterError("UPSTREAM_ERROR", "message did not appear in the thread after sending")
        return {"message_id": f"{channel}:{new[-1]['id']}", "repairs": r.repairs}


def list_threads(channel: str, unanswered_only: bool = False, target: str = "mock", *, base_url=None,
                 repair: bool = True, proposer=None, selectors_dir=None, changelog_path=None) -> dict:
    return _wrap(_list, channel, unanswered_only, target, base_url, repair, proposer, selectors_dir, changelog_path)


def read_thread(thread_id: str, target: str = "mock", *, base_url=None, repair: bool = True, proposer=None,
                selectors_dir=None, changelog_path=None) -> dict:
    return _wrap(_read, thread_id, target, base_url, repair, proposer, selectors_dir, changelog_path)


def send_message(thread_id: str, text: str, attachments: list | None = None, target: str = "mock", *,
                 base_url=None, repair: bool = True, proposer=None, selectors_dir=None, changelog_path=None) -> dict:
    return _wrap(_send, thread_id, text, target, base_url, repair, proposer, selectors_dir, changelog_path)
