# Statistics review of the evaluation protocol

Reviewer: adversarial statistics review, 2026-10-18. Scope: `docs/eval-protocol.md` (commit `fa319c1`), `gym/stats.py`, `gym/run_seeds.py`, `docs/eval-method.md`, `docs/results.md`. Nothing in the protocol or code was edited.

What I ran:
- `gym/.venv/bin/python -m pytest -q gym/tests/test_stats_llm_renter.py`: 12 passed. The tests cover Wilson, exact McNemar, pass^k / pass@k, Holm, summary and paired compare. Nothing tests the non-inferiority p-value, kappa, a calls-per-task comparison or row-level McNemar for the reader, because none of those exist in code.
- A re-analysis of the committed v2 runs (`gym/results/v2-heldout-{baseline,final,final-router}-s{1,2,3}`) through `stats.Config` / `stats.compare`, to check the SDs the protocol's power table uses and to split variance into the part that comes from tasks and the part that comes from seeds. Numbers quoted below come from that run.
- Power for non-inferiority (normal approximation) and a simulation of exact McNemar power for the reader tests.

Checked and fine (no finding): the unit of analysis is the task in every interval and test, and seeds are averaged within a task before resampling (`stats.py:163-164`, `193-195`), so there is no pseudo-replication across seeds in the agent tests. The Wilson interval on a fractional mean pass rate with n = tasks is valid and conservative, because a per-task pass fraction X lies in [0, 1], so Var(X) ≤ p(1 − p) (`stats.py:107-114`). pass^k = C(c,k)/C(n,k) averaged over tasks is the τ-bench estimator and is implemented correctly (`stats.py:127-129`), and so is pass@k (`132-136`). The Holm step-down is correct (`149-156`). Optional stopping is explicitly banned (`eval-protocol.md:147`). Non-significant results must be reported in the same format, with no "trend" wording (`eval-protocol.md:161`). Co-primary H3 (i) and (ii) both have to pass, which is an intersection-union test and needs no multiplicity correction. The MDE arithmetic (2.8 × SD / √n) is right for the inputs it uses, and the protocol's v2 SDs hold up: 0.232 measured for final vs baseline, and 0.114 for router vs final (the protocol says ≈ 0.13).

## Findings

