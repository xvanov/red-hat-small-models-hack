"""Publish the project's open datasets to Hugging Face (dry run unless --push).

Two public dataset repos under the account that owns HF_TOKEN (.env):
  <ns>/rentus-reader-messages   reader set, data/published/reader/          CC BY-SA 4.0
  <ns>/rentus-leasing-twins     twins, owner gold, Gym task sets v1-v3      CC BY 4.0

Files are uploaded byte-for-byte from the repo (frozen evaluation files are never touched);
each repo also gets its dataset card (data/hf/<name>/README.md) and a SHA256SUMS file.
After upload every file is downloaded back and its sha256 compared with the local file.

  data/.venv/bin/python data/hf/publish_datasets.py                 # dry run: list files + hashes
  data/.venv/bin/python data/hf/publish_datasets.py --push          # create/update repos, upload, verify
  data/.venv/bin/python data/hf/publish_datasets.py --verify-only   # re-check hashes on the Hub
"""
from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
NS = "xvanov"

# repo name -> list of (path in HF repo, local path relative to REPO)
DATASETS: dict[str, list[tuple[str, str]]] = {
    "rentus-reader-messages": [
        ("data/train_full.jsonl.gz", "data/published/reader/train_full.jsonl.gz"),
        ("data/train.jsonl", "data/published/reader/train.jsonl"),
        ("data/dev.jsonl", "data/published/reader/dev.jsonl"),
        ("data/test.jsonl", "data/published/reader/test.jsonl"),
        ("stats.json", "data/published/reader/stats.json"),
    ],
    "rentus-leasing-twins": [
        ("twins/twins.jsonl", "data/published/twins/twins.jsonl"),
        ("twins/reader_test.jsonl", "data/published/twins/reader_test.jsonl"),
        ("twins/reader_test_labeled_0548.jsonl", "data/published/twins/reader_test_labeled_0548.jsonl"),
        ("twins/owner_gold.jsonl", "data/published/twins/owner_gold.jsonl"),
        ("twins/owner_gold_audit.json", "data/published/twins/owner_gold_audit.json"),
        ("twins/stats_card.json", "data/published/twins/stats_card.json"),
        ("twins/filter_report.json", "data/published/twins/filter_report.json"),
        ("twins/tasks_stats.json", "data/published/twins/tasks_stats.json"),
        ("owner_gold_combined.jsonl", "data/published/owner_gold_combined.jsonl"),
        ("owner_gold_combined.json", "data/published/owner_gold_combined.json"),
        ("gym_tasks/v3/heldout.jsonl", "gym/tasks/v3/heldout.jsonl"),
        ("gym_tasks/v3/heldout_ops.jsonl", "gym/tasks/v3/heldout_ops.jsonl"),
        ("gym_tasks/v2/train.jsonl", "gym/tasks/v2/train.jsonl"),
        ("gym_tasks/v2/heldout.jsonl", "gym/tasks/v2/heldout.jsonl"),
        ("gym_tasks/v2/stats.json", "gym/tasks/v2/stats.json"),
        ("gym_tasks/v1/train.jsonl", "gym/tasks/train.jsonl"),
        ("gym_tasks/v1/heldout.jsonl", "gym/tasks/heldout.jsonl"),
        ("gym_tasks/v1/stats.json", "gym/tasks/stats.json"),
    ],
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_env(path: Path = REPO / ".env") -> None:
    """KEY=VALUE lines into os.environ; never prints anything."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def git_head() -> str:
    try:
        return subprocess.check_output(["git", "-C", str(REPO), "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def sums_text(files: list[tuple[str, str]]) -> str:
    lines = [f"# sha256 of each file; the local source path in https://github.com/{NS}/red-hat-small-models-hack "
             f"(at commit {git_head()}) follows '<-'"]
    for dst, src in files:
        lines.append(f"{sha256(REPO / src)}  {dst}  <- {src}")
    return "\n".join(lines) + "\n"


def verify(api, repo_id: str, files: list[tuple[str, str]], token: str) -> bool:
    from huggingface_hub import hf_hub_download
    ok = True
    with tempfile.TemporaryDirectory() as tmp:
        for dst, src in files:
            p = hf_hub_download(repo_id, dst, repo_type="dataset", token=token, local_dir=tmp, force_download=True)
            remote, local = sha256(Path(p)), sha256(REPO / src)
            good = remote == local
            ok &= good
            print(f"  {'OK ' if good else 'BAD'} {dst}  {remote[:16]}")
    return ok


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--push", action="store_true", help="actually create the repos and upload (owner approved)")
    ap.add_argument("--verify-only", action="store_true")
    ap.add_argument("--only", choices=list(DATASETS), help="one dataset only")
    ap.add_argument("--private", action="store_true")
    a = ap.parse_args()

    names = [a.only] if a.only else list(DATASETS)
    for name in names:
        for _, src in DATASETS[name]:
            if not (REPO / src).exists():
                sys.exit(f"missing {src}")
        assert (HERE / name / "README.md").exists(), f"missing card data/hf/{name}/README.md"
        print(f"{NS}/{name}:")
        for dst, src in DATASETS[name]:
            print(f"  {dst:42s} {sha256(REPO / src)[:16]}  {(REPO / src).stat().st_size:>9} B")

    if not (a.push or a.verify_only):
        print("dry run; pass --push to upload")
        return

    load_env()
    token = os.environ.get("HF_TOKEN")
    if not token:
        sys.exit("HF_TOKEN is not set in .env")
    from huggingface_hub import CommitOperationAdd, HfApi
    api = HfApi(token=token)

    all_ok = True
    for name in names:
        repo_id = f"{NS}/{name}"
        files = DATASETS[name]
        if a.push:
            api.create_repo(repo_id, repo_type="dataset", private=a.private, exist_ok=True)
            ops = [CommitOperationAdd(path_in_repo=dst, path_or_fileobj=str(REPO / src)) for dst, src in files]
            ops.append(CommitOperationAdd(path_in_repo="README.md", path_or_fileobj=str(HERE / name / "README.md")))
            ops.append(CommitOperationAdd(path_in_repo="SHA256SUMS", path_or_fileobj=sums_text(files).encode()))
            info = api.create_commit(repo_id, ops, repo_type="dataset",
                                     commit_message=f"Publish {name} from github.com/{NS}/red-hat-small-models-hack@{git_head()[:7]}")
            print(f"uploaded {repo_id}: {info.commit_url}")
        print(f"verifying {repo_id}")
        all_ok &= verify(api, repo_id, files + [("README.md", str((HERE / name / 'README.md').relative_to(REPO)))], token)
        print(f"https://huggingface.co/datasets/{repo_id}")
    if not all_ok:
        sys.exit("hash mismatch")


if __name__ == "__main__":
    main()
