# data/style

Style material for the operator's prompts (lane 5).

| File | What it is | Publishable? |
|---|---|---|
| `owner_style_stats.json` | Aggregate statistics of the owner's own messages: length, sentences, questions, greetings, thanks, apologies, emoji, dashes, language mix and mirroring, burst rate, hour histogram | yes: numbers only |
| `compute_stats.py` | The script that produced the JSON | yes: code only; it needs the private export to run |
| `tone-guide.md` | The voice: what to do and avoid, by situation | yes |
| `examples.jsonl` | 30 synthetic example replies for few-shot prompts | yes: written from scratch, no real text |

## Provenance and method

- **Source of the statistics:** the owner's private, anonymized message export (tenants and contractors datasets, owner rows only; the landlords dataset was not used). It was read locally on the owner's machine; no text went to any external API. Only aggregate numbers are published. Regex heuristics, so treat shares as estimates (language within roughly plus or minus 30%).
- **Reproduce:** `python3 -I data/style/compute_stats.py <path to anonymized export> > data/style/owner_style_stats.json`.
- **Examples:** every line in `examples.jsonl` has `"synthetic": true`. They were written by hand (by the lane 5 agent) in the tone the statistics and the local read describe, for situations covered by `docs/playbooks/`. Names, streets and prices in them are invented. Each example lists the record `facts` the reply relies on, so a few-shot prompt never teaches the model to quote a number that is not in a record.
- **Checks on the examples:** at most 2 sentences per message, at most one question per reply and only in the last message, no long dashes (validated when the file was written).
- The coordinator should add this entry to `docs/data-provenance.md` (lane 5 does not own that file).

## Example record

```json
{"id": "ex17", "synthetic": true, "situation": "partial_rent_received", "playbook": "08", "language": "en",
 "facts": {"ledger": "rent $750, received $500, remainder $250"},
 "incoming": "(received $500 of $750 rent)",
 "reply": ["Hi, I received $500 for October rent, thank you.", "That leaves $250, when do you think you can send the rest?"],
 "note": "exact facts, one question, no new terms"}
```

`reply` is a burst: each string is one message.
