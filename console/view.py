"""Turn a world dict (contract section 3) into what the page renders. Tolerant of shape drift."""
from __future__ import annotations

CHANNELS = ["marketplace", "roomies", "craigslist", "padsplit", "sms", "email"]
GATE = ["lease", "move_in", "phone", "reason", "occupants"]


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
            "renter_id": t.get("renter_id"), "language": t.get("language"),
            "messages": [{"from": m.get("from"), "text": m.get("text"), "ts": m.get("ts")}
                         for m in (t.get("messages") or [])]})

    register = []
    for r in w.get("register") or []:
        gate = r.get("gate") or {}
        register.append({"renter_id": r.get("renter_id"), "name": r.get("name") or r.get("renter_id"),
                         "status": r.get("status"), "phone": r.get("phone"), "channel": r.get("channel"),
                         "gate": {g: {"state": _gate_state(gate.get(g)), "value": _gate_value(gate.get(g))}
                                  for g in GATE}})

    jobs = w.get("jobs") or []
    policy = w.get("policy") or {}
    spent = sum(float(j.get("cost") or 0) for j in jobs if j.get("status") in ("booked", "done", "completed"))
    escalations = []
    for e in w.get("escalations") or []:
        e = dict(e)
        ref = e.get("thread_id") or e.get("job_id") or e.get("ref_id") or ""
        if (e.get("reason") or "").strip() in (ref, e.get("ref_id") or "") and e.get("draft"):
            e["reason"], e["draft"] = e["draft"], None  # the model put the id in reason
        escalations.append(e)
    return {"lanes": lanes, "register": register, "listings": listings,
            "escalations": escalations, "jobs": jobs, "quotes": w.get("quotes") or [],
            "vendors": {v.get("vendor_id"): v.get("name") for v in w.get("vendors") or []},
            "calendar": w.get("calendar") or [],
            "spend": {"spent": spent, "limit": policy.get("spend_limit_usd")},
            "faults": [f for f in (w.get("faults") or []) if (f.get("times", 1) or 0) > 0],
            "clock": w.get("clock")}
