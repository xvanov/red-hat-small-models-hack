"""Console stub driver: a scripted stand-in for operator + tools + renters.

Used only when the real `rentus_operator` package can't be imported, so the console
can always be demonstrated and tested. It is labeled "stub" everywhere in the UI.
It writes contract-shaped events (section 6) and keeps a contract-shaped world dict
(section 3), and it honours injected faults (section 5) with visible recovery:
retry with backoff, verifier catches of malformed data, fallbacks and escalations.
No model runs here; every decision is a fixed rule.
"""
from __future__ import annotations

import copy
import heapq
import itertools
import json
import queue
import re
import threading
import time
from pathlib import Path

from .events import EventLog
from .renters import DEFAULT_COUNTERPARTS, Counterpart

REPO = Path(__file__).resolve().parent.parent
INVENTORY = REPO / "data" / "published" / "inventory.json"
CHANNELS = ["marketplace", "roomies", "craigslist", "padsplit", "sms", "email"]
POST_CHANNELS = ["marketplace", "roomies", "craigslist", "padsplit"]
GATE = ["lease", "move_in", "occupants", "phone", "reason"]
MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], 1)}
MONTHS.update({m: i for i, m in enumerate(
    ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
     "septiembre", "octubre", "noviembre", "diciembre"], 1)})
