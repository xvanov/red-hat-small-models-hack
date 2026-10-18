"""Rentus Operator console: FastAPI app serving one page plus a JSON/SSE API.

Run from the repo root:  uvicorn console.app:app --port 8080
"""
from __future__ import annotations

import asyncio
import json
import os
import secrets
import subprocess
import time
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import integration as integ
from . import panels
from .demo import DEMO_PATCH, Director
from .events import Tail, utc_now
from .operator_run import FINAL_CONFIG_NAME, OperatorRun
from .sim import SimRun
from .view import build_view

HERE = Path(__file__).resolve().parent
STATIC = HERE / "static"
FAULT_KINDS = ["timeout", "page_changed", "rate_limited", "malformed", "login_required", "upstream_error", "not_found"]
# Where each fault bites by default: site automations break on publish, the reader on read_reply, etc.
DEFAULT_FAULT_TOOL = {"timeout": "request_quote", "page_changed": "publish_listing", "rate_limited": "send_message",
                      "malformed": "read_reply", "login_required": "publish_listing",
                      "upstream_error": "send_message", "not_found": "read_reply"}
FAULT_HELP = {"page_changed": "the site's layout moved under the automation",
              "malformed": "the tool answers with broken data",
              "rate_limited": "the channel says slow down",
              "login_required": "the site logged us out",
              "timeout": "nobody answers in time",
              "upstream_error": "the site returns a 502",
              "not_found": "the record is missing"}

app = FastAPI(title="Rentus Operator console")
app.mount("/static", StaticFiles(directory=STATIC), name="static")
RUNS: dict[str, object] = {}
STATE = {"active": None, "director": None}


def _public_url() -> str:
    """The tailnet address the owner's phone opens (scripts/tailnet_forward.py relays it to this process)."""
    if os.environ.get("CONSOLE_PUBLIC_URL"):
        return os.environ["CONSOLE_PUBLIC_URL"].rstrip("/")
    try:
        ip = subprocess.run(["tailscale", "ip", "-4"], capture_output=True, text=True, timeout=3).stdout.split()
        if ip:
            return f"http://{ip[0]}:8080"
    except Exception:
        pass
    return "http://127.0.0.1:8080"


PUBLIC_URL = _public_url()


def _console_note(run_id: str, type_: str, data: dict, actor: str = "system"):
    """Console-side annotations live beside the run's events, never inside them (one writer per file)."""
    d = integ.RUNS / run_id
    d.mkdir(parents=True, exist_ok=True)
    with (d / "console.jsonl").open("a") as f:
        f.write(json.dumps({"ts": utc_now(), "run_id": run_id, "type": type_, "actor": actor, "data": data},
                           ensure_ascii=False) + "\n")


def _mode(badge: dict | None = None) -> str:
    """operator: real operator on vLLM. operator-stub: real operator + tools, scripted model.
    stub: the console's own driver (no operator package, or forced for rehearsal)."""
    if os.environ.get("CONSOLE_FORCE_STUB") == "1":
        return "stub"
    op, _ = integ.try_import("rentus_operator")
    tools, _ = integ.try_import("rentus_tools")
    if not (op and tools):
        return "stub"
    badge = badge or integ.probe_backend()
    if badge.get("backend_up"):
        return "operator"
    return "operator-stub" if os.environ.get("CONSOLE_STUB") == "operator" else "stub"


MODE_LABEL = {"operator": integ.LIVE_LABEL, "operator-stub": "stub model (rentus_operator scripted, real tools)",
              "stub": "stub (console driver)"}


def _get_run(run_id: str):
    run = RUNS.get(run_id)
    if not run and not (integ.RUNS / run_id).is_dir():
        raise HTTPException(404, f"no run {run_id}")
    return run


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/approve")
def approve_page():
    return FileResponse(STATIC / "approve.html", headers={"Cache-Control": "no-cache"})


