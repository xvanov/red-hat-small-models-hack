# rentus_tools (W3)

Sandbox tools for the Rentus Operator, implementing `contracts/tools.md`. Python 3.12. The only dependency is `jsonschema`, and even that is optional: without it a small built-in validator takes over, so the package imports with nothing installed.

## Install or import

```bash
uv venv tools/.venv --python 3.12
uv pip install --python tools/.venv/bin/python -e 'tools[test]'
tools/.venv/bin/python -m pytest tools -q          # 180 tests
```

Or skip the install and put `tools/` on `sys.path` (gym and operator already do this).

## Use

```python
import rentus_tools as rt

world = rt.load(patch=task["initial_state"])        # data/published/inventory.json + vendor fixtures + patch
world.faults = task.get("faults", [])
sink = rt.EventSink.for_run("r_abc")                 # runs/r_abc/events.jsonl (or rt.EventSink() in memory)

tools = rt.tool_schemas("verbose")                   # OpenAI function-calling list; rt.TOOLS is the same
res = rt.call(world, "list_rooms", {"area": "Durham"}, sink=sink)
# {"ok": true, "data": {...}}  or  {"ok": false, "error": {"code", "message", "retryable", "hint"?, "details"?}}

before = world.snapshot(); ...; changes = rt.diff(before, world)
rt.get_path(world, "register[renter:maria].gate.move_in.date")   # the scenario check path syntax
rt.gate_complete(world, "renter:maria")
world.save("runs/r_abc/world.json"); rt.load_file("runs/r_abc/world.json")
```

`call()` never raises for tool problems. It parses string args, validates them against the schema (an `INVALID_ARGS` error names the bad argument and lists the expected ones), applies faults, runs the tool, and writes `tool_call` and `tool_result` events, plus `escalation` and `owner_message` events for the owner tools. If `sink` is omitted it uses `world.sink` when set. Any exception inside a tool comes back as `UPSTREAM_ERROR`.

The sandbox clock is `world.clock["now"]`. Tools never read the wall clock; scenarios and the gym move time forward with `world.advance(minutes=...)`.

### Patches

`load(patch=...)` deep-merges dicts. Record lists (rooms, listings, threads, register, calendar, vendors, quotes, jobs, escalations) are upserted by id: `{"rooms": [{"room_id": "R023", "rent": 750}]}` changes one field of R023. `{"vendors": {"$replace": []}}` replaces a value outright.

## Tools

