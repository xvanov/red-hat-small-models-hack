# W8 channels

Browser automations for the listing platforms (marketplace, roomies, craigslist, padsplit), local mock copies of
those sites for the Gym and the demo, an operator-driven selector self-repair loop, and a Facebook Page Graph adapter.

**Safety defaults.** Browser adapters fill the whole form, upload photos, screenshot, and stop before the final
button (`status: ready_to_submit`). `submit=True` only works against mocks. Inbox reading and sending only work
against mocks. Facebook posts are created with `published=false`. See `LOGIN.md` for how the owner logs in.

## Quick start

```bash
cd <repo root>
uv venv channels/.venv --python 3.12 && uv pip install --python channels/.venv/bin/python -r channels/requirements.txt
channels/.venv/bin/playwright install chromium

channels/.venv/bin/python -m channels.mock_sites --port 8765        # mock sites + control panel at http://127.0.0.1:8765/
channels/.venv/bin/python -m channels.publish all                   # fill every mock form, stop before submit
channels/.venv/bin/python -m pytest -q channels/tests               # 27 tests, ~2 min
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
| `login.py`, `publish.py` | Owner CLIs. |
| `../tools/rentus_tools/live/channels_adapter.py` | `LiveAdapter` for W3's tools: `register_all("mock"|"live")` routes `publish_listing`/`send_message` here when `world.mode == "live"`. Live `send_message` only returns a draft. |

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

## Known limitations

- Live selector files are unverified guesses until the owner logs in and the first live run repairs them.
- Live inboxes are not automated (Facebook: conversation count via Graph only). Replies on real platforms stay with the owner.
- Facebook's own Marketplace dropdowns are custom comboboxes (`choose` action); the address field's autocomplete may need a repair or a manual pick.
- The sync Playwright API can't run inside an asyncio event loop; call adapters from a worker thread in async servers.
- Mock data (names, messages, photos) is synthetic; sample photos are generated gradients (`mock_sites/make_sample_photos.py`).
