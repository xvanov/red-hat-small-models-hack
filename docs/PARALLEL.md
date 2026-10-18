# Parallel lanes (Sun Oct 18, from ~03:45 ET)

Each new agent session takes ONE lane. Start the session in `~/red-hat-small-models-hack` with:

> Read CLAUDE.md, BRIEF.md, docs/PARALLEL.md, docs/DECISIONS.md. You own lane **<N>**. Work only in that lane's folders.

Rules for every lane: commit small and often with explicit paths only (`git add <your folders>`, never `-A`); `git pull --rebase --autostash origin main && git push origin HEAD:main`; never touch another lane's folders; nothing reaches a real person or a live platform without the owner's click; never print secrets; no private data (anything under `~/rentus-private-data/`) goes into the repo or to an external API. **Feature freeze 08:30. Code freeze 11:00.** The GPU is shared: keep model concurrency ≤ 8 unless your lane says otherwise.

| Lane | Owns (folders) | Goal by 08:30 | Depends on |
|---|---|---|---|
| **0 — Coordinator (the original session)** | `docs/` (except lane-owned files), `gym/stats.py`, eval protocol, twins runs, results | Eval protocol with reviewer loops, realistic task set from the owner's data, final numbers | — |
| **1 — Console UI redesign** | `console/` (static + templates + app wiring), `docs/img/` | A clean, legible, judge-ready UI: clear hierarchy, readable trace, real-world + trust panels, phone `/approve`. Keep every existing endpoint and the 30-check `scripts/console_verify.py` passing. | none |
| **2 — Concierge / demand capture** | NEW files only: `tools/rentus_tools/impl/demand*.py`, `tools/tests/test_demand*.py`, `operator/prompts/system_v4.md`, `gym/tasks/concierge/` | Demand-first behavior per `docs/spec/concierge.md`: every inquiry captured in the demand register (criteria, status), fit to inventory or offer other rooms, source alternatives (search fixtures), park with `reconnect_at`, follow-up cadence, cluster ≥5 → supply signal report. Register new tools in `schemas.py` with one small commit. | `docs/spec/concierge.md` (being written now) |
| **3 — Live channels** | `channels/` (+ `tools/rentus_tools/live/`) | Roomies, Craigslist, PadSplit listing forms filled and stopped before submit (owner logs in once via `channels/LOGIN.md`); email: read inquiries via IMAP into threads, replies as drafts only; SMS: drafts only, never sent. Same adapter signatures as the contract. | owner logins for live tests |
| **4 — Messenger flow conformance** | `gym/conformance/` (new), `gym/tasks/messenger/` (new) | An executable conformance suite: one scripted or model-played scenario per checklist item in `docs/spec/concierge.md` §5, a runner that reports pass/fail per item for any operator config. This is what proves "it behaves like the Muse flow". | `docs/spec/concierge.md` |
| **5 — Playbooks and tone** | `docs/playbooks/` (new), `data/style/` (new) | From the owner's private data (read locally only; publish paraphrased guidance, no excerpts): ideal flows per situation (prospect inquiry, no-inventory demand capture, late or partial rent → payment plan or escalation, maintenance triage before vendor, contractor quote/schedule/verify), plus a tone guide (less robotic, the owner's flavor, aggregate style stats). Lane 2 turns these into prompt v4. | private data in `~/rentus-private-data/raw/anonymized-2026-10-18/` |

## Not a lane: trust signals

Judging whether a tenant or prospect is trustworthy is useful but legally sensitive (Fair Housing Act): speech style, dialect or language can stand in for national origin, disability or other protected traits. If built, it uses behavior only (stated facts that stay consistent, commitments kept, verifiable information provided, payment history), shows its reasons, never auto-rejects, and the owner decides. Out of scope for the submission unless the owner asks.
