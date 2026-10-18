# Leakage and provenance review of the evaluation protocol

Reviewer: adversarial data-leakage / provenance pass (Claude Opus 5.5), 2026-10-18.
Target: `docs/eval-protocol.md` at `fa319c1`, checked against the code and data at HEAD (`0386d71`).
Scope: reader train/test separation, Gym task splits (v1, v2), the twins pipeline (v3, not built yet), held-out-informed changes, the Opus reference runs, `docs/data-provenance.md`, licenses, and whether each number in `docs/results.md` can be reproduced.
Nothing in the protocol or code was edited. No private text was copied into the repo. The checks against `~/rentus-private-data` were run locally, and only counts are reported here.

Severity: **blocker** = the claim it supports cannot be made until fixed; **major** = a claim is overstated or leaks in a way a reviewer would catch, and must be fixed or disclosed before the freeze; **minor** = worth fixing, small effect.

---

## What was checked and came out clean

These are real results, listed so the findings below are read in proportion.

- **Frozen hashes match.** `sha256sum` of every file in §6.1 that exists (v2 train/held-out, reader test/dev, `verify.py`, `system_v3.md`) equals the protocol's value.
- **Gym v1/v2 train vs held-out renter lines are disjoint.** Of the 102 reader-sourced held-out lines in v2, none matches a train line, even after mapping every digit to 0. The only exact repeats are fixed filler lines ("Just me." ×8, "ok thanks" ×1). Word 8-gram overlap: 3 of 248 held-out lines. v1 gives the same picture (0 of 93 reader-sourced lines).
- **No held-out text in prompts.** Word 8-gram overlap between `reader/prompt.py`, every `operator/prompts/*.md`, `tools/rentus_tools/impl/{inbox,reader}.py` and (a) the reader test set and (b) the v2 held-out lines: 0, with one exception. That exception is a fallback-reader regex phrase ("don't want to sign for 12 months"), which comes from a train template (it occurs 68 times in train), so it is not a leak.
- **No real renter text in the repo.** Every word 8-gram from the real conversations that start on or after 2026-05-01 was compared with `operator/prompts/*.md`, `docs/spec/*.md`, all `gym/tasks/**/*.jsonl`, `tools/rentus_tools/**/*.py` and `operator/rentus_operator/*.py` (46 files). There were 0 hits among the 32,590 8-grams, of which 31,813 are rare (they occur in fewer than 3 conversations). §2.5.5 can cite this as the baseline run of its own check.
- **SGD's own split is respected.** Four SGD dialogue ids occur in both reader train and reader test (`30_00099`, `30_00105`, `30_00106`, `30_00107`), but SGD numbers its dialogues separately in each split file, so these are different dialogues with different text. There is no leak. An id that includes the split name would stop this looking like one.
- **The reader test set was never used for tuning.** `reader/prompt.py` was last changed at `a13a5cf` (11:47 on 10-17), before any test score was committed (`847f93b`, 12:22). The fallback reader was tuned on train/dev (`424776a`). Training early-stops on 400 dev rows. Each system's test metrics were committed once.
- **The NeMo data files are not training data.** `gym/prepare_nemo_data.py` writes held-out rows for serving and verification only. Nothing in the repo trains on Gym tasks.

---

## Findings

### 1. [BLOCKER] The "no shared people" rule cannot be implemented on what `ingest.py` keeps

**Evidence.** Protocol §2.2 requires dropping any held-out thread whose counterpart person id appears in a pre-2026-05-01 thread, enforced by "an assertion in `to_tasks.py` that no held-out person id appears in train". But `data/twins/ingest.py:17` and `:218` keep only `thread_id = "th_" + hid(salt, raw["key"])`. Sender names are dropped on purpose (README "Sender names are dropped"), and the key is per chat (iMazing chat session, Facebook conversation, generic `thread_id`). So no person id ever reaches `label.py`, `twin.py` or `to_tasks.py`. The same person on SMS and on Messenger gets two unrelated thread ids. The anonymized export does carry stable pseudonyms (`raw/anonymized-2026-10-18/people.csv`: "the same person keeps the same pseudonym in every dataset"), but the pipeline does not read that format: all three `input/` folders are empty, and `ingest.py` reads only iMazing, Facebook and generic.

