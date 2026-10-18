"""Freeze bookkeeping shared by run_eval (refuse to start), stats.py (refuse to count) and scripts/freeze.py.

eval-protocol Amendment 2 (round-2 items N3/N4). A confirmatory run counts only if its summary.json shows:
  - not void, no still_failed rollouts (gym/ablate.py rerun rule, A8);
  - provenance.dirty_frozen_paths is false (nothing under gym/frozen_paths.txt was dirty at run time);
  - provenance.commit is the freeze commit, or a later commit whose frozen paths are byte-identical to it
    (`git diff --quiet <freeze> <run> -- <frozen paths>`; the same test scripts/frontier_ref.sh applies), so
    unrelated commits by other lanes (console, docs) during the runs do not void anything, and any change to a
    frozen path does;
  - provenance.tasks_sha256 equals the frozen sha256 of the task file it ran (when the manifest lists it).
The freeze commit is the commit that last touched docs/freeze-manifest.json (written by scripts/freeze.py
--write, committed once). No manifest -> no freeze commit -> no run counts.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Callable

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
PATHS_FILE = HERE / "frozen_paths.txt"
MANIFEST = REPO / "docs" / "freeze-manifest.json"


def frozen_paths() -> list[str]:
    return [l.strip() for l in PATHS_FILE.read_text().splitlines() if l.strip() and not l.lstrip().startswith("#")]


def _git(*a: str) -> str | None:
    try:
        return subprocess.check_output(["git", *a], cwd=REPO, text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:  # noqa: BLE001
        return None


def dirty_frozen() -> list[str]:
    """`git status --porcelain` lines under the frozen paths (untracked files included)."""
    out = _git("status", "--porcelain", "--", *frozen_paths())
    return (out or "").splitlines()


def load_manifest() -> dict | None:
    return json.loads(MANIFEST.read_text()) if MANIFEST.exists() else None


def freeze_commit() -> str | None:
    """Full sha of the commit that last touched the freeze manifest, or None if it was never committed."""
    if not MANIFEST.exists():
        return None
    return _git("log", "-n", "1", "--format=%H", "--", str(MANIFEST.relative_to(REPO))) or None


def frozen_paths_identical(a: str, b: str) -> bool:
    if a == b:
        return True
    try:
        r = subprocess.run(["git", "diff", "--quiet", a, b, "--", *frozen_paths()], cwd=REPO,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:  # noqa: BLE001
        return False
    return r.returncode == 0   # 1 = differs, 128 = unknown commit


def freeze_state() -> dict:
    """What the run gate compares against: the freeze commit and the frozen task-file hashes."""
    man = load_manifest() or {}
    tasks = {k: v["sha256"] for k, v in (man.get("artifacts") or {}).items()
             if isinstance(v, dict) and v.get("sha256") and k.endswith(".jsonl")}
    return {"commit": freeze_commit(), "artifact_sha256": tasks}


def reader_preds_problems(preds_path: str, freeze: dict, gold_rel: str = "data/published/twins/owner_gold.jsonl") -> list[str]:
    """H2 preds count only if their metrics file says they scored the frozen owner gold (Amendment 2, items 7/8)."""
    want = (freeze.get("artifact_sha256") or {}).get(gold_rel)
    if not want:
        return [f"{gold_rel} is not in the freeze manifest (H2 not tested)"]
    mp = Path(str(preds_path).replace(".preds.jsonl", ".metrics.json"))
    if not mp.exists():
        return [f"no metrics file {mp.name} next to the preds"]
    got = (json.loads(mp.read_text()).get("provenance") or {}).get("data_sha256")
    return [] if got == want else [f"scored rows sha256 {str(got)[:12]} is not the frozen owner gold {want[:12]}"]


def run_problems(summary: dict | None, freeze: dict,
                 same_frozen: Callable[[str, str], bool] = frozen_paths_identical) -> list[str]:
    """Reasons a run may not enter the confirmatory analysis (empty list = the run counts). Pure given `same_frozen`."""
    if summary is None:
        return ["no summary.json"]
    out = []
    mer = summary.get("model_error_retries")
    if mer is None:
        out.append("no rerun record (model_error_retries): not launched through ablate.run_variant / run_seeds.py")
        mer = {}
    if mer.get("void"):
        out.append("void (> 10% mid-rollout endpoint drops)")
    if mer.get("still_failed"):
        out.append(f"{len(mer['still_failed'])} rollout(s) never reached the model after retries (still_failed)")
    prov = summary.get("provenance")
    if not prov:
        return out + ["no provenance in summary.json"]
    for i, rp in enumerate(mer.get("retry_provenance") or []):   # rerun rollouts must meet the same rules
        for why in run_problems({"model_error_retries": {}, "provenance": rp}, freeze, same_frozen):
            out.append(f"retry {i + 1}: {why}")
    if prov.get("dirty_frozen_paths") is not False:
        out.append("frozen paths dirty at run time" if prov.get("dirty_frozen_paths") else "dirty_frozen_paths not recorded")
    fc, rc = freeze.get("commit"), prov.get("commit")
    if not fc:
        out.append("no freeze commit (docs/freeze-manifest.json not committed)")
    elif not rc:
        out.append("run commit not recorded")
    elif rc != fc and not same_frozen(fc, rc):
        out.append(f"run commit {rc[:10]} differs from freeze commit {fc[:10]} on frozen paths")
    tp, ts = prov.get("tasks_path"), prov.get("tasks_sha256")
    want = None
    for k, v in (freeze.get("artifact_sha256") or {}).items():
        if tp and (str(tp) == k or str(tp).endswith("/" + k)):
            want = v
    if want and ts != want:
        out.append(f"task file sha256 {str(ts)[:12]} is not the frozen {want[:12]}")
    return out
