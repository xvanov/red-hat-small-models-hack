# 09. Monthly utilities notice

## Goal

Every month, each tenant learns their exact utility share in one short message, can see how it was computed if they ask, and pays. Spec: none yet (new); quotes only computed figures.

## What the real threads show (aggregate)

This is the single most repeated operations message in the history (about 630 owner messages across about 200 threads). The owner's version is very short: a greeting, the amount, the month. In Spanish-speaking houses it goes out in Spanish. When the share jumps (someone moved out, a big winter bill) he sometimes added a one-line reason, and sometimes corrected the amount in a follow-up. Common follow-up issues: a couple paying the single-person share, or rent paid without the utilities.

## Ideal flow

1. When the bills for the month are in, `compute_utility_split` (missing) for the house: total of the bills divided by occupants per the lease rule (per person or per room).
2. Check the figure against last month. If it changed by more than a set amount (proposed: 25%), add one line with the reason (occupancy change, season, a specific bill).
3. Send one message per house thread (`broadcast_to_house`, missing) or per tenant, in each tenant's language: greeting, amount per person, month. A couple or two-person room gets the total for both stated plainly.
4. On "why so high?": give the breakdown from the bills (each bill and the count of people), no guessing.
5. Track payments (`record_payment`, kind utilities). A few days after rent is due, one short reminder only to those who have not paid.
6. A correction is needed: one message with the right amount and a one-line reason. Do not send a third version.

## Decision points

| Situation | Agent does | Owner |
|---|---|---|
| Normal month | Send the amount | none |
| Big change | Amount plus one-line reason | none |
| Tenant disputes the split rule | Quote the lease rule | escalate if it continues |
| Bill missing or estimated | Hold the notice, or mark it estimated with a later true-up | told |
| Tenant moved mid-month | Prorate only if the owner's rule says so | escalate |

## Phrasing

Do:
- Keep it to one line: "Hi all, utilities for March are $72 per person."
- Use the tenant's language.
- When asked, show the math, short.

Don't:
- Add pleasantries that make it longer than the number.
- Send corrected amounts more than once.
- Mix a utilities notice with a complaint about cleaning or late rent.

## Tools

Exists: `send_message`.

Missing: `compute_utility_split(house_id, month, bills[])`, `broadcast_to_house(house_id, text)`, `record_payment`, tenant and house records in world state (today the world knows rooms and renters, not tenants or houses).
