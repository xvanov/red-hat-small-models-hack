# 06. No-show and reschedule

## Goal

Protect the owner's time with the one-hour-before rule, make rescheduling easy, and keep a no-show in play instead of writing them off. Spec: R-SHOW-4 to R-SHOW-6, R-ESC-8.

## What the real threads show (aggregate)

No-shows and "are you coming?" messages appear in at least a dozen prospect threads; running late and rescheduling, on both sides, is common. The owner's good habits: asking for a confirmation shortly before, telling the person how to reach him on arrival, and later a plain "are you still interested?". His weaker habit: a bare "please reschedule" with no options, after which the thread often died.

## Ideal flow

1. When the owner confirms a time: tell the prospect once that it is confirmed, then in a separate short message the rule: please confirm about an hour before that you are on your way. Give the address privately now.
2. No confirmation by one hour before: one short check ("are we still on for 3?"). Nothing more.
3. Still nothing by the start time: no showing. Report to the owner (R-ESC-8). Do not message again that day.
4. Next day: one warm, no-blame message offering two new slots from `find_showing_slots`. Every new time goes back through `propose_showing` and owner confirmation.
5. They ask to reschedule themselves: thank them for the heads-up, offer two slots, same flow.
6. Second no-show: report to the owner and park (playbook 05) unless the owner says otherwise.
7. The owner is running late: tell the prospect right away with a new arrival time and a short apology, once.

## Decision points

| Situation | Agent does | Owner |
|---|---|---|
| Confirmed on the way | Nothing to the prospect; showing proceeds | none |
| Running late, under 15 minutes | "No problem, see you soon" | none |
| Running late, more than 30 minutes | Ask whether to keep the time or move it | tell owner |
| No word by start | No showing, report | report |
| Reschedule requested | Offer 2 slots, propose, owner confirms | confirm |
| Second no-show | Report, park | decides |

## Phrasing

Do:
- Keep it blame-free: things come up.
- Always give concrete options, never just "reschedule".
- One check before, one message after. Then stop.

Don't:
- Send several "are you coming?" messages.
- Tell a prospect a new time is confirmed before the owner confirms it.
- Scold a no-show.

## Tools

Exists: `find_showing_slots`, `propose_showing`, `send_message` (booking guard `showing_not_confirmed`), `report_to_owner`.

Missing: `confirm_showing`, `reschedule_showing`, `cancel_showing`, `mark_no_show`; event fields `on_the_way_by` and `mode` (in person, video, hybrid); a sandbox clock to fire the one-hour check.
