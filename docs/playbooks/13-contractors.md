# 13. Contractors: quote, schedule, access, no-show, verify, pay

## Goal

Get the job done well at a fair price under the owner's spend limit, with the tenant informed and the work verified before anyone is paid. Spec: ops tools in `contracts/tools.md` §4.

## What the real threads show (aggregate)

- Owner openers stated the problem, the address, and a photo or video, then asked whether they could come today or tomorrow.
- Most firms want to see the job before pricing it. Quotes arrived from the same day to two weeks later, often after a nudge; promised dates slipped one to three times.
- Prices moved when asked in about half the cases, typically by a few percent, or by trimming scope line by line. "That's more than I can do right now" was a common, polite owner answer.
- About a third of scheduled visits had a late arrival, a same-day cancel, or a no-show; rain cancelled exterior work often.
- Access: a lockbox code (one failed at the door), a tenant letting them in, or the owner on site. One good rule seen: the tenant only opens the door; decisions and payment stay with the owner.
- Proof: photos or video of the finished work in many threads; sometimes only "done".
- Payment: digital transfers for individuals, card or invoice for firms; advances refused until there was a written agreement.
- What not to copy: accepting a second vendor's price after verbally agreeing with the first, waiting days on a silent vendor without trying a second, and cash-without-tax offers.

## Ideal flow

1. **Job:** `create_job` with a clear issue description, what was already tried, photos from the tenant, and severity.
2. **Find two or three vendors:** `find_vendors` (by `job_id`), `web_search` if needed. Prefer rated vendors in the service area.
3. **Ask for quotes in parallel:** `request_quote` with the description and photos. Ask for an itemized price; accept that many need a site visit first.
4. **Chase once:** a vendor silent for about a day gets one polite nudge; a `TIMEOUT` or second silence moves on to the next vendor. No retry loops.
5. **Compare and choose:** under `policy.spend_limit_usd`, book the best value (price, rating, earliest date) with `book_vendor`. Above it (`BUDGET_EXCEEDED`): escalate with the quotes side by side and a recommendation. A polite counter is fine when the owner has allowed it; never mention a competitor's price falsely.
6. **Schedule and access:** confirm the window with the vendor, then the tenant (`notify_tenant`, missing). Share a lockbox or door code only with the booked vendor, only for that visit, and ask the owner to change it after if that is his rule.
7. **Day of:** an hour before the window, a quick check that they are still coming. Late or no word 30 minutes into the window: ask for an ETA. No-show: tell the tenant, mark it, rebook the next vendor, report to the owner.
8. **Verify:** ask for before and after photos or a short video (a running tap, a dry ceiling, a working unit). Ask the tenant to confirm it works.
9. **Pay:** only after proof, the amount on the quote, through the owner's approved method, with the owner's approval. Refuse advances without a written agreement; deposits for materials go to the owner.
10. **Close:** log the cost on the job, note the warranty, rate the vendor. A repeat problem within the warranty period is a callback, not a new paid job.

## Decision points

| Situation | Agent does | Owner |
|---|---|---|
| Quote under spend limit | Book | report |
| Quote over spend limit | Quotes side by side | escalate |
| Scope grows after the visit | Ask for a revised itemized quote | escalate if over limit |
| Vendor asks for an advance or a deposit | Ask for a written agreement | escalate |
| Cash-only to avoid tax, or no license | Do not accept | escalate |
| Contract or service agreement (multi-month) | Read the key terms back, do not sign | escalate |
| Vendor no-show | Rebook next vendor, inform tenant | report |
| Rain or weather cancel | Reschedule, inform tenant | none |
| Work disputed or ineffective | Photos, request warranty visit | escalate if refused |
| Lead-platform bot asks contact details | Answer from the owner-approved contact profile only | none |
| Marketing drip, no job | Do not engage; opt out | none |

## Phrasing

Do:
- Be specific: what is broken, where, photos, when the house is accessible.
- Be polite and brief with vendors; thank them for quotes even when declining.
- Say no plainly: "Thanks, that's above what I can do for this job."
- Confirm times in writing: day, window, who will open the door.

Don't:
- Agree a price and then take another quote's offer.
- Share an access code in a group or before booking.
- Pay before proof, or pay more than the quote without a revised quote.
- Commit the owner to a contract, a financing plan, or an advance.

## Tools

Exists: `create_job`, `find_vendors`, `web_search`, `fetch_page`, `request_quote` (`TIMEOUT` for silent vendors), `book_vendor` (`BUDGET_EXCEEDED`), `escalate_to_owner`, `report_to_owner`.

Missing: `message_vendor` (multi-turn vendor thread for nudges and ETAs), `reschedule_booking`, `cancel_booking`, `mark_vendor_no_show`, `notify_tenant` with access windows and scoped codes, `request_proof` / `complete_job`, `pay_vendor` (owner approval), structured quotes (line items, options, valid until, revised), warranty callbacks.
