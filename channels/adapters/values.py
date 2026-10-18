"""Turn a contract listing (+ its room) into the flat values each platform's flow fills in.

Input shape (what tools' publish_listing passes through):
  {"listing_id", "title", "body", "price", "room": {room fields from contracts/tools.md §3},
   "photos": ["path" | {"name", "url"}], "contact_email"?, "overrides"?: {platform: {value_key: value}}}
"""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SAMPLE_PHOTOS = REPO / "channels" / "mock_sites" / "static" / "sample_photos"


def resolve_photos(photos: list, *, allow_samples: bool) -> list[str]:
    out: list[str] = []
    tmp: Path | None = None
    for ph in photos or []:
        ref = ph.get("url") or ph.get("path") if isinstance(ph, dict) else ph
        if not ref:
            continue
        ref = str(ref)
        if ref.startswith(("http://", "https://")):
            import httpx

            tmp = tmp or Path(tempfile.mkdtemp(prefix="rentus-photos-"))
            name = (ph.get("name") if isinstance(ph, dict) else None) or ref.rsplit("/", 1)[-1] or "photo.jpg"
            dest = tmp / Path(name).name
            r = httpx.get(ref, timeout=20, follow_redirects=True)
            r.raise_for_status()
            dest.write_bytes(r.content)
            out.append(str(dest))
            continue
        p = Path(ref.removeprefix("file://"))
        if not p.is_absolute():
            p = REPO / p
        if p.exists():
            out.append(str(p))
    if not out and allow_samples:
        out = [str(p) for p in sorted(SAMPLE_PHOTOS.glob("*.png"))]
    return out


def _min_stay(months) -> str | None:
    """Roomies' minimum-stay option for the room's confirmed lease minimum; None (left unset) when unknown."""
    try:
        m = int(months)
    except (TypeError, ValueError):
        return None
    if m < 1:
        return None
    for opt in (12, 6, 3, 1):
        if m >= opt:
            return f"{opt} months" if opt > 1 else "1 month"
    return None


def known(room: dict, key: str):
    """The room record's value for `key` only when it is an owner-confirmed fact: present, not null, not
    'unconfirmed'/'unknown', and not named in the record's `unconfirmed` list. Otherwise None."""
    if key in (room.get("unconfirmed") or []):
        return None
    v = room.get(key)
    if v is None or (isinstance(v, str) and v.strip().lower() in ("", "unconfirmed", "unknown", "tbd", "n/a")):
        return None
    return v


def craigslist_laundry(v) -> str | None:
    """A confirmed laundry fact -> craigslist's exact drop-down option; None when it does not map."""
    t = str(v or "").lower()
    if not t:
        return None
    if t in ("w/d in unit", "w/d hookups", "laundry in bldg", "laundry on site", "no laundry on site"):
        return t
    if re.search(r"\bno\b|none", t):
        return "no laundry on site"
    if "hookup" in t:
        return "w/d hookups"
    if "unit" in t or "in room" in t or "in-unit" in t:
        return "w/d in unit"
    if "bldg" in t or "building" in t:
        return "laundry in bldg"
    if "site" in t or "premises" in t or "shared" in t:
        return "laundry on site"
    return None


def craigslist_parking(v) -> str | None:
    t = str(v or "").lower()
    if not t:
        return None
    opts = ("carport", "attached garage", "detached garage", "off-street parking", "street parking",
            "valet parking", "no parking")
    if t in opts:
        return t
    if re.search(r"\bno\b|none", t):
        return "no parking"
    for o in ("carport", "attached garage", "detached garage", "valet"):
        if o in t:
            return o if o != "valet" else "valet parking"
    if any(w in t for w in ("off-street", "off street", "on premises", "on-site", "on site", "driveway", "lot")):
        return "off-street parking"
    if "street" in t:
        return "street parking"
    return None


def _housing_type(room: dict) -> str | None:
    ht = known(room, "housing_type")
    if ht:
        return ht
    t = str(known(room, "type") or "").lower()
    for word in ("house", "apartment", "townhouse", "condo", "duplex"):
        if word in t:
            return word
    return None


def prepare(platform: str, listing: dict, *, target: str) -> dict:
    """Flat values for a platform's flow. Only owner-confirmed room facts are filled: an unknown fact is None,
    and the engine skips a step whose value is None (a required one fails loudly instead of guessing).
    Checkboxes for unknown facts stay unchecked (nothing is claimed)."""
    room = listing.get("room") or {}
    price = listing.get("price") or room.get("rent")
    pb = known(room, "private_bath")
    private_bath = bool(pb)
    pets = str(known(room, "pets") or "").lower()
    lease = known(room, "lease_min_months")
    v = {
        "title": listing.get("title"),
        "headline": listing.get("title"),
        "posting_title": listing.get("title"),
        "body": listing.get("body"),
        "description": listing.get("body"),
        "price": int(price) if price is not None else None,
        "weekly_price": round(int(price) * 12 / 52) if price is not None else None,
        "address": room.get("address_public") or room.get("area"),
        "area": room.get("area") or room.get("address_public"),
        "postal": room.get("zip"),
        "available_date": known(room, "available_from"),
        "private_bath": private_bath,
        "private_bath_text": None if pb is None else ("private bath" if pb else "no private bath"),
        "furnished": bool(known(room, "furnished")),
        "bedrooms": 1,  # a single-room listing
        "bathrooms": 1 if pb else None,
        "home_type": "Room only",
        "min_stay": _min_stay(lease),  # never a lease length the room record does not have
        "lease_min_months": lease,
        "category": "rooms & shares",
        # craigslist drop-downs (exact option text): filled only from explicit room-record fields
        # (laundry, parking, housing_type or a type naming the building). Unknown -> None -> the step is skipped and the drop-down stays unset.
        "private_room_text": "private room" if room.get("type", "private_room") != "shared_room" else "room not private",
        "rent_period_text": "month",
        "housing_type_text": _housing_type(room),
        "is_house": True if _housing_type(room) == "house" else None,
        "laundry_text": craigslist_laundry(known(room, "laundry")),
        "parking_text": craigslist_parking(known(room, "parking")),
        "room_name": room.get("room_id") or listing.get("title"),
        # mock forms require a size; the real sites get one only from the record
        "room_size": known(room, "size") or ("Medium" if target == "mock" else None),
        "cat_friendly": "cat" in pets or pets in ("yes", "true", "allowed"),
        "dog_friendly": "dog" in pets or pets in ("yes", "true", "allowed"),
        "email": listing.get("contact_email") or os.environ.get("CHANNELS_CONTACT_EMAIL")
        or ("leasing@example.com" if target == "mock" else None),
        "photos": resolve_photos(listing.get("photos") or room.get("photos") or [],
                                 allow_samples=(target == "mock")),
    }
    v.update((listing.get("overrides") or {}).get(platform, {}))
    return v
