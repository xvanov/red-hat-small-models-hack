"""W5 step 3: translate SGD Homes renter turns (and their thread context) to Spanish.

Runs against the OpenAI-compatible vLLM endpoint that serves the operator model.
It is the operator model itself (already in the parameter budget), so no extra
model is added. Plan and caveats: data/translate_es.md.

Env (read by name only, never printed):
  OPERATOR_BASE_URL   e.g. http://host:8000/v1
  OPERATOR_MODEL      served model name
  OPERATOR_API_KEY    optional bearer token

Input : data/processed/reader/{train,dev,test}.jsonl  (rows with source == "sgd")
Output: data/processed/reader/sgd_es_{split}.jsonl     (source "sgd_es", same split,
        same labels except language="es"; SGD test stays test)

Usage:
  data/.venv/bin/python data/translate_es.py --dry-run          # show 3 prompts, no calls
  data/.venv/bin/python data/translate_es.py --limit 200        # translate 200 per split
Then: data/.venv/bin/python data/build_reader_set.py --with-sgd-es
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import re
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
PROC = ROOT / "processed" / "reader"

SYSTEM = (
    "You translate short rental-inquiry chat messages from English to natural, informal Latin American Spanish "
    "as a renter would text it. Keep every number, date, phone number, street and place name exactly as written. "
    "Do not add or remove information. Do not answer the message. Return only JSON: "
    '{"context": [<translated context strings, same order>], "message": "<translated message>"}'
)


def build_prompt(row: dict) -> list[dict]:
    payload = {"context": [c["text"] for c in row["input"]["context"]], "message": row["input"]["message"]}
    return [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]


DIGITS = re.compile(r"\d+")


def valid(src: dict, out: dict) -> bool:
    """Deterministic checks: shape, same context length, digits preserved."""
    if not isinstance(out, dict) or not isinstance(out.get("message"), str) or not out["message"].strip():
        return False
    if len(out.get("context", [])) != len(src["input"]["context"]):
        return False
    return sorted(DIGITS.findall(src["input"]["message"])) == sorted(DIGITS.findall(out["message"]))


def call(row: dict, base: str, model: str, key: str | None, retries: int = 2) -> dict | None:
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    for _ in range(retries + 1):
        try:
            r = requests.post(f"{base.rstrip('/')}/chat/completions", headers=headers, timeout=120, json={
                "model": model, "messages": build_prompt(row), "temperature": 0.3, "max_tokens": 600,
                "response_format": {"type": "json_object"}})
            r.raise_for_status()
            text = r.json()["choices"][0]["message"]["content"]
            text = text[text.find("{"): text.rfind("}") + 1]
            out = json.loads(text)
            if valid(row, out):
                return out
        except Exception as e:  # noqa: BLE001
            print(f"  retry {row['id']}: {type(e).__name__}", file=sys.stderr)
    return None


def to_es(row: dict, tr: dict) -> dict:
    new = json.loads(json.dumps(row))
    new["id"] = row["id"].replace("sgd-", "sgd_es-", 1)
    new["source"] = "sgd_es"
    for c, t in zip(new["input"]["context"], tr["context"]):
        c["text"] = t
    new["input"]["message"] = tr["message"]
    new["output"]["language"] = "es"
    new["meta"]["hard_cases"] = sorted(set(new["meta"]["hard_cases"]) | {"spanish", "machine_translated"})
    new["meta"]["translated_from"] = row["id"]
    return new


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="max rows per split (0 = all SGD rows)")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    for split in ("train", "dev", "test"):
        src = PROC / f"{split}.jsonl"
        if not src.exists():
            sys.exit(f"missing {src}; run build_reader_set.py first")
        rows = [r for r in map(json.loads, open(src)) if r["source"] == "sgd"]
        if a.limit:
            rows = rows[: a.limit]
        if a.dry_run:
            print(f"[{split}] {len(rows)} SGD rows would be translated; sample prompt:")
            print(json.dumps(build_prompt(rows[0]), ensure_ascii=False, indent=1)[:1200])
            continue
        base, model = os.environ.get("OPERATOR_BASE_URL"), os.environ.get("OPERATOR_MODEL")
        if not base or not model:
            sys.exit("OPERATOR_BASE_URL and OPERATOR_MODEL must be set (vLLM endpoint). Use --dry-run to inspect.")
        key = os.environ.get("OPERATOR_API_KEY")
        out_path = PROC / f"sgd_es_{split}.jsonl"
        done = {json.loads(l)["meta"]["translated_from"] for l in open(out_path)} if out_path.exists() else set()
        todo = [r for r in rows if r["id"] not in done]
        ok = fail = 0
        with open(out_path, "a") as fo, cf.ThreadPoolExecutor(a.workers) as ex:
            for row, tr in zip(todo, ex.map(lambda r: call(r, base, model, key), todo)):
                if tr is None:
                    fail += 1
                    continue
                fo.write(json.dumps(to_es(row, tr), ensure_ascii=False) + "\n")
                ok += 1
        print(f"[{split}] translated {ok}, failed {fail}, already had {len(done)} -> {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
