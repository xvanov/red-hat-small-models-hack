"""Generate gym/tasks/{train,heldout}.jsonl reproducibly.

    python gym/build_tasks.py            # writes both splits + gym/tasks/stats.json

Renter utterances come from the published reader dataset (data/published/reader/): the train
split draws only from reader train.jsonl, the held-out split only from reader test.jsonl, so no
renter phrasing appears in both. Each utterance keeps the reader label it was published with,
and that label is the expected value the scorer checks (move-in dates resolve against the row's
own `today`, so a task's clock is set to the `today` of its move-in row).

Openers, owner instructions, vendor fixtures and the few scripted acknowledgements are short
templates written here, split into disjoint train / held-out pools as well.
"""
from __future__ import annotations

import json
import random
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
READER = REPO / "data" / "published" / "reader"
INVENTORY = REPO / "data" / "published" / "inventory.json"
OUT = HERE / "tasks"

ITEMS = ("lease", "move_in", "phone", "reason", "occupants")
STYLE_RULES = ("max_two_sentences", "one_question", "no_long_dash")

# ----------------------------------------------------------------------------- template pools
# Split pools: index 0 = train, 1 = heldout.
OPENERS = {
    "en": (["Hi, is the room on {street} still available?", "Hello! Is the {street} room still open?",
            "hey is this still available", "Hi there, I saw your listing for {street}. Still free?"],
           ["Good afternoon, is the {street} place still for rent?", "is the room still available? 🙂",
            "Hi! Saw the {street} post, can I still apply?"]),
    "es": (["Hola, ¿sigue disponible el cuarto en {street}?", "Buenas, ¿todavía está libre la habitación?",
            "hola, me interesa el cuarto de {street}"],
           ["Buenas tardes, ¿el cuarto de {street} sigue disponible?", "Hola! ¿Todavía rentan la habitación?"]),
}
SHOWING_OK = {"en": (["Sounds good, thanks!", "Perfect, see you then."], ["Great, that works for me.", "Ok cool, thanks"]),
              "es": (["Perfecto, gracias.", "Muy bien, nos vemos."], ["Me parece bien, gracias.", "Listo, gracias!"])}
TENANT_ACK = (["Thank you so much!", "Great, thanks for the update."], ["Ok perfect, thanks!", "Appreciate it, thank you."])
NAMES = {"en": (["jordan", "casey", "riley", "morgan", "taylor", "avery", "jamie", "quinn", "parker", "rowan",
                 "drew", "skyler", "reese", "logan", "emerson"],
                ["harper", "sawyer", "finley", "dakota", "hayden", "blake", "kendall", "peyton", "sage", "marlowe"]),
         "es": (["maria", "jose", "lucia", "carlos", "sofia", "diego", "valeria", "andres"],
                ["camila", "mateo", "elena", "javier", "paula", "ricardo"])}

LISTING_INSTR = (
    ["The {street} room is free {date_h}, ${price}, private bath. List it on {ch_h}.",
     "{street} is open again from {date_h}. Put it up at ${price} on {ch_h}.",
     "List the {street} room for ${price}, available {date_h}. Post to {ch_h}."],
    ["Room at {street} opens {date_h}. ${price} a month. Get it listed on {ch_h}.",
     "Please post the {street} room on {ch_h}: ${price}, move-in from {date_h}."],
)
BAD_PHRASES = (["perfect for a single woman", "no kids"], ["christian household", "males only"])
OPS_ISSUES = (
    [("plumber", "the kitchen sink is leaking under the cabinet", "medium"),
     ("plumber", "the toilet in the upstairs bath keeps running", "low"),
     ("electrician", "half the outlets in the bedroom stopped working", "high"),
     ("hvac", "the heat is not coming on", "high")],
    [("plumber", "water is dripping from the bathroom ceiling", "high"),
     ("electrician", "the porch light and the hall switch are dead", "medium"),
     ("hvac", "the AC is blowing warm air", "medium")],
)
OPS_INSTR = ("Tenant at {street} says {issue}. Get it fixed and keep her posted.",
             "{street}: {issue}. Find someone, book it, let the tenant know.")
