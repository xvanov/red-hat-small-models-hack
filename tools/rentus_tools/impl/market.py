"""get_market_rent: Zillow ZORI by ZIP.

Reads data/raw/zori/zori_nc.csv (from data/download.py) when present, else the committed table
rentus_tools/data/zori_nc_latest.csv built from it by tools/scripts/build_zori_table.py.
"""
from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path

from ..core import tool
from ..errors import ToolError
from ..world import PKG_DIR, find_repo_root

TABLE = PKG_DIR / "data" / "zori_nc_latest.csv"
SOURCE = "Zillow Observed Rent Index (ZORI), ZIP, smoothed, all homes + multifamily"


@lru_cache(maxsize=1)
def zori_table() -> tuple[dict, str]:
    root = find_repo_root()
    raw = root / "data" / "raw" / "zori" / "zori_nc.csv" if root else None
    table: dict[str, dict] = {}
    if raw and raw.exists():
        with raw.open() as fh:
            rows = list(csv.reader(fh))
        head = rows[0]
        months = [i for i, h in enumerate(head) if h[:4].isdigit()]
        for r in rows[1:]:
            vals = [(head[i], r[i]) for i in months if r[i]]
            if vals:
                table[r[head.index("RegionName")].zfill(5)] = {"zori": round(float(vals[-1][1]), 2), "as_of": vals[-1][0],
                                                              "city": r[head.index("City")], "metro": r[head.index("Metro")]}
        return table, "raw"
    with Path(TABLE).open() as fh:
        for r in csv.DictReader(fh):
            table[r["zip"]] = {"zori": float(r["zori"]), "as_of": r["as_of"], "city": r["city"], "metro": r["metro"]}
    return table, "table"


@tool("get_market_rent")
def get_market_rent(world, zip: str, bedrooms: int | None = None):
    table, origin = zori_table()
    row = table.get(zip)
    if row is None:
        near = sorted(table, key=lambda z: abs(int(z) - int(zip)))[:3]
        raise ToolError("NOT_FOUND", f"no ZORI value for ZIP {zip} (North Carolina ZIPs only)",
                        hint=f"nearest covered ZIPs: {', '.join(near)}")
    out = {"zip": zip, "zori": row["zori"], "source": SOURCE, "as_of": row["as_of"], "city": row["city"],
           "metro": row["metro"], "unit": "USD/month, typical whole home",
           "note": "ZORI is whole-home rent across all sizes; a room in a shared home rents well below it"}
    if bedrooms is not None:
        out["bedrooms_requested"] = bedrooms
    return out
