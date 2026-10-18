# Data provenance

Every dataset the system uses, where it came from, its license, what we took, and
how it reaches the running system. No real tenant or renter data is used anywhere.
All scripts live in `data/`; raw downloads go to `data/raw/` and large processed
files to `data/processed/` (both gitignored, rebuilt by the scripts). Small outputs
are committed under `data/published/`.

Rebuild everything:

```bash
cd data && uv venv .venv --python 3.12 && uv pip install --python .venv/bin/python -r requirements.txt && cd ..
data/.venv/bin/python data/download.py
data/.venv/bin/python data/build_reader_set.py
data/.venv/bin/python data/build_inventory.py
```

> **Owner clarification 2026-10-17:** teams may use any open dataset.

> **Privacy (applies to every use of the owner's data below):** private data never leaves infrastructure we control: this machine and our rented GPU instance (reached over an encrypted SSH tunnel); it is never sent to a third-party model API and never committed. The owner approved processing on the rented GPU (decision D28). The loopback check in `data/twins/common.LocalLLM` cannot tell a local server from an SSH-forwarded port, so "local endpoint" in this repo means "this machine or the rented GPU through the tunnel", never a hosted model API.

> **Licenses (decision D28, table in `LICENSES.md`):** code Apache-2.0 (`LICENSE`); SGD-derived reader data and the current reader weights CC BY-SA 4.0; the synthetic twin dataset CC BY 4.0 with attribution to nvidia/Nemotron-Personas-USA (it contains no SGD content); Gym tasks, style examples and inventory CC BY 4.0.

## Synthetic data is published with its method

The hackathon rules allow synthetic data only if the data and the method are
published openly. Ours are:

| Output | Method (code) | Published data |
|---|---|---|
| Reader training/eval set (synthetic part) | `data/build_reader_set.py`: hand-written English and Spanish templates composed per message, persona styling, labels known by construction. No LLM. Rules in `data/reader_schema.md`. Seeded, fully reproducible. | `data/published/reader/{train,dev,test}.jsonl` + `stats.json` |
| Spanish SGD translations (planned) | `data/translate_es.py`, plan in `data/translate_es.md`. Uses the operator model on vLLM; deterministic digit-preservation check. | will be added to the same folder when run |
| Sandbox room inventory | `data/build_inventory.py`: fictional rooms priced from UCI x ZORI, amenities from Inside Airbnb. | `data/published/inventory.json` + `inventory_stats.json` |
| Rewritten twins (draft, see below) | `data/twins/`: label skeletons of the owner's real threads rewritten by Lightning with Nemotron personas, verified and privacy-filtered. | `data/published/twins/` (stats card, filter report, twins, reader test set) + `gym/tasks/v3/heldout.jsonl` |

## Datasets

**Datasets on Hugging Face:** [xvanov/rentus-reader-messages](https://huggingface.co/datasets/xvanov/rentus-reader-messages) (reader set, CC BY-SA 4.0) and [xvanov/rentus-leasing-twins](https://huggingface.co/datasets/xvanov/rentus-leasing-twins) (synthetic twins, owner gold labels, Gym tasks v1–v3, CC BY 4.0). Byte-identical to `data/published/` and `gym/tasks/` (checksums in each repo's `SHA256SUMS`, uploaded and verified by `data/hf/publish_datasets.py`).

### Google Schema-Guided Dialogue (SGD, DSTC8)
- **URL:** https://github.com/google-research-datasets/dstc8-schema-guided-dialogue, pinned to commit `e852981ae34990f4358979625854259302feaa78` (`data/download.py` checks the commit in the archive's zip comment; derived `homes_dialogues.jsonl` sha256 `e0d67c28e876a4e947d7cbfa7c4b6d146d04145c7e2fd3b6191b752d0e4c0e3e`).
- **License:** CC BY-SA 4.0 (`LICENSE.txt` in the repo).
- **Used:** only dialogues whose services include `Homes_1` or `Homes_2` (1,273 dialogues: 847 train, 180 dev, 246 test), USER turns only as reader inputs, the preceding turns as thread context.
- **Transformations:** re-labeled for our reader schema by rules over SGD dialogue acts: `INFORM visit_date` -> `scheduling` intent (a showing date is not a move-in date); `REQUEST *` -> `question` (asking the property's phone is not a renter phone); `NEGATE_INTENT` -> `not_now`; `AFFIRM` after an operator turn about a visit -> `scheduling`; THANK_YOU / GOODBYE / AFFIRM / SELECT with no other act -> `small_talk`; a regex picks up "moving ... for work/school" as a `reason`. Everything else stays `absent`. SGD's own train/dev/test split is kept, so SGD test dialogues are never trained on. Up to 2,000 train turns and 300 per eval split are sampled (seeded).
- **Feeds:** reader fine-tune and eval (W6); context-length and ellipsis realism.
- **Share-alike:** because the reader files mix SGD-derived rows, `data/published/reader/` is released under **CC BY-SA 4.0**.

### UCI Apartment for Rent Classified
- **URL:** https://archive.ics.uci.edu/dataset/555/apartment+for+rent+classified
- **License:** CC BY 4.0.
- **Used:** the 100K-row file, NC monthly listings in Durham, Raleigh, Chapel Hill, Carrboro (1,421 listings, scraped 2018-12 to 2019-12).
- **Transformations:** median rent per bedroom over 2-3 BR listings per area (Durham $565, Raleigh $564, Chapel Hill/Carrboro $540, 2019 dollars); 1 BR medians kept for reference.
- **Feeds:** base price of each sandbox room (`build_inventory.py`); the market-rent tool can quote the same stats.

### Zillow Observed Rent Index (ZORI), ZIP level
- **URL:** https://files.zillowstatic.com/research/public_csvs/zori/Zip_zori_uc_sfrcondomfr_sm_month.csv (from https://www.zillow.com/research/data/)
- **License:** Zillow publishes this as free public research data under its Terms of Use, with attribution required ("Zillow Observed Rent Index (ZORI)"). It is not a Creative Commons license; we redistribute only derived ratios for ~15 ZIPs in `inventory_stats.json`, not the CSV.
- **Used:** NC rows only (258 ZIPs). For each inventory ZIP: value at 2019-12-31 and at the latest month (2026-09-30).
- **Transformations:** growth factor = latest / 2019-12 (city median when the ZIP has no 2019 value), applied to the UCI 2019 per-bedroom medians to bring them to 2026 dollars.
- **Feeds:** sandbox room rents; market-rent tool in the operator.

### Inside Airbnb, Asheville NC
- **URL:** https://insideairbnb.com/get-the-data/ (file used: `https://data.insideairbnb.com/united-states/nc/asheville/2026-09-19/data/listings.csv.gz`)
- **License:** CC BY 4.0.
- **Used:** the 267 "Private room" listings of the 2026-09-19 snapshot (Asheville is the only NC city Inside Airbnb publishes).
- **Transformations:** amenity frequencies, share with a private bath, share with a private entrance. No listing text, names, host data or photos are kept.
- **Feeds:** amenity mix and private-bath / own-entrance rates of the sandbox rooms.

### nvidia/When2Call
- **URL:** https://huggingface.co/datasets/nvidia/When2Call
- **License:** CC BY 4.0.
- **Used:** downloaded in full to the local HF cache; a seeded 2,000-row sample written to `data/processed/hf_samples/` for inspection.
- **Feeds (planned):** examples of when to call a tool vs ask a follow-up vs refuse, for operator prompt design and Gym scenarios (W2/W4). Not mixed into the reader set.

### nvidia/Nemotron-RL-Agentic-Conversational-Tool-Use-Pivot-v1
- **URL:** https://huggingface.co/datasets/nvidia/Nemotron-RL-Agentic-Conversational-Tool-Use-Pivot-v1
- **License:** CC BY 4.0.
- **Used:** the first 20,000 lines of `train.jsonl` (1.75 GB file) streamed, then a seeded 2,000-row sample to `data/processed/hf_samples/` for inspection. Our pinned `datasets==3.2.0` cannot parse this card's `Json` feature type, so `download.py` streams the raw JSONL instead.
- **Feeds (planned):** NeMo Gym-format conversational tool-use trajectories as a reference for the Gym environment and any operator LoRA (W4).

### Owner style statistics and example replies (`data/style/`, lane 5)
- **Source:** the owner's private, anonymized message export (owner-written rows of the tenants and contractors datasets). Read locally; private data never leaves infrastructure we control: this machine and our rented GPU instance (reached over an encrypted SSH tunnel); it is never sent to a third-party model API and never committed.
- **Published:** `owner_style_stats.json`, aggregate numbers only (message length, sentences, questions, greetings, emoji, dashes, language mix, burst rate, hour histogram), no text; `compute_stats.py` (code; needs the private export to run); `tone-guide.md`; `examples.jsonl`, 30 synthetic example replies written from scratch by an agent (every row `"synthetic": true`, invented names, streets and prices).
- **License:** CC BY 4.0, like the twins.
- **Feeds:** operator prompt style and few-shot examples (`docs/playbooks/`).

## Excluded or skipped

- **Salesforce xLAM function-calling datasets: excluded.** Released for research use only, which does not fit an openly published hackathon submission.
- **HUD Fair Market Rents API and Census ACS API: skipped.** HUD's API needs a registered token we don't have; ZORI + UCI already cover rent levels. Can be added later if a key is obtained (the Census API works keyless at low volume).
- **Nemotron Personas:** not used by the reader set, which uses hand-written persona styles in code. The twins pipeline uses it (below).

## Reader set at a glance (seed 7)

| Split | Rows | Synthetic | SGD | Published |
|---|---|---|---|---|
| train | 14,000 | 12,000 | 2,000 | all: `train_full.jsonl.gz` (sha256 of the uncompressed file `3d9237ef6e79f8a18bdd22fde1417b019b86eb318ae152239dfb22694a3d19b3`, verified by `data/publish_reader_train.py --check`); `train.jsonl` keeps the first 5,000, which the Gym task builders read |
| dev | 1,100 | 800 | 300 | all |
| test | 1,419 | 1,144 | 275 | all |

Test is held out only partly by template. Correction 2026-10-18 (leakage review #4): the test split draws a
test-only template with probability 0.6 and otherwise from **all** templates (`build_reader_set.py` `pick`), and
openers, closers and joiners are not split at all. Measured: 188 of the 1,144 synthetic test rows use only
templates that also occur in train/dev, 956 use at least one test-only template; 47 synthetic and 6 SGD test rows
equal a train/dev row after normalizing punctuation and digits. So the right description is "test-biased templates
(60% test-only draws), test-only name / employer / school / city / area-code pools, SGD's test dialogues, exact
lowercase duplicates of train/dev dropped". The set is frozen and not regenerated (that would void the scores);
`docs/results.md` reports exact match on both template groups. Full label counts per split are in
`data/published/reader/stats.json`.

### nvidia/Nemotron-Personas-USA
- **URL:** https://huggingface.co/datasets/nvidia/Nemotron-Personas-USA
- **License:** CC BY 4.0.
- **Used:** shard `data/train-00000-of-00011.parquet`; a seeded sample of 4,000 adults (age 19-68), fields uuid, persona, professional_persona, hobbies, sex, age, marital status, education, occupation, city, state (`data/twins/personas.py`).
- **Feeds:** the invented renter of each rewritten twin. Each published twin and v3 task carries the persona with its source uuid and license.

## Method (draft): rewritten twins of real conversations

**Status:** pipeline built and tested end to end on 10 invented fixture threads (`data/twins/fixtures/`). Not yet run on real data; the owner supplies the anonymized exports (decision D22).

**Why.** The open synthetic sets are clean by construction. Real renters are vaguer, switch language, push on price and go silent. Twins carry that shape into open data without carrying any real person's words.

**How a twin is made** (code in `data/twins/`, details in its README):
1. *Ingest.* The owner's own anonymized exports (iMazing SMS CSV, Facebook Messenger JSON, generic CSV/JSONL) are loaded on the owner's machine, outside the repo. Sender names are dropped, thread ids are salted hashes, and a second regex scrub replaces phones, emails, URLs, street addresses and unit/id numbers. Non-rental threads are dropped (keyword score; Lightning decides borderline threads).
2. *Label.* Lightning, served locally on vLLM, labels every renter message with the reader schema using the reader's own prompt, every owner message with what it does (questions classified by the Gym's deterministic classifier), and every thread with its outcome (qualified, showing, applied, ghosted, no).
3. *Rewrite.* For each thread Lightning writes a twin from the **label skeleton only**: the speaker of each turn, each renter message's statuses, intents and language, style hints (length, emoji, casing), timing gaps and the ending. It does not see the real wording. The renter is a Nemotron persona; dates are shifted into Oct 2026 to Feb 2027, the phone is a fictional 555-01xx number, and reason, job and details are invented. The prompt forbids reusing any 4-word phrase.
4. *Verify.* Each twin renter message is re-labeled and must equal its target (statuses, dates, values, intents, language). Mismatches go back for a rewrite, up to 3 attempts. Twins that still fail are dropped. Gold labels are known by construction: the original's labels with the twin's own dates, phone and reason.
5. *Privacy filter.* Every twin line is compared with every real line: character 8-gram containment (>= 0.5 of the twin line, or >= 0.6 of a real line), embedding cosine >= 0.90 (`paraphrase-multilingual-MiniLM-L12-v2`, local CPU; embedding models are outside the 33B budget), exact match, and PII regex. A flagged line is rewritten blind and re-verified, or the twin is dropped. Real phrases that occur in 3+ different threads count as common and are not protected. The filter asserts that the published set passes.

**Privacy guarantees.** Private data never leaves infrastructure we control: this machine and our rented GPU instance (reached over an encrypted SSH tunnel); it is never sent to a third-party model API and never committed. Concretely: labeling, twin verification, the privacy-filter rewrites and the H6 replay send anonymized real threads to Lightning on vLLM on our single-tenant rented Brev GPU, reached through `serving/tunnel.sh`; vLLM there binds to 127.0.0.1 and runs without request logging. The pipeline's model client refuses any endpoint that is not loopback (an SSH-forwarded port counts as loopback, which is why the sentence above names the GPU instance explicitly). All intermediates holding real text stay in `~/rentus-private-data/work/` on this machine. The instance's disk and container logs are wiped at teardown.

**What is published.**
- `stats_card.json`: aggregates of the real threads (counts, rates, quartiles), with cells under 5 suppressed.
- `filter_report.json`: privacy filter counts and thresholds.
- `twins.jsonl`, `reader_test.jsonl`: twin conversations with gold labels, and a reader test set in the `data/reader_schema.md` row format (`source: "twin"`).
- `gym/tasks/v3/heldout.jsonl`: held-out Gym tasks (format in `contracts/tools.md` §10).

Twins are released under CC BY 4.0 (D28), and their personas keep Nemotron-Personas-USA's CC BY 4.0 attribution. They contain no SGD content.

**Limits.** The regex scrub is a second layer and misses free-form identifiers, so the owner's anonymization comes first. Labels come from a model, so a mislabeled real message gives a twin whose shape is slightly off, but the twin's gold labels still match the twin's text. Thread outcomes are model judgements.
