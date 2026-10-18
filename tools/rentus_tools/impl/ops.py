"""Ops tools: web_search, fetch_page, find_vendors, create_job, request_quote, book_vendor.
Sandbox web = the vendor directory fixtures. `responds` and `quote_range` are hidden simulator truth."""
from __future__ import annotations

import copy
import hashlib
import re
from datetime import timedelta

from ..core import tool
from ..errors import ToolError
from ._util import need

WEB = "https://sandbox.vendors.local"
TRADE_ALIASES = {
    "plumber": "plumber", "plumbing": "plumber", "plumbers": "plumber", "drain": "plumber", "leak": "plumber",
    "water heater": "plumber", "fontanero": "plumber", "plomero": "plumber",
    "hvac": "hvac", "heating": "hvac", "ac": "hvac", "a/c": "hvac", "air conditioning": "hvac", "furnace": "hvac",
    "heat": "hvac", "heat pump": "hvac",
    "electrician": "electrician", "electrical": "electrician", "electric": "electrician", "electricista": "electrician",
    "wiring": "electrician", "outlet": "electrician", "breaker": "electrician",
}
PUBLIC_FIELDS = ("vendor_id", "name", "trade", "phone", "rating", "service_area", "eta_days")
SEVERITY_FACTOR = {"low": 0.0, "medium": 0.25, "high": 0.5, "emergency": 0.85}


def norm_trade(t: str) -> str | None:
    t = t.strip().lower()
    if t in TRADE_ALIASES:
        return TRADE_ALIASES[t]
    for k in sorted(TRADE_ALIASES, key=len, reverse=True):
        if re.search(rf"\b{re.escape(k)}\b", t):
            return TRADE_ALIASES[k]
    return None


def _public(v: dict) -> dict:
    return {k: v.get(k) for k in PUBLIC_FIELDS}


@tool("web_search")
def web_search(world, query: str):
    q = query.lower()
    trade = norm_trade(q)
    zips = set(re.findall(r"\b\d{5}\b", q))
    words = set(re.findall(r"[a-z]{3,}", q)) - {"near", "the", "and", "for", "best", "durham", "raleigh", "chapel", "hill",
                                                "cheap", "local", "service", "services", "company", "repair"}
    results = []
    for v in world.vendors:
        name_hit = bool(words & set(re.findall(r"[a-z]{3,}", v["name"].lower())))
        if not (name_hit or (trade and v["trade"] == trade)):
            continue
        if zips and not zips & set(v.get("service_area", [])):
            continue
        results.append({"title": f"{v['name']} | {v['trade']} | Durham NC", "url": f"{WEB}/{v['vendor_id'].lower()}",
                        "snippet": f"{v['name']}, rated {v['rating']}/5. Serves {len(v.get('service_area', []))} Triangle ZIPs. Call {v['phone']}."})
    results.sort(key=lambda r: r["url"])
    return {"results": results[:10], "query": query}


@tool("fetch_page")
def fetch_page(world, url: str):
    m = re.fullmatch(rf"{re.escape(WEB)}/(v\d+)/?", url.strip(), flags=re.IGNORECASE)
    v = world.get("vendors", m.group(1).upper()) if m else None
    if v is None:
        raise ToolError("NOT_FOUND", f"page not found: {url}", hint="use a URL returned by web_search")
    text = (f"{v['name']}\nTrade: {v['trade']}\nPhone: {v['phone']}\nRating: {v['rating']} out of 5\n"
            f"Service area ZIPs: {', '.join(v.get('service_area', []))}\nTypical scheduling lead time: {v.get('eta_days', 2)} day(s)\n"
            f"{v.get('about', '')}\nQuotes on request. Vendor id: {v['vendor_id']}")
    return {"url": url, "text": text}


ZIP_HOW = ("pass job_id from create_job (the job carries the property's zip), or a 5-digit zip from the room record "
           "(get_room / list_rooms); never guess a zip")


@tool("find_vendors")
def find_vendors(world, trade: str, zip: str | None = None, job_id: str | None = None):
    t = norm_trade(trade)
    if t is None:
        raise ToolError("INVALID_ARGS", f"unknown trade {trade!r}", hint="trades: plumber, hvac, electrician")
    job_zip = None
    if job_id is not None:
        job = need(world, "jobs", job_id, "job")
        job_zip = job.get("zip")
        if not job_zip and zip is None:
            raise ToolError("INVALID_ARGS", f"job {job_id} has no zip: its property {job.get('property')!r} matched no room",
                            hint="find the room with list_rooms (its address or area) or get_room, then call "
                                 "find_vendors with that room's zip")
        if job_zip and zip is not None and zip != job_zip:
            raise ToolError("INVALID_ARGS", f"zip {zip} does not match job {job_id}'s property zip {job_zip}",
                            hint="pass job_id alone and the job's zip is used", details={"job_zip": job_zip})
    if zip is None and job_zip is None:
        raise ToolError("INVALID_ARGS", "find_vendors needs a zip or a job_id", hint=ZIP_HOW)
    z = zip or job_zip
    out = [_public(v) for v in world.vendors if v["trade"] == t and z in v.get("service_area", [])]
    out.sort(key=lambda v: (-v["rating"], v["vendor_id"]))
    res = {"vendors": out, "trade": t, "zip": z}
    if job_id is not None:
        res["job_id"] = job_id
    return res


