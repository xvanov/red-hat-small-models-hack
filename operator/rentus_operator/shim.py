"""Tiny local stand-in for the rentus_tools package (contracts/tools.md).

Used only when rentus_tools is not importable, and by the offline tests so they
stay deterministic. Same calling convention: call(world, name, args) -> envelope.
It is deliberately small: enough behaviour for the loop and verifier to be
exercised (style rules, gate rule, spend limit, faults, malformed data).
"""
from __future__ import annotations

import copy
import json
import re
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
INVENTORY = REPO / "data" / "published" / "inventory.json"

CHANNELS = ["marketplace", "roomies", "craigslist", "padsplit", "sms", "email"]
LISTING_CHANNELS = ["marketplace", "roomies", "craigslist", "padsplit"]


def _fn(name, desc, props, required=()):
    return {"type": "function", "function": {
        "name": name, "description": desc,
        "parameters": {"type": "object", "properties": props, "required": list(required),
                       "additionalProperties": False}}}


S = {"type": "string"}
D = {"type": "string", "description": "Date as YYYY-MM-DD."}
OBJ = {"type": "object"}

TOOLS = [
    _fn("list_rooms", "List rooms in the inventory. Filter by availability date or area.",
        {"available_by": D, "area": S}),
    _fn("get_room", "Get one room record. Its facts are the only facts you may quote.", {"room_id": S}, ["room_id"]),
    _fn("update_room", "Update fields of a room record, for example rent or available_from.",
        {"room_id": S, "fields": OBJ}, ["room_id", "fields"]),
    _fn("create_listing", "Create a draft listing for a room.",
        {"room_id": S, "title": S, "body": S, "price": {"type": "number"}}, ["room_id", "title", "body", "price"]),
    _fn("publish_listing", "Publish a draft listing on one channel.",
        {"listing_id": S, "channel": {"type": "string", "enum": LISTING_CHANNELS}}, ["listing_id", "channel"]),
    _fn("update_listing", "Update fields of a listing.", {"listing_id": S, "fields": OBJ}, ["listing_id", "fields"]),
    _fn("mark_filled", "Mark a listing filled and remove it from every channel.", {"listing_id": S}, ["listing_id"]),
    _fn("get_listing_media", "Get the photos stored for a room.", {"room_id": S}, ["room_id"]),
    _fn("check_listing_compliance", "Check listing text against fair-housing phrase rules.", {"text": S}, ["text"]),
    _fn("get_market_rent", "Market rent index for a zip code.", {"zip": S, "bedrooms": {"type": "integer"}}, ["zip"]),
    _fn("list_threads", "List renter conversation threads.",
        {"channel": {"type": "string", "enum": CHANNELS}, "unanswered_only": {"type": "boolean"}}),
    _fn("read_thread", "Read every message in a thread.", {"thread_id": S}, ["thread_id"]),
    _fn("send_message", "Send a message to a renter. Max 2 sentences, at most one question, no long dashes.",
        {"thread_id": S, "text": S, "attachments": {"type": "array", "items": S}}, ["thread_id", "text"]),
    _fn("read_reply", "Read a renter reply into exact JSON: which qualifying items it answers and how.",
        {"thread_id": S, "text": S, "pending_item": {"type": "string",
         "enum": ["lease", "move_in", "phone", "reason", "occupants"]}}),
    _fn("upsert_renter", "Create or update the renter's register row for a thread.",
        {"thread_id": S, "fields": OBJ}, ["thread_id", "fields"]),
    _fn("match_renters", "Rank registered renters for a room.", {"room_id": S}, ["room_id"]),
    _fn("find_showing_slots", "Find open showing slots for a room.",
        {"room_id": S, "date_from": D, "date_to": D}, ["room_id", "date_from", "date_to"]),
    _fn("propose_showing", "Put a PROPOSED showing on the calendar. Refused unless the renter's gate is complete.",
        {"renter_id": S, "room_id": S, "start": S}, ["renter_id", "room_id", "start"]),
    _fn("web_search", "Search the web.", {"query": S}, ["query"]),
    _fn("fetch_page", "Fetch a web page as text.", {"url": S}, ["url"]),
    _fn("find_vendors", "Find vendors by trade and zip.", {"trade": S, "zip": S}, ["trade", "zip"]),
    _fn("request_quote", "Ask a vendor for a quote on a job.",
        {"vendor_id": S, "job_id": S, "description": S}, ["vendor_id", "job_id", "description"]),
    _fn("book_vendor", "Book the vendor behind a quote. Refused above the spending limit.", {"quote_id": S}, ["quote_id"]),
    _fn("create_job", "Open a maintenance job.",
        {"property": S, "issue": S, "severity": {"type": "string", "enum": ["low", "medium", "high", "emergency"]}},
        ["property", "issue", "severity"]),
    _fn("escalate_to_owner", "Hand a decision to the owner, with an optional draft reply.",
        {"reason": S, "ref_id": S, "draft": S}, ["reason", "ref_id"]),
    _fn("report_to_owner", "Send the owner a summary of what was done.", {"summary": S}, ["summary"]),
]
TOOL_NAMES = {t["function"]["name"] for t in TOOLS}