@app.get("/api/status")
def status():
    badge = dict(integ.probe_backend())
    pkgs = {n: integ.try_import(n)[0] is not None for n in ("rentus_operator", "rentus_tools", "rentus_env")}
    active = STATE["active"]
    run = RUNS.get(active) if active else None
    mode = getattr(run, "mode", None) if run and getattr(run, "status", "") not in ("stopped",) else _mode(badge)
    badge["label"] = MODE_LABEL.get(mode, mode)
    badge["live"] = mode == "operator"
    reader = dict(integ.probe_reader())
    if os.environ.get("READER_LABEL"):
        reader["label"] = os.environ["READER_LABEL"]
    return {"badge": badge, "mode": mode, "packages": pkgs, "active_run": active,
            "run_status": getattr(run, "status", None), "run_mode": getattr(run, "mode", None),
            "speed": getattr(run, "speed", None), "fault_kinds": FAULT_KINDS, "default_fault_tool": DEFAULT_FAULT_TOOL,
            "fault_help": FAULT_HELP, "reader": reader, "reader_label": reader["label"].removeprefix("reader: "),
            "operator_config": getattr(run, "config_name", None) or FINAL_CONFIG_NAME, "public_url": PUBLIC_URL,
            "approve_url": PUBLIC_URL + "/approve",
            "demo": STATE["director"].state() if STATE["director"] else None}


@app.get("/api/scenarios")
def scenarios():
    return [{k: v for k, v in s.items() if k != "task"} for s in integ.list_scenarios()]


@app.get("/api/scoreboard")
def get_scoreboard():
    return panels.scoreboard()


@app.get("/api/realworld")
def get_realworld():
    return panels.realworld()


@app.get("/api/trust")
def get_trust():
    return panels.trust()


@app.get("/api/runs")
def list_runs():
    out = []
    if integ.RUNS.is_dir():
        for d in sorted(integ.RUNS.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)[:30]:
            if d.is_dir():
                run = RUNS.get(d.name)
                out.append({"run_id": d.name, "status": getattr(run, "status", "finished"),
                            "mode": getattr(run, "mode", None), "mtime": d.stat().st_mtime})
    return out


@app.post("/api/runs")
def start_run(body: dict = Body(default={})):
    goal = (body.get("goal") or "").strip()
    sid = body.get("scenario_id")
    speed = float(body.get("speed") or 1.0)
    scenario = integ.get_scenario(sid) if sid else None
    if sid and not scenario:
        raise HTTPException(404, f"no scenario {sid}")
    if not goal and scenario:
        goal = scenario.get("owner_instruction") or ""
    run_id = "r_" + time.strftime("%H%M%S") + "_" + secrets.token_hex(2)
    run_dir = integ.RUNS / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    _stop_active()
    badge = integ.probe_backend(force=True)
    mode = _mode(badge)
    run = None
    if mode in ("operator", "operator-stub"):
        try:
            run = OperatorRun(run_id, run_dir, goal, scenario, speed, live=mode == "operator", badge=badge)
        except Exception as e:
            _console_note(run_id, "fallback", {"from": "rentus_operator", "to": "console stub driver",
                                               "reason": f"{type(e).__name__}: {e}"})
            run = None
    if run is None:
        run = SimRun(run_id, run_dir, goal, scenario, speed)
    else:
        run.note = lambda t, data, actor="system": _console_note(run_id, t, data, actor)
    RUNS[run_id] = run
    STATE["active"] = run_id
    if sid:
        _console_note(run_id, "scenario", {"scenario_id": sid, "counterparts": len(scenario.get("counterparts") or []),
                                           "faults": scenario.get("faults") or []})
    run.start()
    return {"run_id": run_id, "mode": run.mode}


def _stop_active():
    if STATE["director"]:
        STATE["director"].stop()
        STATE["director"] = None
    if STATE["active"] and STATE["active"] in RUNS:
        RUNS[STATE["active"]].stop()


