"""Tool schemas: the single source of truth for every tool in contracts/tools.md section 4.

`PARAMS` holds each tool's JSON-Schema arguments (types, enums, required). `DESCRIPTIONS` holds the
wording, in two variants ("verbose" and "terse"), because tool descriptions are an ablation target.
`tool_schemas(variant)` combines them into OpenAI function-calling format; `TOOLS` is the verbose set.

Descriptions keyed "<tool>" describe the tool; "<tool>.<param>" describe a parameter. A variant that
lacks a parameter description simply omits it.
"""
from __future__ import annotations

import copy

S = {"type": "string"}
DATE = {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"}
DATETIME = {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?$"}
POST_CHANNEL = {"type": "string", "enum": ["marketplace", "roomies", "craigslist", "padsplit"]}
ANY_CHANNEL = {"type": "string", "enum": ["marketplace", "roomies", "craigslist", "padsplit", "sms", "email"]}
GATE_ITEM = {"type": "string", "enum": ["lease", "move_in", "phone", "occupants", "reason"]}


def _obj(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


PARAMS: dict[str, dict] = {
    # Inventory
    "list_rooms": _obj({"available_by": DATE, "area": S}, []),
    "get_room": _obj({"room_id": S}, ["room_id"]),
    "update_room": _obj({"room_id": S, "fields": {"type": "object"}}, ["room_id", "fields"]),
    # Listings
    "create_listing": _obj({"room_id": S, "title": S, "body": S, "price": {"type": "number"}},
                           ["room_id", "title", "body", "price"]),
    "publish_listing": _obj({"listing_id": S, "channel": POST_CHANNEL}, ["listing_id", "channel"]),
    "update_listing": _obj({"listing_id": S, "fields": {"type": "object"}}, ["listing_id", "fields"]),
    "mark_filled": _obj({"listing_id": S}, ["listing_id"]),
    "get_listing_media": _obj({"room_id": S}, ["room_id"]),
    "check_listing_compliance": _obj({"text": S}, ["text"]),
    # Market
    "get_market_rent": _obj({"zip": {"type": "string", "pattern": r"^\d{5}$"}, "bedrooms": {"type": "integer", "minimum": 0}},
                            ["zip"]),
    # Inbox
    "list_threads": _obj({"channel": ANY_CHANNEL, "unanswered_only": {"type": "boolean"}}, []),
    "read_thread": _obj({"thread_id": S}, ["thread_id"]),
    "send_message": _obj({"thread_id": S, "text": S, "attachments": {"type": "array", "items": S}},
                         ["thread_id", "text"]),
    # Reader
    "read_reply": _obj({"thread_id": S, "text": S, "pending_item": GATE_ITEM}, []),
    # Register
    "upsert_renter": _obj({"thread_id": S, "fields": {"type": "object"}}, ["thread_id", "fields"]),
    "match_renters": _obj({"room_id": S}, ["room_id"]),
    # Calendar
    "find_showing_slots": _obj({"room_id": S, "date_from": DATE, "date_to": DATE}, ["room_id", "date_from", "date_to"]),
    "propose_showing": _obj({"renter_id": S, "room_id": S, "start": DATETIME}, ["renter_id", "room_id", "start"]),
    # Ops
    "web_search": _obj({"query": S}, ["query"]),
    "fetch_page": _obj({"url": S}, ["url"]),
    "find_vendors": _obj({"trade": S, "zip": {"type": "string", "pattern": r"^\d{5}$"}, "job_id": S}, ["trade"]),
    "request_quote": _obj({"vendor_id": S, "job_id": S, "description": S}, ["vendor_id", "job_id", "description"]),
    "book_vendor": _obj({"quote_id": S}, ["quote_id"]),
    "create_job": _obj({"property": S, "issue": S,
                        "severity": {"type": "string", "enum": ["low", "medium", "high", "emergency"]}},
                       ["property", "issue", "severity"]),
    # Owner
    "escalate_to_owner": _obj({"reason": S, "ref_id": S, "draft": S}, ["reason", "ref_id"]),
    "report_to_owner": _obj({"summary": S}, ["summary"]),
    # Concierge / demand capture (docs/spec/concierge.md). Not in the default tool list: exposed with
    # tool_schemas("concierge") so earlier configs and baselines see exactly the tools they always did.
    "listing_disclosure": _obj({"room_id": S, "thread_id": S}, []),
    "capture_demand": _obj({"thread_id": S, "criteria": {"type": "object"}, "listing_of_interest": S, "phone": S,
                            "email": S, "proxy": {"type": "boolean"}}, ["thread_id"]),
    "match_inventory": _obj({"renter_id": S}, ["renter_id"]),
    "search_external_rooms": _obj({"renter_id": S}, ["renter_id"]),
    "park_prospect": _obj({"renter_id": S, "reason": S, "timeframe": S}, ["renter_id", "reason"]),
    "log_followup": _obj({"renter_id": S, "event": {"type": "string", "enum": ["application_sent", "checkin_sent", "reply",
                                                                          "reconnect_sent", "applied", "closed", "placed"]},
                          "note": S}, ["renter_id", "event"]),
    "due_followups": _obj({"now": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2})?)?$"}}, []),
    "cluster_report": _obj({"as_of": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2})?)?$"},
                            "min_watch": {"type": "integer", "minimum": 1}, "min_signal": {"type": "integer", "minimum": 1}}, []),
    # Tenancy (owner decisions D29): ledger, payments, late-rent ladder, lease notices, payment plans,
    # maintenance triage, quotes side by side. Exposed with the concierge variant only.
    "get_ledger": _obj({"tenant_id": S, "thread_id": S}, []),
    "record_payment": _obj({"tenant_id": S, "thread_id": S, "amount": {"type": "number"}, "date": DATE, "method": S,
                            "note": S}, ["amount"]),
    "rent_ladder": _obj({"tenant_id": S, "thread_id": S,
                         "event": {"type": "string", "enum": ["warned", "reminder_sent", "assessed", "tenant_replied",
                                                              "followup_sent", "checkin_sent", "plan_sent", "escalated"]},
                         "promised_date": DATE, "note": S}, []),
    "send_notice": _obj({"tenant_id": S, "thread_id": S, "kind": {"type": "string", "enum": ["late_rent"]}}, []),
    "propose_payment_plan": _obj({"tenant_id": S, "thread_id": S,
                                  "shape": {"type": "string", "enum": ["split", "due_date_shift", "catch_up"]},
                                  "installments": {"type": "array", "items": {"type": "object"}},
                                  "proposed_by": {"type": "string", "enum": ["tenant", "agent"]}, "tenant_words": S,
                                  "new_due_day": {"type": "integer", "minimum": 1}, "paycheck_day": {"type": "integer", "minimum": 1}},
                                 ["shape", "installments"]),
    "triage_maintenance": _obj({"thread_id": S, "text": S}, ["thread_id"]),
    "compare_quotes": _obj({"job_id": S}, ["job_id"]),
}

