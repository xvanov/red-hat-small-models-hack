# rentus_tools (W3)

Sandbox tools for the Rentus Operator, implementing `contracts/tools.md`. Python 3.12. The only dependency is `jsonschema`, and even that is optional: without it a small built-in validator takes over, so the package imports with nothing installed.

## Install or import

```bash
uv venv tools/.venv --python 3.12
uv pip install --python tools/.venv/bin/python -e 'tools[test]'
tools/.venv/bin/python -m pytest tools -q          # 125 tests
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
| Listings | `create_listing`, `publish_listing`, `update_listing`, `mark_filled`, `get_listing_media`, `check_listing_compliance` | price must equal the room's rent and any `$` figure must be in the room record (`POLICY_BLOCKED`, hint: `update_room` first); publishing is refused while the fair-housing check finds a violation; one active listing per room (`CONFLICT`) |
| Market | `get_market_rent` | Zillow ZORI for NC ZIPs, from `data/raw/zori/zori_nc.csv` when present, else the committed `rentus_tools/data/zori_nc_latest.csv` (rebuild it with `scripts/build_zori_table.py`) |
| Inbox | `list_threads`, `read_thread`, `send_message` | `POLICY_BLOCKED` for more than 2 sentences, more than one `?`, em or en dashes, a dollar figure not in the thread's room/listing record, or a lease term shorter than `policy.lease_min_months_public` |
| Reader | `read_reply` | reader JSON per `data/reader_schema.md`, plus `backend` (`model` or `fallback`) |
| Register | `upsert_renter`, `match_renters` | gate items use the reader's shapes (`{"status","value"}`, move_in `{"status","date","raw"}`); scalar shorthand accepted (`"lease": true`, `"move_in": "2026-11-01"`); phones normalized to E.164 |
| Calendar | `find_showing_slots`, `propose_showing` | `POLICY_BLOCKED` unless lease is an explicit yes (status `answered`, value true), move_in has an exact date (`answered` or `exception`), and phone, reason and occupants are filled; occupants must fit `max_occupants`; slots stay inside `policy.showing_hours` |
| Ops | `web_search`, `fetch_page`, `find_vendors`, `create_job`, `request_quote`, `book_vendor` | vendors with `responds: false` return `TIMEOUT` (not retryable, hint: try another vendor); `BUDGET_EXCEEDED` above `policy.spend_limit_usd` (default $500); quote amounts are deterministic within each vendor's range |
| Owner | `escalate_to_owner`, `report_to_owner` | `ref_id` must exist (thread, job, renter, listing, quote, room or event) |

Hidden simulator truth (`vendors[].responds`, `vendors[].quote_range`) never appears in tool output.

### Tool descriptions (ablation)

`schemas.DESCRIPTIONS` holds two wordings, `verbose` and `terse`, keyed `"tool"` and `"tool.param"`. `rt.tool_schemas("terse")` swaps all of them at once, and `rt.tool_schemas("verbose", descriptions={"send_message": "..."})` overrides single entries. Argument schemas (`schemas.PARAMS`) do not change between variants.

### Reader

When `READER_BASE_URL` is set, `read_reply` posts to `$READER_BASE_URL/chat/completions` with model `$READER_MODEL` (default `rentus-reader`), optional `READER_API_KEY`, and the shared prompt from `reader/prompt.py`. A network error or invalid JSON falls back to the deterministic reader `rentus_tools.impl.reader.read_reply_fallback(text, pending_item=None, context=None, today=None)`: English and Spanish regex rules for dates (with the ambiguous `1/11` rule), phones, occupants, lease answers, reasons, intents and language. Measure it with `scripts/eval_reader.py dev|test`; tune on dev only.

## Faults

Set `world.faults` to a list of `{tool, kind, times=1, after=0, match?}`:

- `tool`: a tool name, or `"*"` for any tool
- `kind`: `timeout`, `rate_limited`, `upstream_error` (retryable), `login_required`, `page_changed`, `not_found` (not retryable), or `malformed`
- `after`: let this many matching calls succeed first; `times`: then fail this many before recovering
- `match` (an extension to the contract): an args subset, for example `{"channel": "marketplace"}`

An error fault skips the tool, so nothing changes. `malformed` runs the tool (side effects happen) and then returns `ok: true` with the data deterministically corrupted: a key dropped and another given the wrong type, for the verifier to catch. Fault counters (`_seen`, `_fired`) live on the fault dicts, so they show up in snapshots. Invalid arguments never consume a fault.

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
