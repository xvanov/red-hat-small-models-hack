# Channels (W8, lane 3)

Browser automations for the listing platforms (marketplace, roomies, craigslist, padsplit), local mock copies of
those sites for the Gym and the demo, an operator-driven selector self-repair loop, a Facebook Page Graph adapter,
and two inbound conversation channels: **email** (platform lead emails read over IMAP) and **SMS** (drafts only).

**Safety defaults.** Browser adapters fill the whole form, upload photos, screenshot, and stop before the final
button (`status: ready_to_submit`). `submit=True` only works against mocks; on live targets a click guard also
refuses any button that reads like publish, submit or send. Browser inbox reading and sending only work against
mocks. Email and SMS replies are saved as drafts with a reason (`status: draft_saved`) and never sent; the IMAP
reader is read-only and refuses to run until the owner confirms the inbox. Facebook posts are created with
`published=false`, except the one owner-approved pilot post (D20, `pilot_post.py`). See `LOGIN.md` for the owner's
5-minute login checklist.

## Quick start

```bash
cd <repo root>
uv venv channels/.venv --python 3.12 && uv pip install --python channels/.venv/bin/python -r channels/requirements.txt
channels/.venv/bin/playwright install chromium

channels/.venv/bin/python -m channels.mock_sites --port 8765        # mock sites + control panel at http://127.0.0.1:8765/
channels/.venv/bin/python -m channels.publish all                   # fill every mock form, stop before submit
channels/.venv/bin/python -m pytest -q channels/tests               # 52 tests, ~2 min
```

## Layout

| Path | What |
|---|---|
| `mock_sites/` | FastAPI app. Per platform: multi-step listing form (required fields, hidden or visible photo input, review step, final button), inbox, thread pages, login wall. `specs.py` defines fields in two layouts. |
| `adapters/api.py` | Contract signatures: `publish_listing(listing, channel, target)`, `list_threads(channel, unanswered_only)`, `read_thread(thread_id)`, `send_message(thread_id, text)`. Return the contract envelope, never raise. Thread ids are `<channel>:<id>`. |
| `adapters/engine.py` | Generic runner: reads a selector file, executes its `flow`, checks the login wall and validation errors, screenshots, stops before submit. No platform DOM in code. |
| `adapters/selectors/{mock,live}/<platform>.json` | `elements` (selector, action, description), `flow` (ordered steps), `changelog`. The only thing repair edits. |
| `adapters/values.py` | Contract listing + room -> per-platform values (e.g. PadSplit weekly price = monthly x 12 / 52). |
| `repair/` | Self-repair loop (below). |
| `facebook_page.py` | Graph API: unpublished photo post, Page check, conversation count. |
| `pilot_post.py`, `pilot_shadow.py` | D20 pilot: operator-written published post; shadow inbox (drafts only). |
| `login.py`, `publish.py` | Owner CLIs. |
| `inbound/` | Email + SMS: `email_parse.py` (lead email -> `Lead`), `imap_reader.py` (read-only IMAP), `store.py` (threads + drafts outboxes in `channels/.inbox/`, gitignored), `email_channel.py`, `sms.py` (outbox, disabled `TwilioSender`), CLI `python -m channels.inbound`. |
| `tests/fixtures/email/` | Hand-written fake notification emails (Roomies, Furnished Finder, Zillow, craigslist relay, a direct Spanish email, two non-leads). |
| `../tools/rentus_tools/live/channels_adapter.py` | `LiveAdapter` for W3's tools: `register_all("mock"|"live")` routes `publish_listing`/`send_message` here when `world.mode == "live"`. Live `send_message` only returns a draft. |
| `../tools/rentus_tools/live/calendar_adapter.py` | Google Calendar behind `find_showing_slots`/`propose_showing` in live mode (D29): slots only inside "Available for showings" events (`CHANNELS_SHOWINGS_AVAILABILITY_TITLE`, case-insensitive) clipped to 08:00-20:00, or the full 08:00-20:00 on a day with no such block; only showing events ("PROPOSED: Showing ...", "Showing with ...") block, for every room (no overlaps); the owner's other events and other calendars are ignored (R-SHOW-3); real NY clock, one `PROPOSED: Showing with <first name>` event only on `CHANNELS_SHOWINGS_CALENDAR_ID`, no attendees, `sendUpdates=none`. Dry run: `PYTHONPATH=tools channels/.venv/bin/python -m rentus_tools.live.calendar_adapter slots`. |
| `../tools/rentus_tools/live/inbound_adapter.py` | Email/SMS `LiveAdapter`s: `send_message` -> `draft_saved`; in live mode `list_threads`/`read_thread` first sync the inbound store into `world.threads`. `live.register_live("live")` registers all six channels in one call. |

## Live channels (lane 3)

```python
from rentus_tools import live
live.register_live("live")      # marketplace/roomies/craigslist/padsplit on the owner's profiles + email + sms
world.mode = "live"             # publish_listing -> fill and stop; list_threads/read_thread include inbound
                                # email/SMS threads; send_message on email/sms -> {"status": "draft_saved", ...}
```

