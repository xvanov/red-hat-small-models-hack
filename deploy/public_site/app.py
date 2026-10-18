"""Public demo page for Rentus Operator.

A tiny, separate FastAPI app that serves one static page and a read-only,
cached, rate-limited proxy of exactly three console GETs (+ a status check).
Nothing else from the private console (127.0.0.1:8080) is reachable here:
no inbox, no runs, no approvals, no POSTs.

Run: .venv/bin/python -m uvicorn deploy.public_site.app:app --host 127.0.0.1 --port 8091
"""
from __future__ import annotations

import html
import os
import re
import threading
import time
from collections import defaultdict, deque
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

HERE = Path(__file__).resolve().parent
CONSOLE = os.environ.get("PUBLIC_CONSOLE_URL", "http://127.0.0.1:8080").rstrip("/")
CACHE_S = 60.0
STATUS_CACHE_S = 15.0
RATE_N, RATE_WINDOW_S = 30, 60.0  # proxy requests per client per minute
PROXIED = ("results", "trust", "performance")
MESSENGER_URL = "https://m.me/947720821760300"
TWILIO_ENV_FILE = Path(os.environ.get(
    "PUBLIC_TWILIO_ENV_FILE", str(Path.home() / "rental-management/.env.production")))


def _read_twilio_number() -> str | None:
    """Read ONLY TWILIO_PHONE_NUMBER (a public business number). No other value is kept."""
    if os.environ.get("PUBLIC_SMS_NUMBER"):
        raw = os.environ["PUBLIC_SMS_NUMBER"]
    else:
        raw = None
        try:
            for line in TWILIO_ENV_FILE.read_text().splitlines():
                m = re.match(r"\s*(?:export\s+)?TWILIO_PHONE_NUMBER\s*=\s*(.*)$", line)
                if m:
                    raw = m.group(1).strip().strip('"').strip("'")
                    break
        except OSError:
            return None
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if not re.fullmatch(r"1?\d{10}", digits):  # must look like a NANP phone number, nothing else
        return None
    return "+1" + digits[-10:]


def _pretty(e164: str) -> str:
    d = e164[-10:]
    return f"({d[:3]}) {d[3:6]}-{d[6:]}"


def _demo_email() -> str | None:
    v = os.environ.get("PUBLIC_DEMO_EMAIL", "").strip()
    return v if re.fullmatch(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", v) else None


def render_page() -> str:
    tpl = (HERE / "static" / "index.html").read_text()
    sms = _read_twilio_number()
    email = _demo_email()
    subs = {
        "{{MESSENGER_URL}}": MESSENGER_URL,
        "{{SMS_HREF}}": f"sms:{sms}?&body=DEMO%20hi%2C%20is%20the%20room%20on%20Appling%20Way%20still%20available%3F" if sms else "#",
        "{{SMS_PRETTY}}": _pretty(sms) if sms else "coming soon",
        "{{SMS_HIDDEN}}": "" if sms else "hidden",
        "{{DEMO_EMAIL}}": email or "coming soon",
        "{{EMAIL_HREF}}": f"mailto:{email}?subject=DEMO&body=DEMO%20hi%2C%20is%20the%20room%20on%20Appling%20Way%20still%20available%3F" if email else "#",
        "{{EMAIL_HIDDEN}}": "" if email else "hidden",
    }
    for k, v in subs.items():
        tpl = tpl.replace(k, html.escape(v, quote=True))
    return tpl


CSP = ("default-src 'none'; script-src 'self'; style-src 'self' https://fonts.googleapis.com; "
       "font-src https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; "
       "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def headers(request: Request, call_next):
    if request.method not in ("GET", "HEAD"):
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    resp = await call_next(request)
    resp.headers["Content-Security-Policy"] = CSP
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return resp


# --- rate limit + cache -------------------------------------------------------
_hits: dict[str, deque] = defaultdict(deque)
_lock = threading.Lock()
_cache: dict[str, tuple[float, int, bytes]] = {}


def _client(request: Request) -> str:
    # Behind cloudflared every request comes from 127.0.0.1; use Cloudflare's header then.
    return request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "?")


def _limited(request: Request) -> bool:
    now = time.monotonic()
    with _lock:
        q = _hits[_client(request)]
        while q and now - q[0] > RATE_WINDOW_S:
            q.popleft()
        if len(q) >= RATE_N:
            return True
        q.append(now)
        if len(_hits) > 10000:
            _hits.clear()
    return False


def _fetch(path: str, ttl: float) -> tuple[int, bytes]:
    now = time.monotonic()
    hit = _cache.get(path)
    if hit and now - hit[0] < ttl:
        return hit[1], hit[2]
    try:
        r = httpx.get(f"{CONSOLE}{path}", timeout=10.0)
        out = (r.status_code if r.status_code == 200 else 503,
               r.content if r.status_code == 200 else b'{"available":false}')
    except httpx.HTTPError:
        out = (503, b'{"available":false}')
    _cache[path] = (now, *out)
    return out


def _proxy(request: Request, path: str, ttl: float = CACHE_S) -> Response:
    if _limited(request):
        return JSONResponse({"detail": "Too many requests"}, status_code=429)
    code, body = _fetch(path, ttl)
    return Response(body, status_code=code, media_type="application/json",
                    headers={"Cache-Control": f"public, max-age={int(ttl)}"})


# Exactly three read-only console endpoints, spelled out (no path parameter).
@app.get("/api/results")
def results(request: Request):
    return _proxy(request, "/api/results")


@app.get("/api/trust")
def trust(request: Request):
    return _proxy(request, "/api/trust")


@app.get("/api/performance")
def performance(request: Request):
    return _proxy(request, "/api/performance")


@app.get("/api/online")
def online(request: Request):
    """Only a boolean leaves: is the operator model reachable."""
    if _limited(request):
        return JSONResponse({"detail": "Too many requests"}, status_code=429)
    code, body = _fetch("/api/status", STATUS_CACHE_S)
    up = False
    if code == 200:
        try:
            import json
            badge = json.loads(body).get("badge") or {}
            up = bool(badge.get("live") and badge.get("backend_up"))
        except ValueError:
            up = False
    return JSONResponse({"online": up}, headers={"Cache-Control": "no-store"})


@app.get("/", response_class=HTMLResponse)
def index():
    return HTMLResponse(render_page(), headers={"Cache-Control": "no-cache"})


_STATIC = {"app.js": "text/javascript", "app.css": "text/css", "favicon.svg": "image/svg+xml"}


@app.get("/static/{name}")
def static(name: str):
    if name not in _STATIC:
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    return Response((HERE / "static" / name).read_bytes(), media_type=_STATIC[name],
                    headers={"Cache-Control": "public, max-age=300"})


@app.get("/healthz")
def healthz():
    return {"ok": True}
