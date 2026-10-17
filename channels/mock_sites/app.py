"""Local mock copies of four listing platforms: marketplace, roomies, craigslist, padsplit.

Each platform has a multi-step listing form (required fields, photo upload, a review
step and a final publish button), an inbox with threads, and two switches:

  layout      v1 (what the shipped selector files expect) | v2 (a "redesign" that breaks them)
  login_wall  off | on (every page shows a login form until the browser has a session cookie)

Run:  channels/.venv/bin/python -m channels.mock_sites --port 8765
Admin: GET /  (control panel), GET|POST /_admin/config, POST /_admin/reset,
       POST /_admin/{platform}/threads (inject a renter message), GET /_admin/state

Nothing here talks to the internet. All names and messages are synthetic.
"""
from __future__ import annotations

import copy
import html
import itertools
import os
import time

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from .specs import PLATFORMS, Field, Platform, dom_id, dom_name, testid

E = html.escape

SEED_THREADS = {
    "marketplace": [
        ("Jordan P.", "Hi, is this room still available?"),
        ("Alexis R.", "What utilities are included in the rent?"),
    ],
    "roomies": [
        ("Sam T.", "Hey! I'm moving to Durham for work, is the room open Nov 1?"),
        ("Priya K.", "Is there parking at the house?"),
    ],
    "craigslist": [
        ("reply-8f2k1", "Is the room still for rent? Can I see it this weekend?"),
    ],
    "padsplit": [
        ("Member 4471", "Does the room have a private bathroom?"),
        ("Member 9013", "Hola, ¿el cuarto sigue disponible?"),
    ],
}


def _default_config() -> dict:
    cfg = {p: {"layout": "v1", "login_wall": "off"} for p in PLATFORMS}
    # MOCK_LAYOUTS="marketplace=v2,roomies=v2"  MOCK_LOGIN_WALL="craigslist"
    for item in filter(None, os.environ.get("MOCK_LAYOUTS", "").split(",")):
        p, _, v = item.partition("=")
        if p in cfg and v in ("v1", "v2"):
            cfg[p]["layout"] = v
    for p in filter(None, os.environ.get("MOCK_LOGIN_WALL", "").split(",")):
        if p in cfg:
            cfg[p]["login_wall"] = "on"
    return cfg


class State:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.config = _default_config()
        self.listings: dict[str, list[dict]] = {p: [] for p in PLATFORMS}
        self.threads: dict[str, list[dict]] = {p: [] for p in PLATFORMS}
        self._ids = itertools.count(1001)
        base = 1760700000  # fixed synthetic timestamps
        for p, seeds in SEED_THREADS.items():
            for i, (who, text) in enumerate(seeds):
                tid = f"t{next(self._ids)}"
                self.threads[p].append({
                    "thread_id": tid, "renter_name": who, "unread": True,
                    "messages": [{"id": f"m{next(self._ids)}", "from": "renter", "text": text,
                                  "ts": base + 60 * i}],
                })

    def next_id(self, prefix: str) -> str:
        return f"{prefix}{next(self._ids)}"

    def thread(self, platform: str, tid: str) -> dict:
        for t in self.threads[platform]:
            if t["thread_id"] == tid:
                return t
        raise HTTPException(404, "thread not found")


STATE = State()
app = FastAPI(title="Rentus channel mocks")


# ---------------------------------------------------------------- helpers

def _platform(p: str) -> Platform:
    if p not in PLATFORMS:
        raise HTTPException(404, "unknown platform")
    return PLATFORMS[p]


def _layout(p: str) -> str:
    return STATE.config[p]["layout"]


def _walled(request: Request, p: str) -> bool:
    return STATE.config[p]["login_wall"] == "on" and request.cookies.get(f"{p}_session") != "ok"


