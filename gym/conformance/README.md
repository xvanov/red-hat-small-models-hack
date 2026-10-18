# gym/conformance: Messenger flow conformance suite (lane 4)

An executable version of the 67-item checklist in `docs/spec/concierge.md` §9. Each item is one behavior
of the owner's Marketplace/Messenger leasing flow. The suite runs scenarios against any operator config and
reports, per item, PASS, FAIL or BLOCKED. It answers one question: does this config behave like the Muse
flow the owner ran from Oct 4 to 18?

```
build.py        SOURCE OF TRUTH: the 67 items, the scenarios that test them, the reference player's moves
checklist.yaml  generated from build.py: id, text, stage, source date, required features, scenario + checks
checks.py       conformance-only check types (standard ones go through gym/rentus_env/verify.py unchanged)
engine.py       plays one scenario: phases, environment events, operator or reference player
features.py     probes for tools/state an item needs; a missing one makes the item BLOCKED
run.py          runs the suite for a RunConfig, prints the table, writes gym/results/conformance/<name>/
../tasks/messenger/<stage>.jsonl   the scenarios (generated), one file per checklist stage
```

## Run it

```bash
gym/.venv/bin/python gym/conformance/build.py                 # after editing build.py
gym/.venv/bin/python gym/conformance/run.py --reference       # privileged reference player, no model, ~5 s
gym/.venv/bin/python gym/conformance/run.py --variant guard+prompt3+style+rhist+readermodel --name final --workers 8
gym/.venv/bin/python gym/conformance/run.py --variant base --items C14,C23,C32   # a few items
gym/.venv/bin/python gym/conformance/features.py              # which required features exist right now
```

`--variant` takes the same specs as `gym/ablate.py` (the default is the final config from `docs/results.md`).
The model endpoint and reader come from `.env` exactly as in `run_eval.py`. Concurrency is capped at 8.
Scenarios that never reached the model (endpoint drops, vLLM restarts) are rerun after the endpoint answers
again (`--retry-errors`, default 2); scenarios that reached the model are never rerun.

Output: `summary.json` (item verdicts with the failing check details, per-stage counts, probed features,
config, git commit), `per_scenario.jsonl` (every check's result), `transcripts/<scenario>.json` (tool trace,
renter view, phase boundaries, operator messages).

## How an item is tested

An item lists one or more `(scenario, [check names])`. It PASSES only if every named check passes in every
listed scenario and the scenario's preconditions held. Several items share a scenario where one
conversation exercises them all (for example `msg-full-gate` carries C1 to C4, C10, C14, C15, C19, C26, C50,
C55, C58), which keeps the run short.

**Scenarios** are Gym tasks (`contracts/tools.md` §7) plus:

- **Seeded mid-flow state.** Most scheduling and post-tour scenarios start where the behavior begins (Dana
  already passed the gate, a showing is proposed or confirmed) so that a failure earlier in the flow cannot
  hide or fake a later item.
- **Phases.** Later operator runs on the same World, each opened by environment events the harness applies
  (never the operator): `clock` jumps, `confirm_event` (the owner edits the calendar), `owner_confirm`
  (lane 2's owner-only `owner_confirm_showing`), `delete_event` (owner reject), `renter_says`. The goal of a
  phase is an owner line ("Calendar: the showing E_seed ended at 15:30") or the new renter message.
- **Setup** steps run tools before phase 0 outside the scored trace (for example `log_followup
  application_sent` to start a cadence).
- **Tool probes** (`kind: tool_probe`) call tools directly with no model (matching, area resolution, the
  weekly rollup). Their result is the same for every config: they test the system, not the model.

**Renters** are scripted (`gym/rentus_env/counterparts.py`, classifier v2). Renter lines are synthetic,
written in `build.py` for this suite (no real renter text). A scripted renter has no catch-all line, so
operator messages without a question get no reply, which is what lets the suite see a disclosure burst.

**New check types** (only here, `checks.py`): `burst_question_last`, `disclosure_before_questions`,
`reply_to_line` (the operator's response to one renter message: last question asks item X, contains or
avoids phrases, message count), `reask_differs`, `msg`, `count_messages`, `message_order`,
`separate_messages`, `no_send`, `owner_notified`, `owner_text`, `no_time_offer_before_gate` (a time the
renter said themselves may be echoed), `no_confirm_claim`, `language_before`, `figures_in`, `listing_text`,
`event_ok`, `register_key` (finds `reconnect_at`, `proxy`, `sourcing` anywhere on the renter's row,
including lane 2's `demand` block), `register_rows`, `no_delete_tool`, `probe`. Message checks read what was
SENT: a draft a guard refused never reached the prospect, so guards count as conformance.

## Verdicts

- **BLOCKED** means a feature the item needs does not exist yet (`features.py` probes behavior on a scratch
  World, not names alone). Re-run after new tools land; blocked items unblock on their own. At the time of
  writing: C9 (2-occupant pricing on rooms), C16 (walkthrough video), C24 (quiet-window clock), C36 and C37
  (showing mode), C57 (10-minute unanswered alert).
- **The reference player** (`--reference`) is privileged: it plays each scenario from a fixed list of tool
  calls written next to the scenario in `build.py`, through the same tools and guards. It proves the
  scenarios are passable. It passes 60 of the 61 testable items. The one failure, C63, is a gap in the tool
  itself: `cluster_report` has clusters, WATCH, SUPPLY SIGNAL, totals and channels, but no matches-with-reasons
  section and no stale-row list, so no player can pass it.

## Known limits

- Times are simulated by clock jumps between phases. The 60 s quiet window and the 120 s small-talk wait
  (C24) cannot be tested in the sandbox; C56 tests burst handling with three messages already in the thread.
- The owner's "did the tour happen?" answer and calendar edits are environment events. The operator is told
  about them in an owner line, the way a calendar watcher would tell it.
- Keyword checks can miss an unusual phrasing (for example a warm line with none of the listed openers).
  Each failing check prints the message it judged, so a reviewer can overrule it from the transcript.
- The final config (`prompt v3`, verbose tools) does not expose lane 2's concierge tools (`park_prospect`,
  `capture_demand`, `due_followups` and others are only in `tool_schemas("concierge")` with prompt v4), so
  items that need them can fail for that config even though the tools exist. Run a v4/concierge config to
  measure them.
- This is a development check, not a headline number: the scenarios were written alongside the system,
  each item is one scenario run once (no seeds, no confidence interval).
