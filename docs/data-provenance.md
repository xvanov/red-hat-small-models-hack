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

## Synthetic data is published with its method

The hackathon rules allow synthetic data only if the data and the method are
published openly. Ours are:

| Output | Method (code) | Published data |
|---|---|---|
| Reader training/eval set (synthetic part) | `data/build_reader_set.py`: hand-written English and Spanish templates composed per message, persona styling, labels known by construction. No LLM. Rules in `data/reader_schema.md`. Seeded, fully reproducible. | `data/published/reader/{train,dev,test}.jsonl` + `stats.json` |
| Spanish SGD translations (planned) | `data/translate_es.py`, plan in `data/translate_es.md`. Uses the operator model on vLLM; deterministic digit-preservation check. | will be added to the same folder when run |
| Sandbox room inventory | `data/build_inventory.py`: fictional rooms priced from UCI x ZORI, amenities from Inside Airbnb. | `data/published/inventory.json` + `inventory_stats.json` |

## Datasets

### Google Schema-Guided Dialogue (SGD, DSTC8)
- **URL:** https://github.com/google-research-datasets/dstc8-schema-guided-dialogue
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

## Excluded or skipped

- **Salesforce xLAM function-calling datasets: excluded.** Released for research use only, which does not fit an openly published hackathon submission.
- **HUD Fair Market Rents API and Census ACS API: skipped.** HUD's API needs a registered token we don't have; ZORI + UCI already cover rent levels. Can be added later if a key is obtained (the Census API works keyless at low volume).
- **Nemotron Personas:** not downloaded. The synthetic reader set uses hand-written persona styles in code (casual, formal, terse, emoji, all-caps; English/Spanish name pools) in that spirit.

## Reader set at a glance (seed 7)

| Split | Rows | Synthetic | SGD | Published |
|---|---|---|---|---|
| train | 14,000 | 12,000 | 2,000 | first 5,000 |
| dev | 1,100 | 800 | 300 | all |
| test | 1,419 | 1,144 | 275 | all |

Test is held out: it uses test-only templates (every 5th template in each list),
test-only name / employer / school / city / area-code pools, SGD's test dialogues,
and any test message that also appears verbatim in train or dev is dropped. Full
label counts per split are in `data/published/reader/stats.json`.