CSS = """
*{box-sizing:border-box} body{font-family:system-ui,Segoe UI,Helvetica,Arial,sans-serif;margin:0;background:#f0f2f5;color:#1c1e21}
header{background:var(--accent);color:#fff;padding:12px 20px;font-weight:700;font-size:18px;display:flex;gap:16px;align-items:center}
header a{color:#fff;font-weight:400;font-size:14px}
main{max-width:720px;margin:24px auto;background:#fff;border-radius:8px;padding:20px 24px;box-shadow:0 1px 3px #0002}
label{display:block;margin:10px 0 4px;font-weight:600;font-size:14px}
input[type=text],input[type=number],input[type=date],input[type=email],select,textarea{width:100%;padding:8px;border:1px solid #ccd0d5;border-radius:6px;font:inherit}
textarea{min-height:110px}
.chk{display:flex;gap:8px;align-items:center;font-weight:400}
.btn,.btn-next,button{background:var(--accent);color:#fff;border:0;border-radius:6px;padding:9px 16px;font-weight:600;cursor:pointer;display:inline-block;margin-top:14px}
.step[hidden]{display:none}
.form-error{color:#c00;margin-top:8px;font-size:14px}
.thumbs{display:flex;gap:6px;margin-top:6px;font-size:12px;color:#555}
.photo-drop{border:2px dashed #ccd0d5;border-radius:8px;padding:18px;text-align:center;cursor:pointer}
dl#review dt{font-weight:600} dl#review dd{margin:0 0 6px}
.thread-row,.conv-item{display:block;padding:10px;border-bottom:1px solid #eee;color:inherit;text-decoration:none}
.unread-dot,.badge-new{color:var(--accent);font-weight:700}
.msg,.bubble{margin:8px 0;padding:8px 12px;border-radius:14px;max-width:80%}
.msg-in,.bubble.them{background:#e4e6eb} .msg-out,.bubble.me{background:var(--accent);color:#fff;margin-left:auto}
.login-box{max-width:360px;margin:40px auto}
"""


def _page(p: Platform, title: str, body: str, layout: str = "v1") -> HTMLResponse:
    nav = (f'<a href="/{p.key}/create">Create listing</a><a href="/{p.key}/inbox">Inbox</a>'
           f'<a href="/{p.key}/listings">Your listings</a>')
    return HTMLResponse(
        f"<!doctype html><html lang=en><head><meta charset=utf-8><title>{E(title)} | {E(p.brand)}</title>"
        f"<meta name=viewport content='width=device-width,initial-scale=1'>"
        f"<style>:root{{--accent:{p.accent}}}{CSS}</style></head>"
        f"<body data-layout='{layout}'><header><span>{E(p.brand)}</span>{nav}</header><main>{body}</main></body></html>"
    )


def _login_wall(p: Platform, next_url: str) -> HTMLResponse:
    body = (
        f"<div class='login-box' id='login-wall'><h2>Log in to continue</h2>"
        f"<p>You need to be logged in to use {E(p.brand)}.</p>"
        f"<form method=post action='/{p.key}/login'>"
        f"<input type=hidden name=next value='{E(next_url)}'>"
        f"<label for=email>Email</label><input type=text id=email name=email>"
        f"<label for=pass>Password</label><input type=password id=pass name=password style='width:100%;padding:8px'>"
        f"<button type=submit>Log in</button></form></div>"
    )
    resp = _page(p, "Log in", body)
    resp.status_code = 200
    return resp


# ---------------------------------------------------------------- form rendering

def _field_attrs(p: Platform, f: Field, layout: str) -> tuple[str, str]:
    """Return (attributes for the control, label html prefix/for attr)."""
    name = dom_name(p.key, f.key, layout)
    label = f.label(layout)
    req = " required data-required='1'" if f.required else ""
    if p.hook == "aria":
        return f"name='{name}' aria-label='{E(label)}'{req}", ""
    if p.hook == "id":
        return f"id='{dom_id(p.key, f.key, layout)}' name='{name}'{req}", dom_id(p.key, f.key, layout)
    if p.hook == "testid":
        return f"data-testid='{testid(f.key, layout)}' name='{name}'{req}", ""
    return f"name='{name}'{req}", ""  # craigslist: name only