The protocol's implementation gate already says the split does not exist yet. This finding is that the planned fix (an assertion in `to_tasks.py`) has nothing to assert on.

**Fix.** In `ingest.py`, compute `person_key = hid(salt, pseudonym)` from the owner's pseudonym (or the iMazing handle or Facebook participant id) before the name is dropped. Merge keys across channels with an owner-supplied map, or with `people.csv` if the generic export is built from the anonymized set. Carry `person_key` and `start` through to `to_tasks.py`. Then implement the split there: `--split-date 2026-05-01` plus an assertion that the set of held-out person keys does not intersect the set of train keys. Log aggregate counts (threads dropped from each side for sharing a person). Add a fixture test where one invented person appears on two channels on both sides of the date. Until this lands, nothing built from v3 can be called held-out.

### 2. [MAJOR] v2 held-out is largely v1 held-out, which was run about 15 times and whose transcripts were read

**Evidence.** I compared the two task files directly:
- 31 of the 33 v2 held-out task ids also exist in v1 held-out;
- 81 of the 92 reader-test utterances used in v2 held-out are also used in v1 held-out;
- 80 of the 159 unique v2 held-out renter lines occur verbatim in v1 held-out.

v1 held-out was run about 15 times (protocol §0) while the guard, prompt v2/v3 and the style pre-check were being chosen. `docs/task-review.md:27` reads per-task held-out transcripts from the Opus run ("6 held-out tasks have an availability message the renter never answered"), and the v2 changes were designed from that review (`docs/task-v2-changes.md:28`, "That was the main cause of Opus's leasing failures"). Protocol §0 describes v2 held-out as "run once per config" and contaminated only "for any change that targets those patterns". That understates it: the v2 held-out content was seen and repaired using held-out transcripts. `docs/results.md:5` still says "**These are the numbers to quote**" for v2 held-out.

**Fix.** In §0, state that v2 held-out shares 31/33 tasks and 81/92 renter utterances with v1 held-out, and that v2 was designed from v1 held-out transcripts (Opus run). Change the `results.md` header from "numbers to quote" to "secondary, contaminated, see protocol §0". Keep v2 only as a regression check, never as the source of an effect size. In particular, §1 sets δ and the MDE table from v2 variance. That is fine, but say so.

### 3. [MAJOR] A held-out-informed change went into the frozen `final` harness, and `results.md` says no such change was made

**Evidence.** `b190ed2` (2026-10-18 03:10:48, 25 seconds after the v2 results commit `3900214`) rewrites the `POLICY_BLOCKED` hint in `tools/rentus_tools/impl/inbox.py` so it no longer models "pending the owner's confirmation". Its commit message says: "Found in v2 held-out runs: 30 of 99 final-config rollouts failed the third-person check … Disclosed in docs/results.md." But `docs/results.md:54` says "We did not change prompts after seeing held-out results; these are the next things to fix on train", and nowhere mentions the hint change. The change sits in `tools/`, which §4.1 freezes for the final runs, so it ships in every v3 config. It breaks §2.5.1 ("Tuning happens only on train"). It was not first reproduced on train. It also makes the committed v2 runs (at `437b611`) impossible to reproduce at HEAD: `git diff 437b611 HEAD -- tools` shows exactly this change.

For v3 the effect is probably small and helps both arms, because the hint fires for baseline too. But it is exactly the kind of undisclosed change a pre-registration exists to rule out.

**Fix.** Add a §0 bullet: "`b190ed2` changed a tool hint in response to a v2 held-out failure pattern; it is in all v3 configs." Correct `results.md:54` to say the hint was changed afterwards, and that v2 numbers were produced at `437b611`, before it. Either re-run the v2 train set with and without the hint to show the change has a train-side justification, or accept it as a disclosed held-out-informed change.

### 4. [MAJOR] The reader test set is not "test-only templates": 40% of draws come from the shared pool

