r"""Verify every console demo path end to end on the LIVE models, and screenshot each into docs/img/.

    channels/.venv/bin/python scripts/console_verify.py all
    channels/.venv/bin/python scripts/console_verify.py listing spanish faults ops panels demo

Paths (each prints PASS/FAIL lines and saves a screenshot):
  listing   owner instruction -> listing live in the channel lanes            docs/img/console-listing.png
  spanish   Gym task lease-spanish-train-003: gate ticks fill, a showing is
            proposed only after all five items are answered                   docs/img/console-spanish.png
  faults    page changed + login wall on publish, rate limit on send, a
            malformed reader result -> retry / verifier / fallback in trace   docs/img/console-faults.png
  ops       Gym task ops-under_limit-heldout-001: vendor timeout, booking
            under the limit, tenant notified                                  docs/img/console-ops.png
  panels    scoreboard, why-trust-it and real-world tabs                      docs/img/console-{scoreboard,trust,realworld}.png
  demo      one-click demo run; the owner approves on a phone-sized /approve  docs/img/console-demo.png, approve-phone.png

The console must be up (scripts/demo.sh) with the operator and reader endpoints live.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parent.parent
API = "http://127.0.0.1:8080"
IMG = REPO / "docs" / "img"
RESULTS: list[tuple[str, bool, str]] = []
EDIT_TEXT = "Thanks for asking, the rent is firm at $750 a month."


def check(name: str, ok: bool, detail: str = ""):
    RESULTS.append((name, bool(ok), detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""), flush=True)


def get(path):
    return httpx.get(API + path, timeout=15).json()


def post(path, body=None):
    r = httpx.post(API + path, json=body or {}, timeout=30)
    r.raise_for_status()
    return r.json()


def events(run_id: str) -> list[dict]:
    p = REPO / "runs" / run_id / "events.jsonl"
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []


def notes(run_id: str) -> list[dict]:
    p = REPO / "runs" / run_id / "console.jsonl"
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []


def wait_idle(run_id: str, timeout: float, settle: float = 6.0) -> float:
    t0, since = time.time(), None
    while time.time() - t0 < timeout:
        st = get(f"/api/runs/{run_id}").get("status")
        if st in ("idle", "stopped", "error"):
            since = since or time.time()
            if time.time() - since >= settle:
                return time.time() - t0
        else:
            since = None
        time.sleep(2)
    return -1


def results_of(evs, tool):
    return [e["data"] for e in evs if e["type"] == "tool_result" and e["data"].get("tool") == tool]


def shoot(page, name: str, run_id: str | None = None, tab: str | None = None):
    if tab:
        page.click(f".tab[data-tab='{tab}']")
    page.wait_for_timeout(2500)
    out = IMG / name
    page.screenshot(path=str(out))
    print(f"  shot  {out.relative_to(REPO)}")


def open_page(p, width=1680, height=1050):
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": width, "height": height})
    page.goto(API + "/", wait_until="load")
    page.wait_for_timeout(5000)  # status poll attaches to the active run, SSE replays its events
    return b, page


# ------------------------------------------------------------------------------------------ paths
def path_listing(p):
    print("listing: owner instruction -> listing in lanes")
    r = post("/api/runs", {"goal": "Appling Way room free Nov 1, $750, private bath", "speed": 4})
    rid = r["run_id"]
    check("live operator mode", r["mode"] == "operator", r["mode"])
    t = wait_idle(rid, 300, settle=3)
    v = get(f"/api/runs/{rid}/view")
    live = {ch: [x for x in L["posts"] if x["status"] == "live"] for ch, L in v["lanes"].items()}
    lanes = [ch for ch, xs in live.items() if xs]
    check("listing live in at least 3 lanes", len(lanes) >= 3, ", ".join(lanes))
    evs = events(rid)
    comp = results_of(evs, "check_listing_compliance")
    created = [((d.get("result") or {}).get("data") or {}).get("compliance") or {} for d in results_of(evs, "create_listing")]
    check("fair-housing compliance clean", created and all(c.get("ok", True) for c in created),
          f"check_listing_compliance called {len(comp)}x; create_listing compliance {created[-1] if created else None}")
    check("price 750 from the owner", any(x["price"] == 750 for xs in live.values() for x in xs))
    print(f"  listing turn finished in {t:.0f}s")
    b, page = open_page(p)
    shoot(page, "console-listing.png")
    b.close()
    post("/api/reset")


def gate_ok_before_showing(evs) -> tuple[bool, str]:
    shows = [i for i, e in enumerate(evs) if e["type"] == "tool_result" and e["data"].get("tool") == "propose_showing"
             and (e["data"].get("result") or {}).get("ok")]
    if not shows:
        return False, "no showing proposed"
    ups = [(i, (e["data"].get("result") or {}).get("data") or {}) for i, e in enumerate(evs)
           if e["type"] == "tool_result" and e["data"].get("tool") == "upsert_renter" and i < shows[0]]
    if not ups:
        return False, "no upsert before showing"
    missing = ups[-1][1].get("gate_missing")
    return missing == [], f"gate_missing before showing = {missing}"


def path_spanish(p):
    print("spanish: leasing scenario in Spanish -> gate ticks -> showing only after all five")
    r = post("/api/runs", {"scenario_id": "lease-spanish-train-003", "speed": 4})
    rid = r["run_id"]
    t = wait_idle(rid, 420, settle=4)
    v = get(f"/api/runs/{rid}/view")
    reg = v["register"]
    check("renter registered", bool(reg), ", ".join(x["name"] for x in reg))
    if reg:
        g = reg[0]["gate"]
        check("all five gate items ticked", all(g[k]["state"] == "ok" for k in g), json.dumps({k: g[k]["state"] for k in g}))
    evs = events(rid)
    ok, why = gate_ok_before_showing(evs)
    check("showing proposed only after the gate was complete", ok, why)
    refused = [d for d in results_of(evs, "propose_showing") if not (d.get("result") or {}).get("ok")]
    print(f"  propose_showing refused {len(refused)}x before the gate was complete; turn {t:.0f}s")
    msgs = [e["data"]["args"]["text"] for e in evs if e["type"] == "tool_call" and e["data"].get("tool") == "send_message"]
    es = sum(1 for m in msgs if any(w in m.lower() for w in ("¿", "hola", "gracias", "mudanza", "contrato", "teléfono")))
    check("operator replied in Spanish", msgs and es >= len(msgs) * 0.7, f"{es}/{len(msgs)} messages")
    reads = results_of(evs, "read_reply")
    backends = {((d.get("result") or {}).get("data") or {}).get("backend") for d in reads}
    check("read_reply served by the fine-tuned reader", "model" in backends, f"backends={backends}")
    b, page = open_page(p)
    shoot(page, "console-spanish.png")
    b.close()
    post("/api/reset")


def path_faults(p):
    print("faults: page changed, login wall, rate limited, malformed -> visible recovery")
    r = post("/api/runs", {"goal": "Appling Way room free Nov 1, $750, private bath. Post it on Marketplace, Roomies, "
                                   "Craigslist and PadSplit.", "speed": 4})
    rid = r["run_id"]
    for f in ({"kind": "page_changed", "tool": "publish_listing", "match": {"channel": "craigslist"}},
              {"kind": "login_required", "tool": "publish_listing", "match": {"channel": "padsplit"}},
              {"kind": "rate_limited", "tool": "send_message"},
              {"kind": "malformed", "tool": "read_reply"}):
        post(f"/api/runs/{rid}/faults", f)
    t = wait_idle(rid, 480, settle=8)
    evs = events(rid)
    fired = [d for e in evs if e["type"] == "tool_result" for d in [e["data"]] if d.get("fault")
             or ((d.get("result") or {}).get("error") or {}).get("code") in ("PAGE_CHANGED", "LOGIN_REQUIRED", "RATE_LIMITED")]
    codes = sorted({((d.get("result") or {}).get("error") or {}).get("code") or d.get("fault") for d in fired})
    check("all four faults fired", len(codes) >= 4, ", ".join(map(str, codes)))
    retries = [e["data"] for e in evs if e["type"] == "retry"]
    check("rate limit retried", any(d.get("code") == "RATE_LIMITED" for d in retries))
    vcatch = [e["data"] for e in evs if e["type"] == "verifier" and e["data"].get("stage") == "result" and e["data"].get("ok") is False]
    check("verifier caught the malformed reader result", any(d.get("tool") == "read_reply" for d in vcatch))
    fbs = [e["data"] for e in evs if e["type"] == "fallback"]
    check("broken channels fell back", any(d.get("code") in ("PAGE_CHANGED", "LOGIN_REQUIRED") for d in fbs),
          "; ".join(f"{d.get('tool')} {d.get('code')}" for d in fbs))
    v = get(f"/api/runs/{rid}/view")
    live = [ch for ch, L in v["lanes"].items() if any(x["status"] == "live" for x in L["posts"])]
    check("other channels still went live", len(live) >= 2, ", ".join(live))
    check("owner told about the broken channels", any("craigslist" in (e.get("reason") or "").lower()
          or "padsplit" in (e.get("reason") or "").lower() or "page" in (e.get("reason") or "").lower()
          for e in v["escalations"]) or any("craigslist" in json.dumps(e["data"]).lower() for e in evs
                                             if e["type"] == "owner_message" and e["actor"] != "owner"))
    print(f"  fault run idle after {t:.0f}s")
    b, page = open_page(p)
    page.uncheck("#followTrace")
    # scroll the trace to the first recovery row so the screenshot shows it
    page.evaluate("""() => { const r = [...document.querySelectorAll('#trace .row.retry, #trace .row.vfail, #trace .row.fb')][0];
                      if (r) r.scrollIntoView({block: 'center'}); }""")
    shoot(page, "console-faults.png")
    b.close()
    post("/api/reset")


def path_ops(p):
    print("ops: plumber job -> vendor timeout, booking under limit, tenant notified")
    r = post("/api/runs", {"scenario_id": "ops-under_limit-heldout-001", "speed": 4})
    rid = r["run_id"]
    t = wait_idle(rid, 300, settle=4)
    evs = events(rid)
    q = results_of(evs, "request_quote")
    check("a vendor timed out", any(((d.get("result") or {}).get("error") or {}).get("code") == "TIMEOUT" for d in q))
    check("two or more quotes", sum(1 for d in q if (d.get("result") or {}).get("ok")) >= 2)
    v = get(f"/api/runs/{rid}/view")
    booked = [j for j in v["jobs"] if j.get("status") == "booked"]
    lim = v["spend"]["limit"]
    check("booked under the limit", booked and all(float(j["cost"]) <= lim for j in booked),
          f"{[(j.get('vendor_id'), j.get('cost')) for j in booked]} limit {lim}")
    quotes = [((d.get("result") or {}).get("data") or {}).get("quote", {}).get("amount") for d in q if (d.get("result") or {}).get("ok")]
    check("cheapest quote booked", booked and float(booked[0]["cost"]) == min(quotes), f"quotes {quotes}")
    sent = [e["data"] for e in evs if e["type"] == "tool_result" and e["data"].get("tool") == "send_message"
            and (e["data"].get("result") or {}).get("ok")]
    check("tenant notified", bool(sent))
    print(f"  ops turn {t:.0f}s")
    b, page = open_page(p)
    shoot(page, "console-ops.png")
    b.close()
    post("/api/reset")


def path_panels(p):
    print("panels: scoreboard, trust, real world")
    t = get("/api/trust")
    o, ref = t["heldout"]["ours"], t["heldout"]["reference"]
    check("trust: budget under 33B", t["budget"]["used_b"] <= 33, f"{t['budget']['used_b']}B")
    check("trust: held-out numbers from result files", o and ref, f"ours {o['passed']}/{o['tasks']} {o['mean_reward']:.3f} vs "
          f"Opus {ref['passed']}/{ref['tasks']} {ref['mean_reward']:.3f}")
    rw = get("/api/realworld")
    check("real world: live post link", bool(rw["post"] and rw["post"]["permalink"]), rw["post"]["permalink"] if rw["post"] else "")
    check("real world: thumbnail cached", bool(rw["thumb"]))
    sb = get("/api/scoreboard")
    check("scoreboard: baseline and final rows", any(r["kind"] == "baseline" for r in sb) and any(r["kind"] == "final" for r in sb))
    b, page = open_page(p)
    for tab, name in (("score", "console-scoreboard.png"), ("trust", "console-trust.png"), ("real", "console-realworld.png")):
        page.click(f".tab[data-tab='{tab}']")
        page.wait_for_timeout(1500)
        page.locator("footer .evidence").screenshot(path=str(IMG / name))
        print(f"  shot  docs/img/{name}")
    b.close()


def path_demo(p, speed: float = 1.0):
    print("demo: one-click demo run, owner approves on the phone view")
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 1920, "height": 1080})
    page.goto(API + "/", wait_until="load")
    page.wait_for_timeout(2000)
    page.select_option("#speed", str(int(speed)) if speed >= 1 else str(speed))
    t0 = time.time()
    page.click("#demoBtn")
    page.wait_for_timeout(3000)
    st = get("/api/status")
    rid = st["active_run"]
    check("demo started on the live operator", st["mode"] == "operator" and rid and rid.startswith("d_"), str(rid))
    phone = b.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True)
    phone_url = st["approve_url"]
    try:
        phone.goto(phone_url, wait_until="load")
        via = "tailnet " + phone_url
    except Exception:
        phone.goto(API + "/approve", wait_until="load")
        via = "localhost (tailnet unreachable from here)"
    print(f"  phone view via {via}")
    approved = edited = False
    shots = {}
    while time.time() - t0 < 600:
        d = get("/api/status").get("demo") or {}
        step = d.get("step")
        if step and step not in shots and step in ("renters", "fault", "ops"):
            shots[step] = True
            page.wait_for_timeout(1500)
            page.screenshot(path=str(IMG / f"console-demo-{step}.png"))
        if step == "approve" and not approved and phone.locator(".card:not(.done) button.approve").count():
            phone.wait_for_timeout(1500)
            phone.screenshot(path=str(IMG / "approve-phone.png"))
            page.screenshot(path=str(IMG / "console-demo-approve.png"))
            print("  shot  docs/img/approve-phone.png")
            card = phone.locator(".card:not(.done)").first
            if card.locator("textarea").count():  # the owner rewrites the reply in his own words
                card.locator("button.edit").tap()
                card.locator("textarea").fill(EDIT_TEXT)
                phone.wait_for_timeout(500)
                phone.screenshot(path=str(IMG / "approve-phone-edit.png"))
                edited = True
            card.locator("button.approve").tap()
            approved = True
            phone.wait_for_timeout(2500)
            phone.screenshot(path=str(IMG / "approve-phone-done.png"))
        if d.get("finished"):
            break
        time.sleep(2)
    d = get("/api/status").get("demo") or {}
    check("demo reached the end", d.get("step") == "done" and not d.get("error"), f"{d.get('step')} {d.get('error') or ''}")
    print(f"  demo took {d.get('elapsed')}s at {speed}x")
    ns = notes(rid)
    check("owner approved from the phone", any(n["type"] == "owner_decision" and n["data"].get("via") == "phone" for n in ns)
          or not approved, "approved" if approved else "nothing was waiting for the owner")
    page.wait_for_timeout(3000)
    page.screenshot(path=str(IMG / "console-demo.png"))
    print("  shot  docs/img/console-demo.png")
    evs = events(rid)
    if edited:
        sent = [e["data"]["args"]["text"] for e in evs if e["type"] == "tool_call" and e["data"].get("tool") == "send_message"]
        check("the owner's edited text reached the renter unchanged", EDIT_TEXT in sent,
              f"last sends: {sent[-2:]}")
    kinds = {e["type"] for e in evs}
    check("demo trace shows retry and verifier catches", "retry" in kinds and any(
        e["type"] == "verifier" and e["data"].get("ok") is False for e in evs))
    b.close()


PATHS = {"listing": path_listing, "spanish": path_spanish, "faults": path_faults, "ops": path_ops,
         "panels": path_panels, "demo": path_demo}


def main(argv) -> int:
    names = list(PATHS) if not argv or argv == ["all"] else argv
    st = get("/api/status")
    print("badge:", st["badge"]["label"], "|", st["reader"]["label"], "| config:", st.get("operator_config"))
    if not st["badge"]["live"]:
        print("operator endpoint is not live; these checks are for the live models")
        return 2
    IMG.mkdir(parents=True, exist_ok=True)
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        for n in names:
            try:
                PATHS[n](p)
            except Exception as e:  # keep going; report it
                check(f"{n} crashed", False, f"{type(e).__name__}: {e}")
                try:
                    post("/api/reset")
                except Exception:
                    pass
    bad = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(bad)}/{len(RESULTS)} checks passed")
    for name, _, detail in bad:
        print(f"  FAIL {name}: {detail}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
