"""Listing tools: create/publish/update/mark_filled, media, compliance."""
from __future__ import annotations

import copy

from .. import live
from ..core import tool
from ..errors import ToolError
from ..world import POST_CHANNELS
from . import compliance
from ._util import dollar_figures, need, num
from .demand_guards import house_numbers, public_street
from .fact_guards import check_unconfirmed

MEDIA_BASE = "https://sandbox.rentus.local/media"


def allowed_figures(room: dict, listing: dict | None = None) -> set[float]:
    figs = {num(room.get("rent")), num(room.get("deposit"))}
    if listing:
        figs.add(num(listing.get("price")))
    for v in dollar_figures(str(room.get("utilities", ""))):
        figs.add(v)
    return {f for f in figs if f is not None}


def check_figures(text: str, allowed: set[float], room_id: str) -> None:
    bad = [f for f in dollar_figures(text) if f not in allowed]
    if bad:
        shown = ", ".join(f"${b:g}" for b in bad)
        ok_ = ", ".join(f"${a:g}" for a in sorted(allowed))
        raise ToolError("POLICY_BLOCKED", f"dollar figure {shown} is not in the record for {room_id} (allowed: {ok_})",
                        hint="quote only the room's rent/deposit; if the owner changed the price, update_room first")


def check_address(world, text: str, room: dict) -> None:
    """Public text gives the street name only, never the house number (R-STYLE-7, C7)."""
    hits = house_numbers(text, world.rooms)
    if hits:
        raise ToolError("POLICY_BLOCKED", "public listing text gives a house number: " + ", ".join(map(repr, hits)),
                        hint=f"use the street name only, e.g. '{public_street(room.get('address', ''))}'",
                        details={"rules": ["address_public"], "phrases": hits})


def _check_price(room: dict, price) -> None:
    if num(price) != num(room.get("rent")):
        raise ToolError("POLICY_BLOCKED", f"price {price} does not match {room['room_id']} rent {room.get('rent')}",
                        hint="if the owner gave a new price, call update_room with the new rent first")


@tool("create_listing")
def create_listing(world, room_id: str, title: str, body: str, price):
    room = need(world, "rooms", room_id, "room", "list_rooms")
    if not title.strip() or not body.strip():
        raise ToolError("INVALID_ARGS", "create_listing: title and body must not be empty")
    for l in world.listings:
        if l["room_id"] == room_id and l["status"] in ("draft", "live"):
            raise ToolError("CONFLICT", f"room {room_id} already has {l['status']} listing {l['listing_id']}",
                            hint=f"use update_listing on {l['listing_id']} instead")
    _check_price(room, price)
    check_figures(f"{title}\n{body}", allowed_figures(room), room_id)
    check_address(world, f"{title}\n{body}", room)
    check_unconfirmed(f"{title}\n{body}", room, "listing text")
    listing = {"listing_id": world.next_id("L"), "room_id": room_id, "status": "draft", "title": title, "body": body,
               "price": int(price) if float(price).is_integer() else price, "channels": {},
               "created_at": world.clock["now"]}
    world.listings.append(listing)
    return {"listing": copy.deepcopy(listing), "compliance": compliance.check(f"{title}\n{body}", world.policy)}