| Group | Tools | Rules the tool enforces |
|---|---|---|
| Inventory | `list_rooms`, `get_room`, `update_room` | editable fields only, typed values |
| Listings | `create_listing`, `publish_listing`, `update_listing`, `mark_filled`, `get_listing_media`, `check_listing_compliance` | price must equal the room's rent and any `$` figure must be in the room record (`POLICY_BLOCKED`, hint: `update_room` first); publishing is refused while the fair-housing check finds a violation (gender wording in a shared room is a `warning` the owner decides, D23); one active listing per room (`CONFLICT`) |
| Market | `get_market_rent` | Zillow ZORI for NC ZIPs, from `data/raw/zori/zori_nc.csv` when present, else the committed `rentus_tools/data/zori_nc_latest.csv` (rebuild it with `scripts/build_zori_table.py`) |
| Inbox | `list_threads`, `read_thread`, `send_message` | `POLICY_BLOCKED` for more than 2 sentences, more than one `?` (the owner's two-part lease question, EN/ES, counts as one), third-person references to the owner (rule `first_person`, `impl/demand_guards.py`), a house number before the renter's showing is confirmed (rule `address_private`; listings refuse one always, `address_public`), em or en dashes, a dollar figure not in the thread's room/listing record, or a lease term shorter than `policy.lease_min_months_public`; a term at or above `policy.lease_floor_months` (6) only once the renter has asked for a shorter lease (D23); a sentence telling the renter a showing/time is confirmed, booked, scheduled, set or agreed (EN/ES: "confirmado", "agendado", "quedamos", "see you Saturday") unless that renter has a calendar event with status `confirmed` (rule `showing_not_confirmed`, hint: say "proposed, pending the owner's confirmation"; questions and pending wording pass); a draft clearly in the other language from the renter's (stopword ratio, renter's latest clear message else `thread.language`; rule `language_mismatch`, `details.rewrite: true`) (`impl/guards.py`) |
| Reader | `read_reply` | reader JSON per `data/reader_schema.md`, plus `backend` (`model` or `fallback`) |
| Register | `upsert_renter`, `match_renters` | gate items use the reader's shapes (`{"status","value"}`, move_in `{"status","date","raw"}`); scalar shorthand accepted (`"lease": true`, `"move_in": "2026-11-01"`); phones normalized to E.164 |
| Calendar | `find_showing_slots`, `propose_showing` | `POLICY_BLOCKED` unless lease is an explicit answer (status `answered` and value true, or `months` >= `policy.lease_floor_months`; when `months` is given it decides), move_in has an exact date (`answered` or `exception`), and phone, reason and occupants are filled; occupants must fit `max_occupants`; slots stay inside `policy.showing_hours` |
| Ops | `web_search`, `fetch_page`, `find_vendors`, `create_job`, `request_quote`, `book_vendor` | `create_job` resolves `property` (room id, street address, or text with a ZIP) against the rooms and returns the job with `room_id`, `address`, `zip`, `area`; `find_vendors` takes `zip` or `job_id` (uses the job's zip), and its `INVALID_ARGS` hints say where a zip comes from; vendors with `responds: false` return `TIMEOUT` (not retryable, hint: try another vendor); `BUDGET_EXCEEDED` above `policy.spend_limit_usd` (default $500); quote amounts are deterministic within each vendor's range |
| Owner | `escalate_to_owner`, `report_to_owner` | `ref_id` must exist (thread, job, renter, listing, quote, room or event) |
| Concierge (`impl/demand.py`; exposed only by `tool_schemas("concierge")`, not in the default 26) | `listing_disclosure`, `capture_demand`, `match_inventory`, `search_external_rooms`, `park_prospect`, `log_followup`, `due_followups`, `cluster_report` | demand record on the register row under `demand` (criteria, status `new/contacted/qualifying/qualified/sourcing/parked/applied/placed/closed`, sources, listing_of_interest + history, sourcing, reconnect_at, followup); a second channel with the same phone/email merges into one row; matching hard gates per spec §5.4 (type, budget >15% below rent, occupants, known banned pet, stay below the 6-month floor, stated private bath, area not in or next to the stated set; unknowns never disqualify; 2 stated criteria needed); area phrases resolve to sets (airport, "between X and Y", adjacency); sourcing searches `fixtures/demand_external_rooms.json` (fictional) and sets a due date `policy.sourcing_days` (3) out; `park_prospect` resolves a named month to the 1st, an exact date to itself, nothing to +30 days; cadence 12,12,12,12,24,24,48,96 h then doubling, reset on reply; `cluster_report` WATCH at 3 active, SUPPLY SIGNAL at 5 qualified (gate complete, budget stated, not proxy), else "nominal" |

Hidden simulator truth (`vendors[].responds`, `vendors[].quote_range`) never appears in tool output.

### Tool descriptions (ablation)

`schemas.DESCRIPTIONS` holds two wordings, `verbose` and `terse`, keyed `"tool"` and `"tool.param"`. `rt.tool_schemas("terse")` swaps all of them at once, and `rt.tool_schemas("verbose", descriptions={"send_message": "..."})` overrides single entries. Argument schemas (`schemas.PARAMS`) do not change between variants.

### Reader

When `READER_BASE_URL` is set, `read_reply` posts to `$READER_BASE_URL/chat/completions` with model `$READER_MODEL` (default `rentus-reader`), optional `READER_API_KEY`, and the shared prompt from `reader/prompt.py`. A network error or invalid JSON falls back to the deterministic reader `rentus_tools.impl.reader.read_reply_fallback(text, pending_item=None, context=None, today=None)`: English and Spanish regex rules for dates (with the ambiguous `1/11` rule), phones, occupants, lease answers, reasons, intents and language. Measure it with `scripts/eval_reader.py dev|test`; tune on dev only.

## Owner actions (not operator tools)

`owner_confirm_showing` is reachable only from the owner path; it is not in `PARAMS`, `REGISTRY` or any tool list, so `rt.call()` answers a model that names it with `INVALID_ARGS` (unknown tool).

```python
from rentus_tools.impl.demand_owner import owner_call
owner_call(world, "owner_confirm_showing", {"event_id": "E001", "decision": "confirm"}, sink=sink)
```

Endpoint contract for the console `/approve` flow (lane 1 wires it; suggested route `POST /api/showings/<event_id>/decision`):

- request JSON `{"decision": "confirm" | "reject", "note"?: string, "housemate"?: bool}`
- response: the envelope from `owner_call`. Success `data` = `{event, renter_id, thread_ids, next_step}`; a repeated identical decision returns `{event, already: true}` and changes nothing (first signal wins); `NOT_FOUND` for an unknown event, `CONFLICT` when the event is not `proposed` (for example confirming a rejected one).
- confirm: event `status` `confirmed`, `on_the_way_by` = start minus 1 hour, `decided_by` `owner`; the renter row becomes `showing_confirmed`; open escalations on that event are resolved. After it, hand the operator `data.next_step` (tell the renter once that the time is confirmed, then the one-hour rule as its own message; the address may now be sent).
- reject: event `status` `rejected` (the slot is free again); the renter row returns to `qualified`; the operator offers another slot or closes politely.
- events: `tool_call` / `tool_result` with actor `owner`, then `owner_message` `{summary, decision, event}`.

## Faults

Set `world.faults` to a list of `{tool, kind, times=1, after=0, match?}`:

- `tool`: a tool name, or `"*"` for any tool
- `kind`: `timeout`, `rate_limited`, `upstream_error` (retryable), `login_required`, `page_changed`, `not_found` (not retryable), or `malformed`
- `after`: let this many matching calls succeed first; `times`: then fail this many before recovering
- `match` (an extension to the contract): an args subset, for example `{"channel": "marketplace"}`

An error fault skips the tool, so nothing changes. `malformed` runs the tool (side effects happen) and then returns `ok: true` with the data deterministically corrupted: a key dropped and another given the wrong type, for the verifier to catch. With `field` (for example `"rent"`) the fault corrupts that key wherever it appears instead (`field_mode`: `wrong_type`, the default, or `drop`). Fault counters (`_seen`, `_fired`) live on the fault dicts, so they show up in snapshots. Invalid arguments never consume a fault.

## Live mode

`world.mode = "live"` routes `publish_listing` and `send_message` through `rentus_tools.live`. W8 registers real adapters with `live.register(channel, adapter)`; unregistered channels use `StubAdapter`. Adapters stop before submit and return `{"status": "ready_to_submit", "screenshot": path}`. Nothing is marked live and no message is marked sent until the owner submits.

## Files

```
rentus_tools/
  __init__.py   public API          core.py     call(), validation, registry
  schemas.py    PARAMS + DESCRIPTIONS -> tool_schemas()
  world.py      World, load, merge, diff, get_path, save
  faults.py     fault injection     events.py   EventSink
  errors.py     ToolError + envelope
  impl/         inventory, listings, compliance (+ compliance_rules.md), market, inbox, style, reader, register, calendar, ops, owner
  live/         adapter interface + stub
  fixtures/vendors.json   12 fictional Durham-area vendors (555-01xx phones)
  data/zori_nc_latest.csv ZORI fallback table
scripts/  build_zori_table.py, eval_reader.py
tests/    pytest suite
```