**Evidence.** In `data/build_reader_set.py:90-99` (`pick`), the test split takes a held-out template only with probability 0.6 (`cand = held if held and rng.random() < 0.6 else idx`), and otherwise draws from all templates, train ones included. Openers, closers, first messages, operator asks and joiners use `rng.choice` with no split at all (`synth_example`, lines 509-596). Measured on `data/processed/reader/*.jsonl`:
- 188 of the 1,144 synthetic test rows (16%) are built entirely from templates that also occur in train;
- 416 of the 910 synthetic test rows long enough to have one (46%) share at least one word 8-gram with train/dev;
- 47 synthetic and 6 SGD test rows equal a train/dev row after stripping punctuation and mapping digits to 0. The existing guard (`build_reader_set.py:709-713`) only drops exact lowercase matches;
- the same leak reaches the Gym: 23 of the 92 reader rows behind v2 held-out (25%) use only train-visible templates, and the fine-tuned reader in `final` was trained on those templates.

Despite this, `docs/data-provenance.md` ("Test is held out: it uses test-only templates…"), the `build_reader_set.py:14-16` docstring ("test measures generalization to unseen phrasings, not memorized strings") and protocol §2.3 all claim template disjointness. The headline 0.791 / 0.813 (reader vs Opus 0.738) is partly an in-template score.

**Fix.** Do not regenerate the set: it is frozen, and that would void the scores. Instead, report exact match on the 956 test rows that use at least one held-out template and on the 188 that use none (the per-row `meta.templates` already has what is needed), next to the pooled number. Change the provenance and protocol wording to "test-biased templates (60% held-out draws) and test-only name/employer/area-code pools". Add the normalized-duplicate count. H2 already makes the twin set primary; say explicitly that the synthetic result is partly in-distribution.

### 5. [MAJOR] The H2 twin reader test is chosen by Lightning's own reading, and one labeler option would choose it by the fine-tuned reader

**Evidence.** The gold labels are Lightning's labels of the real message (`label.py`, default `--labeler lightning`, reasoning on). The twin text is written by Lightning, and a twin is kept only if Lightning with reasoning on re-labels every renter message to exactly that gold (`twin.py:388`, `ver = LocalLLM("operator", …, reasoning=True)`, up to 3 rewrites, failures dropped). So every row in `reader_test.jsonl` is, by construction, a row that Lightning with reasoning on reads perfectly. H2 then measures agreement with Lightning-with-reasoning on text Lightning wrote, not accuracy on real renter language. Threat 1 names the circularity of the labels. It does not name this filter, which removes exactly the rows a model would find hard. In addition, `label.py --labeler reader` exists and would label the real data with the fine-tuned reader that H2 evaluates. Nothing in the protocol forbids it, and the README records that the reader was tried as a labeler.

**Fix.**
- In §2.3/§8, state that twin rows are filtered to those Lightning-with-reasoning gets exactly right.
- Report Lightning with reasoning on as the test set's ceiling (expected 1.0 on the verify pass, lower on a fresh seed).
- Extend checkpoint 7.2 to have the owner check the twin row's gold against the twin text, not only the real message's labels, on held-out rows.
- Report the twin drop rate per field.
- Pre-register that `--labeler lightning` is the only labeler allowed for v3, and that `stats_card.json` / `tasks_stats.json` must show `"labeler": "lightning"`. Otherwise the run is void.

### 6. [MAJOR] The rules that score v3 come from the held-out window itself, and lane-2 prompts will be built from them

**Evidence.** `docs/spec/concierge.md` (committed `224f6ca`, 03:37, after the protocol) says it is distilled from the owner's sessions with his agent "Muse" over **Oct 4 to 18, 2026**. All of that is inside the v3 held-out window (§2.2: threads starting on or after 2026-05-01). Protocol §3.3 makes this spec the source of the v3 checks, and §1 anticipates "prompt v4 from lane 2". Local counts only: of the 1,159 conversations in the anonymized tenant export, 123 start in the held-out window, and 3 on or after Oct 4. The Muse session discusses live leasing conversations from that period. `concierge.md` shares 43 word 8-grams with the Muse transcript, and `system_v3.md` shares 11. All of them are the owner's own scripted wording ("How long do you want to stay? Is a one year lease okay with you?", "should I close this out or are you still looking"), not renter text. So this is not a privacy leak. It is a tuning leak: a candidate prompt written from the spec is informed by how the held-out-window conversations went, and the checks reward the same rules. Threat 4 frames the exploration leak as "which situations", but here the rules and possibly the candidate prompt are both derived from held-out-period threads.

