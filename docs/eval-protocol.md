# Evaluation protocol (pre-registration)

Written 2026-10-18 ~04:30 ET, **before** the final experiments run. Independent reviewers will attack it, and amendments are logged at the bottom with a time and a reason. The commit time of this file is the proof that it came first. Method details that already exist live in `docs/eval-method.md` (scorer, statistics code, model-played renters). This file says what we will claim, on what data, how we will decide, and what would count against us.

## 0. What has already been seen (so the reader can discount it)

- **v1 tasks** (`gym/tasks/{train,heldout}.jsonl`): run about 15 times on held-out. Superseded, and used for no claim below.
- **v2 held-out** (`gym/tasks/v2/heldout.jsonl`, 33 tasks): run once per config (baseline, final, final + router: 3 seeds each; NeMo path: 2 seeds) at commit `437b611`. The results, and the specific failure patterns behind them, are written up in `docs/results.md`: the `first_person` phrase "pending the owner's confirmation", missing `not_now` / `lost` statuses, and the router's lost move-in dates. Held-out check details were read to write that up. So **v2 held-out is contaminated for any change that targets those patterns.** It stays a secondary set, and it is flagged wherever it is used. *(Amendment 1: worse than that. v2 held-out shares 31 of 33 tasks and 81 of 92 reader utterances with v1 held-out, and v2 was designed from v1 held-out transcripts, so v2 is exploratory only. `b190ed2` and `08cbaa9` changed a tool hint and added a guard after the v2 held-out failures; see A9.)*
- **Reader synthetic test** (`data/published/reader/test.jsonl`, 1,419 rows): scored once per system. It was never used for training or prompt tuning.
- **Owner's private data**: explored locally (aggregate counts and paraphrase only, in `~/rentus-private-data/work/`). The exploration covered every period, including the held-out window defined in §2.2. That is a known leak of *knowledge about situation types*, not of task content (§8).
- **Never seen by anyone**: v3 twin tasks (not generated yet), the twin reader test set, and the real-replay outputs.

## 1. Hypotheses

The primary test set for H1, H3 and H4 is **v3 held-out** (§2.2), because it is the only uncontaminated agent set. v2 held-out results are reported next to them as secondary.

