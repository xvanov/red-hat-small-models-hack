# Freeze procedure (v3 confirmatory runs)

eval-protocol Amendment 2, round-2 item 11 (N13). The freeze is one commit that records the sha256 of every input the confirmatory analysis depends on, made **before any model reads the v3 held-out tasks or the owner-labeled rows**. After it, a run counts only if it ran on the same frozen content (`gym/frozen.py`, enforced by `gym/stats.py plan`).

Check where things stand at any time (no model calls, writes nothing):

```bash
python3 scripts/freeze.py --check      # exit 0 = freezable, 1 = something below is missing
```

## 1. Owner sign-offs needed

Each one is a line in `docs/DECISIONS.md` containing `FREEZE-SIGNOFF <id>` (for example `| D32 | Oct 18 07:40 | FREEZE-SIGNOFF realism-7.1: 8/20 identified, mean realism 3.9, pass | ... | Owner |`). `scripts/freeze.py` looks for these exact ids.

| id | what the owner confirms | needed before | if it is not done by the cut-off |
|---|---|---|---|
| `blind-labels` | The blind H2 labels are finished in the labeler (`labeler/`, port 8090): every row of the A1a sample (simple random sample of twin threads from `data/published/twins/reader_test.jsonl`, seed 0, at least 150 rows) is labeled or explicitly skipped. Then `python3 scripts/owner_gold.py` writes `data/published/twins/owner_gold.jsonl` and `owner_gold_audit.json`. | freeze | The owner writes `FREEZE-SIGNOFF blind-labels: not done, H2 not tested`. H2a and H2b are reported as not tested (p = 1, still in the Holm family). Agent runs are not blocked |
| `realism-7.1` | Twin realism review (protocol §7.1): 10 real + 10 train twins, shuffled, blind; real-or-twin call and a 1-5 rating | freeze | v3 is reported as "synthetic, realism not confirmed" |
| `label-check-7.2` | Blind check of the task-deciding labels (§7.2 as extended by A7 P-6; sheet owned by the twins agent, `data/twins/review_sheets.py`) | freeze | the fallback in A7 P-6 applies (fields below threshold are dropped) |
| `playbooks-7.4` | Playbooks and the 45-day showing window approved as scoring sources (round-2 N14) | freeze | unapproved flows score nothing; without the 45-day window the showing rule is unscored |
| `protocol-7.5` | `docs/eval-protocol.md` including Amendments 1 and 2 | freeze | no freeze |
| `cutoff-N12` | The clock time after which missing owner work counts as not done (round-2 N12) | the first of the above | — |

Not a freeze gate, done later:

| what | when |
|---|---|
| **κ grading** (§7.3 / A5): 40 transcripts, simple random sample, blind, verdict first | after all held-out runs finish, before the write-up. If not done, the scorer is reported as "scorer-defined" |
| Replay aggregate privacy check (§7.6) | before `data/published/replay/aggregate.json` is committed |

## 2. Artifacts the freeze records

`scripts/freeze.py` hashes each of these (the list is `ARTIFACTS` in the script). Required ones block the freeze; optional ones, when absent, make only their dependent hypothesis "not tested".

