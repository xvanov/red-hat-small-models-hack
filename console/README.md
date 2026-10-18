# Console (W7)

The owner's leasing desk: one inbox for every live channel, an assistant that lists rooms and handles repairs, a pipeline of prospects, and the model's measured results. Every tool call, reader parse, verifier catch and recovery is visible per conversation.

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

## Page

A sidebar app with one page per job. Light and dark follow the system setting. The top bar shows only the product name, the operator (Lightning on vLLM) and reader (0.6B) status dots, and one dot per live channel.

1. **Inbox** (default, `#/inbox/<thread_id>`): every live conversation from `channels/live/api.py` (Messenger Page, the owner's personal Messenger shown as "Marketplace · Messenger", SMS, email, listing sites; unknown channels get a generic icon). Left: threads with channel icon, name, last message, time, unread dot and a "Needs you" badge; filters All / Needs you / Unread. Right: the conversation as bubbles with channel and delivery status per message, the five qualification items (lease, move-in, phone, reason, people: exact / vague / missing), drafts waiting for approval with one-click **Approve & send / Edit / Deny**, a reply box for the owner, and the **Activity** drawer: the thread's tool calls, reader parses and verifier catches, with failed steps in red and the step that recovered from them in green ("Errors & recoveries" filters to those). **New conversation** starts a thread (channel, to, text); sending obeys the live allow-list. Polls every 2.5 s.
2. **Assistant**: the owner chats with the operator (`POST /api/runs` with `seed_renters: false`, then `/api/runs/{id}/owner`, events over SSE). Each reply folds its tool calls ("Show 7 tool calls · 44 s", with caught errors and recoveries counted). The right column shows result cards from `/api/runs/{id}/view`: listing preview with per-channel status (Posted / Needs your click with a Publish link), maintenance jobs with quotes and spend vs limit, showings, and the run's escalations with Approve / Edit / Deny.
   Assistant runs are **live** (`live_channels: true`, `console/live_world.py`): `rentus_tools.live.register_live("live")` browser adapters on the owner's logged-in profiles fill the Marketplace / Roomies / Craigslist / PadSplit forms and stop before submit; Google Calendar holds showings; the world holds only the real Appling Way room with the owner-confirmed facts from `channels/pilot_post.py` (photos from `CONSOLE_ROOM_PHOTO_DIR` or `CHANNELS_PHOTO_DIR`, never in the repo). `/api/runs/{id}/posts` reports what really happened per channel: Ready, needs your click (with the filled-form screenshot), Needs login (with the login command), Failed (with the reason), Not connected. The Facebook Page row has **Prepare Page post** (an unpublished post, not visible) and **Publish** (the `channels/pilot_post.py publish` path, then the draft is deleted), both only on the owner's click (`POST /api/runs/{id}/listings/{lid}/facebook {action}`; `CONSOLE_FB_MODULE` swaps in a fake for tests). Verifier flags are shown under the operator's reply.
3. **Pipeline**: one row per person from the live threads, stage inquiry → qualifying → qualified → showing → application, qualification dots, last message; a row opens the thread in the Inbox.
4. **Model**: held-out evaluation (pass rate and mean reward with 95% CIs per config, paired Holm-corrected comparisons, per category), the reader's exact match against Claude Opus 5.5, Lightning prompted, the rules fallback and the untuned base (Wilson intervals), vLLM serving (prefix caching on/off, reasoning off/on, operator load vs reader latency on one GPU), and the parameter budget. Every number comes from `/api/results`, `/api/trust` and `/api/performance` at request time; `/api/results` uses the newest held-out protocol version that has both a baseline and a final run (`gym/results/v3-heldout-*` once they land, v2 until then), skipping runs still in progress.

`/approve` is the phone page: every open approval (live drafts plus the Assistant run's escalations) with the renter's last message, the reason, the drafted reply and Approve / Edit / Deny. The console listens on 127.0.0.1 only; `scripts/tailnet_forward.py` relays it to this machine's Tailscale address. There is no login: the tailnet is the access control.

If `channels/live/api.py` is missing, fails to import, raises or takes longer than `CONSOLE_LIVE_TIMEOUT_S` (8 s), the live endpoints answer with `available: false` and the pages show a clean empty state. `CONSOLE_LIVE_MODULE` swaps the module (tests use `console/tests/fake_live.py`, synthetic data).

The older one-click demo director (`/api/demo`), fault injection and scenario endpoints still work over the API for scripts; the page no longer exposes them.

## Verification

`channels/.venv/bin/python scripts/console_verify.py all` drives the UI with Playwright and writes screenshots to `docs/img/`: every tab in light and dark, a live inbox thread with its Activity drawer, the approval flow (Edit sends the owner's text; phone Approve) on a second console process wired to the fake channels so nothing reaches a real person, the Model numbers checked against the endpoints, the live `/approve`, and a live Assistant listing run (`assistant`, uses the GPU).

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
| GET | `/approve`, `/api/approvals` | phone view; the active run's escalations (open first) |
| GET | `/api/live/status` `/api/live/threads` `/api/live/threads/{id}` | live channels: per-channel connection, thread list, one thread with messages and trace |
| POST | `/api/live/threads/{id}/reply` `/api/live/conversations` | owner reply `{text}`; new conversation `{channel, to, text}` |
| GET/POST | `/api/live/approvals` `/api/live/approvals/{id}` | live drafts plus the Assistant run's open escalations (`run:<run_id>:<esc_id>`); decide `{decision: approve\|edit\|deny, text?, source?}` |
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
