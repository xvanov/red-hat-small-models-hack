# 04. Shorter lease

## Goal

Find a term that works for both sides without giving away a short stay at standard rent. Spec: R-GATE-5, R-DISC-2, R-ESC-2, D23.

## What the real threads show (aggregate)

When renters mentioned a lease length, about two thirds asked for something shorter than a year (summer, a work contract of a few months, a travel assignment, month to month). The owner's real answers ranged from yes, to yes at a higher short-term price, to no month to month. So the honest rule is: 6 months is the floor the agent may offer; anything shorter is the owner's call and usually a different price.

## Ideal flow

1. Public wording is always "Lease: 1 year". The 6-month option is never volunteered (`send_message` blocks it before the prospect asks: `lease_floor_not_requested`).
2. They ask for shorter, or say how long they need. `read_reply` with `pending_item: lease`.
3. Their term is 6 to 11 months: say 6 months is the shortest possible and confirm their exact term. Their yes closes `lease` (`upsert_renter` with `gate.lease.months`). No owner check needed.
4. Their term is under 6 months: do not agree, do not say no flatly. Holding line ("let me check what I can do for a shorter stay"), continue the gate, `escalate_to_owner` with the term and dates and a draft.
5. If the owner prices an exception, relay it exactly as a fact.

## Decision points

| They want | Agent does | Escalate? |
|---|---|---|
| 12 months or more | Close `lease` | no |
| 6 to 11 months, after asking for shorter | Offer 6 months as the shortest, confirm their term | no |
| Under 6 months / month to month | Holding line, keep qualifying | yes, with draft |
| "Not sure how long" | Ask the yes/no form of the lease question (playbook 02) | no |
| Longer than a year (2 years) | Close `lease` at 1 year; note their interest in staying longer | report only |

## Phrasing

Do:
- Be matter-of-fact: 6 months is the shortest possible.
- Acknowledge their reason (work contract, school term) in a few words before the answer.

Don't:
- Say "minimum" in public text, or mention 6 months before they ask.
- Promise a short stay "should be fine".
- Turn it into a negotiation; the owner sets short-stay pricing.

## Tools

Exists: `read_reply`, `upsert_renter` (`gate.lease.months`, passes the gate at `lease_floor_months`), `send_message` guards `lease_floor_not_requested` and `lease_term_not_in_record`, `escalate_to_owner`.

Missing: short-stay inventory and term-based prices on rooms (so a 3-month nurse can be matched to a room the owner has priced for that).
