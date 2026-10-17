r"""Drive the console end to end and screenshot it (Playwright, headless Chromium).

    .venv/bin/python scripts/console_run.py --goal "Appling Way room free Nov 1, \$750, private bath" \
        --out docs/img/console-listing.png
    .venv/bin/python scripts/console_run.py --scenario lease-full-heldout-001 --out docs/img/console-leasing.png
    .venv/bin/python scripts/console_run.py --attach --out docs/img/console-now.png   # screenshot the active run

Starts the run through the console API (console must be up: scripts/demo.sh), waits until the operator is
idle, prints a summary (mode, listings per lane, register gate ticks, escalations), then opens the page,
lets the event stream replay, and saves a full-page screenshot.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parent.parent


def wait_idle(api: str, run_id: str, timeout: float, settle: float = 12.0) -> dict:
    """Idle for `settle` seconds in a row (free play seeds renters a few seconds after the listing)."""
    t0, idle_since, info = time.time(), None, {}
    while time.time() - t0 < timeout:
        info = httpx.get(f"{api}/api/runs/{run_id}", timeout=5).json()
        if info.get("status") in ("idle", "stopped", "error", "finished"):
            idle_since = idle_since or time.time()
            if time.time() - idle_since >= settle:
                return info
        else:
            idle_since = None
        time.sleep(2)
    info["timed_out"] = True
    return info


def summary(api: str, run_id: str) -> dict:
    v = httpx.get(f"{api}/api/runs/{run_id}/view", timeout=5).json()
    return {
        "mode": v.get("mode"),
        "lanes": {k: {"posts": len(x["posts"]), "threads": len(x["threads"])} for k, x in v["lanes"].items()
                  if x["posts"] or x["threads"]},
        "register": [{"renter": r.get("name") or r.get("renter_id"), "status": r.get("status"),
                      "gate": {k: g.get("state") for k, g in (r.get("gate") or {}).items()}} for r in v["register"]],
        "escalations": [e.get("reason") for e in v["escalations"]],
        "calendar": len(v.get("calendar") or []),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://127.0.0.1:8080")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--goal")
    g.add_argument("--scenario")
    g.add_argument("--attach", action="store_true")
    ap.add_argument("--speed", type=float, default=4.0)
    ap.add_argument("--timeout", type=float, default=420)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    st = httpx.get(f"{a.api}/api/status", timeout=10).json()
    print("badge:", st["badge"]["label"], "|", (st.get("reader") or {}).get("label"))
    if a.attach:
        run_id = st.get("active_run")
        if not run_id:
            print("no active run"); return 1
    else:
        body = {"speed": a.speed, **({"goal": a.goal} if a.goal else {"scenario_id": a.scenario})}
        r = httpx.post(f"{a.api}/api/runs", json=body, timeout=30).json()
        run_id = r["run_id"]
        print("run:", run_id, "mode:", r.get("mode"))
        info = wait_idle(a.api, run_id, a.timeout)
        print("status:", info.get("status"), "(timed out)" if info.get("timed_out") else "")
    print(json.dumps(summary(a.api, run_id), indent=1, ensure_ascii=False))

    from playwright.sync_api import sync_playwright
    out = Path(a.out)
    if not out.is_absolute():
        out = REPO / out
    out.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(viewport={"width": 1600, "height": 1000})
        page.goto(a.api + "/", wait_until="load")
        page.wait_for_timeout(6000)  # status poll attaches to the run, SSE replays the events
        page.screenshot(path=str(out), full_page=True)
        b.close()
    print("screenshot:", out.relative_to(REPO) if out.is_relative_to(REPO) else out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
