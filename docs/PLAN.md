# Plan — Rentus Operator

The plan we follow until code freeze (Sun Oct 18, 11:00 AM ET). `BRIEF.md` explains the product and architecture, `docs/DECISIONS.md` records why. Update the status column as work lands.

## Success criteria (what "done" means for judging)

1. **End to end:** the owner types "Appling Way room free Nov 1, $750, private bath" in the console, and the operator builds the listing, posts it to sandbox channels (and at least one real platform in stop-before-submit mode), answers inbound renters, qualifies them, records them, matches, proposes a showing, and escalates what needs the owner. Plus one ops scenario: find a plumber, collect quotes, book under the limit, notify the tenant.
2. **Tool-calling reliability, measured:** a NeMo Gym environment with tasks, tools and scorers; a held-out split; baseline vs improved pass rate for the operator, with each improvement isolated.
3. **vLLM, measured:** throughput/latency under concurrency, prefix caching effect, tool-call parse success rate.
4. **Open data, documented:** every dataset cited in `docs/data-provenance.md`; synthetic sets and methods published under `data/published/`.
5. **Submission:** README per checklist, 3–5 min video, Airtable form submitted by 10:45.

## Phase 1 — Sat 11:30 → 20:00: MVP loop in the sandbox

| ID | Workstream | Deliverable | Depends on | Status |
|---|---|---|---|---|
| P1.0 | Contracts (Claude) | `contracts/tools.md`, `contracts/scenario.md`, `contracts/events.md` | — | in progress |
| P1.1 | W1 serving | RTX Pro 6000 on Brev, vLLM serving Lightning with tool calling, tunnel to localhost:8000, smoke test, first bench | GPU approval (done) | starting |
| P1.2 | W5 data | downloads, reader dataset (train/dev/test), sandbox inventory, provenance doc | — | running |
| P1.3 | W3 tools | sandbox implementations of every tool in the contract, with a fault-injection switch | P1.0 | starting |
| P1.4 | W2 operator | agent loop over vLLM's OpenAI-compatible API, verifier, retries, fallbacks, event stream; runs on a stub model until P1.1 is up | P1.0 | starting |
| P1.5 | W4 gym | NeMo Gym resources server wrapping the sandbox tools, 40+ tasks (leasing + ops), scorers, train/held-out split, baseline run script | P1.0, P1.3 | starting |
| P1.6 | W7 console | web console: owner chat, channel lanes, register, escalations, scoreboard, "break something" button; reads the event stream | P1.0 | starting |
| P1.7 | Baseline | first Gym score of Lightning on held-out tasks, committed to `results/` | P1.1, P1.4, P1.5 | — |

**Checkpoint 20:00:** the full sandbox loop runs on Lightning through vLLM, the console shows it, and a baseline score exists.

## Phase 2 — Sat 20:00 → Sun 09:00: improve, measure, reach real platforms

| ID | Workstream | Deliverable |
|---|---|---|
| P2.1 | Gym improvement | ablations one at a time (system prompt, tool descriptions, verifier feedback, reader-in-the-loop); results table with each delta isolated |
| P2.2 | W6 reader | fine-tune a ≤1.5B reader on the published set; eval vs base and vs Lightning on held-out; publish weights to Hugging Face |
| P2.3 | Operator LoRA (stretch) | rejection-sampled SFT from Gym rollouts on Lightning; only if P2.1 is done and GPU time allows |
| P2.4 | W8 channels | browser automations for 1–2 real platforms (fill, screenshot, stop before submit) + local mock pages for the Gym + operator-driven selector repair |
| P2.5 | vLLM bench | concurrency sweep, prefix caching on/off, NVFP4 vs BF16 if feasible, written up |
| P2.6 | README + docs | quick start, architecture diagram, sample `.env`, provenance, limitations |

## Sunday — 09:00 → 11:00

| Time | Step |
|---|---|
| 09:00 | Choose the track from results. Freeze features. |
| 09:15 | Final scores on held-out tasks; README final. |
| 09:45 | Record the 3–5 min video (intro, pitch, live loop, how it's built, so-what). |
| 10:30 | Upload unlisted; start the Airtable form. |
| 10:45 | Submitted. |
| 10:50 | Delete the Brev instance after confirming nothing else needs it. |

## Rules every workstream follows

See `CLAUDE.md`. In short: commit your own folder often (`git add <your folder>`, never `git add -A`), pull with rebase before push, never touch another workstream's folder, never print secrets, nothing real gets sent.

## Open questions for organizers

Kept in the local rules summary (`docs/hackathon/README.md` §10). The four that affect design: simulator model in the Gym vs the 33B budget; several agents on one model counting once; LoRA adapters counting; datasets under 2 weeks old.
