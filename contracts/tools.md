# Contract: tools, world state, errors, events, scenarios

Every workstream builds against this file. Change it only here, and note the change in `BRIEF.md`. Language is Python 3.12 everywhere (NeMo Gym is Python).

## 1. Package layout

```
tools/        rentus_tools package: schemas + implementations (W3)
  schemas.py  TOOLS: list[dict] in OpenAI function-calling format, generated from one source of truth
  world.py    World: the sandbox state (load/save JSON, snapshot, diff)
  impl/*.py   one module per tool group
  faults.py   fault injection
  live/       live adapters (real platforms), same signatures, W8 fills these
operator/     rentus_operator package: agent loop + verifier (W2)
gym/          NeMo Gym resources server + tasks + scorers (W4)
console/      FastAPI app + single-page UI (W7)
contracts/    this file
```

Calling convention: `rentus_tools.call(world, name: str, args: dict) -> dict`. It validates args against the schema, applies faults, runs the tool, appends an event, and returns a result envelope. It never raises for tool-level problems.

## 2. Result envelope

```json
{"ok": true,  "data": { ... }}
{"ok": false, "error": {"code": "INVALID_ARGS|NOT_FOUND|CONFLICT|RATE_LIMITED|TIMEOUT|LOGIN_REQUIRED|PAGE_CHANGED|UPSTREAM_ERROR|POLICY_BLOCKED|BUDGET_EXCEEDED",
                         "message": "human readable", "retryable": true, "hint": "optional: what to try instead"}}
```

`POLICY_BLOCKED` means a business rule refused the action (for example proposing a showing before the qualifying gate is complete). The operator must not retry those blindly.

## 3. World state (sandbox)

One JSON document, loaded from `data/published/inventory.json` plus a scenario's `initial_state` patch.

```
rooms[]          room_id, area, zip, address_public, type, private_bath, rent, deposit, utilities, available_from, pets, lease_min_months, photos[]
listings[]       listing_id, room_id, status(draft|live|filled|removed), title, body, price, channels{channel: {post_id, status, url}}
channels         marketplace | roomies | craigslist | padsplit | sms | email  (each: posts[], threads[])
threads[]        thread_id, channel, renter_name, language, messages[{id, from(renter|operator), text, attachments[], ts}]
register[]       renter_id, thread_ids[], name, phone, gate{lease, move_in, phone, reason, occupants}, wants{area, budget, type, private_bath}, status, listing_of_interest
calendar[]       event_id, title, start, end, status(available_block|proposed|confirmed), renter_id
vendors[]        vendor_id, name, trade, phone, rating, service_area, responds(bool), quote_range[min,max]
quotes[]         quote_id, vendor_id, job_id, amount, eta, status
jobs[]           job_id, property, issue, severity, status, vendor_id, cost
escalations[]    esc_id, reason, thread_id|job_id, draft, created_at
policy           spend_limit_usd, showing_hours, lease_min_months_public=12, lease_floor_months=6
clock            "now" (scenarios set it; tools never read the wall clock)
```

## 4. Tools

Arguments are JSON. All return the envelope above; the `data` shape is listed.