TENANCY_TOOLS = ["get_ledger", "record_payment", "rent_ladder", "send_notice", "propose_payment_plan",
                 "triage_maintenance", "compare_quotes"]

CONCIERGE_TOOLS = ["listing_disclosure", "capture_demand", "match_inventory", "search_external_rooms", "park_prospect",
                   "log_followup", "due_followups", "cluster_report"]

GROUPS = {
    "inventory": ["list_rooms", "get_room", "update_room"],
    "listings": ["create_listing", "publish_listing", "update_listing", "mark_filled", "get_listing_media",
                 "check_listing_compliance"],
    "market": ["get_market_rent"],
    "inbox": ["list_threads", "read_thread", "send_message"],
    "reader": ["read_reply"],
    "register": ["upsert_renter", "match_renters"],
    "calendar": ["find_showing_slots", "propose_showing"],
    "ops": ["web_search", "fetch_page", "find_vendors", "request_quote", "book_vendor", "create_job"],
    "owner": ["escalate_to_owner", "report_to_owner"],
    "demand": CONCIERGE_TOOLS,
    "tenancy": TENANCY_TOOLS,
}

DESCRIPTIONS: dict[str, dict[str, str]] = {
    "verbose": {
        "list_rooms": "List rooms in the inventory. Filter by the date a room must be free by and/or by area (city or ZIP).",
        "list_rooms.available_by": "YYYY-MM-DD. Only rooms whose available_from is on or before this date.",
        "list_rooms.area": "City (Durham, Raleigh, Chapel Hill) or 5-digit ZIP.",
        "get_room": "Get the full record for one room: rent, deposit, utilities, availability, pets, lease minimum, occupancy cap, amenities, photos.",
        "get_room.room_id": "Room id such as R023.",
        "update_room": "Change fields on a room record, for example a new rent or available_from the owner gave you. Do this BEFORE quoting a new price anywhere.",
        "update_room.fields": "Fields to change, e.g. {\"rent\": 750, \"available_from\": \"2026-11-01\", \"private_bath\": true}.",
        "create_listing": "Create a draft listing for a room. The price must equal the room's rent and any dollar figure in the text must come from the room record. Returns the draft plus compliance findings.",
        "create_listing.price": "Monthly rent in USD; must equal the room record's rent.",
        "publish_listing": "Post a draft or live listing to one channel. Call once per channel. Refused if the listing text fails the fair-housing check.",
        "publish_listing.channel": "One of marketplace, roomies, craigslist, padsplit.",
        "update_listing": "Edit a listing's title, body or price. Live posts are updated too.",
        "update_listing.fields": "Any of {\"title\", \"body\", \"price\"}.",
        "mark_filled": "Mark a listing filled; removes it from every channel. Use when a room is leased.",
        "get_listing_media": "Get the photo names and URLs for a room, to attach to listings or messages.",
        "check_listing_compliance": "Check ad or message text against fair-housing advertising rules (24 CFR 100.75). Returns findings with a suggested rewrite for each problem phrase.",
        "get_market_rent": "Get the Zillow Observed Rent Index (typical whole-home rent) for a ZIP. A room in a shared home normally rents well below this.",
        "get_market_rent.bedrooms": "Optional; ZORI is all-sizes, so this is recorded but does not change the number.",
        "list_threads": "List conversation threads with renters (summaries). Use unanswered_only to find threads whose last message is from the renter.",
        "read_thread": "Read every message in one thread.",
        "send_message": "Send a reply in a thread. Style rules are enforced: at most 2 sentences, at most one question, no em or en dashes, and no dollar figure or lease term that is not in the room or listing record. Ask for one missing item at a time.",
        "send_message.text": "Plain, short text in the renter's language.",
        "send_message.attachments": "Optional photo names from get_listing_media.",
        "read_reply": "Read a renter's latest message into exact JSON: lease answer, move-in date (exact or vague), phone, occupants, reason, intents, language. Always use this instead of judging a reply yourself; a month or 'soon' is vague, not a date.",
        "read_reply.thread_id": "Thread whose latest renter message to read. Give this or text.",
        "read_reply.text": "Raw message text, when there is no thread.",
        "read_reply.pending_item": "The item you last asked for, so a bare 'yes' or '2' is read correctly.",
        "upsert_renter": "Create or update the renter record for a thread. Put gate answers from read_reply under fields.gate (lease, move_in, phone, occupants, reason) and preferences under fields.wants.",
        "upsert_renter.fields": "e.g. {\"name\": \"Maria\", \"gate\": {\"move_in\": {\"status\": \"answered\", \"date\": \"2026-11-01\"}}, \"wants\": {\"budget\": 800}, \"listing_of_interest\": \"L001\"}.",
        "match_renters": "Rank renters in the register for a room by budget, area, move-in date, occupancy and gate completeness.",
        "find_showing_slots": "Find free showing slots for a room within showing hours, between two dates (max 14 days).",
        "propose_showing": "Propose a showing time to a renter. Refused unless the renter's gate is complete: explicit yes to a 12-month lease, an exact move-in date, phone, reason and number of occupants.",
        "propose_showing.start": "Slot start from find_showing_slots, YYYY-MM-DDTHH:MM.",
        "web_search": "Search the web (sandbox: local vendor directory). Returns titles, URLs and snippets.",
        "fetch_page": "Fetch the text of a web page found by web_search.",
        "find_vendors": "Find service vendors by trade (plumber, hvac, electrician) that serve the property's ZIP. Give job_id (from create_job, whose job carries the property's zip) or zip; never guess a zip.",
        "find_vendors.trade": "plumber, hvac or electrician.",
        "find_vendors.zip": "5-digit ZIP from the job (create_job's job.zip) or the room record (get_room, list_rooms). Optional when job_id is given.",
        "find_vendors.job_id": "Job id from create_job; the job's property zip is used.",
        "create_job": "Open a maintenance job for a property before asking vendors for quotes. The returned job includes the property's room_id, address, zip and area when the property matches a room; pass its job_id to find_vendors.",
        "create_job.property": "Room id (best) or the property's street address as the owner wrote it.",
        "request_quote": "Ask a vendor for a quote on a job. Returns TIMEOUT if the vendor does not respond; then try another vendor.",
        "book_vendor": "Accept a quote and book the vendor. Refused with BUDGET_EXCEEDED above the owner's spending limit; escalate those instead.",
        "escalate_to_owner": "Hand a decision to the owner (over-budget quote, shorter lease request, conditional answer, anything you may not decide). Include a draft reply when useful.",
        "escalate_to_owner.ref_id": "The thread_id, job_id, renter_id, listing_id or quote_id the decision is about.",
        "report_to_owner": "Send the owner a short status summary of what you did.",
        "listing_disclosure": "Get the full-disclosure messages for a room, built from its record only: type, what is private and shared, rent, deposit, utilities, street (never the house number), availability and the 1 year lease, plus the house rules (smoking, parties, pets). Send each as its own message before the first gate question.",
        "listing_disclosure.thread_id": "Thread whose room and language to use. Give this or room_id.",
        "capture_demand": "Record what an inquirer wants (every inquiry is demand, fit or not) on their register row, then check it against the inventory. Returns whether the room they asked about is available and fits, other open rooms that fit, and the next step.",
        "capture_demand.criteria": "Only what they stated, never guesses: {\"area\": \"near the airport\", \"budget\": 800, \"type\": \"room\", \"private_bath\": true, \"move_in\": \"2026-11-01\", \"stay_months\": 12, \"occupants\": 1, \"pets\": \"cat\", \"language\": \"es\"}.",
        "capture_demand.listing_of_interest": "The listing_id or room_id they asked about (defaults to the thread's).",
        "capture_demand.phone": "Their phone if given; a person already on file with this phone is merged into one row.",
        "match_inventory": "Rooms that fit a renter's stated criteria (hard gates: type, budget more than 15% below rent, occupants, pets, stay, private bath, area; unknowns never disqualify; needs at least 2 stated criteria).",
        "search_external_rooms": "Sourcing step when nothing in the inventory fits: search off-inventory leads (partners, pipeline), mark the renter 'sourcing' with a due date a few days out. Leads are for the owner only, never offered to the renter as yours.",
        "park_prospect": "Park a not-now prospect with a reconnect date taken from their timeframe: a named month is the 1st of that month, an exact date is that date, no timeframe is 30 days out. Stops check-ins until then.",
        "park_prospect.reason": "Their own words, e.g. 'not looking until January'.",
        "park_prospect.timeframe": "What they said about timing ('January', 'next month', 'in 2 weeks', '2027-01-15'); leave out if they gave none.",
        "log_followup": "Record a follow-up event so the cadence advances: application_sent (check-ins every 12 h, then 24 h, then doubling), checkin_sent, reply (resets to 12 h), reconnect_sent, applied, closed, placed.",
        "due_followups": "List prospects whose reconnect, check-in or sourcing date has come, each with the next step. Optional now (YYYY-MM-DD or YYYY-MM-DDTHH:MM); default is the current time.",
        "get_ledger": "A tenant's exact money facts from the ledger and lease: rent due this period, received, remainder, arrears, balance, days late, and the late fee ONLY if the lease has one. Quote nothing else.",
        "get_ledger.tenant_id": "Tenant id; or give thread_id.",
        "record_payment": "Record money a tenant sent. Returns the exact amount received, the exact remainder, and acknowledgement messages to send as written (no new terms).",
        "record_payment.amount": "Dollars received, e.g. 400.",
        "rent_ladder": "The late-rent ladder: reminder, assess how they plan to pay, check in, escalate after the deadline (2 silent follow-ups, then the owner). Without event: what to do next (actions), including a lease notice when it is due. With event: record what you just did (reminder_sent, assessed, tenant_replied, followup_sent, checkin_sent, plan_sent, escalated) or that the tenant warned before the due date (warned + promised_date).",
        "rent_ladder.promised_date": "YYYY-MM-DD the tenant said they can pay.",
        "send_notice": "Send the lease's own late-rent notice (its template, exact ledger figures), recorded as a notice message. Always send it when rent_ladder says it is due, even while a plan is being made. Never write a notice yourself.",
        "propose_payment_plan": "Put the tenant's proposed schedule (ask how they plan to pay first) into a plan and check it against the owner's bounds: split = at most 2 payments inside this month; due_date_shift = new due day 0 to 3 days after their paycheck; catch_up = arrears spread over at most 3 months on top of rent. Returns in_bounds and an owner_draft: escalate_to_owner with it. Never agree a plan before the owner approves.",
        "propose_payment_plan.installments": "[{\"date\": \"2026-10-24\", \"amount\": 350}, ...] exactly as the tenant proposed.",
        "triage_maintenance": "Safety screen first for a maintenance report (gas, fire, smoke, sparks, CO alarm, flooding, sewage, no heat in freezing weather, night lockout; EN/ES). Emergency: the owner is alerted at once and you get the safety_message to send FIRST. Otherwise: triage questions to ask one at a time before a job.",
        "triage_maintenance.text": "The tenant's message; defaults to their latest message on the thread.",
        "compare_quotes": "The quotes for a job side by side (vendor, amount, rating, earliest date), ready for escalate_to_owner: every expenditure needs the owner's approval.",
        "cluster_report": "Demand report for the owner: totals by status, new captures by channel, and clusters of people wanting the same area, type and $150 budget band (WATCH at 3, SUPPLY SIGNAL at 5 qualified people; 5 counting unqualified people is 'nominal'). Use the summary in report_to_owner.",
    },
    "terse": {
        "list_rooms": "List rooms.",
        "get_room": "Get one room.",
        "update_room": "Update room fields.",
        "create_listing": "Create a draft listing.",
        "publish_listing": "Publish a listing to a channel.",
        "update_listing": "Update a listing.",
        "mark_filled": "Mark a listing filled.",
        "get_listing_media": "Get room photos.",
        "check_listing_compliance": "Fair-housing check on text.",
        "get_market_rent": "Market rent for a ZIP.",
        "list_threads": "List threads.",
        "read_thread": "Read a thread.",
        "send_message": "Send a message in a thread.",
        "read_reply": "Parse a renter reply to JSON.",
        "upsert_renter": "Create or update a renter.",
        "match_renters": "Match renters to a room.",
        "find_showing_slots": "Find showing slots.",
        "propose_showing": "Propose a showing.",
        "web_search": "Web search.",
        "fetch_page": "Fetch a page.",
        "find_vendors": "Find vendors by trade and zip, or by job_id.",
        "find_vendors.zip": "ZIP from job or room.",
        "find_vendors.job_id": "Job id; uses its zip.",
        "request_quote": "Request a vendor quote.",
        "book_vendor": "Book a vendor quote.",
        "create_job": "Create a maintenance job; returns its zip.",
        "create_job.property": "Room id or address.",
        "escalate_to_owner": "Escalate to the owner.",
        "report_to_owner": "Report to the owner.",
        "listing_disclosure": "Disclosure messages and house rules for a room.",
        "capture_demand": "Record an inquirer's criteria and check the inventory.",
        "match_inventory": "Rooms that fit a renter.",
        "search_external_rooms": "Search off-inventory leads; mark sourcing.",
        "park_prospect": "Park a not-now prospect with a reconnect date.",
        "log_followup": "Record a follow-up event.",
        "due_followups": "Follow-ups that are due.",
        "cluster_report": "Demand clusters and supply signals.",
        "get_ledger": "Tenant ledger facts.",
        "record_payment": "Record a tenant payment.",
        "rent_ladder": "Late-rent ladder: next action or record an event.",
        "send_notice": "Send the lease's late-rent notice.",
        "propose_payment_plan": "Check a payment plan against the owner's bounds.",
        "triage_maintenance": "Safety screen and triage questions.",
        "compare_quotes": "Quotes side by side for the owner.",
    },
}

