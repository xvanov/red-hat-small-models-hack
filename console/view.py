"""Turn a world dict (contract section 3) into what the page renders. Tolerant of shape drift."""
from __future__ import annotations

CHANNELS = ["marketplace", "roomies", "craigslist", "padsplit", "sms", "email"]
GATE = ["lease", "move_in", "phone", "reason", "occupants"]


# register status -> pipeline column (docs/spec/concierge.md 5.2)
STAGE = {"new": "inquiry", "qualifying": "inquiry", "escalated": "inquiry", "qualified": "qualified",
         "showing_proposed": "showing", "showing_confirmed": "showing", "applied": "application",
         "leased": "application", "not_now": "parked", "lost": "closed"}
ACTIVE = {"new", "qualifying", "escalated", "qualified", "showing_proposed", "showing_confirmed", "applied"}
QUALIFIED = {"qualified", "showing_proposed", "showing_confirmed", "applied"}
BAND = 150  # docs/spec/concierge.md 5.3: $150-wide budget buckets


def _first(x):
    if isinstance(x, dict):
        x = x.get("resolved") or x.get("raw")
    if isinstance(x, (list, tuple)):
        x = x[0] if x else None
    return x


def clusters(w: dict) -> list[dict]:
    """Demand clusters (docs/spec/concierge.md 5.3): primary area + type + $150 budget band, distinct active people.
    WATCH at 3+ active, SUPPLY SIGNAL at 5+ qualified. When a person stated no criteria, the room they asked
    about stands in for them and the cluster is marked inferred."""
    rooms = {r.get("room_id"): r for r in w.get("rooms") or []}
    lst_room = {l.get("listing_id"): l.get("room_id") for l in w.get("listings") or []}
    out: dict[tuple, dict] = {}
    for r in w.get("register") or []:
        if (r.get("status") or "new") not in ACTIVE:
            continue
        wants = r.get("wants") or {}
        area, typ, budget = _first(wants.get("areas") or wants.get("area")), wants.get("type"), wants.get("budget_max_usd")
        inferred = False
        if not (area and budget):
            room = rooms.get(lst_room.get(r.get("listing_of_interest"))) or {}
            if not room:
                continue
            area = area or room.get("area")
            typ = typ or ("room, private bath" if room.get("private_bath") else room.get("type") or "room")
            budget = budget or room.get("rent")
            inferred = True
        try:
            lo = int(float(budget) // BAND * BAND)
        except (TypeError, ValueError):
            continue
        k = (str(area), str(typ or "room"), lo)
        c = out.setdefault(k, {"area": k[0], "type": k[1], "band": [lo, lo + BAND - 1], "people": 0,
                               "qualified": 0, "names": [], "inferred": False})
        c["people"] += 1
        c["qualified"] += (r.get("status") in QUALIFIED)
        c["names"].append(r.get("name") or r.get("renter_id"))
        c["inferred"] = c["inferred"] or inferred
    res = []
    for c in out.values():
        c["level"] = "signal" if c["qualified"] >= 5 else "watch" if c["people"] >= 3 else "forming"
        res.append(c)
    return sorted(res, key=lambda c: (-c["qualified"], -c["people"]))


def _gate_state(v) -> str:
    if v is None or v is False:
        return "none"
    if v is True:
        return "ok"
    if isinstance(v, dict):
        st = v.get("status")
        if st in ("answered", "exception", "ok", "done"):
            return "ok"
        if st == "vague":
            return "vague"
        if st == "no":
            return "no"
        if st in (None, "absent"):
            return "ok" if (v.get("value") not in (None, "") or v.get("date")) and st is None else "none"
        return "none"
    return "ok" if v not in ("", None) else "none"


def _gate_value(v):
    if isinstance(v, dict):
        return v.get("date") or v.get("value") if v.get("value") is not True else "yes"
    return v if v is not True else "yes"


def build_view(w: dict) -> dict:
    w = w or {}
    lanes = {c: {"posts": [], "threads": []} for c in CHANNELS}
    for ch in (w.get("channels") or {}):
        lanes.setdefault(ch, {"posts": [], "threads": []})

    listings = w.get("listings") or []
    for lst in listings:
        for ch, post in (lst.get("channels") or {}).items():
            post = post if isinstance(post, dict) else {"status": str(post)}
            lanes.setdefault(ch, {"posts": [], "threads": []})["posts"].append({
                "listing_id": lst.get("listing_id"), "title": lst.get("title"), "price": lst.get("price"),
                "status": post.get("status") or lst.get("status"), "url": post.get("url"),
                "screenshot": post.get("screenshot"), "post_id": post.get("post_id")})

    threads = list(w.get("threads") or [])
    seen = {t.get("thread_id") for t in threads}
    for ch, c in (w.get("channels") or {}).items():
        for t in (c or {}).get("threads", []) if isinstance(c, dict) else []:
            if isinstance(t, dict) and t.get("thread_id") not in seen:
                threads.append({**t, "channel": t.get("channel", ch)})
                seen.add(t.get("thread_id"))
    for t in threads:
        ch = t.get("channel") or "marketplace"
        lanes.setdefault(ch, {"posts": [], "threads": []})["threads"].append({
            "thread_id": t.get("thread_id"), "renter_name": t.get("renter_name") or t.get("renter_id"),
            "renter_id": t.get("renter_id"), "language": t.get("language"), "kind": t.get("kind") or "renter",
            "listing_id": t.get("listing_id"), "room_id": t.get("room_id"),
            "messages": [{"from": m.get("from"), "text": m.get("text"), "ts": m.get("ts")}
                         for m in (t.get("messages") or [])]})

    register = []
    for r in w.get("register") or []:
        gate = r.get("gate") or {}
        register.append({"renter_id": r.get("renter_id"), "name": r.get("name") or r.get("renter_id"),
                         "status": r.get("status"), "phone": r.get("phone"), "channel": r.get("channel"),
                         "thread_ids": r.get("thread_ids") or [], "language": r.get("language"),
                         "wants": r.get("wants") or {}, "listing_of_interest": r.get("listing_of_interest"),
                         "reconnect_at": r.get("reconnect_at"), "stage": STAGE.get(r.get("status") or "new", "inquiry"),
                         "gate": {g: {"state": _gate_state(gate.get(g)), "value": _gate_value(gate.get(g))}
                                  for g in GATE}})

    jobs = w.get("jobs") or []
    policy = w.get("policy") or {}
    spent = sum(float(j.get("cost") or 0) for j in jobs if j.get("status") in ("booked", "done", "completed"))
    escalations = []
    for e in w.get("escalations") or []:
        e = dict(e)
        ref = e.get("thread_id") or e.get("job_id") or e.get("ref_id") or ""
        if (e.get("reason") or "").strip() in (ref, e.get("ref_id") or "", e.get("ref_type") or "", "thread", "job") and e.get("draft"):
            e["reason"], e["draft"] = e["draft"], None  # the model put the id in reason
        escalations.append(e)
    return {"lanes": lanes, "register": register, "listings": listings,
            "escalations": escalations, "jobs": jobs, "quotes": w.get("quotes") or [],
            "vendors": {v.get("vendor_id"): v.get("name") for v in w.get("vendors") or []},
            "calendar": w.get("calendar") or [],
            "spend": {"spent": spent, "limit": policy.get("spend_limit_usd")},
            "faults": [f for f in (w.get("faults") or []) if (f.get("times", 1) or 0) > 0],
            "clusters": clusters(w), "supply_signals": w.get("supply_signals") or [],
            "rooms": {"total": len(w.get("rooms") or []),
                      "listed": len({l.get("room_id") for l in listings if l.get("status") == "live"})},
            "clock": w.get("clock")}
