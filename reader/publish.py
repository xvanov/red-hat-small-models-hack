"""Prepare (and, only with --push, upload) the fine-tuned reader to Hugging Face.

Default is a dry run: it writes the model card (README.md) into the checkpoint folder
from the eval results and prints what it would upload. Nothing leaves the machine
until the owner approves and the command is re-run with --push.

  python reader/publish.py --ckpt reader/checkpoints/rentus-reader --repo <user>/rentus-reader-qwen3-0.6b
  python reader/publish.py ... --push          # owner-approved upload; needs HF_TOKEN in .env

The eval table is filled from reader/results/<label>.test.metrics.json for the labels
fallback, base, finetuned and lightning (whichever exist).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from eval import RESULTS, load_env  # noqa: E402
from prompt import SYSTEM_PROMPT  # noqa: E402

ROWS = [("fallback", "Deterministic regex fallback (no model)"),
        ("base", "{base} base, same prompt"),
        ("finetuned", "**This model** ({base} + SFT)"),
        ("lightning", "Nemotron 3.5 Lightning 30B-A3B (operator), same prompt")]


def eval_table(base: str) -> str:
    head = ("| System | Exact match | JSON valid | Lease | Move-in | Phone | Occupants | Reason | Intent F1 (micro) "
            "| Language | Vague-date trap (lower is better) |\n|---|---|---|---|---|---|---|---|---|---|---|")
    lines = [head]
    for label, desc in ROWS:
        p = RESULTS / f"{label}.test.metrics.json"
        if not p.exists():
            continue
        m = json.loads(p.read_text())
        f = {k: f"{v['status_and_value_acc']:.3f}" for k, v in m["fields"].items()}
        trap = m["vague_date_trap"]["rate"]
        lines.append(f"| {desc.format(base=base)} | {m['exact_match']:.3f} | {m['json_valid']:.3f} | {f['lease']} | "
                     f"{f['move_in']} | {f['phone']} | {f['occupants']} | {f['reason']} | {m['intent_f1_micro']:.3f} | "
                     f"{m['language_acc']:.3f} | {trap:.3f} |")
    return "\n".join(lines)


def card(base: str, repo: str, info: dict) -> str:
    steps = info.get("global_steps")
    mins = round(info.get("train_seconds", 0) / 60, 1)
    return f"""---
license: cc-by-sa-4.0
base_model: {base}
language: [en, es]
pipeline_tag: text-generation
library_name: transformers
tags: [information-extraction, json, rental, leasing, small-model, trl, sft]
datasets: [google-research-datasets/schema_guided_dstc8]
---

# {repo.split('/')[-1]}

A small **reader** for room-rental conversations: given the thread so far and the latest renter
message, it returns one exact JSON object saying which qualifying items the message answers
(one-year lease, move-in date, phone, occupants, reason for moving) and how (`answered`,
`vague`, `no`, `exception`, `absent`), plus intents and language (English or Spanish).

It is the "reader" tool of Rentus Operator (NVIDIA x Red Hat Small Models Hack, Raleigh, Oct 2026):
the operator model (Nemotron 3.5 Lightning) calls it like a calculator instead of judging on its
own whether "next month" is a move-in date. The hard cases it is trained for: vague dates
("next month", "around the 15th", an ambiguous "1/11") must never be marked answered; a showing
date is not a move-in date; pets are not occupants; a request for the property's phone is not a
renter phone; relative dates resolve against the given `Today`.

## Use

Serve with vLLM (`vllm serve {repo} --max-model-len 4096`) and send the system prompt below plus a
user message of the form:

```
Today: 2026-10-17
Thread so far:
operator: When would you like to move in?
Latest renter message:
el primero de noviembre, somos dos
```

The reply is JSON only, for example
`{{"lease":{{"status":"absent","value":null}},"move_in":{{"status":"answered","date":"2026-11-01","raw":"el primero de noviembre"}},...}}`.
The chat template defaults to thinking off. The exact system prompt is in `reader/prompt.py` of the
project repo and reproduced at the end of this card.

## Training

- Base: `{base}` ({'0.6B' if '0.6B' in base else ''} parameters by its model card, Apache 2.0), full-parameter SFT with TRL
  `SFTTrainer`, completion-only loss on the canonical JSON, early stopping on dev loss.
- Data: 14,000 training rows (12,000 bilingual synthetic template rows + 2,000 relabelled
  SGD "Homes" dialogue turns), 1,100 dev, 1,419 held-out test never used for training or tuning.
  Method and sources: `docs/data-provenance.md` and `data/reader_schema.md` in the project repo.
- Run: {steps} optimizer steps, effective batch {info.get('effective_batch')}, lr {info.get('lr')},
  {mins} min on one {info.get('gpu')}.

## Evaluation (held-out test, 1,419 rows)

Field columns are status-and-value accuracy (move-in compares status and the resolved date).
Exact match requires every field, the intent set and the language to be right.
"Vague-date trap" is the share of vague move-in answers a system wrongly marked answered or exception.

{eval_table(base)}

## License and provenance

Weights are released under **CC BY-SA 4.0** because part of the training data derives from the
Schema-Guided Dialogue dataset (Google Research, CC BY-SA 4.0); the ShareAlike terms carry over.
The base model is Apache 2.0. Synthetic rows were generated with code written at the event and are
published with their method. No real tenant or renter data was used.

## Limitations

Trained for room-rental leasing in the US (phone numbers normalized to +1). English and Spanish only.
Synthetic templates dominate the training set, so unusual phrasing can still fool it; the operator
treats its output as a tool result checked by deterministic code, not as ground truth.

## System prompt

```
{SYSTEM_PROMPT}
```
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", default=str(HERE / "checkpoints" / "rentus-reader"))
    ap.add_argument("--repo", required=True, help="namespace/name on the Hub")
    ap.add_argument("--base", default=None, help="base model id (default: from rentus_train_info.json)")
    ap.add_argument("--private", action="store_true")
    ap.add_argument("--push", action="store_true", help="actually upload (owner approval required)")
    a = ap.parse_args()
    ckpt = Path(a.ckpt)
    info_p = ckpt / "rentus_train_info.json"
    info = json.loads(info_p.read_text()) if info_p.exists() else {}
    base = a.base or info.get("base_model", "Qwen/Qwen3-0.6B")
    if not ckpt.exists():
        sys.exit(f"no checkpoint at {ckpt}")
    (ckpt / "README.md").write_text(card(base, a.repo, info))
    files = sorted(p.name for p in ckpt.iterdir() if p.is_file())
    print(f"model card written to {ckpt / 'README.md'}")
    print(f"would upload to {a.repo} ({'private' if a.private else 'public'}): {files}")
    if not a.push:
        print("dry run: re-run with --push once the owner approves")
        return
    load_env()
    token = os.environ.get("HF_TOKEN")
    if not token:
        sys.exit("HF_TOKEN is not set in .env")
    from huggingface_hub import HfApi
    api = HfApi(token=token)
    api.create_repo(a.repo, private=a.private, exist_ok=True, repo_type="model")
    api.upload_folder(folder_path=str(ckpt), repo_id=a.repo, repo_type="model",
                      ignore_patterns=["*-trainer/*", "optimizer.pt", "rng_state*"],
                      commit_message="Rentus reader: fine-tuned weights, model card, eval table")
    print(f"pushed https://huggingface.co/{a.repo}")


if __name__ == "__main__":
    main()