| Channel | Live without login | Needs the owner |
|---|---|---|
| craigslist | Real anonymous flow (Raleigh > housing offered > rooms & shares), details form fully filled, stops with `stage: details_form_filled` | Login (or `CHANNELS_CONTACT_EMAIL`) to reach images + preview; stops before **publish** |
| Roomies | `LOGIN_REQUIRED` (Cloudflare check) with the login command | `channels.login roomies` |
| PadSplit | `LOGIN_REQUIRED` (redirect to sign-in) with the login command | `channels.login padsplit` |
| Email | Parser + store + drafts on `.eml` files (`email-import`) | Inbox choice: `CHANNELS_IMAP_CONFIRMED=1` + login vars, then `email-poll` |
| SMS | Outbox drafts; inbound texts added by hand (`sms-add`) | Nothing (sending stays disabled) |

Craigslist's selector file is marked `verified` for the steps observed on the real site (see its `verified_note`);
Roomies and PadSplit form fields are unverified until the first logged-in run, when the repair loop fixes them.

Live selector-file keys added for real sites: `bot_wall_title` (regex on the page title, e.g. Cloudflare),
`expect_url_contains` (a redirect away from the form means not logged in), `forbidden_click_url`, per-step
`url_contains` (run the step only on that page), `exact` on `choose`, `press` after `fill`, and the
`stop_if_empty` step (stop with a partial fill when a value only an account provides is missing).

## Email and SMS (drafts only)

Lead emails from Roomies, Furnished Finder, the Zillow family (Zillow, Trulia, HotPads), craigslist reply relays,
PadSplit and Facebook, plus direct renter emails, become one thread per renter per platform (`email:<hash>`), with
`source_platform`, `reply_via` (`email` | `relay` | `platform`), `contact`, `listing_ref` and `lead_facts`
(move-in, stay length, budget, occupants when the email has them). Notifications without a renter message
(digests, password resets, receipts) are skipped. Threads that read as Spanish get `language: "es"`, so the
send guard keeps replies in Spanish.

A reply goes to `channels/.inbox/email_drafts.jsonl` or `sms_outbox.jsonl` with `sent: false` and a reason,
for example "This lead came from Roomies; reply inside Roomies (its emails are notifications, not a mailbox)".
`send_message`'s guards (style, language, prices, lease terms, first person) run before any draft is written.

`TwilioSender` in `inbound/sms.py` is the seam for a future real send. It is disabled: `send()` always raises,
it never reads `TWILIO_*`, and nothing in this repo turns it on. Enabling it is the owner's decision and needs a
per-message approval step, the owner's existing communications guard in front of it, opt-out handling, and
number registration (10DLC or toll-free).

## Real-world pilot (D20)

The owner approved one real, published Page post for the Appling Way room. The operator wrote it; replies stay with the owner.

```bash
operator/.venv/bin/python -m channels.pilot_post draft                          # live operator -> runs/pilot/operator_listing.json
channels/.venv/bin/python -m channels.pilot_post publish runs/pilot/post_final.txt PHOTO...   # PUBLISHED post, <=4 photos, EXIF stripped
channels/.venv/bin/python -m channels.pilot_post delete POST_ID

# shadow inbox: polls Page conversations every 180 s, runs the operator in a sandbox per conversation,
# writes drafts to runs/pilot/shadow.jsonl and counters to runs/pilot/stats.json. GET requests only, never sends.
nohup operator/.venv/bin/python -m channels.pilot_shadow > runs/pilot/shadow.log 2>&1 &
operator/.venv/bin/python -m channels.pilot_shadow --selftest "Is the room still available?"   # synthetic, no Graph
```

**Stop the shadow reader:** `pkill -f "channels.pilot_shadow"`

`runs/pilot/shadow.jsonl` and `runs/pilot/threads/` hold real renter text: gitignored, never commit them.
The shadow config is the best held-out Gym row (prompt v3, renter guard, style pre-check, reasoning history).

## Mock switches ("page changed", "login wall")

Control panel at `/` has links. Programmatic:

```bash
curl -X POST localhost:8765/_admin/config -H 'content-type: application/json' -d '{"marketplace":{"layout":"v2"}}'
curl -X POST localhost:8765/_admin/config -H 'content-type: application/json' -d '{"craigslist":{"login_wall":"on"}}'
curl -X POST localhost:8765/_admin/padsplit/threads -H 'content-type: application/json' -d '{"renter_name":"Ana","text":"¿Sigue disponible?"}'
curl -X POST localhost:8765/_admin/reset
```

Or at start-up: `MOCK_LAYOUTS=marketplace=v2,roomies=v2 MOCK_LOGIN_WALL=craigslist`.
`v2` renames labels, ids, names, test ids, button text and inbox markup, which breaks almost every selector in the
shipped mock files. A login wall makes adapters return `LOGIN_REQUIRED`.

## Self-repair loop

When an element's selector stops matching (`PAGE_CHANGED`):

1. `repair/snapshot.py` captures the visible interactive elements (with a selector computed to be unique among
   visible elements), repeated data-carrying elements (inbox rows, messages), and a truncated ARIA snapshot.
