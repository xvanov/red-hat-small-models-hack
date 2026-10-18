---
license: cc-by-4.0
language: [en, es]
pretty_name: Rentus leasing twins and Gym tasks
size_categories: [n<1K]
task_categories: [text-generation]
tags: [synthetic, rental, leasing, agents, nemo-gym, evaluation, information-extraction, nemotron-personas]
configs:
- config_name: twins
  data_files:
  - split: heldout
    path: twins/twins.jsonl
- config_name: reader_test
  data_files:
  - split: test
    path: twins/reader_test.jsonl
- config_name: owner_gold
  data_files:
  - split: test
    path: owner_gold_combined.jsonl
- config_name: gym_v3
  data_files:
  - split: heldout
    path: gym_tasks/v3/heldout.jsonl
---

# Rentus leasing twins and Gym tasks

Synthetic **"twins"** of a small landlord's real room-rental SMS threads, the evaluation sets
built from them, and the NeMo Gym task sets used to train and test **Rentus Operator**, an
agent that answers renters, qualifies them and books showings (NVIDIA x Red Hat Small Models
Hack, Oct 17-18 2026).

A twin keeps the *shape* of a real conversation (who spoke when, what each renter message
answered, how vague it was, language, length, emoji, the gaps, how the thread ended) and
replaces every word and every person. **No real message text, name, phone number, address or
identifier is in this dataset.**

