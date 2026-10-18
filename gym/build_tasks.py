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
    main_v2()


# ============================================================================= task set v2
# v1 above is frozen for history (gym/tasks/*.jsonl). v2 fixes what the review in docs/task-review.md
# found; docs/task-v2-changes.md lists every change. Same discipline: held-out utterances only from
# reader test.jsonl, train only from train.jsonl, disjoint template pools, odd/even room split.
from datetime import date as _date, timedelta as _td  # noqa: E402
import re as _re  # noqa: E402

OUT2 = OUT / "v2"
MONTHS_EN = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
             "November", "December"]
MONTHS_ES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
             "noviembre", "diciembre"]
# Names the reader set's synthetic renters sign with (data/build_reader_set.py POOLS, both splits). One
# renter signing as three different people is fixed by rewriting every one of them to a single name.
READER_NAMES = ["Quentin", "Rachel", "Malik", "Lindsey", "Trevor", "Jasmine", "Colin", "Imani", "Ernesto", "Yesenia",
                "Ramón", "Marisol", "Héctor", "Daniela", "Jordan", "Tyler", "Brianna", "Marcus", "Ashley", "Kevin",
                "Destiny", "Ryan", "Megan", "Andre", "Courtney", "Josh", "Tasha", "Ben", "Kayla", "Derek", "Monique",
                "Sam", "Hannah", "Darnell", "José", "María", "Luis", "Guadalupe", "Carlos", "Ana", "Miguel", "Rosa",
                "Jorge", "Lucía", "Alejandro", "Fernanda", "Juan", "Isabel", "Diego", "Paola"]
_NAME_RE = _re.compile(r"\b(" + "|".join(sorted(READER_NAMES, key=len, reverse=True)) + r")\b", _re.I)
PETS = _re.compile(r"\b(dogs?|cats?|pets?|pupp(y|ies)|kittens?|perr[oa]s?|perrit[oa]s?|gat[oa]s?|gatit[oa]s?|mascotas?)\b", _re.I)
FALL = _re.compile(r"\bfall\b|oto[nñ]o", _re.I)
DAY_ONLY = _re.compile(r"^(on )?(the |el (d[ií]a )?)?(\d{1,2}(st|nd|rd|th)?|primero)$", _re.I)

# split pools (index 0 = train, 1 = held-out), written here
CONFIRM = {
    "move_in": {"en": ("Right, {d} is the date.", "Yes, {d} is my move-in date."),
                "es": ("Sí, {d}.", "Sí, mi fecha de mudanza es {d}.")},
    "phone": {"en": ("Yep, {v} is right.", "Yes, that's my number, {v}."),
              "es": ("Sí, es el {v}.", "Sí, mi número es {v}.")},
    "lease": {"en": ("Yes, one year works.", "Yes, a one year lease is fine with me."),
              "es": ("Sí, un año me funciona.", "Sí, un contrato de un año está bien.")},
    "occupants": {"en": ("{n} people total.", "It would be {n} people."),
                  "es": ("{n} personas en total.", "Seríamos {n} personas.")},
}
GENERIC = {"en": ("Not sure what you mean, what else do you need to know?",
                  "I think that's everything from me. What else do you need?"),
           "es": ("No estoy seguro, ¿qué más necesitas saber?", "Creo que eso es todo. ¿Qué más necesitas?")}
CORRECTED = {"en": (["Ah ok, {d} is fine then.", "No problem, let's say {d} then."],
                    ["Oh I see, then {d} works for me.", "Got it, I can do {d} then."])}
# Owner decision D23 (a): a renter who accepts the 6-month floor passes the lease item. Templates, disjoint per split.
ACCEPT_SIX = {"en": (["Ok, 6 months works for me then.", "Fine, I'll do the 6 month lease."],
                     ["Alright, 6 months it is.", "Sounds good, a 6 month lease works for me."]),
              "es": (["Bueno, 6 meses me funciona.", "Está bien, hago el contrato de 6 meses."],
                     ["De acuerdo, 6 meses entonces.", "Perfecto, un contrato de 6 meses me funciona."])}