TOOL_NAMES = [n for n in PARAMS if n not in CONCIERGE_TOOLS and n not in TENANCY_TOOLS]
DESCRIPTIONS["concierge"] = dict(DESCRIPTIONS["verbose"])   # verbose wording + the concierge tools


def tool_schemas(variant: str = "verbose", only: list[str] | None = None,
                 descriptions: dict[str, str] | None = None) -> list[dict]:
    """OpenAI function-calling tool list. `variant` picks a DESCRIPTIONS set; `descriptions`
    overrides individual entries (for ablations); `only` restricts to a subset of tool names."""
    if variant not in DESCRIPTIONS:
        raise KeyError(f"unknown description variant {variant!r}; have {sorted(DESCRIPTIONS)}")
    desc = {**DESCRIPTIONS[variant], **(descriptions or {})}
    out = []
    names = only or (TOOL_NAMES + CONCIERGE_TOOLS + TENANCY_TOOLS if variant == "concierge" else TOOL_NAMES)
    for name in names:
        params = copy.deepcopy(PARAMS[name])
        for pname, pschema in params["properties"].items():
            d = desc.get(f"{name}.{pname}")
            if d:
                pschema["description"] = d
        out.append({"type": "function",
                    "function": {"name": name, "description": desc.get(name, name), "parameters": params}})
    return out


TOOLS: list[dict] = tool_schemas("verbose")
