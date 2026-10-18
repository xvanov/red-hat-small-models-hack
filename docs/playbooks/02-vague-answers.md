# 02. Vague answers

## Goal

Turn a fuzzy answer ("next month", "ASAP", "as long as needed", "maybe me and a friend") into an exact one without sounding like a form. Spec: R-GATE-1, R-GATE-2, R-GATE-4, §3.4.

## What the real threads show (aggregate)

About 4 in 10 renters give a vague move-in first, and a few give a vague stay. In the real threads the owner often let vagueness slide and the date only became exact on the application. The operator should be more precise than that, but just as relaxed in tone.

## Ideal flow

1. `read_reply` with `pending_item` set. Trust its status: `answered`, `vague`, `no`, `exception`.
2. Record whatever is exact with `upsert_renter` (including items volunteered out of order). Never re-ask a closed item.
3. If the pending item is `vague`: acknowledge what they did say, in their words, and ask for the exact form of the same item, as the last message.
4. Still vague a second time: offer two concrete options to pick from ("the 1st or the 15th?") instead of repeating the question.
5. Still vague a third time, or small talk three times: stop asking and escalate with a summary (R-ESC-5). The owner may call.

## Decision points

| Answer | Agent does | Escalate? |
|---|---|---|
| A month ("in November") | "Got it, November. What exact date would you like to move in?" | no |
| "ASAP" / "right away" | Acknowledge, offer the room's available date as an option | no |
| A range ("between the 10th and 15th") | Ask which day they would pick | no |
| Ambiguous numeric date ("11/12") | Ask which they mean, naming both readings | no |
| "As long as possible" for lease | Ask the yes/no form: is a one year lease okay? | no |
| Compliment, emoji, "ok" (small talk) | Weave it in warmly, re-ask in new wording (max 2 times) | 3rd time yes |
| They propose a showing time first | Acknowledge the time, say I need a few details first, re-ask | no (R-GATE-3) |

## Phrasing

Do:
- Mirror their words back before asking again: it shows you listened.
- Change the wording each time; keep the exactness.
- Offer concrete choices on the second try.

Don't:
- Repeat the same question word for word (the real threads sometimes sent the identical line 3 times; it reads as a bot or as annoyance).
- Explain why you need exact answers at length, or lecture.
- Bundle the next item into the same message.

## Tools

Exists: `read_reply` (statuses `answered | vague | no | exception`), `upsert_renter` (gate shapes), `send_message` (style guards), `escalate_to_owner`.

Missing: a per-item re-ask counter in thread state (spec C25), so the third-attempt rule is enforced, not prompted.
