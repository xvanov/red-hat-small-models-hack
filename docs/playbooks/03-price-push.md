# 03. Price push

## Goal

Keep the prospect warm and the qualifying going while the owner decides on any price change. The agent never agrees, hints at, or invents a discount. Spec: R-ESC-1, R-STYLE-6, §3.12.

## What the real threads show (aggregate)

Price pushes are rare (about 3 in 100 inquiries). The owner's real answers were short and calm: he either held the price in one line, or offered a different, cheaper room as the way to meet a budget. Occasionally he countered with term-based pricing (a longer stay at the listed price, a shorter stay at a higher one). He did not argue value at length.

## Ideal flow

1. `read_reply` to detect the price intent and capture any budget number (`upsert_renter` `wants.budget`).
2. Check for a cheaper live room that fits their area and type (`list_rooms`, `match_renters`). If one exists, mention it as a fact in one line.
3. Send one holding line: I'll check on that. In the same burst, continue the gate with the next pending question.
4. `escalate_to_owner` with the reason, their budget, the room, how far apart they are, and a draft reply for each owner choice (hold, counter, alternative room).
5. Relay the owner's answer exactly. Never soften a hold into a "maybe".

## Decision points

| Situation | Agent does | Owner escalation |
|---|---|---|
| "Is the price negotiable?" with no number | Holding line, continue gate | yes, with draft |
| A specific counteroffer | Record it, holding line | yes, include the number |
| Budget fits another room | Offer that room as a fact | no (still note the push in the report) |
| Asks about cost of move-in (deposit plus first month) | Quote record numbers only | no |
| Asks about the discount seen in an old post | Do not confirm; holding line | yes |

## Phrasing

Do:
- Keep it light and short: one holding line, then the next question.
- State alternatives as facts (street, price, bath), no sales talk.

Don't:
- Promise ("I'm sure we can work something out"), hint ("let me see what I can do for you"), or apologize for the price.
- Justify the price with a list of features.
- Quote any number not in the record (`send_message` blocks it: `price_not_in_record`).

## Tools

Exists: `read_reply`, `upsert_renter`, `list_rooms`, `match_renters`, `send_message`, `escalate_to_owner`.

Missing: term-based pricing on room records (12, 6 months, monthly) so the agent can quote an owner-set ladder as a fact instead of escalating every time.
