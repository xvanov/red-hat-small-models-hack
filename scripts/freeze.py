#!/usr/bin/env python3
"""Freeze commit helper (docs/FREEZE.md, eval-protocol Amendment 2 item 11 / round-2 N13).

    python3 scripts/freeze.py            # = --check: what is present, what is missing; exit 1 if not freezable
    python3 scripts/freeze.py --write    # writes docs/freeze-manifest.json (refuses unless --check passes)

Then ONE commit holding docs/freeze-manifest.json (and every artifact it names that is tracked) is the freeze
commit. gym/frozen.py takes the freeze commit to be the last commit that touched docs/freeze-manifest.json, and
gym/stats.py counts a confirmatory run only if its frozen paths match that commit (see gym/frozen.py).

What it records: sha256 of every frozen artifact (task sets, reader test + owner gold + sample manifest, reader
checkpoint, serving config and launch scripts, confirmatory plan and stats code, scorer and prompt files, the
trivial-agent floors), a content hash of every frozen path tree (gym/frozen_paths.txt), and the owner sign-offs
found in docs/DECISIONS.md as lines containing `FREEZE-SIGNOFF <id>`. Pure stdlib; no model calls.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MANIFEST = REPO / "docs/freeze-manifest.json"
DECISIONS = REPO / "docs/DECISIONS.md"
PRIVATE = Path(os.environ.get("RENTUS_PRIVATE_DIR", Path.home() / "rentus-private-data"))

# (path, role, required). Optional = a missing file makes the dependent hypothesis "not tested", never blocks.
ARTIFACTS: list[tuple[str, str, bool]] = [
    ("gym/tasks/v3/heldout.jsonl", "task set: v3 held-out (H1, H3, H4)", True),
    ("gym/tasks/v3/heldout_ops.jsonl", "task set: v3 held-out ops (experimental, secondary)", False),
    ("data/published/twins/twins.jsonl", "task set: published twins", True),
    ("data/published/twins/reader_test.jsonl", "reader test (twin, reader gold; secondary H2 set)", True),
    ("data/twins/splits.json", "split record + to_tasks frozen_sha256", True),
    ("labeler/sample_manifest.json", "A1a sample drawn by the blind labeler", True),
    ("data/published/twins/owner_gold.jsonl", "H2 gold: owner blind labels (H2a/H2b not tested if absent)", False),
    ("data/published/twins/owner_gold_audit.json", "twin gold vs owner audit", False),
    ("reader/release/rentus-reader/model.safetensors", "reader checkpoint reader-v1 (local, gitignored)", True),
    ("serving/FROZEN.json", "serving config", True),
    ("serving/start_vllm.sh", "serving launch: Lightning", True),
    ("reader/serve_reader.sh", "serving launch: reader", True),
    ("gym/confirmatory_v3.json", "confirmatory plan", True),
    ("gym/stats.py", "confirmatory statistics", True),
    ("gym/frozen.py", "run gate", True),
    ("gym/frozen_paths.txt", "frozen path list", True),
    ("gym/rentus_env/verify.py", "scorer", True),
    ("gym/rentus_env/v3_rules.py", "scorer: v3 rules", True),
    ("tools/rentus_tools/impl/inbox.py", "sandbox inbox tool", True),
    ("operator/prompts/system_v3.md", "operator prompt (prompt3)", True),
    ("operator/prompts/system_v4.md", "operator prompt v4 (final config, Amendment 6)", True),
    ("reader/prompt.py", "reader prompt", True),
    ("docs/eval-protocol.md", "protocol incl. amendments", True),
    ("gym/results/v3-floors.json", "trivial-agent floors (gym/floors.py --tasks-file gym/tasks/v3/heldout.jsonl --json)", True),
]
PRIVATE_ARTIFACTS = [  # hash only; the file stays private (protocol 2.5.2)
    ("work/replay/thread_ids.json", "replay thread-id list (H6; hash only)", False),
]
SIGNOFFS = [  # id, what the owner confirms; all required before --write
    ("blind-labels", "A1a: blind H2 labels finished in the labeler (or the owner declares H2 not tested)"),
    ("realism-7.1", "7.1: blind twin realism review done and passed (or v3 reported 'realism not confirmed')"),
    ("label-check-7.2", "7.2: blind label check of task-deciding labels (P-6), result recorded"),
    ("playbooks-7.4", "7.4: playbooks and the 45-day showing window approved as scoring sources (or dropped)"),
    ("protocol-7.5", "7.5: protocol incl. Amendments 1 and 2 signed off"),
    ("cutoff-N12", "N12: cut-off time for owner work, after which missing work = not tested"),
]
EXPECTED_READER_SHA = "877c884355584ed5c78caaca741e33cc438037f2dc80cb991119c97476dc2ec6"


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git(*a: str) -> str:
    return subprocess.check_output(["git", *a], cwd=REPO, text=True, stderr=subprocess.DEVNULL).strip()


def frozen_paths() -> list[str]:
    txt = (REPO / "gym/frozen_paths.txt").read_text().splitlines()
    return [l.strip() for l in txt if l.strip() and not l.lstrip().startswith("#")]


def tree_hash(rel: str) -> dict:
    """sha256 over (path, file sha256) of every tracked or untracked-not-ignored file under rel."""
    files = [f for f in git("ls-files", "-co", "--exclude-standard", "--", rel).splitlines() if f]
    h = hashlib.sha256()
    for f in sorted(files):
        p = REPO / f
        if p.is_file():
            h.update(f.encode() + b"\0" + sha256_file(p).encode() + b"\n")
    return {"files": len(files), "sha256": h.hexdigest()}


def signoffs() -> dict[str, str | None]:
    lines = DECISIONS.read_text().splitlines() if DECISIONS.exists() else []
    out = {}
    for sid, _ in SIGNOFFS:
        hit = next((l.strip() for l in lines if f"FREEZE-SIGNOFF {sid}" in l), None)
        out[sid] = hit[:300] if hit else None
    return out


def collect() -> dict:
    arts, missing_req, missing_opt, problems = {}, [], [], []
    for rel, role, req in ARTIFACTS:
        p = REPO / rel
        if p.is_file():
            arts[rel] = {"sha256": sha256_file(p), "bytes": p.stat().st_size, "role": role}
        else:
            (missing_req if req else missing_opt).append(f"{rel}  ({role})")
    for rel, role, req in PRIVATE_ARTIFACTS:
        p = PRIVATE / rel
        if p.is_file():
            arts[f"private:{rel}"] = {"sha256": sha256_file(p), "bytes": p.stat().st_size, "role": role}
        else:
            (missing_req if req else missing_opt).append(f"private:{rel}  ({role})")
    ck = arts.get("reader/release/rentus-reader/model.safetensors")
    if ck and ck["sha256"] != EXPECTED_READER_SHA:
        problems.append(f"reader checkpoint sha256 {ck['sha256'][:12]} is not release reader-v1 ({EXPECTED_READER_SHA[:12]})")
    try:
        fz = json.loads((REPO / "serving/FROZEN.json").read_text())
        for key, rel in (("operator", "serving/start_vllm.sh"), ("reader", "reader/serve_reader.sh")):
            if rel in arts and fz[key]["launch_script_sha256"] != arts[rel]["sha256"]:
                problems.append(f"{rel} changed since serving/FROZEN.json was written")
        if ck and fz["reader"]["model_safetensors_sha256"] != ck["sha256"]:
            problems.append("reader checkpoint differs from serving/FROZEN.json")
        if any("TO CONFIRM" in str(v) for v in (fz["image"].get("digest_source"), fz["operator"].get("revision_source"))):
            problems.append("serving/FROZEN.json still has TO CONFIRM values (image digest / revision from the instance)")
    except (OSError, KeyError, ValueError) as e:
        problems.append(f"serving/FROZEN.json unreadable: {e}")
    dirty = [l for l in git("status", "--porcelain", "--", *frozen_paths()).splitlines() if l]
    if dirty:
        problems.append(f"{len(dirty)} dirty file(s) under frozen paths, e.g. {dirty[:4]}")
    so = signoffs()
    return {"artifacts": arts, "missing_required": missing_req, "missing_optional": missing_opt,
            "problems": problems, "signoffs": so, "missing_signoffs": [k for k, v in so.items() if not v],
            "frozen_path_trees": {rel: tree_hash(rel) for rel in frozen_paths()}}


def report(c: dict) -> str:
    out = [f"artifacts present: {len(c['artifacts'])}"]
    for k, v in c["artifacts"].items():
        out.append(f"  ok       {v['sha256'][:16]}  {k}")
    out += [f"  MISSING  (required)  {m}" for m in c["missing_required"]]
    out += [f"  absent   (optional)  {m}" for m in c["missing_optional"]]
    out.append("owner sign-offs (docs/DECISIONS.md, a line containing `FREEZE-SIGNOFF <id>`):")
    for sid, what in SIGNOFFS:
        out.append(f"  {'ok     ' if c['signoffs'][sid] else 'MISSING'}  {sid}: {what}")
    out += [f"problem: {p}" for p in c["problems"]]
    ready = not (c["missing_required"] or c["missing_signoffs"] or c["problems"])
    out.append("FREEZABLE" if ready else
               f"NOT FREEZABLE: {len(c['missing_required'])} required artifact(s), {len(c['missing_signoffs'])} sign-off(s), "
               f"{len(c['problems'])} problem(s)")
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true", help="default: report only, write nothing")
    g.add_argument("--write", action="store_true", help="write docs/freeze-manifest.json if freezable")
    ap.add_argument("--record-missing-signoffs", action="store_true",
                    help="Amendment 6: freeze although owner sign-offs are missing; they are recorded in the manifest as "
                         "missing_signoffs_at_freeze and the consequence in docs/FREEZE.md section 1 applies to each. "
                         "Artifacts and problems still block.")
    a = ap.parse_args(argv)
    c = collect()
    print(report(c))
    blocking_signoffs = [] if a.record_missing_signoffs else c["missing_signoffs"]
    ready = not (c["missing_required"] or blocking_signoffs or c["problems"])
    if not a.write:
        return 0 if ready else 1
    if not ready:
        print("refusing to write the manifest")
        return 1
    if MANIFEST.exists():
        print(f"refusing: {MANIFEST.relative_to(REPO)} exists; a second freeze is a new protocol version (docs/FREEZE.md)")
        return 1
    man = {"_note": "Freeze manifest (docs/FREEZE.md). The commit that adds this file is the freeze commit.",
           "written_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "parent_commit": git("rev-parse", "HEAD"),
           "artifacts": c["artifacts"], "absent_optional": c["missing_optional"],
           "frozen_paths": frozen_paths(), "frozen_path_trees": c["frozen_path_trees"], "signoffs": c["signoffs"],
           "missing_signoffs_at_freeze": c["missing_signoffs"]}
    MANIFEST.write_text(json.dumps(man, indent=1, ensure_ascii=False) + "\n")
    print(f"wrote {MANIFEST.relative_to(REPO)}; now commit it (and nothing else) as the freeze commit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
