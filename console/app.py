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
from . import live as livemod
from . import live_world
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


@app.get("/api/results")
def get_results():
    return panels.results_v2()


@app.get("/api/performance")
def get_performance():
    return panels.performance()


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


def _chat_meta(run_id: str) -> dict:
    try:
        return json.loads((integ.RUNS / run_id / "chat.json").read_text())
    except (OSError, ValueError):
        return {}


@app.get("/api/chats")
def list_chats():
    """The owner's Assistant conversations (origin "assistant"), newest first. Test and verify runs are not listed."""
    out = []
    if integ.RUNS.is_dir():
        for d in integ.RUNS.iterdir():
            m = _chat_meta(d.name) if d.is_dir() else {}
            if m.get("origin") != "assistant":
                continue
            run = RUNS.get(d.name)
            out.append({**m, "open": run is not None and getattr(run, "status", "") not in ("stopped", "error")})
    return sorted(out, key=lambda c: c.get("started") or "", reverse=True)[:100]


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
    origin = str(body.get("origin") or "api")[:20]  # "assistant" = the owner's chat; "verify"/"test"/"api" stay out of the history
    (run_dir / "chat.json").write_text(json.dumps({"run_id": run_id, "origin": origin, "title": goal[:120],
                                                   "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                                                   "live_channels": bool(body.get("live_channels"))}))
    _stop_active()
    badge = integ.probe_backend(force=True)
    mode = _mode(badge)
    run = None
    if mode in ("operator", "operator-stub"):
        try:
            kw = {"seed_renters": False} if body.get("seed_renters") is False and not scenario else {}
            if body.get("live_channels") and not scenario:
                kw["live_channels"] = True
            run = OperatorRun(run_id, run_dir, goal, scenario, speed, live=mode == "operator", badge=badge, **kw)
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
        if reason.strip() in (ref or "", e.get("ref_id") or "", e.get("ref_type") or "", "thread", "job") and draft:  # model put the id in reason
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


def _run_events(run_id: str) -> list[dict]:
    p = integ.RUNS / run_id / "events.jsonl"
    out = []
    if p.exists():
        for line in p.read_text().splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    return out


def _fb_state(run_id: str) -> dict:
    run = RUNS.get(run_id)
    if run is not None and not hasattr(run, "fb"):
        run.fb = {}
    return getattr(run, "fb", {}) if run is not None else {}


@app.get("/api/runs/{run_id}/posts")
def run_posts(run_id: str):
    """Honest per-channel posting status of the run's listings (console/live_world.py)."""
    run = _get_run(run_id)
    if run is not None:
        world = run.snapshot()
    else:  # a past chat: the world as it was saved
        f = integ.RUNS / run_id / "world.json"
        world = json.loads(f.read_text()) if f.exists() else {}
    lc = getattr(run, "live_channels", None) if run is not None else (_chat_meta(run_id).get("live_channels") or None)
    listings = live_world.posts((world or {}).get("listings") or [], _run_events(run_id), _fb_state(run_id))
    if lc:  # the owner's photos of the real room, shown as a strip on the listing card
        photos = [str(p.relative_to(integ.REPO)) if p.is_relative_to(integ.REPO) else str(p) for p in live_world.room_photos()]
        for l in listings:
            l["photos"] = photos
    return {"live": bool(lc), "live_setup": lc, "mode": (world or {}).get("mode"), "listings": listings}


@app.post("/api/runs/{run_id}/listings/{listing_id}/facebook")
def run_facebook(run_id: str, listing_id: str, body: dict = Body(...)):
    """Facebook Page: `prepare` creates an unpublished post; `publish` publishes it. Only from the owner's click."""
    action = body.get("action")
    if action not in ("prepare", "publish"):
        raise HTTPException(400, "action must be prepare or publish")
    run = _live_run(run_id)
    listing = next((l for l in run.snapshot().get("listings") or [] if l.get("listing_id") == listing_id), None)
    if not listing:
        raise HTTPException(404, f"no listing {listing_id}")
    fb = _fb_state(run_id)
    cur = fb.get(listing_id) or {}
    try:
        if action == "prepare":
            if cur.get("state") in ("draft", "published"):
                return {"ok": True, **cur}
            r = live_world.fb_prepare(listing)
            fb[listing_id] = {"state": "draft", "post_id": r.get("post_id"), "is_published": r.get("is_published")}
        else:
            if cur.get("state") == "published":
                return {"ok": True, **cur}
            r = live_world.fb_publish(listing, cur.get("post_id"))
            fb[listing_id] = {"state": "published" if r.get("is_published", True) else "failed",
                              "post_id": r.get("post_id"), "permalink": r.get("permalink_url")}
    except Exception as e:
        fb[listing_id] = {**cur, "state": cur.get("state") if action == "publish" and cur.get("state") else "failed",
                          "error": f"{type(e).__name__}: {e}"[:300]}
        _console_note(run_id, "facebook_page", {"action": action, "listing_id": listing_id, "ok": False}, actor="owner")
        raise HTTPException(502, fb[listing_id]["error"])
    _console_note(run_id, "facebook_page", {"action": action, "listing_id": listing_id, "ok": True,
                                            "state": fb[listing_id]["state"]}, actor="owner")
    return {"ok": True, **fb[listing_id]}


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


# ------------------------------------------------------------------ live channels (channels/live/api.py)
def _live(fn: str, *args, default=None, **kw):
    try:
        return livemod.call(fn, *args, **kw), None
    except livemod.Unavailable as e:
        return default, str(e)
    except Exception as e:  # the live module raised: show it as a degraded state, never a 500
        return default, f"{type(e).__name__}: {e}"


@app.get("/api/live/status")
def live_status():
    st, err = _live("status")
    if not isinstance(st, dict):
        return {"available": False, "error": err, "channels": [], "send_enabled": False, "allowlist_size": 0}
    chans = st.get("channels")
    if chans is None:  # per-channel dicts keyed by name, or a list
        chans = [dict(v, channel=v.get("channel") or k) for k, v in st.items() if isinstance(v, dict)]
    elif isinstance(chans, dict):
        chans = [dict(v, channel=v.get("channel") or k) for k, v in chans.items() if isinstance(v, dict)]
    return {"available": True, "error": None, "channels": chans, "send_enabled": bool(st.get("send_enabled")),
            "allowlist_size": st.get("allowlist_size") or 0, "can_archive": livemod.has("archive_thread")}


@app.get("/api/live/threads")
def live_threads():
    ts, err = _live("list_threads", default=[])
    items = [livemod.norm_thread(t) for t in (ts or []) if isinstance(t, dict)]
    items.sort(key=lambda t: str(t.get("last_ts") or ""), reverse=True)
    return {"available": err is None, "error": err, "items": items}


@app.get("/api/live/threads/{thread_id}")
def live_thread(thread_id: str):
    t, err = _live("get_thread", thread_id)
    if err:
        raise HTTPException(503, err)
    if not t:
        raise HTTPException(404, f"no thread {thread_id}")
    t = livemod.norm_thread(t)
    t["messages"] = [m for m in (t.get("messages") or []) if isinstance(m, dict)]
    t["trace"] = [x for x in (t.get("trace") or []) if isinstance(x, dict)]
    return t


@app.post("/api/live/threads/{thread_id}/reply")
def live_reply(thread_id: str, body: dict = Body(...)):
    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "text required")
    r, err = _live("send_owner_message", thread_id, text, _timeout=livemod.SEND_TIMEOUT_S)
    if err:
        raise HTTPException(503, err)
    return _delivery(r)


@app.post("/api/live/threads/{thread_id}/archive")
def live_archive(thread_id: str):
    if not livemod.has("archive_thread"):
        raise HTTPException(501, "archiving is not available in the live channels yet")
    r, err = _live("archive_thread", thread_id)
    if err:
        raise HTTPException(503, err)
    return {"ok": bool((r or {}).get("ok", True)) if isinstance(r, dict) else True}


@app.post("/api/live/conversations")
def live_start(body: dict = Body(...)):
    ch, to, text = (body.get("channel") or "").strip(), (body.get("to") or "").strip(), (body.get("text") or "").strip()
    if not (ch and to and text):
        raise HTTPException(400, "channel, to and text are required")
    r, err = _live("start_conversation", ch, to, text, _timeout=livemod.SEND_TIMEOUT_S)
    if err:
        raise HTTPException(503, err)
    return {"ok": True, "result": r}


def _run_approvals() -> list[dict]:
    """Open escalations of the Assistant's active run, in the same shape as live approvals."""
    try:
        a = approvals()
    except Exception:
        return []
    out = []
    for i in a.get("items") or []:
        if i.get("status") != "open":
            continue
        out.append({"id": f"run:{a['run_id']}:{i['esc_id']}", "source": "assistant", "thread_id": i.get("ref"),
                    "who": i.get("who") or (i.get("job") or {}).get("property") or "Assistant",
                    "channel": i.get("channel"), "reason": i.get("reason"), "draft_text": i.get("draft"),
                    "last_message": i.get("last_renter_message"), "created": i.get("created_at")})
    return out


@app.get("/api/live/approvals")
def live_approvals():
    ap, err = _live("list_approvals", default=[])
    names = {}
    if ap:
        ts, _ = _live("list_threads", default=[])
        names = {t.get("thread_id"): t for t in ts or [] if isinstance(t, dict)}
    items = []
    for a in ap or []:
        if not isinstance(a, dict):
            continue
        t = names.get(a.get("thread_id")) or {}
        last = a.get("last_message") or t.get("last_text")
        if last and (last.strip() == (a.get("draft_text") or "").strip()):
            last = None  # the thread's last line is the draft itself
        items.append({**a, "source": "live", "who": a.get("who") or t.get("renter_name") or t.get("contact_display"),
                      "channel": a.get("channel") or t.get("channel"), "last_message": last})
    items += _run_approvals()
    return {"available": err is None, "error": err, "items": items}


@app.post("/api/live/approvals/{approval_id:path}")
def live_decide(approval_id: str, body: dict = Body(...)):
    decision = body.get("decision")
    if decision not in ("approve", "edit", "deny", "dismiss"):
        raise HTTPException(400, "decision must be approve, edit, deny or dismiss")
    text = (body.get("text") or "").strip() or None
    if decision == "edit" and not text:
        raise HTTPException(400, "edit needs text")
    if approval_id.startswith("run:"):
        _, run_id, esc_id = approval_id.split(":", 2)
        decide(run_id, esc_id, {"decision": "deny" if decision in ("deny", "dismiss") else "approve", "text": text,
                                "source": (body.get("source") or "console")})
        return {"ok": True, "status": "recorded", "sent": False, "error": None}
    if decision == "dismiss":  # a note or a draft-less escalation: close it, never send anything
        if livemod.has("dismiss_approval"):
            r, err = _live("dismiss_approval", approval_id)
        else:
            r, err = _live("decide", approval_id, "deny")
        if err:
            raise HTTPException(503, err)
        return {"ok": bool((r or {}).get("ok", True)) if isinstance(r, dict) else True, "status": "dismissed", "sent": False, "error": None}
    r, err = _live("decide", approval_id, decision, text=text, _timeout=livemod.SEND_TIMEOUT_S)
    if err:  # never fall back to sending the original draft
        raise HTTPException(503, err)
    return _delivery(r)


def _delivery(r) -> dict:
    """What the live module did with a send: ok + status ("sent", "awaiting_approval", ...) + reason if not sent."""
    r = r if isinstance(r, dict) else {"ok": bool(r)}
    return {"ok": bool(r.get("ok", True)), "status": r.get("status"), "sent": bool(r.get("sent") or r.get("status") == "sent"),
            "error": r.get("error") or r.get("reason"), "result": r}


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
