# Agent brief — NVIDIA x Red Hat Small Models Hack

Read this first. Every coding agent (Claude Code, Codex, OpenCode, Cursor) working in this repo follows it. `AGENTS.md` is a copy of this file.

## Source of truth for the rules

`docs/hackathon/README.md` holds the rules, judging criteria, bounties and submission checklist, taken from the event Notion page and the kickoff slides. Read it before designing anything. `docs/hackathon/slides.md` is the slide-by-slide transcription and `docs/hackathon/source/` holds the originals.

Code freeze and submission: **Sunday Oct 18, 11:00 AM ET**. Nothing merges after that.

## Hard rules, never break these

1. **≤33B total parameters, summed across every generative language model the system runs**, including verifiers, critics, routers and speculative-decoding drafts. Embedding and reranking models are excluded. MoE models count their total parameters. Nemotron 3.5 Lightning is 30B, so it leaves about 3B for everything else. Any model you add goes in the budget table in `BRIEF.md`.
2. **All code is written during the event.** Do not copy code from `~/rental-management`, `~/rental-media`, `~/rentus-room-agent` or any other private repo. Reading their docs and rules for domain knowledge is fine. Open-source libraries are allowed only if they were public 2+ weeks before Oct 17, 2026. Commit early and often, because the commit timestamps prove when code was written.
3. **Open data only.** Every dataset must be public or open-data, or synthetic data generated here and published with its method. Record each source in `docs/data-provenance.md` when you add it. No real tenant or renter data, ever.
4. **Nothing reaches a real person or a live platform without the owner's click.** Channel automations run in stop-before-submit mode by default. No real messages, calls or posts.
5. **Secrets live in `.env`** (gitignored). Never print, log or commit them. Refer to them by variable name only, for example `BREV_KEY`.

## Hackathon updates (Discord and announcements)

Claude cannot read the event Discord. The owner pastes announcements, screenshots or rule clarifications into the chat as they come. When that happens:

1. Append the update to `docs/hackathon/updates.md` with the date and time (ET), quoting it verbatim.
2. Check it against `docs/hackathon/README.md` and `BRIEF.md`. If it changes a rule, a deadline, a judging criterion or a requirement, update `docs/hackathon/README.md` and mark the change with the date.
3. Tell the owner, in plain words, whether it affects the current plan and what you would change. Flag anything that puts a workstream at risk right away instead of waiting.

Before starting any new workstream, re-read `docs/hackathon/updates.md` for anything that changed since you last looked.

## How we work

- One workstream per agent session, each in its own folder (see `BRIEF.md`), so parallel sessions don't collide.
- Shared formats live in `contracts/`. Change a format only by editing it there and noting it in `BRIEF.md`.
- Keep the README in the shape the submission checklist requires: quick start, architecture diagram, how to reproduce the demo with a sample `.env`, datasets and provenance, known limitations.
