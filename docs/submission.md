# Submission: form answers and bounty write-ups

Form: https://airtable.com/appm7NS9oN8K3friP/pagqXe6ElIlXx6oa3/form (due Sun Oct 18, 11:00 AM ET; the form takes 10 to 15 minutes, start by 10:40). Values in `{{...}}` are filled by `scripts/fill_results.py --write [--video-url URL]`; check `scripts/fill_results.py` (dry run) before pasting.

## Form answers

**Team name:** Rentus

**Project description** (about 150 words):

> Rentus Operator runs the leasing desk of a small room-rental business with small open models on one GPU, live: text (888) 891-2046, message the Rentus Homes Facebook Page, or email info@rentus.homes and it answers. NVIDIA Nemotron 3.5 Lightning on Red Hat vLLM calls 41 tools: it writes and fair-housing-checks listings, answers renters in English and Spanish from owner-confirmed facts only, qualifies each on a strict five-item gate, books showings on Google Calendar and triages repairs. Code checks every call and blocks false claims; a Qwen3-0.6B reader we fine-tuned turns each message into exact JSON; spending goes to the owner. On a pre-registered NeMo Gym held-out set of 46 twins of real threads, the same Lightning weights go from 9.2% to 58.2% of tasks fully passed (Claude Opus 5.5, same harness: 61.1% on a 36-task subset). Total: 30.6B parameters.

**Challenge selected:** Tool-Calling

**Repo link:** https://github.com/xvanov/red-hat-small-models-hack (public)

**Demo video (unlisted, 3 to 5 min):** {{VIDEO_URL}}

**Deployed URL / screen capture:** https://demo.rentus.homes (public page: try-it links and live results). The assistant itself is live on real channels: SMS **(888) 891-2046**, the **Rentus Homes Facebook Page** on Messenger, and **info@rentus.homes** all get AI replies (open mode, decision D39), with code-enforced guards: owner-confirmed facts only, no false "booked"/"published" claims, first person as the owner, the renter's language, owner approval for any spending, a fair-housing check, and a kill switch, STOP opt-out and rate caps. The personal Messenger inbox (Marketplace inquiries) only creates drafts the owner approves; Craigslist, Roomies and PadSplit are filled and stop before submit. The owner console (Inbox, Assistant, Pipeline, Model, Data) stays private on the owner's tailnet; screenshots are in `docs/img/`. The operator's Appling Way listing on the Facebook Page: {{FB_POST_URL}}. Open data: [xvanov/rentus-reader-messages](https://huggingface.co/datasets/xvanov/rentus-reader-messages), [xvanov/rentus-leasing-twins](https://huggingface.co/datasets/xvanov/rentus-leasing-twins); model: [xvanov/rentus-reader-qwen3-0.6b](https://huggingface.co/xvanov/rentus-reader-qwen3-0.6b).

**Team roster:**

| Name | Role | Contact |
|---|---|---|
| Kalin Ivanov | Solo: product, architecture, every decision; built with AI coding agents (Claude Code), one per workstream | GitHub @xvanov (email entered in the form) |

---

## Bounty: Best Use of NVIDIA Nemotron Lightning

**What Lightning does.** It is the whole operator. Every word to the owner, renters and vendors and every one of the 41 tool calls comes from Nemotron 3.5 Lightning 30B-A3B: reading the room record, running the fair-housing check, writing the listing, choosing channels, asking renters the five gate questions one at a time, deciding when a vague answer needs a re-ask, proposing showings, opening a maintenance job, comparing quotes, booking the cheapest plumber under the limit, and escalating to the owner with a ready-to-send draft. It also proposes fixes when a channel's page changes. It is not a chat layer on top of a workflow: there is no hardcoded call sequence, and the verifier only checks and corrects what Lightning decides.

