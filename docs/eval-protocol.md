# Evaluation protocol (pre-registration)

Written 2026-10-18 ~04:30 ET, **before** the final experiments run. Independent reviewers will attack it, and amendments are logged at the bottom with a time and a reason. The commit time of this file is the proof that it came first. Method details that already exist live in `docs/eval-method.md` (scorer, statistics code, model-played renters). This file says what we will claim, on what data, how we will decide, and what would count against us.

## 0. What has already been seen (so the reader can discount it)

- **v1 tasks** (`gym/tasks/{train,heldout}.jsonl`): run about 15 times on held-out. Superseded, and used for no claim below.
- **v2 held-out** (`gym/tasks/v2/heldout.jsonl`, 33 tasks): run once per config (baseline, final, final + router: 3 seeds each; NeMo path: 2 seeds) at commit `437b611`. The results, and the specific failure patterns behind them, are written up in `docs/results.md`: the `first_person` phrase "pending the owner's confirmation", missing `not_now` / `lost` statuses, and the router's lost move-in dates. Held-out check details were read to write that up. So **v2 held-out is contaminated for any change that targets those patterns.** It stays a secondary set, and it is flagged wherever it is used.
- **Reader synthetic test** (`data/published/reader/test.jsonl`, 1,419 rows): scored once per system. It was never used for training or prompt tuning.
- **Owner's private data**: explored locally (aggregate counts and paraphrase only, in `~/rentus-private-data/work/`). The exploration covered every period, including the held-out window defined in §2.2. That is a known leak of *knowledge about situation types*, not of task content (§8).
- **Never seen by anyone**: v3 twin tasks (not generated yet), the twin reader test set, and the real-replay outputs.

## 1. Hypotheses

The primary test set for H1, H3 and H4 is **v3 held-out** (§2.2), because it is the only uncontaminated agent set. v2 held-out results are reported next to them as secondary.

δ (the non-inferiority margin) = **0.05 mean reward**, fixed now. It is about the size of the shift one task-level flip causes on 20 to 40 tasks, and slightly above the router's measured v2 drop (0.053).

| ID | Claim | Primary metric (test) | Secondary metrics | Counts as NOT supported if |
|---|---|---|---|---|
| H1 | The Gym-improved operator (`final`) beats the `baseline` | Δ mean reward, v3 held-out (paired bootstrap, two-sided, Holm) | Δ pass rate (exact sign/McNemar), pass^3, per category, v2 held-out | Holm-adjusted p ≥ 0.05, or Δ ≤ 0 |
| H2a | The fine-tuned 0.6B reader beats Lightning (prompted, thinking off) at reading renter messages | exact match on the **twin reader test** (exact McNemar on per-row correctness, Holm) | per-field accuracy, vague-date trap, intent F1, latency; synthetic test (already run) | Holm p ≥ 0.05, or reader ≤ Lightning |
| H2b | The fine-tuned reader beats the frontier reference (Claude Opus 5.5, prompted) | exact match on the twin reader test, same rows (exact McNemar, Holm) | the same as H2a | Holm p ≥ 0.05, or reader ≤ frontier. If the budget does not allow the frontier run, H2b is **untested** (not "supported") and only the v1-era 400-row synthetic result is cited, labeled as such |
| H3 | The router cuts Lightning calls without losing more than δ reward | **two co-primary**: (i) Lightning calls per task, router vs final (paired bootstrap; supported if the upper CI bound is < 0); (ii) non-inferiority: the lower bound of the 95% paired CI of Δ reward must be > −δ | input tokens, task time, pass rate, per check type | either (i) or (ii) fails. **Status today: (ii) fails on v2** (Δ −0.053, CI −0.093 to −0.016). A router fix may be designed on train only |
| H4 | The local system (Lightning + 0.6B reader) is within δ of the frontier reference running the same harness | non-inferiority: lower bound of the 95% paired CI of Δ reward (local − frontier) > −δ, v3 held-out | pass rate, cost per task, latency (not like for like) | lower bound ≤ −δ. A **win** is claimed only if the two-sided Holm p < 0.05 with Δ > 0. Untested if the budget is not approved (§4.6) |
| H5 | Prefix caching raises serving throughput on the real operator prompt | output tok/s at N = 32, caching on vs off (`cache_salt`), 3 back-to-back paired repetitions | TTFT p50, gains at N = 8 and N = 64, reader latency under load | the gain is ≤ 0 in any repetition, or the mean gain is < 25%. One repetition (+76%) exists already. This claim is engineering, not inference, so it is outside the Holm family |
| H6 | On real held-out conversations replayed in shadow mode, the system behaves acceptably | **descriptive, with pre-set targets** (§2.4): never-do violations = 0; style pass on drafts ≥ 90%; reader exact match on owner-checked labels ≥ 0.70; agreement with the next action required by the current rules ≥ 60% | escalation rate, register completeness, per-situation breakdown (cells < 5 suppressed) | any target missed. It is reported as missed, with no re-run against the same threads |