def _render_field(p: Platform, f: Field, layout: str) -> str:
    attrs, for_id = _field_attrs(p, f, layout)
    label = E(f.label(layout))
    lab = f"<label{f' for={for_id}' if for_id else ''}>{label}{' *' if f.required else ''}</label>"
    if f.kind in ("text", "number", "date"):
        extra = " min='0' step='1'" if f.kind == "number" else ""
        return f"{lab}<input type='{f.kind}'{extra} {attrs}>"
    if f.kind == "textarea":
        return f"{lab}<textarea {attrs}></textarea>"
    if f.kind == "select":
        opts = "".join(f"<option>{E(o)}</option>" for o in f.options)
        return f"{lab}<select {attrs}><option value=''>Select…</option>{opts}</select>"
    if f.kind == "checkbox":
        return f"<label class='chk'{f' for={for_id}' if for_id else ''}><input type='checkbox' value='yes' {attrs}> {label}</label>"
    if f.kind == "radio":
        name = dom_name(p.key, f.key, layout)
        items = "".join(
            f"<label class='chk'><input type='radio' name='{name}' value='{E(o)}'"
            f"{' data-required=1' if f.required else ''}> {E(o)}</label>" for o in f.options)
        return f"<fieldset><legend>{label}</legend>{items}</fieldset>"
    if f.kind == "file":
        # Marketplace and PadSplit hide the real input behind a drop zone, like the real sites.
        hidden = " style='display:none'" if p.hook in ("aria", "testid") else ""
        inp = f"<input type='file' accept='image/*' multiple {attrs}{hidden}>"
        if hidden:
            return (f"{lab}<div class='photo-drop' role='button' tabindex=0 "
                    f"onclick=\"this.nextElementSibling.click()\">{label}</div>{inp}<div class='thumbs'></div>")
        return f"{lab}{inp}<div class='thumbs'></div>"
    raise ValueError(f.kind)


def _button(p: Platform, kind: str, layout: str, step_idx: int = 0) -> str:
    """kind: next | submit."""
    text = (p.next_label if kind == "next" else p.submit_label)[0 if layout == "v1" else 1]
    data = "data-next" if kind == "next" else "data-submit"
    t = E(text)
    if p.hook == "aria":
        cls = "btn" if layout == "v1" else "btn x9f2"
        return f"<div role='button' tabindex='0' class='{cls}' aria-label='{t}' {data}>{t}</div>"
    if p.hook == "id":
        if kind == "next":
            cls = "btn-next" if layout == "v1" else "wizard-advance"
            return f"<button type='button' class='{cls}' {data}>{t}</button>"
        bid = "publish-btn" if layout == "v1" else "goLiveV2"
        return f"<button type='button' id='{bid}' {data}>{t}</button>"
    if p.hook == "testid":
        if kind == "next":
            tid = "next-btn" if layout == "v1" else "wizard-continue"
        else:
            tid = "submit-review" if layout == "v1" else "wizard-submit"
        return f"<button type='button' data-testid='{tid}' {data}>{t}</button>"
    # craigslist: classic name/value buttons
    nm = "go" if layout == "v1" else "action"
    return f"<button type='button' name='{nm}' value='{t}' {data}>{t}</button>"


FORM_JS = r"""
<script>
(function(){
  const form = document.getElementById('listing-form');
  const steps = Array.from(form.querySelectorAll('.step'));
  let cur = 0;
  function show(i){ steps.forEach((s,j)=>{ s.hidden = j!==i; }); cur=i; window.scrollTo(0,0); }
  function err(step,msg){ let e=step.querySelector('.form-error'); e.textContent=msg; }
  function validate(step){
    const missing=[];
    step.querySelectorAll('[data-required]').forEach(el=>{
      if(el.type==='radio'){ if(!step.querySelector(`input[name="${el.name}"]:checked`)) missing.push(el.name); }
      else if(el.type==='file'){ if(!el.files || el.files.length===0) missing.push('photos'); }
      else if(!el.value) missing.push(el.getAttribute('aria-label')||el.name);
    });
    return Array.from(new Set(missing));
  }
  form.querySelectorAll('input[type=file]').forEach(inp=>inp.addEventListener('change',()=>{
    const t=inp.parentElement.querySelector('.thumbs'); if(t) t.textContent=inp.files.length+' photo(s) added: '+Array.from(inp.files).map(f=>f.name).join(', ');
  }));
  form.querySelectorAll('[data-next]').forEach(b=>b.addEventListener('click',()=>{
    const step=steps[cur]; const m=validate(step);
    if(m.length){ err(step,'Please fill in: '+m.join(', ')); return; }
    err(step,'');
    if(cur+1===steps.length-1){ // review step
      const dl=document.getElementById('review'); dl.innerHTML='';
      new FormData(form).forEach((v,k)=>{ const val=(v instanceof File)?v.name:v; if(!val) return;
        const dt=document.createElement('dt'); dt.textContent=k; const dd=document.createElement('dd'); dd.textContent=val; dl.append(dt,dd); });
    }
    show(cur+1);
  }));
  form.querySelectorAll('[data-submit]').forEach(b=>b.addEventListener('click',async()=>{
    b.setAttribute('aria-disabled','true');
    const r=await fetch(form.getAttribute('data-action'),{method:'POST',body:new FormData(form)});
    const j=await r.json();
    const done=document.getElementById('posted');
    done.hidden=false; done.setAttribute('data-listing-id',j.listing_id); done.querySelector('a').href=j.url;
    done.querySelector('a').textContent=j.url; form.hidden=true;
  }));
  form.addEventListener('submit',e=>e.preventDefault());
  show(0);
})();
</script>
"""


