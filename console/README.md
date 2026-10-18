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

1. **live** — `rentus_operator.run()` on vLLM over `rentus_tools`, with the held-out winning config (`guard+prompt3+style+rhist`, docs/results.md), not the `RunConfig()` defaults (those are the baseline). Each owner message, arriving renter or escalation decision is one operator turn. Owner turns run one at a time with their own history; renter conversations run in parallel (up to 3, one history per thread), so vLLM batches them. Every tool call holds one lock, so the World stays consistent. A decision on a renter's escalation runs inside that renter's conversation, after its current turn.
2. **operator-stub** — same loop and tools, the operator's `StubClient` instead of a model.
3. **stub (console driver)** — `console/sim.py`, a rule-based stand-in for operator + tools + renters, so the full loop (listing, qualifying, showing, price escalation, plumber quotes, faults and recovery) can be shown with no GPU. It is labeled stub everywhere and never claims to be a model.

Scenarios (`gym/tasks/*.jsonl`) run through the gym's own `RolloutSession`, so scripted renters answer inside `send_message` exactly as they do when scoring. In free play the console adds three synthetic renters once a listing is live.

## Demo run (one click, for the video)

**▶ Demo run** starts a fresh free-play run on a demo world (sandbox inventory, three plumbers for the Appling Way zip, $400 limit; at the plumber step the director injects a timeout on the first `request_quote` call, so one plumber never answers whichever the model asks first) and `console/demo.py` plays the owner and the world while the live operator does everything else:

1. owner: "Appling Way room free Nov 1, $750 ..." → listing written, compliance-checked, posted to 3 lanes
2. María (Spanish, vague date first) and Devon (asks if the rent is negotiable) write in at the same time
3. faults: a rate limit on María's next message, a malformed reader result → retry and verifier catch in the trace
4. owner: the tenant's sink leaks → job, quotes (one vendor times out), cheapest booked under the limit, tenant told
5. Devon's price question waits for the owner; the bar shows the phone URL + QR code. If the operator did not escalate on its own, Devon asks once more for a payment-terms discount (which the prompt says must go to the owner).

The bar on top shows the step, a plain-language line for narration and the elapsed time. On the live endpoint the whole sequence took 75 to 130 seconds at 1× across five verification runs. Speed scales the scripted pauses and tool pacing, never the model. **Reset** stops everything and clears the page.

## Owner approval on the phone

`/approve` is a phone-sized page listing open escalations (who, their last message, the reason, the drafted reply) with **Approve / Edit / Deny**. Edit lets the owner rewrite the reply; the operator is told to send that exact text. Decisions are tagged `via phone` in the trace and the side panel. The console listens on 127.0.0.1 only; `scripts/tailnet_forward.py` (started by `scripts/demo.sh`) relays it to this machine's Tailscale address, so the phone opens `http://<tailscale-ip>:8080/approve` and nothing is exposed on the LAN. There is no login: the tailnet is the access control.

## Evidence panels (bottom right, ⤢ opens them full screen for the projector)

- **Why trust it**: held-out reward and pass rate with 95% intervals (final vs baseline), tasks better/worse with the Holm p-value, who does what and the parameter budget, the reader's exact match on the same 400 held-out messages (Wilson intervals) against Claude Opus 5.5 and Lightning prompted.
- **Results**: every v2 held-out config (`gym/results/v2-heldout-<name>-s<seed>/`, discovered by name) with reward and pass-rate intervals drawn as whiskers, pass in every run, time per task; paired tests (Holm-corrected); per category baseline vs final. All computed at request time by `gym/stats.py` from `per_task.jsonl` (`/api/results`), so the panel matches `docs/results.md`. The superseded v1 ladder sits folded below it.
- **Performance**: vLLM numbers from `serving/results/serve_bench.jsonl` (`/api/performance`): peak throughput, prefix caching on vs off (paired), reasoning off vs on, reader latency under operator load, request and error totals, with two small bar charts. Method in `docs/vllm.md`.
- **Real world**: the live Facebook Page post (permalink parsed from docs/DECISIONS.md D20, thumbnail cached by `scripts/pilot_thumb.py`, a read-only Graph GET) and the shadow inbox counters from `runs/pilot/stats.json` (counts only; renter text is never read here).

## Verification

`channels/.venv/bin/python scripts/console_verify.py all` drives every path on the live models with Playwright and writes screenshots to `docs/img/`: listing, a Spanish leasing scenario (showing proposed only after all five gate items), Break-something faults (page changed, login wall, rate limited, malformed), the plumber scenario, the three panels, and the demo run with the owner editing and approving on a phone-sized `/approve`.

