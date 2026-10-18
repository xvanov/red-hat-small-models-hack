# Scorer validity and privacy review of the eval protocol

Reviewer: adversarial scorer-validity and privacy pass, 2026-10-18. Reviewed `docs/eval-protocol.md` (as of `fa319c1`) against `gym/rentus_env/` (`verify.py`, `counterparts.py`, `llm_renter.py`, `session.py`), `tools/rentus_tools/impl/` (`inbox.py`, `register.py`), `data/twins/` (all steps), `reader/eval.py` + `reader/prompt.py`, `docs/task-review.md`, `docs/task-v2-changes.md`, `docs/spec/concierge.md`, `docs/vllm.md`. Evidence from data uses only the committed **fake** fixture (`data/twins/fixtures/out/published/`). No private data was opened or copied. No protocol or code was edited.

The statistics side (Holm, non-inferiority, κ arithmetic) is covered by `docs/reviews/stats-review.md`; this review cross-references it and does not repeat it.

Severity: **Blocker** = the claim it supports cannot be trusted as written; fix before the freeze. **Major** = a judge would discount the number; fix before the freeze or pre-register the limitation with a reported sensitivity analysis. **Minor** = amend or note.

## Findings

### 1. Blocker: H2's primary metric partly measures agreement with Lightning's own wording, on a test set filtered until Lightning reads it correctly

Evidence:
- `reader/eval.py:score` counts a row as exact only if every field's value matches, and `_norm_val("reason")` compares the reason as a lowercased free-text string. The schema asks for "a short normalized phrase", so it is free text.
- For twins, gold `reason.value` is Lightning's own re-label of the twin text (`twin.py:gold_of`, and `filter.py` overwrites it again after a rewrite). Gold `move_in.raw` comes from the same source.
- The twin writer's output is re-labeled by Lightning (reasoning on) and **rewritten until Lightning's labels equal the spec** (`twin.py:make_twin`, up to 3 rounds). Twins that never match are dropped (`filter.py`, "dropped_unverified_labels"). So every row in the twin reader test is one that Lightning-with-reasoning already reads "correctly", by construction.

Consequences: H2a (reader vs Lightning, thinking off) is scored against gold written by the same model with the same prompt. Any reason row with a concrete reason is close to free for Lightning and close to impossible for a model that phrases it differently: the fine-tuned reader learned template-style reasons from `data/published/reader/train.jsonl`, and Opus has its own phrasing. H2b (reader vs Opus) then mostly measures which model's wording is closer to Lightning's. §8.1 notes the circularity but proposes the 7.2 spot-check as the fix, and 7.2 checks labels of **real** messages. Twin gold is the *spec*, verified by Lightning. Whether the real label was right does not change whether the twin row's gold is right (see also finding 6).

