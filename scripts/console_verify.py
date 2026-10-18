r"""Verify the console UI end to end with Playwright and screenshot each page into docs/img/.

    channels/.venv/bin/python scripts/console_verify.py all
    channels/.venv/bin/python scripts/console_verify.py tabs inbox approval model phone assistant

Paths (each prints PASS/FAIL lines and saves screenshots):
  tabs       every tab (Inbox, Assistant, Pipeline, Model) renders with no page errors,
             light and dark                                                docs/img/console-{tab}.png, console-{tab}-dark.png
  inbox      the live inbox lists threads (or a clean empty state); a thread opens with
             messages, the qualification dots and the Activity drawer      docs/img/console-inbox-thread.png
  approval   Approve / Edit / Deny on drafts, in the thread view and on the phone page. Runs on a
             second console process with the in-memory fake channels (console/tests/fake_live.py), so
             nothing reaches a real person                                 docs/img/console-approval.png, approve-phone.png
  model      the Model tab shows the numbers the result endpoints serve (/api/results, /api/trust,
             /api/performance), never hardcoded ones                       docs/img/console-model.png
  public     the read-only public console on :8092 (CONSOLE_PUBLIC_READONLY=1): every tab renders, no action
             buttons, writes refused, no personal-Messenger threads          docs/img/console-public-*.png
  phone      /approve on the real console at phone size                    docs/img/approve-phone-live.png
  assistant  LIVE operator run (uses the GPU): the owner types a listing instruction in the Assistant,
             the operator's reply and its tool calls appear, the listing card shows per-channel status
                                                                           docs/img/console-assistant.png

The console must be up on 127.0.0.1:8080 (scripts/demo.sh). `all` runs every path.
"""
from __future__ import annotations

import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parent.parent
API = os.environ.get("CONSOLE_URL", "http://127.0.0.1:8080")
IMG = REPO / "docs" / "img"
RESULTS: list[tuple[str, bool, str]] = []
PY = REPO / ".venv" / "bin" / "python"


def check(name: str, ok: bool, detail: str = ""):
    RESULTS.append((name, bool(ok), detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""), flush=True)


def get(path, base=API):
    return httpx.get(base + path, timeout=30).json()


def open_page(p, url, width=1600, height=960, scheme="light", mobile=False):
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": width, "height": height}, color_scheme=scheme, is_mobile=mobile,
                        device_scale_factor=2 if mobile else 1)
    page = ctx.new_page()
    page._errors = []
    page.on("pageerror", lambda e: page._errors.append(str(e)))
    page.goto(url)
    return b, page


def shoot(page, name):
    IMG.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(IMG / name))
    print(f"        screenshot docs/img/{name}")


# ------------------------------------------------------------------ paths
def path_tabs(p):
    for scheme in ("light", "dark"):
        b, pg = open_page(p, API + "/#/inbox", scheme=scheme)
        for tab, sel in (("inbox", "#thread-list"), ("assistant", "#ask"), ("pipeline", "#page-pipeline .page-head"),
                         ("model", "#page-model .kpis"), ("data", "#page-data .flow")):
            pg.goto(API + f"/#/{tab}")
            try:
                pg.wait_for_selector(sel, timeout=15000)
                pg.wait_for_timeout(1800)
                ok = pg.is_visible(sel)
            except Exception:
                ok = False
            check(f"{tab} tab renders ({scheme})", ok and not pg._errors, "; ".join(pg._errors[:2]))
            shoot(pg, f"console-{tab}{'-dark' if scheme == 'dark' else ''}.png")
        st = pg.inner_text(".top .status")
        check(f"top bar shows operator, reader and channel status ({scheme})",
              "Operator" in st and "Reader" in st, st.replace("\n", " ")[:120])
        b.close()