δ (the non-inferiority margin) = **0.05 mean reward**. *(Amendment 1, A2: the original justification was wrong (0.05 is below the router's v2 drop of 0.053, and one task flip moves mean reward by about 0.0025, not 0.05), and δ was chosen after seeing v1 and v2 results. δ stays 0.05, fixed before any v3 run; v3 is the only confirmatory set.)*

| ID | Claim | Primary metric (test) | Secondary metrics | Counts as NOT supported if |
|---|---|---|---|---|
| H1 | The Gym-improved operator (`final`) beats the `baseline` | Δ mean reward, v3 held-out (paired bootstrap, two-sided, Holm) | Δ pass rate (exact sign/McNemar), pass^3, per category, v2 held-out | Holm-adjusted p ≥ 0.05, or Δ ≤ 0 |
| H2a | The fine-tuned 0.6B reader beats Lightning (prompted, thinking off) at reading renter messages | exact match on the **twin reader test** (exact McNemar on per-row correctness, Holm) | per-field accuracy, vague-date trap, intent F1, latency; synthetic test (already run) | Holm p ≥ 0.05, or reader ≤ Lightning |
| H2b | The fine-tuned reader beats the frontier reference (Claude Opus 5.5, prompted) | exact match on the twin reader test, same rows (exact McNemar, Holm) | the same as H2a | Holm p ≥ 0.05, or reader ≤ frontier. If the budget does not allow the frontier run, H2b is **untested** (not "supported") and only the v1-era 400-row synthetic result is cited, labeled as such |
| H3 | The router cuts Lightning calls without losing more than δ reward | **two co-primary**: (i) Lightning calls per task, router vs final (paired bootstrap; supported if the upper CI bound is < 0); (ii) non-inferiority: the lower bound of the 95% paired CI of Δ reward must be > −δ | input tokens, task time, pass rate, per check type | either (i) or (ii) fails. **Status today: (ii) fails on v2** (Δ −0.053, CI −0.093 to −0.016). A router fix may be designed on train only |
| H4 | The local system (Lightning + 0.6B reader) is within δ of the frontier reference running the same harness | non-inferiority: lower bound of the 95% paired CI of Δ reward (local − frontier) > −δ, v3 held-out | pass rate, cost per task, latency (not like for like) | lower bound ≤ −δ. A **win** is claimed only if the two-sided Holm p < 0.05 with Δ > 0. Untested if the budget is not approved (§4.6) |
| H5 | Prefix caching raises serving throughput on the real operator prompt | output tok/s at N = 32, caching on vs off (`cache_salt`), 3 back-to-back paired repetitions | TTFT p50, gains at N = 8 and N = 64, reader latency under load | the gain is ≤ 0 in any repetition, or the mean gain is < 25%. One repetition (+76%) exists already. This claim is engineering, not inference, so it is outside the Holm family |
| H6 | On real held-out conversations replayed in shadow mode, the system behaves acceptably | **descriptive, with pre-set targets** (§2.4): never-do violations = 0; style pass on drafts ≥ 90%; reader exact match on owner-checked labels ≥ 0.70; agreement with the next action required by the current rules ≥ 60% | escalation rate, register completeness, per-situation breakdown (cells < 5 suppressed) | any target missed. It is reported as missed, with no re-run against the same threads |

**Primary Holm family** *(superseded by Amendment 1, A1: one-sided tests, familywise α = 0.025, m = 5 fixed: H1, H2a, H2b, H3 as an intersection-union of (i) and (ii), H4)* (familywise α = 0.05): H1, H2a, H2b, H3(ii), H4. That is 5 tests (fewer if some are untested). H3(i) is a large, mechanical effect and is reported with its CI only. Secondary metrics get uncorrected 95% CIs and are labeled "secondary". No claim rests on them alone.

**A new candidate** (e.g. prompt v4 from lane 2, or a router fix): it gets one pre-declared slot, "H1b: candidate vs final, v3 held-out, two-sided". It joins the Holm family only if it is named in an amendment *before* the v3 held-out freeze. Otherwise it is reported on train only.

### Minimum detectable effects (80% power, α = 0.05 two-sided, before Holm)

These use the per-task SD of paired reward differences seen on v2: ≈ 0.13 for close configs (router vs final) and ≈ 0.23 for distant ones (final vs baseline). MDE ≈ 2.8 × SD / √n.

| n tasks | close configs (Δ reward) | distant configs (Δ reward) | pass rate (sign test, rough) |
|---|---|---|---|
| 33 (v2) | 0.063 | 0.11 | ~20 points |
| 40 (expected v3) | 0.058 | 0.10 | ~18 points |
| 80 | 0.041 | 0.072 | ~13 points |

So H1 is well powered (v2 effect +0.36). H3(ii) and H4 can only show non-inferiority if the true difference is close to 0. A δ of 0.05 at n ≈ 40 needs a true Δ of about ≥ −0.01. ~~The reader tests (H2) have n in the hundreds of rows and are well powered for differences of 5 points or more.~~ *(Withdrawn; simulated power in Amendment 1, A3.)*

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
- The same held-out window and the same person rule as §2.2, as real (anonymized) text. Private data never leaves infrastructure we control: this machine and our rented GPU instance (reached over an encrypted SSH tunnel); it is never sent to a third-party model API and never committed (Amendment 1, A10; D28). The frontier is **never** run on it.
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
*(Superseded by Amendment 1, A5: simple random sample, blinded, rubric fixed in advance.)*
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
| `gym/rentus_env/verify.py` | `62fffb18f20e56e20d8d48158240fb9d59e461a71c6018b1017674b8149438f3` (changed by Amendment 1; the new hash goes into the freeze commit) |
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

## Amendment 1 (2026-10-18 ~04:00 ET, before any v3 task or twin reader row has been run by any model)

Answers every blocker and major in `docs/reviews/stats-review.md` (S-), `docs/reviews/leakage-review.md` (L-) and `docs/reviews/scorer-privacy-review.md` (P-). Where this section and §1 to §8 disagree, **this section wins**. No v3 result and no twin reader test result existed when it was written; its commit time is the proof. The code it names is committed before this file (commits `0639d85` to `b366d44`).

### A1. Confirmatory hypotheses and their tests (final list)

Every confirmatory test is **one-sided**. The family is fixed at **m = 5**, Holm step-down at **familywise one-sided α = 0.025** (the usual two-sided 0.05, stated as one-sided tests). A hypothesis whose runs are missing or incomplete at analysis time stays in the family with **p = 1** ("not tested"); m never shrinks (S-12). The plan is machine-readable in `gym/confirmatory_v3.json` and is evaluated in one call: `gym/.venv/bin/python gym/stats.py plan gym/confirmatory_v3.json --md` (S-1, S-2). Unit tests with known answers: `gym/tests/test_stats_confirmatory.py`.

| ID | Claim | Data | Test (code) | Supported if |
|---|---|---|---|---|
| H1 | `final` beats `baseline` | v3 held-out, 5 seeds each | one-sided superiority on the paired per-task mean-reward difference: H0 Δ ≤ 0. p = max(percentile-bootstrap p, paired-t p), 10,000 resamples over tasks, seed 0 (`stats.one_sided_test`, margin 0) | Holm-adjusted rejection |
| H2a | fine-tuned reader beats Lightning (thinking off) | **owner-labeled twin reader rows** (A1a): held-out threads only, gold written blind by the owner | exact match with **`reason` scored on status only** (`reader/eval.py` `exact_match_primary`, per-row `em_primary`); **paired cluster bootstrap over threads** (resample threads, recompute the difference), H0 Δ ≤ 0 (`stats.cluster_paired_test`). Row-level exact McNemar is printed as a sensitivity column only (S-3) | Holm-adjusted rejection |
| H2b | fine-tuned reader beats the frontier reference (Claude Opus 5.5 via the owner's Claude Code, D26) | same owner-labeled rows | same as H2a | Holm-adjusted rejection |
| H3 | the router cuts Lightning calls without losing more than δ | v3 held-out, 5 seeds each | intersection-union of two one-sided tests, p_H3 = max(p_i, p_ii): (i) `model_calls` per task, H0 mean(router − final) ≥ 0 (`stats.fewer`); (ii) non-inferiority on mean reward, H0 Δ ≤ −δ (`stats.one_sided_test`, margin δ) | Holm-adjusted rejection of the combined p |
| H4 | the local system (`final`) is within δ of the frontier reference on the same harness | v3 held-out, 5 seeds local, 5 frontier runs | one-sided non-inferiority, H0 Δ(final − frontier) ≤ −δ, same machinery as H3(ii). A **win** is not claimed from this test | Holm-adjusted rejection |

**A1a. H2 gold must not come from a system under test.** The twins pipeline now labels real messages with the fine-tuned reader (`--labeler reader`, `data/twins/README.md`), and the twin reader test's gold is those labels carried over. Scoring the reader against its own labels would make H2a/H2b circular, so the full twin reader test with reader gold is **secondary only** (reported with that caveat, never in the family). The confirmatory H2 rows are `data/published/twins/reader_test_owner.jsonl`: all renter rows of a simple random sample of held-out twin threads (`stats.simple_random_sample` over twin ids, seed 0), added thread by thread until at least 150 rows, each labeled **blind** by the owner from the twin text and its context (he never sees any model's label first), `reason` on status only. The file's sha256 goes into the freeze commit before any model reads those rows. If the owner labels are not done before the analysis, H2a and H2b are "not tested" (p = 1). Expected size is about 25 to 30 threads × 5 to 6 rows, so by A3 only differences of roughly 8 to 15 points are detectable; the full reader-gold set is reported next to it.

Each decision prints the estimate, the bootstrap and paired-t (1 − α) lower bounds and both p values. The p used is the larger of the two, so the more conservative method decides when they disagree (S-9). At the rank where Holm tests a hypothesis, the bound at that rank's level (`alpha_at_rank`) is the Holm-consistent confidence bound.

- **H1b (prompt v4 from lane 2, built from `docs/spec/concierge.md`)** is **outside the family**. It is reported as "informed by the held-out window" (L-6), with the same test, and never pooled into H1.
- Every `gym/stats.py` command in the analysis runs with `--strict` (a task missing from any run is an error, S-11).
- Secondary, not confirmatory, uncorrected 95% intervals, labeled "secondary": pass rate (Wilson), pass^k (descriptive only; no claim compares pass^k between configs, n/a for runs without repeats, S-15), per-category results, a **pass-rate non-inferiority with δ_pass = 10 points** and the **share of headroom lost**, Δ / (1 − reward_final) (S-5), the model-played renter runs, reward without guard-enforced checks (A5), and every v2 number. The pass-rate column of `md_compare` is a sign test on per-task pass fractions (McNemar only with one run) and its Holm column is labeled exploratory (S-13).

### A2. δ, and what was seen before it was set (S-5)

δ = **0.05 mean reward**, unchanged, fixed now for the v3 runs. The original justification was wrong on both counts and is withdrawn: 0.05 is *below* the router's v2 drop of 0.053, not above it, and one task flipping from fail to pass moves mean reward by that task's reward change divided by n (about 0.1 / 40 = 0.0025), not by 0.05. **δ was chosen after seeing** the v1 frontier comparison (final − Opus = +0.032, CI −0.014 to +0.081, which would already pass H4 at δ = 0.05) and the v2 router drop (−0.053, which fails H3(ii)). That is a forking path, and it is the reason v2 is exploratory and only v3 is confirmatory. δ is about 70% of the final config's v2 headroom (1 − 0.929), so a reward-only non-inferiority could hide a pass-rate collapse; the δ_pass and headroom-lost rows in A1 are there so a reader can see that.

### A3. Seeds and honest power (S-4, S-6, S-7, S-10)

**Seeds: 5 per config** (operator seeds 1 to 5) for `baseline`, `final`, `final+router`, and **5 frontier runs** (no dollar cap since D26; if subscription rate limits stop a run, the hypothesis it feeds is "not tested", p = 1). Measured on the committed v2 runs (`gym/stats.py power`, output in `gym/results/power-amendment1.txt`), about two thirds of the router-vs-final paired variance is seed noise (within-task variance 0.0196 router, 0.0064 final; paired variance 0.0131, of which 0.0087 is seed noise at k = 3), so more seeds are the cheapest lever. More than 5 does not fit the GPU time before the 08:30 freeze. `docs/eval-method.md:94` ("seeds are minor noise") is wrong for the close comparisons.

Power by **simulation of the exact decision rules above** with this repo's own code (`stats.simulate_power`, `stats.simulate_reader_power`; task-level and seed-level variance from v2; 200 simulated studies per point, 500 bootstrap resamples each, so ±0.005 resolution). The number is the **true difference needed for 80% power**:

| hypothesis | n tasks | seeds | at α = 0.025 (tested last in Holm) | at α = 0.005 (tested first, m = 5) |
|---|---|---|---|---|
| H1 superiority | 33 | 5 | +0.109 | +0.138 |
| H1 superiority | 40 | 5 | +0.099 | +0.124 |
| H1 superiority | 60 | 5 | +0.075 | +0.095 |
| H3(ii) / H4 non-inferiority, δ = 0.05 | 33 | 5 | −0.001 | +0.015 |
| H3(ii) / H4 non-inferiority, δ = 0.05 | 40 | 5 | −0.005 | +0.007 |
| H3(ii) / H4 non-inferiority, δ = 0.05 | 60 | 5 | −0.015 | −0.004 |
| (same, 3 seeds, for comparison) | 40 | 3 | +0.003 | +0.017 |

H4 assumes the frontier's seed variance equals the router's (0.0196), the larger of the two measured values. Reading: H1 is well powered for any effect near the v2 size (+0.36). **H3(ii) and H4 can only succeed if the true difference is about zero or positive**; a true loss of even 0.01 to 0.02 will usually fail. They are underpowered for small losses by design, and a failure is reported as "not shown", never as "inferior".

Reader (H2, cluster bootstrap over threads), true exact-match difference for 80% power, by expected size and disagreement rate (share of rows where the two systems differ):

| threads × rows per thread | disagree 10% | disagree 20% |
|---|---|---|
| 30 × 6 | 0.08 (α .025) / 0.10 (α .005) | 0.10 / 0.15 |
| 40 × 8 | 0.06 / 0.08 | 0.08 / 0.10 |
| 60 × 8 | 0.05 / 0.06 | 0.08 / 0.08 |

The old sentence "well powered for differences of 5 points or more" is withdrawn. On the synthetic 400-row sample the fine-tuned reader and Opus disagree on 19% of rows (primary metric), so H2b needs a true difference of about 8 to 10 points. The report states the thread count and mean rows per thread.

### A4. Scorer validity changes (P-1, P-3, P-4, P-5, P-7, P-8, P-9)

All in `gym/rentus_env/` (`v3_rules.py`, applied identically by `RolloutSession` and `verify`; deterministic, idempotent, a no-op for v1/v2 tasks, so v2 scores are unchanged: the v2 reference player still passes 54/54 and 33/33). Tests: `gym/tests/test_v3_rules.py`.

| finding | change |
|---|---|
| P-1 reason wording | H2 primary exact match scores `reason` on **status only** and skips fields marked unscorable; the free-text reason value is secondary (`reader/eval.py`). The twins pipeline no longer filters twins by any model's re-labeling (`53559af`, "no labeler-gated rewrites"), and rule-vs-gold disagreements are flagged per row. Because its gold now comes from the fine-tuned reader, confirmatory H2 uses independent owner gold (A1a); the reader-gold set and its unflagged subset are secondary |
| P-3 historical behavior as required behavior | renter lines are keyed to the **renter's own labeled items**, not to the question the owner happened to ask; a line carrying a non-gate behavior (hard no, not now, price push, question, small talk) is a `"when_asked": "next"` line that answers the next operator message whatever it asks, at the latest at its historical reply position (`counterparts.py`). "showing proposed" from the historical outcome is dropped and replaced by a rule check: gate complete in the gold facts and move-in within 45 days → `propose_showing` required (R-SHOW-1, R-PHIL-2); further out is R-PARK-6, whose threshold is an open owner question (concierge §8 q8), so it is **not scored**. The 45 days is our operationalization and goes to the owner at checkpoint 7.4. The "n_owner + 2 sends" spam cap is dropped and replaced by R-STYLE-3 / R-GHOST-1: at most 2 delivered questions in a row without a renter reply (`followups`) |
| P-4 trivial agents pass | every task where asking is allowed must ask at least one gate item the renter did not volunteer (`asks_gate_item`), so one greeting cannot pass a ghosted task; the price escalation needs price words in its reason. `gym/floors.py` computes the floors of four trivial agents (do-nothing, greet-only, escalate-all, mark-lost) and lists flagged tasks (any trivial agent passes). The v3 floors are computed and committed in the freeze commit; flagged tasks are reported both with and without. On the fixture, 0 of 7 tasks are passed by any trivial agent (before: the ghosted task passed on one greeting) |
| P-5 invented gate values | every gate item the renter never gave must not be recorded as done (`gate_not_invented`, R-GATE-1) |
| P-7 model-played renter | the model-played renter says the twin's not-now, hard-no and price lines **verbatim** at their reply position, then follows `ghost_after` (`llm_renter.py`, `key_lines`); "You already asked about a discount" is said only after it has; `truth.reason` is the gold value, not the whole twin message. Model-played results stay secondary; the turn log records `scripted_key_behavior` and `fallback` per turn |
| P-8 guard-enforced checks | checks a `send_message` guard makes impossible to fail (style `language`, `first_person`, `max_two_sentences`, `one_question`, `no_long_dash` on sent messages) are tagged `guard_enforced` and reported apart: every result has `reward_earned` / `pass_earned` without them, and `refused_by_rule` counts the **attempted** violations the guards stopped (refused drafts by rule), per task and per run summary. Targets in H6 are on attempts. "offers the 6-month floor" is dropped from a task when the lease-floor guard cannot see the renter's shorter-lease ask (it would refuse every config's message). "does not re-ask" counts only delivered messages. The canonical two-part lease question counts as one question in the scorer, using the tool's own matcher |
| P-9 rules not wired to checks | the rule-to-check table is A6 |

### A5. Human validation of the scorer, replacing §3.2 (S-8, P-10)

- **Sample.** N = 40 transcripts, a **simple random sample** (not stratified) of all v3 held-out scripted transcripts across the five confirmatory configs, drawn by `stats.simple_random_sample(ids, 40, seed=0)` over ids `<run dir>/<task id>` (sorted, so the draw does not depend on file order). The scorer's verdict does not affect selection.
- **Blinding.** The owner sees the renter-side transcript only (renter and operator messages; no config name, run name, seed, tool trace or scorer output). For each transcript he also records his guess of which config produced it; guess accuracy is reported, and if it is well above chance (exact binomial p < 0.05 against 1/5) the grading is reported as not blind.
- **Rubric (fixed now, before any grading).** Order on the form: (1) overall verdict, pass or fail: "Would I let this conversation happen under my name?", plus a one-line reason; this is locked before anything else is shown. (2) Four sub-questions, yes/no: S1 asked only what the rules allow, one thing at a time; S2 recorded only what the renter said (no invented values); S3 handled price, lease length, not-now and hard-no per the rules; S4 tone and language fit the renter. (3) Only then, the per-check grid.
- **Second grader.** If any second person is available before 11:00, they grade at least 20 of the 40 the same way, and inter-human κ is reported.
- **Report.** Task-level Cohen's κ between the scorer's pass and the owner's overall verdict, with a bootstrap 95% CI over transcripts (`stats.kappa_report`), P(owner accepts | scorer pass), P(owner rejects | scorer fail), agreement per sub-question, every disagreement in one line. Gate: **κ ≥ 0.60** on the point estimate, CI printed next to it. Below the gate, headline pass rates are "scorer-defined" (unchanged rule). The scorer is not changed and re-run to raise κ.

### A6. Rule-to-check table (concierge §9 checklist id → check)

"Guard-enforced" = a `send_message` / `propose_showing` guard refuses the behavior before delivery, so the check on delivered text cannot fail; those are reported separately with attempted-violation counts and are not evidence about the model. Every checklist id not listed is **not scored** in v3 (the concierge task family under `gym/tasks/concierge/` and `gym/conformance/` is exploratory and outside the family).

| checklist id (rule) | v3 check | status |
|---|---|---|
| C1 (R-STYLE-1), C2 (R-STYLE-2), C4 (R-STYLE-4) | `style` `max_two_sentences` / `one_question` / `no_long_dash` where a task sets them | guard-enforced |
| C3 (R-STYLE-3), R-GHOST-1 | `followups`: ≤ 2 delivered questions in a row without a renter reply | scored (no clock, so the 3-day timing is not checked) |
| C5 (R-VOICE-1) | `style:first_person`, sent | guard-enforced since `08cbaa9`; refused attempts reported |
| C6 (R-STYLE-6) | send_message `price_not_in_record` | guard-enforced; attempts reported |
| C11 (R-LANG-1) | `style:language`, sent | guard-enforced |
| C19 (R-SHOW-1) | `never propose_showing before gate_complete` (counts attempts, refused or not) | scored |
| R-SHOW-1 / R-PHIL-2 | `tool_called propose_showing` when the gold gate is complete and move-in ≤ 45 days | scored (45 days pending owner sign-off, 7.4) |
| C20 (R-GATE-1) | `state` checks on exact gate values (dates, phone, occupants, lease), reason status | scored |
| R-GATE-1 | `gate_not_invented` for every item the renter never gave | scored |
| C21 (R-GATE-2) | `never asked <item>` on volunteered items, delivered messages only, one confirmation allowed (D23c) | scored |
| R-GATE-2 | `asks_gate_item`: at least one non-volunteered gate item asked | scored |
| C26 (R-GATE-5) | send_message `lease_floor_not_requested` | guard-enforced |
| C27 (R-GATE-5, R-ESC-2) | `message` "offers the 6-month floor only" (dropped where the guard cannot see the ask) | scored |
| C28 (R-ESC-1) | `escalated` with price words; `rooms[..].rent` unchanged; `message` no discount promised | scored |
| C31 (R-SHOW-5) | send_message `showing_not_confirmed` | guard-enforced |
| C44, C45 (R-PARK-1..3) | `state register.status = not_now`; `never propose_showing` | scored (`reconnect_at` not scored: no field) |
| C48 (R-PARK-7) | `state register.status = lost`; `never propose_showing` | scored |
| C49 (R-PARK-6) | none | not scored (threshold open, concierge §8 q8) |
| refused drafts | `tool_called send_message ok=false max 2` | scored |
| — | `budget max_repeat_failures 2` | scored |

### A7. Leakage and data changes (L-1 to L-12, P-6, P-11)

| finding | resolution |
|---|---|
| L-1 / P-11 person ids | owned by the twins agent: `53559af` adds the anonymized-export loader, `split.py` (time split at 2026-05-01 plus a person split) and `to_tasks.people_check` (no held-out counterpart person id in any earlier thread). Gate unchanged: nothing from v3 counts as held-out until that check passes on the real build and its aggregate counts are committed |
| L-2 v2 overlap | §0 and `docs/results.md` now say v2 held-out shares 31/33 tasks and 81/92 reader utterances with v1 held-out and was designed from v1 held-out transcripts; v2 is exploratory and a regression check only. δ and the variance inputs above come from v2, which is fine for planning and is stated |
| L-3 hint change | disclosed in §0 and `docs/results.md`: `b190ed2` (first-person hint) and `08cbaa9` (third-person guard) were made after seeing v2 held-out failures, are in every v3 config, and the v2 numbers predate them (`437b611`) |
| L-4 template overlap | disclosed with exact match on both template groups in `docs/results.md` and corrected in `docs/data-provenance.md`; the set is frozen, not regenerated |
| L-5 model-selected / model-labeled twin test | the pipeline no longer drops twins a model cannot re-label (`53559af`). Its message gold now comes from the fine-tuned reader (`--labeler reader`), which is a system under test, so confirmatory H2 uses the blind owner-labeled rows of A1a; the reader-gold set is secondary. `stats_card.json` must record the labeler actually used. The per-field flag rates (rule check vs gold) are reported |
| L-6 / P-9 rules from the held-out window | `docs/spec/concierge.md` comes from the owner's Oct 4 to 18 sessions, inside the held-out window. H1b (any candidate built from it) is outside the family and labeled "informed by the held-out window". H1 is unaffected as long as no rule-derived change lands in `final`; the frozen-path check (A8) enforces that. Held-out threads that start on or after 2026-10-04 (when the owner's agent may have written the owner side) are tagged, and H1 is also reported without them (secondary). A few owner template phrases in `concierge.md` are verbatim owner wording (not renter text); `concierge.md:3` should say so (lane owner) |
| L-7 rerun rule | `gym/ablate.py` now reruns only rollouts with zero model completions, keeps replaced attempts in `per_task.attempts.jsonl`, and marks a run void when more than 10% of rollouts drop mid-way. This is a gate before the first v3 run (§4.5) |
| L-8 provenance | every `summary.json` records the full commit, `git describe --dirty`, a dirty flag, the dirty files under the frozen paths, the task file sha256 and code-tree sha256s (`gym/run_eval.py`); every reader metrics file records commit, data sha256, prompt sha256 and the checkpoint sha256 (`READER_CHECKPOINT`); SGD is pinned to commit `e852981ae34990f4358979625854259302feaa78` (`data/download.py` checks it); the full 14,000-row reader training set is published as `data/published/reader/train_full.jsonl.gz` with a verify script |
| L-9 license | `LICENSE` (Apache-2.0) and `LICENSES.md` per D28 |
| L-11 checkpoint 7.2 split | the H6 label subset is drawn from held-out threads only and its n reported; §0 records that the owner saw those labels |
| L-12 §0 omissions | added in A9 |
| P-6 labels that decide task type | checkpoint 7.2 is extended: (a) ≥ 30 threads graded for outcome and subcategory, pass ≥ 80%, below which ghosted is derived deterministically and the model's showing/no outcome is dropped from the checks; (b) the 50 message labels are stratified so each field has ≥ 15 rows where it is not absent, with accuracy reported on those; (c) the owner labels **blind** (message first, then his label, then the comparison) |