Fix (pre-register before the freeze):
1. Primary H2 exact match = all statuses + lease/move-in date/phone/occupants values + intents + language, with **`reason` scored on status only**. Report the reason-value match only as a secondary metric, judged by a fixed normalizer or by a human.
2. Independent gold for the twin reader test. Twins are synthetic and publishable, so a second labeler is allowed: either (a) the owner or any second person labels ≥ 150 twin rows **blind** (without seeing Lightning's label), or (b) Opus labels every twin row and disagreements with Lightning gold are adjudicated by a human. Report H2 on the adjudicated subset.
3. Report H2 separately on rows that passed verification on the first draft and rows that needed repair. Repaired rows are where the Lightning filter acted hardest.

### 2. Blocker: the privacy guarantee "real text never leaves the machine" is false as implemented

Evidence: `data/twins/README.md` (guarantee 2) and protocol §2.4 say every model client refuses non-local endpoints, so real text never leaves the owner's machine. But `common.LocalLLM._is_local_host` only checks the hostname. `docs/vllm.md` lines 12 to 15 and `serving/tunnel.sh` show that `localhost:8000` / `:8001` are **SSH tunnels to a rented Brev cloud instance**. Labeling (`label.py`), twin verification, the privacy-filter rewrites and the H6 replay all send the owner's real (anonymized) threads to a third-party GPU host. `TWINS_EXTRA_LOCAL_HOSTS` can also whitelist any host by name. The guard passes and the claim is wrong. A judge who reads `vllm.md` next to the README will find the contradiction.

Fix:
1. Restate the guarantee accurately everywhere it appears (README, §2.4, §0, data-provenance): "real text is processed only on the owner's laptop and on one single-tenant rented GPU instance reached over SSH, where vLLM binds to 127.0.0.1. Nothing goes to a hosted model API. The instance is deleted after submission."
2. Record the owner's explicit consent to that processing in `docs/DECISIONS.md` before any further real-data step.
3. Check that vLLM 0.27.1 on the instance does not log request bodies (no `--enable-log-requests`, no prompt logging in `docker logs`). Check that the twins cache (`work/cache/`) lives only on the laptop. Wipe the instance's disk and container logs at teardown, and log that it was done.
4. Make `LocalLLM` print the resolved endpoint and require an explicit `TWINS_REMOTE_GPU_ACK=1` when the endpoint is a forwarded port. At minimum, document that the loopback check cannot detect a tunnel.

### 3. Major: checks and scripted renters encode the owner's PAST behavior, which contradicts §3.3

§3.3 says correct agent behavior comes from the current rules, not from what the owner did. `data/twins/to_tasks.py` does the opposite in three places:
- **"showing proposed"** is checked only `if gate_complete and oc.get("showing")`, that is, only when the historical thread reached a showing. If the gate is complete but the historical owner never proposed a showing, nothing is checked. The concierge spec (R-PARK-6) says a fully qualified renter with a far-out move-in should be parked, *not* shown, and the check ignores that.
- **"does not spam a silent renter"** allows `n_owner + 2` sends, where `n_owner` is how many messages the historical owner sent. The current rule is R-GHOST-1: one close message after about 3 days, and the sandbox has no clock (`docs/spec/gap-analysis.md` #8).
- **Scripted renter lines are keyed to the historical owner's questions.** `script_of` tags each renter block with the items the *historical* owner asked just before it. The renter's hard-no or not-now line is then said only if the operator asks that same item. Fixture evidence (`twin_hard_no`): the hard-no line is `when_asked: "move_in"` because the historical owner asked the move-in date. The task is `ends_silent`, so it has no generic fallback. An operator that answers the renter's bus question and asks about the lease first (allowed by the rules) gets silence forever and cannot pass "closed as not interested". The same shape appears in `twin_not_now` (not-now line keyed to `move_in`).

Why it matters: the v3 headline number partly rewards copying the owner's historical question order and outcome, which is exactly what §3.3 promises not to do.

Fix: (a) Lines that carry a non-gate behavior (hard_no, not_now, price_negotiation, question, small_talk) answer the **next** operator message whatever it asks. Gate-item lines are keyed to the renter's own label items, not to the historical owner's acts. (b) Derive "showing proposed" from the rules: gate complete and move-in within N days means propose; far-out means park, per R-PARK-6. (c) Replace the spam cap with the rule (at most 1 follow-up after an unanswered question) or drop it until the sandbox has a clock. (d) Add a test that a rule-following reference player (one that asks gate items in a fixed canonical order, not the historical order) reaches 100% on v3, the way `oracle.py` does for v2.

### 4. Major: some v3 tasks are passed by a trivial agent

On the fixture, a static count of which checks a "send one greeting in the renter's language, do nothing else" agent passes:

| fixture task | checks | do-nothing | one greeting | greeting passes the whole task |
|---|---|---|---|---|
| twin_ghosted | 6 | 0.67 | **1.00** | **yes** |
| twin_hard_no | 6 | 0.50 | 0.83 | add `status=lost` and yes |
| twin_price_push | 9 | 0.67 | 0.89 | add any escalation and yes |

Ghosted threads (the renter goes silent) are common in real traffic. When the renter gave no gate items, the only checks left are `never`, `budget`, refused-drafts `max`, spam `max` and the two style rules. The price-push escalation check has no keywords, so "escalate everything" passes it. The v2 floor of 0.291 quoted in §3.1 and §8.6 does not describe v3.

Fix: before the freeze, compute and pre-register the v3 floors for four trivial agents: do-nothing, greet-only, escalate-every-message, and mark-every-renter-lost/not_now. Require every task to have at least one check a trivial agent fails (a state value, a required tool call, or a required message). Otherwise drop the task or flag it, and report pass rate both with and without flagged tasks. Give the price-push escalation `reason_any` keywords (price, discount, rent, precio).

### 5. Major: invented gate values are rewarded

`upsert_renter` (`tools/rentus_tools/impl/register.py`) accepts any gate value with no evidence. `to_tasks.checks_of` writes state checks only for items the twin renter actually gave. "Gate before showing" reads `gate_before`, which is the world's register state (`session.py:114`). So an operator can invent `occupants: 1` or `reason: "new job"` for a renter who never said them, complete the gate, propose a showing, and pass "gate before showing". No check fails. That is exactly the behavior the gate exists to prevent, and the concierge spec says "all five gate items exact".

Fix: for every item that is absent from `final_gate(twin)`, add `{"type":"state","path":"register[t].gate.<item>.status","in":["absent","vague","no"]}`. Better still, add a "grounded" check: every recorded phone, date or occupants value must appear in, or resolve from, a renter message on that thread.

### 6. Major: the labels that decide task type and checks are the least checked

Thread-level outcome labels (ghosted / showing / no) and the `not_now` / `hard_no` intents decide each task's subcategory and several checks (findings 3 and 4). An earlier exploration found the Lightning thread-level labels unreliable (for example, zero no-shows detected). Checkpoint 7.2 checks only renter-message fields (lease, move-in, phone, occupants, reason), and checks them on a sample where "absent" dominates. Most messages leave most fields absent, so ≥ 90% per field can be reached mostly from absent-equals-absent rows.

Fix: (a) Extend 7.2 to ≥ 30 threads graded for outcome and subcategory, with a pass threshold. Below it, derive ghosted deterministically (`features.renter_went_silent` already exists) and drop the model's showing / no outcome from the checks. (b) Stratify the 50 message labels so that each field has ≥ 15 rows where it is *not* absent, and report accuracy on those. (c) The owner grades blind: show the message and ask for the label, then compare. Showing Lightning's label first anchors him toward accepting it. (d) The README's "fine-tuned reader as labeler: 19/42" is agreement *with Lightning*, not accuracy. Before ruling out the reader as a labeler, compare both against the owner's blind labels on the same 50 rows.

### 7. Major: the model-played renter does not implement the twin plan, and it is a maximally cooperative partner from the same model family

Evidence:
- `to_tasks.py` writes `twin_script` and a `deviation_policy` ("follow twin_script in order..."), but **no code reads them**. A grep of `gym/` finds no use. `llm_renter.py` uses only `opening`, `truth`, `behaviors` and `persona`.
- The truth sheet has no not-now, hard-no, factual question or language switch. In model-played mode, a `twin_not_now` or `twin_hard_no` renter never says it, so "kept on file as not now" and "closed as not interested" can only pass if the operator invents the status.
- A price push that came mid-thread is not in `opening`. The prompt says "You already asked about a discount" but the renter never actually asks (fixture `twin_price_push`: the ask is renter turn 3, `opening` holds only turn 1). The escalation check then rewards an operator that escalates without being asked.
- Collusion and ease: the renter prompt says to accept any proposed showing, confirm correct read-backs, answer whatever is asked, and never refuse. Director notes fire only when the operator's text hits the same keyword classifier the scorer uses (`classify_question`). Lightning plays both sides at temperature 0. §8.15 names the risk but has no measurement.

Fix: (a) Inject non-gate behaviors from `twin_script` verbatim at their turn: the renter says the twin's not-now, hard-no, price or question line as its next reply after the matching operator turn. Or restrict model-played results to the subcategories it supports and say so. (b) Run at least one model-played seed with a simulator from a different family. Simulators are outside the 33B budget (organizer ruling 2026-10-17), so this is allowed. Report whether H1's direction agrees. (c) Log how often the director note fired and how often the renter used a fallback. Report per-task "renter stayed on its truth sheet" with a deterministic check of dates, phone and head count in every renter reply, not only the phone.

### 8. Major: tool guards make several "never-do" and style outcomes guaranteed, not earned

`send_message` refuses, before anything is sent: a language mismatch (`language_mismatch`); a confirmed-showing claim the owner has not confirmed (`booking_claims`); dollar figures not in the record; and the 6-to-11-month floor before the renter asked for a shorter lease (`inbox.py`). So:
- In H6, "never-do violations = 0" for unconfirmed showings, unasked floor and invented prices is guaranteed by the tools. It cannot miss, so it is not evidence about the model.
- In v3, `style:language` on sent messages fails only when the scorer's word list and the guard's detector disagree. It adds near-constant reward to every config.
- The floor guard decides "the renter asked for a shorter lease" with its own regex and the rule-based reader (`renter_asked_shorter`). A twin phrasing that Lightning labeled `shorter_lease` but the regex misses gets the operator's "6 months" message refused. "Offers the 6-month floor" then becomes impossible for every config, whichever is better.

Fix: in H6 and v3, report **attempted** violations: refused `send_message` / `propose_showing` calls broken down by `details.rules`, per config. Pre-register targets on attempts, not on what was delivered. Either take `style:language` out of reward or label it "tool-guaranteed". Before the freeze, run `renter_asked_shorter` over every v3 twin line labeled `shorter_lease` and drop or repair tasks where it returns false.

### 9. Major: §3.3's "frozen rules" are not wired to any check, and the rules come from the held-out window

- No mapping from rules to checks exists. `docs/playbooks/` does not exist. `docs/spec/concierge.md` (committed `224f6ca`) is not read by `to_tasks.py`, whose checks are hardcoded. Rules the protocol implies are scored are not checked at all: R-PARK-2/3 (ask for a timeframe, set `reconnect_at`), R-ESC-1 ("tell the prospect I will check; keep collecting the gate"), R-PARK-6 and R-GHOST-1. Approving the playbooks at 7.4 would not change any score.
- The concierge rules are distilled from the owner's Oct 4 to 18 sessions, which fall **inside** the held-out window (≥ 2026-05-01). In those sessions the owner side was partly written by his AI agent ("Muse", concierge.md line 3). So part of v3 held-out is renters reacting to an agent that already followed these rules, which is closer to the operator under test than to "real traffic". It also goes beyond §8.4's "knowledge of situation types": the rules themselves were built on held-out conversations.

Fix: commit a table (rule id → check type → task subcategories) at the freeze. Any rule without a row is "not scored". Tag held-out threads by whether the agent ran the owner side (Oct 4 onward), report H1 for each part, and add both points to §8.

### 10. Major: the human-grading design cannot support "correct behavior" claims as specified

Beyond the κ arithmetic in stats-review #8 (stratified sample, wide CI at N = 40):
- **Anchoring.** §3.2 asks for "a pass/fail per scorer check" *and* an overall verdict. If the check list is shown first, the owner is grading the scorer's own frame. Collect the overall verdict and a free-text reason first, on a form that does not show the check list. Show the per-check grid only after the verdict is locked.
- **Blinding is not tested.** Baseline (prompt v1) and final (prompt v3 + guards) differ in visible ways: the guard hint wording "I've penciled in … and will confirm it shortly", how refused drafts are retried, how much is asked per message. The near-miss stratum also tells the grader that the transcript is close to passing. Record the grader's guess of the config for each transcript and report guess accuracy. If it is well above chance, say the grading was not blind.
- **One stakeholder grader is a choice, not a constraint.** v3 transcripts are synthetic twins with fictional personas and phones, so they can be shown to a second person. Have a second grader do ≥ 20 of the 40 and report inter-human κ. That removes threat 14 rather than merely naming it.
- **The rubric is one question.** "Would I let this conversation happen under my name?" mixes rule compliance with taste. Add 3 to 4 fixed sub-questions tied to the scored constructs (asked only what the rules allow; recorded what the renter said, no invented values; handled price, lease, not-now and hard-no per the rules; tone). Report agreement per sub-question, so a disagreement can be traced to a check.
- **Report precision, not only κ.** The headline is a pass rate, so the number that matters is P(owner accepts | scorer pass) and P(owner rejects | scorer fail), with inverse-probability weights for the 15/15/10 strata.

### 11. Major: person-disjointness cannot be built from what ingest keeps

§2.2 requires that no held-out counterpart person id appears in train. But `ingest.py` drops sender names ("Sender names are never stored") and stores only salted thread hashes, so no person id exists downstream. One person who wrote on both Messenger and SMS has two unrelated thread ids. `to_tasks.py` also labels **every** twin `split: "heldout"`. The protocol admits the time split is missing; the person key is missing too, and is harder to add.

Fix: at ingest, compute a salted person hash from the stable participant key (iMazing chat session or handle, Facebook participant id) and from any normalized phone in the renter's lines (before scrubbing). Join on either. State that people who used different handles and gave no phone cannot be linked across channels.

### 12. Minor: the twin realism checkpoint (7.1) is weak

The owner will recognize his own real threads from memory, whatever the twins' quality, so identification accuracy mostly measures his memory. With n = 20, 75% (15/20) is already well above chance (one-sided binomial p ≈ 0.02). The pass condition is "accuracy ≤ 75% **or** realism ≥ 3.5", so a twin set the owner spots every time still passes on ratings alone. Fix: drop the identification part, or use it only as a description. Pass on mean twin realism ≥ 3.5 **and** no twin rated ≤ 2 for "this could not happen". If possible, a second person rates the twins only.

### 13. Minor: the twin writer's blindness is a flag, not a guarantee

`twin.py --show-original` passes the real text to the writer. The protocol does not forbid it. Fix: the freeze commit asserts `generator_saw_original == false` for every published twin, and `to_tasks.py` refuses to publish any twin where it is true.

### 14. Minor: privacy scrubbing misses several kinds of identifier

`common.scrub` / `pii_hits` cover phones, emails, URLs, street addresses, units, SSNs and cards. They do not cover lockbox, door, gate or wifi codes (bare 4 to 6 digit numbers), license plates, employer, school or business names, or Spanish street forms outside the listed words. With a blind writer, published twins can contain these only if the writer invents them, so the main exposure is real text sent to the remote GPU (finding 2). `twin.py` rule 7 forbids "a real business name" but nothing checks it. The `cos ≥ 0.90` embedding threshold is lenient for MiniLM: a close paraphrase of a distinctive real line often scores 0.75 to 0.9. Fix: add a code-number regex (`\b\d{4,6}\b` near "code / lockbox / gate / wifi / clave / código") to the real-text scrub and to `pii_hits`. Run a local NER pass (ORG / FAC) over published lines and review the hits by hand. Report the number of kept lines with cosine 0.80 to 0.90 to the nearest distinctive real line, and have the owner skim 50 random published lines before they are committed.

### 15. Minor: residual linkage in published twins

The published `twins.jsonl` keeps the real thread's turn count, act and label sequence, outcome, `features` (turn counts), and message gaps scaled by 0.8 to 1.25. `twin_id` is a salted hash of the real thread id. Outsiders cannot link these without the private data, but the owner, or anyone holding the export, could. Fix: re-scale gaps by bucket (minutes / hours / days), not by a near-1 factor, and drop `features` from the published file. The twin id should hash only within the published set, not from the real thread id.

### 16. Minor: smaller scorer issues

- `check_never` with `asked` counts refused (never delivered) drafts as asks. That breaks the G2 principle "score what the renter received". Filter on `e["ok"]`.
- v3 scripts have no reusable confirmation lines (v2 has them). An operator's D23(c) confirmation gets the generic "I think that's everything from me". It does no harm, but the protocol should say so.
- `llm_renter_fields` uses whole twin messages as `truth.reason` and `occupants_desc` (fixture: a reason that ends in a month-to-month question). That leaks other intents into the renter's persona. Use the gold value instead.
- The anonymizer-damage exclusion in §2.2 is not implemented in `data/twins` (no unscorable marking), so add it to the implementation gate.
- H6 "next-action agreement" has no judge yet. The rule table must be committed with the freeze hashes, not "before the replay".
- Twin landlord lines reproduce historical rule breaks (fixture: "i can offer $730"). This is harmless as reader context, but the published twins should be labeled as historical-style, not ideal behavior.

## Verdict

**Not ready to freeze.** The v2 machinery (scorer fixes, held-out separation, outcome-independent rerun rules) is sound. The new v3 path is not yet a valid instrument for the claims attached to it:

- H2's primary metric rewards matching Lightning's wording, on a test set Lightning filtered (finding 1).
- The headline privacy sentence is contradicted by the serving setup (finding 2).
- v3 checks and scripted renters reward the owner's past behavior (finding 3), let trivial agents pass some tasks (finding 4), and reward invented gate values (finding 5).
- The model-played renter cannot express half the behaviors it is supposed to test (finding 7).

Fix findings 1 to 7 before the hashes are frozen. Findings 8 to 11 can be handled by amendment, with the extra metrics reported. If time runs out, report v3 pass rates as "scorer-defined, on twin tasks whose checks include historical-outcome criteria", report H2 with reason scored on status only, and correct the privacy wording in every published file.
