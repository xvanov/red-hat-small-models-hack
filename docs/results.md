# Results: Gym-driven improvement of the operator

## v2 results (approved task set)

**Secondary and exploratory, not confirmatory** (see the disclosures right below and `docs/eval-protocol.md` Amendment 1). The confirmatory set is v3 held-out, run once with configs and δ fixed in advance. Task set v2 (`gym/tasks/v2/heldout.jsonl`, 33 held-out tasks, approved by the owner as decision D23) fixes flaws found in an audit of v1 (`docs/task-review.md`, `docs/task-v2-changes.md`). Everything under "v1 results" further down used the flawed v1 tasks and is superseded. v1 and v2 numbers are not comparable with each other.

Run 2026-10-18 02:20 to 03:10 ET at commit `437b611`. Model: Nemotron 3.5 Lightning 30B-A3B (NVFP4) on vLLM on our one rented GPU, temperature 0.2, no paid APIs. Each config ran 3 times with operator seeds 1, 2, 3 (NeMo path: 2 runs, seeds 1, 2). Tasks, tools and scorer (`gym/rentus_env/verify.py`) were not changed. Statistics from `gym/stats.py` (method in `docs/eval-method.md`).

### Disclosures (added 2026-10-18 with protocol Amendment 1)

1. **v2 held-out overlaps v1 held-out.** 31 of the 33 v2 held-out tasks also exist in v1 held-out, 81 of the 92 reader-test utterances behind v2 held-out are also used in v1 held-out, and 80 of the 159 unique v2 renter lines occur verbatim in v1 held-out. v1 held-out was run about 15 times while the guard, prompt v2/v3 and the style pre-check were chosen, and v2 was designed after reading v1 held-out transcripts (Opus run, `docs/task-review.md`). So v2 held-out is a secondary, exploratory set and a regression check, never the source of a confirmatory effect size.
2. **A held-out-informed change was made after these runs.** The first-person rewrite hint in `send_message`'s confirmation guard (`b190ed2`, 25 seconds after this results commit) and the `send_message` guard that refuses third-person references to the owner (`08cbaa9`) were both made after seeing the v2 held-out failures below (30 of 99 final rollouts failed `style:first_person` on "pending the owner's confirmation"). They were not first reproduced on train. They are in every v3 config, baseline included. The v2 numbers here were produced at `437b611`, before either change, and cannot be reproduced at HEAD. The sentence "We did not change prompts after seeing held-out results" below is true of prompts only, not of tool hints and guards.
3. **Reader test template overlap.** The synthetic reader test is not template-disjoint from train: the builder draws a test-only template with probability 0.6 and otherwise from all templates, and openers/closers are shared. 188 of the 1,144 synthetic test rows use only templates that also occur in train, 956 use at least one test-only template. Exact match by group (full test, 1,419 rows): fine-tuned reader 0.746 on the 956 rows with a test-only template vs 0.957 on the 188 train-template rows (SGD rows 0.836); rule-based fallback 0.475 vs 0.979; Lightning 0.069 vs 0.069. With `reason` scored on status only (the Amendment 1 primary metric): fine-tuned 0.908 overall, 0.920 / 0.957 by group; on the 400-row sample, fine-tuned 0.905 vs Opus 0.803 (0.813 vs 0.738 with the free-text reason value). The pooled synthetic number is partly in-distribution; the twin reader test is the primary H2 set.
4. **The v3 scoring rules are dated inside the v3 held-out window.** `docs/spec/concierge.md` is distilled from the owner's sessions with his agent over Oct 4 to 18, 2026, which falls inside the v3 held-out window (threads starting on or after 2026-05-01). Part of the owner side of those late threads was written by that agent. The rules were not derived from these v2 tasks, but any v3 claim scored by them carries this caveat (protocol Amendment 1, items L6 and S9).
5. **Reruns.** The rerun rule used for these runs was wider than stated below: `gym/ablate.py` reran every row with `status in (model_error, missing)` or any error, including rollouts that crashed after real model calls (final 52 of 99, baseline 12 of 99). The replaced rows were overwritten, so whether any rerun discarded a scored rollout cannot be audited. The rule is now narrowed to rollouts with zero model completions, and replaced attempts are kept (`per_task.attempts.jsonl`).
6. **Pass-rate test label.** With 3 runs per config the pass column is an exact sign test on per-task pass fractions, not McNemar (it is McNemar only with 1 run).

### Headline (held-out v2, 33 tasks)

| config | runner | runs | pass rate (95% CI) | mean reward (95% CI) | pass^3 (passes in all 3 runs) |
|---|---|---|---|---|---|
| Baseline (v1 settings: `RunConfig()`, prompt v1, rule-based reader) | our loop | 3 | 12.1% (5 to 27%) | 0.570 (0.493 to 0.648) | 6.1% |
| **Final** (guard + prompt v3 + style pre-check + reasoning history + fine-tuned 0.6B reader) | our loop | 3 | **45.5% (30 to 62%)** | **0.929 (0.911 to 0.945)** | 18.2% |
| Final + router | our loop | 3 | 46.5% (31 to 63%) | 0.876 (0.834 to 0.914) | 21.2% |
| Final, NeMo Gym `simple_agent` (prompt v3 + fine-tuned reader) | NeMo Gym | 2 | 54.5% (38 to 70%) | 0.887 (0.842 to 0.930) | n/a (pass^2 30.3%) |

Pass rate = share of tasks where every check passed, averaged over runs (Wilson interval). Mean reward = average share of checks passed (bootstrap interval over tasks). pass^3 = share of tasks that passed in all 3 runs, a reliability measure.