def _norm_addr(s: str) -> str:
    s = re.sub(r"\(.*?\)", " ", s.lower())
    return " ".join(re.findall(r"[a-z0-9]+", s))


def resolve_property(world, prop: str) -> dict | None:
    """Where a create_job `property` is: a room id, a street address of a room, or text with a 5-digit zip.
    Returns {room_id, address, zip, area} (room_id None for a multi-room address) or None when nothing
    matches or the matches disagree on the zip."""
    p = prop.strip()
    room = world.get("rooms", p) or world.get("rooms", p.upper())
    if room:
        return {"room_id": room["room_id"], "address": room.get("address") or room.get("address_public"),
                "zip": room.get("zip"), "area": room.get("area")}
    q = _norm_addr(p)
    hits = []
    if q:
        for r in world.rooms:
            addr = r.get("address") or r.get("address_public") or ""
            street, full = _norm_addr(addr.split(",")[0]), _norm_addr(addr)
            if street and (f" {street} " in f" {q} " or (len(q) >= 6 and f" {q} " in f" {full} ")):
                hits.append(r)
    if hits:
        if len({r.get("zip") for r in hits}) != 1:
            return None
        r = hits[0]
        return {"room_id": r["room_id"] if len(hits) == 1 else None,
                "address": r.get("address") or r.get("address_public"), "zip": r.get("zip"), "area": r.get("area")}
    m = re.search(r"\b(\d{5})\b", p)
    return {"room_id": None, "address": None, "zip": m.group(1), "area": None} if m else None


@tool("create_job")
def create_job(world, property: str, issue: str, severity: str):
    if not issue.strip() or not property.strip():
        raise ToolError("INVALID_ARGS", "create_job: property and issue must not be empty")
    loc = resolve_property(world, property) or {}
    job = {"job_id": world.next_id("J"), "property": property, "room_id": loc.get("room_id"),
           "address": loc.get("address"), "zip": loc.get("zip"), "area": loc.get("area"), "issue": issue,
           "severity": severity, "status": "open", "vendor_id": None, "cost": None, "created_at": world.clock["now"]}
    world.jobs.append(job)
    out = {"job": copy.deepcopy(job)}
    if job["zip"]:
        out["next"] = f"find_vendors with the trade and job_id {job['job_id']} (zip {job['zip']})"
    else:
        out["hint"] = ("the property matched no room, so the job has no zip; find the room with list_rooms or "
                       "get_room and call find_vendors with its zip")
    return out


def quote_amount(vendor: dict, job: dict) -> int:
    lo, hi = vendor["quote_range"]
    h = int(hashlib.sha256(f"{vendor['vendor_id']}|{job['job_id']}|{job['issue']}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    frac = min(1.0, SEVERITY_FACTOR.get(job.get("severity"), 0.25) * 0.6 + h * 0.4)
    return int(round((lo + (hi - lo) * frac) / 5.0) * 5)


@tool("request_quote")
def request_quote(world, vendor_id: str, job_id: str, description: str):
    vendor = need(world, "vendors", vendor_id, "vendor", "find_vendors")
    job = need(world, "jobs", job_id, "job")
    if job["status"] in ("booked", "done", "cancelled"):
        raise ToolError("CONFLICT", f"job {job_id} is {job['status']}")
    for q in world.quotes:
        if q["vendor_id"] == vendor_id and q["job_id"] == job_id:
            return {"quote": copy.deepcopy(q), "existing": True}
    if not vendor.get("responds", True):
        raise ToolError("TIMEOUT", f"{vendor['name']} did not respond to the quote request", retryable=False,
                        hint="try another vendor from find_vendors")
    q = {"quote_id": world.next_id("Q"), "vendor_id": vendor_id, "vendor_name": vendor["name"], "job_id": job_id,
         "amount": quote_amount(vendor, job), "description": description,
         "eta": (world.now() + timedelta(days=vendor.get("eta_days", 2))).date().isoformat(), "status": "offered",
         "created_at": world.clock["now"]}
    world.quotes.append(q)
    if job["status"] == "open":
        job["status"] = "quoting"
    return {"quote": copy.deepcopy(q)}


@tool("book_vendor")
def book_vendor(world, quote_id: str):
    q = need(world, "quotes", quote_id, "quote")
    job = need(world, "jobs", q["job_id"], "job")
    if job["status"] == "booked":
        raise ToolError("CONFLICT", f"job {job['job_id']} is already booked with {job['vendor_id']}")
    if q["status"] != "offered":
        raise ToolError("CONFLICT", f"quote {quote_id} is {q['status']}")
    limit = world.policy.get("spend_limit_usd")
    if limit is not None and q["amount"] > limit:
        raise ToolError("BUDGET_EXCEEDED", f"quote {quote_id} is ${q['amount']}, above the ${limit} spending limit",
                        hint="book a cheaper quote, or escalate_to_owner with this quote for approval",
                        details={"amount": q["amount"], "limit": limit})
    q["status"] = "accepted"
    for other in world.quotes:
        if other["job_id"] == job["job_id"] and other["quote_id"] != quote_id and other["status"] == "offered":
            other["status"] = "declined"
    job.update({"status": "booked", "vendor_id": q["vendor_id"], "cost": q["amount"], "quote_id": quote_id,
                "scheduled_for": q["eta"], "booked_at": world.clock["now"]})
    return {"job": copy.deepcopy(job)}