@app.post("/api/demo")
def start_demo(body: dict = Body(default={})):
    """One-click demo: a fresh free-play run on the demo world, driven by console/demo.py."""
    speed = float(body.get("speed") or 1.0)
    auto = body.get("auto_approve_s")
    _stop_active()
    badge = integ.probe_backend(force=True)
    mode = _mode(badge)
    if mode not in ("operator", "operator-stub"):
        raise HTTPException(409, "the demo run needs the operator package (rentus_operator); the stub driver can't play it")
    run_id = "d_" + time.strftime("%H%M%S") + "_" + secrets.token_hex(2)
    run_dir = integ.RUNS / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    run = OperatorRun(run_id, run_dir, "", None, speed, live=mode == "operator", badge=badge,
                      world_patch=DEMO_PATCH, seed_renters=False)
    run.note = lambda t, data, actor="system": _console_note(run_id, t, data, actor)
    RUNS[run_id] = run
    STATE["active"] = run_id
    run.start()
    d = Director(run, lambda t, data, actor="system": _console_note(run_id, t, data, actor), speed=speed,
                 auto_approve_s=float(auto) if auto else None, approve_url=PUBLIC_URL + "/approve")
    STATE["director"] = d
    d.start()
    return {"run_id": run_id, "mode": run.mode, "demo": d.state()}


@app.post("/api/demo/speed")
def demo_speed(body: dict = Body(...)):
    d = STATE["director"]
    if not d:
        raise HTTPException(409, "no demo running")
    d.set_speed(float(body.get("speed") or 1.0))
    return d.state()


@app.post("/api/reset")
def reset():
    """Stop whatever is running and clear the page (the run's files stay under runs/)."""
    _stop_active()
    STATE["active"] = None
    return {"ok": True}


@app.get("/api/approvals")
def approvals():
    """What the owner's phone shows: open escalations (with drafts) first, then recent decisions."""
    rid = STATE["active"]
    run = RUNS.get(rid) if rid else None
    if run is None:
        return {"run_id": None, "items": [], "status": None}
    w = run.snapshot()
    threads = {t.get("thread_id"): t for t in w.get("threads") or []}
    jobs = {j.get("job_id"): j for j in w.get("jobs") or []}
    items = []
    for e in w.get("escalations") or []:
        ref = e.get("thread_id") or e.get("ref_id") or e.get("job_id")
        t = threads.get(ref) or {}
        last = next((m.get("text") for m in reversed(t.get("messages") or []) if m.get("from") == "renter"), None)
        j = jobs.get(ref) or {}
        reason, draft = e.get("reason") or "", e.get("draft")
        if reason.strip() in (ref or "", e.get("ref_id") or "") and draft:  # model put the id in reason
            reason, draft = draft, None
        items.append({"esc_id": e.get("esc_id"), "reason": reason, "draft": draft,
                      "status": e.get("status") or "open", "ref": ref, "decided_via": e.get("decided_via"),
                      "owner_text": e.get("owner_text"), "who": t.get("renter_name"), "channel": t.get("channel"),
                      "language": t.get("language"), "last_renter_message": last,
                      "job": {"property": j.get("property"), "issue": j.get("issue")} if j else None,
                      "created_at": e.get("created_at")})
    items = [i for _, i in sorted(enumerate(items), key=lambda p: (p[1]["status"] != "open", -p[0]))]
    return {"run_id": rid, "status": getattr(run, "status", None), "items": items}


@app.get("/api/runs/{run_id}")
def run_info(run_id: str):
    run = _get_run(run_id)
    return {"run_id": run_id, "status": getattr(run, "status", "finished"), "mode": getattr(run, "mode", None),
            "speed": getattr(run, "speed", None), "error": getattr(run, "error", None)}


@app.get("/api/runs/{run_id}/view")
def run_view(run_id: str):
    run = _get_run(run_id)
    if run is not None:
        world = run.snapshot()
    else:
        f = integ.RUNS / run_id / "world.json"
        world = json.loads(f.read_text()) if f.exists() else {}
    v = build_view(world)
    v["status"] = getattr(run, "status", "finished")
    v["mode"] = getattr(run, "mode", None)
    return v


