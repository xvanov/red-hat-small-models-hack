"""Persona pool for twins: a seeded sample of nvidia/Nemotron-Personas-USA (CC BY 4.0).

Downloads one parquet shard (~245 MB) to data/raw/personas/ (gitignored) and writes a sample of
adult personas to data/processed/twins/personas_sample.jsonl. Re-running reuses both.

Usage: data/twins/.venv/bin/python data/twins/personas.py [--n 4000]
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from common import REPO

DATASET = "nvidia/Nemotron-Personas-USA"
SHARD = "data/train-00000-of-00011.parquet"
RAW = REPO / "data" / "raw" / "personas"
SAMPLE = REPO / "data" / "processed" / "twins" / "personas_sample.jsonl"
KEEP = ("uuid", "persona", "professional_persona", "hobbies_and_interests", "sex", "age", "marital_status",
        "education_level", "occupation", "city", "state")
LICENSE = "CC BY 4.0"


def build(n: int = 4000, seed: int = 11) -> Path:
    if SAMPLE.exists():
        return SAMPLE
    import pyarrow.parquet as pq
    from huggingface_hub import hf_hub_download
    path = hf_hub_download(DATASET, SHARD, repo_type="dataset", local_dir=RAW)
    t = pq.read_table(path, columns=[c for c in KEEP if c in pq.read_schema(path).names]).to_pylist()
    rows = [r for r in t if r.get("age") and 19 <= int(r["age"]) <= 68 and r.get("persona")]
    random.Random(seed).shuffle(rows)
    SAMPLE.parent.mkdir(parents=True, exist_ok=True)
    with open(SAMPLE, "w", encoding="utf-8") as f:
        for r in rows[:n]:
            f.write(json.dumps({k: r.get(k) for k in KEEP}, ensure_ascii=False) + "\n")
    return SAMPLE


def load() -> list[dict]:
    with open(build(), encoding="utf-8") as f:
        return [json.loads(l) for l in f]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=4000)
    p = build(ap.parse_args().n)
    rows = load()
    print(f"{len(rows)} personas in {p}; example fields: {sorted(rows[0])}")