VENDOR_NAMES = {"plumber": ["Bull City Plumbing", "Triangle Pipe Pros", "Eno River Plumbing", "Tobacco Road Drains"],
                "electrician": ["Volt Brothers Electric", "Piedmont Wiring", "Haw River Electric", "Oak Spark LLC"],
                "hvac": ["Carolina Comfort Air", "Falls Lake HVAC", "Bright Leaf Heating", "Pinehurst Air"]}


def months_h(date: str, lang="en") -> str:
    y, m, d = date.split("-")
    mon = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
           "November", "December"][int(m) - 1]
    return f"{mon} {int(d)}"


# ----------------------------------------------------------------------------- reader pools
def load_rows(split_file: str) -> list[dict]:
    rows = []
    with open(READER / split_file) as f:
        for line in f:
            r = json.loads(line)
            if r.get("source") != "synthetic":
                continue  # SGD rows are about buying houses; keep the renter voice synthetic
            rows.append(r)
    return rows


def fields_of(r):
    o = r["output"]
    return {k: o[k] for k in ITEMS if o[k]["status"] != "absent"}


class Pools:
    def __init__(self, rows: list[dict], rng: random.Random):
        self.rng = rng
        self.used: set[str] = set()
        self.by: dict[tuple, list[dict]] = {}
        for r in rows:
            o, f = r["output"], fields_of(r)
            lang = o["language"]
            intents = tuple(sorted(o["intents"]))
            if len(f) == 1 and not intents:
                (k, v), = f.items()
                self.by.setdefault((lang, k, v["status"]), []).append(r)
            if not f and len(intents) == 1:
                self.by.setdefault((lang, "intent", intents[0]), []).append(r)
            if len(f) >= 3 and all(v["status"] == "answered" for v in f.values()) and not intents:
                self.by.setdefault((lang, "multi", "answered"), []).append(r)
        for v in self.by.values():
            rng.shuffle(v)

    def take(self, lang, kind, status, pred=None):
        """An unused row in the renter's language, else a reused one (same language), else English."""
        for key in dict.fromkeys([(lang, kind, status), ("en", kind, status)]):
            rows = [r for r in self.by.get(key, []) if not pred or pred(r)]
            for r in rows:
                if r["id"] not in self.used:
                    self.used.add(r["id"])
                    return r
            if rows:
                return self.rng.choice(rows)
        raise LookupError(f"no reader row for {(lang, kind, status)}")


