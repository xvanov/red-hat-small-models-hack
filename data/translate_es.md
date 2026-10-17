# Spanish translation of SGD Homes renter turns (plan)

**Status:** script ready (`data/translate_es.py`), not run yet. It needs the vLLM
endpoint from W1 (`OPERATOR_BASE_URL`, `OPERATOR_MODEL`).

## Why

The synthetic reader set already has ~25% Spanish, but all of it comes from our
own templates. Translating the SGD Homes renter turns adds Spanish phrasing we did
not write, for the cases SGD covers well: search requests, property questions,
showing scheduling, thanks/goodbye, "not now".

## Method

1. Take every `source == "sgd"` row from `data/processed/reader/{split}.jsonl`.
2. Send its thread context and message to the operator model (Nemotron 3.5
   Lightning on vLLM, already counted in the parameter budget, so no extra model)
   with a fixed system prompt: translate to informal Latin American Spanish, keep
   numbers, dates, phones, names; return JSON only. Temperature 0.3.
3. Deterministic verifier per row: valid JSON, same number of context turns, the
   multiset of digit runs in the message is unchanged. Up to 2 retries, then the
   row is dropped and counted.
4. Labels are copied unchanged from the English row (the SGD relabel rules are
   language-independent) except `language = "es"`. Rows are tagged
   `machine_translated` and keep `meta.translated_from`.
5. Each translated row stays in its original split. SGD test dialogues stay test.
6. Rebuild: `python data/build_reader_set.py --with-sgd-es` appends
   `sgd_es_{split}.jsonl` to the matching split.

## Run

```bash
data/.venv/bin/python data/translate_es.py --dry-run        # no network
export OPERATOR_BASE_URL=... OPERATOR_MODEL=...              # values from .env, by name
data/.venv/bin/python data/translate_es.py --limit 300       # resumable, appends
data/.venv/bin/python data/build_reader_set.py --with-sgd-es
```

## Caveats

- Machine translation; a sample of ~50 rows should be spot-checked by a Spanish
  speaker before reporting Spanish test numbers on `sgd_es` rows. Report them
  separately from the hand-templated Spanish rows.
- Since the operator model produces the translations, a reader evaluated against
  the operator on these rows may share its phrasing bias. Keep the template-based
  Spanish test rows as the main Spanish number.