Code and full method: <https://github.com/xvanov/red-hat-small-models-hack> (`data/twins/`,
`docs/data-provenance.md`, `docs/eval-protocol.md`). Companion data:
[`xvanov/rentus-reader-messages`](https://huggingface.co/datasets/xvanov/rentus-reader-messages).
Model evaluated on the reader rows: [`xvanov/rentus-reader-qwen3-0.6b`](https://huggingface.co/xvanov/rentus-reader-qwen3-0.6b).

## Files

| File | Rows | What it is |
|---|---|---|
| `twins/twins.jsonl` | 51 | Twin conversations (46 leasing, 4 contractor, 1 ops). Each has a Nemotron persona (with source uuid and license), channel, start time, and turns; every renter turn carries gold reader labels. |
| `twins/reader_test.jsonl` | 192 | Every renter message of the twins with text, in the reader row format (`source: "twin"`), gold from the twin's truth sheet. 73 rows flagged where a rule-based check disagrees with the gold (in `meta`). |
| `twins/reader_test_labeled_0548.jsonl` | 61 | The earlier (05:48 ET) reader test rows the owner labeled; kept because the owner labels refer to these exact bytes. |
| `twins/owner_gold.jsonl` | 61 | The owner's blind labels on those 61 twin messages (22 threads). |
| `owner_gold_combined.jsonl` | 90 | The 61 rows above plus 29 **pilot** rows (see below); `meta.h2_source` is `real_twin` or `pilot`. Hashes in `owner_gold_combined.json`. |
| `twins/owner_gold_audit.json` | | Agreement of the pipeline's gold with the owner's labels (exact row match 30 / 61; per field 0.95-1.0, intents 0.52). |
| `twins/stats_card.json` | | Aggregate statistics of the real threads the twins mirror (counts and quartiles only, cells under 5 suppressed). |
| `twins/filter_report.json` | | Privacy filter counts and thresholds. |
| `twins/tasks_stats.json` | | Counts for the v3 task build. |
| `gym_tasks/v3/heldout.jsonl` | 46 | Held-out NeMo Gym tasks built from the twins (confirmatory evaluation set). |
| `gym_tasks/v3/heldout_ops.jsonl` | 5 | Experimental held-out ops/vendor tasks from the twins (not in the confirmatory set). |
| `gym_tasks/v2/train.jsonl`, `heldout.jsonl` | 54, 33 | Gym tasks v2 (scripted, from the synthetic rows of the reader set). |
| `gym_tasks/v1/train.jsonl`, `heldout.jsonl` | 51, 31 | Gym tasks v1 (same construction, earlier version). |
| `gym_tasks/v{1,2}/stats.json` | | Task counts by category. |
| `SHA256SUMS` | | sha256 of every file, equal to the copies in the GitHub repo. |

Task format (initial sandbox state, scripted counterparts, fault injections, checks):
[`contracts/tools.md`](https://github.com/xvanov/red-hat-small-models-hack/blob/main/contracts/tools.md) §7, §9, §10.
Rooms and listings in the tasks are fictional (sandbox inventory in the GitHub repo,
`data/published/inventory.json`). Reader row format: [`data/reader_schema.md`](https://github.com/xvanov/red-hat-small-models-hack/blob/main/data/reader_schema.md).

**Frozen files.** These files are frozen for the project's pre-registered evaluation (hashes in
`docs/freeze-manifest.json` and `data/twins/splits.json` in the GitHub repo). They are uploaded
byte-for-byte; `SHA256SUMS` lets you check that. Example: `twins/owner_gold.jsonl` sha256
`f8cdf129c3781e4f7900b6b9ffb228a53d0a8cdfefc08be35615c3c99fd60c7d`.

## How a twin is made

Code in `data/twins/` of the GitHub repo.

1. **Ingest (private, on the owner's machine).** The owner's own anonymized message exports are
   loaded outside the repo. Sender names are dropped, thread ids are salted hashes, and a regex
   scrub replaces phones, emails, URLs, street addresses and unit numbers. Non-rental threads are
   dropped. The real text never leaves infrastructure the team controls (this machine and a
   rented single-tenant GPU over an SSH tunnel) and is never sent to a third-party API.
2. **Label skeleton.** Nemotron 3.5 Lightning (30B-A3B, served locally on vLLM) and the project's
   reader label each real renter message with the reader schema, each owner message with what it
   does, and each thread with its outcome (showing, applied, ghosted, no).
3. **Rewrite.** Lightning writes the twin from the **label skeleton only**: the speaker of each
   turn, each renter message's statuses, intents and language, style hints (length, emoji,
   casing), timing gaps and the ending. It never sees the real wording. The renter is a persona
   from [nvidia/Nemotron-Personas-USA](https://huggingface.co/datasets/nvidia/Nemotron-Personas-USA);
   dates are shifted into Oct 2026 - Feb 2027, the phone is a fictional 555-01xx number, and
   reasons, jobs and details are invented. The prompt forbids reusing any 4-word phrase.
4. **Re-verify.** Each twin renter message is re-labeled and must equal its target (statuses,
   dates, values, intents, language). Mismatches are rewritten (up to 3 attempts); twins that
   still fail are dropped. Gold labels are known by construction: the original's statuses with
   the twin's own dates, phone and reason.
5. **Privacy filter.** Every twin line is compared with every real line (46,151 real lines):
   character 8-gram containment (>= 0.5 of the twin line, or >= 0.6 of a real line), embedding
   cosine >= 0.90 (`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`), exact match, and
   a PII regex. A flagged line is rewritten blind and re-verified, or the twin is dropped. Phrases
   that occur in 3+ different real threads count as common ("see you then") and are not
   protected; lines under 15 characters are exempt from the similarity tests. Result for the
   held-out set: 60 twins in, 2 dropped for broken structure, 118 lines rewritten, 7 twins dropped
   for privacy, **51 out**. Details in `twins/filter_report.json`.

## What the owner labels are

The owner (the landlord whose threads the twins mirror) blind-labeled reader rows with no
prefilled answers:

- **61 real-twin rows** (`twins/owner_gold.jsonl`): renter messages of the twins, sampled from the
  05:48 ET reader test (`twins/reader_test_labeled_0548.jsonl`), 22 threads. A rule-based audit
  flagged 2 rows (language); the owner adjudicated both. The labeled text is twin text, not real text.
- **29 pilot rows** (in `owner_gold_combined.jsonl`, `meta.h2_source == "pilot"`): renter messages
  from twins of 7 **fictional practice conversations written by an agent** to test the pipeline
  (`data/twins/fixtures/` in the GitHub repo); not derived from any real thread. They are reported
  separately from the confirmatory results.

The combined 90 rows are the gold for the project's reader comparison (H2). The
`twins/reader_test.jsonl` gold, by contrast, is the pipeline's truth sheet, not owner-checked.

## License and attribution

**CC BY 4.0.**

- Personas: [nvidia/Nemotron-Personas-USA](https://huggingface.co/datasets/nvidia/Nemotron-Personas-USA),
  CC BY 4.0; every twin and v3 task keeps the persona's source uuid and license.
- Twin text and labels are outputs of NVIDIA Nemotron 3.5 Lightning, used under NVIDIA's open model license.
- The twins contain no content from Google SGD. The v1/v2 Gym tasks use only the team-written
  synthetic rows of the reader set (no SGD-derived row).

## Intended use

- Evaluating leasing agents in NeMo Gym-style sandboxes on conversations shaped like real ones
  (ghosting, price pushes, vague dates, "not now", hard no, language switches).
- Testing structured extraction from renter messages against owner-labeled gold.

## Limitations

- **One owner's business.** The twins mirror 60 SMS threads of one small landlord renting rooms
  in North Carolina; other markets, channels and property types look different.
- **Synthetic.** Every word was written by a model from a label skeleton. Realism was **not
  confirmed** by the owner: the planned blind real-vs-twin realism review was not done before the
  freeze, so the set is reported as "synthetic, realism not confirmed" (`docs/eval-protocol.md`,
  Amendment 6).
- **Model labels.** The skeleton labels of the real messages come from models; a mislabeled real
  message gives a twin of a slightly different shape (the twin's gold still matches the twin's
  text). Thread outcomes are model judgements. Owner-checked labels exist only for the 61 + 29 rows.
- **Easy-heavy.** Most renter messages are small talk, thanks and logistics; only 4 of the 61
  real-twin owner rows have any non-`absent` qualifying field (17 of the 29 pilot rows do).
- **Small.** 51 twins, 46 confirmatory tasks; mostly English (1 Spanish task).
- **Privacy filter limits.** The filter catches copied or closely paraphrased lines; the regex
  scrub misses free-form identifiers, so the owner's own anonymization comes first.