def render_form(p: Platform, layout: str) -> str:
    parts = [f"<h1>{E(p.tagline)}</h1>",
             f"<form id='listing-form' data-action='/{p.key}/api/listings' enctype='multipart/form-data'>"]
    for i, st in enumerate(p.steps):
        title = st.title[0 if layout == "v1" else 1]
        fields = "".join(_render_field(p, f, layout) for f in st.fields)
        parts.append(f"<section class='step' data-step='{i + 1}'><h2>Step {i + 1} of {len(p.steps) + 1}: "
                     f"{E(title)}</h2>{fields}<div class='form-error' role='alert'></div>"
                     f"{_button(p, 'next', layout)}</section>")
    review = "Review your listing" if layout == "v1" else "Check everything before posting"
    parts.append(f"<section class='step' data-step='{len(p.steps) + 1}'><h2>{review}</h2><dl id='review'></dl>"
                 f"<div class='form-error' role='alert'></div>{_button(p, 'submit', layout)}</section>")
    parts.append("</form>")
    parts.append("<div id='posted' hidden><h2>Your listing is live</h2><p>View it at <a href='#'></a></p></div>")
    if layout == "v2" and p.hook == "aria":
        # the redesign also wraps the page in an extra container, as SPA rewrites do
        return "<div class='x1n2onr6'><div class='x78zum5'>" + "".join(parts) + "</div></div>" + FORM_JS
    return "".join(parts) + FORM_JS


# ---------------------------------------------------------------- routes: control panel + admin

@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    rows = []
    for p in PLATFORMS.values():
        c = STATE.config[p.key]
        rows.append(
            f"<tr><td><b>{p.brand}</b></td><td><a href='/{p.key}/create'>create</a> · "
            f"<a href='/{p.key}/inbox'>inbox</a> · <a href='/{p.key}/listings'>listings</a></td>"
            f"<td>layout <b data-layout-of='{p.key}'>{c['layout']}</b> "
            f"<a href='/_admin/toggle/{p.key}/layout'>switch</a></td>"
            f"<td>login wall <b>{c['login_wall']}</b> <a href='/_admin/toggle/{p.key}/login_wall'>switch</a></td></tr>")
    body = ("<h1>Rentus channel mocks</h1><p>Local copies for the Gym and the demo. Switch a layout to "
            "simulate a site redesign; switch the login wall to simulate an expired session.</p>"
            f"<table cellpadding=6>{''.join(rows)}</table><p><a href='/_admin/reset'>reset everything</a></p>")
    fake = Platform("admin", "Rentus mocks", "", "id", ("", ""), ("", ""), [], accent="#333")
    return _page(fake, "Mocks", body)


@app.get("/_admin/config")
def get_config() -> dict:
    return STATE.config


@app.post("/_admin/config")
async def set_config(request: Request) -> dict:
    patch = await request.json()
    for p, c in patch.items():
        _platform(p)
        if "layout" in c:
            if c["layout"] not in ("v1", "v2"):
                raise HTTPException(400, "layout must be v1 or v2")
            STATE.config[p]["layout"] = c["layout"]
        if "login_wall" in c:
            STATE.config[p]["login_wall"] = "on" if c["login_wall"] in ("on", True) else "off"
    return STATE.config


@app.get("/_admin/toggle/{p}/{what}")
def toggle(p: str, what: str):
    _platform(p)
    c = STATE.config[p]
    if what == "layout":
        c["layout"] = "v2" if c["layout"] == "v1" else "v1"
    elif what == "login_wall":
        c["login_wall"] = "on" if c["login_wall"] == "off" else "off"
    return RedirectResponse("/", status_code=303)


