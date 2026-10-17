"""Turn a contract listing (+ its room) into the flat values each platform's flow fills in.

Input shape (what tools' publish_listing passes through):
  {"listing_id", "title", "body", "price", "room": {room fields from contracts/tools.md §3},
   "photos": ["path" | {"name", "url"}], "contact_email"?, "overrides"?: {platform: {value_key: value}}}
"""
from __future__ import annotations

import os
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


def _min_stay(months: int | None) -> str:
    m = months or 12
    for opt in (12, 6, 3, 1):
        if m >= opt:
            return f"{opt} months" if opt > 1 else "1 month"
    return "1 month"


def prepare(platform: str, listing: dict, *, target: str) -> dict:
    room = listing.get("room") or {}
    price = listing.get("price") or room.get("rent")
    private_bath = bool(room.get("private_bath"))
    pets = str(room.get("pets") or "").lower()
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
        "available_date": room.get("available_from"),
        "private_bath": private_bath,
        "private_bath_text": "private bath" if private_bath else "no private bath",
        "furnished": bool(room.get("furnished")),
        "bedrooms": 1,
        "bathrooms": 1,
        "home_type": "Room only",
        "min_stay": _min_stay(room.get("lease_min_months")),
        "category": "rooms & shares",
        "room_name": room.get("room_id") or listing.get("title"),
        "room_size": room.get("size") or "Medium",
        "cat_friendly": "cat" in pets or pets in ("yes", "true", "allowed"),
        "dog_friendly": "dog" in pets or pets in ("yes", "true", "allowed"),
        "email": listing.get("contact_email") or os.environ.get("CHANNELS_CONTACT_EMAIL")
        or ("leasing@example.com" if target == "mock" else None),
        "photos": resolve_photos(listing.get("photos") or room.get("photos") or [],
                                 allow_samples=(target == "mock")),
    }
    v.update((listing.get("overrides") or {}).get(platform, {}))
    return v
