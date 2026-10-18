# Task set v2: what changed and why

**Status (2026-10-17):** v2 is built, and the privileged reference player and the gym tests check it. **No model has run on it** (no GPU, no API calls). Please approve it before any paid reruns. The flaws it fixes are listed task by task in `docs/task-review.md`.

- v1 is untouched: `gym/tasks/{train,heldout}.jsonl`. Regenerating with `python gym/build_tasks.py` reproduces it byte for byte, and every committed result used it.
- v2: `gym/tasks/v2/{train,heldout}.jsonl` plus `stats.json`, from the same script (`Builder2` and `PLAN2` in `gym/build_tasks.py`).
- To run on v2 later: `run_eval.py --tasks-version v2` (also works for `ablate.py`; the default is still `v1`). `summary.json` now records `tasks_version`. Reference player: `oracle.py --tasks-version v2`.

## At a glance

| | v1 held-out | v2 held-out | v1 train | v2 train |
|---|---|---|---|---|
| tasks | 31 | 33 | 51 | 54 |
| checks | 328 | 332 | 531 | 535 |
| reader utterances used | 88 | 93 (82 same as v1) | 142 | 158 (135 same) |
| tasks whose room availability is set in the task | 0 | 8 | 0 | 8 |
| move-in date before the room is free | 8 | 0 (and 2 early_date tasks, on purpose) | 14 | 0 (and 3 on purpose) |
| reusable fallback lines in renter scripts | 0 | 95 | 0 | 145 |
| do-nothing / stub reward floor | 0.218 | 0.291 | | |
| reference player | 31/31 | **33/33** | 51/51 | **54/54** |

The separation rules are the same. Held-out renter lines come only from the reader `test.jsonl` (a test asserts this), train lines only from `train.jsonl`, there is no overlap, and the template pools and rooms (odd vs even inventory index) are disjoint. The seeds are the same too.

## Generator changes (`gym/build_tasks.py`)

1. **Move-in dates fit the room.** Each task's room is chosen so that `available_from <= move-in <= max(available_from, task date) + 90 days`. If no room in the split fits the date, the task sets that room's `available_from` in its own `initial_state` (to the 1st of the move-in month, or the task date if that is later), and the live listing text shows the same date. The inventory file is not changed. *Why:* in 8 held-out tasks the renter wanted a date up to 75 days before the room was free; an operator that noticed got no reply. That was the main cause of Opus's leasing failures. Patching availability keeps utterance variety, where filtering rooms alone would have reused the same few lines. Effect: 8 held-out and 8 train tasks set an availability date, and 1 held-out task raises a room's maximum occupants from 1 to 2, because the only pet-free Spanish answers in the test split are two-person households.
2. **New subcategory `leasing/early_date` (2 held-out, 3 train).** The renter's first date is 7 to 75 days before the room is free. Asked about the move-in date a second time, the renter gives a corrected date equal to `available_from` ("Oh I see, then October 31 works for me.", a template). The check expects the corrected date. *Why:* this turns the flaw into a tested skill: notice the conflict, ask, record the new date. Limitation: the correction comes on any second move-in question, even one that doesn't mention availability.
3. **Vague answers agree with the exact date that follows.** A vague phrase is used only with an exact date it could mean: a named month must match, "mid-" means days 8 to 22, "next month" means the next month, "in a few weeks" means 10 to 45 days, "11/3" must match one of its two readings, and "whenever it's ready" means within 14 days of availability. *Why:* "sometime in january" followed by "november 1" (and 2 more like it in train).
4. **Scripted renters can answer clarifying questions** (opt-in counterpart features, see below):
   - a reusable confirmation for each answered item: move-in ("Yes, December 1 is my move-in date."), phone ("Yes, that's my number, 828-555-0153."), lease ("Yes, a one year lease is fine with me."), and occupants ("It would be 2 people." / "Just me.");
   - a reusable generic line for any other question ("I think that's everything from me. What else do you need?"), which only answers a message that asks something;
   - a question about availability or a different date ("it's available from Jan 1, would that work?") now counts as a move-in question;
   - not-now renters get a line for "when will you look again?" ("Probably around January, I'll know more then.").

   All of these lines are templates written here with disjoint train and held-out pools. I checked every one with the rule-based reader: each parses to the value the checks expect.
