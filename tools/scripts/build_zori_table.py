"""Build the committed NC ZORI fallback table from data/raw/zori/zori_nc.csv (made by data/download.py).

Usage: python tools/scripts/build_zori_table.py
Writes tools/rentus_tools/data/zori_nc_latest.csv: one row per NC ZIP with the latest month's ZORI.
Source: Zillow Observed Rent Index (ZORI), ZIP level, smoothed, all homes + multifamily.
"""
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "data" / "raw" / "zori" / "zori_nc.csv"
OUT = ROOT / "tools" / "rentus_tools" / "data" / "zori_nc_latest.csv"


def main() -> int:
    if not SRC.exists():
        print(f"missing {SRC}; run data/download.py --only zori", file=sys.stderr)
        return 1
    with SRC.open() as fh:
        rows = list(csv.reader(fh))
    head, body = rows[0], rows[1:]
    months = [i for i, h in enumerate(head) if h[:4].isdigit()]
    out = []
    for r in body:
        vals = [(head[i], r[i]) for i in months if r[i]]
        if not vals:
            continue
        as_of, v = vals[-1]
        prior = next((x for m, x in vals if m[:4] == str(int(as_of[:4]) - 1) and m[5:7] == as_of[5:7]), "")
        out.append({"zip": r[head.index("RegionName")].zfill(5), "city": r[head.index("City")],
                    "metro": r[head.index("Metro")], "county": r[head.index("CountyName")], "as_of": as_of,
                    "zori": round(float(v), 2), "zori_12mo_ago": round(float(prior), 2) if prior else ""})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(sorted(out, key=lambda x: x["zip"]))
    print(f"wrote {len(out)} rows to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
