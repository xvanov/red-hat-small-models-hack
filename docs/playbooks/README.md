# Playbooks

How the operator handles each recurring situation, and how it should sound while doing it. The flow rules live in `docs/spec/concierge.md` (the Muse flow); these playbooks refine **how** each situation is handled and phrased. Where a playbook and the spec disagree, the spec wins and the playbook is a bug.

Source: the owner's real message history (tenants and contractors, about 16k of the owner's own messages, 2017 to 2026), read locally only. Everything here is paraphrased and generalized: no names, no house details, no message excerpts. The real threads include mistakes and heated moments; the playbooks keep the owner's general approach and tone and drop the mistakes (each playbook has a "What the real threads got wrong" note where it matters).

The stance across all of them: **never give up on a prospect or tenant, always look for a solution.** No room today means capture the demand, look for a place within days, otherwise stay in touch. Late rent means a payment plan first, the formal path only on the owner's judgment. **The agent proposes, the owner decides** every commitment.

## Owner review (confirm before these go into prompt v4)

Each item is a decision the playbooks currently mark as PROPOSED. Tick it, change it, or strike it.

**Money and payment plans**
- [ ] Payment-plan shapes the agent may *propose* (always as a draft for you): (a) split the month into 2 payments, both inside the same month; (b) move the due date to match a paycheck, with the deposit adjustment your lease requires; (c) catch-up schedule spreading arrears over at most 3 months on top of current rent. Any others? Any you never want offered?
- [ ] Does an approved plan go out from the agent (after your tap), or do you always send it yourself?
- [ ] Late fee: the agent quotes only the fee written in the lease and never computes a compounding or daily fee. Confirm the fee wording per lease, and that you have checked it against state law (the agent gives no legal advice).
- [ ] Grace rule: a tenant who warns *before* the due date and names a date within your grace window gets "that works this time" only after your yes. Confirm the window (proposed: up to 5 days).
- [ ] Partial payment received: the agent may acknowledge the exact amount received and the exact remainder, with no new terms. Confirm.
- [ ] Deposit return: deadline you follow and itemized deductions you allow (proposed: agent drafts the itemized statement, you approve, nothing is sent or paid without you).

**Escalation thresholds (all PROPOSED)**
- [ ] Late rent: owner alert on day 2 after the due date with no word; plan proposal drafted on first contact; formal-path recommendation (written demand, then counsel) only when arrears reach 1 full month **and** no plan was agreed or a plan was broken twice. The agent never sends a demand, notice or anything legal.
- [ ] Maintenance: safety emergencies (gas smell, smoke or fire, sparking or burning smell, active flooding, sewage backup, no heat below freezing, someone locked out at night, carbon monoxide alarm) alert you immediately and the tenant gets safety instructions first. Everything else: triage, then a job.
- [ ] Vendor spend: book only under `policy.spend_limit_usd`; above it, escalate with the quotes side by side. Confirm the limit and whether it differs for emergencies.
- [ ] Roommate conflict: escalate on any threat, harassment, discrimination claim, police mention, or the same complaint a third time.
- [ ] Prospect price push and leases under 6 months: always escalated (spec R-ESC-1, R-ESC-2). Confirm you never want an automatic first-month discount offered.

**What the agent may promise (PROPOSED: only these, nothing else)**
- [ ] "I will get back to you" with a real time (today, tomorrow).
- [ ] Facts in the room, lease or ledger record (rent, deposit, utilities, dates, amounts received).
- [ ] "I'll let you know as soon as something fits" to a no-fit prospect, and a follow-up date.
- [ ] Sending a vendor or a quote request; never a visit time until the vendor confirms it.
- [ ] Never: a discount, a hold, a waived fee, a plan, a deposit amount back, a repair date, a rule exception, or anything about eviction or court.

**Open items needing your call**
- [ ] Sourcing window for no-fit prospects (spec §8 q1; proposed 3 days).
- [ ] How many follow-ups a silent tenant gets on a money question before you take over (proposed: 2, with new wording each time, then you).
- [ ] Languages: the owner writes Spanish and Russian with those speakers; the operator's checks cover en/es only. Russian stays draft-for-owner?