@tool("publish_listing")
def publish_listing(world, listing_id: str, channel: str):
    listing = need(world, "listings", listing_id, "listing")
    if channel not in POST_CHANNELS:
        raise ToolError("INVALID_ARGS", f"cannot post to {channel!r}", hint=f"channels: {', '.join(POST_CHANNELS)}")
    if listing["status"] in ("filled", "removed"):
        raise ToolError("CONFLICT", f"listing {listing_id} is {listing['status']}", hint="create a new listing")
    cur = listing["channels"].get(channel)
    if cur and cur.get("status") in ("live", "ready_to_submit"):
        raise ToolError("CONFLICT", f"listing {listing_id} is already {cur['status']} on {channel}",
                        hint="use update_listing to change it")
    room = world.get("rooms", listing["room_id"]) or {}
    check_address(world, f"{listing['title']}\n{listing['body']}", room)
    check_unconfirmed(f"{listing['title']}\n{listing['body']}", room, "listing text")
    report = compliance.check(f"{listing['title']}\n{listing['body']}", world.policy)
    if not report["ok"]:
        phrases = "; ".join(f"'{f['phrase']}' ({f['rule']})" for f in report["findings"] if f["severity"] == "violation")
        raise ToolError("POLICY_BLOCKED", f"listing text fails the fair-housing check: {phrases}",
                        hint="rewrite with update_listing using the suggestions, then publish again",
                        details={"findings": report["findings"]})
    if world.mode == "live":
        res = live.adapter_for(channel).publish_listing(world, listing, channel)
        entry = {"post_id": res.get("post_id"), "status": res.get("status", "ready_to_submit"), "url": res.get("url"),
                 "screenshot": res.get("screenshot")}
    else:
        entry = {"post_id": f"{channel[:3]}-{listing_id}", "status": "live",
                 "url": f"https://sandbox.rentus.local/{channel}/{listing_id}"}
    listing["channels"][channel] = entry
    if entry["status"] == "live":
        listing["status"] = "live"
    world.channels[channel]["posts"] = [p for p in world.channels[channel]["posts"] if p.get("listing_id") != listing_id]
    world.channels[channel]["posts"].append({**entry, "listing_id": listing_id, "posted_at": world.clock["now"]})
    return dict(entry)


@tool("update_listing")
def update_listing(world, listing_id: str, fields: dict):
    listing = need(world, "listings", listing_id, "listing")
    allowed = {"title", "body", "price"}
    bad = [k for k in fields if k not in allowed]
    if bad or not fields:
        raise ToolError("INVALID_ARGS", f"update_listing: editable fields are title, body, price (got {', '.join(fields) or 'none'})",
                        hint="use mark_filled to close a listing")
    if listing["status"] in ("filled", "removed"):
        raise ToolError("CONFLICT", f"listing {listing_id} is {listing['status']}")
    room = need(world, "rooms", listing["room_id"], "room")
    if "price" in fields:
        _check_price(room, fields["price"])
    title, body = fields.get("title", listing["title"]), fields.get("body", listing["body"])
    if not str(title).strip() or not str(body).strip():
        raise ToolError("INVALID_ARGS", "update_listing: title and body must not be empty")
    check_figures(f"{title}\n{body}", allowed_figures(room), room["room_id"])
    check_address(world, f"{title}\n{body}", room)
    check_unconfirmed(f"{title}\n{body}", room, "listing text")
    listing.update(fields)
    for entry in listing["channels"].values():
        if entry.get("status") == "live":
            entry["updated_at"] = world.clock["now"]
    return {"listing": copy.deepcopy(listing), "compliance": compliance.check(f"{title}\n{body}", world.policy)}


@tool("mark_filled")
def mark_filled(world, listing_id: str):
    listing = need(world, "listings", listing_id, "listing")
    if listing["status"] == "filled":
        raise ToolError("CONFLICT", f"listing {listing_id} is already filled")
    listing["status"] = "filled"
    listing["filled_at"] = world.clock["now"]
    for ch, entry in listing["channels"].items():
        entry["status"] = "removed"
        for p in world.channels[ch]["posts"]:
            if p.get("listing_id") == listing_id:
                p["status"] = "removed"
    return {"listing": copy.deepcopy(listing)}


@tool("get_listing_media")
def get_listing_media(world, room_id: str):
    room = need(world, "rooms", room_id, "room", "list_rooms")
    return {"photos": [{"name": p, "url": f"{MEDIA_BASE}/{room_id}/{p}"} for p in room.get("photos", [])]}


@tool("check_listing_compliance")
def check_listing_compliance(world, text: str):
    return compliance.check(text, world.policy)
