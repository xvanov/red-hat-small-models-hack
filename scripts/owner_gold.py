#!/usr/bin/env python3
"""Owner blind labels -> H2 gold (eval-protocol Amendment 1 A1a, Amendment 2 items 7/8).

    python3 scripts/owner_gold.py            # writes data/published/twins/owner_gold.jsonl + owner_gold_audit.json
    python3 scripts/owner_gold.py --check    # progress and consistency only, writes nothing; exit 1 if not ready

Inputs (from the blind labeler, labeler/server.py, which never shows a model label):
  labeler/out/owner_labels.jsonl   one record per sampled row: id, labeler "owner", mode, sample_sha256, skipped, output
  labeler/sample_manifest.json     the A1a sample: twin ids, row ids, row_ids_sha256, source sha256
  data/published/twins/reader_test.jsonl   the twin reader test the sample was drawn from

Rules (fixed before any label is read):
  - the manifest must match the source file (source_sha256) and its own id list (row_ids_sha256);
  - every label must be mode "real", labeler "owner", carry the manifest's sample_sha256, and name a sampled row;
  - EVERY sampled row must have a record (a label or an explicit skip); otherwise nothing is written and H2a/H2b
    are not tested (A1a). No partial gold, no re-sampling;
  - a skipped row (owner could not tell) is left out of the gold and counted;
  - gold row = the source row's id, source, input and meta with `output` replaced by the owner's label;
    meta.gold = "owner", meta.unscorable = [] (the owner's label is complete by construction), and the twin
    pipeline's own label is NOT carried into the gold file;
  - owner_gold_audit.json: per-field agreement of the twin pipeline's gold (made by the fine-tuned reader) with the
    owner on the same rows, i.e. an audit of the twin task gold (round-2 N1), reported, never used to edit gold.
Pure stdlib.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LABELS = REPO / "labeler/out/owner_labels.jsonl"
MANIFEST = REPO / "labeler/sample_manifest.json"
SOURCE = REPO / "data/published/twins/reader_test.jsonl"
OUT = REPO / "data/published/twins/owner_gold.jsonl"
AUDIT = REPO / "data/published/twins/owner_gold_audit.json"
FIELDS = ("lease", "move_in", "phone", "occupants", "reason", "intents", "language")


class NotReady(Exception):
    pass


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def read_jsonl(p: Path) -> list[dict]:
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def field_key(out: dict, f: str):
    """Comparable value of one field: status plus value; reason on status only (A1)."""
    v = out.get(f)
    if f == "intents":
        return tuple(sorted(v or []))
    if f == "language":
        return v
    v = v or {}
    if f == "reason":
        return v.get("status")
    if f == "move_in":
        return v.get("status"), v.get("date")
    return v.get("status"), v.get("value")


def build(labels: list[dict], manifest: dict, source_rows: list[dict], source_sha256: str) -> tuple[list[dict], dict]:
    """Pure: returns (gold rows in sample order, audit). Raises NotReady with every problem found."""
    problems = []
    if manifest.get("source_sha256") != source_sha256:
        problems.append("sample manifest was drawn from a different reader_test.jsonl (source_sha256 mismatch)")
    ids = manifest.get("row_ids") or []
    if hashlib.sha256("\n".join(ids).encode()).hexdigest() != manifest.get("row_ids_sha256"):
        problems.append("manifest row_ids do not match row_ids_sha256")
    if manifest.get("mode", "real") != "real":
        problems.append(f"manifest mode is {manifest.get('mode')!r}, not 'real'")
    by_src = {r["id"]: r for r in source_rows}
    missing_src = [i for i in ids if i not in by_src]
    if missing_src:
        problems.append(f"{len(missing_src)} sampled ids not in the source file, e.g. {missing_src[:3]}")
    sample = set(ids)
    seen: dict[str, dict] = {}
    for rec in labels:
        rid = rec.get("id")
        if rid in seen:
            problems.append(f"duplicate label for {rid}")
        seen[rid] = rec
        if rid not in sample:
            problems.append(f"label for {rid}, which is not in the sample")
        if rec.get("labeler") != "owner":
            problems.append(f"{rid}: labeler is {rec.get('labeler')!r}, not 'owner'")
        if rec.get("mode") != "real":
            problems.append(f"{rid}: label mode is {rec.get('mode')!r}, not 'real'")
        if rec.get("sample_sha256") != manifest.get("row_ids_sha256"):
            problems.append(f"{rid}: label was saved against a different sample")
        if not rec.get("skipped") and not isinstance(rec.get("output"), dict):
            problems.append(f"{rid}: not skipped but has no output")
    unlabeled = [i for i in ids if i not in seen]
    if unlabeled:
        problems.append(f"{len(unlabeled)} of {len(ids)} sampled rows not labeled yet (first: {unlabeled[0]})")
    if problems:
        raise NotReady("\n".join(problems))

    gold, agree, n_cmp, skipped = [], Counter(), Counter(), []
    for rid in ids:
        rec, src = seen[rid], by_src[rid]
        if rec.get("skipped"):
            skipped.append(rid)
            continue
        meta = {k: v for k, v in (src.get("meta") or {}).items() if k not in ("unscorable", "flagged", "labeler")}
        meta.update(gold="owner", unscorable=[], owner_label_ts=rec.get("ts"))
        gold.append({"id": rid, "source": src.get("source"), "input": src["input"], "output": rec["output"], "meta": meta})
        twin = src.get("output") or {}
        for f in FIELDS:
            n_cmp[f] += 1
            agree[f] += field_key(twin, f) == field_key(rec["output"], f)
    threads = {(r["meta"] or {}).get("twin_id") or r["id"] for r in gold}
    audit = {
        "what": "agreement of the twin pipeline's reader-test gold (labels by the fine-tuned reader) with the owner's "
                "blind labels, same rows; status+value per field, reason on status only, intents as a set",
        "source": str(SOURCE.relative_to(REPO)), "source_sha256": source_sha256,
        "sample_row_ids_sha256": manifest.get("row_ids_sha256"),
        "sampled_rows": len(ids), "sampled_threads": len(manifest.get("twin_ids") or []),
        "gold_rows": len(gold), "gold_threads": len(threads), "skipped_by_owner": len(skipped),
        "twin_gold_vs_owner": {f: {"agree": agree[f], "n": n_cmp[f],
                                   "rate": round(agree[f] / n_cmp[f], 4) if n_cmp[f] else None} for f in FIELDS},
        "twin_gold_exact_row_match": None,
    }
    if gold:
        exact = sum(all(field_key(by_src[g["id"]].get("output") or {}, f) == field_key(g["output"], f) for f in FIELDS)
                    for g in gold)
        audit["twin_gold_exact_row_match"] = {"agree": exact, "n": len(gold), "rate": round(exact / len(gold), 4)}
    return gold, audit


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--labels", type=Path, default=LABELS)
    ap.add_argument("--manifest", type=Path, default=MANIFEST)
    ap.add_argument("--source", type=Path, default=SOURCE)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--audit", type=Path, default=AUDIT)
    ap.add_argument("--check", action="store_true", help="report readiness only; write nothing")
    a = ap.parse_args(argv)
    for p in (a.manifest, a.source, a.labels):
        if not p.exists():
            print(f"not ready: {p} does not exist")
            return 1
    try:
        gold, audit = build(read_jsonl(a.labels), json.loads(a.manifest.read_text()), read_jsonl(a.source),
                            sha256_file(a.source))
    except NotReady as e:
        print("not ready:\n" + str(e))
        return 1
    summary = {k: audit[k] for k in ("sampled_rows", "gold_rows", "gold_threads", "skipped_by_owner")}
    if a.check:
        print(json.dumps({"ready": True, **summary}))
        return 0
    if a.out.exists():
        print(f"refusing to overwrite {a.out}: the owner gold is written once (delete it deliberately to rebuild)")
        return 1
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in gold))
    audit["owner_gold_sha256"] = sha256_file(a.out)
    a.audit.write_text(json.dumps(audit, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps({"wrote": str(a.out), "sha256": audit["owner_gold_sha256"], **summary}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