**Primary Holm family** (familywise α = 0.05): H1, H2a, H2b, H3(ii), H4. That is 5 tests (fewer if some are untested). H3(i) is a large, mechanical effect and is reported with its CI only. Secondary metrics get uncorrected 95% CIs and are labeled "secondary". No claim rests on them alone.

**A new candidate** (e.g. prompt v4 from lane 2, or a router fix): it gets one pre-declared slot, "H1b: candidate vs final, v3 held-out, two-sided". It joins the Holm family only if it is named in an amendment *before* the v3 held-out freeze. Otherwise it is reported on train only.

### Minimum detectable effects (80% power, α = 0.05 two-sided, before Holm)

These use the per-task SD of paired reward differences seen on v2: ≈ 0.13 for close configs (router vs final) and ≈ 0.23 for distant ones (final vs baseline). MDE ≈ 2.8 × SD / √n.

| n tasks | close configs (Δ reward) | distant configs (Δ reward) | pass rate (sign test, rough) |
|---|---|---|---|
| 33 (v2) | 0.063 | 0.11 | ~20 points |
| 40 (expected v3) | 0.058 | 0.10 | ~18 points |
| 80 | 0.041 | 0.072 | ~13 points |

So H1 is well powered (v2 effect +0.36). H3(ii) and H4 can only show non-inferiority if the true difference is close to 0. A δ of 0.05 at n ≈ 40 needs a true Δ of about ≥ −0.01. The reader tests (H2) have n in the hundreds of rows and are well powered for differences of 5 points or more.

## 2. Datasets and splits

### 2.1 v2 (synthetic, owner-approved, D23)
`gym/tasks/v2/{train,heldout}.jsonl`, 54 / 33 tasks, regenerated byte for byte by `gym/build_tasks.py`. Held-out renter lines come only from the reader test split, and rooms and template pools are disjoint (`docs/task-v2-changes.md`). The privileged reference player (`gym/oracle.py`) passes 54/54 and 33/33. **Role: secondary, contaminated (§0).**

### 2.2 v3 realistic tasks (twins of the owner's data)
Built by `data/twins/` (ingest → label → twin → privacy filter → tasks). Task format: `contracts/tools.md` §10.

- **Sampling frame.** The owner's anonymized 1:1 message threads whose content is leasing (a room inquiry through to a showing, application or loss), regardless of the folder they were filed in. Three-way hand-off threads are included only if partner lines are mapped to the owner side. Excluded: group house chats, social chats, threads where the owner is the renter, the house sale / rent-to-own campaign, automated texts, and Russian threads (the reader's `language` field covers only en/es). Ops twins (maintenance, rent, vendors) are in scope only if the pipeline supports them before the freeze. If so, they are reported as a separate category and never pooled into H1.
- **Time split.** **Held-out = threads whose first message is on or after 2026-05-01.** Train/dev = threads that start earlier.
- **No shared people.** A held-out thread is kept only if none of its counterpart person ids (owner and partner ids excluded) appear in any pre-2026-05-01 thread. Threads from the held-out window that share a person with earlier threads are dropped from **both** splits.
- **Stratification.** Within each split: `stratified_sample` (seeded round-robin) over channel × language × outcome (qualified / showing / applied / ghosted / no). Behavior strata (shorter lease, price push, vague move-in, not now, hard no, ghosted, language switch, Spanish) are balanced up to availability. Held-out takes **every** eligible thread. It is not sampled, so its size is whatever the window gives (expected about 30 to 50 tasks after verification drops).
- **Exclusions for anonymizer damage.** The anonymizer sometimes replaced the day after a month name with a street-name word, which destroys exact dates. Any renter message matching `<month name> <non-numeric token>` where a day is expected (or containing `[state]` in place of a function word next to a date) gets its **move-in gold marked unscorable**. If move-in is the thread's only gate item, the whole thread is excluded. The pipeline logs the count of excluded messages and threads per split, as an aggregate.
- **Implementation gate.** As of this commit `data/twins` has **no** time split or person-disjointness. Both must be added (a `--split-date 2026-05-01` flag, plus an assertion in `to_tasks.py` that no held-out person id appears in train) and tested on the fixture before any v3 task counts.
- **Verification drops** (twins that fail re-labeling 3 times) are counted per stratum and reported. They make v3 easier than reality (§8).