def path_inbox(p):
    th = get("/api/live/threads")
    b, pg = open_page(p, API + "/#/inbox")
    pg.wait_for_selector("#thread-list", timeout=15000)
    pg.wait_for_timeout(2000)
    if not th.get("items"):
        check("inbox shows a clean empty state when there are no threads", pg.is_visible("#thread-list .empty"),
              th.get("error") or "no threads")
        shoot(pg, "console-inbox-thread.png")
        b.close()
        return
    check("inbox lists every live thread", len(pg.query_selector_all(".titem")) == len(th["items"]),
          f"{len(th['items'])} threads")
    pg.click(".titem")
    pg.wait_for_selector("#msgs .msg", timeout=15000)
    pg.wait_for_timeout(1200)
    check("thread opens with its messages", len(pg.query_selector_all("#msgs .msg")) >= 1)
    first = th["items"][0]
    nd = len(pg.query_selector_all(".qual .gate i"))
    if first.get("role") in (None, "prospect"):
        check("qualification items shown for a prospect", nd in (4, 5), f"{nd} items ({first.get('channel')}; SMS hides phone)")
    else:
        check("no qualification dots for tenant / lease threads", nd == 0, first.get("role"))
    if not pg.is_visible(".activity"):
        pg.click("#toggle-act")
    check("Activity drawer lists the thread's trace", pg.is_visible(".activity .act-list"))
    check("no page errors", not pg._errors, "; ".join(pg._errors[:2]))
    shoot(pg, "console-inbox-thread.png")
    b.close()


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def path_approval(p):
    port = _free_port()
    runs = REPO / "runs" / "_verify_fake"
    runs.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "CONSOLE_LIVE_MODULE": "console.tests.fake_live", "CONSOLE_FB_MODULE": "console.tests.fake_fb",
           "CONSOLE_FORCE_STUB": "1",
           "OPERATOR_BASE_URL": "", "CONSOLE_RUNS_DIR": str(runs)}
    proc = subprocess.Popen([str(PY if PY.exists() else sys.executable), "-m", "uvicorn", "console.app:app",
                             "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"], cwd=REPO, env=env)
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(60):
            try:
                if httpx.get(base + "/api/status", timeout=0.5).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.25)
        b, pg = open_page(p, base + "/#/inbox/t_test_sam")
        pg.wait_for_selector(".pending", timeout=15000)
        check("a draft waiting for approval shows Approve / Edit / Deny in the thread",
              all(pg.is_visible(f'.pending button[data-act="{a}"]') for a in ("approve", "edit", "deny")))
        shoot(pg, "console-approval.png")
        pg.click('.pending button[data-act="edit"]')
        pg.fill(".pending .edit-text", "Thanks Sam. The rent is $750 a month and it's firm.")
        pg.click('.pending button[data-act="send-edit"]')
        pg.wait_for_function("() => !document.querySelector('.pending')", timeout=10000)
        pg.wait_for_timeout(2600)
        last = pg.query_selector_all("#msgs .msg.out .b")[-1].inner_text()
        check("Edit sends the owner's text, not the draft", "it's firm" in last, last[:60])
        pg.goto(base + "/#/inbox/t_test_lee")
        pg.wait_for_selector(".note", timeout=15000)
        note = pg.inner_text(".note summary")
        check("operator reports show as a compact note without internal ids", "Note from operator" in note
              and "9f8e7d6c" not in note and not pg.query_selector('.note button[data-act="approve"]'), note[:80])
        check("operator typing indicator", pg.is_visible(".typing") and pg.is_visible(".titem .chip.accent"))
        pg.click(".note summary")
        shoot(pg, "console-inbox-note.png")
        pg.goto(base + "/#/inbox/t_test_mp")
        pg.wait_for_selector(".pending", timeout=15000)
        check("Marketplace Messenger thread labeled", "Marketplace · Messenger" in pg.inner_text(".convo-head"))

        # Facebook Page: prepare (unpublished) and Publish only on the owner's click, against the fake Page
        rid = httpx.post(base + "/api/runs", json={"goal": "Appling Way room free Nov 1, $750, private bath", "origin": "verify"}, timeout=30).json()["run_id"]
        for _ in range(60):
            if get(f"/api/runs/{rid}/posts", base)["listings"]:
                break
            time.sleep(0.5)
        pg.on("dialog", lambda d: d.accept())
        pg.goto(base + f"/?origin=verify&run={rid}#/assistant")
        pg.wait_for_selector('button[data-fb="publish"]', timeout=20000)
        fb0 = get(f"/api/runs/{rid}/posts", base)["listings"][0]["channels"][-1]["state"]
        check("Facebook Page is never posted without a click", fb0 == "not_prepared", fb0)
        check("Facebook row previews the post text before publishing", "Appling" in pg.inner_text(".prow.fb"))
        pg.click('button[data-fb="publish"]')
        pg.wait_for_selector('text=View post', timeout=15000)
        fb1 = get(f"/api/runs/{rid}/posts", base)["listings"][0]["channels"][-1]
        check("Publish on the owner's click publishes the Page post (fake Page)", fb1["state"] == "published", fb1["label"])
        shoot(pg, "console-assistant-facebook.png")
        b.close()

        b, ph = open_page(p, base + "/approve", width=390, height=844, mobile=True)
        ph.wait_for_selector(".card", timeout=15000)
        n = len(ph.query_selector_all(".card[data-id]"))
        check("phone /approve lists the open approvals", n >= 1, f"{n} open")
        shoot(ph, "approve-phone.png")
        ph.click('.card[data-id="ap_2"] button[data-act="approve"]')
        ph.wait_for_selector(".done", timeout=10000)
        check("Approve on the phone records the decision", not get("/api/live/approvals", base)["items"] or
              all(a["id"] != "ap_2" for a in get("/api/live/approvals", base)["items"]))
        check("no page errors", not (pg._errors or ph._errors))
        b.close()
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def path_model(p):
    r, t = get("/api/results"), get("/api/trust")
    b, pg = open_page(p, API + "/#/model")
    pg.wait_for_selector("#page-model .kpis", timeout=20000)
    pg.wait_for_timeout(1500)
    text = pg.inner_text("#page-model")
    fin = next((c for c in r.get("configs") or [] if c["kind"] == "final"), None)
    base = next((c for c in r.get("configs") or [] if c["kind"] == "baseline"), None)
    if fin and base:
        want = [f"{fin['pass_rate'] * 100:.1f}%", f"{base['pass_rate'] * 100:.1f}%", f"{fin['mean_reward']:.3f}"]
        check("plain setup names (no bare 'Final')", "Final" not in text and "starting setup" in text, r.get("version"))
        check("metric explanations available on hover", len(pg.query_selector_all("#page-model .info")) >= 6)
        if r.get("floors"):
            check("reference floors shown", "Reference: Does nothing" in text)
        check("held-out numbers match /api/results", all(w in text for w in want), ", ".join(want) + f" ({r.get('version')})")
        check("charts with confidence intervals drawn", len(pg.query_selector_all(".chart svg .whisk")) >= 6)
    else:
        check("held-out section shows a clean empty state", "No held-out results yet" in text)
    rd = t.get("reader") or {}
    if rd.get("sample"):
        check("reader exact match vs Lightning vs Opus shown",
              f"{rd['sample']['finetuned'] * 100:.0f}%" in text and "Claude Opus 5.5" in text and "Lightning" in text)
    check("serving numbers shown (prefix caching, reasoning off)", "Prefix caching" in text and "Reasoning off" in text)
    bud = t.get("budget") or {}
    check("parameter budget shown", f"{bud.get('used_b', 0):.1f}B" in text and f"{bud.get('limit_b', 0):g}B" in text)
    check("no page errors", not pg._errors, "; ".join(pg._errors[:2]))
    shoot(pg, "console-model.png")
    pg.set_viewport_size({"width": 1600, "height": 2600})
    shoot(pg, "console-model-full.png")
    b.close()