## Index

| # | Playbook | Audience |
|---|---|---|
| 01 | [Prospect inquiry, with and without matching inventory](01-prospect-inquiry.md) | prospect |
| 02 | [Vague answers](02-vague-answers.md) | prospect |
| 03 | [Price push](03-price-push.md) | prospect |
| 04 | [Shorter lease](04-shorter-lease.md) | prospect |
| 05 | [Not now and reconnect](05-not-now-reconnect.md) | prospect |
| 06 | [No-show and reschedule](06-no-show-reschedule.md) | prospect |
| 07 | [Post-tour application nudges](07-post-tour-application.md) | prospect |
| 08 | [Late or partial rent](08-late-partial-rent.md) | tenant |
| 09 | [Monthly utilities notice](09-utilities-notice.md) | tenant |
| 10 | [Maintenance triage before a vendor](10-maintenance-triage.md) | tenant |
| 11 | [Roommate conflict](11-roommate-conflict.md) | tenant |
| 12 | [Move-out and deposit](12-move-out-deposit.md) | tenant |
| 13 | [Contractors: quote, schedule, access, no-show, verify, pay](13-contractors.md) | vendor |

Tone and examples: `data/style/tone-guide.md`, `data/style/owner_style_stats.json`, `data/style/examples.jsonl` (synthetic few-shots).

## Conventions in every playbook

- **Goal**, **ideal flow** (numbered steps), **decision points** (with the owner-escalation rule for each), **phrasing** (do and don't), **tools** (what exists in `contracts/tools.md`, and what is missing).
- Style rules from the spec apply everywhere: first person, at most 2 sentences per message, one question and it comes last, no long dashes, only record facts.
- "Escalate" means `escalate_to_owner(reason, ref_id, draft)` with a ready-to-send draft, plus at most one holding line to the person.

## Missing tools, collected

Everything the playbooks need that `contracts/tools.md` does not have yet. Lane 2 owns the demand tools; the rest are proposals for whoever picks them up.

| Tool (proposed) | Needed by | Why |
|---|---|---|
| demand register fields `reconnect_at`, `paused_reason`, `sourcing{due_at}` (lane 2) | 01, 05 | park and reconnect, sourcing within days |
| `schedule_followup(ref_id, at, reason)` | 01, 05, 06, 07, 08, 13 | every nudge and check-in is a timed follow-up |
| `confirm_showing`, `reschedule_showing`, `cancel_showing`, `mark_no_show` | 06 | showing lifecycle after `propose_showing` |
| `confirm_tour(event_id, happened)`, `send_application(renter_id)`, `record_application` | 07 | post-tour step (spec R-APP-1/2) |
| tenant records: `get_tenant(tenant_id)`, `get_ledger(tenant_id)` | 08, 09, 12 | amounts owed and received are facts the agent may quote |
| `record_payment(tenant_id, amount, kind, method, date)` | 08, 09, 12 | log what arrived, compute the remainder deterministically |
| `draft_payment_plan(tenant_id, shape, installments[])` | 08 | builds a plan as an owner draft; never sends |
| `compute_utility_split(house_id, month, bills[])` | 09 | per-person amount from bills and occupancy |
| `broadcast_to_house(house_id, text)` | 09, 11 | one message to every tenant in a house thread |
| `notify_tenant(tenant_id, text)` / access windows | 10, 13 | tell the tenant when a vendor comes, respect notice |
| `message_vendor(vendor_id, text)` | 13 | multi-turn vendor thread (nudges, "on your way?") |
| `reschedule_booking`, `cancel_booking`, `mark_vendor_no_show` | 13 | vendor lifecycle after `book_vendor` |
| `request_proof(job_id)`, `complete_job(job_id, proof[])` | 10, 13 | verify before paying |
| `pay_vendor(job_id, amount, method)` (owner approval required) | 13 | payment only after proof |
| `move_out_checklist(tenant_id)`, `draft_deposit_statement(tenant_id, deductions[])` | 12 | itemized deposit return as an owner draft |