### 2.3 Reader test sets
- Synthetic: `data/published/reader/test.jsonl` (1,419 rows, test-only templates, name pools, SGD test dialogues). Already scored for every system.
- **Twin reader test**: `data/published/twins/reader_test.jsonl`, built **only from held-out threads** (§2.2). This is the primary set for H2. Gold = the real message's labels carried over to the twin's own values, with move-in unscorable where §2.2 says so.
- The reader is not retrained after this protocol. Its checkpoint is frozen (§6).

### 2.4 Private real-replay set (aggregate only)
- The same held-out window and the same person rule as §2.2, as real (anonymized) text. It never leaves the owner's machine. Every model client refuses non-local endpoints (`common.LocalLLM`). The frontier is **never** run on it.
- **Replay.** For each thread, the renter's messages are fed in order to the final config in **shadow mode** (sandbox tools, `send_message` captured, nothing sent). The owner's real replies are not shown to the operator. After each operator turn, the next real renter message is injected, whatever the operator said (open-loop). This is a known limit: the renter cannot react to the operator.
- **Metrics:**
  - never-do violations (promising a discount, quoting an unconfirmed fact, naming the 6-month floor unasked, confirming a showing the owner has not confirmed, any send outside the thread);
  - style pass on drafts, by the send tool's rules;
  - reader exact match on owner-checked labels (§7.2);
  - next-action agreement with **the current rules**, not with the owner's past reply (§3.3), judged per renter turn into categories: ask a gate item / answer a question / propose a showing / park / escalate / close.
- Output: one aggregate JSON (counts and rates, cells < 5 suppressed), shown to the owner before it is committed (§7).

### 2.5 Leakage controls
1. **Tuning happens only on train**: v2 train, v3 train/dev twins, and the reader's train/dev. `gym/results/_p21/diagnose.py` refuses to run on held-out. The same guard is extended to v3 and to the twin reader test before the freeze.
2. **Held-out is frozen with hashes.** The sha256 of `gym/tasks/v3/heldout.jsonl`, `data/published/twins/reader_test.jsonl` and the replay thread-id list (the hash only; the list stays private) are added to §6 in a commit made **before** the first model run on them. Any later change to those files voids the run that used them.
3. **Nobody reads v3 held-out transcripts until all pre-registered runs are done.** Aggregates (pass rate, reward, per-check rates) may be printed. Per-task check details may not.
4. **Owner rules and playbooks are frozen at the same commit** (§3.3). Changing a rule after the freeze creates v3.1, which needs a fresh baseline.
5. **No held-out text in prompts.** Prompt files are grepped for 8-gram overlap with the v3 held-out and twin reader test before runs, and the result is logged.

## 3. Scoring

### 3.1 Check types (`gym/rentus_env/verify.py`, sha256 in §6)
Each check is pass or fail. Reward = the share of checks passed. A task passes only if every check passes.

| type | passes when | known limits |
|---|---|---|
| `state` | a value in the final world equals / contains / exists / meets a bound | checks only the end state, not how it got there. Date normalization accepts only exact dates |
| `never` | a tool is never attempted (or never before a condition such as `gate_complete`), or an item is never asked again (one confirmation allowed, D23c) | passes for an agent that does nothing. "Asked" uses the keyword classifier, which can mislabel unusual phrasing |
| `style` | sent messages are in the renter's language and in first person, with at most 2 refused drafts per thread | language detection is crude on very short messages. `first_person` is a phrase list (it misses paraphrases and may flag quotes) |
| `tool_called` | a tool succeeded with matching arguments, min/max times | argument matching is literal |
| `escalated` | an owner escalation exists or doesn't, optionally matching keywords | keyword match on the reason: a correct escalation in other words fails |
| `budget` | booked spend is under the limit, tool calls are under a cap, no failing call is repeated more than N times | passes for an agent that does nothing |
| `message` | sent text contains or avoids given phrases | phrase lists, so it can be fooled by paraphrase in both directions |