@app.get("/api/runs/{run_id}/events")
async def run_events(run_id: str, request: Request):
    _get_run(run_id)
    d = integ.RUNS / run_id
    tails = {"run": Tail(d / "events.jsonl"), "console": Tail(d / "console.jsonl")}
    counts = {"run": 0, "console": 0}

    async def gen():
        yield "retry: 1000\n\n"
        last_beat = time.monotonic()
        while True:
            if await request.is_disconnected():
                return
            sent = False
            for src, t in tails.items():
                for ev in t.read_new():
                    counts[src] += 1
                    ev["_k"] = f"{src}:{counts[src]}"
                    ev["_src"] = src
                    yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
                    sent = True
            if not sent and time.monotonic() - last_beat > 10:
                last_beat = time.monotonic()
                yield ": keepalive\n\n"
            await asyncio.sleep(0.15)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _live_run(run_id: str):
    run = _get_run(run_id)
    if run is None:
        raise HTTPException(409, "run is not live in this console process")
    return run


@app.post("/api/runs/{run_id}/owner")
def owner_message(run_id: str, body: dict = Body(...)):
    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "text required")
    _live_run(run_id).owner_say(text)
    return {"ok": True}


@app.post("/api/runs/{run_id}/escalations/{esc_id}")
def decide(run_id: str, esc_id: str, body: dict = Body(...)):
    decision = body.get("decision")
    if decision not in ("approve", "deny"):
        raise HTTPException(400, "decision must be approve or deny")
    run = _live_run(run_id)
    w = run.snapshot()
    esc = next((e for e in w.get("escalations") or [] if e.get("esc_id") == esc_id), None)
    if esc is None:
        raise HTTPException(404, f"no escalation {esc_id}")
    if (esc.get("status") or "open") != "open":
        raise HTTPException(409, f"{esc_id} was already {esc.get('status')}")
    source = (body.get("source") or "console")[:20]
    text = (body.get("text") or "").strip() or None
    run.decide(esc_id, decision == "approve", body.get("note", ""), text=text, source=source)
    _console_note(run_id, "owner_decision", {"esc_id": esc_id, "decision": decision, "via": source,
                                             "edited": bool(text and text != (esc.get("draft") or "").strip())},
                  actor="owner")
    return {"ok": True}


@app.post("/api/runs/{run_id}/faults")
def inject_fault(run_id: str, body: dict = Body(...)):
    kind = body.get("kind")
    if kind not in FAULT_KINDS:
        raise HTTPException(400, f"kind must be one of {FAULT_KINDS}")
    fault = {"tool": body.get("tool") or DEFAULT_FAULT_TOOL[kind], "kind": kind, "times": int(body.get("times") or 1)}
    if isinstance(body.get("match"), dict):
        fault["match"] = body["match"]
    _live_run(run_id).inject_fault(fault)
    _console_note(run_id, "fault_injected", fault, actor="owner")
    return {"ok": True, "fault": fault}


@app.post("/api/runs/{run_id}/speed")
def set_speed(run_id: str, body: dict = Body(...)):
    speed = float(body.get("speed") or 1.0)
    _live_run(run_id).set_speed(speed)
    if STATE["director"] and STATE["director"].run.run_id == run_id:
        STATE["director"].set_speed(speed)
    return {"ok": True, "speed": speed}


@app.post("/api/runs/{run_id}/stop")
def stop_run(run_id: str):
    _live_run(run_id).stop()
    return {"ok": True}


@app.get("/api/file")
def get_file(path: str = Query(...)):
    """Screenshots from live adapters. Only files under runs/, channels/ or results/."""
    p = (integ.REPO / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
    allowed = [integ.REPO / x for x in ("runs", "channels", "results")]
    if not any(str(p).startswith(str(a.resolve()) + os.sep) for a in allowed) or not p.is_file():
        raise HTTPException(404, "not found")
    if p.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
        raise HTTPException(415, "images only")
    return FileResponse(p)


@app.exception_handler(Exception)
async def on_error(request: Request, exc: Exception):
    return JSONResponse({"error": f"{type(exc).__name__}: {exc}"}, status_code=500)
