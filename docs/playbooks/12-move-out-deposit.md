# 12. Move-out and deposit

## Goal

A clean handover with no surprises: clear notice, a known checklist, an inspection, an itemized deposit return on time, and the leaving tenant offered another place if they want one. Spec: none yet (new); R-PHIL-2 step 4 (placed tenants are demand again).

## What the real threads show (aggregate)

Move-out, last day, and deposit return come up in about 130 threads. The owner's practice: deposit back if the tenant cleans, leaves the room and furniture in good shape, and gives a month's notice; deposits returned minus final utilities, sometimes in two transfers because of payment-app limits; asking leaving tenants if they want to renew or move to another of his places. Weak spots: a promised remainder forgotten until the tenant asked, a tenant who left belongings and dragged the move-out on for weeks with identical reminders, and keys and condition handled loosely.

## Ideal flow

1. **Before lease end (proposed: 45 to 60 days):** ask whether they plan to renew, move to another room, or leave. If renewing, escalate to the owner for terms.
2. **Notice received:** confirm the exact last day in writing and what the lease says about notice. Offer another live room if their reason is fixable (price, size, roommates).
3. **One week before:** one message with the move-out checklist (room and shared areas clean, belongings out, keys back, forwarding address and preferred payment method).
4. **Last day:** inspection by the owner or a delegate, with photos. Collect keys or codes changed.
5. **Deposit:** `draft_deposit_statement` (missing): deposit minus itemized deductions (final utilities, documented damage beyond normal wear) with photos. Owner approves. Return on time (deadline set by the owner per state law; the agent gives no legal advice). If paid in parts, say so and track the remainder until it is done.
6. **After:** mark the room available, run `match_renters` before publishing (spec C65), and keep the tenant in the register as future demand.

## Decision points

| Situation | Agent does | Owner |
|---|---|---|
| Wants to renew | Capture term wanted | sets terms |
| Short notice | Quote the lease's notice rule, no threats | escalate |
| Wants to leave early / break the lease | Holding line | escalate |
| Belongings left behind | One message with a pickup date | escalate after it passes |
| Deductions disputed | Send the itemized list and photos | escalate |
| Asks to use deposit as last month | Holding line | escalate |

## Phrasing

Do:
- Thank them for living there; it costs nothing.
- Be exact about dates, amounts, and what each deduction is for.
- Close every money thread with a clear "that's everything" when the last payment is sent.

Don't:
- Promise the full deposit back before the inspection.
- Deduct anything without a reason and a photo.
- Send the same reminder repeatedly in identical words.

## Tools

Exists: `send_message`, `update_room`, `create_listing`, `match_renters`, `publish_listing`, `escalate_to_owner`, `report_to_owner`.

Missing: tenant and lease records with end dates, `move_out_checklist`, `draft_deposit_statement`, `record_payment` (deposit refunds), `schedule_followup`.