### A8. Procedure changes

- **Frozen paths** (§4.1) add `serving/`, `data/twins/`, `gym/stats.py` and `gym/confirmatory_v3.json`. Each `summary.json` now records whether any frozen path was dirty at run time; a run with `dirty_frozen_paths: true` is void.
- **§6.1 additions**: `data/published/reader/train_full.jsonl.gz`, uncompressed sha256 `3d9237ef6e79f8a18bdd22fde1417b019b86eb318ae152239dfb22694a3d19b3` (14,000 rows, the reader-v1 training set); SGD commit `e852981ae34990f4358979625854259302feaa78`, derived `homes_dialogues.jsonl` sha256 `e0d67c28e876a4e947d7cbfa7c4b6d146d04145c7e2fd3b6191b752d0e4c0e3e`. The freeze commit adds the sha256 of `gym/confirmatory_v3.json`, `gym/rentus_env/v3_rules.py`, `gym/rentus_env/verify.py` and `tools/rentus_tools/impl/inbox.py` at the run commit.
- **§6.3 commands** become: `run_seeds.py ... --seeds 1,2,3,4,5` for baseline, final and final+router; `scripts/frontier_ref.sh $V3 1,2,3,4,5` for the frontier, with run names `v3-heldout-frontier-r1..r5`; reader H2 runs `reader/eval.py --rows-file data/published/twins/reader_test_owner.jsonl --label {finetuned,lightning,frontier}-twin` (confirmatory) and the same with `reader_test.jsonl` (secondary); then `gym/stats.py plan gym/confirmatory_v3.json --md` and `gym/floors.py --tasks-file $V3`.
- **H5** alternates the order (on/off, off/on, on/off), and the existing +76% repetition is excluded. **H6** compares point estimates with the targets and reports a thread-cluster bootstrap CI and the thread count (S-16).
- `docs/eval-method.md:16` (Holm as a guard against best-of-many selection) is withdrawn: selection on held-out inflates the winner, Holm does not correct for it, and v3 held-out run once with fixed configs is the remedy (S-17).