| group | files |
|---|---|
| task sets | `gym/tasks/v3/heldout.jsonl`; `gym/tasks/v3/heldout_ops.jsonl` (optional, secondary); `data/published/twins/twins.jsonl`; `data/twins/splits.json` |
| reader rows | `data/published/twins/reader_test.jsonl`; `labeler/sample_manifest.json` (the A1a sample); `data/published/twins/owner_gold.jsonl` and `owner_gold_audit.json` (optional: H2 gold) |
| reader checkpoint | `reader/release/rentus-reader/model.safetensors` (local, gitignored; must equal release reader-v1, `877c8843...`) |
| serving config | `serving/FROZEN.json` (image digest, checkpoint id and revision, exact args; its "TO CONFIRM" values must be confirmed from the instance first), `serving/start_vllm.sh`, `reader/serve_reader.sh` |
| confirmatory plan | `gym/confirmatory_v3.json`, `gym/stats.py`, `gym/frozen.py`, `gym/frozen_paths.txt` |
| scorer and prompts | `gym/rentus_env/verify.py`, `gym/rentus_env/v3_rules.py`, `tools/rentus_tools/impl/inbox.py`, `operator/prompts/system_v3.md`, `reader/prompt.py`, `docs/eval-protocol.md` |
| floors (A4, N11) | `gym/results/v3-floors.json` = `gym/.venv/bin/python gym/floors.py --tasks-file gym/tasks/v3/heldout.jsonl --json` (no model calls) |
| private, hash only | `~/rentus-private-data/work/replay/thread_ids.json` (H6 replay thread ids, optional) |

It also records a content hash of every frozen path tree (`gym/frozen_paths.txt`: `gym/rentus_env`, `gym/tasks`, the run and stats code, `tools`, `operator`, `reader/prompt.py`, `reader/eval.py`, `serving`, `data/twins`, `data/published/twins`, `scripts/frontier_ref.sh`) and the sign-off lines it found.

## 3. Freeze commit, step by step

1. Every lane commits its work. `git status --porcelain -- $(grep -v '^#' gym/frozen_paths.txt)` prints nothing.
2. The twins build has run on held-out (`to_tasks.py --split heldout`); `data/twins/splits.json` holds its `frozen_sha256`.
3. Floors: `gym/.venv/bin/python gym/floors.py --tasks-file gym/tasks/v3/heldout.jsonl --json > gym/results/v3-floors.json`.
4. Serving: copy the image digest and `refs/main` of the BF16 checkpoint from the instance into `serving/FROZEN.json`, replacing the "TO CONFIRM" notes; commit.
5. Owner labels: `python3 scripts/owner_gold.py --check`, then `python3 scripts/owner_gold.py`; commit `labeler/sample_manifest.json`, `data/published/twins/owner_gold.jsonl` and `owner_gold_audit.json`.
6. Owner sign-offs (section 1) land in `docs/DECISIONS.md`.
7. `python3 scripts/freeze.py --check` says FREEZABLE.
8. `python3 scripts/freeze.py --write` writes `docs/freeze-manifest.json`. Commit **only that file**: `git commit -m "Freeze v3 ..." -- docs/freeze-manifest.json`, then push. That commit is the freeze commit (`gym/frozen.py freeze_commit()` = the last commit touching the manifest).
9. Protocol §6.1 points to `docs/freeze-manifest.json` for the hashes (Amendment 2). The manifest keeps the hash of the protocol as frozen; any later protocol text change is a post-freeze entry in its Amendments table and cannot change a hypothesis, test or margin.
10. Start the runs with the exact commands in `gym/confirmatory_v3.json` `"launch"`. `gym/run_eval.py` refuses a v3 held-out run on dirty frozen paths or a task file that is not the frozen one; `scripts/frontier_ref.sh` does the same.
11. Analysis: `gym/.venv/bin/python gym/stats.py plan gym/confirmatory_v3.json --check` lists every missing or rejected run, then `... plan gym/confirmatory_v3.json --md`.

## 4. Rules after the freeze

- The manifest is written once; `scripts/freeze.py --write` refuses if it exists. Changing any frozen artifact or frozen path afterwards makes every later run void under the gate. A deliberate re-freeze is a new protocol version (v3.1) with fresh baselines, recorded as a protocol amendment.
- Commits outside the frozen paths (console, docs, results) during the runs are fine: a run counts when its commit's frozen paths are byte-identical to the freeze commit's.
- A run counts only if its `summary.json` is not void, has no `still_failed` rollouts, recorded `dirty_frozen_paths: false` (for the run and every retry), and its task file sha256 equals the frozen one. H2 preds count only if their metrics file scored the frozen `owner_gold.jsonl`.
