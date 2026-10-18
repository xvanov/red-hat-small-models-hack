# labeler: blind owner labels for the twin reader test

The confirmatory H2 gold (eval-protocol Amendment 1, A1a): the owner labels renter messages **blind**. The page shows
only the last 1-2 context lines, the renter message and the "today" date. It never shows any model's label.

## Start

```bash
cd labeler && uv venv .venv --python 3.12 && uv pip install --python .venv/bin/python -r requirements.txt   # once
labeler/start.sh                  # auto: real set when frozen, fixture until then
labeler/start.sh --source real    # force the real set
```

Open **http://100.64.38.18:8090** (tailnet only). `start.sh` runs `server.py` on `127.0.0.1:8090` and
`scripts/tailnet_forward.py --listen 100.64.38.18:8090 --target 127.0.0.1:8090`, both under nohup; logs and pid
files are in `labeler/logs/` (gitignored). Rerunning `start.sh` restarts both.

## Sample

A1a: all renter rows of a simple random sample of twin threads, seed 0 (`random.Random(0).sample` over the sorted
twin ids, the same draw as `gym/stats.py simple_random_sample`), added thread by thread until at least 150 rows.
Drawn once and written to a manifest (twin ids, row ids, `row_ids_sha256`, source sha256); every restart reuses it.

| mode | source | manifest | labels |
|---|---|---|---|
| real | `data/published/twins/reader_test.jsonl` | `sample_manifest.json` | `out/owner_labels.jsonl` |
| fixture | `data/twins/fixtures/out/published/reader_test.jsonl` | `sample_manifest.fixture.json` | `out/owner_labels.fixture.jsonl` |

`--source auto` switches to real only once the real file's sha256 matches `frozen_sha256` in `data/twins/splits.json`
(written by `to_tasks.py` after the file), so a half-written file is never sampled. Once `sample_manifest.json`
exists, real mode is locked in. The two modes never share a manifest or a label file; the open page reloads by
itself when the mode changes. Commit `sample_manifest.json` as soon as it appears.

## Labels

`out/labels_log.<mode>.jsonl` (gitignored) is the source of truth and is **append-only**: every save, audit change
and undo is a new line, nothing is rewritten or deleted (undo appends an `undo` record; the item falls back to its
previous save). On first start it is seeded from an existing `owner_labels*.jsonl` (`save_reason: "imported_pre_log"`).
`out/owner_labels.jsonl` (gitignored) is derived from it on every save: the latest label per item, in sample order:
`id, labeler: "owner", ts, mode, sample_sha256, skipped, output` (reader-schema fields), `ui` (the raw button
values) and `save_reason` (`label` or `audit`). `out/history.<mode>.jsonl` logs every save and undo.

The form is always filled from the latest saved label of the item, every field (Back, browser back/forward, a
reload, a tab restored from the browser cache). The item position is in the URL (`#i=12`). A save from a form that
was loaded from an older version of the item (a stale tab) is refused with 409 and the page reloads the item.

UI value to schema: lease yes/no/vague/exception/not mentioned -> `answered true / no false / vague / exception true /
absent`; move-in exact + date -> `answered` (or `exception` with the condition box); phone given + number -> `answered`
E.164 (`exception` with the caveat box), declined -> `no`; occupants 1-5+ -> `answered` count (`exception` with the
part-time guest box); reason given/declined -> `answered`/`no`, value null (scored on status only); language
`other` is stored as `"other"` (the schema has en/es only). Skip saves `skipped: true, output: null`.

Move-in exact date: a month dropdown (names), a day number and a year prefilled from the item's conversation
date (it follows "next time that date comes after the conversation date" until edited); the date is shown in words.

Tests: `node <script>` with Playwright against a server started with `LABELER_OUT=<copy dir>` (never the real
`out/`), e.g. `LABELER_OUT=/tmp/x labeler/.venv/bin/python labeler/server.py --source fixture --port 8191`.

## Audit (eval-protocol Amendment 3)

`/audit` lists every label flagged by a deterministic rule from `data/reader_schema.md` over the item's own text
and "today" (`labeler/audit.py`; **no model output of any kind**, not even the twin gold). Each flag shows the
message, the owner's label, the rule, and its suggested value: **Keep** records the decision
(`out/audit_decisions.<mode>.jsonl`), **Change** appends a new owner label with `save_reason: "audit"`, and
**Edit in labeler** opens the item with the same reason. `labeler/.venv/bin/python labeler/audit.py` writes the
counts per rule to `out/audit_summary.json`.

Keys (desktop): up/down or j/k pick a field, 1-9 choose, Enter save & next, left arrow back, s skip, u undo.
`server.py --reset [--source fixture]` moves that mode's labels, log and history aside as `*.reset-<time>.jsonl` (the manifest stays).
