"""Publish the FULL reader training set (14,000 rows) the released reader-v1 checkpoint was trained on.

data/published/reader/train.jsonl keeps only the first 5,000 rows (PUBLISHED_TRAIN_CAP), which the Gym v1/v2
task builders read, so it is left as it is. The full file goes next to it, gzipped (deterministic: mtime 0),
and is checked against the hash recorded in docs/eval-protocol.md §6.1 / reader/MODEL_CARD.md.

    data/.venv/bin/python data/publish_reader_train.py            # write + verify (needs data/processed/reader/train.jsonl)
    data/.venv/bin/python data/publish_reader_train.py --check    # verify the published file only

Rebuild from scratch instead: data/download.py --only sgd (pinned SGD commit) then data/build_reader_set.py
(seed 7); the output data/processed/reader/train.jsonl must hash to TRAIN_SHA256.
License: CC BY-SA 4.0 (the file mixes SGD-derived rows), like the rest of data/published/reader/.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "processed" / "reader" / "train.jsonl"
DEST = ROOT / "published" / "reader" / "train_full.jsonl.gz"
TRAIN_SHA256 = "3d9237ef6e79f8a18bdd22fde1417b019b86eb318ae152239dfb22694a3d19b3"
TRAIN_ROWS = 14000


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def check() -> None:
    raw = gzip.decompress(DEST.read_bytes())
    rows = raw.count(b"\n")
    if sha(raw) != TRAIN_SHA256 or rows != TRAIN_ROWS:
        sys.exit(f"{DEST}: sha256 {sha(raw)} rows {rows}; expected {TRAIN_SHA256} rows {TRAIN_ROWS}")
    print(f"ok {DEST.relative_to(ROOT.parent)}: {rows} rows, sha256 {TRAIN_SHA256} (uncompressed)")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    if not a.check:
        raw = SRC.read_bytes()
        if sha(raw) != TRAIN_SHA256:
            sys.exit(f"{SRC} has sha256 {sha(raw)}, not the trained-on {TRAIN_SHA256}; rebuild it first")
        with open(DEST, "wb") as fh, gzip.GzipFile(filename="train_full.jsonl", mode="wb", fileobj=fh, mtime=0, compresslevel=9) as gz:
            gz.write(raw)
    check()


if __name__ == "__main__":
    main()