## Page

Light and dark themes (follows the system, ◐ toggles). Built for a 1920×1080 recording; works at 1680 and stacks on narrow screens.

- **Top bar**: product name, live model badges (operator Lightning on vLLM, reader 0.6B; grey when the endpoint is down), parameters used of 33B, spend of the owner's limit, run state; **▶ Demo run**, speed, **Gym ▾** (scenario picker), **Break something ▾**, **Reset**.
- **Demo bar** (while a demo plays): five-step progress, the current step's title and narration line, elapsed time, and the phone URL with a QR code (it pulses when the owner's decision is waiting).
- **Left**: the owner conversation (instructions, the operator's reports per turn) and **Needs you**: open escalations with the renter's last message, the drafted reply and Approve / Edit / Deny, plus proposed showings waiting for confirmation.
- **Center**: the leasing pipeline. A channel strip (listing, then each channel live / not posted / failed with its thread count), then renter cards in Inquiries → Qualified → Showing → Application by register status. Each card shows the five gate items as a progress bar (green exact, striped amber vague, red no), key facts and the last two messages. **Maintenance** appears under it once a tenant writes or a job opens: quotes (the booked one highlighted), spend vs limit, the tenant thread.
- **Right**: the demand register (everyone who wrote, status, what they want, reconnect dates) and **Supply signals**: demand clusters by area, type and $150 budget band (docs/spec/concierge.md 5.3), WATCH at 3 active, SUPPLY SIGNAL at 5 qualified. When a person stated no criteria, the room they asked about stands in and the cluster says so. Any `supply_signals` the tools write into the world are listed too.
- **Bottom**: the live trace, grouped per turn (each group opens on an owner instruction or a renter message and counts steps and recoveries). A tool call and its result share one row; the reasoning behind a call is in the row's tooltip. Actors are color-coded: operator (Lightning), reader (0.6B), router, verifier (code), tools, scripted renters and vendors. Errors, retries, verifier catches, fallbacks and injected faults are highlighted; **recoveries only** filters to them. Older groups fold unless they hold a recovery. The ▾ button collapses trace and evidence.

## API

| Method | Path | |
|---|---|---|
| GET | `/api/status` | badge, mode, packages, active run |
| GET | `/api/scenarios` | gym tasks |
| GET | `/api/scoreboard` | held-out ladder from `gym/results/*/summary.json` |
| GET | `/api/trust` `/api/realworld` | evidence panels (`console/panels.py`) |
| GET | `/api/results` | v2 held-out configs with 95% CIs, paired Holm tests, per category (`gym/stats.py`) |
| GET | `/api/performance` | vLLM serving benchmarks (`serving/results/serve_bench.jsonl`) |
| POST | `/api/demo` `/api/demo/speed` `/api/reset` | demo run, its speed, stop and clear |
| GET | `/approve`, `/api/approvals` | phone view and its data (open escalations first) |
| GET/POST | `/api/runs` | list / start `{goal?, scenario_id?, speed?}` |
| GET | `/api/runs/{id}/view` | world rendered for the page |
| GET | `/api/runs/{id}/events` | SSE: `runs/<id>/events.jsonl` (contract §6) merged with `console.jsonl` (fault and scenario notes the console writes) |
| POST | `/api/runs/{id}/owner` `/faults` `/speed` `/stop` `/escalations/{esc_id}` | controls; a decision takes `{decision, text?, source?}`, a fault `{kind, tool?, times?, match?}` |
| GET | `/api/file?path=` | screenshot images under `runs/`, `channels/`, `results/` only |

## Known limits

- An operator turn can't be interrupted; owner messages sent during a turn queue behind it.
- Owner decisions reach the real operator as a new turn ("Owner decision on escalation X: APPROVED ..."); the escalation's status is set in the world by the console.
- The model sometimes fills `escalate_to_owner` with the thread id as `reason`; the page then shows the draft as the reason.
- Free-play renters (not Gym scenarios) also answer a request phrased without a "?" ("Please tell me the exact day"); Gym scenarios keep the scored renters' exact behavior.
- Each run reads `operator/prompts/system_v3.md` when a turn starts, so an edit to the prompt by another session lands in the next turn (once, mid-edit, a half-written file crashed a turn; it shows as a fallback row and `runs/<id>/errors.log`).