**Why Lightning.** Three reasons, all measured. (1) 30B total for reliable tool choice, but only 3B active per token (hybrid Mamba/MoE), so one GPU serves 30 to 60 concurrent agent conversations plus a second model (`docs/vllm.md`). (2) It fits the 33B budget with room for our 0.6B reader. (3) It runs locally, so a renter's messages never leave infrastructure we control, and there is no per-message fee: the frontier reference costs about $0.11 per operator task.

**How we optimized it.**
- *Harness and prompt, measured in NeMo Gym one change at a time:* a renter guard (plain text is never delivered, so the loop sends the model back to `send_message`), a step-by-step system prompt (v1 → v3 → v4 written from the owner's rules), concierge tool descriptions, a style pre-check that turns a draft breaking the 2-sentence / 1-question rules into a rewrite request before it is sent, and keeping Lightning's reasoning in the history (that alone closed most of the gap between our loop and NeMo Gym's `simple_agent`).
- *Grounding:* a fine-tuned 0.6B reader as a tool, because prompted Lightning marks over a third of vague move-in dates as exact (vague-date trap 0.365 vs 0.012 for the reader, synthetic test).
- *Serving:* thinking off for routine tool turns doubles turns per second; prefix caching on the shared ~6k-token prompt raises throughput 76% at N=32; BF16 instead of NVFP4 after NVFP4 crashed under load.
- *In production:* the same final config answers real renters on SMS, the Facebook Page's Messenger and email (decision D39).
- *Evidence:* on the pre-registered v3 held-out set, final 0.930 (0.909 to 0.949) mean reward and 26.8/46 = 58.2% (44 to 71%) pass rate vs baseline 0.726 (0.695 to 0.758) / 4.2/46 = 9.2% (4 to 21%) (H1: Δ mean reward +0.204 (final − baseline; 4 vs 4 runs, 46 tasks), one-sided lower bound +0.170; p < 0.001, Holm p < 0.001: **supported**). Against Claude Opus 5.5 on the same harness (H4, non-inferiority at 0.05): Δ mean reward +0.014 (final − frontier, margin −0.05; 4 vs 1 runs, 36 tasks), one-sided lower bound -0.040; p = 0.011, Holm p = 0.033: **not supported**.

---

## Bounty: Best Model Improvement with NVIDIA NeMo Gym

**The task the agent failed at.** Leasing conversations under a strict rule set: qualify a renter on five items, one question at a time, in their language, never re-ask what they already said, never invent an answer, never propose a showing early, never promise a discount, and record everything in the demand register. The baseline (prompt v1, verbose tool descriptions, rule-based reader) passed 12% of v2 held-out tasks; on train, 23 of 28 leasing tasks never called `send_message` at all.

**Setup** (`gym/`, details in `gym/README.md`):
- *Environment:* a NeMo Gym 0.6.0 resources server (`gym/resources_servers/rentus/`) wrapping the same `rentus_tools` the product uses, one sandbox World per rollout, with fault injection (timeouts, rate limits, malformed results).
- *Tasks:* v1 (51 train / 31 held-out) and v2 (54 / 33, synthetic, from the open reader set) for development; **v3 held-out (46 leasing tasks)** built from twins of the owner's real threads, split by time (threads starting on or after 2026-05-01) and by person, frozen with sha256 before any model ran on it. Scripted renters and vendors answer from each task's script (no model, so scores are deterministic given the operator).
- *Scorer:* `gym/rentus_env/verify.py`, 7 check types (`state`, `never`, `style`, `tool_called`, `escalated`, `budget`, `message`); reward = share of checks passed, pass = every check passed. Trivial-agent floors are published (`gym/floors.py`): on v3 a greet-only agent earns 0.841 reward and passes 0 tasks.
- *Two runners, one scorer:* our loop (`gym/run_eval.py`) and NeMo Gym rollout collection with `simple_agent` (`--via nemo`), so improvements can be checked on NeMo's own harness.

**Baseline vs final, same held-out tasks and eval config.**

| set | baseline | final | test |
|---|---|---|---|
| **v3 held-out, 46 tasks (confirmatory)** | pass 4.2/46 = 9.2% (4 to 21%), reward 0.726 (0.695 to 0.758) | pass 26.8/46 = 58.2% (44 to 71%), reward 0.930 (0.909 to 0.949) | Δ mean reward +0.204 (final − baseline; 4 vs 4 runs, 46 tasks), one-sided lower bound +0.170; p < 0.001, Holm p < 0.001: **supported** |
| v2 held-out, 33 tasks (exploratory, 3 seeds) | pass 12.1% (5 to 27%), reward 0.570 | pass 45.5% (30 to 62%), reward 0.929 | Δ +0.359 (+0.281 to +0.436), 22 tasks better / 2 worse |
| v1 held-out, 31 tasks (superseded) | 1/31, reward 0.453 | 20/31, reward 0.921 | ablation ladder below |

**What improved it, isolated one knob at a time** (v1 held-out, each change alone vs baseline and cumulatively; `docs/results.md`):

| change | kind | alone | cumulative |
|---|---|---|---|
| (a) renter guard: plain text is never delivered, bounce back to `send_message` | harness | 0.453 → 0.686 | 0.686 |
| (b) prompt v3: plain-text rule first, a workflow per scenario, exact ids and ZIPs | prompt | 0.453 → 0.798 (1 → 11 passes; also 4 → 15 passes on NeMo `simple_agent`) | 0.846 with (a) |
| (d) style pre-check before `send_message` | verifier | 0.468 (nothing alone) | 0.902 with (a)+(b) |
| (g) reasoning kept in history (NeMo `vllm_model` parity) | harness | 0.614 | **0.921, 20/31** |
| (c) verbose tool descriptions v2 | tool descriptions | no gain on train, not kept | |
| (f) fine-tuned 0.6B reader instead of rules | model weights (tool) | +0.019, inside noise | |

Then, on development data only (Messenger conformance scenarios, concierge train, v2 train), prompt v4 from the owner's rules, concierge tool descriptions and a guard stand-down on owner-held threads: conformance 28 → 50 of 61 items, v2 train reward 0.746 → 0.831. That is the confirmatory final config.

**How to run scoring.**

```bash
scripts/setup.sh --gym
gym/.venv/bin/python gym/run_eval.py --tasks-version v2 --split heldout --run-name my-baseline          # our loop
gym/.venv/bin/python gym/run_eval.py --tasks-version v2 --split heldout --run-name my-nemo --via nemo  # NeMo Gym simple_agent
gym/.venv/bin/python gym/ablate.py --run-name _ --split train --variants base,guard,guard+prompt3      # one knob at a time
gym/.venv/bin/python gym/stats.py --md --config a=my-baseline --config b=my-nemo --compare b:a           # CIs and paired tests
gym/.venv/bin/python gym/run_eval.py --tasks-version v2 --split heldout --run-name plumbing --stub        # no GPU: plumbing only, not a score
```

The pre-registered v3 commands are in the README ("Reproduce the confirmatory results") and `gym/confirmatory_v3_a9.json`.

**Honest notes.** Changes were designed on train; v1 held-out was run about 15 times while choosing them, which is why v2 is exploratory and only v3, frozen before any run, is confirmatory. Part of the style-check gain is the scorer no longer counting drafts the guard would have stopped; those checks are reported separately on v3.

---

## Bounty: Best Use of Red Hat vLLM

Full write-up with every table: [docs/vllm.md](vllm.md).

**Architecture.** One Brev RTX PRO 6000 Blackwell (96 GB, $2.63/hr) runs two vLLM 0.27.1 containers: the Lightning operator and the 0.6B reader, split by memory fraction (0.85 / 0.12). Both bind to 127.0.0.1 on the instance and are reached only through an SSH tunnel; both restart themselves (`--restart unless-stopped`), and a watchdog sends a one-token generation probe every ~2 minutes, because `/v1/models` kept answering during a stalled engine. vLLM is the only inference path in the system: the console, the operator loop, the Gym runs and the reader evaluation all talk to it through the OpenAI-compatible API, with server-side parsing (`--reasoning-parser nemotron_v3`, `--tool-call-parser qwen3_coder --enable-auto-tool-choice`). `serving/rebuild.sh` rebuilds the whole thing on a new instance in one command; `serving/FROZEN.json` pins the image digest, checkpoint revision and every argument for the evaluation.

**Configuration that mattered.** Prefix caching with the Mamba `align` cache mode (that is what makes caching work on a hybrid model; side effect: reuse in whole 2,128-token blocks, which predicts our measured 71.3% first-turn hit rate exactly), `--async-scheduling`, the card's Mamba cache flags, `--max-num-seqs 64`, `--max-model-len 65536`, and per-request `enable_thinking` so routine tool turns skip reasoning without a restart.

**Measured results** (real operator prompt and 26 tool schemas, `serving/serve_bench.py`, Prometheus `/metrics` snapshots):
- Prefix caching: **+76% throughput at N=32, +97% at N=64**, time to first token −50 to −64% (paired on/off via per-request `cache_salt`, because restarting the shared server would have broken other running jobs).
- Reasoning off for tool turns: **6.9 → 13.2 turns/s**, p95 latency 8.1 → 2.6 s, still 100% tool calls.
- Two models on one card: the reader stays under 0.47 s p95 at every operator load, 0 errors.
- 1,650 benchmark requests, 0 errors; one engine crash recovered by Docker in 40 s.
- Pre-registered 3-repetition caching bench on the frozen BF16 server (H5): not run in time; the +76% above is a single repetition.

**The NVFP4 → BF16 stability story.** We started on NVFP4 (18 GB of weights, room for a 50 GiB KV cache and the reader). Under real agent load it died intermittently with `CUDA error: misaligned address` / illegal memory access, and each crash failed every in-flight request (52 of 99 rollouts in one eval had to be rerun). We isolated it with one change per run under a 48-worker stress test: CUDA graphs piecewise only, still crashed at 11.5 min; Triton kernels instead of FlashInfer, crashed at 8.7 min; the **BF16 checkpoint, 2,567 requests in 15.5 min, 0 errors**. What remained in common was the NVFP4 path on SM120 (Marlin W4A16, FP8 linear layers, FP8 KV cache). We moved the evaluation to BF16 and paid for it: decode throughput −38% at N=32 (1,412 → 880 tok/s), but time to first token got faster (2.2 → 1.0 s) and nothing crashed. Built-in MTP speculative decoding, free under the 33B budget, accepted about 3 tokens per step but crashed at 4 concurrent requests, so it is off too.

---

## Champions Choice pitch

A landlord with fifty rooms lives in the inbox. Rentus Operator puts a 30-billion-parameter open model on one GPU in charge of that inbox and holds it to the owner's own rules: it writes and posts the listing, qualifies renters in two languages without re-asking what they said, books the plumber under budget, and sends the owner only the decisions that are his, on his phone. It is not a demo of a chatbot. It is a tool-calling system with a code verifier that catches bad calls, a 0.6B model we fine-tuned to read renter messages (0.522 exact match on owner-labeled messages, vs 0.667 for Claude Opus 5.5), and an evaluation we pre-registered and froze before running, including the parts that did not go our way. And it is live: text (888) 891-2046, message the Rentus Homes Page or email info@rentus.homes, and Lightning answers, under guards written in code (demo.rentus.homes). On a pre-registered held-out set it goes from 9.2% to 58.2% of tasks fully passed, against 61.1% for Claude Opus 5.5 on the same harness. The code, the NeMo Gym environment, the datasets and the reader are all open.