# --------------------------------------------------------------------------- world

def load(patch: dict | None = None):
    return new_world(patch)


def new_world(patch: dict | None = None, inventory: Path | None = INVENTORY) -> dict:
    base = json.loads(Path(inventory).read_text()) if inventory and Path(inventory).exists() else {"rooms": []}
    w = {"rooms": base.get("rooms", []), "listings": [], "channels": {c: {"posts": [], "threads": []} for c in CHANNELS},
         "threads": [], "register": [], "calendar": [], "vendors": [], "quotes": [], "jobs": [], "escalations": [],
         "owner_reports": [], "policy": {"spend_limit_usd": 300, "showing_hours": "8 AM to 8 PM",
                                   "lease_min_months_public": 12, "lease_floor_months": 6},
         "clock": {"now": "2026-10-17T09:00:00"}, "faults": [], "_seq": {}, "_fault_state": {}}
    for k, v in (patch or {}).items():
        w[k] = v
    return w


def _id(w, prefix):
    n = w["_seq"].get(prefix, 0) + 1
    w["_seq"][prefix] = n
    return f"{prefix}{n:03d}"


def _find(rows, key, val):
    return next((r for r in rows if r.get(key) == val), None)


def _err(code, msg, retryable=False, hint=None):
    e = {"code": code, "message": msg, "retryable": retryable}
    if hint:
        e["hint"] = hint
    return {"ok": False, "error": e}


def _ok(data):
    return {"ok": True, "data": data}


# --------------------------------------------------------------------------- events

class EventSink:
    """Contract §6 events, in memory and optionally appended to a JSONL file."""

    def __init__(self, run_id: str = "r_local", path: str | Path | None = None, on_event=None):
        self.run_id, self.seq, self.events = run_id, 0, []
        self.path = Path(path) if path else None
        self.on_event = on_event
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, type: str, actor: str, data: dict) -> dict:
        self.seq += 1
        ev = {"ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "run_id": self.run_id,
              "seq": self.seq, "type": type, "actor": actor, "data": data}
        self.events.append(ev)
        if self.path:
            with self.path.open("a") as f:
                f.write(json.dumps(ev, default=str) + "\n")
        if self.on_event:
            self.on_event(ev)
        return ev


# --------------------------------------------------------------------------- faults

FAULT_ERRORS = {
    "timeout": ("TIMEOUT", "the call timed out", True),
    "rate_limited": ("RATE_LIMITED", "too many requests", True),
    "login_required": ("LOGIN_REQUIRED", "the session expired, login required", False),
    "page_changed": ("PAGE_CHANGED", "the page layout changed, the automation could not find the form", False),
    "upstream_error": ("UPSTREAM_ERROR", "upstream returned 502", True),
    "not_found": ("NOT_FOUND", "not found", False),
}


def _corrupt(data):
    if not isinstance(data, dict):
        return {"garbage": True}
    out = {}
    for i, (k, v) in enumerate(data.items()):
        if isinstance(v, list):
            out[k] = "not-a-list"
        elif isinstance(v, dict):
            out[k] = None
        elif i % 2:
            out[k] = v
    return out


def _fault_for(w, name):
    st = w.setdefault("_fault_state", {})
    for i, f in enumerate(w.get("faults", [])):
        if f.get("tool") != name:
            continue
        s = st.setdefault(str(i), {"calls": 0, "fired": 0})
        s["calls"] += 1
        if s["calls"] <= f.get("after", 0) or s["fired"] >= f.get("times", 1):
            continue
        s["fired"] += 1
        return f["kind"]
    return None


# --------------------------------------------------------------------------- tools