### 1. Blocker: the non-inferiority decision rule is defined two incompatible ways, and no code computes it
**Evidence.** `eval-protocol.md:24-25` decides H3(ii) and H4 by "the lower bound of the 95% paired CI of Δ reward > −δ". That is a one-sided test at α = 0.025, with no multiplicity adjustment. `eval-protocol.md:29` puts H3(ii) and H4 in a Holm family at familywise α = 0.05, and `eval-protocol.md:159` defines a non-inferiority p as "the share of bootstrap Δ ≤ −δ". Applying Holm to that p means comparing it against 0.05/m … 0.05, not 0.025, so the two rules can disagree in either direction. `gym/stats.py:190-209` (`compare`) returns only a superiority p (the centred bootstrap, `stats.py:202`). It has no δ argument and no non-inferiority p. The §6.3 command (`eval-protocol.md:200-204`) therefore cannot produce the pre-registered H3(ii) / H4 decision. Whoever runs the analysis would have to improvise it after seeing the data.
**Fix (amendment before the freeze).** Pick one rule. Recommended: a one-sided non-inferiority p, p_NI = (#{bootstrap Δ* ≤ −δ} + 1)/(B + 1), computed from the same paired bootstrap, entered into Holm at one-sided α = 0.025 (or state α = 0.05 one-sided and say so). Report the Holm-consistent confidence bound next to it, which is the (1 − α_adj) lower bound for the rank at which the hypothesis was tested. Add `compare(..., delta=0.05)` returning `p_ni` and the lower bound, plus a unit test with a known answer, before the freeze.

### 2. Blocker: the primary Holm family is spread over two tools, and the committed command adjusts over the wrong set
**Evidence.** The family is H1, H2a, H2b, H3(ii), H4 (`eval-protocol.md:29`). `stats.py:263-264` applies Holm across "all comparisons in one invocation". The §6.3 stats command (`eval-protocol.md:200-204`) runs only `final:baseline` and `router:final`, so Holm runs over m = 2 and uses a superiority p for `router:final`. The frontier config and `final:frontier` are missing, and H2a/H2b come from `reader/eval.py`, which has no McNemar (a grep of `gym/`, `reader/` and `data/` finds McNemar only in `stats.py`). `md_compare` also runs two separate Holm families, one over reward p-values and one over pass p-values (`stats.py:263-264`). The protocol's family is reward only for the agent hypotheses, so the pass-test Holm column is not the pre-registered adjustment. If the reported Holm p is whatever the tool prints, it will be computed over the wrong m.
**Fix.** Before the freeze, commit a small `gym/primary_family.py` (or a `--family` flag) that takes the five pre-specified p-values (H1 superiority p on reward, the H2a/H2b exact McNemar p, the H3(ii) and H4 non-inferiority p from finding 1) and applies Holm once. It should mark untested hypotheses and drop them from m by a rule fixed now (see finding 12). Fix the §6.3 command to include the frontier config and `--compare final:frontier`. Label the pass-test Holm column in `md_compare` "exploratory".

### 3. Major: the reader McNemar treats messages as independent, but they are nested in a small number of threads
**Evidence.** H2a/H2b use "exact McNemar on per-row correctness" (`eval-protocol.md:22-23`, `159`). The twin reader test is "built only from held-out threads" (`eval-protocol.md:63`), and those are expected to be about 30 to 50 threads (`eval-protocol.md:56`). Several messages per thread share a renter, a style and anonymizer damage, so their correctness is correlated. McNemar's exactness assumes independent pairs. With clustering, the real variance is larger and the p-value is too small (false positives).
**Fix.** Make the primary H2 test a paired cluster bootstrap over threads (resample threads, recompute the exact-match difference), or a clustered McNemar (Obuchowski 1998 / Durkalski 2003). Keep row-level McNemar as a sensitivity row. Report the number of threads and the mean rows per thread.

### 4. Major: the reader tests are not "well powered for 5 points"
**Evidence.** `eval-protocol.md:43` says the H2 tests "have n in the hundreds of rows and are well powered for differences of 5 points or more". McNemar power depends on the share of rows where the two systems disagree, not just on n. In simulation (exact two-sided McNemar, true difference 5 points):

| rows | rows where they disagree | power at α 0.05 | power at α 0.01 (Holm, smallest p) |
|---|---|---|---|
| 200 | 10% | 0.53 | 0.27 |
| 300 | 10% | 0.73 | 0.51 |
| 300 | 20% | 0.42 | 0.22 |
| 500 | 20% | 0.67 | 0.44 |

That is before accounting for clustering (finding 3), which cuts the effective n further.
**Fix.** Replace the sentence with the MDE for the expected row count and disagreement rate. Estimate the disagreement rate from the synthetic test set, which is already scored for every system. State the MDE in threads if the cluster bootstrap becomes primary.

### 5. Major: δ was chosen after the relevant data were seen, and its stated justification is wrong
**Evidence.** `eval-protocol.md:17`: δ = 0.05 is "slightly above the router's measured v2 drop (0.053)". In fact 0.05 is below 0.053. The other reason, "the size of the shift one task-level flip causes on 20 to 40 tasks", is pass-rate arithmetic (1/20 = 0.05). In mean reward, one task flipping from fail to pass moves the mean by (that task's reward change)/n, which is typically 0.1/40 = 0.0025. δ was also fixed after the v1 frontier comparison was public (`eval-method.md:80`: final vs Opus +0.032, CI −0.014 to +0.081). On those numbers, H4 non-inferiority at δ = 0.05 would already pass. That is a forking path that favors H4, even though δ = 0.05 works against H3(ii). There is also a scale problem. The final config's v2 mean reward is 0.929 (`results.md:14`), so δ = 0.05 is about 70% of the remaining headroom (0.071), and a do-nothing agent scores 0.291 (`eval-protocol.md:98`). A system could lose most of what final gains in the last mile and still be "non-inferior".
**Fix.** In the amendment, correct the arithmetic and state openly that δ was set knowing v1 H4 (+0.032) and v2 H3 (−0.053). Add a second, pre-registered secondary non-inferiority on pass rate (for example δ_pass = 10 points) or on the share of headroom lost (Δ / (1 − reward_final)), so a reader can see whether reward non-inferiority hides a pass-rate collapse. Do not change δ for the primary tests now. That would be a second look.

### 6. Major: non-inferiority power is overstated; H3(ii) is a coin flip even if the router is exactly as good
**Evidence.** `eval-protocol.md:43`: "A δ of 0.05 at n ≈ 40 needs a true Δ of about ≥ −0.01." With SD 0.13 and n = 40 (SE 0.0206), a true Δ of −0.0097 gives a 50% chance that the lower bound clears −0.05. For 80% power the true Δ must be ≥ +0.008, and ≥ +0.020 at the Holm-adjusted α = 0.01 if H3(ii) ends up tested first. At n = 33 these become +0.013 and +0.027. H4 is worse: the frontier gets 1 run (`eval-protocol.md:132`), so its full seed variance enters the paired difference, where the local system's is divided by 3.
**Fix.** Restate the table as "true Δ needed for 80% power", both before and after Holm. Then apply finding 7. It is the only lever left that does not need more tasks.

### 7. Major: seed noise is not negligible, and "more tasks, not more repeats" is wrong for the close comparisons
**Evidence.** `eval-method.md:94` and `eval-protocol.md:156` treat seeds as minor noise. On the committed v2 runs, the average within-task variance of reward across the 3 seeds is 0.0064 for final and 0.0196 for router. The variance across tasks of final's per-task means is only 0.0027, and about 0.0021 of that is seed noise (0.0064/3). For router vs final, the paired-difference variance is 0.0131, and roughly 0.0087 of it (about two thirds) comes from seed noise ((0.0196 + 0.0064)/3). The small "run-to-run sd" in `eval-method.md` is the SD of the whole-run average, and it hides how much single tasks move. Fixing k = 3 (`eval-protocol.md:132`, `147`) is therefore the main thing limiting H3(ii) and H4.
**Fix.** Before the freeze (that is not optional stopping, because it is fixed before any v3 data), raise the operator seeds to k = 10 for final and final+router, and to at least 3 frontier runs if the budget allows. On v2's numbers, k = 10 brings the paired SD from 0.114 to about 0.084, which moves the 80%-power point at n = 40 from Δ ≥ +0.008 to about Δ ≥ −0.013. If the GPU time isn't there, say in the protocol that H3(ii) and H4 are underpowered by design. Also correct `eval-method.md:94`.

### 8. Major: the kappa gate is computed on an unrepresentative sample with no code behind it
**Evidence.** `eval-protocol.md:101-103` draws N = 40 as 15 scorer-pass, 15 scorer-fail and 10 near-miss (which are also scorer-fail). Cohen's κ depends on prevalence, and this design fixes the scorer's marginal at 15/25 whatever the true pass rate is. So the κ it yields does not describe agreement on the real output. At N = 40, a bootstrap 95% CI for κ near 0.6 is roughly ±0.25 wide, and the gate is on the point estimate. `stats.py` has no kappa function, even though `eval-protocol.md:162` cites one.
**Fix.** Report the owner's agreement separately within each stratum (agreement given the scorer passed, agreement given it failed), plus a κ reweighted to the observed pass rate by inverse sampling weights. Keep the 0.60 gate on the reweighted κ, and print the CI. Add `cohen_kappa` with a bootstrap over transcripts to `stats.py` with a test, before grading.

### 9. Minor: the percentile bootstrap at n ≈ 33 to 40 undercovers on skewed differences, right where the non-inferiority boundary sits
**Evidence.** `stats.py:117-124`, `198-202`. The router-minus-final per-task differences on v2 have skew −1.07. The percentile bootstrap with n = 33 tends to be too narrow, and the non-inferiority decision depends on the exact lower bound.
**Fix.** Pre-register BCa or a studentized bootstrap for the non-inferiority bound, or a paired t interval as a sensitivity row. If the methods disagree on a decision, report both, and use the more conservative one as primary.

### 10. Minor: the MDE table ignores Holm and the pass-rate column has no derivation
**Evidence.** `eval-protocol.md:33-41` uses z = 1.96 (before Holm, as labeled), but the smallest Holm p is tested at 0.01, which multiplies the MDE by about 1.22. "~20 points (sign test, rough)" has no stated discordance assumption.
**Fix.** Add the Holm-adjusted column. Derive the pass-rate MDE from the v2 discordant-task rate (for example 24 of 33 discordant for final vs baseline, 21 of 33 for router vs final).

### 11. Minor: tasks missing from some runs are dropped silently
**Evidence.** `stats.py:76-81` keeps only tasks present in every run and prints a warning to stderr. `compare` then uses the intersection (`stats.py:192`). Whether a task goes missing could depend on the outcome (crashes on long tasks).
**Fix.** Add a `--strict` flag that exits non-zero on any dropped task, and use it in the §6.3 commands. `eval-protocol.md:144` already says such runs are incomplete.

### 12. Minor: the Holm family size depends on budget and time
**Evidence.** H2b and H4 drop out if the budget isn't approved (`eval-protocol.md:29`, `153`), and incomplete hypotheses at the 08:30 freeze become "not tested" (`eval-protocol.md:149`). A smaller m makes the remaining tests easier. This is outcome-independent only if m is fixed before any primary result is seen.
**Fix.** Fix m in the freeze commit as the hypotheses whose runs are approved and scheduled. A hypothesis that later runs out of time stays in m with p = 1. That costs a little power and removes the forking path.

### 13. Minor: the sign test is mislabeled as McNemar when there are 3 seeds, and it discards magnitude
**Evidence.** `results.md:22` heads the pass column "exact McNemar", but with k = 3 the code runs a sign test on pass fractions (`stats.py:209`). A task at 2/3 vs 1/3 counts the same as 1 vs 0.
**Fix.** Relabel it in `results.md`. For the v3 secondary pass-rate test, consider a paired permutation test on per-task pass fractions, which keeps magnitude, alongside the sign test.

### 14. Minor: H3(i) (Lightning calls per task) has no implementation
**Evidence.** `eval-protocol.md:24` decides H3(i) by a paired bootstrap on calls per task. `per_task.jsonl` has `model_calls`, but `stats.py` compares only reward and pass.
**Fix.** Add a generic `--metric model_calls` paired bootstrap to `compare`, with a test, before the freeze.

### 15. Minor: pass^3 is reported but compared by nothing, and for H4 it is undefined
**Evidence.** `eval-protocol.md:21`, `158`. With k = 3, pass^3 per task is the 0/1 indicator "passed all 3", which is noisy. The frontier has 1 run, so H4 has no pass^3.
**Fix.** Keep pass^3 descriptive with its bootstrap CI (as planned), say explicitly that no claim compares pass^3 between configs, and mark it n/a for the frontier.

### 16. Minor: H5 always runs caching-on before caching-off, and H6 targets have no stated uncertainty rule
**Evidence.** `eval-protocol.md:208-210` runs `on-r$r` before `off-r$r` in every repetition, so warm-up and thermal state are confounded with the condition. It is unclear whether the existing +76% repetition counts toward "3". H6 targets (`eval-protocol.md:27`) don't say whether a point estimate or a CI bound is compared to 90%, 0.70 and 60%. Their rates are per turn, and turns are clustered within threads.
**Fix.** Alternate the order (on/off, off/on, on/off) and state that the old repetition is excluded. For H6, state "point estimate vs target, with a thread-cluster bootstrap CI reported" and give the thread count.

### 17. Minor: `eval-method.md` claims Holm protects against best-of-many selection
**Evidence.** `eval-method.md:16`: about 15 configs run on the same 31 held-out tasks, with "the Holm correction in section 4 is the guard". Holm covered the 12 comparisons reported, not the selection of the winner from every config tried. v1 is superseded, but the sentence is still in the judges' method page.
**Fix.** Reword: selection on held-out inflates the winner, Holm does not correct for it, and v3 held-out (run once, configs fixed in advance) is the remedy.

## Verdict

**Not ready.** Findings 1 and 2 mean the primary non-inferiority and Holm decisions cannot be produced by the committed code or the §6.3 command as written, so they would be improvised after the data are seen. Both can be fixed with an amendment and a small amount of code before the freeze commit. Findings 3 to 8 should go into the same amendment: clustered reader tests, an honest power statement, a corrected δ rationale, more seeds for H3/H4, and a representative kappa. With those in, the protocol is ready.