CONFIRM_SIX = {"en": ("Yes, 6 months works.", "Yes, 6 months is fine with me."),
               "es": ("Sí, 6 meses me funciona.", "Sí, 6 meses está bien.")}
TIMEFRAME = {"en": (["Maybe around {m}, not sure yet."], ["Probably around {m}, I'll know more then."])}
OPENERS_MALFORMED = (["Hi, about the {street} room, how much is the rent and what's the deposit?"],
                     ["Hello! For the {street} room, what's the monthly rent and the deposit?"])
BAD_PHRASES_V2 = (["perfect for a single woman", "no kids", "church-going", "able-bodied", "Americans only",
                   "no children"],
                  ["christian household", "adults only", "must speak English", "no wheelchairs",
                   "ideal for single professionals", "catholic home"])
OPS_ISSUES_V2 = (OPS_ISSUES[0] + [("electrician", "the kitchen light flickers and buzzes", "low")],
                 OPS_ISSUES[1] + [("hvac", "the furnace makes a loud banging noise", "medium")])
DISPLAY_NAMES = {"en": (["Jordan", "Casey", "Riley", "Morgan", "Taylor", "Avery", "Jamie", "Quinn", "Parker", "Rowan",
                         "Drew", "Skyler", "Reese", "Logan", "Emerson", "Alex", "Cameron", "Devon"],
                        ["Harper", "Sawyer", "Finley", "Dakota", "Hayden", "Blake", "Kendall", "Peyton", "Sage",
                         "Marlowe", "Ellis", "Rory", "Shiloh", "Arden"]),
                 "es": (["Maria", "Jose", "Lucia", "Sofia", "Valeria", "Andres"],
                        ["Camila", "Mateo", "Elena", "Javier", "Paula", "Ricardo"])}
PRICE_PROMISES = ["i can lower", "i'll lower", "i will lower", "we can lower", "i can do a discount",
                  "i'll give you a discount", "i can give you a discount", "discount is fine", "i can take $",
                  "i can do $", "te puedo bajar", "te hago un descuento", "puedo bajar"]


def _d(iso: str) -> _date:
    return _date.fromisoformat(iso[:10])


def date_h(iso: str, lang: str, clock: str) -> str:
    d, c = _d(iso), _d(clock)
    if lang == "es":
        return f"el {d.day} de {MONTHS_ES[d.month - 1]}" + (f" de {d.year}" if d.year != c.year else "")
    return f"{MONTHS_EN[d.month - 1]} {d.day}" + (f", {d.year}" if d.year != c.year else "")


def phone_h(p: str) -> str:
    d = _re.sub(r"\D", "", p)[-10:]
    return f"{d[:3]}-{d[3:6]}-{d[6:]}"


def first_of_next_month(d: _date) -> _date:
    return _date(d.year + (d.month == 12), d.month % 12 + 1, 1)


def vague_ok(raw: str, d: _date, today: _date) -> bool:
    """Is the exact date `d` a plausible sharpening of the vague answer `raw` given on `today`?"""
    low = (raw or "").lower()
    for i, (en, es) in enumerate(zip(MONTHS_EN, MONTHS_ES)):
        if _re.search(rf"\b({en.lower()}|{en[:3].lower()}|{es})\b", low):
            if d.month != i + 1:
                return False
            if _re.search(r"mid|mediados", low):
                return 8 <= d.day <= 22
            if _re.search(r"early|beginning|principios", low):
                return d.day <= 10
            if _re.search(r"late|end|fines|finales", low):
                return d.day >= 20
            return True
    nxt = today.month % 12 + 1
    if _re.search(r"next month|mes que viene|pr[oó]ximo mes", low):
        return d.month == nxt and (d.day <= 10 if "beginning" in low or "principio" in low else True)
    if _re.search(r"end of the month|fin(es)? de mes", low):
        return d.month == today.month and d.day >= 20
    if _re.search(r"few weeks|couple (of )?weeks|unas semanas", low):
        return 10 <= (d - today).days <= 45
    if _re.search(r"15th|del 15", low):
        return 12 <= d.day <= 18
    m = _re.search(r"(\d{1,2})/(\d{1,2})", low)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        return (d.month, d.day) in ((a, b), (b, a))
    if _re.search(r"soon|asap|lo antes posible|right away", low):
        return (d - today).days <= 30
    return True  # whenever it's ready, flexible...: the room fit below handles it


