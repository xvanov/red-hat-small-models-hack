# 05. Not now, and reconnect

## Goal

A "not yet" never becomes a "no". Park the person with a date, go quiet, and come back once at the right time. Spec: §3.8 (R-PARK-1 to R-PARK-7), R-PHIL-2 step 3.

## What the real threads show (aggregate)

An explicit "not now" is rare (under 1 in 100); the real "not now" is silence, which ended about 3 in 10 prospect threads. The owner's real follow-ups were short ("are you still interested in the place?"). Reconnecting months later almost never happened in the history, which is exactly the demand the business lost.

## Ideal flow

1. `read_reply` detects timing language (`not_now`) or a hard no (`hard_no`). Timing language always parks; only "found a place", "not interested" without timing, or "stop" closes.
2. Warm reply, no pressure, staying in touch is fine; one question: when do they plan to start looking again, or when would they move?
3. On a timeframe: park (`upsert_renter` status `not_now`) with `paused_reason` (their words) and `reconnect_at` (a named month = the 1st; a date = that date). No answer: 30 days out. Tell the owner once.
4. On `reconnect_at`: re-read the thread, check whether a fitting room is live, then one short message: we spoke before, you mentioned looking again around now, are you starting to look? Name a room only if it is live.
5. Silence after that: gentle cadence (48 hours, then doubling), then close cold at about 45 days. The row stays.
6. Hard no: one short kind close, status `lost`, note to the owner, nothing after.

## Decision points

| They say | Agent does | Owner |
|---|---|---|
| "Not right now" / "maybe later" | Park, ask timeframe | told once |
| "Next spring" | Park, `reconnect_at` = 1st of March (or the month they name) | told once |
| "Found a place" | Kind close, `lost` | report |
| Qualified but moving in months from now | Park with a check-back about a month before move-in, as an owner draft (R-PARK-6) | draft |
| Silent 3 days before the gate finished | One "should I close this out, or are you still looking?" (owner-approved batch, R-GHOST-1) | approve batch |

## Phrasing

Do:
- Sound glad to stay in touch, not disappointed.
- Remind them briefly of what they wanted when you reconnect ("a room near Duke with a private bath").

Don't:
- Ask "why not?" or try to change their mind.
- Send the same "still interested?" line twice.
- Claim a room is available on reconnect without checking.

## Tools

Exists: `read_reply` (`not_now`, `hard_no`), `upsert_renter` (status `not_now`, `lost`), `list_rooms`, `send_message`, `report_to_owner`.

Missing: `reconnect_at`, `paused_reason`, follow-up state on the register (lane 2); `schedule_followup` and a sandbox clock tick so a reconnect fires on its date.
