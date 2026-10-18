# BRIEF — Rentus Operator

Main track: **Tool-Calling**. Backups we can switch to at the 9 AM Sunday decision: Fine-Tuned & Specialized, Multi-Agent. Bounties targeted: Nemotron Lightning, NeMo Gym, Red Hat vLLM, Champions Choice.

## The product in one line

Tell it "the Appling Way room is free Nov 1, $750, private bath" and it runs the whole leasing loop: it builds the listing, posts it to every channel, answers inquiries, qualifies renters with exact answers, matches them to rooms, proposes showings, and hands the owner only what needs a decision. The same operator handles property operations, for example finding a plumber, collecting quotes and booking the cheapest one under the owner's spending limit.

## Architecture

```
            owner (console chat)            simulated or real channels
                    |                       (marketplace, roomies, sms, email)
                    v                                    |
   +-----------------------------------+                 |
   |  OPERATOR  Nemotron 3.5 Lightning |<---- inbox -----+
   |  30B MoE, served on vLLM          |
   |  talks AND calls tools            |---- tools ----> listings, channels, media,
   +-----------------------------------+                 register, calendar, market rent,
          |   calls like any tool                         web search, vendors, escalate
          v
   +-----------------------------------+
   |  READER  fine-tuned model <= 3B   |   narrow job: renter message -> exact JSON
   |  served on the same vLLM          |   (lease ok, exact date or vague, phone,
   +-----------------------------------+    occupants, reason, intents, language)

   VERIFIER = deterministic code, not a model: schema checks, rule checks, retry and fallback.
   NeMo Gym environment = the same tools in a sandbox + scripted renters/vendors + scorers.
```

- **Operator** decides and acts. One model holds the conversation and makes the tool calls in the same turn.
- **Reader** is an instrument the operator calls, like a calculator. The operator never judges on its own whether "next month" is an exact date: it calls `read_reply` and trusts the result. The reader is evaluated and published on its own, which is the Fine-Tuned backup.
- **Gym-improved operator**: a LoRA on Lightning trained from Gym rollouts, if GPU time allows. It's the same 30B model in the budget.

## Parameter budget (must stay ≤ 33B)

| Model | Role | Total params |
|---|---|---|
| Nemotron 3.5 Lightning 30B-A3B | operator | 30B |
| Reader (TBD, target ≤1.5B) | message reader | ≤1.5B |
| **Total** | | **≤31.5B by the card, ≤33.1B by the raw weight count** |

Lightning's card says 30B, but Hugging Face counts 31.58B in the weights. The rule uses the card's number, but we keep the reader at 1.5B or less so we stay under 33B by either count. Lightning's draft models for speculative decoding (DSpark, DFlash) count toward the limit, so we don't use them. Its built-in MTP speed-up is free.

**NeMo Gym improvement doesn't require training** (kickoff slides): a measured change to prompts, tool descriptions, the harness or routing qualifies, with tasks and scorer held fixed and one change at a time. Weight training is the stretch goal, not the requirement.

Simulated renters and vendors in the Gym are scripted from open datasets, not a model, until the organizers confirm a simulator model doesn't count. Any self-repair of broken site automations at runtime uses the operator itself, never an extra model.

## Workstreams (one agent session each, own folder)

| # | Folder | Owns |
|---|---|---|
| W1 | `serving/` | Brev GPU, vLLM serving Lightning + reader, tool-call parsing confirmed, throughput/latency benchmarks |
| W2 | `operator/` | agent loop, verifier, retries and fallbacks |
| W3 | `tools/` | tool implementations against `contracts/tools.md`; sandbox and live modes |
| W4 | `gym/` | NeMo Gym resources server: tasks, scripted renters and vendors, scorers, held-out split |
| W5 | `data/` | open datasets, Spanish translation, synthetic leasing tasks, published with method; `docs/data-provenance.md` |
| W6 | `reader/` | reader fine-tune and eval against base and Lightning |
| W7 | `console/` | interactive demo console |
| W8 | `channels/` | browser automations for real platforms, stop-before-submit, self-repair loop |

## Contract changes

- 2026-10-18: `contracts/tools.md` §6, new actor `router` (triage router decisions are `verifier` events with `data.stage = "router"`, and its register writes / escalations are tool calls with actor `router`). Additive.
- 2026-10-17: `contracts/tools.md` §9, task set v2 script fields (`reuse`, list `when_asked`, `classifier`, per-task room patches). Additive; v1 tasks unchanged.

## Milestones

- **Phase 1, by 8 PM Sat:** the full loop runs in the sandbox on Lightning via vLLM, with a baseline Gym score.
- **Phase 2, overnight:** Gym-driven improvement (reader fine-tune and/or operator LoRA), final scores on the held-out split, vLLM benchmarks, real channel automations, console polish.
- **Sun 9:00–10:45:** choose the track, record the 3–5 min video, finish the README, submit before 11:00.
