"""W5 step 1: fetch every open dataset the data pipeline uses.

Raw files land in data/raw/ (gitignored). Small inspection samples land in
data/processed/ (gitignored). Re-run any time; finished downloads are skipped.

Usage:  data/.venv/bin/python data/download.py [--only sgd,uci,zori,airbnb,hf]

Sources (licenses in docs/data-provenance.md):
  sgd     Google Schema-Guided Dialogue (CC BY-SA 4.0) -> Homes_1 / Homes_2 dialogues only
  uci     UCI Apartment for Rent Classified (CC BY 4.0)
  zori    Zillow Observed Rent Index, ZIP level -> North Carolina rows only
  airbnb  Inside Airbnb, Asheville NC listings (CC BY 4.0)
  hf      nvidia/When2Call and nvidia/Nemotron-RL-Agentic-Conversational-Tool-Use-Pivot-v1
          (2k-row samples for inspection)
"""
from __future__ import annotations

import argparse
import gzip
import io
import json
import random
import re
import sys
import zipfile
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "raw"
PROC = ROOT / "processed"
UA = {"User-Agent": "rentus-hackathon-data/0.1 (open-data research)"}

# Pinned (leakage review #8): the commit the reader set was built from. GitHub writes the commit into the zip comment,
# which is checked after download; the derived Homes file must hash to SGD_HOMES_SHA256.
SGD_COMMIT = "e852981ae34990f4358979625854259302feaa78"
SGD_ZIP = f"https://github.com/google-research-datasets/dstc8-schema-guided-dialogue/archive/{SGD_COMMIT}.zip"
SGD_HOMES_SHA256 = "e0d67c28e876a4e947d7cbfa7c4b6d146d04145c7e2fd3b6191b752d0e4c0e3e"
UCI_ZIP = "https://archive.ics.uci.edu/static/public/555/apartment+for+rent+classified.zip"
ZORI_CSV = "https://files.zillowstatic.com/research/public_csvs/zori/Zip_zori_uc_sfrcondomfr_sm_month.csv"
AIRBNB_PAGE = "https://insideairbnb.com/get-the-data/"
HF_SETS = ["nvidia/When2Call", "nvidia/Nemotron-RL-Agentic-Conversational-Tool-Use-Pivot-v1"]
HOMES = {"Homes_1", "Homes_2"}


def fetch(url: str, dest: Path, timeout: int = 120) -> Path:
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  have {dest.relative_to(ROOT)}")
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"  get  {url}")
    with requests.get(url, headers=UA, stream=True, timeout=timeout) as r:
        r.raise_for_status()
        tmp = dest.with_suffix(dest.suffix + ".part")
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
        tmp.rename(dest)
    return dest


def sgd() -> None:
    """Keep only dialogues whose services include Homes_1 or Homes_2."""
    print("[sgd]")
    out = RAW / "sgd" / "homes_dialogues.jsonl"
    if out.exists():
        print(f"  have {out.relative_to(ROOT)}")
        return
    z = RAW / "sgd" / "sgd-master.zip"   # an earlier download of master at the same commit is accepted
    if not z.exists():
        z = fetch(SGD_ZIP, RAW / "sgd" / f"sgd-{SGD_COMMIT[:12]}.zip", timeout=600)
    got = zipfile.ZipFile(z).comment.decode(errors="replace").strip()
    if got != SGD_COMMIT:
        raise SystemExit(f"SGD archive is commit {got!r}, expected {SGD_COMMIT}")
    kept, schemas = 0, {}
    with zipfile.ZipFile(z) as zf, open(out, "w") as fo:
        for name in zf.namelist():
            m = re.search(r"/(train|dev|test)/(dialogues_\d+|schema)\.json$", name)
            if not m:
                continue
            split, kind = m.groups()
            data = json.loads(zf.read(name))
            if kind == "schema":
                schemas[split] = [s for s in data if s["service_name"] in HOMES]
                continue
            for d in data:
                if HOMES & set(d.get("services", [])):
                    d["_split"] = split
                    fo.write(json.dumps(d) + "\n")
                    kept += 1
    (RAW / "sgd" / "homes_schema.json").write_text(json.dumps(schemas, indent=1))
    import hashlib
    h = hashlib.sha256(out.read_bytes()).hexdigest()
    print(f"  kept {kept} Homes dialogues -> {out.relative_to(ROOT)} (sha256 {h[:12]}, "
          f"{'matches the pin' if h == SGD_HOMES_SHA256 else 'DOES NOT MATCH the pin ' + SGD_HOMES_SHA256[:12]})")