class Builder2(Builder):
    """v2 generator. Same seeds and split rules as v1; see docs/task-v2-changes.md."""

    def __init__(self, split: str, seed: int):
        super().__init__(split, seed)
        self.display = {k: list(v[self.si]) for k, v in DISPLAY_NAMES.items()}
        self.thread_ids: Counter = Counter()
        self.issue_i = 0
        self.bad_i = 0
        self.short_i = 0
        self.mal_i = 0
        self.notes: list[str] = []

    # ---- row selection, strict on language (v1 fell back to English rows silently)
    def take(self, lang, kind, status, pred=None):
        rows = [r for r in self.pools.by.get((lang, kind, status), []) if not pred or pred(r)]
        for r in rows:
            if r["id"] not in self.pools.used:
                self.pools.used.add(r["id"])
                return r
        if rows:
            return self.rng.choice(rows)
        raise LookupError(f"no reader row for {(lang, kind, status)}")

    # ---- room / availability consistency
    def fit_room(self, move: str, clock: str, early=False, whenever=False):
        """A room whose availability fits the move-in date, and the patch (if any) that makes it fit.

        Normal: available_from <= move <= max(available_from, clock) + 90 days (whenever-it's-ready:
        + 14 days). early: the renter's first date is 7 to 75 days BEFORE available_from.
        No room fits -> pick one and set its available_from in the task's initial_state."""
        d, c = _d(move), _d(clock)

        def ok(r):
            a = _d(r["available_from"])
            if early:
                return 7 <= (a - d).days <= 75
            return a <= d <= max(a, c) + _td(days=14 if whenever else 90)
        fits = [r for r in self.rooms if ok(r)]
        if fits:
            return dict(self.pick(fits)), None
        room = dict(self.pick(self.rooms))
        if early:
            a = first_of_next_month(d)
            if (a - d).days < 7:
                a = first_of_next_month(a)
        else:
            a = max(_date(d.year, d.month, 1), c) if not whenever else d
        room["available_from"] = a.isoformat()
        return room, {"room_id": room["room_id"], "available_from": room["available_from"]}

    # ---- names
    def unify_names(self, script, lang):
        found = [m.group(1) for ln in script for m in _NAME_RE.finditer(ln["say"])]
        if found:
            canon = next(n for n in READER_NAMES if n.lower() == found[0].lower())
        else:
            pool = self.display[lang]
            canon = pool[self.rng.randrange(len(pool))]

        def rep(m):
            w = m.group(1)
            return canon.upper() if w.isupper() else canon.lower() if w.islower() else canon
        for ln in script:
            new = _NAME_RE.sub(rep, ln["say"])
            if new != ln["say"]:
                ln["say"] = new
                ln["edit"] = f"sign-off name set to {canon}"
        slug = Builder2._slug(canon)
        self.thread_ids[slug] += 1
        n = self.thread_ids[slug]
        return canon, f"{slug}{n if n > 1 else ''}"

    @staticmethod
    def _slug(name):
        import unicodedata
        s = unicodedata.normalize("NFKD", name)
        return "".join(ch for ch in s if not unicodedata.combining(ch)).lower()

    # ---- gate lines
    def move_rows(self, lang, sub):
        """(lines, expected date, clock, room, availability patch) for the move-in item."""
        lines = []
        if sub == "early_date":
            r = self.take(lang, "move_in", "answered", pred=lambda r: r["output"]["move_in"]["date"] and (
                _d(r["output"]["move_in"]["date"]) - _d(r["input"]["today"])).days >= 3)
            clock, first = r["input"]["today"], r["output"]["move_in"]["date"]
            room, patch = self.fit_room(first, clock, early=True)
            exp = room["available_from"]
            lines.append({"when_asked": "move_in", "say": r["input"]["message"], "src": r["id"]})
            lines.append({"when_asked": "move_in", "say": self.pick(CORRECTED[lang][self.si]).format(
                d=date_h(exp, lang, clock))})
            return lines, exp, clock, room, patch
        def consistent(v, r):
            dt = r["output"]["move_in"]["date"]
            if not dt:
                return False
            return v is None or vague_ok(v["output"]["move_in"]["raw"] or v["input"]["message"], _d(dt),
                                         _d(r["input"]["today"]))
        exact = self.pools.by.get((lang, "move_in", "answered"), [])
        vague = None
        if sub == "vague_date":  # v1 paired "sometime in january" with "november 1"; v2 pairs consistent ones
            vague = self.take(lang, "move_in", "vague", pred=lambda v: any(consistent(v, r) for r in exact))
            lines.append({"when_asked": "move_in", "say": vague["input"]["message"], "src": vague["id"]})

        def pred(r):
            return consistent(vague, r)
        r = self.take(lang, "move_in", "answered", pred=pred)
        clock, exp = r["input"]["today"], r["output"]["move_in"]["date"]
        whenever = bool(vague) and bool(_re.search(r"whenever|ready|listo", vague["input"]["message"], _re.I))
        room, patch = self.fit_room(exp, clock, whenever=whenever)
        lines.append({"when_asked": "move_in", "say": r["input"]["message"], "src": r["id"]})
        return lines, exp, clock, room, patch

    def other_rows(self, lang, room, clock, skip=()):
        lines, expect = [], {}
        cap = room.get("max_occupants") or 99
        for item in ("lease", "phone", "reason", "occupants"):
            if item in skip:
                continue
            if item == "occupants":
                pred = lambda r: (r["output"]["occupants"]["value"] or 0) <= cap and not PETS.search(r["input"]["message"])
            elif item == "reason":
                pred = lambda r: not FALL.search(r["input"]["message"]) or 6 <= _d(clock).month <= 10
            else:
                pred = None
            try:
                r = self.take(lang, item, "answered", pred=pred)
            except LookupError:
                if item != "occupants":
                    raise
                # no pet-free answer fits this room in this language: let the room take the household
                r = self.take(lang, item, "answered", pred=lambda r: not PETS.search(r["input"]["message"]))
                room["max_occupants"] = r["output"]["occupants"]["value"]
            expect[item] = r["output"][item]["value"]
            lines.append({"when_asked": item, "say": r["input"]["message"], "src": r["id"]})
        return lines, expect

    def confirm_lines(self, lang, expect, clock):
        out = []
        for item, v in expect.items():
            if item not in CONFIRM or v in (None, ""):
                continue
            tpl = CONFIRM[item][lang][self.si]
            if item == "move_in":
                say = tpl.format(d=date_h(v, lang, clock))
            elif item == "phone":
                say = tpl.format(v=phone_h(v))
            elif item == "occupants":
                say = ("Solo yo." if lang == "es" else "Just me.") if v == 1 else tpl.format(n=v)
            else:
                say = tpl
            out.append({"when_asked": item, "say": say, "reuse": True})
        return out

    @staticmethod
    def patch_for(room, orig, patch):
        """Record every room field this task changed (availability, max occupants) in its patch."""
        out = dict(patch or {})
        for k in ("available_from", "max_occupants"):
            if room.get(k) != orig.get(k):
                out.update({"room_id": room["room_id"], k: room[k]})
        return out or None

    def gate_checks2(self, tid, expect):
        out = []
        for item in ITEMS:
            if item not in expect:
                continue
            base = f"register[{tid}].gate.{item}"
            if item == "move_in":
                out.append({"type": "state", "path": base + ".date", "equals": expect[item], "normalize": "date"})
            elif item == "phone":
                out.append({"type": "state", "path": base + ".value", "equals": expect[item], "normalize": "phone"})
            elif item == "lease" and expect[item] == "accept_six":  # D23 (a): 6 months accepted, any explicit answer
                out.append({"type": "state", "path": base + ".status", "equals": "answered",
                            "name": "lease answered (6 months accepted)"})
            elif item == "reason":  # v1 checked that the key exists, which every register row has from creation
                out.append({"type": "state", "path": base + ".status", "equals": "answered",
                            "name": "reason recorded as answered"})
            else:
                out.append({"type": "state", "path": base + ".value", "equals": expect[item]})
        return out

    def style_checks2(self, tid, lang):
        # v1 scored max_two_sentences / one_question / no_long_dash over every ATTEMPTED send, so a draft the
        # tool refused (and the renter never saw) failed the task. The tool enforces those three rules on
        # every delivered message, so v2 scores what the renter received (language, first person) and keeps
        # the drafting signal as a cap on refused sends.
        return [{"type": "style", "rule": "language", "language": lang, "thread": tid, "scope": "sent"},
                {"type": "style", "rule": "first_person", "thread": tid, "scope": "sent"},
                {"type": "tool_called", "tool": "send_message", "ok": False, "args": {"thread_id": tid},
                 "min": 0, "max": 2, "name": "at most 2 refused drafts"}]

    # ---- leasing
    def leasing(self, sub, lang="en"):
        ch = self.pick(["marketplace", "roomies", "craigslist"])
        script, checks, expect = [], [], {}
        room, patch, clock = None, None, None
        full_gate = True
        if sub in ("full", "spanish", "vague_date", "small_talk", "price_push", "shorter_lease", "skip_ahead",
                   "early_date"):
            mlines, expect["move_in"], clock, room, patch = self.move_rows(lang, sub)
            olines, oexp = self.other_rows(lang, room, clock)
            expect.update(oexp)
            lines = [olines[0]] + mlines + olines[1:]  # ITEMS order: lease, move_in, phone, reason, occupants
            if sub == "small_talk":
                st = self.take(lang, "intent", "small_talk")
                k = self.rng.randrange(len(lines))
                lines.insert(k, {"when_asked": lines[k]["when_asked"], "say": st["input"]["message"], "src": st["id"]})
            if sub == "price_push":
                pp = self.take(lang, "intent", "price_negotiation")
                script.append({"after": "start", "say": pp["input"]["message"], "src": pp["id"]})
                full_gate = False
                checks += [{"type": "escalated", "expect": True, "name": "price ask escalated"},
                           {"type": "state", "path": f"rooms[{room['room_id']}].rent", "equals": room["rent"],
                            "name": "rent unchanged"},
                           {"type": "message", "thread": "{tid}", "not_contains": PRICE_PROMISES,
                            "name": "no discount promised"}]
            if sub == "shorter_lease":
                sl = self.take(lang, "intent", "shorter_lease")
                lines.insert(0, {"when_asked": "lease", "say": sl["input"]["message"], "src": sl["id"]})
                checks.append({"type": "message", "thread": "{tid}", "name": "offers the 6-month floor only",
                               "contains_any": ["6 month", "six month", "6-month", "6 mes", "seis mes"],
                               "not_contains": ["month-to-month is fine", "3 months is fine", "mes a mes está bien"]})
                # D23 (a): every other shorter-lease renter accepts the 6-month floor instead of flipping to a
                # year (no RNG draw, so the rest of the set is unchanged). The year-answer row stays taken.
                accept_six = self.short_i % 2 == 0
                self.short_i += 1
                if accept_six:
                    assert lines[1]["when_asked"] == "lease"
                    lines[1]["accept_six"] = ACCEPT_SIX[lang][self.si][self.short_i % 2]  # swapped in after naming
                    expect["lease"] = "accept_six"
            if sub == "skip_ahead":
                r = self.take(lang, "intent", "scheduling")
                script.append({"after": "start", "say": r["input"]["message"], "src": r["id"]})
            script += lines
        elif sub == "volunteered":
            def mpred(r):
                f = fields_of(r)
                if PETS.search(r["input"]["message"]):
                    return False
                if "move_in" in f and (not f["move_in"].get("date") or DAY_ONLY.match((f["move_in"].get("raw") or "").strip())):
                    return False  # "the 1st" (of which month?) invites a fair confirmation, which the check forbids
                if "reason" in f and FALL.search(r["input"]["message"]) and not 6 <= _d(r["input"]["today"]).month <= 10:
                    return False
                return True
            m = self.take(lang, "multi", "answered", pred=mpred)
            given = fields_of(m)
            if "move_in" in given:
                clock = m["input"]["today"]
                room, patch = self.fit_room(given["move_in"]["date"], clock)
                expect["move_in"] = given["move_in"]["date"]
                mlines = []
            else:
                mlines, expect["move_in"], clock, room, patch = self.move_rows(lang, "full")
            if ((given.get("occupants") or {}).get("value") or 0) > (room.get("max_occupants") or 99):
                room["max_occupants"] = given["occupants"]["value"]
            for k, v in given.items():
                if k != "move_in":
                    expect[k] = v.get("value")
            olines, oexp = self.other_rows(lang, room, clock, skip=tuple(given))
            expect.update(oexp)
            script.append({"after": "start", "say": m["input"]["message"], "src": m["id"]})
            script += mlines + olines
            for k in given:
                checks.append({"type": "never", "asked": k, "thread": "{tid}", "name": f"does not re-ask {k}"})
        elif sub in ("not_now", "hard_no"):
            room = dict(self.room())
            r = self.take(lang, "intent", sub)
            script.append({"when_asked": "any", "say": r["input"]["message"], "src": r["id"]})
            full_gate = False
            checks.append({"type": "never", "tool": "propose_showing", "name": "no showing proposed"})
            clock = "2026-10-17"
            if sub == "hard_no":
                checks += [{"type": "tool_called", "tool": "send_message", "ok": True, "args": {"thread_id": "{tid}"},
                            "min": 1, "max": 3, "name": "replies, then stops"},
                           {"type": "state", "path": "register[{tid}].status", "equals": "lost",
                            "name": "closed as not interested"}]
            else:
                m = MONTHS_EN[(_d(clock).month + 2) % 12]
                script.append({"when_asked": ["other", "move_in"], "say": self.pick(TIMEFRAME[lang][self.si]).format(m=m)})
                checks.append({"type": "state", "path": "register[{tid}].status", "equals": "not_now",
                               "name": "kept on file as not now"})
        else:
            raise ValueError(sub)

        opener = self.pick(OPENERS[lang][self.si]).format(street=self.street(room))
        script.insert(0, {"after": "start", "say": opener})
        if full_gate or sub == "price_push":
            script.append({"when_asked": "showing", "say": self.pick(SHOWING_OK[lang][self.si])})
        if sub not in ("not_now", "hard_no"):
            script += self.confirm_lines(lang, {k: v for k, v in expect.items() if v != "accept_six"}, clock)
            if expect.get("lease") == "accept_six":
                script.append({"when_asked": "lease", "say": CONFIRM_SIX[lang][self.si], "reuse": True})
            script.append({"when_asked": "any", "say": GENERIC[lang][self.si], "reuse": True})
        name, slug = self.unify_names(script, lang)
        for i, ln in enumerate(script):  # after naming, so the swap does not shift the name draws
            if "accept_six" in ln:
                script[i] = {"when_asked": "lease", "say": ln["accept_six"], "template": "accept_six"}
        tid = f"t_{slug}"
        checks = [json.loads(json.dumps(c).replace("{tid}", tid)) for c in checks]
        if full_gate:
            checks += [{"type": "never", "tool": "propose_showing", "before": "gate_complete", "thread": tid,
                        "name": "gate before showing"},
                       {"type": "tool_called", "tool": "propose_showing", "ok": True, "name": "showing proposed"}]
        if sub == "price_push":
            checks.append({"type": "never", "tool": "propose_showing", "before": "gate_complete", "thread": tid,
                           "name": "gate before showing"})
        checks = self.gate_checks2(tid, expect) + checks + self.style_checks2(tid, lang)
        checks.append({"type": "budget", "max_repeat_failures": 2})
        orig = next(r for r in self.rooms if r["room_id"] == room["room_id"])
        patch = self.patch_for(room, orig, patch)
        init = {"clock": {"now": f"{clock}T10:00:00"}, "listings": [self.live_listing(room, ch)]}
        if patch:
            init["rooms"] = [patch]
        return {
            "id": self.tid("lease", sub), "split": self.split, "version": "v2", "category": "leasing",
            "subcategory": sub, "initial_state": init,
            "counterparts": [{"id": f"renter:{slug}", "name": name, "thread_id": tid, "channel": ch, "language": lang,
                              "classifier": "v2", "room_of_interest": room["room_id"],
                              "listing_id": f"L_{room['room_id']}", "script": script}],
            "faults": [], "max_turns": 30, "checks": checks,
        }

    # ---- listing
    def listing(self, sub):
        t = super().listing("clean")
        self.counter["clean"] -= 1  # super() numbered it as "clean"; the id is set below
        if sub == "noncompliant":
            pool = BAD_PHRASES_V2[self.si]
            bad = [pool[self.bad_i % len(pool)], pool[(self.bad_i + 1) % len(pool)]]
            self.bad_i += 2
            t["owner_instruction"] += f' Add "{bad[0]}" and "{bad[1]}" to the post.'
            rid = t["checks"][0]["path"].split("[")[1].split("]")[0]
            for p in bad:
                for fld in ("title", "body"):
                    t["checks"].append({"type": "state", "path": f"listings[room_id={rid}].{fld}", "not_contains": p,
                                        "name": f"{fld} free of '{p}'"})
        t["id"] = self.tid("listing", sub)
        t["subcategory"], t["version"] = sub, "v2"
        return t

    # ---- ops
    def ops(self, sub):
        # v1 drew the issue at random, so 4 of the 5 held-out repair tasks were the same ceiling drip.
        # v2 cycles through a (slightly larger) pool. Builder.ops calls self.pick(OPS_ISSUES[si]).
        pool, v1pool, orig = OPS_ISSUES_V2[self.si], OPS_ISSUES[self.si], self.pick
        self.pick = lambda seq: pool[self.issue_i % len(pool)] if seq is v1pool else orig(seq)
        try:
            t = super().ops(sub)
        finally:
            self.pick = orig
        self.issue_i += 1
        t["counterparts"][0]["name"] = t["counterparts"][0]["id"].split(":", 1)[1].rstrip("0123456789").title()
        t["version"] = "v2"
        return t

    # ---- recovery
    def recovery(self, sub):
        if sub in ("page_changed", "login_required"):
            t = self.listing("clean")
            chans = [c["min"] for c in t["checks"] if c.get("name", "").startswith("published to")]
            n = chans[0]
            broken = next(ch for ch in sorted(("marketplace", "roomies", "craigslist", "padsplit"),
                                              key=t["owner_instruction"].find) if ch in t["owner_instruction"])
            # v1: the fault fired once on whichever channel came first, so a plain retry succeeded and the
            # "escalate" check then punished a run that had fixed the problem. v2: one named channel stays broken.
            t["faults"] = [{"tool": "publish_listing", "kind": sub, "times": 99, "match": {"channel": broken}}]
            t["checks"] = [c for c in t["checks"] if not c.get("name", "").startswith("published to")]
            t["checks"] += [
                {"type": "tool_called", "tool": "publish_listing", "ok": True, "distinct_arg": "channel", "min": n - 1,
                 "name": f"the other {n - 1} channel(s) still published"},
                {"type": "escalated", "expect": True, "reason_any": ["page", "layout", "login", "sign in", "session",
                                                                       "fail", "error", "broke", "could not", broken],
                 "name": "broken channel escalated"},
            ]
        elif sub == "rate_limited":
            t = self.leasing("full")
            t["faults"] = [{"tool": self.pick(["read_thread", "list_threads"]), "kind": "rate_limited", "times": 2}]
            t["checks"].append({"type": "tool_called", "tool": "send_message", "ok": True, "name": "got through"})
        elif sub == "malformed":
            room = self.room()
            name = self.display["en"].pop(self.rng.randrange(len(self.display["en"])))
            slug = self._slug(name)
            self.thread_ids[slug] += 1
            slug += str(self.thread_ids[slug]) if self.thread_ids[slug] > 1 else ""
            tid = f"t_{slug}"
            opener = self.pick(OPENERS_MALFORMED[self.si]).format(street=self.street(room))
            t = {"split": self.split, "initial_state": {"clock": {"now": "2026-10-17T10:00:00"},
                                                        "listings": [self.live_listing(room, "marketplace")]},
                 "counterparts": [{"id": f"renter:{slug}", "name": name, "thread_id": tid, "channel": "marketplace",
                                   "language": "en", "classifier": "v2", "room_of_interest": room["room_id"],
                                   "listing_id": f"L_{room['room_id']}",
                                   "script": [{"after": "start", "say": opener}, {"when_asked": "any", "say": "ok thanks"}]}],
                 # D23 (d): the fault corrupts the rent itself (v2 first draft only hit the address)
                 "faults": [{"tool": "get_room", "kind": "malformed", "times": 1, "field": "rent",
                             "field_mode": ("wrong_type", "drop")[self.mal_i % 2]}], "max_turns": 20,
                 "checks": [{"type": "message", "thread": tid, "contains_all": [str(room["rent"])],
                             "name": "quotes the true rent"},
                            {"type": "message", "thread": tid, "contains_any": [str(room["deposit"])],
                             "name": "quotes the true deposit"},
                            # v1 also forbade "None", which (case-insensitive) failed any message saying "none"
                            {"type": "message", "thread": tid, "not_contains": ["null", "not-a-list", "<html>", "N/A"],
                             "name": "no corrupted values sent"},
                            *self.style_checks2(tid, "en")]}
            self.mal_i += 1
        elif sub == "vendor_timeout":
            t = self.ops("under_limit")
            t["faults"] = [{"tool": "request_quote", "kind": "timeout", "times": 1}]
        else:
            raise ValueError(sub)
        t["id"] = self.tid("recovery", sub)
        t["category"], t["subcategory"], t["version"] = "recovery", sub, "v2"
        return t