@app.api_route("/_admin/reset", methods=["GET", "POST"])
def reset(request: Request):
    STATE.reset()
    if request.method == "GET":
        return RedirectResponse("/", status_code=303)
    return {"ok": True}


@app.get("/_admin/state")
def state() -> dict:
    return {"config": STATE.config, "listings": STATE.listings, "threads": STATE.threads}


@app.post("/_admin/{p}/threads")
async def inject_message(p: str, request: Request) -> dict:
    """Simulate a renter writing in: {"renter_name": "...", "text": "...", "thread_id"?: "..."}."""
    _platform(p)
    body = await request.json()
    msg = {"id": STATE.next_id("m"), "from": "renter", "text": body["text"], "ts": int(time.time())}
    if body.get("thread_id"):
        t = STATE.thread(p, body["thread_id"])
        t["messages"].append(msg)
        t["unread"] = True
    else:
        t = {"thread_id": STATE.next_id("t"), "renter_name": body.get("renter_name", "Renter"),
             "unread": True, "messages": [msg]}
        STATE.threads[p].append(t)
    return {"thread_id": t["thread_id"], "message_id": msg["id"]}


# ---------------------------------------------------------------- routes: login

@app.post("/{p}/login")
def login(p: str, next: str = Form("/"), email: str = Form(""), password: str = Form("")):
    _platform(p)
    resp = RedirectResponse(next if next.startswith("/") else "/", status_code=303)
    resp.set_cookie(f"{p}_session", "ok", httponly=True)
    return resp


# ---------------------------------------------------------------- routes: listing form

@app.get("/{p}/create", response_class=HTMLResponse)
def create_page(p: str, request: Request):
    plat = _platform(p)
    if _walled(request, p):
        return _login_wall(plat, f"/{p}/create")
    layout = _layout(p)
    return _page(plat, plat.tagline, render_form(plat, layout), layout)


@app.post("/{p}/api/listings")
async def post_listing(p: str, request: Request) -> JSONResponse:
    plat = _platform(p)
    if _walled(request, p):
        raise HTTPException(401, "login required")
    form = await request.form()
    fields: dict = {}
    photos: list[str] = []
    for k, v in form.multi_items():
        if hasattr(v, "filename"):
            if v.filename:
                photos.append(v.filename)
        else:
            fields[k] = v
    lid = STATE.next_id("L")
    listing = {"listing_id": lid, "fields": fields, "photos": photos, "layout": _layout(p),
               "url": f"/{p}/listings/{lid}"}
    STATE.listings[plat.key].append(listing)
    return JSONResponse({"listing_id": lid, "url": listing["url"], "status": "live"})


@app.get("/{p}/listings", response_class=HTMLResponse)
def listings(p: str, request: Request):
    plat = _platform(p)
    if _walled(request, p):
        return _login_wall(plat, f"/{p}/listings")
    items = "".join(
        f"<li><a href='{l['url']}'>{E(l['listing_id'])}</a> · {len(l['photos'])} photos · "
        f"{E(str(list(l['fields'].values())[:3]))}</li>" for l in STATE.listings[p]) or "<li>No listings yet</li>"
    return _page(plat, "Your listings", f"<h1>Your listings</h1><ul id='my-listings'>{items}</ul>", _layout(p))


@app.get("/{p}/listings/{lid}", response_class=HTMLResponse)
def listing_detail(p: str, lid: str):
    plat = _platform(p)
    for l in STATE.listings[p]:
        if l["listing_id"] == lid:
            rows = "".join(f"<dt>{E(k)}</dt><dd>{E(str(v))}</dd>" for k, v in l["fields"].items())
            return _page(plat, lid, f"<h1>Listing {E(lid)}</h1><dl>{rows}</dl><p>Photos: "
                         f"{E(', '.join(l['photos']))}</p>", _layout(p))
    raise HTTPException(404)


# ---------------------------------------------------------------- routes: inbox

