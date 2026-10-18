#!/usr/bin/env python3
"""Combined H2 gold (eval-protocol Amendment 7): 61 real-twin owner labels + 29 pilot owner labels = 90 rows.

    python3 scripts/owner_gold_combined.py          # writes data/published/owner_gold_combined.jsonl + .json record
    python3 scripts/owner_gold_combined.py --check  # validate only

Real-twin part: data/published/twins/owner_gold.jsonl exactly as frozen (its sha256 must equal the freeze manifest's).
Pilot part: labeler/out/owner_labels.fixture.jsonl (latest label per item, mode "fixture", labeler "owner") on the
29-row practice sample labeler/sample_manifest.fixture.json drawn from data/twins/fixtures/out/published/reader_test.jsonl
(agent-written fictional conversations, not derived from real data). Same validation rules as scripts/owner_gold.py
except the mode, which must be "fixture" here. Every row gets meta.h2_source ("real_twin" | "pilot") and
meta.informative (owner gold has at least one gate field lease/move_in/phone/occupants/reason not "absent").
Cluster ids (meta.twin_id) are prefixed by source so a real and a pilot thread can never share a cluster.
Pure stdlib; no model calls.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
REAL = REPO / "data/published/twins/owner_gold.jsonl"
PILOT_LABELS = REPO / "labeler/out/owner_labels.fixture.jsonl"
PILOT_MANIFEST = REPO / "labeler/sample_manifest.fixture.json"
PILOT_SOURCE = REPO / "data/twins/fixtures/out/published/reader_test.jsonl"
OUT = REPO / "data/published/owner_gold_combined.jsonl"
RECORD = REPO / "data/published/owner_gold_combined.json"
GATE = ("lease", "move_in", "phone", "occupants", "reason")


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def rows(p: Path) -> list[dict]:
    return [json.loads(l) for l in open(p) if l.strip()]


def informative(out: dict) -> bool:
    return any(((out.get(f) or {}).get("status") or "absent") != "absent" for f in GATE)


def build() -> tuple[list[dict], dict]:
    problems = []
    man = json.loads((REPO / "docs/freeze-manifest.json").read_text())
    want = man["artifacts"]["data/published/twins/owner_gold.jsonl"]["sha256"]
    if sha(REAL) != want:
        problems.append("owner_gold.jsonl differs from the frozen one")
    pm = json.loads(PILOT_MANIFEST.read_text())
    if pm.get("source_sha256") != sha(PILOT_SOURCE):
        problems.append("pilot manifest source_sha256 mismatch")
    ids = pm.get("row_ids") or []
    if hashlib.sha256("\n".join(ids).encode()).hexdigest() != pm.get("row_ids_sha256"):
        problems.append("pilot manifest row_ids do not match row_ids_sha256")
    src = {r["id"]: r for r in rows(PILOT_SOURCE)}
    latest: dict[str, dict] = {}
    for rec in rows(PILOT_LABELS):   # file order = save order; the last record per id wins
        if rec.get("labeler") != "owner" or rec.get("mode") != "fixture" or rec.get("sample_sha256") != pm.get("row_ids_sha256"):
            problems.append(f"pilot label {rec.get('id')}: not an owner fixture label on this sample")
        latest[rec["id"]] = rec
    missing = [i for i in ids if i not in latest]
    if missing:
        problems.append(f"{len(missing)} pilot rows unlabeled")
    extra = [i for i in latest if i not in set(ids)]
    if extra:
        problems.append(f"{len(extra)} pilot labels outside the sample")
    if problems:
        raise SystemExit("NOT READY:\n" + "\n".join(problems))
    out = []
    for r in rows(REAL):
        m = dict(r["meta"])
        m.update(h2_source="real_twin", informative=informative(r["output"]), twin_id="real:" + (m.get("twin_id") or r["id"]))
        out.append({**r, "meta": m})
    skipped = 0
    for i in ids:
        rec, s = latest[i], src[i]
        if rec.get("skipped"):
            skipped += 1
            continue
        m = {k: v for k, v in (s.get("meta") or {}).items() if k not in ("unscorable", "flagged", "labeler")}
        m.update(gold="owner", unscorable=[], owner_label_ts=rec.get("ts"), reason_scored_on="status",
                 h2_source="pilot", informative=informative(rec["output"]),
                 twin_id="pilot:" + (m.get("twin_id") or m.get("thread_id") or i))
        out.append({"id": i, "source": s.get("source"), "input": s["input"], "output": rec["output"], "meta": m})
    by = lambda k, v: [r for r in out if r["meta"][k] == v]
    rec = {"what": "eval-protocol Amendment 7: combined H2 gold, 61 real-twin + 29 pilot owner labels",
           "real_twin_gold": "data/published/twins/owner_gold.jsonl", "real_twin_gold_sha256": want,
           "pilot_source": str(PILOT_SOURCE.relative_to(REPO)), "pilot_source_sha256": sha(PILOT_SOURCE),
           "pilot_labels_sha256": sha(PILOT_LABELS), "pilot_sample_row_ids_sha256": pm["row_ids_sha256"],
           "rows": len(out), "threads": len({r["meta"]["twin_id"] for r in out}), "pilot_skipped": skipped,
           "by_source": {s: {"rows": len(by("h2_source", s)), "threads": len({r["meta"]["twin_id"] for r in by("h2_source", s)}),
                             "informative_rows": sum(r["meta"]["informative"] for r in by("h2_source", s))}
                         for s in ("real_twin", "pilot")},
           "informative_rows": len(by("informative", True)),
           "informative_definition": "owner gold has at least one of lease/move_in/phone/occupants/reason with status != absent"}
    return out, rec


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    out, rec = build()
    if not a.check:
        if OUT.exists():
            print(f"refusing: {OUT.relative_to(REPO)} exists (written once)")
            return 1
        with open(OUT, "w") as f:
            for r in out:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        rec["sha256"] = sha(OUT)
        RECORD.write_text(json.dumps(rec, indent=1) + "\n")
    print(json.dumps(rec, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
