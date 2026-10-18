# Handoff — how to resume if this session ends (Sun Oct 18)

If the coordinating Claude session runs out of tokens or is restarted under another subscription, a new session resumes from here. Everything below lives in git or in `~/rentus-private-data/` (private, never committed).

## Read first (in order)
1. `CLAUDE.md` (rules), `BRIEF.md` (architecture), `docs/DECISIONS.md` (every decision, D1–D31), `docs/PARALLEL.md` (lanes).
2. `docs/eval-protocol.md` incl. Amendment 1, `docs/reviews/*.md` (round 1 + round 2). **Rule D31: no result counts until the round-2 review says READY.**
3. `docs/results.md` (v2 exploratory results on top), `docs/vllm.md`, `reader/README.md`.
4. `docs/spec/concierge.md` + `docs/spec/gap-analysis.md` (the Muse flow), `docs/playbooks/` + `docs/playbooks/owner-decisions.md`.

## Infrastructure
- GPU: one Brev instance `rentus-operator` (RTX Pro 6000), running until the 11:00 freeze, then delete it (`~/.local/bin/brev delete rentus-operator` with `BREV_API_KEY` exported). Rebuild from scratch: `serving/rebuild.sh`.
- Tunnels: `serving/tunnel.sh` (Lightning → localhost:8000), `LPORT=8011 RPORT=8001 serving/tunnel.sh` (reader → localhost:8011), `serving/watchdog.sh start`.
- Console: `scripts/demo.sh` (127.0.0.1:8080); tailnet: `python3 scripts/tailnet_forward.py` (100.64.38.18:8080). Verify: `scripts/console_verify.py`.
- Health: `scripts/doctor.sh`.

## Work in flight at the time of writing (check `git log` for what landed)
- Twins pipeline on the owner's data (`data/twins/`, private work in `~/rentus-private-data/work/`): v3 held-out tasks + owner review sheets (label spot-check, realism blind review).
- vLLM crash fix (CUDA misaligned address under load) → `docs/vllm.md` Stability section.
- Round-2 methodology review → `docs/reviews/round2-review.md`.
- Owner policy decisions (D29) → tools + prompt v4.
- Email (Gmail read-only, drafts) + Google Calendar showings adapter → `channels/`.
- Console UI redesign → `console/`, screenshots `docs/img/console-v2-*`.
- Frontier reference via local Claude Code → `scripts/frontier_ref.sh`.
- Messenger conformance suite → `gym/conformance/`.

## Remaining critical path to submission
1. Round-2 verdict READY → freeze v3 held-out (hashes in `data/twins/splits.json`).
2. Owner labels the reader test sample (H2) if he chose to; else H2-realistic is "untested".
3. Confirmatory runs per `gym/confirmatory_v3.json` (5 seeds), frontier reference on v3, stats → `docs/results.md`.
4. Owner grades the κ sample.
5. README final, demo rehearsal, make the repo public (or invite judges), record the 3–5 min video (`docs/demo-script.md`), submit the Airtable form by 10:45 (link in local `docs/hackathon/README.md`), delete the Brev instance.

## Friction log
Notes and reports in `.agent-logs/87a72e7b/` (gitignored). The trimmed report for @Robbie is `friction-report-2.txt`.