@app.get("/{p}/inbox", response_class=HTMLResponse)
def inbox(p: str, request: Request):
    plat = _platform(p)
    if _walled(request, p):
        return _login_wall(plat, f"/{p}/inbox")
    v1 = _layout(p) == "v1"
    rows = []
    for t in STATE.threads[p]:
        last = t["messages"][-1]
        unanswered = last["from"] == "renter"
        if v1:
            rows.append(
                f"<a class='thread-row' data-thread-id='{t['thread_id']}' data-unanswered='{int(unanswered)}' "
                f"href='/{p}/inbox/{t['thread_id']}'><span class='who'>{E(t['renter_name'])}</span> "
                f"{'<span class=unread-dot>●</span>' if t['unread'] else ''}"
                f"<div class='snippet'>{E(last['text'][:80])}</div></a>")
        else:
            rows.append(
                f"<div class='conv-item' role='link' data-conv='{t['thread_id']}' "
                f"data-awaiting-reply='{str(unanswered).lower()}' "
                f"onclick=\"location.href='/{p}/inbox/{t['thread_id']}'\"><b class='conv-name'>{E(t['renter_name'])}</b> "
                f"{'<span class=badge-new>New</span>' if t['unread'] else ''}"
                f"<p class='conv-preview'>{E(last['text'][:80])}</p></div>")
    lst_id = "thread-list" if v1 else "conversations"
    body = f"<h1>{'Inbox' if v1 else 'Messages'}</h1><div id='{lst_id}'>{''.join(rows) or 'No messages'}</div>"
    return _page(plat, "Inbox", body, _layout(p))


@app.get("/{p}/inbox/{tid}", response_class=HTMLResponse)
def thread_page(p: str, tid: str, request: Request):
    plat = _platform(p)
    if _walled(request, p):
        return _login_wall(plat, f"/{p}/inbox/{tid}")
    t = STATE.thread(p, tid)
    t["unread"] = False
    v1 = _layout(p) == "v1"
    msgs = []
    for m in t["messages"]:
        if v1:
            cls = "msg msg-in" if m["from"] == "renter" else "msg msg-out"
            msgs.append(f"<div class='{cls}' data-from='{m['from']}' data-message-id='{m['id']}' "
                        f"data-ts='{m['ts']}'><span class='text'>{E(m['text'])}</span></div>")
        else:
            cls = "bubble them" if m["from"] == "renter" else "bubble me"
            msgs.append(f"<div class='{cls}' data-author='{'them' if m['from'] == 'renter' else 'me'}' "
                        f"data-mid='{m['id']}' data-ts='{m['ts']}'><p>{E(m['text'])}</p></div>")
    if v1:
        composer = ("<form id='reply-form'><textarea aria-label='Write a message' name='text'></textarea>"
                    "<button type='button' id='send-btn'>Send</button></form>")
    else:
        composer = ("<div class='composer'><div contenteditable='true' role='textbox' aria-label='Message' "
                    "class='cmp-input' style='border:1px solid #ccc;min-height:60px;padding:8px'></div>"
                    "<div role='button' aria-label='Reply' class='btn'>Reply</div></div>")
    js = f"""<script>
(function(){{
  const btn=document.querySelector('#send-btn, [aria-label=Reply]');
  btn.addEventListener('click',async()=>{{
    const box=document.querySelector('textarea[name=text], .cmp-input');
    const text=(box.value!==undefined?box.value:box.innerText).trim(); if(!text) return;
    await fetch('/{p}/api/threads/{tid}/messages',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{text}})}});
    location.reload();
  }});
}})();</script>"""
    head = (f"<h1 class='thread-with'>{E(t['renter_name'])}</h1>" if v1
            else f"<h2 data-conv-title>{E(t['renter_name'])}</h2>")
    lst = "messages" if v1 else "conv-log"
    return _page(plat, t["renter_name"], f"{head}<div id='{lst}' data-thread-id='{tid}'>{''.join(msgs)}</div>"
                 f"{composer}{js}", _layout(p))


@app.post("/{p}/api/threads/{tid}/messages")
async def post_message(p: str, tid: str, request: Request) -> dict:
    _platform(p)
    if _walled(request, p):
        raise HTTPException(401, "login required")
    body = await request.json()
    t = STATE.thread(p, tid)
    msg = {"id": STATE.next_id("m"), "from": "operator", "text": body["text"], "ts": int(time.time())}
    t["messages"].append(msg)
    return {"message_id": msg["id"]}


def snapshot() -> dict:
    return copy.deepcopy({"config": STATE.config, "listings": STATE.listings, "threads": STATE.threads})