LONG_DASH = re.compile("[–—]")
COMPLIANCE = [
    (r"\bno kids\b|\bno children\b", "familial status", "remove the restriction on children"),
    (r"\bchristian\b|\bchurch\b", "religion", "remove religious preference"),
    (r"\bperfect for (a )?(single )?(man|woman|male|female)\b|\bmales? only\b|\bfemales? only\b", "sex",
     "describe the room, not the renter"),
    (r"\bno disabled\b|\bmust be able to climb\b|\bable[- ]bodied\b", "disability", "describe the stairs instead"),
    (r"\bno section 8\b", "source of income (local rule)", "remove it"),
]


def _sentences(text):
    return [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s]


def _gate_complete(r):
    g = r.get("gate") or {}
    for k in ("lease", "move_in", "phone", "reason", "occupants"):
        v = g.get(k)
        if isinstance(v, dict):
            if v.get("status") not in ("answered", "exception"):
                return False
        elif v in (None, "", False):
            return False
    return True


def _impl(w, name, a):
    rooms = w["rooms"]
    if name == "list_rooms":
        out = rooms
        if a.get("area"):
            out = [r for r in out if a["area"].lower() in (r.get("area", "") + " " + r.get("address", "")).lower()]
        if a.get("available_by"):
            out = [r for r in out if r.get("available_from", "") <= a["available_by"]]
        return _ok({"rooms": [{k: r.get(k) for k in ("room_id", "area", "address", "type", "private_bath", "rent",
                                                      "available_from")} for r in out]})
    if name in ("get_room", "update_room", "get_listing_media"):
        r = _find(rooms, "room_id", a["room_id"])
        if not r:
            return _err("NOT_FOUND", f"no room {a['room_id']}", hint="call list_rooms")
        if name == "update_room":
            r.update(a["fields"])
        if name == "get_listing_media":
            return _ok({"photos": [{"name": p, "url": f"sandbox://media/{p}"} for p in r.get("photos", [])]})
        return _ok({"room": r})
    if name == "create_listing":
        if not _find(rooms, "room_id", a["room_id"]):
            return _err("NOT_FOUND", f"no room {a['room_id']}")
        lst = {"listing_id": _id(w, "L"), "room_id": a["room_id"], "status": "draft", "title": a["title"],
               "body": a["body"], "price": a["price"], "channels": {}}
        w["listings"].append(lst)
        return _ok({"listing": lst})
    if name in ("publish_listing", "update_listing", "mark_filled"):
        lst = _find(w["listings"], "listing_id", a["listing_id"])
        if not lst:
            return _err("NOT_FOUND", f"no listing {a['listing_id']}")
        if name == "update_listing":
            lst.update(a["fields"])
            return _ok({"listing": lst})
        if name == "mark_filled":
            lst["status"] = "filled"
            for c in lst["channels"].values():
                c["status"] = "removed"
            return _ok({"listing": lst})
        ch = a["channel"]
        post = {"post_id": _id(w, "P"), "url": f"sandbox://{ch}/{lst['listing_id']}", "status": "live"}
        lst["channels"][ch] = post
        lst["status"] = "live"
        w["channels"][ch]["posts"].append({**post, "listing_id": lst["listing_id"]})
        return _ok(post)
    if name == "check_listing_compliance":
        f = [{"phrase": m.group(0), "rule": rule, "suggestion": sug} for pat, rule, sug in COMPLIANCE
             for m in [re.search(pat, a["text"], re.I)] if m]
        return _ok({"ok": not f, "findings": f})
    if name == "get_market_rent":
        return _ok({"zori": 1650.0, "source": "Zillow ZORI (shim)", "as_of": "2026-08"})
    if name == "list_threads":
        ts = w["threads"]
        if a.get("channel"):
            ts = [t for t in ts if t["channel"] == a["channel"]]
        if a.get("unanswered_only"):
            ts = [t for t in ts if t["messages"] and t["messages"][-1]["from"] == "renter"]
        return _ok({"threads": [{"thread_id": t["thread_id"], "channel": t["channel"], "renter_name": t.get("renter_name"),
                                 "last": t["messages"][-1]["text"] if t["messages"] else None} for t in ts]})
    if name in ("read_thread", "send_message"):
        t = _find(w["threads"], "thread_id", a["thread_id"])
        if not t:
            return _err("NOT_FOUND", f"no thread {a['thread_id']}", hint="call list_threads")
        if name == "read_thread":
            return _ok({"thread": t})
        text = a["text"]
        if LONG_DASH.search(text):
            return _err("POLICY_BLOCKED", "long dash in message", hint="use a comma or a period")
        if len(_sentences(text)) > 2:
            return _err("POLICY_BLOCKED", "more than 2 sentences", hint="split into several short messages")
        if text.count("?") > 1:
            return _err("POLICY_BLOCKED", "more than one question", hint="ask one question at a time")
        known = {str(r.get(k)) for r in rooms for k in ("rent", "deposit")}
        for amt in re.findall(r"\$\s?(\d[\d,]*)", text):
            if amt.replace(",", "") not in known:
                return _err("POLICY_BLOCKED", f"price ${amt} is not in any room record", hint="quote the record")
        m = {"id": _id(w, "M"), "from": "operator", "text": text, "attachments": a.get("attachments", []),
             "ts": w["clock"]["now"]}
        t["messages"].append(m)
        return _ok({"message_id": m["id"]})
    if name == "read_reply":
        text = a.get("text")
        if not text and a.get("thread_id"):
            t = _find(w["threads"], "thread_id", a["thread_id"])
            msgs = [m for m in (t or {}).get("messages", []) if m["from"] == "renter"]
            text = msgs[-1]["text"] if msgs else ""
        text = text or ""
        absent = lambda: {"status": "absent", "value": None}
        out = {"lease": absent(), "move_in": {"status": "absent", "date": None, "raw": None}, "phone": absent(),
               "occupants": absent(), "reason": absent(), "intents": [],
               "language": "es" if re.search(r"[¿¡ñ]|\b(hola|cuarto|gracias)\b", text, re.I) else "en"}
        digits = re.sub(r"\D", "", text)
        if len(digits) >= 10:
            out["phone"] = {"status": "answered", "value": "+1" + digits[-10:]}
        d = re.search(r"\b(20\d\d-\d\d-\d\d)\b", text)
        if d:
            out["move_in"] = {"status": "answered", "date": d.group(1), "raw": d.group(1)}
        elif re.search(r"next month|soon|asap|fines de mes", text, re.I):
            out["move_in"] = {"status": "vague", "date": None, "raw": text}
        if re.search(r"\b(yes|sí|si)\b", text, re.I) and a.get("pending_item") == "lease":
            out["lease"] = {"status": "answered", "value": True}
        if re.search(r"\b(see|visit|tour|showing)\b", text, re.I):
            out["intents"].append("scheduling")
        return _ok(out)
    if name == "upsert_renter":
        r = next((r for r in w["register"] if a["thread_id"] in r.get("thread_ids", [])), None)
        if not r:
            r = {"renter_id": _id(w, "renter:"), "thread_ids": [a["thread_id"]], "gate": {}, "wants": {},
                 "status": "new"}
            w["register"].append(r)
        f = dict(a["fields"])
        if isinstance(f.get("gate"), dict):
            r["gate"].update(f.pop("gate"))
        r.update(f)
        return _ok({"renter": r})
    if name == "match_renters":
        return _ok({"matches": [{"renter_id": r["renter_id"], "score": 1.0 if _gate_complete(r) else 0.5,
                                 "reasons": []} for r in w["register"]]})
    if name == "find_showing_slots":
        return _ok({"slots": [f"{a['date_from']}T{h}:00:00-04:00" for h in (10, 14, 17)]})
    if name == "propose_showing":
        r = _find(w["register"], "renter_id", a["renter_id"])
        if not r:
            return _err("NOT_FOUND", f"no renter {a['renter_id']}")
        if not _gate_complete(r):
            missing = [k for k in ("lease", "move_in", "phone", "reason", "occupants")
                       if not _gate_complete({"gate": {**{x: True for x in ("lease", "move_in", "phone", "reason",
                                                                            "occupants")}, k: r["gate"].get(k)}})]
            return _err("POLICY_BLOCKED", "qualifying gate incomplete: " + ", ".join(missing),
                        hint="ask the next missing item")
        ev = {"event_id": _id(w, "E"), "title": f"PROPOSED: Showing with {r.get('name', r['renter_id'])}",
              "start": a["start"], "status": "proposed", "renter_id": a["renter_id"], "room_id": a["room_id"]}
        w["calendar"].append(ev)
        return _ok({"event": ev})
    if name == "web_search":
        return _ok({"results": [{"title": v["name"], "url": f"sandbox://vendor/{v['vendor_id']}",
                                 "snippet": v.get("trade", "")} for v in w["vendors"]]})
    if name == "fetch_page":
        return _ok({"text": f"(shim page for {a['url']})"})
    if name == "find_vendors":
        return _ok({"vendors": [v for v in w["vendors"] if v.get("trade") == a["trade"]]})
    if name == "create_job":
        j = {"job_id": _id(w, "J"), "property": a["property"], "issue": a["issue"], "severity": a["severity"],
             "status": "open", "vendor_id": None, "cost": None}
        w["jobs"].append(j)
        return _ok({"job": j})
    if name == "request_quote":
        v = _find(w["vendors"], "vendor_id", a["vendor_id"])
        if not v:
            return _err("NOT_FOUND", f"no vendor {a['vendor_id']}")
        if not v.get("responds", True):
            return _err("TIMEOUT", f"{v['name']} did not respond", retryable=False, hint="ask another vendor")
        lo, hi = v.get("quote_range", [100, 200])
        q = {"quote_id": _id(w, "Q"), "vendor_id": v["vendor_id"], "job_id": a["job_id"], "amount": (lo + hi) / 2,
             "eta": "tomorrow", "status": "quoted"}
        w["quotes"].append(q)
        return _ok({"quote": q})
    if name == "book_vendor":
        q = _find(w["quotes"], "quote_id", a["quote_id"])
        if not q:
            return _err("NOT_FOUND", f"no quote {a['quote_id']}")
        if q["amount"] > w["policy"]["spend_limit_usd"]:
            return _err("BUDGET_EXCEEDED", f"${q['amount']} is above the ${w['policy']['spend_limit_usd']} limit",
                        hint="escalate to the owner")
        j = _find(w["jobs"], "job_id", q["job_id"]) or {"job_id": q["job_id"]}
        j.update(status="booked", vendor_id=q["vendor_id"], cost=q["amount"])
        q["status"] = "booked"
        return _ok({"job": j})
    if name == "escalate_to_owner":
        e = {"esc_id": _id(w, "X"), "reason": a["reason"], "ref_id": a["ref_id"], "draft": a.get("draft"),
             "created_at": w["clock"]["now"]}
        w["escalations"].append(e)
        return _ok({"escalation": e})
    if name == "report_to_owner":
        w["owner_reports"].append({"summary": a["summary"], "ts": w["clock"]["now"]})
        return _ok({"ok": True})
    return _err("NOT_FOUND", f"unknown tool {name}")