**Fix.**
- Add an amendment that names this.
- Either (a) exclude from v3 held-out every thread the owner discussed in the Muse sessions (an owner-supplied list, hash committed), or (b) report H1b (candidate built from the spec) as "informed by the held-out window", outside the Holm family.
- Keep H1 (final vs baseline). Neither arm is built from the spec, so it is unaffected as long as no rule-derived change lands in `final` before the freeze. Pin that with the §4.1 `git diff` check on `operator/prompts/`.
- Also correct `concierge.md:3` ("contains no … message text"): a few owner template phrases are verbatim. That is fine because they are the owner's own words, but say so.

### 7. [MAJOR] The rerun rule in the committed v2 runs is wider than `results.md` says, and the replaced attempts are gone

**Evidence.** `gym/ablate.py:83` reruns every row with `status in ("model_error", "missing") or r.get("error")`, which includes rollouts that crashed after real model completions. Protocol §4.4 admits this. Yet `docs/results.md:58` states "rollouts that reached the model were never rerun". Reruns were also lopsided between configs: final 52 of 99, baseline 12 of 99. The replaced rows were overwritten (`per_task.attempts.jsonl` does not exist), so whether any rerun discarded a scored rollout cannot be audited.

**Fix.** Correct `results.md:58`. For each v2 run, list how many of the `tasks_rerun` entries had at least one model completion in the transcript or log, if logs survive. If they don't, say the claim is unverifiable. The §4.4 narrowing plus `per_task.attempts.jsonl` must land before the freeze, and should be listed as a gate in §4.5.

### 8. [MAJOR] Several numbers in `results.md` cannot be tied to exact inputs

**Evidence.**
- **Run summaries.** `gym/results/*/summary.json` records `git` as a short hash with no dirty flag (`gym/run_eval.py:379-382`). `tasks_file` is `None` in all v2 runs. There is no task-file hash and no vLLM model revision. The working tree is dirty right now (`M serving/start_vllm.sh`), and §4.1's `git diff --quiet` check does not cover `serving/`.
- **v1-era runs.** All 15 `heldout-*` runs have `operator_seed: null`.
- **Reader metrics.** `reader/results/*.metrics.json` record neither the commit, the checkpoint hash nor the data hash. Nothing ties `finetuned.test` (0.791) to the released `model.safetensors` (`877c8843…`).
- **Reader training data.** The model was trained on 14,000 rows (`finetuned.train_info.json`), but only the first 5,000 are published (`PUBLISHED_TRAIN_CAP`). The full file's hash (`3d9237ef6e79f8a18bdd22fde1417b019b86eb318ae152239dfb22694a3d19b3`, measured now) is recorded nowhere, and the model card (`reader/MODEL_CARD.md:77`) says the set is "Published … in the project repo". Rebuilding it needs `data/download.py:35`, which fetches SGD from `refs/heads/master.zip` (unpinned).
- **Not hashed in §6.1.** The reader train file, `tools/rentus_tools/impl/inbox.py` (changed after v2, finding 3) and `operator/rentus_operator/*`.

**Fix.**
- Record `git describe --dirty`, sha256 of the task file and the tools tree, and the vLLM `served_model` revision in every `summary.json`.
- Add `commit`, `checkpoint_sha256` and `data_sha256` to `reader/eval.py` metrics.
- Pin SGD to a commit SHA in `download.py`.
- Either publish the full 14k train file (it is small and CC BY-SA) or put its sha256 in §6.1 and the model card, and change "Published" to "first 5,000 published; full set regenerated by `build_reader_set.py --seed 7` at SGD commit X".
- Add `serving/` and `data/twins/` to the §4.1 frozen paths.

