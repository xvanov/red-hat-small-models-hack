"""Write the public model card and (only with --push) upload the fine-tuned reader to Hugging Face.

Default is a dry run: it writes the model card (README.md) and the exact system prompt
(prompt.txt) into the checkpoint folder, refreshes reader/MODEL_CARD.md, and prints what it
would upload. Nothing leaves the machine without --push.

  python reader/publish.py --ckpt reader/release/rentus-reader                  # card only (GitHub release)
  python reader/publish.py --ckpt reader/release/rentus-reader --repo <ns>/rentus-reader-qwen3-0.6b
  python reader/publish.py ... --repo <ns>/rentus-reader-qwen3-0.6b --push      # needs HF_TOKEN in .env

The checkpoint is the one published as GitHub release reader-v1 (model.safetensors
sha256 877c8843...dc2ec6); the release tarball unpacks to the same folder.
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


RELEASE_URL = "https://github.com/xvanov/red-hat-small-models-hack/releases/tag/reader-v1"
PROJECT_URL = "https://github.com/xvanov/red-hat-small-models-hack"


def card(base: str, repo: str | None, info: dict) -> str:
    """The public model card. Same text goes to reader/MODEL_CARD.md, the GitHub release and the HF repo."""
    steps = info.get("global_steps")
    mins = round(info.get("train_seconds", 0) / 60, 1)
    name = repo.split("/")[-1] if repo else "rentus-reader-qwen3-0.6b"
    serve_id = repo or "./rentus-reader"
    return f"""---
license: cc-by-sa-4.0
base_model: {base}
base_model_relation: finetune
language: [en, es]
pipeline_tag: text-generation
library_name: transformers
tags: [information-extraction, json, rental, leasing, small-model, trl, sft, qwen3]
datasets: [google-research-datasets/schema_guided_dstc8]
---

# {name}

A 0.6B-parameter **reader** for room-rental conversations. Given the thread so far and the latest
renter message, it returns one JSON object saying which qualifying items the message answers
(one-year lease, move-in date, phone, occupants, reason for moving) and how (`answered`, `vague`,
`no`, `exception`, `absent`), plus intents and language (English or Spanish).

It is the `read_reply` tool of Rentus Operator, built at the NVIDIA x Red Hat Small Models Hack
(Raleigh, Oct 17-18 2026; code and data: {PROJECT_URL}). The operator model (Nemotron 3.5
Lightning 30B-A3B) calls it like a calculator instead of judging on its own whether "next month"
is a move-in date.

- **Base model:** [`{base}`](https://huggingface.co/{base}) (0.6B parameters by its model card,
  Apache-2.0), full-parameter fine-tune. No adapter: this is a plain Hugging Face checkpoint (bf16 safetensors).
