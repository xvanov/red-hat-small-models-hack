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


@tool("find_vendors")
def find_vendors(world, trade: str, zip: str):
    t = norm_trade(trade)
    if t is None:
        raise ToolError("INVALID_ARGS", f"unknown trade {trade!r}", hint="trades: plumber, hvac, electrician")
    out = [_public(v) for v in world.vendors if v["trade"] == t and zip in v.get("service_area", [])]
    out.sort(key=lambda v: (-v["rating"], v["vendor_id"]))
    return {"vendors": out, "trade": t, "zip": zip}


@tool("create_job")
def create_job(world, property: str, issue: str, severity: str):
    if not issue.strip() or not property.strip():
        raise ToolError("INVALID_ARGS", "create_job: property and issue must not be empty")
    room = world.get("rooms", property)
    job = {"job_id": world.next_id("J"), "property": property, "zip": (room or {}).get("zip"), "issue": issue,
           "severity": severity, "status": "open", "vendor_id": None, "cost": None, "created_at": world.clock["now"]}
    world.jobs.append(job)
    return {"job": copy.deepcopy(job)}


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