def call(world: dict, name: str, args: dict | None = None, *, sink=None, actor: str = "operator",
         call_id: str | None = None) -> dict:
    """Same signature and event behaviour as rentus_tools.call."""
    if sink:
        sink.emit("tool_call", actor, {"tool": name, "call_id": call_id, "args": args})
    res = _call(world, name, args or {})
    if sink:
        sink.emit("tool_result", "system", {"tool": name, "call_id": call_id, "result": res})
        if res["ok"] and name == "escalate_to_owner":
            sink.emit("escalation", actor, res["data"])
        if res["ok"] and name == "report_to_owner":
            sink.emit("owner_message", actor, {"summary": (args or {}).get("summary")})
    return res


def _call(world: dict, name: str, args: dict) -> dict:
    if name not in TOOL_NAMES:
        return _err("NOT_FOUND", f"unknown tool {name}", hint="use one of the listed tools")
    tool = next(t for t in TOOLS if t["function"]["name"] == name)["function"]["parameters"]
    missing = [k for k in tool["required"] if k not in (args or {})]
    if missing:
        return _err("INVALID_ARGS", "missing " + ", ".join(missing))
    kind = _fault_for(world, name)
    if kind and kind != "malformed":
        code, msg, retry = FAULT_ERRORS[kind]
        return _err(code, msg, retryable=retry)
    try:
        env = _impl(world, name, args)
    except (KeyError, TypeError, ValueError) as e:
        return _err("INVALID_ARGS", f"{type(e).__name__}: {e}")
    if kind == "malformed" and env.get("ok"):
        return {"ok": True, "data": _corrupt(copy.deepcopy(env["data"]))}
    return env


def snapshot(world: dict) -> dict:
    return copy.deepcopy({k: v for k, v in world.items() if not k.startswith("_")})
