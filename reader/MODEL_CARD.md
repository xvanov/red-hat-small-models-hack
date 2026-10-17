---
license: cc-by-sa-4.0
base_model: Qwen/Qwen3-0.6B
base_model_relation: finetune
language: [en, es]
pipeline_tag: text-generation
library_name: transformers
tags: [information-extraction, json, rental, leasing, small-model, trl, sft, qwen3]
datasets: [google-research-datasets/schema_guided_dstc8]
---

# rentus-reader-qwen3-0.6b

A 0.6B-parameter **reader** for room-rental conversations. Given the thread so far and the latest
renter message, it returns one JSON object saying which qualifying items the message answers
(one-year lease, move-in date, phone, occupants, reason for moving) and how (`answered`, `vague`,
`no`, `exception`, `absent`), plus intents and language (English or Spanish).

It is the `read_reply` tool of Rentus Operator, built at the NVIDIA x Red Hat Small Models Hack
(Raleigh, Oct 17-18 2026; code and data: https://github.com/xvanov/red-hat-small-models-hack). The operator model (Nemotron 3.5
Lightning 30B-A3B) calls it like a calculator instead of judging on its own whether "next month"
is a move-in date.

- **Base model:** [`Qwen/Qwen3-0.6B`](https://huggingface.co/Qwen/Qwen3-0.6B) (0.6B parameters by its model card,
  Apache-2.0), full-parameter fine-tune. No adapter: this is a plain Hugging Face checkpoint (bf16 safetensors).