5. **"Reason recorded" now means answered.** `register[t].gate.reason.status == "answered"`, replacing `exists`, which every register row passes (G1).
6. **Style checks score what the renter received.** The checks become `language` (scope `sent`), `first_person` (scope `sent`, new) and **at most 2 refused drafts per thread** (`tool_called send_message ok:false max 2`). They replace `max_two_sentences` / `one_question` / `no_long_dash` / `language` over attempted messages. *Why:* v1 failed a task over a draft the tool refused and the renter never saw (G2). The tool already enforces the three length and dash rules on every delivered message, so scoring them on sent messages would be free points. The refused-draft cap keeps the signal for sloppy drafting without failing a single rewrite. `first_person` is the rules file's "never refer to Kalin in the third person". This change is why the do-nothing floor rises from 0.218 to 0.291: the refused-draft cap passes when nothing is sent.
7. **Price push: no ban on the word "discount".** "No discount promised" now fails on promises ("I can lower", "I'll give you a discount", "I can do $", "te hago un descuento", and so on) and no longer on the word itself, so "I can't offer a discount" is fine. The renter also gets a line for a proposed showing.
8. **Not-now and hard-no say what should happen.** Not-now: the register status must be `not_now`, where v1 accepted any register write. Hard-no: the status must be `lost`, on top of "1 to 3 replies". *Why:* the rules separate "park and reconnect" from "close as not interested".
9. **Non-compliant listings use real violations, rotated.** The phrases are drawn from 6-phrase pools per split, all of which `check_listing_compliance` flags as violations (held-out: "christian household", "adults only", "must speak English", "no wheelchairs", ...). The instruction now quotes them (`Add "X" and "Y" to the post.`). *Why:* "males only" is not flagged by the tool, and the rules say a shared-room sex preference is the owner's call (D3). Also, every non-compliant task used the same pair.
10. **Publish faults stay broken on one named channel.** `{"tool": "publish_listing", "kind": ..., "times": 99, "match": {"channel": <first channel named>}}`, and the other channels must all be published (`min = n - 1`, where v1 needed only 1). The escalation keywords now include the channel name. *Why:* v1's fault fired once, so a plain retry succeeded and the run was then failed for not escalating.
11. **Malformed:** the renter no longer quotes the internal room id, and the "no corrupted values" check no longer bans "None" (which, case-insensitively, failed any message saying "none"). It still only corrupts the address (D4), so this task stays weak until `tools/` changes.
12. **Repair issues rotate** instead of being drawn at random, and each split's pool gains one issue (held-out: "the furnace makes a loud banging noise"; train: "the kitchen light flickers and buzzes"). Held-out ceiling drips: 4 of 5 → 2 of 5.
13. **One name per renter.** If a renter's lines sign with several names from the reader set's name pools, all are rewritten to the first one, and the thread is named after it (13 lines in 11 held-out tasks, 29 lines in 22 train tasks, each marked `"edit"` in the script). Display names no longer carry digit suffixes ("Marlowe222"); thread ids still do where needed to stay unique. Labels are unaffected, because names are not part of any expected value.
14. **Row filters:** no pets in occupant answers (v1 had a dog in a no-pets room), and "this fall" reasons only when the task date is June to October. A volunteered move-in must name its month or day (no bare "the 1st", which invites a confirmation the "does not re-ask" check forbids). Rows must be in the renter's language: v1's selector silently fell back to English rows.

## Counterpart changes (`gym/rentus_env/counterparts.py`)

All opt-in, so **v1 tasks replay exactly as before**. The v1 reference player still passes 31/31 and 51/51, and a test pins the v1 classifier.
- `"reuse": true` lines are never used up and are tried only after the one-shot lines for the same item.
- `when_asked` may be a list of items.
- `"classifier": "v2"` on a counterpart reclassifies an "other" question about availability or dates as `move_in`.

## Scorer changes (`gym/rentus_env/verify.py`)

These apply to every task, v1 included, because each check was clearly wrong:
- **S1. Sentence splitting and long dashes match the send tool** (`tools/rentus_tools/impl/style.py`): periods in "St.", "Ct.", "$875.00", "a.m." and URLs no longer start a sentence, and "--" and the other dash characters the tool refuses now count. *Effect on history:* re-scoring every stored transcript changes 3 of 2,571 style checks, all from fail to pass (two in `train-guard+rhist`, one in the held-out `baseline` run). No final-config number changes. `docs/results.md` was not re-scored.
- **S2. `first_person` no longer flags self-identification** ("I'm the owner", "soy el dueño"), and it now also catches "al/del/la dueño/dueña". No v1 task used this rule.

## Other files