Floor: a do-nothing agent scores 0.291 mean reward on v2 (stub). **Pass rate and pass^k are read alongside reward, never reward alone.** Scripted renters can go silent when the operator's question doesn't match a keyword (fallback lines reduce this but don't remove it).

### 3.2 Human validation of the scorer
- **What.** After all held-out runs finish, the owner grades **N = 40** transcripts, drawn with a fixed seed from v3 held-out across configs: 15 scorer-pass, 15 scorer-fail, and 10 near-miss (reward ≥ 0.85 but fail). The owner is blind to the config and to the scorer's verdict. Per transcript, the owner gives (a) a pass/fail per scorer check and (b) one overall verdict: "would I let this conversation happen under my name?".
- **Report.** Task-level Cohen's κ between the scorer's pass and the owner's overall verdict, with a bootstrap CI. Per-check-type percent agreement and κ where there are 10 or more items. Every disagreement listed in one line.
- **Pre-set threshold: κ ≥ 0.60** (point estimate) for the task-level agreement. Below that, headline pass rates are reported as "scorer-defined pass rate" with the κ next to them, and no claim describes them as "correct behavior". The scorer is **not** changed and re-run to raise κ.

### 3.3 Where behavior comes from
- **Renter behavior comes from the data**: what real renters asked, how vague they were, when they went silent or switched language (twin skeletons), and what facts they had.
- **Correct agent behavior comes from the CURRENT owner rules, not from what the owner did in the past.** Sources: `docs/spec/concierge.md` (when present, frozen at its commit), the rules of engagement the tasks already encode, owner decisions D23, and the playbooks in `docs/playbooks/` once the owner approves them (§7.4). If the owner's past reply conflicts with the current rules (for example, he skipped the gate questions that the rules now require), the check follows the rules. The owner's past next action is recorded only as a secondary "matches the owner's historical move" rate in H6.
- Rules frozen after this protocol's v3 freeze commit are the ones that score. A rule that does not exist at freeze time (e.g. concierge demand capture without a spec) is not scored.

### 3.4 Scripted vs model-played renters
- **Primary: scripted** for every hypothesis test. Scripted renters are deterministic and free of the simulator confound. v3 tasks keep a v2-style `script` derived from the twin turns.
- **Secondary: model-played** (`llm_renter`, using the twin's `twin_script`, `truth` and persona). The simulator is the local Lightning at temperature 0, simulator seed 7, thinking off. It runs final and baseline on v3 held-out with 3 operator seeds. If the direction of H1 differs between modes, both are reported and H1 is described as mode-dependent.
- The simulator is the same model family as the operator and may understand it too easily (§8).

## 4. Procedure

### 4.1 Configs (`gym/ablate.py` variants; `RunConfig` in `operator/rentus_operator/config.py`)
Common to every Lightning config: `model=nemotron-3.5-lightning` (`nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4`), `temperature=0.2`, `max_tokens=2048`, `max_steps=30` (capped by the task's `max_turns`), `max_retries=2`, `backoff_base_s=0.5`, `loop_guard_repeats=3`, `self_check_rounds=1`, `reasoning=None` (server default, on), `tool_descriptions="verbose"`, `verifier=True`, `reader=True`, `format_facts=False`, `api="openai"`.

| name | variant spec | differs from the common values |
|---|---|---|
| baseline | `base` | `prompt_version="v1"`, `renter_guard=False`, `style_precheck=False`, `keep_reasoning_in_history=False`, `router=False`; reader backend = rule-based fallback |
| final | `guard+prompt3+style+rhist+readermodel` | `prompt_version="v3"`, `renter_guard=True` (`renter_guard_rounds=3`), `style_precheck=True`, `keep_reasoning_in_history=True`, `router=False`; reader backend = fine-tuned model |
| final+router | `guard+prompt3+style+rhist+readermodel+router` | final + `router=True`, `router_quiet_s=0.0` |
| final-nemo (secondary) | `--via nemo prompt3+readermodel` | NeMo Gym 0.6.0 `simple_agent`; guard and style pre-check don't apply |
| frontier (reference) | final with `--api anthropic --model claude-opus-5-5` | `api="anthropic"`, `effort="high"`; no temperature (the API rejects it); **the same fine-tuned reader** as final, so only the operator model differs |
| candidate (optional) | named in an amendment before the freeze | — |

**Git commit.** All final runs use one commit, recorded in every `summary.json` and listed in §6 before the runs start. Between that commit and the end of the runs, nothing changes under `gym/rentus_env/`, `gym/tasks/`, `tools/rentus_tools/`, `operator/` or `reader/prompt.py`. A check before each run (`git diff --quiet <commit> -- <those paths>`) refuses to run if anything did.

### 4.2 Seeds and temperatures
- Operator seeds **1, 2, 3** for every Lightning config (sent as the OpenAI `seed` field). The frontier gets one run (or 3 if the budget allows), and its seed is not controllable.
- The simulator (model-played) uses temperature 0, seed 7, thinking off.
- The reader uses temperature 0 and thinking off, for every backend in H2.
- Bootstrap seed 0, 10,000 resamples.

### 4.3 Concurrency
`--workers 5` for agent runs (the same as v2). Model concurrency stays ≤ 8 on the shared GPU (`docs/PARALLEL.md`). The reader eval runs at concurrency 32 (fine-tuned) and 8 (Lightning, frontier). Latency and throughput numbers from agent runs are indicative only (shared GPU). Only the H5 serving bench controls load, and it records `foreign_requests`.

### 4.4 Endpoint-drop handling
- **Rerun rule.** Only rollouts that **never reached the model** are rerun: zero model completions returned and an infrastructure error (connection, timeout, HTTP 5xx, tunnel). They are rerun up to 3 times (`--retry-errors 3`) after `wait_endpoint` succeeds. Rollouts that reached the model are never rerun, whatever their score.
- **Known gap in the current code.** `gym/ablate.py` reruns every row with `status in (model_error, missing)` or any `error`. That includes rollouts that crashed mid-way after real model calls. Before the final runs this is narrowed to the rule above, and the replaced attempt rows are kept in `per_task.attempts.jsonl` instead of being overwritten.
- **Mid-rollout drops** (an infrastructure error after ≥ 1 completion) are scored as they are and counted. If more than **10%** of a run's rollouts have one, the **whole run is void** and repeated with the same seed. That decision doesn't depend on any score. The voided run is kept and listed.
- `summary.json` → `model_error_retries` lists `tasks_rerun` and `still_failed`. A run with any `still_failed` is incomplete and is repeated, never reported.

### 4.5 Stopping rules
- Exactly 3 seeds per config. **No optional stopping**: no extra seeds or tasks are added because a result is close. The only allowed repeat is the outcome-independent void rule in §4.4.
- Order: protocol commit → v3 build → owner checkpoints 7.1, 7.2 and 7.4 → freeze commit with hashes → runs (baseline, final, final+router, frontier, model-played) → reader H2 runs → H5 bench → H6 replay → scorer grading (7.3) → write-up.
- If the 08:30 feature freeze arrives before every run finishes, the hypotheses whose runs are incomplete are reported as **not tested**, with the partial data clearly marked.

### 4.6 Budget
- GPU: one RTX Pro 6000, funded through 11:00 (D25). Estimate: about 15 minutes per seed per config on v2 at 5 workers, so roughly 3 configs × 3 seeds × ~40 tasks ≈ 3 hours on v3 for scripted, plus about 2 hours for model-played.
- Frontier: the D21 cap is $10, of which $7.62 is spent, leaving **$2.38**. That is not enough for the operator on v3 (≈ $0.11 × tasks × runs) plus the reader. H2b and H4 need the owner to approve a stated amount before they run (estimate: operator 40 tasks × 1 run ≈ $4.50; twin reader test ≈ $0.009 × rows). If the owner doesn't approve, H2b and H4 are untested. A hard cap per process (`FRONTIER_BUDGET_USD`) stops spending at the approved amount. A run cut off by the cap is reported as incomplete.

## 5. Statistics (`gym/stats.py`; definitions in `docs/eval-method.md` §4)
- **Unit = task** (or reader row for H2). Seeds reduce noise within a task but add no tasks. Every interval resamples tasks, never task-runs.
- **Pass rate**: the mean over tasks of the per-task pass fraction, with a 95% Wilson interval on n = tasks (conservative with repeats). **Mean reward**: a 95% percentile bootstrap over tasks.
- **pass^k** (passes in all k runs; τ-bench estimator C(c,k)/C(n,k)) and **pass@k**, both with a bootstrap CI. pass^3 is reported next to every pass rate.
- **Paired tests**: Δ reward by paired bootstrap over tasks (two-sided p from the centered bootstrap; non-inferiority p = the share of bootstrap Δ ≤ −δ). Pass/fail by the exact two-sided sign test on per-task pass fractions (ties dropped). With one run this is exactly McNemar. For H2: exact McNemar on per-row exact match.
- **Multiple comparisons**: Holm over the primary family (§1), at familywise α = 0.05. Secondary comparisons get Holm within their own table, which is labeled exploratory.
- **Non-significant results** are reported in the same table and format as significant ones: the point estimate, the CI, and "not supported" or "not distinguishable from 0 at this n", with the MDE from §1. No result is dropped. No result is described as a "trend". Hypotheses that were untested (budget or time) are listed as untested.
- **Kappa**: Cohen's κ with a bootstrap CI over transcripts.

## 6. Provenance and reproducibility

### 6.1 Frozen inputs (sha256 at the protocol commit)

| file | sha256 |
|---|---|
| `gym/tasks/v2/heldout.jsonl` | `7c5a626f872e0c987dc6564c1549a258564b293cb26f424dc741fcec23b33b00` |
| `gym/tasks/v2/train.jsonl` | `03ba99a1c82f22b2b4a07c49b2b3d17b1c76c441bd44fc3334be4694b60fc8d6` |
| `data/published/reader/test.jsonl` | `2b880ee1658fc421aaa2baa81f5d855c18014238301c58da88fab67d99999bfc` |
| `data/published/reader/dev.jsonl` | `b7fb0bbe33ec1fed87e068205492b445ebed8806ea57b9f4ca32f5068b36c4bb` |
| `gym/rentus_env/verify.py` | `62fffb18f20e56e20d8d48158240fb9d59e461a71c6018b1017674b8149438f3` |
| `operator/prompts/system_v3.md` | `fdfa90a7f2052c20348c2dc9d6e7734b134257e1dc27d0daca1a9181060f1aa0` |
| reader `model.safetensors` (release `reader-v1`, HF `xvanov/rentus-reader-qwen3-0.6b`) | `877c884355584ed5c78caaca741e33cc438037f2dc80cb991119c97476dc2ec6` |
| reader tarball `rentus-reader-qwen3-0.6b-v1.tar.gz` | `c310824fc52f20a2e88ce2e7a9ce5e167ddc5069db048bfee69ba8e2e16ba466` |
| `gym/tasks/v3/heldout.jsonl` | *added in the freeze commit, before any run* |
| `data/published/twins/reader_test.jsonl` | *added in the freeze commit* |
| replay thread-id list (private; hash only) | *added in the freeze commit* |
| run commit | *added in the freeze commit* |

Lightning weights are pulled by Hugging Face id. The revision hash vLLM resolved is copied from the server log into §6 at freeze.

### 6.2 Environment
vLLM `vllm/vllm-openai:v0.27.1` (flags in `serving/start_vllm.sh` and `reader/serve_reader.sh`), 1× RTX Pro 6000 Blackwell 96 GB, NVFP4 via Marlin. Gym: Python 3.12.3 (`gym/.venv`). NeMo Gym 0.6.0 on Python 3.13.14 (`gym/.venv-nemo`). Frontier: `anthropic` SDK 1.11.0 via OpenCode Zen. Twins: `data/twins/requirements.txt`, embedding model `paraphrase-multilingual-MiniLM-L12-v2` on CPU.

### 6.3 Commands
```bash
F=guard+prompt3+style+rhist+readermodel; V3=gym/tasks/v3/heldout.jsonl
# H1 / H3 (scripted, primary)
gym/.venv/bin/python gym/run_seeds.py --variant base      --tasks-file $V3 --seeds 1,2,3 --prefix v3-heldout-baseline     --workers 5
gym/.venv/bin/python gym/run_seeds.py --variant $F        --tasks-file $V3 --seeds 1,2,3 --prefix v3-heldout-final        --workers 5
gym/.venv/bin/python gym/run_seeds.py --variant $F+router --tasks-file $V3 --seeds 1,2,3 --prefix v3-heldout-final-router --workers 5
# H4 (reference; OPENCODE_API_KEY in .env, never printed)
FRONTIER_BUDGET_USD=<approved> FRONTIER_USAGE_LOG=gym/results/frontier-usage.jsonl gym/.venv/bin/python gym/ablate.py --run-name _ \
  --tasks-file $V3 --variants $F --api anthropic --model claude-opus-5-5 --prefix v3-heldout-frontier- --workers 4
# model-played (secondary): the same with an llm_renter copy of $V3 and --sim-seed 7
# stats (no model calls)
gym/.venv/bin/python gym/stats.py --md --categories \
  --config baseline=v3-heldout-baseline-s1,v3-heldout-baseline-s2,v3-heldout-baseline-s3 \
  --config final=v3-heldout-final-s1,v3-heldout-final-s2,v3-heldout-final-s3 \
  --config router=v3-heldout-final-router-s1,v3-heldout-final-router-s2,v3-heldout-final-router-s3 \
  --compare final:baseline --compare router:final
# H2
python3 reader/eval.py --backend endpoint --base-url http://127.0.0.1:8001/v1 --model rentus-reader --label finetuned-twin --split <twin reader test>
python3 reader/eval.py --backend endpoint --base-url http://127.0.0.1:8000/v1 --model nemotron-3.5-lightning --no-thinking --concurrency 8 --label lightning-twin --split <twin reader test>
# H5 (3 paired repetitions)
for r in 1 2 3; do gym/.venv/bin/python serving/serve_bench.py --label on-r$r --levels 8,32,64 --reader-probe
                   gym/.venv/bin/python serving/serve_bench.py --label off-r$r --no-prefix-reuse --levels 8,32,64 --reader-probe; done
```
If a flag above doesn't exist yet (`--split` on the twin set for `reader/eval.py`, `--tasks-file` on `ablate.py`), it is added before the freeze with no change in behavior, and noted here as an amendment.

### 6.4 Where results live
Agent runs: `gym/results/<prefix>-s<seed>/` (`summary.json` with RunConfig, commit, task file and seed; `per_task.jsonl`; `transcripts/`; `per_task.attempts.jsonl`). Reports: `gym/results/v3-heldout-*-report.md`. Reader: `reader/results/*.twin.*`. Serving: `serving/results/*.jsonl`. Twins: `data/published/twins/` (stats card, filter report, twins, reader test). Replay: private outputs in `~/rentus-private-data/work/replay/`; the owner-approved aggregate in `data/published/replay/aggregate.json`. Narrative: a new "v3 results" section at the top of `docs/results.md`.

### 6.5 What a third party can and cannot reproduce

| can | cannot |
|---|---|
| Regenerate v1/v2 tasks byte for byte. Rerun the reference player. Recompute every statistic from the committed runs with no model calls | Regenerate the v3 twins (this needs the owner's private threads). They can verify the published twins and tasks against the hashes, and audit the method and the filter report |
| Rerun any Lightning config (on a GPU with vLLM 0.27.1 and the NVFP4 checkpoint). Expect the same distribution, not identical transcripts: batch-level numeric noise | Get bit-identical rollouts. Seeds make runs distinct and labeled, not deterministic under load |
| Rerun the reader evals from the published checkpoint | Rerun the frontier without their own API key and spend. The model may also change behind the API |
| Rerun the serving bench (numbers depend on the GPU and on other load) | Rerun H6 or see any per-thread output. Only the aggregate JSON and the replay code are public |

## 7. Owner verification checkpoints

| # | What | When | Pass condition | If it fails |
|---|---|---|---|---|
| 7.1 | **Twin realism, blind review.** 10 real threads (shown locally, never committed) and 10 twins from **train**, shuffled. The owner marks each as real or twin and rates realism 1 to 5 | after the v3 build, **before the freeze** | identification accuracy ≤ 75% **or** mean twin realism ≥ 3.5 | fix the twin prompts on train and repeat. If it still fails, v3 is reported as "synthetic, realism not confirmed" |
| 7.2 | **Label spot-check.** 50 renter-message labels (the Lightning gold), seeded and drawn from both splits. Per field: correct / wrong / unscorable | before the freeze | ≥ 90% correct per field on lease, move-in, phone and occupants; reason ≥ 80% | fields below threshold are dropped from exact match for H2 (reported both ways), and the rate is stated |
| 7.3 | **Scorer agreement grading** (§3.2), N = 40, blind | after all held-out runs | κ ≥ 0.60 | report "scorer-defined" (§3.2). The scorer is not changed |
| 7.4 | **Ideal-flow playbooks approval** (`docs/playbooks/`, and `docs/spec/concierge.md` if used for checks) | before the freeze | owner signs off in `docs/DECISIONS.md` | unapproved flows don't score anything |
| 7.5 | **Protocol sign-off** (this file plus any amendments) | before the freeze | an entry in `docs/DECISIONS.md` | — |
| 7.6 | **Replay aggregate privacy check** | before committing `data/published/replay/aggregate.json` | the owner approves the exact file | it is not published |
| 7.7 | **Frontier budget** (§4.6) | before the frontier runs | an explicit $ amount | H2b and H4 untested |

## 8. Threats to validity

1. **Same-model circularity.** Lightning labels the real messages (twin gold), verifies the twins and plays the simulated renter. This favors Lightning in H2a (gold made by Lightning with thinking on, compared with Lightning with thinking off). The 7.2 spot-check and the reporting of field-level owner agreement are the mitigation, not a cure.
2. **Twin selection bias.** Twins that fail verification are dropped. Those are probably the messiest real threads, so v3 is easier than reality. Drop counts per stratum are reported.
3. **v2 contamination and the post-hoc timing.** This protocol was written after the v2 results were seen. v2 is therefore demoted. Hypothesis H3(ii) is stated with its current failure on record.
4. **Exploration leak.** The private exploration covered the held-out window. It shaped *which situations* we model (task categories, rules), not task content. Prompts are checked for 8-gram overlap (§2.5).
5. **Harness tuned for Lightning.** Prompt v3, the guard and the style pre-check came from Lightning's failures. The frontier gets no tuning, so H4 is tilted toward us. The frontier also runs without temperature control and with its own thinking.
6. **Scorer limits** (§3.1): a do-nothing agent scores 0.291 mean reward. Phrase-list checks are fooled by paraphrase. Keyword-classified "asked". One failed check fails a task, which is why pass rates sit low next to reward.
7. **Small n.** About 30 to 50 v3 held-out tasks. Per-category numbers (listing, ops, recovery: 4 to 5 tasks each) are anecdotes. The MDE table says what can't be detected.
8. **Temporal shift.** The held-out window reflects the owner's 2026 process, which is not the earlier train window. That is intended (newest = closest to deployment), but train/held-out differences can be shift, not overfitting.
9. **Past behavior vs current rules.** Correct behavior is scored by the current rules, which the owner's own past replies often didn't follow. H6 next-action agreement depends on how those rules are turned into categories. The judge (a rule table, or a human for ambiguous turns) is written down before the replay.
10. **Open-loop replay** (H6): real renters can't react to what the operator says, so later turns may not fit. The replay measures per-turn behavior, not conversation outcomes.
11. **Anonymizer artifacts**: corrupted dates (excluded), substituted function words and pseudonymized verbs remain. They can confuse the reader and the operator in ways real text would not.
12. **Coverage.** Real threads are all phone messaging, while tasks name marketplace and other channels. English and Spanish only (Russian threads excluded). Personas are US-only (Nemotron-Personas-USA).
13. **Infrastructure noise.** The GPU is shared and the tunnel drops. Rerun rules (§4.4) are outcome-independent but change which samples are kept. Latency numbers from agent runs are not controlled.
14. **One grader.** The owner is the only human grader (no inter-rater check between humans), and he has a stake in the result. Blinding (§3.2, §7.1) is the guard.
15. **Simulator realism.** The model-played renter is the operator's model family and may be easier to talk to than real people. That is why it is secondary.

## Amendments

| when (ET) | change | why |
|---|---|---|
| | | |