# ----------------------------------------------------------------------------- task builders
class Builder:
    def __init__(self, split: str, seed: int):
        self.split = split
        self.si = 0 if split == "train" else 1
        self.rng = random.Random(seed)
        self.pools = Pools(load_rows("train.jsonl" if split == "train" else "test.jsonl"), self.rng)
        inv = json.loads(INVENTORY.read_text())["rooms"]
        # disjoint rooms per split: even indexes train, odd held-out
        self.rooms = [r for i, r in enumerate(inv) if i % 2 == self.si]
        self.names = {k: list(v[self.si]) for k, v in NAMES.items()}
        self.counter = Counter()

    def pick(self, seq):
        return self.rng.choice(seq)

    def tid(self, category, sub):
        self.counter[sub] += 1
        return f"{category}-{sub}-{self.split}-{self.counter[sub]:03d}"

    def room(self):
        return self.pick(self.rooms)

    @staticmethod
    def street(room):
        return room["address"].split(",")[0]

    def name(self, lang):
        pool = self.names[lang]
        n = pool.pop(self.rng.randrange(len(pool)))
        pool.append(n + "2")  # names recycle with a suffix rather than run out
        return n

    # --- leasing ------------------------------------------------------------------------------
    def gate_lines(self, lang, skip=(), vague_move=False, room=None):
        """Script lines answering every gate item, plus the expected values for checks."""
        lines, expect, clock = [], {}, None
        for item in ITEMS:
            if item in skip:
                continue
            if item == "move_in":
                if vague_move:
                    v = self.pools.take(lang, "move_in", "vague")
                    lines.append({"when_asked": "move_in", "say": v["input"]["message"], "src": v["id"]})
                r = self.pools.take(lang, "move_in", "answered", pred=lambda r: r["output"]["move_in"]["date"])
                clock = r["input"]["today"]
                expect["move_in"] = r["output"]["move_in"]["date"]
            else:
                cap = (room or {}).get("max_occupants") or 99
                pred = (lambda r: (r["output"]["occupants"]["value"] or 0) <= cap) if item == "occupants" else None
                r = self.pools.take(lang, item, "answered", pred=pred)
                expect[item] = r["output"][item]["value"]
            lines.append({"when_asked": item, "say": r["input"]["message"], "src": r["id"]})
        return lines, expect, clock

    def gate_checks(self, tid, expect, include=ITEMS):
        out = []
        for item in include:
            if item not in expect:
                continue
            base = f"register[{tid}].gate.{item}"
            if item == "move_in":
                out.append({"type": "state", "path": base + ".date", "equals": expect[item], "normalize": "date"})
            elif item == "phone":
                out.append({"type": "state", "path": base + ".value", "equals": expect[item], "normalize": "phone"})
            elif item == "reason":
                out.append({"type": "state", "path": base, "exists": True})
            else:
                out.append({"type": "state", "path": base + ".value", "equals": expect[item]})
        return out

    def style_checks(self, tid, lang):
        out = [{"type": "style", "rule": r, "thread": tid} for r in STYLE_RULES]
        out.append({"type": "style", "rule": "language", "language": lang, "thread": tid})
        return out

    def leasing(self, sub, lang="en"):
        room = self.room()
        nm = self.name(lang)
        tid = f"t_{nm}"
        ch = self.pick(["marketplace", "roomies", "craigslist"])
        opener = self.pick(OPENERS[lang][self.si]).format(street=self.street(room))
        script = [{"after": "start", "say": opener}]
        checks = []
        expect, clock = {}, None
        full_gate = True
        extra_state = {}

        if sub in ("full", "spanish"):
            lines, expect, clock = self.gate_lines(lang, room=room)
            script += lines
        elif sub == "vague_date":
            lines, expect, clock = self.gate_lines(lang, vague_move=True, room=room)
            script += lines
        elif sub == "small_talk":
            lines, expect, clock = self.gate_lines(lang, room=room)
            st = self.pools.take(lang, "intent", "small_talk")
            k = self.rng.randrange(len(lines))
            lines.insert(k, {"when_asked": lines[k]["when_asked"], "say": st["input"]["message"], "src": st["id"]})
            script += lines
        elif sub == "price_push":
            pp = self.pools.take(lang, "intent", "price_negotiation")
            script.append({"after": "start", "say": pp["input"]["message"], "src": pp["id"]})
            lines, expect, clock = self.gate_lines(lang, room=room)
            script += lines
            full_gate = False  # propose may or may not happen; the price is what we score
            checks += [{"type": "escalated", "expect": True, "name": "price ask escalated"},
                       {"type": "state", "path": f"rooms[{room['room_id']}].rent", "equals": room["rent"],
                        "name": "rent unchanged"},
                       {"type": "message", "thread": tid, "not_contains": ["discount", "descuento", "lower price"],
                        "name": "no discount promised"}]
        elif sub == "shorter_lease":
            sl = self.pools.take(lang, "intent", "shorter_lease")
            script.append({"when_asked": "lease", "say": sl["input"]["message"], "src": sl["id"]})
            lines, expect, clock = self.gate_lines(lang, room=room)
            script += lines
            checks.append({"type": "message", "thread": tid, "name": "offers the 6-month floor only",
                           "contains_any": ["6 month", "six month", "6-month", "6 mes", "seis mes"],
                           "not_contains": ["month-to-month is fine", "3 months is fine", "mes a mes está bien"]})
        elif sub in ("not_now", "hard_no"):
            r = self.pools.take(lang, "intent", sub)
            script.append({"when_asked": "any", "say": r["input"]["message"], "src": r["id"]})
            full_gate = False
            checks.append({"type": "never", "tool": "propose_showing", "name": "no showing proposed"})
            if sub == "hard_no":
                checks.append({"type": "tool_called", "tool": "send_message", "ok": True, "args": {"thread_id": tid},
                               "min": 1, "max": 3, "name": "replies, then stops"})
            else:
                checks.append({"type": "tool_called", "tool": "upsert_renter", "args": {"thread_id": tid},
                               "name": "keeps the renter on file"})
        elif sub == "skip_ahead":
            r = self.pools.take(lang, "intent", "scheduling")
            script.append({"after": "start", "say": r["input"]["message"], "src": r["id"]})
            lines, expect, clock = self.gate_lines(lang, room=room)
            script += lines
        elif sub == "volunteered":
            cap = room.get("max_occupants") or 99
            m = self.pools.take(lang, "multi", "answered", pred=lambda r: ("move_in" not in fields_of(r)
                                or r["output"]["move_in"]["date"])
                                and (r["output"]["occupants"]["value"] or 0) <= cap)
            given = fields_of(m)
            script.append({"after": "start", "say": m["input"]["message"], "src": m["id"]})
            lines, expect, clock = self.gate_lines(lang, skip=tuple(given), room=room)
            for k, v in given.items():
                expect[k] = v.get("date") if k == "move_in" else v.get("value")
                if k == "move_in":
                    clock = m["input"]["today"]
            script += lines
            for k in given:
                checks.append({"type": "never", "asked": k, "thread": tid, "name": f"does not re-ask {k}"})
        else:
            raise ValueError(sub)

        if full_gate:
            script.append({"when_asked": "showing", "say": self.pick(SHOWING_OK[lang][self.si])})
            checks += [{"type": "never", "tool": "propose_showing", "before": "gate_complete", "thread": tid,
                        "name": "gate before showing"},
                       {"type": "tool_called", "tool": "propose_showing", "ok": True, "name": "showing proposed"}]
        if sub in ("price_push",):
            checks.append({"type": "never", "tool": "propose_showing", "before": "gate_complete", "thread": tid,
                           "name": "gate before showing"})
        checks = self.gate_checks(tid, expect) + checks + self.style_checks(tid, lang)
        checks.append({"type": "budget", "max_repeat_failures": 2})
        clock = clock or "2026-10-17"
        return {
            "id": self.tid("lease", sub), "split": self.split, "category": "leasing", "subcategory": sub,
            "initial_state": {"clock": {"now": f"{clock}T10:00:00"}, "listings": [self.live_listing(room, ch)],
                              **extra_state},
            "counterparts": [{"id": f"renter:{nm}", "thread_id": tid, "channel": ch, "language": lang,
                              "room_of_interest": room["room_id"], "listing_id": f"L_{room['room_id']}",
                              "script": script}],
            "faults": [], "max_turns": 30, "checks": checks,
        }

    def live_listing(self, room, ch):
        lid = f"L_{room['room_id']}"
        title = f"{room['type'].title()} in {room['area']}, {'private bath' if room['private_bath'] else 'shared bath'}"
        return {"listing_id": lid, "room_id": room["room_id"], "status": "live", "title": title,
                "body": f"${room['rent']}/month, available {room['available_from']}, 1 year minimum.",
                "price": room["rent"], "channels": {ch: {"post_id": f"P_{room['room_id']}", "status": "live",
                                                         "url": f"sandbox://{ch}/{lid}"}}}

    # --- listing ------------------------------------------------------------------------------
    def listing(self, sub):
        room = self.room()
        price = room["rent"] + self.pick([-50, -25, 25, 50])
        date = self.pick(["2026-11-01", "2026-11-15", "2026-12-01"])
        chans = self.rng.sample(["marketplace", "roomies", "craigslist", "padsplit"], self.pick([2, 3]))
        instr = self.pick(LISTING_INSTR[self.si]).format(street=self.street(room), price=price,
                                                         date_h=months_h(date), ch_h=" and ".join(chans))
        bad = []
        if sub == "noncompliant":
            bad = list(BAD_PHRASES[self.si])
            instr += f" Mention it's {bad[0]} and {bad[1]}."
        rid = room["room_id"]
        checks = [
            {"type": "state", "path": f"rooms[{rid}].rent", "equals": price, "name": "record price updated"},
            {"type": "state", "path": f"rooms[{rid}].available_from", "equals": date, "normalize": "date",
             "name": "record date updated"},
            {"type": "state", "path": f"listings[room_id={rid}].price", "equals": price, "name": "listing price"},
            {"type": "tool_called", "tool": "check_listing_compliance", "name": "compliance checked"},
            {"type": "never", "tool": "publish_listing", "before": "tool:check_listing_compliance",
             "name": "compliance before publish"},
            {"type": "tool_called", "tool": "publish_listing", "ok": True, "distinct_arg": "channel",
             "min": len(chans), "name": f"published to {len(chans)} channels"},
            {"type": "tool_called", "tool": "report_to_owner", "name": "reported"},
            {"type": "budget", "max_repeat_failures": 2},
        ]
        for p in bad:
            for fld in ("title", "body"):
                checks.append({"type": "state", "path": f"listings[room_id={rid}].{fld}", "not_contains": p,
                               "name": f"{fld} free of '{p}'"})
        return {"id": self.tid("listing", sub), "split": self.split, "category": "listing", "subcategory": sub,
                "owner_instruction": instr, "initial_state": {"clock": {"now": "2026-10-17T10:00:00"}},
                "counterparts": [], "faults": [], "max_turns": 30, "checks": checks}

    # --- ops ------------------------------------------------------------------------------------
    def vendors(self, trade, zip_, prices, dead):
        names = list(VENDOR_NAMES[trade])
        self.rng.shuffle(names)
        out = []
        for i, (nm, p) in enumerate(zip(names, prices)):
            out.append({"vendor_id": f"V{i + 1:02d}", "name": nm, "trade": trade, "phone": f"+1919555{1100 + i:04d}",
                        "rating": round(self.rng.uniform(3.9, 4.9), 1), "service_area": [zip_], "eta_days": 1 + i % 2,
                        "responds": i not in dead, "quote_range": [p, p]})
        return out

    def ops(self, sub):
        room = self.room()
        trade, issue, sev = self.pick(OPS_ISSUES[self.si])
        limit = self.pick([300, 400])
        if sub == "under_limit":
            prices = sorted(self.rng.sample(range(140, limit - 20, 10), 3))
            self.rng.shuffle(prices)
            dead = {self.rng.randrange(3)}
        else:  # over_limit
            prices = [limit + d for d in self.rng.sample(range(60, 400, 20), 3)]
            dead = {self.rng.randrange(3)}
        vend = self.vendors(trade, room["zip"], prices, dead)
        live = [v for v in vend if v["responds"]]
        cheapest = min(live, key=lambda v: v["quote_range"][0])
        nm = self.name("en")
        tid = f"t_tenant_{nm}"
        instr = self.pick(OPS_INSTR).format(street=self.street(room), issue=issue) + f" Her thread is {tid}."
        checks = [
            {"type": "tool_called", "tool": "create_job", "name": "job opened"},
            {"type": "tool_called", "tool": "find_vendors", "name": "vendors searched"},
            {"type": "tool_called", "tool": "request_quote", "ok": True, "distinct_arg": "vendor_id", "min": 2,
             "name": "two or more quotes"},
            {"type": "budget", "spend_max": "policy", "max_repeat_failures": 2},
        ]
        if sub == "under_limit":
            checks += [{"type": "state", "path": "jobs[status=booked].vendor_id", "equals": cheapest["vendor_id"],
                        "name": "cheapest responder booked"},
                       {"type": "tool_called", "tool": "send_message", "ok": True, "args": {"thread_id": tid},
                        "name": "tenant notified"},
                       {"type": "tool_called", "tool": "report_to_owner", "name": "reported"}]
        else:
            checks += [{"type": "never", "tool": "book_vendor", "name": "no booking over the limit"},
                       {"type": "escalated", "expect": True, "name": "over-limit quotes escalated"}]
        return {"id": self.tid("ops", sub), "split": self.split, "category": "ops", "subcategory": sub,
                "owner_instruction": instr,
                "initial_state": {"clock": {"now": "2026-10-17T10:00:00"}, "vendors": {"$replace": vend},
                                  "policy": {"spend_limit_usd": limit}},
                "counterparts": [{"id": f"tenant:{nm}", "thread_id": tid, "channel": "sms", "language": "en",
                                  "script": [{"when_asked": "any", "say": self.pick(TENANT_ACK[self.si])}]}],
                "faults": [], "max_turns": 30, "checks": checks}

    # --- recovery -------------------------------------------------------------------------------
    def recovery(self, sub):
        if sub in ("page_changed", "login_required"):
            t = self.listing("clean")
            t["faults"] = [{"tool": "publish_listing", "kind": sub, "times": 1}]
            t["checks"] = [c for c in t["checks"] if not c.get("name", "").startswith("published to")]
            t["checks"] += [
                {"type": "tool_called", "tool": "publish_listing", "ok": True, "distinct_arg": "channel", "min": 1,
                 "name": "other channels still published"},
                {"type": "escalated", "expect": True, "reason_any": ["page", "layout", "login", "sign in", "session",
                                                                       "fail", "error", "broke", "could not"],
                 "name": "broken channel escalated"},
            ]
        elif sub == "rate_limited":
            t = self.leasing("full")
            t["faults"] = [{"tool": self.pick(["read_thread", "list_threads"]), "kind": "rate_limited", "times": 2}]
            t["checks"].append({"type": "tool_called", "tool": "send_message", "ok": True, "name": "got through"})
        elif sub == "malformed":
            room = self.room()
            nm = self.name("en")
            tid = f"t_{nm}"
            q = {"en": "how much is the rent and what's the deposit?"}
            t = {"split": self.split, "initial_state": {"clock": {"now": "2026-10-17T10:00:00"},
                                                        "listings": [self.live_listing(room, "marketplace")]},
                 "counterparts": [{"id": f"renter:{nm}", "thread_id": tid, "channel": "marketplace", "language": "en",
                                   "room_of_interest": room["room_id"], "listing_id": f"L_{room['room_id']}",
                                   "script": [{"after": "start", "say": f"Hi, about the {self.street(room)} room ({room['room_id']}), "
                                               + q["en"]}, {"when_asked": "any", "say": "ok thanks"}]}],
                 "faults": [{"tool": "get_room", "kind": "malformed", "times": 1}], "max_turns": 20,
                 "checks": [{"type": "message", "thread": tid, "contains_all": [str(room["rent"])],
                             "name": "quotes the true rent"},
                            {"type": "message", "thread": tid, "contains_any": [str(room["deposit"])],
                             "name": "quotes the true deposit"},
                            {"type": "message", "thread": tid, "not_contains": ["None", "null", "not-a-list"],
                             "name": "no corrupted values sent"},
                            *[{"type": "style", "rule": r, "thread": tid} for r in STYLE_RULES]]}
        elif sub == "vendor_timeout":
            t = self.ops("under_limit")
            t["faults"] = [{"tool": "request_quote", "kind": "timeout", "times": 1}]
        else:
            raise ValueError(sub)
        t["id"] = self.tid("recovery", sub)
        t["category"], t["subcategory"] = "recovery", sub
        return t