def path_phone(p):
    b, ph = open_page(p, API + "/approve", width=390, height=844, mobile=True)
    ph.wait_for_selector("#list", timeout=10000)
    ph.wait_for_timeout(2500)
    ok = ph.is_visible("#list .card") or ph.is_visible("#list .empty")
    check("live /approve renders at phone size", ok and not ph._errors)
    shoot(ph, "approve-phone-live.png")
    b.close()


def path_assistant(p, timeout=240):
    b, pg = open_page(p, API + "/?origin=verify#/assistant")  # tagged: verify runs never show in the owner's history
    pg.wait_for_selector("#ask", timeout=15000)
    check("opening the Assistant sends nothing and the box starts empty", pg.input_value("#ask") == "" and not pg.query_selector(".turn-owner"))
    pg.click("#new-chat")
    pg.wait_for_timeout(1000)
    pg.fill("#ask", "Appling Way room free Nov 1, $750, private bath. Post it on Marketplace, Roomies, Craigslist and the Facebook Page.")
    pg.click("#ask-send")
    t0 = time.time()
    try:
        pg.wait_for_selector(".turn-op .text", timeout=timeout * 1000)
        pg.wait_for_function("() => !document.querySelector('.turn-op .working')", timeout=timeout * 1000)
        done = True
    except Exception:
        done = False
    check("operator answers the owner in the Assistant", done, f"{time.time() - t0:.0f}s")
    pg.wait_for_timeout(3500)
    if pg.query_selector(".steps-toggle"):
        tog = pg.inner_text(".steps-toggle")
        n = int(re.search(r"(\d+) tool call", tog).group(1)) if re.search(r"(\d+) tool call", tog) else 0
        check("tool calls listed under the reply", n >= 2, tog.replace("\n", " "))
        pg.click(".steps-toggle")
    rid = get("/api/status").get("active_run")
    if rid:
        ls = get(f"/api/runs/{rid}/posts").get("listings") or []
        rows = [r for l in ls for r in l["channels"] if r["channel"] != "facebook_page"]
        states = ", ".join(f"{r['channel']}={r['label']}" for r in rows)
        check("every platform is Ready / Needs login (never Posted or sandbox)", rows and all(r["state"] in ("ready", "login") for r in rows), states)
        if ls and ls[0].get("photos"):
            check("photo strip on the listing card", len(pg.query_selector_all(".listing-prev .strip:not(.sm) img")) == len(ls[0]["photos"]),
                  f"{len(ls[0]['photos'])} photos")
    check("listing card with per-channel status", pg.is_visible(".listing-prev") and len(pg.query_selector_all(".listing-prev .rows > div")) >= 1)
    check("no page errors", not pg._errors, "; ".join(pg._errors[:2]))
    shoot(pg, "console-assistant.png")
    check("verify run kept out of the owner's chat history", all(c["run_id"] != rid for c in get("/api/chats")))
    httpx.post(API + "/api/reset", timeout=15)  # leave nothing running for the owner
    b.close()


