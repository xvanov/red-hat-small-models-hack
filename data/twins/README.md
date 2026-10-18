# data/twins: rewritten twins of real rental conversations

Turns the owner's real rental-inquiry threads into **synthetic twins**: new conversations with the same shape (turns, what each message does, how vague or hard it is, language switches, where the renter went silent) but a different invented renter and entirely new wording. The twins become a published reader test set and Gym held-out tasks that mirror real traffic. No real text is ever committed or sent off the machine.

## Where the owner drops his data

Outside the repo, in `~/rentus-private-data/input/` (override with `RENTUS_PRIVATE_DIR`):

| Folder | What | Format |
|---|---|---|
| `imazing/` | iMazing iPhone message exports | `*.csv` with iMazing's columns (`Chat Session`, `Message Date`, `Type` = Incoming/Outgoing, `Sender Name`, `Text`, ...). One or many chats per file. |
| `facebook/` | Facebook "Download your information", **JSON** format, unzipped | any `message_*.json` below it (`messages/inbox`, `archived_threads`, `filtered_threads`, `message_requests`, `e2ee_cutover`). Classic and newer E2EE layouts both work; Facebook's latin-1 mojibake is repaired. |
| `generic/` | anything else | `*.csv` or `*.jsonl` with `thread_id, ts, sender, text` (optional `role` = owner/renter, `channel`). `ts` is ISO 8601 or epoch s/ms. |

Then:

```bash
export TWINS_OWNER_NAMES="Owner Name,Rentus Homes"   # how the owner appears as sender (iMazing Outgoing is always the owner)
data/twins/run.sh --limit 20     # dry run on 20 threads
data/twins/run.sh                # everything
```

## Setup

```bash
cd data/twins && uv venv .venv --python 3.12
uv pip install --python .venv/bin/python torch==2.5.1 --index-url https://download.pytorch.org/whl/cpu
uv pip install --python .venv/bin/python -r requirements.txt
```

Needs the local vLLM endpoints from `.env`: `OPERATOR_BASE_URL` (Nemotron 3.5 Lightning, default `http://localhost:8000/v1`) and, for `--labeler reader`, `READER_BASE_URL`.

## Steps

Every step is idempotent (model replies are cached in `work/cache/`, randomness is seeded per thread) and takes `--fixture`, `--limit N` and `--workers N`.

| Step | Does | Writes |
|---|---|---|
| `ingest.py` | loads the three formats, sorts messages, marks owner/renter, detects language and switches, drops non-rental threads (keyword score; Lightning decides the borderline ones), re-scrubs PII with regex (phones, emails, URLs, street addresses, unit and id numbers). Sender names are dropped, thread ids are salted hashes. | `work/threads.jsonl`, `work/ingest_report.json` |
| `label.py` | Lightning (reasoning on) labels every renter message with the reader schema, using the reader's own prompt (`reader/prompt.py`); labels every owner message with acts and every thread with outcomes (qualified / showing / applied / ghosted / no). Deterministic difficulty and style features. | `work/labeled.jsonl`, **`published/stats_card.json`** (aggregates; cells below 5 shown as `<5`) |
| `twin.py` | for each thread, Lightning writes a twin from the label skeleton only (it never sees the real wording unless `--show-original`), with a persona from `nvidia/Nemotron-Personas-USA`, new dates (shifted into Oct 2026 to Feb 2027), a fictional 555-01xx phone, new reason and details. The twin is re-labeled and must match its skeleton exactly; mismatches go back for a rewrite (3 attempts). Gold labels = the original's labels with the twin's own values. | `work/twins.jsonl` |
| `filter.py` | compares every twin line with every real line: character 8-gram containment, embedding cosine (local `paraphrase-multilingual-MiniLM-L12-v2`), exact match, PII regex. Flagged lines are rewritten blind and re-verified, or the twin is dropped. Unverified twins are dropped. | `work/twins_filtered.jsonl`, **`published/filter_report.json`** (counts only) |
| `to_tasks.py` | publishes the twins, a reader test set and Gym held-out tasks (format v3, `contracts/tools.md` §10). | **`published/twins.jsonl`**, **`published/reader_test.jsonl`**, **`gym/tasks/v3/heldout.jsonl`**, `published/tasks_stats.json` |

