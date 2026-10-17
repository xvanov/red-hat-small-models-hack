# Console (W7)

The live demo: one page where the owner types an instruction and watches the operator list the room, answer renters, qualify them, escalate decisions and book vendors, with every tool call, verifier catch, retry and fallback visible. Faults can be injected live to show recovery.

## Run

From the repo root (Python 3.12):

```bash
scripts/setup.sh          # root .venv with tools, operator, console, channels
scripts/demo.sh           # tunnels if needed + console on :8080
# or by hand: .venv/bin/python -m uvicorn console.app:app --port 8080
# open http://localhost:8080
```

Environment (read from `.env` if present, never printed):

| Variable | Effect |
|---|---|
| `OPERATOR_BASE_URL` | vLLM OpenAI endpoint (default `http://localhost:8000/v1`). If `GET /models` answers, runs use the real operator on it and the badge reads **live: Nemotron 3.5 Lightning (vLLM)**. |
| `READER_BASE_URL`, `READER_MODEL`, `READER_API_KEY` | the reader endpoint `read_reply` posts to (`http://localhost:8011/v1`). If `GET /models` answers, the second badge reads **reader: rentus-reader 0.6B (vLLM)**, else **reader: rules fallback**. |
| `OPERATOR_MODEL`, `OPERATOR_API_KEY` | passed through to the operator's `RunConfig`; the model defaults to the first id vLLM lists. |
| `CONSOLE_STUB=operator` | with no endpoint, run the real `rentus_operator` loop and real `rentus_tools`, using the operator's scripted stub model (listing flow only). |
| `CONSOLE_FORCE_STUB=1` | always use the console's own stub driver (rehearsal, or if the operator breaks on stage). |
| `READER_LABEL` | overrides the reader badge text. |
| `CONSOLE_RUNS_DIR` | where runs are written (default `runs/`). |

Test: `python -m pytest console/tests -q` starts the app under uvicorn on a free port and hits every endpoint, in both stub modes.

## Modes (shown in the badge)

1. **live** — `rentus_operator.run()` on vLLM over `rentus_tools`. Each owner message, arriving renter or escalation decision is one operator turn; history carries across turns.
2. **operator-stub** — same loop and tools, the operator's `StubClient` instead of a model.
3. **stub (console driver)** — `console/sim.py`, a rule-based stand-in for operator + tools + renters, so the full loop (listing, qualifying, showing, price escalation, plumber quotes, faults and recovery) can be shown with no GPU. It is labeled stub everywhere and never claims to be a model.

Scenarios (`gym/tasks/*.jsonl`) run through the gym's own `RolloutSession`, so scripted renters answer inside `send_message` exactly as they do when scoring. In free play the console adds three synthetic renters once a listing is live.

## Page

- **Owner** (left): chat. The first message starts a run; later messages go to the running operator.
- **Channels** (middle): one lane each for marketplace, roomies, craigslist, padsplit, sms, email. Listing cards on top (with a screenshot thumbnail when a live adapter returns `screenshot`), threads below as messages arrive.
- **Right**: demand register with gate ticks (lease, move-in, phone, reason, occupants: ✓ answered, ~ vague, ✗ no), owner escalations with Approve / Deny, ops jobs, quotes and spend vs limit.
- **Bottom**: live trace, color-coded by kind, each row labeled with who acted (operator + model, reader, verifier = code, scripted renter, owner); scoreboard from `results/*/summary.json` and `gym/results/*/summary.json` (baseline vs improved, with delta).
- **Header**: Run scenario picker, speed (0.5× to 10×, paces tool calls and renter arrivals), **Break something** (timeout, page changed, rate limited, malformed result, login required) which appends a contract §5 fault to the running world's `faults` for the next call of the chosen tool.

## API

| Method | Path | |
|---|---|---|
| GET | `/api/status` | badge, mode, packages, active run |
| GET | `/api/scenarios` | gym tasks |
| GET | `/api/scoreboard` | parsed `results/*/summary.json` |
| GET/POST | `/api/runs` | list / start `{goal?, scenario_id?, speed?}` |
| GET | `/api/runs/{id}/view` | world rendered for the page |
| GET | `/api/runs/{id}/events` | SSE: `runs/<id>/events.jsonl` (contract §6) merged with `console.jsonl` (fault and scenario notes the console writes) |
| POST | `/api/runs/{id}/owner` `/faults` `/speed` `/stop` `/escalations/{esc_id}` | controls |
| GET | `/api/file?path=` | screenshot images under `runs/`, `channels/`, `results/` only |

## Known limits

- An operator turn can't be interrupted; owner messages sent during a turn queue behind it.
- The scoreboard reads `pass_rate` (or `task_pass_rate`, `score`, `passed/total`) and `per_check` / `checks`; other summary shapes show as "?".
- Owner decisions reach the real operator as a new owner turn ("Owner decision on escalation X: APPROVED ..."); the escalation's status is set in the world by the console.
