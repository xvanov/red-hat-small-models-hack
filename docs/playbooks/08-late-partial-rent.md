# 08. Late or partial rent

## Goal

Keep the tenancy working and the money coming. Default to a solution (a payment plan, a date that matches a paycheck, a cheaper room) before anything adversarial. The agent tracks facts, proposes plans to the owner, and keeps the tenant informed; the owner decides every term and every escalation. No legal advice, ever. Spec: R-PHIL-5, R-ESC-12, C67.

## What the real threads show (aggregate)

- Asking to pay later or in parts shows up in about 80 tenant threads; owner rent reminders in about 70. Common reasons: paycheck timing, a payment-app daily limit forcing two transfers, a new job's first pay date, travel, lost hours or a lost job.
- What worked well, and is worth copying:
  - Stating exact numbers: what was received, what was expected, the difference, then "can you send the rest?".
  - Thanking a tenant who warned in advance and allowing a few days that once.
  - Accepting a tenant's own reasonable split ("pay part now, the rest with next rent") and calling it fair.
  - Offering a cheaper room when rent had outgrown the tenant's budget.
  - Confirming the tally when payments arrive in pieces ("that covers the deposit and this month").
- What not to copy:
  - Fees that compound daily, or fee arithmetic the lease may not support. Late-fee limits are set by law and vary by state; the agent quotes only the lease and the owner checks legality.
  - Jumping from "you owe a lot" straight to a formal demand without first asking for or proposing a plan.
  - Sending the same reminder word for word several times.
  - Going quiet on a promised remainder, from either side.

## Ideal flow

1. **Before the due date.** A tenant warns they will be late: thank them for the heads-up, ask for the exact date they can pay, record it. If it is within the owner's grace window (proposed: 5 days), draft "that works this time" for the owner's tap. Otherwise go to step 4.
2. **Partial payment arrives.** `record_payment` (missing), then one message: the exact amount received, the exact remainder, and one question: when can you send the rest? No new terms.
3. **Due date passes with nothing.** Day 2 (proposed): one friendly, factual reminder with the amount due and a question about when it is coming. Alert the owner at the same time.
4. **The tenant cannot pay in full.** Listen first. Ask one question to understand the timing (when is the next paycheck, how much can they send now). Then build up to two plan options with `draft_payment_plan` (missing) and send them to the owner as drafts, with the ledger and the tenant's own words. Tell the tenant: thanks for being upfront, I'll come back to you today with options.
5. **The owner approves a plan.** Send it (or the owner sends it) as a short, exact schedule: amounts and dates. Ask them to confirm. Record it.
6. **Plan check-ins.** The day before each installment, a short reminder. A missed installment: one message asking what happened and when it is coming, and tell the owner.
7. **Escalation is the owner's call.** When the proposed threshold is reached (arrears of 1 full month **and** no agreed plan, or a plan broken twice), report the facts to the owner with a recommendation. The agent never sends a demand, notice, or anything that mentions eviction or court, and never threatens it. If the owner sends formal notice himself, the agent stands down on that thread and escalates every new message.

## Plan shapes the agent may propose (owner confirms the list)

| Shape | When it fits | Draft looks like |
|---|---|---|
| Split month | Payment-app limit, or half now, half on next payday | two amounts, both inside the current month |
| Due-date shift | Paycheck lands after the 1st, every month | new due date plus any deposit change the lease requires (owner sets it) |
| Catch-up | Arrears after a one-off shock (lost hours, medical) | current rent on time plus arrears spread over at most 3 months |
| Cheaper room | Rent no longer fits income | a live room with lower rent, as a fact, owner approves the move |

## Decision points

| Situation | Agent does | Owner |
|---|---|---|
| Warned in advance, within grace window | Draft "that works this time" | taps yes |
| Partial payment | Exact received and remainder, ask when | informed |
| No word by day 2 | One factual reminder | alerted |
| Tenant proposes their own split | Restate it exactly, send to owner | approves |
| Hardship (job loss, illness) | Empathy, one timing question, draft plans | decides |
| Asks to use the deposit as last month's rent | Holding line; it depends on the lease | escalate |
| Any mention of eviction, lawyer, court, discrimination, or a government program | Holding line, no comment | escalate immediately |
| Threshold reached | Facts plus recommendation | decides formal path |

## Phrasing

Do:
- Lead with the facts, not the feeling: amounts, dates, what was received.
- Thank tenants who tell you early. It is the behavior you want more of.
- One question per message: when can you send the rest?
- Keep the same calm tone on the third message as on the first.

Don't:
- Say "late fee" in the first reminder unless the owner wants it there.
- Compute or invent a fee or a total not in the ledger.
- Moralize ("rent must be punctual"), guilt, or use capitals and multiple question marks.
- Promise a plan, waive a fee, or say "don't worry about it".
- Mention eviction, court, credit reporting, or police.

## Tools

Exists: `send_message`, `escalate_to_owner` (draft plans go here), `report_to_owner`, `list_rooms` (cheaper-room option).

Missing: tenant records and ledger (`get_tenant`, `get_ledger`), `record_payment`, `draft_payment_plan`, `schedule_followup` for installment reminders, a `send_message` guard that blocks fee, plan, or legal commitments in tenant threads (spec C67), and a tenant-ops Gym family.