`published/` = `data/published/twins/` in real mode, `data/twins/fixtures/out/published/` with `--fixture`.

## Privacy guarantees

1. **Real text never enters the repo.** Input and every intermediate holding real text live in `~/rentus-private-data/` (mode 700). `Paths` refuses a private dir inside the repo.
2. **Real text never leaves the machine.** The only model client (`common.LocalLLM`) refuses any endpoint that is not loopback, private (RFC 1918) or tailnet (100.64/10). The embedding model runs on CPU here. No hosted API is reachable from this code.
3. **Two scrubs before any model sees a message**: the owner's own anonymization, then the regex scrub in `ingest.py`.
4. **The twin writer is blind by default**: it gets labels, style hints and a persona, not the real words.
5. **Every published line is checked against every real line** (8-gram, embedding, exact, PII) and `filter.py` asserts the published set passes. Phrases that 3+ different real threads share ("is it still available?") are treated as common and not protected, because they identify no one.
6. **Only aggregates leave `work/`**: the stats card and filter report have counts, with small cells suppressed.

Limits: the scrub regexes are a second layer and miss free-form identifiers (a name typed mid-sentence); the owner's anonymization is the first. Similarity thresholds are tunable (`filter.py --help`).

## Fixture (fake data, for testing)

`make_fixture.py` writes 10 invented threads (EN and ES, all three formats, one non-rental chat) to `fixtures/input/`. `run.sh --fixture` runs the whole pipeline on them; outputs are committed under `fixtures/out/` (fake text only, so `work/` is committed there too).

```bash
data/twins/.venv/bin/python data/twins/make_fixture.py
data/twins/run.sh --fixture
data/twins/.venv/bin/python data/twins/test_twins.py   # offline tests: loaders, mojibake, scrub, local-only guard
```

Fixture result (2026-10-18, fresh cache, `--concurrency 32`): 10 threads in, 1 non-rental dropped, 9 labeled, 9 twins, 7 verified, 8 lines rewritten by the privacy filter, 0 twins dropped for privacy, 7 v3 tasks (7 different behaviours) and 29 reader rows. The v3 tasks load and score in the Gym (`run_eval.py --tasks-file ... --stub`, 0 errors).

## Speed and how to cap work

Every model request goes through one in-flight cap (`--concurrency`, default 32; vLLM serves 32 to 64 well, see `serving/bench-results.md`). Every prompt starts with the step's fixed system prompt, so vLLM's prefix cache (`--enable-prefix-caching`, on in `serving/start_vllm.sh`) reuses it. `--sample N` (label and twin steps) picks a seeded sample spread across channel x language x outcome.

Measured on the fixture (generated tokens per thread; the fixture averages 4.7 renter messages per thread):

| step | tokens / thread | what costs |
|---|---|---|
| label | ~25k | Lightning reasons ~4.3k tokens per renter message |
| twin | ~40k | draft without reasoning (cheap); verification re-labels with reasoning; only failing turns are rewritten |
| filter | ~2.5k | blind rewrites of flagged lines |

At the bench's ~1,700 generated tokens/s (concurrency 32) that is about **1.5 threads/min**: roughly 5.5 h for 500 threads and 22 h for 2,000. `--sample` is the lever, for example `label.py --sample 400` followed by twins for all of them (about 4.5 h).

What was tried and rejected (fixture, 42 renter messages, compared with reasoning-on labels; reasoning-on against itself agrees 36/42):
- Lightning with reasoning **off** as labeler: 30x faster but all five fields agree only 8/42. Kept as `label.py --label-reasoning off`, not the default.
- The fine-tuned reader as labeler: 19/42 (it copies answers from earlier in the thread on real-style threads).
- Reasoning-off verification of twins: matches gold on 3/35 turns. Verification always reasons.
- Reasoning **on** for twin drafts: ~30k tokens per draft and repairs ran out of tokens before answering; drafts are reasoning-off by default (`--gen-reasoning on` to change).

Per-step timing and token use are appended to `work/timing.jsonl`.

If an endpoint call fails, a step stops before writing anything. Finished calls are cached, so rerunning resumes where it stopped.