### 9. [MAJOR] The repository has no license file

**Evidence.** There is no `LICENSE*` at the repo root. The README licenses the reader data and weights (CC BY-SA 4.0) and the twins (CC BY 4.0), but the code, the Gym tasks and the published inventory carry no license, so they are not legally open. That matters for an "openly published" hackathon submission and for the synthetic-data rule. The v2/v1 Gym tasks draw utterances from `data/published/reader/*.jsonl`, which is declared CC BY-SA as a whole. All 258 v2 utterances are synthetic rows (0 SGD-sourced, checked), so share-alike is not technically forced on the tasks, but the provenance doc doesn't say that.

**Fix.** Add a root `LICENSE` (e.g. Apache-2.0 for code) and a data-license table: reader set CC BY-SA 4.0; Gym tasks CC BY 4.0 (with the statement "built only from the synthetic, team-authored rows of the reader set; no SGD-derived row is used"); twins CC BY 4.0 with Nemotron-Personas attribution, plus a note that twin text and labels are outputs of Nemotron 3.5 Lightning under NVIDIA's open model license; inventory CC BY 4.0 with UCI, Inside Airbnb and ZORI attribution.

### 10. [MINOR] Twin personas and dates can overlap across splits, and the published twins hide the split

**Evidence.** `twin.py:127-131` draws `persona = rng.choice(pool)` from one 4,000-persona pool for every thread, seeded by a private salt. With about 200 twins, roughly 5 persona collisions are expected, some of them across train and held-out. All twins are moved into the same Oct 2026 to Feb 2027 window (`TWIN_WINDOW`, line 47), so the published files cannot show that the time split was respected.

**Fix.** Split the persona pool by `uuid` hash parity (train vs held-out). Publish each twin's split and the quarter its source thread started in (coarse enough to be private), so a third party can check §2.2 against `tasks_stats.json`.

### 11. [MINOR] Checkpoint 7.2 mixes the splits, and its labels feed H6

**Evidence.** §7.2 draws 50 labels "from both splits", and §2.4 uses "owner-checked labels (§7.2)" for H6 reader exact match, which is a held-out-only metric. The owner also sees held-out labels before the freeze. That is harmless while the owner tunes nothing, but it is not recorded.

**Fix.** Draw the H6 subset only from held-out threads, report its n separately, and note in §0 that the owner saw those labels.

### 12. [MINOR] The protocol's description of what has been seen is incomplete

**Evidence.** §0 omits the following:
- the Opus held-out run on v1 (`heldout-frontier-opus55-…`, `f91e5e9`) and the reading of its transcripts (finding 2);
- the stratified 400-row reader sample, scored by Opus and rescored for every system (`reader/eval.py --sample 400 --seed 0`). It is in `results.md` but not in §0;
- the router fixes. Their train-only design (`5542c78`) is fine, but the claim that its v2 held-out drop is "status today" means the router has been seen on held-out once already.

**Fix.** Add these three to §0.

---

## Verdict

**Not ready to freeze.** Finding 1 is a blocker: the person-disjoint, time-split v3 held-out set that carries H1, H2, H3 and H4 cannot be built from what `ingest.py` keeps. Fix it with a fixture test before anything from v3 is called held-out.

Findings 2 to 9 do not invalidate the plan, but each one overstates a claim that is already written down:
- v2 held-out is close to a re-skin of v1 held-out;
- a change informed by held-out results shipped without the disclosure the commit message promises;
- the "test-only templates" wording is wrong for 40% of draws;
- the twin reader test is chosen by Lightning's own reading;
- the v3 scoring rules come from inside the held-out window;
- the v2 rerun claim is unverifiable;
- several numbers lack dirty-tree, data or checkpoint hashes;
- the code has no license.

All of these are fixable with amendments, extra report columns and small code changes before the freeze. None needs a re-run, except that finding 1 must be fixed before v3 is built.

The core separations hold up under direct measurement: Gym train vs held-out lines, prompts vs held-out text, and repo vs real renter text all show no overlap.