**Paired tests** (same 33 tasks; task is the resampling unit; Holm-corrected over the three comparisons):

| A vs B | Δ mean reward (95% paired bootstrap) | Holm p (reward) | Δ pass rate | tasks A better / B better | Holm p (pass, exact sign test) |
|---|---|---|---|---|---|
| Final vs baseline | **+0.359 (+0.281 to +0.436)** | <0.001 | **+33.3 pts** | 22 / 2 | <0.001 |
| Final + router vs final | **−0.053 (−0.093 to −0.016)** | 0.016 | +1.0 pts | 9 / 12 | 0.664 |
| Final NeMo vs final (our loop) | −0.042 (−0.092 to +0.005) | 0.093 | +9.1 pts | 18 / 9 | 0.244 |

### Per category

Pass rate (95% Wilson) and mean reward (95% bootstrap); n = tasks in the category.

| config | leasing (20) | listing (4) | ops (4) | recovery (5) |
|---|---|---|---|---|
| baseline | pass 5.0% (1 to 24%); reward 0.425 (0.360 to 0.492) | pass 8.3% (1 to 57%); reward 0.799 (0.750 to 0.847) | pass 50.0% (15 to 85%); reward 0.893 (0.786 to 1.000) | pass 13.3% (2 to 57%); reward 0.710 (0.596 to 0.824) |
| final | pass 26.7% (12 to 49%); reward 0.919 (0.902 to 0.937) | pass 83.3% (36 to 98%); reward 0.965 (0.931 to 1.000) | pass 83.3% (36 to 98%); reward 0.962 (0.925 to 1.000) | pass 60.0% (23 to 88%); reward 0.911 (0.837 to 0.967) |
| final + router | pass 40.0% (22 to 61%); reward 0.871 (0.818 to 0.918) | pass 50.0% (15 to 85%); reward 0.896 (0.854 to 0.931) | pass 83.3% (36 to 98%); reward 0.972 (0.944 to 1.000) | pass 40.0% (12 to 77%); reward 0.800 (0.675 to 0.928) |
| final, NeMo | pass 45.0% (26 to 66%); reward 0.887 (0.833 to 0.936) | pass 75.0% (30 to 95%); reward 0.948 (0.896 to 1.000) | pass 87.5% (40 to 99%); reward 0.917 (0.750 to 1.000) | pass 50.0% (17 to 83%); reward 0.817 (0.667 to 0.967) |

Per check type (share passed over all runs): baseline → final: style 20% → 77%, state 39% → 95%, tool_called 67% → 97%, escalated 61% → 94%, message 52% → 95%, never 84% → 89%, budget 100% → 100%. Final + router: style 97%, state 82%, tool_called 88%, escalated 78%, message 95%, never 80%, budget 99%.

### Cost per task (our loop, 99 rollouts per config)

| config | Lightning calls / task | input tokens / task | output tokens / task | task time p50 / mean | runs that hit the 30-step cap |
|---|---|---|---|---|---|
| baseline | 8.4 | 66k | 2.2k | 23 s / 31 s | 5 of 99 |
| final | 20.9 | 249k | 8.5k | 105 s / 99 s | 47 of 99 |
| final + router | **11.2** | **110k** | **5.3k** | **61 s / 71 s** | 1 of 99 |

Router decisions (377 routed events over 3 runs): LIGHTNING 300, RECORD_ONLY 59, BATCH 18, ESCALATE_DIRECT 0, NO_OP 0. The GPU was shared with other work during the runs, so times are indicative only.

### How to read this

