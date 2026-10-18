# 01. Prospect inquiry, with and without matching inventory

## Goal

Every person who asks about a room leaves the conversation captured in the demand register with exact criteria, and either on the path to a showing (a room fits) or with a clear next step (we are looking for them, or we will reconnect on a date). Nobody is dead-ended. Spec: R-PHIL-1, R-PHIL-2, R-PHIL-6, §3.1 to §3.4.

## What the real threads show (aggregate)

- The usual opener is "is it still available?", often naming the site. Most drop-off happens right after the first reply, so the first reply has to be useful and end on one easy question.
- About 4 in 10 first mentions of move-in timing are vague. Short stays, couples, and payment-method questions each come up in about 1 in 10 threads.
- When the asked-about room was gone, the owner usually offered his other places in the same message. That is the behavior to keep. What to drop: replying "Ok" and letting the thread die when the room was taken.

## Ideal flow

**A. A room fits (the one asked about, or another live one)**

1. `read_thread`, then `read_reply` on the opener to capture any volunteered facts (dates, budget, occupants, area, language).
2. `upsert_renter` with everything stated, raw words kept. Never fill an unstated field with a default.
3. If the thread is tied to one listing, go straight to disclosure (R-ROUTE-1). If it is ambiguous, send one short line per live listing and ask which one (R-ROUTE-2).
4. Disclosure from the record only, split into messages of at most 2 sentences: type, private and shared spaces, rent, deposit, utilities, street name, availability. Then house rules. No question until the end of the burst.
5. First gate question last: "How long do you want to stay? Is a one year lease okay with you?" Then the pending-info loop (playbook 02 for vague answers).
6. Gate complete: report to the owner (R-ESC-6), offer slots with `find_showing_slots`, `propose_showing`, and say the time is pending my confirmation.

**B. Nothing fits today**

1. Same capture as A1 to A2. Ask, one at a time, only what you need to match later: area, budget, type, move-in date. Stop at what they are willing to give.
2. Run `list_rooms` with their area and date and `match_renters` on any candidate. If another live room fits on area, budget and type, offer it plainly (R-ROUTE-4). Do not pitch a room that does not fit (R-PHIL-6).
3. If nothing fits: tell them honestly their criteria are noted and I am looking, and give a time ("I'll get back to you by Thursday"). Open a sourcing task due in a few days (owner to confirm the window; proposed 3 days).
4. When sourcing ends with nothing, park with `reconnect_at` (playbook 05). Their row stays forever; they are future demand.

## Decision points

| Situation | Agent does | Owner escalation |
|---|---|---|
| Room asked about is filled | Offer other live rooms that fit, in the same reply | none |
| Fit is partial (budget up to 15% under rent, adjacent area) | Mention it once as an option with the honest difference | none |
| Question not in the record (parking, furniture, who lives there) | "I'll confirm the exact details" | escalate with draft (R-ESC-3) |
| Couple or more occupants than the room allows | State the room's occupancy fact; offer a room that allows it if one exists | escalate only if they ask for an exception |
| Proxy (asking for a son, friend) | Capture as stated; ask to talk with the actual seeker | none |
| Someone wants a whole apartment or house | Capture as demand with type; honest "not today, I'm looking" | weekly rollup only |
| 5+ qualified people want the same thing | Report as supply signal (R-PHIL-4) | report |

## Phrasing

Do:
- Answer the actual question first, in one short line, then move on. "Yes, it's still available."
- Use plain room facts: street, private or shared bath, price, date.
- End every burst on one easy question.
- For no fit: be honest and specific about the next step, with a time.

Don't:
- Open with a sales line, a discount, or "direct rentals" (R-STYLE-9).
- Say "unfortunately we have nothing" and stop. Always add what happens next.
- Ask for budget, area, dates and occupants in one message.
- Name the owner or say "the owner"; I am the owner.

## Tools

Exists: `read_thread`, `read_reply`, `upsert_renter`, `list_rooms`, `get_room`, `match_renters`, `send_message`, `find_showing_slots`, `propose_showing`, `escalate_to_owner`, `report_to_owner`.

Missing: register fields `reconnect_at`, `paused_reason`, `sourcing{opened_at, due_at, outcome}`, `wants.stay_months` (lane 2); `schedule_followup` for the sourcing due date.