def uci() -> None:
    print("[uci]")
    z = fetch(UCI_ZIP, RAW / "uci" / "apartment_for_rent_classified.zip", timeout=600)
    with zipfile.ZipFile(z) as zf:
        for n in zf.namelist():
            target = RAW / "uci" / Path(n).name
            if n.endswith("/") or target.exists():
                continue
            target.write_bytes(zf.read(n))
            # the UCI bundle nests a second zip on some mirrors
            if target.suffix == ".zip":
                with zipfile.ZipFile(target) as inner:
                    inner.extractall(RAW / "uci")
    import py7zr

    for a in (RAW / "uci").glob("*.7z"):
        with py7zr.SevenZipFile(a) as sz:
            names = [n for n in sz.getnames() if not (RAW / "uci" / Path(n).name).exists()]
            if names:
                sz.extract(path=RAW / "uci" / a.stem, targets=names)
    print("  files:", sorted(str(p.relative_to(RAW / "uci")) for p in (RAW / "uci").rglob("*") if p.is_file()))


def zori() -> None:
    print("[zori]")
    full = fetch(ZORI_CSV, RAW / "zori" / "Zip_zori_uc_sfrcondomfr_sm_month.csv")
    import pandas as pd

    df = pd.read_csv(full, dtype={"RegionName": str})
    nc = df[df["State"] == "NC"]
    out = RAW / "zori" / "zori_nc.csv"
    nc.to_csv(out, index=False)
    print(f"  {len(nc)} NC ZIP rows -> {out.relative_to(ROOT)}")


def airbnb() -> None:
    print("[airbnb]")
    html = requests.get(AIRBNB_PAGE, headers=UA, timeout=60).text
    links = re.findall(r'https://data\.insideairbnb\.com/united-states/nc/asheville/[0-9-]+/data/listings\.csv\.gz', html)
    if not links:
        print("  BLOCKED: no Asheville listings link found on get-the-data page")
        return
    url = sorted(set(links))[-1]
    snap = url.split("/")[-3]
    gz = fetch(url, RAW / "airbnb" / f"asheville_listings_{snap}.csv.gz")
    (RAW / "airbnb" / "SOURCE.txt").write_text(url + "\n")
    with gzip.open(gz, "rb") as f:
        n = sum(1 for _ in io.TextIOWrapper(f, encoding="utf-8", errors="replace"))
    print(f"  snapshot {snap}, ~{n} lines")


STREAM_SETS = {"nvidia/Nemotron-RL-Agentic-Conversational-Tool-Use-Pivot-v1": "train.jsonl"}


def stream_jsonl_head(repo: str, filename: str, max_rows: int = 20000) -> list[dict]:
    from huggingface_hub import hf_hub_url

    url = hf_hub_url(repo, filename, repo_type="dataset")
    rows: list[dict] = []
    with requests.get(url, headers=UA, stream=True, timeout=120) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if not line:
                continue
            row = json.loads(line)
            row["_config"], row["_split"] = None, "train"
            rows.append(row)
            if len(rows) >= max_rows:
                break
    print(f"  {repo}: streamed first {len(rows)} rows of {filename}")
    return rows


def hf() -> None:
    print("[hf]")
    from datasets import get_dataset_config_names, load_dataset

    for repo in HF_SETS:
        slug = repo.split("/")[-1]
        out = PROC / "hf_samples" / f"{slug}.sample2k.jsonl"
        if out.exists():
            print(f"  have {out.relative_to(ROOT)}")
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            configs = get_dataset_config_names(repo)
        except Exception as e:  # noqa: BLE001
            print(f"  {repo}: config lookup failed ({e}); trying default")
            configs = [None]
        rows: list[dict] = []
        if repo in STREAM_SETS:
            # 1.75 GB single jsonl whose card uses a feature type our pinned
            # `datasets` cannot parse: stream the head and sample from it.
            rows = stream_jsonl_head(repo, STREAM_SETS[repo])
            configs = []
        for cfg in configs:
            ds = load_dataset(repo, cfg, cache_dir=str(RAW / "hf_cache"))
            for split, part in ds.items():
                for r in part:
                    r = dict(r)
                    r["_config"], r["_split"] = cfg, split
                    rows.append(r)
        random.Random(0).shuffle(rows)
        with open(out, "w") as f:
            for r in rows[:2000]:
                f.write(json.dumps(r, default=str) + "\n")
        print(f"  {repo}: {len(rows)} rows total, sampled {min(2000, len(rows))} -> {out.relative_to(ROOT)}")


STEPS = {"sgd": sgd, "uci": uci, "zori": zori, "airbnb": airbnb, "hf": hf}

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=",".join(STEPS))
    args = ap.parse_args()
    failed = []
    for k in args.only.split(","):
        try:
            STEPS[k]()
        except Exception as e:  # noqa: BLE001
            print(f"  FAILED {k}: {e}")
            failed.append(k)
    if failed:
        print("failed:", failed)
        sys.exit(1)
