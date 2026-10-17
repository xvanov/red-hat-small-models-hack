# Results: Gym-driven improvement of the operator (P2.1)

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
| NeMo baseline (`baseline-nemo`) | nemo | 1 | 4/31 (12.9%) | 0.646 | 0.648 | 0.729 | 0.696 | 0.536 | 0 |
| NeMo + (b) prompt v3 | nemo | 1 | 15/31 (48.4%) | 0.809 | 0.755 | 0.917 | 1.000 | 0.762 | 0 |

Per check type, baseline → final (local): style 5% → 100%, state 33% → 87%, tool_called 54% → 86%, escalated 33% → 100%, message 57% → 86%, never 88% → 91%, budget 100% → 100%.

What each change did, held-out:
- **(a) guard** fixes the delivery bug (leasing reward 0.32 → 0.66) but alone barely moves the pass rate: once the model does send, v1's long first drafts break the style checks.
- **(b) prompt v3** is the largest single change (+0.35 reward, 1 → 11 passes) and the only one that transfers to NeMo's harness, where it takes `simple_agent` from 4 to 15 passes. Ops goes to 1.000 in both runners (correct ZIP and vendor ids).
- **(d) style pre-check** does nothing alone (without the guard the model rarely sends anything to check) and adds about +5.5 passes on top of (a)+(b).
- **(g) reasoning history** explains most of the loop-vs-NeMo gap: alone it takes our loop from 0.453 to 0.614 (NeMo baseline 0.646), and it adds about +3.5 passes on top of (a)+(b)+(d).

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

## Not measured yet / open

- **Model reader vs fallback.** `heldout-guard+prompt3+style+rhist+readermodel` is invalid: the reader server answered HTTP 401 to `READER_API_KEY` from `.env` on every call, so all 93 reads used the fallback (flagged `invalid` in its summary). Rerun once the key matches.
- `format_facts` (showing hours rendered "10:00 to 18:00" like the NeMo rows instead of the raw policy dict) and reasoning off are implemented as variants (`facts`, `think_off`) but not run.
- The NeMo row with prompt v3 is the NeMo-path run of the final config: guard and the style pre-check live in our loop, not in `simple_agent`, and reasoning history is already NeMo's default. A second NeMo run is pending.
- Single runs for the "alone" rows; the spread above (about ±0.02) applies.
