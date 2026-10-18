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
}

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
    },
}

TOOL_NAMES = list(PARAMS)


def tool_schemas(variant: str = "verbose", only: list[str] | None = None,
                 descriptions: dict[str, str] | None = None) -> list[dict]:
    """OpenAI function-calling tool list. `variant` picks a DESCRIPTIONS set; `descriptions`
    overrides individual entries (for ablations); `only` restricts to a subset of tool names."""
    if variant not in DESCRIPTIONS:
        raise KeyError(f"unknown description variant {variant!r}; have {sorted(DESCRIPTIONS)}")
    desc = {**DESCRIPTIONS[variant], **(descriptions or {})}
    out = []
    for name in (only or TOOL_NAMES):
        params = copy.deepcopy(PARAMS[name])
        for pname, pschema in params["properties"].items():
            d = desc.get(f"{name}.{pname}")
            if d:
                pschema["description"] = d
        out.append({"type": "function",
                    "function": {"name": name, "description": desc.get(name, name), "parameters": params}})
    return out


TOOLS: list[dict] = tool_schemas("verbose")