PUBLIC = os.environ.get("CONSOLE_PUBLIC_URL_LOCAL", "http://127.0.0.1:8092")


def path_public(p):
    """The public read-only console (CONSOLE_PUBLIC_READONLY=1 on :8092): tabs render, no controls, writes refused."""
    st = get("/api/status", PUBLIC)
    check("public console runs in read-only mode", st.get("public_readonly") is True)
    for method, path in (("POST", "/api/runs"), ("POST", "/api/reset"), ("POST", "/api/live/conversations"),
                         ("POST", "/api/live/approvals/x"), ("POST", "/api/live/threads/x/reply"),
                         ("POST", "/api/runs/x/listings/L001/facebook"), ("GET", "/approve"), ("GET", "/api/file?path=runs/x.png")):
        code = httpx.request(method, PUBLIC + path, json={"text": "x"}, timeout=10).status_code
        check(f"public {method} {path.split('?')[0]} refused", code == 403, str(code))
    th = get("/api/live/threads", PUBLIC).get("items") or []
    check("no personal-Messenger threads in public", all(t["channel"] != "messenger_personal" for t in th), f"{len(th)} threads")
    b, pg = open_page(p, PUBLIC + "/#/inbox")
    for tab, sel in (("inbox", "#thread-list"), ("assistant", "#chat"), ("pipeline", "#page-pipeline .page-head"),
                     ("model", "#page-model .kpis"), ("data", "#page-data .flow")):
        pg.goto(PUBLIC + f"/#/{tab}")
        pg.wait_for_selector(sel, timeout=20000)
        pg.wait_for_timeout(1500)
        if tab == "inbox" and pg.query_selector(".titem"):
            pg.click(".titem")
            pg.wait_for_timeout(2000)
        visible_actions = [x for x in pg.query_selector_all("button[data-act], #reply-send, #ask-send, #new-convo, #new-chat, [data-fb], #archive-thread") if x.is_visible()]
        check(f"public {tab}: renders with no action buttons", not visible_actions and pg.is_visible(".ro-banner") and not pg._errors,
              f"{len(visible_actions)} visible")
        shoot(pg, f"console-public-{tab}.png")
    b.close()


PATHS = {"tabs": path_tabs, "inbox": path_inbox, "approval": path_approval, "model": path_model, "phone": path_phone,
         "assistant": path_assistant, "public": path_public}


def main(argv) -> int:
    from playwright.sync_api import sync_playwright
    names = [n for n in PATHS if n != "public"] if not argv or argv == ["all"] else argv  # public needs the :8092 process
    with sync_playwright() as p:
        for n in names:
            print(f"== {n}", flush=True)
            try:
                PATHS[n](p)
            except Exception as e:
                check(f"{n} completed", False, f"{type(e).__name__}: {e}"[:200])
    bad = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(bad)}/{len(RESULTS)} checks passed")
    for n, _, d in bad:
        print(f"  FAIL {n} {d}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