- **The final config is a large, statistically clear gain over the baseline**: +0.36 mean reward and +33 pass-rate points, with 22 tasks better and 2 worse. This is the defensible headline.
- **Pass rate is low relative to reward (45% vs 0.93) mainly because of one new v2 check.** `style:first_person` (never refer to the owner in the third person) failed 30 times across the final's 99 rollouts, almost always on the same phrase after proposing a showing: "...pending the owner's confirmation" ("pendiente de confirmación del dueño"). One failed check fails the whole task. Not-now and hard-no tasks also miss the required register status (`not_now` / `lost`) in about half the runs. We did not change prompts after seeing held-out results; these are the next things to fix on train.
- **Reliability is the weak spot.** Only 18% of tasks pass in all 3 runs (pass^3), while 76% pass in at least one (pass@3). 19 of 33 tasks flip between runs. Quote pass^3 next to the pass rate.
- **The router halves the cost but loses some quality.** It cuts Lightning calls per task from 20.9 to 11.2, input tokens by 56% and task time p50 from 105 s to 61 s, and almost nothing hits the step cap any more (1 vs 47 of 99). Pass rate is unchanged (+1 pt, not significant), but mean reward is 0.053 lower (Holm p 0.016). Most lost checks are in leasing (84 of 127 failed checks over 3 runs), led by the recorded move-in date: missing, empty, or a wrong date left in the register (for example, in `early_date` the renter's first, too-early date instead of the correction). Escalation checks also drop (94% → 78%), and listing and recovery lose some reward. The router stays off in the final config until that is fixed on train.
- **NeMo Gym path**: `simple_agent` has no renter guard and no style pre-check (those live in our loop), and reasoning history is NeMo's default. With prompt v3 and the fine-tuned reader it is statistically level with our loop: higher pass rate (+9 pts, p 0.24), lower reward (−0.04, p 0.09). Its two runs differ a lot (0.938 vs 0.837 reward; in run 2 several rollouts ended after 0 to 3 tool calls with a plain-text answer, the failure the guard exists for).
- **Endpoint drops.** As in every committed run, a rollout that never reached the model (`APIConnectionError`, tunnel drop) was rerun once the endpoint answered again; rollouts that reached the model were meant never to be rerun, but the code reran any errored row (see disclosure 5). Reruns per config (of 99): baseline 12, final 52, final + router 35, NeMo 0. Each `summary.json` lists them (`model_error_retries`); none remained failed. The fine-tuned reader answered every `read_reply` call in the final runs (345 calls, 0 fallbacks).

### Runs and reproduce

Run dirs: `gym/results/v2-heldout-{baseline,final,final-router}-s{1,2,3}/` and `gym/results/v2-heldout-final-nemo-s{1,2}/`; per-config reports `gym/results/v2-heldout-*-report.md` (with per-task pass matrices).

```bash
F=guard+prompt3+style+rhist+readermodel
gym/.venv/bin/python gym/run_seeds.py --variant base     --split heldout --tasks-version v2 --seeds 1,2,3 --prefix v2-heldout-baseline     --workers 5
gym/.venv/bin/python gym/run_seeds.py --variant $F       --split heldout --tasks-version v2 --seeds 1,2,3 --prefix v2-heldout-final        --workers 5
gym/.venv/bin/python gym/run_seeds.py --variant $F+router --split heldout --tasks-version v2 --seeds 1,2,3 --prefix v2-heldout-final-router --workers 5
gym/.venv/bin/python gym/run_seeds.py --via nemo --variant prompt3+readermodel --split heldout --tasks-version v2 --seeds 1,2 --prefix v2-heldout-final-nemo --workers 5
gym/.venv/bin/python gym/stats.py --md --categories \
  --config baseline=v2-heldout-baseline-s1,v2-heldout-baseline-s2,v2-heldout-baseline-s3 \
  --config final=v2-heldout-final-s1,v2-heldout-final-s2,v2-heldout-final-s3 \
  --config final+router=v2-heldout-final-router-s1,v2-heldout-final-router-s2,v2-heldout-final-router-s3 \
  --config final-nemo=v2-heldout-final-nemo-s1,v2-heldout-final-nemo-s2 \
  --compare final:baseline --compare final+router:final --compare final-nemo:final
```

---

# v1 results (superseded by v2)

**Superseded.** Everything below used task set v1, which an audit found flawed (move-in dates before the room was free, style scored on drafts the renter never saw, a "discount" word ban, and more; see `docs/task-review.md`). Kept for the record and for the change-by-change ablation history. Quote the v2 section above instead.


Model: Nemotron 3.5 Lightning 30B-A3B (NVFP4) on vLLM, temperature 0.2, the same weights in every row. No training: every change is to the harness, the prompt or the verifier. Environment: `gym/` (NeMo Gym 0.6.0 resources server, 31 held-out tasks, 51 train tasks).

## Headline (held-out, 31 tasks)

| | pass | mean reward |
|---|---|---|
| Baseline, our loop (`RunConfig()`, 2 runs) | 1/31 (3.2%) | 0.453 |
| Baseline, NeMo Gym `simple_agent` | 4/31 (12.9%) | 0.646 |
| **Final, our loop** (guard + prompt v3 + style pre-check + reasoning history, 2 runs) | **20/31 (64.5%)** | **0.921** |
| **Final, NeMo Gym `simple_agent`** (prompt v3, the only change that applies to NeMo's harness) | **15/31 (48.4%)** | **0.809** |

## Method

- **Tasks and scorer fixed.** `gym/tasks/heldout.jsonl`, `gym/tasks/train.jsonl` and `gym/rentus_env/verify.py` were not edited (nor `tools/`). Each config is a named `RunConfig` variant in `gym/ablate.py` (`VARIANTS`), run by `run_eval.evaluate` on the same eval config as the baseline (temperature 0.2, max 30 steps, same tool backend, reader pinned to the rule-based fallback, which the committed baselines used).
- **Train/held-out discipline.** Every change was designed from train-split transcripts only (`gym/results/_p21/diagnose.py` refuses to run on held-out), and chosen by its train score. Held-out runs happened only after a change was kept, and no held-out transcript was read while designing changes.
- **One change at a time.** Each change was first measured on train on top of the changes already kept. On held-out, each change is reported alone against the baseline and cumulatively.
- **Endpoint outages.** The shared vLLM endpoint dropped or hung several times (12:17 to 12:33 ET, plus several shorter tunnel drops). A rollout that never reached the model (`APIConnectionError`) is rerun once the endpoint generates again, and the merged run records which tasks were rerun (`model_error_retries` in each `summary.json`). A failure inside a rollout that did reach the model is never rerun. Runs voided by the 12:17 hang (`train-baseline`, `train-baseline-nemo`) are not used.
- **Repeats.** The top two configs and the baseline were run twice (`-s2`). The other rows are single runs. Run-to-run spread at this temperature is about ±0.01 to 0.02 mean reward (0.452 vs 0.455 for the baseline, 0.911 vs 0.931 for the final), so differences under about 0.03 are noise.

## The changes

| id | variant | what it changes | why (train diagnosis) |
|---|---|---|---|
| (a) | `guard` | **Harness.** In a renter-facing run, if the model ends with plain text while the renter's last message is unanswered (read from world state), the loop does not finish: it adds a `[harness]` turn saying plain text is never delivered and to send the reply with `send_message` (max 3 bounces). `operator/rentus_operator/loop.py` | On train, 23 of 28 leasing tasks never called `send_message`; the model wrote its renter reply as the final answer. |
| (b) | `prompt3` | **System prompt v3** (`operator/prompts/system_v3.md`): the plain-text rule stated first; a step-by-step workflow for each scenario (leasing gate loop, price push, shorter lease, not now, hard no; listing; operations); asks always phrased as questions; match the owner's exact address; take the ZIP from the room record and use `vendor_id`s exactly as `find_vendors` returns them. v2 is the same without the last three. | Train failures: questions without a "?" ("I need your phone number"); wrong room picked (4110 vs 1078 Odessa Gate Ln); guessed ZIPs and vendor names passed as ids → `NOT_FOUND`; compliance check skipped. |
| (d) | `style` | **Verifier.** `send_message` drafts are checked against the same style rules the tool enforces (`rentus_tools.impl.style`) before the call; a failing draft goes back to the model as a rewrite request and is not sent. `operator/rentus_operator/verifier.py` | First drafts often had 3 sentences or 2 questions. |
| (g) | `rhist` | **Loop vs NeMo parity.** Keep the model's reasoning in the message history (`keep_reasoning_in_history`). | Why our loop scored below NeMo's `simple_agent` on the same model: NeMo's `vllm_model` defaults to `uses_interleaved_reasoning: true` and feeds reasoning back each turn; our loop dropped it. |
| (c) | `tools2` | Tool-description variant: `send_message` says it is the only channel to a renter, compliance check "required", etc. `operator/rentus_operator/toolbox.py` | Tried on train, no gain on top of (a)+(b)+(d) (0.918 → 0.916). Not kept. |

Caveat on (d): the `style` check type in the scorer counts every *attempted* `send_message`, including ones the tool refused. The pre-check stops a bad draft before it becomes an attempt, so part of its gain is the model no longer being penalised for a draft it would have had to rewrite anyway. Nothing the renter receives changes. It is reported as its own row so it can be discounted, and the final config without it is the `guard+prompt3` row plus `rhist` (not run separately).

## Held-out results (31 tasks)

Mean reward per category. Pass = every check in the task passed. "Rerun" = rollouts rerun after an endpoint outage (see Method).

| config | runner | runs | pass (mean) | mean reward (range) | leasing (18) | listing (4) | ops (4) | recovery (5) | rerun |
|---|---|---|---|---|---|---|---|---|---|
| baseline (`baseline`, `heldout-base`) | local | 2 | 1/31 (3.2%) | 0.453 (0.452 to 0.455) | 0.316 | 0.792 | 0.762 | 0.432 | 17 |
| (a) guard alone | local | 1 | 2/31 (6.5%) | 0.686 | 0.655 | 0.771 | 0.780 | 0.653 | 24 |
| (b) prompt v3 alone | local | 1 | 11/31 (35.5%) | 0.798 | 0.742 | 0.917 | 1.000 | 0.746 | 21 |
| (d) style pre-check alone | local | 1 | 2/31 (6.5%) | 0.468 | 0.317 | 0.750 | 0.673 | 0.621 | 21 |
| (g) reasoning history alone | local | 1 | 3/31 (9.7%) | 0.614 | 0.567 | 0.729 | 0.625 | 0.680 | 21 |
| (a)+(b) | local | 1 | 11/31 (35.5%) | 0.846 | 0.787 | 0.854 | 1.000 | 0.929 | 21 |
| (a)+(b)+(d) | local | 2 | 16.5/31 (53.2%) | 0.902 (0.897 to 0.907) | 0.886 | 0.854 | 0.964 | 0.947 | 29 |
| **(a)+(b)+(d)+(g) final** | local | 2 | **20/31 (64.5%)** | **0.921 (0.911 to 0.931)** | 0.896 | 1.000 | 1.000 | 0.885 | 30 |
| final + (f) fine-tuned reader (`+readermodel-rerun`) | local | 2 | 20.5/31 (66.1%) | 0.940 (0.936 to 0.943) | 0.944 | 0.812 | 1.000 | 0.978 | 0 |
| NeMo baseline (`baseline-nemo`) | nemo | 1 | 4/31 (12.9%) | 0.646 | 0.648 | 0.729 | 0.696 | 0.536 | 0 |
| NeMo + (b) prompt v3 | nemo | 1 | 15/31 (48.4%) | 0.809 | 0.755 | 0.917 | 1.000 | 0.762 | 0 |

Per check type, baseline → final (local): style 5% → 100%, state 33% → 87%, tool_called 54% → 86%, escalated 33% → 100%, message 57% → 86%, never 88% → 91%, budget 100% → 100%.

What each change did, held-out:
- **(a) guard** fixes the delivery bug (leasing reward 0.32 → 0.66) but alone barely moves the pass rate: once the model does send, v1's long first drafts break the style checks.
- **(b) prompt v3** is the largest single change (+0.35 reward, 1 → 11 passes) and the only one that transfers to NeMo's harness, where it takes `simple_agent` from 4 to 15 passes. Ops goes to 1.000 in both runners (correct ZIP and vendor ids).
- **(d) style pre-check** does nothing alone (without the guard the model rarely sends anything to check) and adds about +5.5 passes on top of (a)+(b).
- **(g) reasoning history** explains most of the loop-vs-NeMo gap: alone it takes our loop from 0.453 to 0.614 (NeMo baseline 0.646), and it adds about +3.5 passes on top of (a)+(b)+(d).
- **(f) fine-tuned reader** (`xvanov/rentus-reader-qwen3-0.6b` instead of the rule-based `read_reply` fallback, on top of the final config): +0.5 passes and +0.019 mean reward over 2 runs, which is under the ~0.03 noise threshold, so it is not a clear gain. It helps leasing (0.896 → 0.944) and recovery (0.885 → 0.978) but listing drops (1.000 → 0.812, 4 tasks). All 184 `read_reply` calls across both runs returned `backend: "model"` (0 fallbacks). Not part of the headline final config.

## Train results (51 tasks, used to choose the changes)

| config | pass | mean reward | leasing | listing | ops | recovery |
|---|---|---|---|---|---|---|
| base | 2/51 | 0.512 | 0.354 | 0.845 | 0.698 | 0.610 |
| guard | 3/51 | 0.704 | 0.710 | 0.667 | 0.702 | 0.715 |
| guard+prompt2 | 21/51 | 0.849 | 0.896 | 0.708 | 0.829 | 0.828 |
| guard+prompt3 | 18/51 | 0.865 | 0.907 | 0.684 | 1.000 | 0.794 |
| guard+tools2 | 8/51 | 0.746 | 0.747 | 0.816 | 0.663 | 0.743 |
| guard+style | 11/51 | 0.788 | 0.825 | 0.696 | 0.825 | 0.726 |
| guard+rhist | 7/51 | 0.726 | 0.728 | 0.839 | 0.611 | 0.708 |
| guard+prompt3+style | 30/51 | 0.918 | 0.921 | 0.881 | 1.000 | 0.885 |
| guard+prompt3+style+tools2 | 33/51 | 0.916 | 0.927 | 0.881 | 0.952 | 0.889 |
| guard+prompt3+style+rhist | 36/51 | 0.957 | 0.969 | 1.000 | 0.901 | 0.929 |

## Reproduce

```bash
gym/.venv/bin/python gym/ablate.py --run-name _ --split heldout --prefix heldout- --workers 4 \
    --variants base,guard,prompt3,style,rhist,guard+prompt3,guard+prompt3+style,guard+prompt3+style+rhist
gym/.venv/bin/python gym/ablate.py --run-name _ --split heldout --via nemo --prefix heldout-nemo- --variants prompt3
gym/.venv/bin/python gym/results/_p21/table.py heldout-base heldout-guard+prompt3+style+rhist   # the table
```

Results JSON: `gym/results/<run>/summary.json` and `per_task.jsonl` (plus local transcripts or NeMo `nemo/rollouts.jsonl`).

## Reference: frontier model (Claude Opus 5.5)

**What this is.** A comparison point, not part of the system. The frontier model is never loaded by the running app (organizers: the 33B limit covers the models loaded to run the app). It shows where our local system (Lightning 30B operator + 0.6B fine-tuned reader, on our own GPU, renter data never leaves it) lands against a frontier API model on the same tasks with the same scorer. Run 2026-10-17, model id `claude-opus-5-5` through OpenCode Zen (Anthropic Messages API, official `anthropic` SDK 1.11.0), effort `high` for the operator and `medium` (the model's default) for the reader. **Total spend: $7.62 of a $10 cap** (operator 3-task probe $0.35, operator run $3.41, reader 30-row probe $0.27, reader run $3.58).

**Same harness, one switch.** `RunConfig(api="anthropic")` (CLI `--api anthropic`) swaps only the model client (`operator/rentus_operator/anthropic_client.py`). Prompt v3, tools, verifier, renter guard, style pre-check, reasoning history, the 31 held-out tasks and `verify.py` are unchanged, and the reader is pinned to the rule-based fallback, as in the final row above. Differences that come from the model: Opus 5.5 rejects `temperature` (Lightning runs at 0.2) and always thinks; its thinking blocks are passed back unchanged on each turn; prompt caching is on. Cost is computed from token usage at list price ($4 in / $20 out / $0.20 cache read / $5 cache write per million tokens) because Zen returned no per-call `cost` field, so the dollar figures are estimates of what Zen bills.

### Operator, held-out (31 tasks)

| system | runs | pass | mean reward | leasing (18) | listing (4) | ops (4) | recovery (5) | model cost per task | task time p50 / mean |
|---|---|---|---|---|---|---|---|---|---|
| **Ours: Lightning 30B-A3B, final config** | 2 | **20/31 (64.5%)** | **0.921** | 0.896 | 1.000 | 1.000 | 0.885 | no per-call fee (our rented GPU) | 53 s / 67 s |
| Claude Opus 5.5, same final config | 1 | 18/31 (58.1%) | 0.889 | 0.831 | 1.000 | 1.000 | 0.923 | $0.110 | 31 s / 35 s |

Opus pass rate by category: leasing 6/18, listing 4/4, ops 4/4, recovery 4/5. Per check type: style 100%, budget/never/escalated/message 100%, state 73%, tool_called 79%. It made 10.3 model calls per task on average (Lightning about 16). Run: `gym/results/heldout-frontier-opus55-guard+prompt3+style+rhist/`. Per-call usage log: `gym/results/frontier-usage.jsonl`.

How to read this honestly:
- **On this benchmark, with this harness, our local system scores slightly above Opus 5.5** (+2 passes, +0.03 reward). The gap is about the size of our run-to-run noise (about ±0.02 reward), and Opus has one run, so the defensible claim is **parity, not a win.**
- **The harness was tuned for Lightning.** Prompt v3, the guard and the style pre-check were designed from Lightning's train-split failures. Opus got no tuning at all. Opus with its own tuning would likely score higher.
- **Most of Opus's leasing losses come from a gap in our tasks, not from a weaker model.** In 9 of its 12 failed leasing tasks, Opus noticed that the renter's move-in date (the label from the reader dataset) falls before the room's availability date and pushed back ("the room is only available from January 1, 2027, so December 1 is too early"). The scripted renter has no line for that, so the gate never completes and `propose_showing` never happens (11 of the 18 failed leasing checks are "showing proposed"). The task generator does not reconcile move-in labels with room availability. That is a flaw in our tasks, and the frontier model's behavior is arguably the better business call. We did not change the tasks or the scorer after seeing this, so the numbers stand as measured. The generator fix is task set v2 (`docs/task-review.md`, `docs/task-v2-changes.md`), built but not yet run with any model.
- **Latency is not like-for-like.** Lightning's times come from a shared vLLM endpoint with outages (see Method) and 4 workers. Opus's come from a hosted API with 4 workers. Per task, Opus is faster here (fewer, longer steps).
- **What the local system gives up and gets.** Opus costs about $0.11 per operator task, sends every renter message to a third-party API, and needs a network connection. Ours has no per-call fee and keeps renter data on our machine.

### Reader, held-out test, stratified 400-row sample

Opus ran on a seeded 400-row sample of the 1,419-row test split, stratified by source × language × gold move-in status (`reader/eval.py --sample 400 --seed 0`), to fit the budget. Every other row below is the **same 400 rows** rescored from its full-split predictions. On these rows the other systems score close to their full-set numbers (fine-tuned exact match 0.813 here vs 0.791 on all rows), so the sample is a fair stand-in.

| System (same 400 rows) | Exact match | JSON valid | Lease | Move-in | Phone | Occupants | Reason | Intent F1 (micro) | Language | Vague-date trap |
|---|---|---|---|---|---|---|---|---|---|---|
| Deterministic regex fallback | 0.555 | 1.000 | 0.873 | 0.995 | 1.000 | 0.973 | 0.890 | 0.764 | 1.000 | 0.000 |
| Qwen3-0.6B base | 0.000 | 0.913 | 0.120 | 0.028 | 0.003 | 0.043 | 0.000 | 0.137 | 0.700 | 0.125 |
| **Ours: Qwen3-0.6B + SFT** | **0.813** | 1.000 | 0.998 | 0.978 | 0.998 | 1.000 | 0.885 | 0.939 | 1.000 | 0.042 |
| Lightning 30B-A3B, prompted | 0.123 | 0.975 | 0.585 | 0.585 | 0.808 | 0.735 | 0.550 | 0.492 | 0.953 | 0.292 |
| Claude Opus 5.5, prompted (reference) | 0.738 | 1.000 | 0.915 | 0.965 | 1.000 | 0.980 | 0.895 | 0.939 | 1.000 | 0.000 |

(Vague-date trap is over the sample's 24 vague move-in rows, so one row = 0.042.) **The 0.6B fine-tuned reader beats Opus 5.5 on exact match (0.813 vs 0.738)**, mainly on the lease field (0.998 vs 0.915), where our label conventions (for example "probably" = vague) are learned and not obvious from the prompt. Opus is slightly better on reason (0.895 vs 0.885) and on the vague-date trap (0 of 24 vs 1 of 24). Intent F1 is tied. Opus costs $0.009 per read at 3.3 s p50 (concurrency 8). The fine-tuned reader runs locally at 0.58 s p50 (concurrency 32) with no per-call fee. Metrics: `reader/results/frontier-opus-5-5.test.sample400.metrics.json` (includes `same_sample_baselines` and the sampled ids).

### Reproduce

```bash
# OPENCODE_API_KEY in the repo .env (loaded automatically, never printed); each process has its own spend cap
FRONTIER_BUDGET_USD=7 FRONTIER_USAGE_LOG=gym/results/frontier-usage.jsonl gym/.venv/bin/python gym/ablate.py --run-name _ \
    --split heldout --variants guard+prompt3+style+rhist --api anthropic --model claude-opus-5-5 --prefix heldout-frontier-opus55- --workers 4
FRONTIER_BUDGET_USD=4.5 FRONTIER_USAGE_LOG=gym/results/frontier-usage.jsonl gym/.venv/bin/python reader/eval.py --backend anthropic \
    --model claude-opus-5-5 --label frontier-opus-5-5 --sample 400 --seed 0 --concurrency 8
```

Not done (budget): a second operator seed for Opus, and the full 1,419-row reader set.

## Not measured yet / open

- **Model reader vs fallback**: measured, see the (f) row. The earlier run `heldout-guard+prompt3+style+rhist+readermodel` stays flagged `invalid` (HTTP 401 on all 93 reads, every call fell back to rules); the valid runs are `...+readermodel-rerun` and `-rerun-s2`.
- `format_facts` (showing hours rendered "10:00 to 18:00" like the NeMo rows instead of the raw policy dict) and reasoning off are implemented as variants (`facts`, `think_off`) but not run.
- The NeMo row with prompt v3 is the NeMo-path run of the final config: guard and the style pre-check live in our loop, not in `simple_agent`, and reasoning history is already NeMo's default. A second NeMo run is pending.
- Single runs for the "alone" rows; the spread above (about ±0.02) applies.

## Router (smoke test, not final)

**Status: smoke test only, not a measurement.** 8 tasks, 1 run each, train split. The owner asked for a run that shows the router works and counts Lightning calls; the real comparison will run later on the realistic task set built from the owner's data. Don't quote these numbers as a result.

**What it is.** `RunConfig(router=True)` (default off, `operator/rentus_operator/router.py`, described in `operator/README.md`). The 0.6B reader reads every inbound renter message before Lightning does, and code picks one of five decisions per message burst: `NO_OP` (platform system text, a re-sent duplicate, an ack while we asked nothing), `RECORD_ONLY` (pure data that the model reader and the rule reader agree on; code writes it to the register), `BATCH` (several messages before we answered: one turn), `ESCALATE_DIRECT` (hard no that both readers agree on, or abuse: code escalates with the reader's summary), and `LIGHTNING`. Every decision is logged as an event with actor `router`. Lightning still writes every renter reply. Its turn opens with the reader's parse and the register's current values, and the turn ends as soon as its `send_message` succeeds, so it no longer spends a model call on a closing summary after each reply. No new model: the budget is unchanged (Lightning 30B + reader 0.6B).

**Setup.** Task set v2 train (as committed at `20a3de3`): `lease-{full, vague_date, spanish, small_talk, price_push, volunteered, hard_no, not_now}-train-001`. Final config (guard + prompt v3 + style pre-check + reasoning history) with the fine-tuned reader in both arms, 8 workers, temperature 0.2. The GPU was shared with other sessions' runs, so latency is not controlled.

| | pass | mean reward | Lightning calls / conversation | input tokens / conv | output tokens / conv | reply latency p50 / mean | runs that hit the 30-step cap |
|---|---|---|---|---|---|---|---|
| router off | 1/8 | 0.886 | 24.6 | 322k | 10.5k | 16.1 s / 19.2 s | 6 of 8 |
| router on, first version | 1/8 | 0.789 | 13.1 | 123k | 6.8k | 8.7 s / 12.6 s | 0 |
| **router on, after two fixes** | **4/8** | **0.868** | **12.8** | **125k** | **7.5k** | 12.8 s / 14.8 s | 0 |

Router decisions in the fixed run (46 routed events): LIGHTNING 34, RECORD_ONLY 9, BATCH 2, ESCALATE_DIRECT 1, NO_OP 0. Runs: `gym/results/train-v2-routersmoke-guard+prompt3+style+rhist+readermodel{,+router,+router-fix1}/`. Each per-task row has `model_calls`, `usage`, `reply_latency_s` and `router_decisions`.

What the smoke run shows, read with care:
- **Calls and tokens: the clearest effect.** About half the Lightning calls (24.6 to 12.8) and 61% fewer input tokens per conversation. Most of the saving comes from ending the turn on the send and from Lightning not re-reading and re-recording what the router already parsed. It does **not** come from skipping Lightning: the scripted Gym renters always owe a next question, so a reply was owed on every RECORD_ONLY event, and Lightning was skipped entirely 0 times. NO_OP only fires on real-inbox noise (reactions, duplicates, acks), which these tasks don't contain. The off arm's call count is capped: 6 of 8 off runs hit the 30-step limit.
- **Quality: no clear loss after the fixes, and no proof of a gain.** Router on passed 4 tasks against 1, but reward was slightly lower (0.868 vs 0.886). With 8 tasks and 1 run, one task moves the mean by about 0.1, so both differences are noise until measured properly.
- **The first version hurt quality (0.789), and the cause was found on these train tasks.** (1) The duplicate rule treated a renter's repeated stock line, given as the answer to a *new* question, as noise, and ended the conversation. Now only text re-sent before we answered counts as a duplicate. (2) Once the gate was complete, Lightning re-sent `upsert_renter` with value-less items (`{"lease": {"status": "answered", "months": 12}}`) that erased values the router had recorded, and `propose_showing` was then refused. In router mode the verifier now drops an update that would erase an already-recorded exact value, and the note shows the register's current values. Both fixes came from these 8 train transcripts and were checked on the same 8, so the fixed row is optimistic.
- **One new failure mode to watch.** In `price_push` (fixed run), Lightning returned 4 empty responses in a row on the batched opening (no text, no tool call), so the renter got nothing (reward 0.38). One sample, cause not known.
- Hard no: router on marked the renter `lost` and escalated by code, and Lightning wrote the single close (1.00). Router off forgot to set `lost` (0.86).
- Latency is lower with the router (p50 16.1 s to 12.8 s), but other runs shared the GPU, so treat it as indicative only.

Reproduce:
```bash
IDS=lease-full-train-001,lease-vague_date-train-001,lease-spanish-train-001,lease-small_talk-train-001,lease-price_push-train-001,lease-volunteered-train-001,lease-hard_no-train-001,lease-not_now-train-001
gym/.venv/bin/python gym/ablate.py --run-name _ --split train --tasks-version v2 --prefix train-v2-routersmoke- --workers 8 --ids $IDS \
    --variants guard+prompt3+style+rhist+readermodel,guard+prompt3+style+rhist+readermodel+router
```

## Development iterations (not confirmatory)

Prompt v4 / harness tuning on 2026-10-18, 04:45 to 06:30 ET, before the evaluation freeze. **Development data only**: the Messenger conformance scenarios (`gym/tasks/messenger/`), the concierge train tasks (`gym/tasks/concierge/train.jsonl`) and the v2 TRAIN split (`gym/tasks/v2/train.jsonl`). No v2/v3 held-out file or result was opened. Every number here is one run per item or per seed, on data the changes were made against, so it is a development signal, not a result.

Config for every run: `guard+prompt3+style+rhist+readermodel` with `prompt_version=v4`, `tool_descriptions=concierge`; the "after" runs add `guard_stand_down=true`. "Before" = commit `a611355` (run from a clean worktree at that commit, so mid-run prompt edits could not leak in).

| Change (commit) | What | Dev effect |
|---|---|---|
| 1 (`de5bd37`) prompt | Gate items recorded with `upsert_renter` before `find_showing_slots`/`propose_showing` (C19); stages 2 to 4 are one burst ending in the gate question, read the whole thread so a burst of renter messages counts (C56); phone ask ends with a question; small talk: one two-sentence woven re-ask, third non-answer escalates (C23, C25); a showing request while items are pending gets "a few details first" (C22) | 22 previously failing items rerun (`gym/results/conformance/dev-iter1/`): 17/22 pass. C19, C23, C56 pass |
| 1 prompt | Tenant short on rent: a payment plan for the owner even with no ledger: escalate with a draft, one holding line (C67); owner-announced reconnect done even when `due_followups` is empty, two messages (C47) | C67, C47 pass in the item rerun |
| 1 prompt | Owner lines name a renter: find the thread yourself; confirmation in two messages (full address, then the one-hour rule), reject leads to a new slot, no-show reported; an "After the tour" section (link once, order, applied stops, reply resets the cadence); hard no sets status lost; far-out move-in parked with a check-back draft; unconfirmed facts escalated; pet rules; proxy posters; below-6-month lease escalated; `match_renters` and an owner report before publishing; owner-held threads get nothing | C8, C18, C33 to C35, C39, C40, C42, C43, C48, C49, C54 pass in the item rerun |
| 1 harness, `guard_stand_down` (RunConfig, default off) | The renter guard no longer bounces a run on a thread marked `owner_owned`/`stand_down`, where the prompt says to send nothing (otherwise the harness pushed the model to message the renter) | C54 passes with it on |
| 1 harness, `burst_guard` (RunConfig, default off) | Bounces a renter run that ends with no pending question while gate items are missing. Unit-tested (`operator/tests/test_burst_guard.py`) but **not used** in any run below | not measured |
| 2 (`f045c2e`) prompt | A showing request is never treated as small talk (C22); a room that does not fit is explained ("dogs are not allowed"), not called taken (C66) | in the full run below only |

**Full conformance suite** (`gym/results/conformance/v4-dev2/`, commit `f045c2e`, one run per item): **50 of 61 testable items pass**, up from 33 of 61 for v4 at `0d45798` (`gym/results/conformance/v4/`). 18 items flipped to pass; 1 flipped to fail (C31: the model wrote gate fields as `number`/`count`/`text` instead of `value`, so `propose_showing` was refused; a gate-shape line in the prompt is the obvious next step, not done because the train runs were already reading the prompt). Still failing: C12, C23 and C47 (passed in the item rerun, failed here: run-to-run variance; C47 ended on an empty model response), C33, C42, C51/C52 (no tool lists only live listings, so the model offers every room), C53, C63 (tool gap, as for the reference player), C66.

**Concierge train** (36 tasks, seed 1): pass rate 0.556 to **0.667**, mean reward 0.887 to **0.892** (`dev-concierge-before-s1` in the worktree, `gym/results/dev-concierge-after-s1/`).

**v2 TRAIN** (54 tasks, prompt v4 + concierge tools, seeds 1 and 2): mean reward **0.746 to 0.831** (seed 1: 0.791 to 0.855; seed 2: 0.700 to 0.807), pass rate **0.315 to 0.435** (seed 1: 0.389 to 0.426; seed 2: 0.241 to 0.444). Runs: `gym/results/dev-v2train-v4-before-s1`, `dev-v2train-v4-before-p2-s2`, `dev-v2train-v4-after-s1`, `dev-v2train-v4-after-p2-s2` (summary and per-task rows; before runs copied from the worktree).

Caveats: one run per conformance item; the item rerun (dev-iter1) started while the prompt was still being edited, so some of its scenarios read a partly edited prompt; seeds 1 and 2 of the v2 train runs ran concurrently with other runs on the same endpoint.

## Known issues / post-freeze fixes

These landed on `main` AFTER the evaluation freeze. **The evaluated version is the freeze commit `c81cb21`** (Re-freeze v3, Amendment 8); no number in this file was produced with these fixes, and confirmatory runs keep using the frozen worktree.

- **Unconfirmed facts stated in a listing (safety, fixed 2026-10-18).** In a live console Assistant run on the real Appling Way room, the operator wrote "1 year minimum lease" into the listing text, although the owner-confirmed record (`channels/pilot_post.py`) says lease length is not confirmed for that house. Cause: the room record only said so in free-text `notes`, and no tool checked it. Fix: the record now carries `unconfirmed: [...]` (lease_min_months, deposit, utilities, furnished, shared_spaces, house_rules, pets) with those fields null; a missing/null lease_min_months, deposit or utilities also counts as unconfirmed. `tools/rentus_tools/impl/fact_guards.py` refuses, with `POLICY_BLOCKED` (rule `unconfirmed_fact`), any `create_listing`, `update_listing`, `publish_listing` or `send_message` text that states such a fact (deterministic EN/ES patterns: "1 year", "12 months", "one-year", "minimum lease", "contrato de un año", "6 meses", deposit amounts, utilities included/split, furnished, shared spaces, house rules; questions such as the gate's "Is a one year lease okay with you?" are exempt in messages). Confirmed facts pass unchanged. Prompt v4 gained one line ("Use only facts confirmed in the room record; if a fact is missing or unconfirmed, don't state it.") and its listing step writes "Lease: 1 year" only when the record confirms it. Dry run (Nemotron 3.5 Lightning, sandbox, nothing published): with the console's prompt v3 the model again wrote "1 year", the tool refused it and the saved draft omits the lease; with prompt v4 the first draft omitted it ("Message us for lease terms and details."). Tests: `tools/tests/test_fact_guards.py`.
- **Disclosure template grammar and length (fixed 2026-10-18).** `listing_disclosure` produced "It's bedroom in house on Appling Way..." (missing articles) and long messages that the live SMS composer joined into a ~390-character first text. It now names every room type with its articles in EN and ES ("It's a bedroom in a house on Appling Way...", "Es una habitación en una casa en Appling Way..."), packs sentences into messages of at most 2 sentences and 160 characters, returns house rules as their own message(s) plus a `sequence` (messages then house rules) to send in order, and uses confirmed facts only (no lease, shared-space or house-rule sentences for Appling).