- `gym/oracle.py`: `--tasks-version`; it ignores reusable lines when counting how often to ask.
- `gym/run_eval.py`: `--tasks-version` (default `v1`), recorded in `summary.json`.
- `gym/tests/test_gym.py`: 9 new tests: v2 reproducible, held-out lines only from the reader test split, reference player 100% on v2, do-nothing below 0.5, no move-in before availability and no household above the room's maximum, one name per renter, counterpart fallbacks, v1 classifier unchanged, scorer matches the send tool. All 14 tests pass.
- `contracts/tools.md` §9 documents the new script fields; `gym/README.md` mentions v2.

## What the owner needs to decide

1. **Approve v2 as the set for reruns**, or name any task to drop or change (fill in the "Owner verdict" lines in `docs/task-review.md`).
2. **Style scoring (change 6).** Approve replacing the three attempted-message rules with "language + first person on sent messages, at most 2 refused drafts". The alternative is to keep them with `scope: "sent"`; they would then always pass.
3. **Availability set inside tasks (change 1)**, rather than keeping inventory dates and reusing utterances.
4. **The new `early_date` subcategory (change 2)**, which changes the held-out set from 31 to 33 tasks.
5. **D1 to D5 in `docs/task-review.md`**: the "6-month lease" refusal and the gate rule (W3), the "males only" policy, the malformed fault, and whether confirmations count as re-asks.
6. **Reruns.** v2 numbers are not comparable to v1. A minimal comparable set is the Lightning baseline and final config on v2 held-out, ideally 2 seeds each (GPU time only). Optionally add Opus on the final config: the v1 operator run cost $3.41 for 31 tasks, so expect about $3.60 for 33. Nothing has been run.

## Applied owner decisions (D23)

Applied 2026-10-17 (`docs/DECISIONS.md` D23). No model was run. The reference player still passes v2 33/33 held-out and 54/54 train (v1: 31/31 and 51/51, v1 task files unchanged). Tests: tools 137 passed, gym 29 passed.

- **(a) 6-month floor.** `send_message` refuses any 6 to 11 month term (`lease_floor_not_requested`) until a renter message on that thread asks for a shorter lease (the reader's `shorter_lease` intent, an equivalent phrase such as "not a full year" or "¿puede ser por menos tiempo?", or a register row recording that they refused a year). It now also catches the floor named without the word "lease" ("6 months is the shortest", "six-month lease"). Below 6 months is always refused. The gate's lease item takes an optional `months`: if `months` is given, `months >= policy.lease_floor_months` decides (so value false with months 6 passes, and value true with months 3 fails); otherwise value true is needed, as before. `propose_showing`, `upsert_renter` and `gate_complete` all use this rule. Prompt `system_v3.md` says the floor may be named only on request and that accepting 6 months answers the lease item (v1 and v2 prompts unchanged).
- **(b) Gender wording.** "males only", "females only", "solo mujeres" and the like come back from `check_listing_compliance` as severity `warning` with `owner_decides: true` and never block publishing. Plural forms ("males only") are now matched; before they were missed. Every other protected-class phrase still blocks. The basis and the shared-housing caveat are in `tools/rentus_tools/impl/compliance_rules.md` (not legal advice).
- **(c) Confirmations.** The "does not re-ask" check allows one ask of an already-given item (a confirmation); a second ask fails. Optional `allow` changes the number. This applies to every task. Re-scoring stored transcripts flips 4 of 208 such checks from fail to pass, all in train runs; no held-out number changes. The generator's filter against volunteered bare dates ("the 1st") is kept, so v2 task content did not change for this.
- **(d) Malformed rent.** Malformed faults take `field` and `field_mode` (`wrong_type`, the default, turns 875 into "N/A"; `drop` removes the key), applied wherever the key appears (get_room, every room of list_rooms). The v2 malformed tasks now corrupt `rent` (held-out: wrong type; train: one of each), and "N/A" is added to the "no corrupted values" phrases. An operator that quotes the first `get_room` result without checking it now fails.
- **v2 regenerated.** 1 of the 2 held-out and 2 of the 3 train shorter-lease renters now accept 6 months (a template line, plus a reusable "Yes, 6 months is fine with me." confirmation) instead of flipping to a year; their lease check is "lease answered (6 months accepted)". The swap happens after naming and takes no random draw, so only those tasks and the malformed tasks changed (2 held-out, 4 train). Held-out is still 33 tasks, and train/held-out separation is unchanged (reader utterances used: 92 held-out, 156 train). The v2 renter classifier now treats a question that names a lease length in months ("would 6 months work for you?") as a lease question; it used to read it as a move-in question.
- Contract notes: `contracts/tools.md` §3 (`gate.lease.months`) and §5 (`field`, `field_mode`), logged in `BRIEF.md`.
