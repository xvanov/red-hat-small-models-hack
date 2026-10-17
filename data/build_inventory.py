"""W5 step 4: sandbox room inventory for the Gym and the demo.

30 fictional rooms across Durham, Raleigh and Chapel Hill/Carrboro. Addresses are
invented (street names do not exist in these cities by design). Prices are grounded
in open data, and every number used is written to data/published/inventory_stats.json:

  base room rent (city, ZIP) =
      UCI 2019 median rent-per-bedroom for 2-3 BR listings in that city
    x ZORI growth for that ZIP (latest month / 2019-12; city median growth if the ZIP
      has no 2019 value)
  then premiums: private bath +10%, own entrance +5%, utilities included +$60,
  rounded to $25.

Amenity mix and the share of rooms with a private bath / private entrance follow
Inside Airbnb Asheville "Private room" listings (the only NC city Inside Airbnb
publishes), used as a proxy for how NC room listings are equipped.

Usage: data/.venv/bin/python data/build_inventory.py
"""
from __future__ import annotations

import collections
import datetime as dt
import glob
import json
import random
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "raw"
OUT = ROOT / "published" / "inventory.json"
STATS = ROOT / "published" / "inventory_stats.json"
TODAY = dt.date(2026, 10, 17)

# area -> (UCI city names, ZIPs, number of rooms)
AREAS = {
    "Durham": (["Durham"], ["27701", "27703", "27704", "27705", "27707", "27713"], 16),
    "Raleigh": (["Raleigh"], ["27603", "27604", "27605", "27606", "27607", "27610"], 8),
    "Chapel Hill": (["Chapel Hill", "Carrboro"], ["27514", "27516", "27510"], 6),
}
# invented street names (checked by eye to not be real streets in these towns)
STREETS = ["Larkspur Bend", "Quillfeather Ln", "Copperleaf Way", "Tamsin Ct", "Brindlewood Dr", "Halloway Loop",
           "Marrowstone St", "Ambergate Rd", "Fennimore Pl", "Silverbell Run", "Wrenhaven Ave", "Odessa Gate Ln",
           "Cobbleford St", "Pennywhistle Dr", "Tillbrook Ct", "Juniper Hollow Rd"]
TYPES = ["room in house", "room in house", "room in house", "room in townhouse", "basement suite", "room in duplex"]


def zori_growth() -> tuple[dict, str]:
    z = pd.read_csv(RAW / "zori" / "zori_nc.csv", dtype={"RegionName": str})
    latest = [c for c in z.columns if c[:2] == "20"][-1]
    out = {}
    for area, (cities, zips, _) in AREAS.items():
        sub = z[z.RegionName.isin(zips)].set_index("RegionName")
        g = (sub[latest] / sub["2019-12-31"]).dropna()
        city_g = float(g.median())
        for zp in zips:
            if zp in sub.index and pd.notna(sub.loc[zp, "2019-12-31"]):
                out[zp] = {"zori_2019_12": round(float(sub.loc[zp, "2019-12-31"]), 1),
                           "zori_latest": round(float(sub.loc[zp, latest]), 1), "growth": round(float(g[zp]), 4),
                           "growth_source": "zip"}
            else:
                out[zp] = {"zori_2019_12": None,
                           "zori_latest": round(float(sub.loc[zp, latest]), 1) if zp in sub.index else None,
                           "growth": round(city_g, 4), "growth_source": f"{area} median"}
    return out, latest


def uci_per_bedroom() -> dict:
    f = RAW / "uci" / "apartments_for_rent_classified_100K" / "apartments_for_rent_classified_100K.csv"
    u = pd.read_csv(f, sep=";", encoding="latin-1", on_bad_lines="skip", low_memory=False)
    u = u[(u.state == "NC") & (u.price_type == "Monthly")]
    u["price"] = pd.to_numeric(u.price, errors="coerce")
    u["bedrooms"] = pd.to_numeric(u.bedrooms, errors="coerce")
    out = {}
    for area, (cities, _, _) in AREAS.items():
        s = u[u.cityname.isin(cities) & u.bedrooms.isin([2, 3])]
        ppb = s.price / s.bedrooms
        one = u[u.cityname.isin(cities) & (u.bedrooms == 1)].price
        out[area] = {"n_listings_2_3br": int(len(s)), "median_rent_per_bedroom_2019": round(float(ppb.median()), 1),
                     "n_listings_1br": int(len(one)), "median_1br_2019": float(one.median())}
    return out