MONTHS.update({"jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
               "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12})
FAULT_ERRORS = {
    "timeout": ("TIMEOUT", "tool call timed out", True),
    "rate_limited": ("RATE_LIMITED", "channel rate limit hit", True),
    "login_required": ("LOGIN_REQUIRED", "channel session expired", False),
    "page_changed": ("PAGE_CHANGED", "page layout changed, selector not found", True),
    "upstream_error": ("UPSTREAM_ERROR", "upstream returned 502", True),
    "not_found": ("NOT_FOUND", "resource not found", False),
}
# Required keys per tool for the verifier's schema check on ok results.
REQUIRED = {
    "read_reply": ["lease", "move_in", "phone", "occupants", "reason", "intents", "language"],
    "send_message": ["message_id"],
    "publish_listing": ["post_id", "status"],
    "create_listing": ["listing_id"],
    "request_quote": ["quote_id", "amount"],
}

QUESTIONS = {
    "en": {"lease": "Are you okay with a 12-month lease?",
           "move_in": "What exact day would you like to move in?",
           "move_in_vague": "Which exact date would that be?",
           "occupants": "How many people would live in the room?",
           "phone": "What's the best phone number to reach you?",
           "reason": "What brings you to the area?"},
    "es": {"lease": "¿Te parece bien un contrato de 12 meses?",
           "move_in": "¿Qué día exacto te quieres mudar?",
           "move_in_vague": "¿Qué fecha exacta sería?",
           "occupants": "¿Cuántas personas vivirían en el cuarto?",
           "phone": "¿Cuál es el mejor número de teléfono para contactarte?",
           "reason": "¿Qué te trae a la zona?"},
}


def deep_merge(base: dict, patch: dict) -> dict:
    for k, v in (patch or {}).items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            deep_merge(base[k], v)
        else:
            base[k] = copy.deepcopy(v)
    return base


def build_world(scenario: dict | None) -> dict:
    rooms = []
    if INVENTORY.exists():
        rooms = json.loads(INVENTORY.read_text()).get("rooms", [])
    world = {
        "rooms": rooms, "listings": [], "threads": [], "register": [], "calendar": [],
        "channels": {c: {"posts": [], "threads": []} for c in CHANNELS},
        "vendors": [
            {"vendor_id": "V1", "name": "Bull City Plumbing (sandbox)", "trade": "plumber", "phone": "+19195550101",
             "rating": 4.7, "service_area": ["27701", "27703", "27704", "27705"], "responds": True, "quote_range": [180, 260]},
            {"vendor_id": "V2", "name": "Triangle Drain Pros (sandbox)", "trade": "plumber", "phone": "+19195550102",
             "rating": 4.4, "service_area": ["27701", "27703", "27704", "27705"], "responds": False, "quote_range": [150, 220]},
            {"vendor_id": "V3", "name": "Eno River Repair (sandbox)", "trade": "plumber", "phone": "+19195550103",
             "rating": 4.9, "service_area": ["27701", "27703", "27704", "27705"], "responds": True, "quote_range": [290, 380]},
        ],
        "quotes": [], "jobs": [], "escalations": [], "faults": [],
        "policy": {"spend_limit_usd": 300, "showing_hours": [10, 18],
                   "lease_min_months_public": 12, "lease_floor_months": 6},
        "clock": "2026-10-17T10:00:00",
    }
    if scenario:
        deep_merge(world, scenario.get("initial_state") or {})
        world["faults"].extend(copy.deepcopy(scenario.get("faults") or []))
    return world


def parse_date(text: str, today: str) -> str | None:
    t = text.lower()
    year = int(today[:4])
    m = re.search(r"(\d{1,2})(?:st|nd|rd|th)?\s+(?:de\s+|of\s+)?([a-záéíóú]+)", t)
    if m and m.group(2) in MONTHS:
        day, mon = int(m.group(1)), MONTHS[m.group(2)]
    else:
        m = re.search(r"([a-z]+)\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b", t)
        if not (m and m.group(1) in MONTHS):
            if re.search(r"primero de ([a-z]+)", t):
                mon = MONTHS.get(re.search(r"primero de ([a-z]+)", t).group(1))
                if mon:
                    return f"{year + (mon < int(today[5:7])):04d}-{mon:02d}-01"
            return None
        mon, day = MONTHS[m.group(1)], int(m.group(2))
    if not 1 <= day <= 31:
        return None
    if (mon, day) < (int(today[5:7]), int(today[8:10])):
        year += 1
    return f"{year:04d}-{mon:02d}-{day:02d}"


def fallback_reader(text: str, pending: str | None, today: str) -> dict:
    """Deterministic reader used by the stub (the real one is the <=1.5B model)."""
    t = text.lower()
    absent = {"status": "absent", "value": None}
    out = {"lease": dict(absent), "move_in": {"status": "absent", "date": None, "raw": None},
           "phone": dict(absent), "occupants": dict(absent), "reason": dict(absent),
           "intents": [], "language": "es" if re.search(r"[ñáéíóú¿¡]|\bhola\b|\bsí\b|\bcuarto\b", t) else "en"}
    if re.search(r"\$\s?\d+|lower|discount|deal|flexib|negotiab|take \$|menos|descuento", t):
        out["intents"].append("price_negotiation")
    if re.search(r"(\d+) months|month[- ]to[- ]month|can't do a full year|no puedo un año", t):
        out["intents"].append("shorter_lease")
    if re.search(r"not interested|stop|ya no", t):
        out["intents"].append("hard_no")
    if pending == "lease" or "lease" in t:
        if re.search(r"\bno\b|can't|cannot|shorter", t):
            out["lease"] = {"status": "no", "value": False}
        elif re.search(r"probably|depends|maybe|quizás|depende", t):
            out["lease"] = {"status": "vague", "value": None}
        elif re.search(r"\byes\b|yeah|\bsí\b|\bsi\b|works|fine|bien|ok|sure", t):
            out["lease"] = {"status": "answered", "value": True}
    date = parse_date(t, today)
    if date:
        out["move_in"] = {"status": "answered", "date": date, "raw": text}
    elif pending == "move_in" or re.search(r"fines de mes|end of (the )?month|next month|soon|asap|pronto", t):
        if re.search(r"fines de mes|end of|next month|soon|asap|pronto|mes", t):
            out["move_in"] = {"status": "vague", "date": None, "raw": text}
    digits = re.sub(r"\D", "", t)
    if len(digits) == 10 or (len(digits) == 11 and digits.startswith("1")):
        out["phone"] = {"status": "answered", "value": "+1" + digits[-10:]}
    if re.search(r"just me|only me|solo yo|sólo yo|\bme\b alone", t):
        out["occupants"] = {"status": "answered", "value": 1}
    elif re.search(r"two of us|2 people|me and my (partner|wife|husband|girlfriend|boyfriend)|dos personas", t):
        out["occupants"] = {"status": "answered", "value": 2}
    if pending == "reason" and len(t.split()) >= 3:
        vague = re.search(r"need a change|personal", t)
        out["reason"] = {"status": "vague" if vague else "answered", "value": None if vague else text.strip()}
    return out


class SimRun:
    mode = "stub"

    def __init__(self, run_id: str, run_dir: Path, goal: str | None, scenario: dict | None,
                 speed: float = 1.0):
        self.run_id = run_id
        self.run_dir = Path(run_dir)
        self.log = EventLog(self.run_dir / "events.jsonl", run_id)
        self.scenario = scenario
        self.world = build_world(scenario)
        self.lock = threading.RLock()
        self.speed = max(0.1, float(speed))
        self.status = "starting"
        self.inbox: queue.Queue = queue.Queue()
        self.timers: list = []
        self._tick = itertools.count()
        self._ids = itertools.count(1)
        self._stop = threading.Event()
        self.counterparts: dict[str, Counterpart] = {}
        self.pending_actions: dict[str, dict] = {}
        self.listing_room: dict | None = None
        self.goal = goal or (scenario or {}).get("owner_instruction") or ""
        self.thread = threading.Thread(target=self._main, name=f"sim-{run_id}", daemon=True)

    # ---------- public API (called from web handlers) ----------
    def start(self):
        self.thread.start()

    def stop(self):
        self._stop.set()

    def owner_say(self, text: str):
        self.inbox.put(("owner", text))

    def decide(self, esc_id: str, approve: bool, note: str = "", text: str | None = None, source: str = "console"):
        self.inbox.put(("decision", esc_id, approve, note))

    def inject_fault(self, fault: dict):
        with self.lock:
            self.world["faults"].append(fault)

    def set_speed(self, speed: float):
        self.speed = max(0.1, float(speed))

    def snapshot(self) -> dict:
        with self.lock:
            return json.loads(json.dumps(self.world))

    def save(self):
        (self.run_dir / "world.json").write_text(json.dumps(self.snapshot(), indent=1))

    # ---------- loop ----------
    def _nid(self, prefix: str) -> str:
        return f"{prefix}{next(self._ids):03d}"

    def pause(self, seconds: float = 0.5):
        self._stop.wait(seconds / self.speed)

    def later(self, seconds: float, *item):
        heapq.heappush(self.timers, (time.monotonic() + seconds / self.speed, next(self._tick), item))

    def _main(self):
        self.status = "running"
        try:
            self.log.emit("owner_message", "owner", {"text": self.goal}) if self.goal else None
            if self.goal:
                self.handle_goal(self.goal)
            elif not self.scenario:
                self.log.emit("model_message", "operator", {"to": "owner", "model": "stub",
                              "text": "Ready. Tell me about a room or a repair."})
            if self.scenario or self.listing_room:
                self.spawn_counterparts()
            while not self._stop.is_set():
                now = time.monotonic()
                while self.timers and self.timers[0][0] <= now:
                    _, _, item = heapq.heappop(self.timers)
                    self.dispatch(item)
                try:
                    item = self.inbox.get(timeout=0.1)
                    self.dispatch(item)
                except queue.Empty:
                    pass
                self.status = "running" if self.timers else "idle"
        except Exception as e:  # never let the stub die silently
            self.log.emit("fallback", "system", {"reason": f"stub driver crashed: {e!r}"})
            self.status = "error"
        finally:
            self.save()
            if self.status != "error":
                self.status = "stopped"

    def dispatch(self, item: tuple):
        kind = item[0]
        if kind == "owner":
            self.log.emit("owner_message", "owner", {"text": item[1]})
            self.handle_goal(item[1])
        elif kind == "decision":
            self.handle_decision(*item[1:])
        elif kind == "renter_says":
            self.renter_says(item[1], item[2])
        elif kind == "operator_turn":
            self.operator_turn(item[1])
        self.save()

    # ---------- tool layer with fault injection and recovery ----------
    def _take_fault(self, tool: str) -> dict | None:
        with self.lock:
            for f in self.world["faults"]:
                if f.get("tool") in (tool, "*") and f.get("times", 1) > 0:
                    if f.get("after", 0) > 0:
                        f["after"] -= 1
                        continue
                    f["times"] = f.get("times", 1) - 1
                    return f
        return None

    def raw_call(self, tool: str, args: dict, actor: str = "operator") -> dict:
        call_id = self._nid("c")
        model = {"operator": "stub", "reader": "deterministic fallback (code)"}.get(actor, actor)
        self.log.emit("tool_call", actor, {"tool": tool, "args": args, "call_id": call_id, "model": model})
        self.pause(0.35)
        fault = self._take_fault(tool)
        if fault and fault["kind"] != "malformed":
            code, msg, retryable = FAULT_ERRORS.get(fault["kind"], ("UPSTREAM_ERROR", fault["kind"], True))
            res = {"ok": False, "error": {"code": code, "message": msg + " (injected)", "retryable": retryable}}
        else:
            try:
                with self.lock:
                    res = getattr(self, "t_" + tool)(**args)
            except Exception as e:
                res = {"ok": False, "error": {"code": "INVALID_ARGS", "message": repr(e), "retryable": False}}
            if fault and res.get("ok"):
                bad = dict(res["data"]) if isinstance(res.get("data"), dict) else {}
                for k in list(bad)[: max(1, len(bad) // 2)]:
                    bad.pop(k)
                bad["_corrupt"] = "\x00??"
                res = {"ok": True, "data": bad}
        self.log.emit("tool_result", actor, {"tool": tool, "call_id": call_id, **res})
        if tool == "escalate_to_owner" and res.get("ok") and "escalation" in res.get("data", {}):
            e = res["data"]["escalation"]
            self.log.emit("escalation", "operator", {"esc_id": e["esc_id"], "reason": e["reason"], "draft": e.get("draft")})
        return res

    def call(self, tool: str, args: dict, actor: str = "operator", max_attempts: int = 3) -> dict:
        """Call with the verifier in the loop: schema check, retry with backoff, fallbacks."""
        for attempt in range(1, max_attempts + 1):
            res = self.raw_call(tool, args, actor)
            if res.get("ok"):
                missing = [k for k in REQUIRED.get(tool, []) if k not in (res.get("data") or {})]
                if missing:
                    self.log.emit("verifier", "verifier", {"check": "schema", "tool": tool, "ok": False,
                                  "detail": f"missing {', '.join(missing)}; result rejected"})
                    if attempt < max_attempts:
                        self.log.emit("retry", "verifier", {"tool": tool, "attempt": attempt + 1,
                                      "reason": "malformed result", "backoff_s": 0})
                        continue
                    break
                if tool in REQUIRED:
                    self.log.emit("verifier", "verifier", {"check": "schema", "tool": tool, "ok": True})
                return res
            err = res["error"]
            if err["code"] == "PAGE_CHANGED" and attempt < max_attempts:
                self.log.emit("fallback", "operator", {"tool": tool, "from": "cached selector",
                              "to": "re-located selector", "reason": "page changed; operator re-read the page"})
                continue
            if err.get("retryable") and attempt < max_attempts:
                backoff = 2 ** (attempt - 1)
                self.log.emit("retry", "verifier", {"tool": tool, "attempt": attempt + 1,
                              "reason": err["code"], "backoff_s": backoff})
                self.pause(backoff * 0.4)
                continue
            return res
        return res

    # ---------- tools (sandbox semantics, simplified) ----------
    def _room(self, room_id):
        return next((r for r in self.world["rooms"] if r["room_id"] == room_id), None)

    def t_update_room(self, room_id, fields):
        r = self._room(room_id)
        if not r:
            r = {"room_id": room_id}
            self.world["rooms"].append(r)
        r.update(fields)
        return {"ok": True, "data": {"room": r}}

    def t_get_market_rent(self, zip, bedrooms=None):
        return {"ok": True, "data": {"zori": 1480, "source": "Zillow ZORI (sandbox fixture)", "as_of": "2026-09"}}

    def t_check_listing_compliance(self, text):
        bad = [p for p in ["no kids", "no children", "christian", "singles only", "perfect for a man",
                           "perfect for a woman", "no section 8", "english only"] if p in text.lower()]
        return {"ok": True, "data": {"ok": not bad, "findings": [
            {"phrase": p, "rule": "24 CFR 100.75", "suggestion": "describe the property, not the renter"} for p in bad]}}

    def t_create_listing(self, room_id, title, body, price):
        lst = {"listing_id": self._nid("L"), "room_id": room_id, "status": "draft", "title": title,
               "body": body, "price": price, "channels": {}}
        self.world["listings"].append(lst)
        return {"ok": True, "data": {"listing": lst, "listing_id": lst["listing_id"]}}

    def t_publish_listing(self, listing_id, channel):
        lst = next(x for x in self.world["listings"] if x["listing_id"] == listing_id)
        post = {"post_id": self._nid("P"), "url": f"sandbox://{channel}/{listing_id}", "status": "live"}
        lst["channels"][channel] = post
        lst["status"] = "live"
        self.world["channels"][channel]["posts"].append({**post, "listing_id": listing_id})
        return {"ok": True, "data": post}

    def t_read_reply(self, thread_id, pending_item=None):
        th = self._thread(thread_id)
        last = next((m for m in reversed(th["messages"]) if m["from"] == "renter"), {"text": ""})
        return {"ok": True, "data": fallback_reader(last["text"], pending_item, self.world["clock"][:10])}

    def t_upsert_renter(self, thread_id, fields):
        th = self._thread(thread_id)
        r = next((x for x in self.world["register"] if thread_id in x["thread_ids"]), None)
        if not r:
            r = {"renter_id": th["renter_id"], "thread_ids": [thread_id], "name": th["renter_name"],
                 "phone": None, "gate": {g: {"status": "absent"} for g in GATE}, "wants": {},
                 "status": "qualifying", "listing_of_interest": self.world["listings"][0]["listing_id"]
                 if self.world["listings"] else None, "channel": th["channel"]}
            self.world["register"].append(r)
        for k, v in fields.items():
            if k == "gate":
                r["gate"].update(v)
            else:
                r[k] = v
        return {"ok": True, "data": {"renter": r}}

    def t_send_message(self, thread_id, text, attachments=None):
        sentences = len(re.findall(r"[.!?](\s|$)", text.strip()))
        if sentences > 2 or text.count("?") > 1 or "—" in text:
            return {"ok": False, "error": {"code": "POLICY_BLOCKED", "retryable": False,
                    "message": "style: max 2 sentences, 1 question, no long dashes"}}
        th = self._thread(thread_id)
        mid = self._nid("m")
        th["messages"].append({"id": mid, "from": "operator", "text": text, "attachments": attachments or [],
                               "ts": self.world["clock"]})
        return {"ok": True, "data": {"message_id": mid}}

    def t_find_showing_slots(self, room_id, date_from, date_to):
        return {"ok": True, "data": {"slots": ["2026-10-24T11:00", "2026-10-24T15:00", "2026-10-25T13:00"]}}

    def t_propose_showing(self, renter_id, room_id, start):
        r = next(x for x in self.world["register"] if x["renter_id"] == renter_id)
        if not all(r["gate"][g]["status"] in ("answered", "exception") for g in GATE):
            return {"ok": False, "error": {"code": "POLICY_BLOCKED", "retryable": False,
                                           "message": "qualifying gate incomplete"}}
        ev = {"event_id": self._nid("E"), "title": f"Showing: {r['name']}", "start": start,
              "end": start, "status": "proposed", "renter_id": renter_id}
        self.world["calendar"].append(ev)
        r["status"] = "showing_proposed"
        return {"ok": True, "data": {"event": ev}}

    def t_escalate_to_owner(self, reason, ref_id, draft=None):
        esc = {"esc_id": self._nid("X"), "reason": reason, "ref_id": ref_id, "draft": draft,
               "created_at": self.world["clock"], "status": "open"}
        self.world["escalations"].append(esc)
        return {"ok": True, "data": {"escalation": esc}}

    def t_report_to_owner(self, summary):
        return {"ok": True, "data": {"ok": True}}

    def t_create_job(self, property, issue, severity):
        job = {"job_id": self._nid("J"), "property": property, "issue": issue, "severity": severity,
               "status": "open", "vendor_id": None, "cost": None}
        self.world["jobs"].append(job)
        return {"ok": True, "data": {"job": job}}

    def t_web_search(self, query):
        return {"ok": True, "data": {"results": [
            {"title": v["name"], "url": f"sandbox://vendors/{v['vendor_id']}", "snippet": f"{v['trade']}, rated {v['rating']}"}
            for v in self.world["vendors"]]}}

    def t_find_vendors(self, trade, zip):
        return {"ok": True, "data": {"vendors": [v for v in self.world["vendors"] if v["trade"] == trade]}}

    def t_request_quote(self, vendor_id, job_id, description):
        v = next(x for x in self.world["vendors"] if x["vendor_id"] == vendor_id)
        if not v["responds"]:
            return {"ok": False, "error": {"code": "TIMEOUT", "retryable": True,
                                           "message": f"{v['name']} did not respond"}}
        q = {"quote_id": self._nid("Q"), "vendor_id": vendor_id, "job_id": job_id,
             "amount": v["quote_range"][0] + 25, "eta": "tomorrow 9-11 AM", "status": "received"}
        self.world["quotes"].append(q)
        return {"ok": True, "data": {"quote": q, "quote_id": q["quote_id"], "amount": q["amount"]}}

    def t_book_vendor(self, quote_id, override=False):
        q = next(x for x in self.world["quotes"] if x["quote_id"] == quote_id)
        if q["amount"] > self.world["policy"]["spend_limit_usd"] and not override:
            return {"ok": False, "error": {"code": "BUDGET_EXCEEDED", "retryable": False,
                    "message": f"${q['amount']} is over the ${self.world['policy']['spend_limit_usd']} limit"}}
        job = next(j for j in self.world["jobs"] if j["job_id"] == q["job_id"])
        job.update(status="booked", vendor_id=q["vendor_id"], cost=q["amount"])
        q["status"] = "accepted"
        return {"ok": True, "data": {"job": job}}

    # ---------- threads ----------
    def _thread(self, thread_id):
        return next(t for t in self.world["threads"] if t["thread_id"] == thread_id)

    def _new_thread(self, channel, renter_id, name, language):
        th = {"thread_id": self._nid("T"), "channel": channel, "renter_id": renter_id,
              "renter_name": name, "language": language, "messages": []}
        with self.lock:
            self.world["threads"].append(th)
            self.world["channels"].setdefault(channel, {"posts": [], "threads": []})["threads"].append(th["thread_id"])
        return th

    # ---------- behaviours ----------
    def handle_goal(self, text: str):
        t = text.lower()
        if re.search(r"leak|plumb|clog|repair|broken|no hot water|toilet|sink", t):
            return self.ops_flow(text)
        if re.search(r"room|free|available|\$\s?\d+", t):
            return self.listing_flow(text)
        self.log.emit("model_message", "operator", {"to": "owner", "model": "stub",
                      "text": "Noted. I'll keep going and flag anything that needs you."})

    def listing_flow(self, text: str):
        price = re.search(r"\$\s?(\d[\d,]*)", text)
        price = int(price.group(1).replace(",", "")) if price else None
        date = parse_date(text, self.world["clock"][:10]) or "2026-11-01"
        street = re.search(r"([A-Z][a-z]+(?: [A-Z][a-z]+)* (?:Way|St|Street|Rd|Road|Ave|Dr|Ln|Ct|Blvd))", text)
        private = bool(re.search(r"private bath", text, re.I))
        name = street.group(1) if street else "Sandbox"
        room_id = "R-" + re.sub(r"\W", "", name.upper())[:10]
        fields = {"area": "Durham", "zip": "27704", "address_public": f"{name}, Durham (sandbox)",
                  "type": "room in house", "private_bath": private, "rent": price or 800,
                  "deposit": price or 800, "utilities": "included", "available_from": date,
                  "pets": "case by case", "lease_min_months": 12}
        self.call("update_room", {"room_id": room_id, "fields": fields})
        self.pause()
        m = self.call("get_market_rent", {"zip": "27704"})
        self.pause()
        title = f"Room with {'private bath' if private else 'shared bath'} near {name}, ${fields['rent']}"
        body = (f"Furnished-ready room off {name} in Durham, {'private bath, ' if private else ''}utilities included, "
                f"available {date}. 12-month lease, ${fields['rent']} a month.")
        c = self.call("check_listing_compliance", {"text": title + " " + body})
        self.log.emit("verifier", "verifier", {"check": "fair-housing phrases", "ok": c["data"]["ok"],
                      "detail": "24 CFR 100.75 phrase rules"})
        lst = self.call("create_listing", {"room_id": room_id, "title": title, "body": body,
                                           "price": fields["rent"]})
        if not lst.get("ok"):
            return
        lid = lst["data"]["listing_id"]
        self.listing_room = self._room(room_id)
        posted, blocked = [], []
        for ch in POST_CHANNELS:
            self.pause(0.3)
            r = self.call("publish_listing", {"listing_id": lid, "channel": ch})
            if r.get("ok"):
                posted.append(ch)
            else:
                blocked.append(ch)
                if r["error"]["code"] == "LOGIN_REQUIRED":
                    self.call("escalate_to_owner", {"reason": f"Log in to {ch} so I can post", "ref_id": lid})
                else:
                    self.log.emit("fallback", "operator", {"tool": "publish_listing", "from": ch,
                                  "to": "other channels", "reason": r["error"]["code"]})
        zori = m.get("data", {}).get("zori") if m.get("ok") else None
        self.log.emit("model_message", "operator", {"to": "owner", "model": "stub", "text":
                      f"Listed {name} at ${fields['rent']} (area ZORI ${zori}) on {', '.join(posted) or 'no channels'}."
                      + (f" Couldn't post to {', '.join(blocked)}." if blocked else "")})
        if not self.counterparts:
            self.spawn_counterparts()

    def spawn_counterparts(self):
        specs = (self.scenario or {}).get("counterparts") or DEFAULT_COUNTERPARTS
        for i, spec in enumerate(specs):
            cp = Counterpart(spec)
            if cp.id in self.counterparts:
                continue
            self.counterparts[cp.id] = cp
            for j, line in enumerate(cp.opening()):
                self.later(2.0 + 3.0 * i + j, "renter_says", cp.id, line)

    def renter_says(self, cp_id: str, text: str):
        cp = self.counterparts[cp_id]
        if not cp.thread_id:
            cp.thread_id = self._new_thread(cp.channel, cp.id, cp.name, cp.language)["thread_id"]
        with self.lock:
            th = self._thread(cp.thread_id)
            th["messages"].append({"id": self._nid("m"), "from": "renter", "text": text,
                                   "attachments": [], "ts": self.world["clock"]})
        self.log.emit("renter_message", cp.id, {"thread_id": cp.thread_id, "channel": cp.channel,
                      "name": cp.name, "language": cp.language, "text": text})
        self.later(0.8, "operator_turn", cp.thread_id)

    def operator_say(self, thread_id: str, text: str) -> bool:
        r = self.call("send_message", {"thread_id": thread_id, "text": text})
        if r.get("ok"):
            self.log.emit("verifier", "verifier", {"check": "style", "ok": True,
                          "detail": "<=2 sentences, <=1 question, no long dashes"})
            th = self._thread(thread_id)
            cp = self.counterparts.get(th["renter_id"])
            reply = cp.reply_to(text) if cp else None
            if reply:
                self.later(2.5, "renter_says", cp.id, reply)
            return True
        code = r["error"]["code"]
        if code == "LOGIN_REQUIRED":
            e = self.call("escalate_to_owner", {"reason": f"{self._thread(thread_id)['channel']} session expired; "
                          "approve to send this reply after login", "ref_id": thread_id, "draft": text})
            if e.get("ok"):
                self.pending_actions[e["data"]["escalation"]["esc_id"]] = {"send": (thread_id, text)}
        else:
            self.log.emit("fallback", "operator", {"tool": "send_message", "from": "reply now",
                          "to": "retry on next turn", "reason": code})
            self.later(4.0, "operator_turn", thread_id)
        return False

    def operator_turn(self, thread_id: str):
        th = self._thread(thread_id)
        lang = th.get("language", "en") if th.get("language") in QUESTIONS else "en"
        reg = next((x for x in self.world["register"] if thread_id in x["thread_ids"]), None)
        pending = None
        if reg:
            pending = next((g for g in GATE if reg["gate"][g]["status"] not in ("answered", "exception")), None)
        rr = self.call("read_reply", {"thread_id": thread_id, "pending_item": pending}, actor="reader")
        if not rr.get("ok"):
            self.log.emit("fallback", "operator", {"tool": "read_reply", "from": "reader",
                          "to": "ask again", "reason": rr["error"]["code"]})
            reading = fallback_reader("", pending, self.world["clock"][:10])
        else:
            reading = rr["data"]
        gate_update = {}
        for g in GATE:
            f = reading.get(g) or {}
            if f.get("status") not in (None, "absent"):
                gate_update[g] = f
        fields = {"gate": gate_update}
        if (reading.get("phone") or {}).get("value"):
            fields["phone"] = reading["phone"]["value"]
        self.call("upsert_renter", {"thread_id": thread_id, "fields": fields})
        reg = next(x for x in self.world["register"] if thread_id in x["thread_ids"])
        intents = reading.get("intents") or []
        room = self.listing_room or {}
        if "hard_no" in intents or reg["gate"]["lease"].get("status") == "no" or "shorter_lease" in intents:
            reg["status"] = "closed"
            msg = ("Thanks for asking, this room needs a 12-month lease so it won't be a fit." if lang == "en"
                   else "Gracias, este cuarto requiere un contrato de 12 meses así que no sería ideal.")
            self.operator_say(thread_id, msg)
            return
        if "price_negotiation" in intents:
            draft = (f"The owner can do ${room.get('rent', 750) - 25} if you sign this week."
                     if lang == "en" else f"El dueño puede dejarlo en ${room.get('rent', 750) - 25}.")
            e = self.call("escalate_to_owner", {"reason": f"{th['renter_name']} asked for a lower price",
                                                "ref_id": thread_id, "draft": draft})
            if e.get("ok"):
                self.pending_actions[e["data"]["escalation"]["esc_id"]] = {"send": (thread_id, draft),
                                                                         "deny": (thread_id, "The price is firm at "
                                                                                  f"${room.get('rent', 750)}.")}
        missing = [g for g in GATE if reg["gate"][g].get("status") not in ("answered", "exception")]
        if not missing and reg["status"] in ("showing_proposed", "showing_confirmed"):
            if reg["status"] == "showing_proposed" and "hard_no" not in intents:
                reg["status"] = "showing_confirmed"
                for ev in self.world["calendar"]:
                    if ev.get("renter_id") == reg["renter_id"]:
                        ev["status"] = "confirmed"
                self.operator_say(thread_id, "Great, see you then." if lang == "en" else "Perfecto, nos vemos.")
                self.call("report_to_owner", {"summary": f"Showing confirmed with {reg['name']}"})
            return
        if not missing:
            slots = self.call("find_showing_slots", {"room_id": room.get("room_id", ""), "date_from": "2026-10-20",
                                                     "date_to": "2026-10-27"})
            start = slots["data"]["slots"][0] if slots.get("ok") else "2026-10-24T11:00"
            p = self.call("propose_showing", {"renter_id": reg["renter_id"], "room_id": room.get("room_id", ""),
                                              "start": start})
            if p.get("ok") and reg["status"] != "showing_proposed_sent":
                reg["status"] = "showing_proposed"
                msg = ("Thanks, you're all set. I can show the room Sat Oct 24 at 11 AM, does that work?" if lang == "en"
                       else "Gracias, ya está todo. ¿Te funciona una visita el sábado 24 a las 11?")
                self.operator_say(thread_id, msg)
            return
        nxt = missing[0]
        q = QUESTIONS[lang]["move_in_vague"] if (nxt == "move_in" and reg["gate"]["move_in"].get("status") == "vague") \
            else QUESTIONS[lang][nxt]
        if len(th["messages"]) <= 1 or sum(m["from"] == "operator" for m in th["messages"]) == 0:
            hi = (f"Hi {th['renter_name']}, yes, it's available {room.get('available_from', 'Nov 1')} at ${room.get('rent', 750)}."
                  if lang == "en" else f"Hola {th['renter_name']}, sí, está disponible desde el {room.get('available_from', '1 de nov')} por ${room.get('rent', 750)}.")
            q = hi + " " + q
        self.operator_say(thread_id, q)

    def handle_decision(self, esc_id: str, approve: bool, note: str = ""):
        with self.lock:
            esc = next((e for e in self.world["escalations"] if e["esc_id"] == esc_id), None)
            if not esc or esc.get("status") != "open":
                return
            esc["status"] = "approved" if approve else "denied"
        self.log.emit("owner_message", "owner", {"text": f"{'Approved' if approve else 'Denied'} {esc_id}: {esc['reason']}"
                                                         + (f" ({note})" if note else ""), "esc_id": esc_id,
                                                 "decision": esc["status"]})
        act = self.pending_actions.pop(esc_id, {})
        if approve and "send" in act:
            self.operator_say(*act["send"])
        elif not approve and "deny" in act:
            self.operator_say(*act["deny"])
        elif approve and "book" in act:
            r = self.call("book_vendor", {"quote_id": act["book"], "override": True})
            if r.get("ok"):
                self.notify_tenant(r["data"]["job"])

    def ops_flow(self, text: str):
        prop = re.search(r"([A-Z][a-z]+(?: [A-Z][a-z]+)* (?:Way|St|Street|Rd|Road|Ave|Dr|Ln))", text)
        prop = prop.group(1) if prop else "Appling Way"
        job = self.call("create_job", {"property": prop, "issue": text, "severity": "high" if "leak" in text.lower() else "normal"})
        jid = job["data"]["job"]["job_id"]
        self.pause()
        self.call("web_search", {"query": f"plumber near {prop} Durham"})
        vs = self.call("find_vendors", {"trade": "plumber", "zip": "27704"})
        quotes = []
        for v in vs["data"]["vendors"]:
            self.pause(0.3)
            q = self.call("request_quote", {"vendor_id": v["vendor_id"], "job_id": jid, "description": text}, max_attempts=2)
            if q.get("ok"):
                quotes.append(q["data"]["quote"])
            else:
                self.log.emit("fallback", "operator", {"tool": "request_quote", "from": v["name"],
                              "to": "other vendors", "reason": q["error"]["code"]})
        if not quotes:
            self.call("escalate_to_owner", {"reason": "No plumber returned a quote", "ref_id": jid})
            return
        best = min(quotes, key=lambda q: q["amount"])
        b = self.call("book_vendor", {"quote_id": best["quote_id"]})
        if b.get("ok"):
            self.notify_tenant(b["data"]["job"])
        elif b["error"]["code"] == "BUDGET_EXCEEDED":
            e = self.call("escalate_to_owner", {"reason": f"Cheapest quote ${best['amount']} is over the limit",
                                                "ref_id": jid, "draft": f"Book quote {best['quote_id']}"})
            if e.get("ok"):
                self.pending_actions[e["data"]["escalation"]["esc_id"]] = {"book": best["quote_id"]}

    def notify_tenant(self, job):
        v = next(x for x in self.world["vendors"] if x["vendor_id"] == job["vendor_id"])
        th = self._new_thread("sms", "tenant:appling", "Tenant (sandbox)", "en")
        self.operator_say(th["thread_id"], f"A plumber from {v['name'].replace(' (sandbox)', '')} is booked for tomorrow 9-11 AM. "
                                           "Reply here if that time doesn't work.")
        self.call("report_to_owner", {"summary": f"Booked {v['name']} for ${job['cost']} on {job['job_id']}"})
        self.log.emit("model_message", "operator", {"to": "owner", "model": "stub",
                      "text": f"Booked {v['name']} at ${job['cost']} (limit ${self.world['policy']['spend_limit_usd']}). Tenant notified by SMS."})