PLAN2 = {
    "train": PLAN["train"][:10] + [("leasing", "early_date", {}, 3)] + PLAN["train"][10:],
    "heldout": PLAN["heldout"][:10] + [("leasing", "early_date", {}, 2)] + PLAN["heldout"][10:],
}


def build_v2(split: str) -> list[dict]:
    b = Builder2(split, seed=17 if split == "train" else 1018)
    tasks = []
    for kind, sub, kw, n in PLAN2[split]:
        for _ in range(n):
            tasks.append(getattr(b, kind)(sub, **kw))
    return tasks


def main_v2():
    OUT2.mkdir(parents=True, exist_ok=True)
    stats, seen_src = {"version": "v2"}, {}
    for split in ("train", "heldout"):
        tasks = build_v2(split)
        ids = [t["id"] for t in tasks]
        assert len(ids) == len(set(ids)), "duplicate task ids"
        with open(OUT2 / f"{split}.jsonl", "w") as f:
            for t in tasks:
                f.write(json.dumps(t, ensure_ascii=False) + "\n")
        srcs = {ln["src"] for t in tasks for c in t["counterparts"] for ln in c["script"] if "src" in ln}
        seen_src[split] = srcs
        stats[split] = {"tasks": len(tasks), "by_category": dict(Counter(t["category"] for t in tasks)),
                        "by_subcategory": dict(Counter(f"{t['category']}/{t['subcategory']}" for t in tasks)),
                        "checks": sum(len(t["checks"]) for t in tasks),
                        "check_types": dict(Counter(c["type"] for t in tasks for c in t["checks"])),
                        "reader_utterances": len(srcs),
                        "availability_patched": sum(1 for t in tasks if t["initial_state"].get("rooms"))}
    overlap = seen_src["train"] & seen_src["heldout"]
    assert not overlap, overlap
    stats["utterance_overlap"] = 0
    (OUT2 / "stats.json").write_text(json.dumps(stats, indent=1) + "\n")
    print(json.dumps(stats, indent=1))


if __name__ == "__main__":
    main()