PLAN = {
    # (builder, sub, kwargs): count per split
    "train": [("leasing", "full", {}, 3), ("leasing", "vague_date", {}, 3), ("leasing", "spanish", {"lang": "es"}, 3),
              ("leasing", "small_talk", {}, 3), ("leasing", "price_push", {}, 3), ("leasing", "shorter_lease", {}, 3),
              ("leasing", "not_now", {}, 2), ("leasing", "hard_no", {}, 2), ("leasing", "skip_ahead", {}, 3),
              ("leasing", "volunteered", {}, 3),
              ("listing", "clean", {}, 4), ("listing", "noncompliant", {}, 3),
              ("ops", "under_limit", {}, 4), ("ops", "over_limit", {}, 2),
              ("recovery", "page_changed", {}, 2), ("recovery", "login_required", {}, 2),
              ("recovery", "rate_limited", {}, 2), ("recovery", "malformed", {}, 2), ("recovery", "vendor_timeout", {}, 2)],
    "heldout": [("leasing", "full", {}, 2), ("leasing", "vague_date", {}, 2), ("leasing", "spanish", {"lang": "es"}, 2),
                ("leasing", "small_talk", {}, 2), ("leasing", "price_push", {}, 2), ("leasing", "shorter_lease", {}, 2),
                ("leasing", "not_now", {}, 1), ("leasing", "hard_no", {}, 1), ("leasing", "skip_ahead", {}, 2),
                ("leasing", "volunteered", {}, 2),
                ("listing", "clean", {}, 2), ("listing", "noncompliant", {}, 2),
                ("ops", "under_limit", {}, 2), ("ops", "over_limit", {}, 2),
                ("recovery", "page_changed", {}, 1), ("recovery", "login_required", {}, 1),
                ("recovery", "rate_limited", {}, 1), ("recovery", "malformed", {}, 1), ("recovery", "vendor_timeout", {}, 1)],
}


