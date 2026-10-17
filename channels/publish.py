"""Command line for the adapters (demo and owner use).

  python -m channels.publish marketplace                 # mock, stops before Publish, prints screenshot path
  python -m channels.publish craigslist --target live    # owner's logged-in profile, stops before publish
  python -m channels.publish all                         # every mock platform
  python -m channels.publish roomies --listing my.json   # your own listing JSON

Repair uses the operator model (OPERATOR_BASE_URL / OPERATOR_MODEL / OPERATOR_API_KEY).
Set CHANNELS_REPAIR_FALLBACK=heuristic to allow the offline word-overlap fallback when no model is up.
"""
from __future__ import annotations

import argparse
import json
import sys

from .adapters import api

SAMPLE_LISTING = {
    "listing_id": "L-demo-appling",
    "title": "Private room with its own bath near Appling Way",
    "body": "Furnished private room with its own bathroom in a quiet shared house. Utilities and wifi "
            "included. Available November 1, 6 month minimum.",
    "price": 750,
    "room": {"room_id": "appling-way-a", "area": "Durham", "zip": "27703", "address_public": "Appling Way, Durham, NC",
             "type": "private_room", "private_bath": True, "furnished": True, "available_from": "2026-11-01",
             "lease_min_months": 6, "pets": "no"},
    "photos": [],
}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("channel", choices=[*api.PLATFORMS, "all"])
    ap.add_argument("--target", default="mock", choices=["mock", "live"])
    ap.add_argument("--listing", help="path to a listing JSON (contract listing + room + photos)")
    ap.add_argument("--base-url", default=None, help="mock server, default $MOCK_BASE_URL or http://127.0.0.1:8765")
    ap.add_argument("--no-repair", action="store_true")
    a = ap.parse_args(argv)
    listing = json.load(open(a.listing)) if a.listing else SAMPLE_LISTING
    if a.target == "live" and not listing.get("photos"):
        print("live posting needs real photos in the listing JSON ('photos': [paths])", file=sys.stderr)
        return 2
    chans = api.PLATFORMS if a.channel == "all" else (a.channel,)
    rc = 0
    for ch in chans:
        res = api.publish_listing(listing, ch, a.target, base_url=a.base_url, repair=not a.no_repair)
        print(json.dumps({"channel": ch, **res}, indent=2, default=str))
        rc |= 0 if res["ok"] else 1
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