| Group | Tool | Args | data |
|---|---|---|---|
| Inventory | `list_rooms` | `available_by?` date, `area?` | `rooms[]` |
| | `get_room` | `room_id` | `room` |
| | `update_room` | `room_id`, `fields{}` | `room` |
| Listings | `create_listing` | `room_id`, `title`, `body`, `price` | `listing` (draft) |
| | `publish_listing` | `listing_id`, `channel` | `{post_id, url, status}` (sandbox: live; live adapters: `ready_to_submit` with `screenshot`) |
| | `update_listing` | `listing_id`, `fields{}` | `listing` |
| | `mark_filled` | `listing_id` | `listing` (removes from all channels) |
| | `get_listing_media` | `room_id` | `photos[{name, url}]` |
| | `check_listing_compliance` | `text` | `{ok, findings[{phrase, rule, suggestion}]}` (deterministic, 24 CFR 100.75 phrase rules) |
| Market | `get_market_rent` | `zip`, `bedrooms?` | `{zori, source, as_of}` |
| Inbox | `list_threads` | `channel?`, `unanswered_only?` | `threads[]` (summaries) |
| | `read_thread` | `thread_id` | `thread` |
| | `send_message` | `thread_id`, `text`, `attachments?[]` | `{message_id}`; refused with `POLICY_BLOCKED` if text breaks style rules (>2 sentences, >1 question, long dashes) or quotes a price/term not in the room record |
| Reader | `read_reply` | `thread_id` or `text`, `pending_item?` | reader JSON (`data/reader_schema.md`); backed by the ≤1.5B reader when served, else a deterministic fallback |
| Register | `upsert_renter` | `thread_id`, `fields{}` | `renter` |
| | `match_renters` | `room_id` | `matches[{renter_id, score, reasons[]}]` |
| Calendar | `find_showing_slots` | `room_id`, `date_from`, `date_to` | `slots[]` |
| | `propose_showing` | `renter_id`, `room_id`, `start` | `event` (status proposed); `POLICY_BLOCKED` unless the renter's gate is complete |
| Ops | `web_search` | `query` | `results[{title, url, snippet}]` (sandbox: from vendor fixtures) |
| | `fetch_page` | `url` | `{text}` |
| | `find_vendors` | `trade`, `zip` | `vendors[]` |
| | `request_quote` | `vendor_id`, `job_id`, `description` | `quote` or `TIMEOUT` when the vendor doesn't respond |
| | `book_vendor` | `quote_id` | `job`; `BUDGET_EXCEEDED` above `policy.spend_limit_usd` |
| | `create_job` | `property`, `issue`, `severity` | `job` |
| Owner | `escalate_to_owner` | `reason`, `ref_id`, `draft?` | `escalation` |
| | `report_to_owner` | `summary` | `{ok}` |

## 5. Faults (for the Gym and the "break something" button)

`world.faults` is a list of `{tool, kind, times, after?}` where `kind` is `timeout | rate_limited | malformed | login_required | page_changed | upstream_error | not_found`. `malformed` returns `ok: true` with a corrupted `data` (missing fields, wrong types) so the verifier has to catch it. `times` counts how many calls fail before the tool recovers.

## 6. Events (what the console and scorers read)

Append-only JSONL, one line per event, written to `runs/<run_id>/events.jsonl` and streamed over SSE by the console.

```json
{"ts": "2026-10-17T14:03:11Z", "run_id": "r_abc", "seq": 12, "type": "tool_call|tool_result|model_message|verifier|retry|fallback|escalation|owner_message|renter_message|score",
 "actor": "operator|reader|verifier|renter:<id>|vendor:<id>|owner|system", "data": { ... }}
```

## 7. Scenarios (Gym tasks)

JSONL, one task per line, in `gym/tasks/{train,heldout}.jsonl`. Held-out tasks are never used for tuning prompts or training.

```json
{"id": "lease-vague-date-es-003", "split": "heldout", "category": "leasing|listing|ops|recovery",
 "owner_instruction": "optional text the owner types",
 "initial_state": {"...": "patch over inventory"},
 "counterparts": [{"id": "renter:maria", "channel": "marketplace", "language": "es",
                   "script": [{"after": "start", "say": "Hola, ¿sigue disponible el cuarto?"},
                              {"when_asked": "move_in", "say": "a fines de mes"},
                              {"when_asked": "move_in", "say": "el 30 de octubre"}]}],
 "faults": [{"tool": "publish_listing", "kind": "page_changed", "times": 1}],
 "max_turns": 30,
 "checks": [{"type": "state", "path": "register[renter:maria].gate.move_in.date", "equals": "2026-10-30"},
            {"type": "never", "tool": "propose_showing", "before": "gate_complete"},
            {"type": "style", "rule": "max_two_sentences"}]}
```

Counterparts are scripted (no model), driven by `when_asked` matching on the operator's last question; source utterances come from the published datasets. Scores: each check is pass/fail; a task passes when all checks pass; we report task pass rate plus per-check rates.
