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

## The owner's anonymized export (the real run, 2026-10-18)

The owner's phone messages arrive as an anonymized export (`~/rentus-private-data/raw/anonymized-YYYY-MM-DD/`:
`{tenants,contractors}/messages.jsonl` + `people.csv`; `landlords/` is ignored). This path replaces the
inquiry-only flow above:

```bash
RAW=~/rentus-private-data/raw/anonymized-2026-10-18
PY=data/twins/.venv/bin/python
$PY data/twins/split.py --raw $RAW            # relevance + protocol split -> work/twins/selection.json, data/twins/splits.json
$PY data/twins/ingest.py --anon $RAW          # episodes per split -> work/twins/{heldout,dev}/threads.jsonl
for S in heldout dev; do
  $PY data/twins/label.py  --split $S --labeler reader
  $PY data/twins/twin.py   --split $S
  $PY data/twins/filter.py --split $S
  $PY data/twins/to_tasks.py --split $S
done
$PY data/twins/review_sheets.py               # owner sheets, private: work/label-spotcheck.md, work/realism-review.md
```

- **Loader** (`ingest.load_anon_selected`): owner = sender `me` plus `people.csv` rows with role `partner` (they speak
  for the operator side, e.g. lead hand-offs); contractor threads get the role `vendor`; channel `sms`; tap-back
  reactions ("Liked …", "Le gustó …") are dropped; attachment-only messages are kept as `[photo]` / `[video]` /
  `[file]`; each message keeps its `people.csv` person id (private work files only) so the people rule can be checked.
  Whole threads are kept (cap 600); a twin mirrors one **episode** of at most 40 messages (leasing from the start;
  tenant ops from the first ops message; a leasing thread that becomes a tenancy yields one of each). The rental
  keyword filter is skipped: relevance comes from the selection.
- **Relevance** (`split.py`): leasing, tenant ops, and contractor repairs at rental houses only. Dev = the
  exploration's recommended lists (`work/explore-*`); held-out candidates are classified by Lightning (reasoning on),
  contractor threads by the exploration's manual read. Only threads with one counterpart person; Russian excluded.
- **Split** (eval-protocol 2.2): held-out = conversations starting on/after 2026-05-01 none of whose counterpart
  person ids appear in an earlier conversation (all datasets); window conversations that share a person are dropped
  from both splits. `data/twins/splits.json` records the sha256 of the held-out id list, counts, and (after
  `to_tasks.py`) the people check and the frozen task hashes. `to_tasks.py --split heldout` asserts that no held-out
  person id appears in a dev thread.
- **Damaged dates**: a counterpart message where the anonymizer replaced a day with a street word ("<Month>
  <StreetWord>") or put `[state]` next to a date is flagged; its move-in is unscorable (reader rows carry
  `meta.unscorable`, tasks drop the move-in check, and a thread whose only gate item is such a move-in is excluded).
- **Labels**: message labels from the fine-tuned **reader** (`--labeler reader`); thread labels (owner acts, outcomes;
  for ops/contractor episodes also counterpart acts and topic) from **Lightning with reasoning on**; a regex
  **rule cross-check** on every message and leasing-thread outcome. Agreement rates go to `label_agreement.json`
  and the stats card.
- **Twins are kept as written.** One draft per episode (retried only for broken structure); no rewriting until a
  model reads the twin "correctly", because that would keep only text the labeler finds easy. The privacy filter's
  rewrites are accepted on the privacy tests alone.
- **Twin reader test selection rule**: every twin renter message with text from a held-out leasing twin becomes a
  row (attachment-only messages excluded); no row is dropped for label disagreement. Gold = the reader's labels of
  the real message carried over with the twin's own values (new date, fictional phone); `reason` is scored on
  status only. Rows where the rule check disagrees with the gold are flagged (`meta.flagged`, `meta.flags`), and the
  owner's spot-check (protocol 7.2) is the arbiter of label quality.
- **Task gold = the truth sheet** written at generation time: the exact values the twin writer was told to express
  (statuses/intents come from the reader's reading of the real message, values are the twin's own). Reader and
  Lightning labels are diagnostics only. Disclosed tilt: which values a twin carries was shaped by the reader.
- **Gold-in-text consistency (drop rule fixed before the run)**: a leasing twin is dropped when any renter message's
  truth sheet says phone answered/exception but the text lacks the assigned fictional number, or phone is not given
  but the text has a full 10-digit number, or move-in answered/exception with a date the text does not express
  (month + day). Other fields and intents are flagged only. Counts: `tasks_stats.json` and `splits.json`.
- **Rules-period tag**: tasks from held-out threads that start on/after 2026-10-04 carry
  `tags: ["rules_period_ge_2026_10_04"]` so H1 can be re-run without them (sensitivity).
- **Ops / contractor twins** become experimental tasks in `gym/tasks/v3/<split>_ops.jsonl` (generic checks only), never
  pooled into H1. `gym/tasks/v3/heldout.jsonl` holds leasing tasks only.

## Setup

```bash
cd data/twins && uv venv .venv --python 3.12
uv pip install --python .venv/bin/python torch==2.5.1 --index-url https://download.pytorch.org/whl/cpu
uv pip install --python .venv/bin/python -r requirements.txt
```

Needs the local vLLM endpoints from `.env`: `OPERATOR_BASE_URL` (Nemotron 3.5 Lightning, default `http://localhost:8000/v1`) and, for `--labeler reader`, `READER_BASE_URL`.

## Steps

Every step is idempotent (model replies are cached in `work/cache/`, randomness is seeded per thread) and takes `--fixture`, `--limit N`, `--sample N` and `--concurrency N`.

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
2. **Private data never leaves infrastructure we control** — this machine and our rented GPU instance (over an encrypted SSH tunnel); it is never sent to a third-party model API and never committed. The only model client (`common.LocalLLM`) refuses any endpoint that is not loopback, private (RFC 1918) or tailnet (100.64/10); the vLLM endpoints are reached through the SSH tunnel on localhost. The embedding model runs on CPU here.
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
