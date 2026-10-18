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

`out/owner_labels.jsonl` (gitignored): one line per item, rewritten atomically on every save, in sample order:
`id, labeler: "owner", ts, mode, sample_sha256, skipped, output` (reader-schema fields) and `ui` (the raw button
values). `out/history.<mode>.jsonl` logs every save and undo.

UI value to schema: lease yes/no/vague/exception/not mentioned -> `answered true / no false / vague / exception true /
absent`; move-in exact + date -> `answered` (or `exception` with the condition box); phone given + number -> `answered`
E.164 (`exception` with the caveat box), declined -> `no`; occupants 1-5+ -> `answered` count (`exception` with the
part-time guest box); reason given/declined -> `answered`/`no`, value null (scored on status only); language
`other` is stored as `"other"` (the schema has en/es only). Skip saves `skipped: true, output: null`.

Keys (desktop): up/down or j/k pick a field, 1-9 choose, Enter save & next, left arrow back, s skip, u undo.
`server.py --reset [--source fixture]` deletes that mode's labels and history (the manifest stays).
