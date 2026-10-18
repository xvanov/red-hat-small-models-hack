---
license: cc-by-sa-4.0
language: [en, es]
pretty_name: Rentus reader messages
size_categories: [10K<n<100K]
task_categories: [text-generation]
tags: [information-extraction, json, rental, leasing, synthetic, small-model]
source_datasets: [google-research-datasets/schema_guided_dstc8]
configs:
- config_name: default
  data_files:
  - split: train
    path: data/train_full.jsonl.gz
  - split: validation
    path: data/dev.jsonl
  - split: test
    path: data/test.jsonl
- config_name: train_first5000
  data_files:
  - split: train
    path: data/train.jsonl
---

# Rentus reader messages

Renter messages from room-rental conversations, each paired with the exact JSON a "reader"
model should return. The JSON says which qualifying items the latest message answers
(one-year lease, move-in date, phone, number of occupants, reason for moving) and how
(`answered`, `vague`, `no`, `exception`, `absent`), plus intents and language (English or Spanish).

Built at the NVIDIA x Red Hat Small Models Hack (Oct 17-18 2026) for **Rentus Operator**.
It trains and evaluates [`xvanov/rentus-reader-qwen3-0.6b`](https://huggingface.co/xvanov/rentus-reader-qwen3-0.6b),
the 0.6B model the operator calls as its `read_reply` tool.
Code, build scripts and full provenance: <https://github.com/xvanov/red-hat-small-models-hack>.

No real tenant or renter data is in this dataset.

## Files and splits

| File | Split | Rows | Synthetic | SGD-derived | English / Spanish |
|---|---|---|---|---|---|
| `data/train_full.jsonl.gz` | train (all) | 14,000 | 12,000 | 2,000 | 10,452 / 3,548 |
| `data/train.jsonl` | first 5,000 rows of train (what the project's Gym task builders read) | 5,000 | 4,281 | 719 | 3,749 / 1,251 |
| `data/dev.jsonl` | validation | 1,100 | 800 | 300 | 871 / 229 |
| `data/test.jsonl` | held-out test | 1,419 | 1,144 | 275 | 1,089 / 330 |
| `stats.json` | label counts per split | | | | |
| `SHA256SUMS` | sha256 of every file, equal to the copies in the GitHub repo | | | | |

The default config loads `train_full` / `dev` / `test`. The files are byte-identical to
`data/published/reader/` in the GitHub repo (commit noted in `SHA256SUMS`); the evaluation
results in the project were computed on exactly these bytes. sha256 of the **uncompressed**
`train_full.jsonl`: `3d9237ef6e79f8a18bdd22fde1417b019b86eb318ae152239dfb22694a3d19b3`.

## Row format

```json
{
  "id": "syn-train-000123",
  "source": "synthetic" | "sgd",
  "input": {
    "today": "2026-10-17",
    "context": [{"role": "operator" | "renter", "text": "..."}],
    "message": "latest renter message"
  },
  "output": {
    "lease":     {"status": "S", "value": true | false | null},
    "move_in":   {"status": "S", "date": "YYYY-MM-DD" | null, "raw": "span as written" | null},
    "phone":     {"status": "S", "value": "+19195550123" | null},
    "occupants": {"status": "S", "value": 2 | null},
    "reason":    {"status": "S", "value": "short normalized reason" | null},
    "intents":   ["price_negotiation", "scheduling", "small_talk", "not_now", "hard_no", "shorter_lease", "question"],
    "language":  "en" | "es"
  },
  "meta": {"templates": ["..."], "hard_cases": ["..."], "persona": "casual"}
}
```

`S` is one of `answered | vague | no | exception | absent`. The output describes **only the
latest message**; the context is there to interpret it (a bare "yes" answers the lease
question only if the operator just asked it). Values are null when the status is `vague`,
`no` or `absent`, except lease `no` = `false`. `intents` is a subset of the seven labels.

The hard cases the labels encode:

- Vague dates ("next month", "around the 15th", "a fines de mes", and any numeric date like
  "1/11" whose month/day order is ambiguous) are `vague`, never `answered`.
- A showing date is `scheduling`, never a move-in date.
- Pets are not occupants ("me and my dog" = 1).
- Asking for the property's phone is a `question`, not a renter phone.
- Relative dates resolve against `input.today`.

Full rules: [`data/reader_schema.md`](https://github.com/xvanov/red-hat-small-models-hack/blob/main/data/reader_schema.md).

## How it was built

Script: [`data/build_reader_set.py`](https://github.com/xvanov/red-hat-small-models-hack/blob/main/data/build_reader_set.py), seed 7, fully reproducible
(`data/download.py` then `data/build_reader_set.py`).

1. **Synthetic rows (12,000 train / 800 dev / 1,144 test).** Hand-written English and Spanish
   templates, composed per message (opener + one or more answer fragments + closer), with
   persona styling (casual, formal, terse, emoji, all-caps, verbose). Names, employers, schools,
   cities and phone numbers come from fictional pools; phones use the reserved 555-01xx range.
   Labels are known by construction. **No LLM wrote any text or label.**
2. **Spanish.** The Spanish rows are written directly from hand-written Spanish templates
   (informal Latin American Spanish), not machine-translated. A planned machine translation of
   the SGD rows (`data/translate_es.py`) was **not run**, so no row in this release is
   machine-translated.
3. **SGD rows (2,000 / 300 / 275).** USER turns of the Google Schema-Guided Dialogue dialogues
   whose services include `Homes_1` or `Homes_2`, with the earlier turns as context. Relabeled
   into this schema by rules over SGD dialogue acts: `INFORM visit_date` -> `scheduling`;
   `REQUEST *` -> `question`; `NEGATE_INTENT` -> `not_now`; `AFFIRM` after an operator turn about
   a visit -> `scheduling`; thanks / goodbye / bare affirm or select -> `small_talk`; a regex
   picks up "moving ... for work/school" as a `reason`. Everything else is `absent`. SGD's own
   train/dev/test split is kept, so SGD test dialogues are never in train. Phone numbers and
   street addresses in these rows are SGD's own (property and venue listings from that public
   dataset), not renter data.

**How held out the test split is.** The test split is test-biased, not fully template-disjoint:
each template draw for test picks a test-only template with probability 0.6 and otherwise any
template, and openers, closers and joiners are shared. Measured: 188 of the 1,144 synthetic test
rows use only templates that also occur in train/dev; 956 use at least one test-only template;
47 synthetic and 6 SGD test rows equal a train/dev row after normalizing punctuation and digits.
Test also uses test-only name / employer / school / city / area-code pools and SGD's test
dialogues, and exact lowercase duplicates of train/dev were dropped. The project reports exact
match on both template groups.

## Sources and attribution

- **Google Schema-Guided Dialogue (SGD, DSTC8)**, <https://github.com/google-research-datasets/dstc8-schema-guided-dialogue>,
  pinned commit `e852981ae34990f4358979625854259302feaa78`, CC BY-SA 4.0. Rastogi et al.,
  "Towards Scalable Multi-domain Conversational Agents: The Schema-Guided Dialogue Dataset", AAAI 2020.
- Synthetic rows: written for this project (templates in the build script, Apache-2.0 code).

## License

**CC BY-SA 4.0.** Because the set mixes rows derived from SGD (CC BY-SA 4.0), share-alike
applies to the whole dataset. The synthetic rows alone (`source == "synthetic"`) carry no SGD
content.

## Intended use

- Training and evaluating small models that turn a renter's free-text message into a
  structured, checkable record (the project's 0.6B reader).
- Benchmarking extraction of exact-vs-vague dates, phone normalization and intent detection
  in English and Spanish rental chat.

## Limitations

- Mostly template text. Real renters are vaguer, mix topics, and write longer and messier
  messages; a reader that scores well here can still miss real-world phrasings. The companion
  set [`xvanov/rentus-leasing-twins`](https://huggingface.co/datasets/xvanov/rentus-leasing-twins)
  has messages shaped like real leasing threads.
- One market and one business model: rooms for rent in North Carolina homes, one-year leases.
- SGD rows are English only and mostly about searching for and visiting properties, so their
  gate fields are nearly all `absent`.
- Test is only partly held out by template (see above).
- Labels are rule-based; edge cases follow the project's schema rules, which other applications
  may define differently.