- **License:** CC BY-SA 4.0 (see [License](#license)).
- **Download:** GitHub release [`reader-v1`]({RELEASE_URL}) (tar.gz + SHA256SUMS).

## Task and output schema

Input (user message; the system prompt is at the end of this card and in `prompt.txt` in the release):

```
Today: 2026-10-17
Thread so far:
operator: When would you like to move in?
Latest renter message:
el primero de noviembre, somos dos
```

`Thread so far: (none)` when there is no context. Output, JSON only, keys always in this order:

```json
{{"lease":     {{"status": "S", "value": true | false | null}},
 "move_in":   {{"status": "S", "date": "YYYY-MM-DD" | null, "raw": "span as written" | null}},
 "phone":     {{"status": "S", "value": "+1XXXXXXXXXX" | null}},
 "occupants": {{"status": "S", "value": 2 | null}},
 "reason":    {{"status": "S", "value": "short normalized reason" | null}},
 "intents":   ["price_negotiation", "scheduling", "small_talk", "not_now", "hard_no", "shorter_lease", "question"],
 "language":  "en" | "es"}}
```

`S` is one of `answered | vague | no | exception | absent`; `intents` is a subset of the seven labels, in that order.
Values are null whenever the status is `vague`, `no` or `absent`, except lease `no` = `false`.
The hard cases it is trained for: vague dates ("next month", "around the 15th", an ambiguous "1/11")
are never `answered`; a showing date is not a move-in date; pets are not occupants; asking for the
property's phone is not a renter phone; relative dates resolve against the given `Today`.
Full rules: `data/reader_schema.md` in the project repo.

## How to serve (vLLM)

```bash
tar -xzf rentus-reader-qwen3-0.6b-v1.tar.gz        # or: cat *.part-* | tar -xz, if split
vllm serve {serve_id} --served-model-name rentus-reader \\
  --max-model-len 4096 --enable-prefix-caching --generation-config vllm
```

Then send OpenAI-style chat requests with the system prompt and the user message above, at
**temperature 0** (the shipped `generation_config.json` is Qwen's sampling default; all numbers
below are greedy). The chat template defaults to thinking off, so no `/no_think` or extra flags are needed.
Parse the reply with `parse_output()` from `reader/prompt.py`. Measured: 1.2 GB of weights, p50 0.58 s
per call at concurrency 32 on one RTX PRO 6000 next to Lightning (`--gpu-memory-utilization 0.12`).
It also loads with `transformers` (`AutoModelForCausalLM.from_pretrained`).

## Training data and provenance

14,000 training rows, 1,100 dev, 1,419 held-out test. Published (CC BY-SA 4.0) in the project repo
at `data/published/reader/` (dev and test in full, the first 5,000 train rows; `data/build_reader_set.py`
regenerates all of it, seed 7). Method: `docs/data-provenance.md` and `data/reader_schema.md`.

| Source | Train rows | How |
|---|---|---|
| Synthetic (bilingual) | 12,000 | Hand-written English and Spanish templates composed per message with persona styling (casual, formal, terse, emoji, all-caps). Labels are known by construction. No LLM generated any text or label. Seeded and fully reproducible. |
| Google Schema-Guided Dialogue (SGD, DSTC8), `Homes_1`/`Homes_2` | 2,000 | USER turns as inputs, earlier turns as context, relabelled into this schema by rules over SGD dialogue acts (e.g. `INFORM visit_date` -> `scheduling`, `REQUEST *` -> `question`). SGD's own train/dev/test split is kept. |

The test split is held out: test-only templates, test-only name/employer/city/area-code pools, SGD
test dialogues, and exact-duplicate messages dropped. No real tenant or renter data was used.

Run: TRL `SFTTrainer`, prompt-completion format with loss on the JSON only, {steps} optimizer steps
(max 2 epochs), effective batch {info.get('effective_batch')}, lr {info.get('lr')}, eval loss on 400 dev rows
every 100 steps with early stopping, {mins} min on one {info.get('gpu')}.

## Evaluation (held-out test, 1,419 rows)

Every system gets the same system prompt, temperature 0, thinking off. Field columns are
status-and-value accuracy (move-in compares status and the resolved date). Exact match requires
every field, the intent set and the language to be right. "Vague-date trap" is the share of
vague move-in answers a system wrongly marked `answered` or `exception` (lower is better).

{eval_table(base)}

Most remaining misses are `reason` paraphrases ("house sale" for "landlord selling"); reason
*status* accuracy is 0.985. The regex fallback was tuned on train/dev templates (0.93 exact match on
dev), so its drop on test shows how different the held-out phrasing is.

## Intended use and limits

- **Intended:** a structured-extraction tool inside a leasing assistant, for US room rentals, English
  and Spanish, where deterministic code checks its output before anything acts on it. Fits next to
  a larger model on one GPU.
- **Not intended:** deciding on its own whether to accept or reject an applicant, tenant screening,
  any fair-housing-relevant judgment, or general chat. It only describes what a message says.
- **Limits:** synthetic templates dominate training, so the test split is still closer to the training
  data than real renter texts would be; unusual phrasing can fool it. Phone numbers are normalized to
  +1 (US) only. `reason.value` is a short paraphrase and may not match a reference word for word.
  Two languages only.

## License

The weights are released under **CC BY-SA 4.0**. Part of the training data is derived from the
Schema-Guided Dialogue dataset (CC BY-SA 4.0), so we release the fine-tuned weights, like the data,
under the same ShareAlike terms: if you redistribute modified weights, use CC BY-SA 4.0 too and keep
the attributions below. The base model `{base}` is Apache-2.0, which permits this; its license and
copyright notice still apply to the base weights (https://huggingface.co/{base}).

## Citation

If you use this model, please cite the datasets and base model:

```bibtex
@inproceedings{{rastogi2020sgd,
  title     = {{Towards Scalable Multi-domain Conversational Agents: The Schema-Guided Dialogue Dataset}},
  author    = {{Rastogi, Abhinav and Zang, Xiaoxue and Sunkara, Srinivas and Gupta, Raghav and Khaitan, Pranav}},
  booktitle = {{Proceedings of the AAAI Conference on Artificial Intelligence}},
  volume    = {{34}}, number = {{05}}, pages = {{8689--8696}}, year = {{2020}}
}}
@misc{{qwen3,
  title  = {{Qwen3 Technical Report}}, author = {{Qwen Team}},
  year   = {{2025}}, eprint = {{2505.09388}}, archivePrefix = {{arXiv}}
}}
@misc{{rentusreader2026,
  title  = {{rentus-reader: a 0.6B reader for room-rental conversations}},
  author = {{Rentus Operator team}}, year = {{2026}},
  note   = {{NVIDIA x Red Hat Small Models Hack}}, howpublished = {{\\url{{{PROJECT_URL}}}}}
}}
```

## System prompt

```
{SYSTEM_PROMPT}
```
"""


UPLOAD_IGNORE = ["*-trainer/*", "optimizer.pt", "scheduler.pt", "rng_state*", "training_args.bin"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", default=str(HERE / "release" / "rentus-reader"))
    ap.add_argument("--repo", default=None, help="namespace/name on the Hub (required with --push)")
    ap.add_argument("--base", default=None, help="base model id (default: from rentus_train_info.json)")
    ap.add_argument("--card-out", default=str(HERE / "MODEL_CARD.md"), help="also write the card here ('' to skip)")
    ap.add_argument("--private", action="store_true")
    ap.add_argument("--push", action="store_true", help="actually upload (owner approval required)")
    a = ap.parse_args()
    ckpt = Path(a.ckpt)
    if not ckpt.exists():
        sys.exit(f"no checkpoint at {ckpt}")
    info_p = ckpt / "rentus_train_info.json"
    info = json.loads(info_p.read_text()) if info_p.exists() else {}
    base = a.base or info.get("base_model", "Qwen/Qwen3-0.6B")
    text = card(base, a.repo, info)
    (ckpt / "README.md").write_text(text)
    (ckpt / "prompt.txt").write_text(SYSTEM_PROMPT + "\n")
    if a.card_out:
        Path(a.card_out).write_text(text)
    files = sorted(p.name for p in ckpt.iterdir() if p.is_file() and p.name not in UPLOAD_IGNORE)
    print(f"model card written to {ckpt / 'README.md'}" + (f" and {a.card_out}" if a.card_out else ""))
    if not a.repo:
        print("no --repo given: card only")
        return
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
    api.upload_folder(folder_path=str(ckpt), repo_id=a.repo, repo_type="model", ignore_patterns=UPLOAD_IGNORE,
                      commit_message="rentus-reader v1: fine-tuned weights, model card, eval table, prompt")
    print(f"pushed https://huggingface.co/{a.repo}")


if __name__ == "__main__":
    main()