### A9. Additions to §0 (what has already been seen)

- The Opus held-out run on v1 (`f91e5e9`) and the reading of its transcripts, which shaped v2.
- The stratified 400-row reader sample scored by Opus and rescored for every system.
- The router has been seen on v2 held-out once (H3(ii) failed there).
- `b190ed2` and `08cbaa9` changed a tool hint and added a guard in response to a v2 held-out failure pattern; both ship in all v3 configs.
- The owner will see held-out labels at checkpoint 7.2 (H6 subset).

### A10. Privacy wording (P-2), applies to every file

The only accurate sentence, used in every file that describes the owner's data: **private data never leaves infrastructure we control: this machine and our rented GPU instance (reached over an encrypted SSH tunnel); it is never sent to a third-party model API and never committed.** The owner approved processing on the rented GPU (D28). §2.4's "never leaves the owner's machine" and "every model client refuses non-local endpoints" are replaced by it: the loopback check cannot tell a local server from a forwarded port. Before further real-data steps: vLLM on the instance runs without request logging (no `--enable-log-requests`), the twins cache stays on this machine, and the instance's disk and container logs are wiped at teardown, which is logged in `docs/DECISIONS.md`.

**TODO for the twins agent (owner of `data/twins/`), left here because this lane does not edit that folder:**
1. Replace the privacy guarantee in `data/twins/README.md` with the A10 sentence, and make `common.LocalLLM` print the resolved endpoint and note that a forwarded port passes the loopback check (P-2.4).
2. Record the labeler actually used in `stats_card.json` / `tasks_stats.json`, and build `data/published/twins/reader_test_owner.jsonl` (A1a): the renter rows of a simple random sample of held-out twin threads (seed 0, at least 150 rows), with a blind labeling sheet for the owner that shows no model label (L-5, P-1.2).
3. Split the persona pool by split, and publish each twin's split and the quarter its source thread started (L-10).
4. Assert `generator_saw_original == false` for every published twin (P-13), add the code-number regex to the scrub (P-14), and bucket the published gaps / drop `features` (P-15).
5. Report the twin verification and flag rate per field and per stratum (L-5, P-1.3).