- **License:** CC BY-SA 4.0 (see [License](#license)).
- **Download:** GitHub release [`reader-v1`](https://github.com/xvanov/red-hat-small-models-hack/releases/tag/reader-v1) (tar.gz + SHA256SUMS).

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
{"lease":     {"status": "S", "value": true | false | null},
 "move_in":   {"status": "S", "date": "YYYY-MM-DD" | null, "raw": "span as written" | null},
 "phone":     {"status": "S", "value": "+1XXXXXXXXXX" | null},
 "occupants": {"status": "S", "value": 2 | null},
 "reason":    {"status": "S", "value": "short normalized reason" | null},
 "intents":   ["price_negotiation", "scheduling", "small_talk", "not_now", "hard_no", "shorter_lease", "question"],
 "language":  "en" | "es"}
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
vllm serve ./rentus-reader --served-model-name rentus-reader \
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

Run: TRL `SFTTrainer`, prompt-completion format with loss on the JSON only, 876 optimizer steps
(max 2 epochs), effective batch 32, lr 3e-05, eval loss on 400 dev rows
every 100 steps with early stopping, 33.2 min on one NVIDIA RTX PRO 6000 Blackwell Server Edition.

## Evaluation (held-out test, 1,419 rows)

Every system gets the same system prompt, temperature 0, thinking off. Field columns are
status-and-value accuracy (move-in compares status and the resolved date). Exact match requires
every field, the intent set and the language to be right. "Vague-date trap" is the share of
vague move-in answers a system wrongly marked `answered` or `exception` (lower is better).

| System | Exact match | JSON valid | Lease | Move-in | Phone | Occupants | Reason | Intent F1 (micro) | Language | Vague-date trap (lower is better) |
|---|---|---|---|---|---|---|---|---|---|---|
| Deterministic regex fallback (no model) | 0.575 | 1.000 | 0.886 | 0.994 | 0.998 | 0.977 | 0.877 | 0.772 | 0.998 | 0.012 |
| Qwen/Qwen3-0.6B base, same prompt | 0.000 | 0.910 | 0.106 | 0.023 | 0.011 | 0.028 | 0.004 | 0.105 | 0.699 | 0.082 |
| **This model** (Qwen/Qwen3-0.6B + SFT) | 0.791 | 1.000 | 0.991 | 0.977 | 0.997 | 0.999 | 0.865 | 0.951 | 1.000 | 0.012 |
| Nemotron 3.5 Lightning 30B-A3B (operator), same prompt | 0.106 | 0.985 | 0.569 | 0.554 | 0.827 | 0.721 | 0.534 | 0.450 | 0.944 | 0.365 |

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
the attributions below. The base model `Qwen/Qwen3-0.6B` is Apache-2.0, which permits this; its license and
copyright notice still apply to the base weights (https://huggingface.co/Qwen/Qwen3-0.6B).

## Citation

If you use this model, please cite the datasets and base model:

```bibtex
@inproceedings{rastogi2020sgd,
  title     = {Towards Scalable Multi-domain Conversational Agents: The Schema-Guided Dialogue Dataset},
  author    = {Rastogi, Abhinav and Zang, Xiaoxue and Sunkara, Srinivas and Gupta, Raghav and Khaitan, Pranav},
  booktitle = {Proceedings of the AAAI Conference on Artificial Intelligence},
  volume    = {34}, number = {05}, pages = {8689--8696}, year = {2020}
}
@misc{qwen3,
  title  = {Qwen3 Technical Report}, author = {Qwen Team},
  year   = {2025}, eprint = {2505.09388}, archivePrefix = {arXiv}
}
@misc{rentusreader2026,
  title  = {rentus-reader: a 0.6B reader for room-rental conversations},
  author = {Rentus Operator team}, year = {2026},
  note   = {NVIDIA x Red Hat Small Models Hack}, howpublished = {\url{https://github.com/xvanov/red-hat-small-models-hack}}
}
```

## System prompt

```
You read one message from a person asking about a room for rent and return JSON only.
Describe ONLY the latest renter message. Use the thread only to interpret it (a bare "yes" answers the lease question only if the operator just asked it).

Return exactly this JSON object, no prose, no code fences:
{"lease":{"status":S,"value":true|false|null},"move_in":{"status":S,"date":"YYYY-MM-DD"|null,"raw":"span as written"|null},"phone":{"status":S,"value":"+1XXXXXXXXXX"|null},"occupants":{"status":S,"value":integer|null},"reason":{"status":S,"value":"short normalized reason"|null},"intents":[zero or more label strings, e.g. "scheduling","question"],"language":"en"|"es"}
S is one of: answered, vague, no, exception, absent (absent = the message does not touch this item).

lease (one-year lease): answered = explicit yes (true). vague = "probably", "as long as necessary", "depends" (null). no = refuses a year (false). exception = yes with a condition such as subletting (true).
move_in: answered = a resolvable calendar day ("Nov 1st", "el primero de noviembre", "this Saturday", "the 15th" = next 15th). vague = only a month, "soon", "ASAP", "next month", "around the 15th", "a fines de mes", or a numeric date like "1/11" where both parts are 1-12 and differ (month/day order is ambiguous); date null. no = declines. exception = a date with a condition; date filled. Resolve relative dates against Today; a bare month-day is the next occurrence on or after Today. raw = the date words exactly as written. A showing/visit date is NOT a move-in date.
phone: answered = full 10-digit US number in any format, normalized to E.164 (+1 and 10 digits). vague = partial number or "I'll send it later". no = declines. exception = number with a caveat ("this one is temporary"), value filled. A request for the property's phone number is not a renter phone.
occupants: number of people moving in (pets do not count: "me and my dog" = 1). vague = "maybe me and a friend". no = declines. exception = core count plus a part-time guest; value = core count.
reason (why they are moving): answered = concrete reason ("new job at Duke", "current lease ending"), value is a short normalized phrase. vague = "need a change", "personal reasons" (null). no = declines (null).
Values are null whenever status is vague, no or absent, except lease no = false.
intents (a JSON list of label strings, zero or more, in this order): price_negotiation (asks for lower price or a deal), scheduling (wants to see the room or proposes/asks a showing time), small_talk (no qualifying content and no request: thanks, ok, emojis, compliments), not_now (interested but timing is later), hard_no (no longer interested / stop), shorter_lease (asks for less than 12 months or month-to-month), question (factual question about the room or listing).
language: "es" if the message is Spanish, else "en".
```