2. `repair/proposers.py` `OperatorProposer` sends the element's description, action, old selector and the candidate
   list to the **operator model** (OpenAI-compatible API, env `OPERATOR_BASE_URL`, `OPERATOR_MODEL`,
   `OPERATOR_API_KEY`), asking for JSON `{index, selector?, reason}`. Same Nemotron Lightning that runs the operator;
   no extra model.
3. `repair/loop.py` validates each proposal on the live page: exactly one visible match (file inputs: one attached),
   the right element kind for the action, not already another field's element, row ids matching `attr_pattern`,
   message authors mapping to renter/operator.
4. The winner is written into the selector file with a `changelog` entry (old, new, proposed_by, reason, url) and a
   line in `repair/changelog.jsonl`. The step is retried.
5. For clicks, the runner checks the page actually progressed. If a freshly repaired click did nothing, the repair is
   reverted (logged as `verifier`) and the loop runs again with that selector excluded.

**Measured 2026-10-17** against the mocks' v2 redesign with the served `nemotron-3.5-lightning`: all four forms
repaired (55 selectors, about 35 s per form, most of it the 2.5 s wait per broken selector), every submitted field
correct, zero rejected proposals. The inbox rows, message author map, composer and send button repaired too.

With no model reachable, repair is off unless `CHANNELS_REPAIR_FALLBACK=heuristic` enables the offline word-overlap
fallback (not a model; it's what the offline tests use). Every changelog entry says which one produced the fix.

Demo: start the mocks, switch marketplace to v2 in the control panel, run `python -m channels.publish marketplace`,
and show `adapters/selectors/mock/marketplace.json`'s changelog. Switching back to v1 breaks and repairs again.
To restore the shipped files: `git checkout channels/adapters/selectors/mock`.

## Env vars

| Var | Use |
|---|---|
| `MOCK_BASE_URL` | mock server for adapters, default `http://127.0.0.1:8765` |
| `OPERATOR_BASE_URL`, `OPERATOR_MODEL`, `OPERATOR_API_KEY` | operator model for repair (default `http://localhost:8000/v1`; model id auto-detected from `/models`; `publish.py` loads them from the repo `.env`) |
| `CHANNELS_REPAIR_FALLBACK=heuristic` | allow the offline fallback proposer |
| `CHANNELS_TIMEOUT_MS` | wait per selector (default 2500 mock, 12000 live) |
| `CHANNELS_HEADLESS=1` | run live sessions headless (default headed) |
| `FB_ENV_FILE` | env file holding `FACEBOOK_PAGE_ID`, `FACEBOOK_PAGE_ACCESS_TOKEN` |
| `CHANNELS_CONTACT_EMAIL` | contact email for craigslist when the account doesn't prefill it |
| `CHANNELS_INBOX_DIR` | inbound store (threads + drafts), default `channels/.inbox/` |
| `CHANNELS_IMAP_CONFIRMED`, `CHANNELS_IMAP_USER`, `CHANNELS_IMAP_PASSWORD`, `CHANNELS_IMAP_HOST`, `CHANNELS_IMAP_PORT`, `CHANNELS_IMAP_FOLDER` | IMAP inbox (read-only); nothing connects until `CONFIRMED=1` |
| `CHANNELS_IMAP_ENV_FILE`, `CHANNELS_IMAP_USER_VAR`, `CHANNELS_IMAP_PASSWORD_VAR` | read the login from another env file by variable name (e.g. `GMAIL_USER`) |
| `CHANNELS_SHOWINGS_CALENDAR_ID` | the ONLY calendar showing events are created on (unset = nothing is written); also the only calendar read (availability blocks + showings) |
| `CHANNELS_SHOWINGS_AVAILABILITY_TITLE`, `CHANNELS_SHOWINGS_HOURS`, `CHANNELS_SHOWINGS_SLOT_MINUTES`, `CHANNELS_SHOWINGS_TZ` | availability-block title (default `Available for showings`); hours (default `08:00-20:00`), slot length (30), zone (`America/New_York`) |
| `CHANNELS_GOOGLE_ENV_FILE`, `CHANNELS_GOOGLE_CREDENTIALS_VAR` | where the service account lives (default `~/rental-management/.env.production`: `GOOGLE_SERVICE_ACCOUNT_EMAIL` + `GOOGLE_PRIVATE_KEY`) |

## Known limitations

- Live selector files are unverified guesses until the owner logs in and the first live run repairs them.
- Live browser inboxes are not automated (Facebook: conversation count via Graph only). Their renters' messages
  reach the operator through the platforms' notification emails (email channel); replies stay drafts.
- The lead-email patterns are written from the general shape of those notifications, not real ones; anything they
  miss falls back to the first prose paragraph (`confidence: "fallback"`). Check the first real poll.
- No SMS reader: there is no read access to the owner's texts, so inbound SMS is entered by hand.
- Facebook's own Marketplace dropdowns are custom comboboxes (`choose` action); the address field's autocomplete may need a repair or a manual pick.
- The sync Playwright API can't run inside an asyncio event loop; call adapters from a worker thread in async servers.
- Mock data (names, messages, photos) is synthetic; sample photos are generated gradients (`mock_sites/make_sample_photos.py`).