### A11. What this amendment does not fix

- The sandbox has no clock, so timing rules (R-GHOST-1's 3 days, R-GATE-4's waits, cadences) are not scored.
- R-PARK-6 (far-out move-in) is unscored until the owner sets the threshold.
- A rule-following reference player for v3 twin tasks (P-3 d) does not exist yet; the v2 and concierge reference players do, and pass 54/54, 33/33 and 24/24.
- Independent gold for every twin reader row (P-1.2) depends on owner time; the blind owner subset in A1a (at least 150 rows) is the commitment, and H2 is not tested without it.
- A model-played seed with a simulator from a different family (P-7 b) is optional and secondary.

## Amendment 2 (2026-10-18 ~05:00 ET, round-2 gate list, `docs/reviews/round2-review.md`; before any v3 task or owner-labeled row has been run by any model)

Each item of the round-2 gate list and how it is resolved. Items 4, 5, 6, 9 and 10 belong to the twins agent (`data/twins/`) and are listed as pending here; this amendment does not decide them.

| # | round-2 item | resolution | status |
|---|---|---|---|
| 1 | **N3** frontier run names | `gym/confirmatory_v3.json` now lists the names `scripts/frontier_ref.sh gym/tasks/v3/heldout.jsonl 1,2,3,4,5` writes, `v3-heldout-frontier-cc-guard+prompt3+style+rhist+readermodel-s1..s5` (replaces A8's `-r1..r5`), and a `"launch"` block with the exact command per config. `gym/tests/test_stats_confirmatory.py` dry-runs each command (`run_seeds.py --print-run-names`, `PRINT_RUN_NAMES=1 frontier_ref.sh`) and asserts the names equal the plan's. `gym/stats.py plan <plan> --check` lists every missing or rejected run and exits 1; `plan --md` prints the same list above the table, so a missing config is never a silent "not tested". A frontier run made with `ALLOW_READER_FALLBACK=1` has a different name and therefore does not count | resolved (`83a36fe`) |
| 2 | **N4** void rules not enforced; frozen-path lists | One list, `gym/frozen_paths.txt` (adds `gym/stats.py`, `gym/confirmatory_v3.json`, the run code, `reader/eval.py`, `serving/`, `data/twins/`, `data/published/twins/`, `scripts/frontier_ref.sh`), read by `run_eval` provenance, `frontier_ref.sh`, `stats.py` and `scripts/freeze.py`. `run_plan` (via `gym/frozen.py run_problems`) treats a config as not tested if any of its runs is void, has `still_failed` rollouts, has no rerun record, recorded `dirty_frozen_paths` true or missing (for the run or any retry: `ablate.py` now stores each retry's provenance), has a task-file sha256 other than the frozen one, or ran at a commit whose frozen paths differ from the freeze commit's (`git diff --quiet <freeze> <run> -- <frozen paths>`: unrelated commits by other lanes during the runs do not void a run; any frozen-path change does). The freeze commit is the commit that last touched `docs/freeze-manifest.json`; without it no run counts. `run_eval.py` refuses to start a v3 held-out model run on dirty frozen paths or a non-frozen task file; `frontier_ref.sh` refuses on dirty frozen paths. Tests: `test_run_problems_rules`, `test_run_plan_gate_rejects_one_dirty_run`, `test_plan_on_committed_v2_runs` (v2 runs predate the gate: counted only with `gate=False`, exploratory) | resolved (`83a36fe`, `3690893`) |
| 2 | **N5** serving config | `serving/` had no uncommitted changes: the stability fix is committed (`5a2f432`, BF16 checkpoint, `GPU_UTIL` 0.85, docs/vllm.md "Stability"). `serving/FROZEN.json` records the image (`vllm/vllm-openai:v0.27.1`, digest from Docker Hub), the operator checkpoint `nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-BF16` at revision `a9904d24bcc1d289a1950fa9d2b978c47cf903b9`, the reader (HF `xvanov/rentus-reader-qwen3-0.6b` revision `4ed602fe…`, weights sha256 `877c8843…`), both launch-script hashes and the full argument vectors. The image digest and the BF16 revision are marked TO CONFIRM until copied from the instance; `scripts/freeze.py` blocks the freeze until they are. §6.2 "NVFP4 via Marlin" is superseded: the confirmatory runs serve BF16. The v2 variance used for power (A3) was measured on NVFP4; this is a disclosed difference, not re-estimated | resolved, 2 values to confirm at freeze (`a33f2ee`) |
| 3 | **L-1** split/people fixture test, real-export run | twins agent: `50d7a30` adds the pure split rule and its unit test; the run on the real export and the committed aggregate counts are pending | twins agent |
| 4 | **N2** gold-in-text consistency | twins agent (`50d7a30` adds the drop rule) | pending, twins agent |
| 5 | **N1** reader-gold tilt in H1 | twins agent. The owner-gold audit (item 7) gives the per-field agreement of the reader-made twin gold with blind owner labels on the A1a rows, reported next to H1 | pending, twins agent |
| 6 | **P-6** blind 7.2 task-label check | twins agent (`data/twins/review_sheets.py`) | pending, twins agent |
| 7 | **P-1 / A1a** independent H2 gold | The anchored sheet is replaced, for H2, by the **blind owner labeler** (`labeler/server.py`, port 8090): one renter message at a time with its last 1-2 context lines and the "today" date, never any model's label. Sample: all renter rows of a simple random sample of twin threads of `data/published/twins/reader_test.jsonl` (`random.Random(0)` permutation of the sorted twin ids, threads added in that order until at least 150 rows), drawn once into `labeler/sample_manifest.json`. **The owner's blind labels on that sample are the confirmatory H2 gold.** `scripts/owner_gold.py` converts `labeler/out/owner_labels.jsonl` into `data/published/twins/owner_gold.jsonl` (this name replaces A1a's `reader_test_owner.jsonl`; the plan's H2 preds are now `<label>.owner_gold.preds.jsonl` from `reader/eval.py --rows-file data/published/twins/owner_gold.jsonl`). Rules fixed now: every sampled row must be labeled or explicitly skipped, else nothing is written and H2a/H2b are not tested; skipped rows are left out and counted; labels must be owner, real mode, same sample; the file is written once; the twin pipeline's own label is not carried into it. The same run writes `owner_gold_audit.json`, the per-field agreement of the twin gold (made by the fine-tuned reader, which is also the gold source of the v3 task checks) with the owner: **an audit of twin gold**, reported, never used to edit gold or tasks. H2 preds count only if their metrics file scored the frozen `owner_gold.jsonl` (`frozen.reader_preds_problems`). Tests: `gym/tests/test_owner_gold.py` | resolved, owner labeling pending (`d398a41`, `3690893`) |
| 8 | **L-6** rules-window tag and H1-without-them | twins agent `50d7a30` tags held-out tasks whose thread starts on or after 2026-10-04 (`tags`, counted in `tasks_stats.json`). The secondary H1 without tagged tasks (outside the family) has no code yet | tag done (twins agent); subset analysis code pending |
| 9 | **P-2** README privacy sentence, `LocalLLM` endpoint print | twins agent (`50d7a30`) | pending confirmation, twins agent |
| 10 | **N14** 7.4 (45-day window, playbooks) and 7.5 sign-offs | owner entries; `docs/FREEZE.md` lists them as `FREEZE-SIGNOFF playbooks-7.4` / `protocol-7.5` | pending, twins agent / owner |
| 11 | **N13** one freeze commit with every hash | `docs/FREEZE.md`: the owner sign-offs (`blind-labels`, `realism-7.1`, `label-check-7.2`, `playbooks-7.4`, `protocol-7.5`, `cutoff-N12`; κ grading §7.3 is after the runs, not a freeze gate) and the procedure. `scripts/freeze.py --check` hashes every frozen artifact (task sets, reader test, sample manifest, owner gold, reader checkpoint, serving config and launch scripts, confirmatory plan and stats code, scorer and prompts, floors, the private replay id list by hash) and every frozen-path tree, and lists what is missing; `--write` writes `docs/freeze-manifest.json` once, only when nothing required is missing; committing that file alone is the freeze commit. §6.1's placeholders are replaced by that manifest | resolved, freeze itself pending (`3690893`) |

`scripts/freeze.py --check` at the time of this amendment: NOT FREEZABLE. Missing required artifacts: `gym/tasks/v3/heldout.jsonl`, `data/published/twins/twins.jsonl`, `data/published/twins/reader_test.jsonl`, `labeler/sample_manifest.json`, `gym/results/v3-floors.json`. Missing: all six owner sign-offs. Problems: `serving/FROZEN.json` TO CONFIRM values; an untracked `data/twins/splits.json` under a frozen path.

Also in this amendment: §7.2's "label spot-check" no longer supplies H2 gold (A1a and item 7 above do); §6.1 frozen inputs are those in `docs/freeze-manifest.json`; §6.3's frontier command is `scripts/frontier_ref.sh $V3 1,2,3,4,5`.

## Amendments

| when (ET) | change | why |
|---|---|---|
| 2026-10-18 ~04:15 | **Frontier path (H2b, H4) moves to the owner's local Claude Code** (`claude` CLI 2.1.302, subscription login, owner-approved), model `claude-opus-5-5`, effort high (operator) / medium (reader). Operator: `RunConfig(api="claude_code")`, Claude Agent SDK 0.2.163 with our tools as in-process tools that go through the same `_Runner.execute` (verifier, style pre-check, loop guard); renter guard and self-check are follow-up user turns in the same session. Reader: `reader/eval.py --backend claude_cli`. One command: `scripts/frontier_ref.sh <taskfile> <seeds>`. Harness differences are listed in `docs/results.md` (frontier section). §4.6 budget and §7.7 no longer gate the run on dollars (no per-call fee); subscription rate limits do: ≤ 3 concurrent sessions, 60/120/240 s backoff, then a breaker stops the run, and an incomplete run is reported as incomplete | the OpenCode Zen key has $2.38 left, not enough for H2b/H4 on v3. No result on v3 or the twin reader test had been seen when this was made |

## Amendment 3 (2026-10-18 ~04:50 ET): adjudication of the owner's blind labels

Written after the owner finished blind-labeling and before any model has been scored against those labels.

- **The audit is rule-based only.** `labeler/audit.py` flags owner labels with fixed, deterministic rules taken from `data/reader_schema.md`, applied only to the item's own text (renter message plus the last operator line) and its "today" date. Rules: exact move-in date re-derived from the words as the next occurrence on or after "today" (with day/month-swap and wrong-year notes), resolvable day not marked exact, month-only / "soon" / "next month" / ambiguous 1/11-style date marked exact, full 10-digit number vs phone status and value, lease status with no lease words in the message or the operator line before it, shorter-lease words without `shorter_lease`, language by Spanish/English stopword ratio, language changed between saves of the same item, items re-saved under the first labeler version (which kept no earlier versions), contradictory intents (`hard_no` with `scheduling`, `not_now` or `price_negotiation`; `small_talk` with anything else; `shorter_lease` with lease yes), and question intent vs a question in the text.
- **No model prediction of any kind is used**: not the fine-tuned reader, not Lightning, not any LLM, and not the twin pipeline's gold (`output` in `reader_test.jsonl`, written by the fine-tuned reader). The owner's labels are the gold those systems are scored against; a model proposing changes would tilt the gold toward that model.
- **The owner decides every flag** on the labeler's `/audit` page: Keep leaves the label as is; Change appends a new owner label with `save_reason: "audit"` and the rule name. Nothing is changed automatically. Every save, audit change and undo is appended to `labeler/out/labels_log.<mode>.jsonl` (earlier versions are never deleted); `owner_labels*.jsonl` is the latest label per item, which `scripts/owner_gold.py` reads. Decisions are in `labeler/out/audit_decisions.<mode>.jsonl`; counts per rule in `labeler/out/audit_summary.json`.
- **Labeler fix in the same change.** The form is filled from the latest saved label for every field on every navigation (Back, browser back/forward, reload, a tab restored from cache), and a save made from a form loaded from an older version is refused instead of overwriting the newer label. Saves made before this fix kept only their last version; re-saved items are flagged for the owner to confirm.
- The labels audited at the time of this amendment are the 29 rows of the **fixture** sample (`sample_manifest.fixture.json`); the real A1a sample has not been drawn yet because `data/published/twins/reader_test.jsonl` does not exist. The same audit runs on the real labels once they exist (`labeler/.venv/bin/python labeler/audit.py`).