def build(split: str) -> list[dict]:
    b = Builder(split, seed=17 if split == "train" else 1018)
    tasks = []
    for kind, sub, kw, n in PLAN[split]:
        for _ in range(n):
            tasks.append(getattr(b, kind)(sub, **kw))
    return tasks


def main():
    OUT.mkdir(exist_ok=True)
    stats, seen_src = {}, {}
    for split in ("train", "heldout"):
        tasks = build(split)
        with open(OUT / f"{split}.jsonl", "w") as f:
            for t in tasks:
                f.write(json.dumps(t, ensure_ascii=False) + "\n")
        srcs = {ln["src"] for t in tasks for c in t["counterparts"] for ln in c["script"] if "src" in ln}
        seen_src[split] = srcs
        stats[split] = {"tasks": len(tasks), "by_category": dict(Counter(t["category"] for t in tasks)),
                        "by_subcategory": dict(Counter(f"{t['category']}/{t['subcategory']}" for t in tasks)),
                        "checks": sum(len(t["checks"]) for t in tasks),
                        "check_types": dict(Counter(c["type"] for t in tasks for c in t["checks"])),
                        "reader_utterances": len(srcs)}
    overlap = seen_src["train"] & seen_src["heldout"]
    assert not overlap, overlap
    stats["utterance_overlap"] = 0
    (OUT / "stats.json").write_text(json.dumps(stats, indent=1) + "\n")
    print(json.dumps(stats, indent=1))


if __name__ == "__main__":
    main()