def airbnb_private_rooms() -> dict:
    f = sorted(glob.glob(str(RAW / "airbnb" / "asheville_listings_*.csv.gz")))[-1]
    a = pd.read_csv(f, low_memory=False)
    pr = a[a.room_type == "Private room"]
    am = collections.Counter(x for s in pr.amenities.dropna() for x in json.loads(s))
    n = len(pr)
    bath_private = pr.bathrooms_text.fillna("").str.contains("private", case=False).mean()
    return {"snapshot": Path(f).name.split("_")[-1].split(".")[0], "n_private_rooms": int(n),
            "share_private_bath": round(float(bath_private), 3),
            "share_private_entrance": round(am["Private entrance"] / n, 3),
            "amenity_share": {k: round(v / n, 3) for k, v in am.most_common(40)}}


KEEP_AMENITIES = ["Wifi", "Free parking on premises", "Heating", "Air conditioning", "Microwave", "Lock on bedroom door",
                  "Refrigerator", "Dedicated workspace", "Kitchen", "Washer", "Ceiling fan", "Free street parking",
                  "Room-darkening shades", "TV", "Mini fridge", "Bathtub", "Outdoor furniture", "Coffee maker"]


def r25(x: float) -> int:
    return int(round(x / 25.0) * 25)


def main() -> None:
    rng = random.Random(2026)
    growth, latest = zori_growth()
    uci = uci_per_bedroom()
    bnb = airbnb_private_rooms()
    am_share = {k: bnb["amenity_share"].get(k, 0.3) for k in KEEP_AMENITIES}
    rooms = []
    n = 0
    for area, (_, zips, count) in AREAS.items():
        base_ppb = uci[area]["median_rent_per_bedroom_2019"]
        for i in range(count):
            n += 1
            zp = zips[i % len(zips)]
            g = growth[zp]["growth"]
            base = base_ppb * g
            # private bath rate pushed up from Asheville's share: our sandbox wants both kinds well represented
            private_bath = rng.random() < max(bnb["share_private_bath"], 0.4)
            own_entrance = rng.random() < bnb["share_private_entrance"]
            rtype = rng.choice(TYPES)
            if rtype == "basement suite":
                private_bath, own_entrance = True, True
            util = rng.choice(["included", "included", "split evenly", "$75 flat"])
            rent = base * (1 + 0.10 * private_bath + 0.05 * own_entrance) + (60 if util == "included" else 0)
            rent = r25(rent * rng.uniform(0.95, 1.05))
            avail = TODAY + dt.timedelta(days=rng.choice([0, 7, 14, 15, 30, 45, 60]))
            if rng.random() < 0.6:  # most rooms open on the 1st
                avail = (avail.replace(day=1) + dt.timedelta(days=32)).replace(day=1)
            amen = sorted(k for k, p in am_share.items() if rng.random() < p)
            rid = f"R{n:03d}"
            rooms.append({
                "room_id": rid,
                "area": area,
                "zip": zp,
                "address": f"{rng.randint(100, 4999)} {rng.choice(STREETS)}, {area}, NC {zp} (fictional)",
                "type": rtype,
                "private_bath": private_bath,
                "own_entrance": own_entrance,
                "furnished": rng.random() < 0.6,
                "rent": rent,
                "deposit": rng.choice([rent, 500, 500, r25(rent / 2)]),
                "utilities": util,
                "available_from": avail.isoformat(),
                "pets": rng.choice(["no", "no", "cats ok", "small dogs ok", "case by case"]),
                "lease_min_months": rng.choice([12, 12, 12, 12, 6]),
                "max_occupants": 2 if rtype == "basement suite" or rng.random() < 0.3 else 1,
                "amenities": amen,
                "photos": [f"{rid.lower()}_{k}.jpg" for k in ("room", "bath", "kitchen", "exterior")],
                "price_basis": {"uci_median_rent_per_bedroom_2019": base_ppb, "zori_growth": g,
                                "zori_growth_source": growth[zp]["growth_source"]},
            })
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"generated": TODAY.isoformat(), "note": "Sandbox inventory. Addresses are fictional. "
                               "Prices derived from UCI Apartment for Rent Classified (2019) x Zillow ZORI growth; "
                               "see inventory_stats.json and docs/data-provenance.md.", "rooms": rooms}, indent=1))
    STATS.write_text(json.dumps({"zori_latest_month": latest, "zori_by_zip": growth, "uci_by_area": uci,
                                 "airbnb_asheville_private_rooms": bnb,
                                 "premiums": {"private_bath": "+10%", "own_entrance": "+5%", "utilities_included": "+$60",
                                              "jitter": "uniform 0.95-1.05", "rounding": "$25"}}, indent=1))
    df = pd.DataFrame(rooms)
    print(f"{len(rooms)} rooms -> {OUT.relative_to(ROOT)}; ZORI month {latest}")
    print(df.groupby("area").rent.describe()[["count", "min", "50%", "max"]])
    print({a: v["median_rent_per_bedroom_2019"] for a, v in uci.items()})


if __name__ == "__main__":
    main()
