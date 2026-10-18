# 10. Maintenance triage before a vendor

## Goal

Make the tenant safe first, understand the problem well enough to fix it cheaply (often without a vendor), and when a vendor is needed, hand them a clear job with photos and access already sorted. Spec: none yet beyond the ops tools; this playbook adds troubleshoot-first.

## What the real threads show (aggregate)

Of about 200 problem reports: plumbing is the biggest group (leaks, clogs, smells, water heaters), then electrical (tripped breakers, outlets), internet, locks and doors, appliances, heating and cooling. The owner's first reply was typically a diagnostic question: can you send a picture, where exactly is it leaking from, when does it happen. About 1 in 8 were solved remotely (reset the breaker, restart the router, a photo showed it was minor), about 1 in 10 needed a vendor, and some the owner fixed himself. Weak spots in the real threads: about 1 in 5 reports had no written reply (handled by phone or forgotten), and some tenants reported the same problem "again" before anything happened.

## Ideal flow

1. **Safety screen first, every time.** If the message suggests an emergency (list below), the first reply is a safety instruction, and the owner is alerted immediately. Then triage.
2. **Acknowledge within minutes.** One line that you got it, then one diagnostic question.
3. **Ask, one at a time, only what you need:** what exactly happens, where, since when, is it getting worse, and a photo or short video. Use the trade checklist below.
4. **Try the safe first fix** where one exists and the tenant is comfortable: breaker reset, router restart, plunger, check the shutoff valve, check the thermostat batteries. Never ask a tenant to open a panel, touch wiring, or climb a roof.
5. **Not solved:** `create_job` with the property, a clear issue description that includes what was tried, and a severity. `find_vendors` → `request_quote` (playbook 13).
6. **Coordinate access:** ask the tenant for good time windows, tell them who is coming and when (`notify_tenant`, missing). Respect notice rules unless it is an emergency.
7. **Close the loop:** after the visit, ask the tenant if it is fixed, and request a photo if it is visible. Report to the owner.

## Emergency list (alert owner immediately; owner to confirm)

| Signal | First instruction to the tenant |
|---|---|
| Gas smell | Leave the house, do not use switches or flames, call the gas company's emergency line from outside |
| Smoke, fire, burning or sparking | Get out and call 911 |
| Carbon monoxide alarm | Get out, call 911 |
| Active flooding or a burst pipe | Turn off the main water shutoff if you know where it is, keep away from outlets |
| Sewage backup | Stop using water and toilets |
| No heat in freezing weather, or no water at all | Tell me right away; I'm arranging help |
| Locked out at night, broken exterior door or lock | Safety first; I'm on it |

## Trade checklists (what to ask before a vendor)

- **Leak:** where is the water coming from (under the sink, the base of the toilet, ceiling), is it dripping or running, photo of the source and of any ceiling stain.
- **Clog or toilet:** one fixture or several (several suggests a main line), has a plunger been tried.
- **No hot water:** all taps or one, any water around the heater, photo of the heater label.
- **Electrical:** what stopped working, did a breaker trip, any smell or heat (if yes, emergency).
- **Heating or cooling:** thermostat setting and display, is air blowing, filter last changed, photo of the unit label.
- **Internet:** lights on the router, has it been restarted, one device or all.
- **Lock or door:** can you get in safely now, what exactly is stuck.
- **Appliance:** model photo, what it does or does not do.
- **Pests:** what kind, where, a photo.

## Decision points

| Situation | Agent does | Owner |
|---|---|---|
| Emergency signal | Safety instruction first | alerted at once |
| Solved remotely | Confirm fixed, log it | report |
| Needs a vendor, under spend limit | Job, quotes, book | report |
| Above spend limit | Quotes side by side | escalate |
| Tenant damage suspected | Collect facts and photos only; no blame in messages | escalate |
| Repeat of an earlier issue | Link to the old job, ask the vendor for a warranty visit | report |

## Phrasing

Do:
- Acknowledge fast and plainly: thanks for letting me know.
- Ask for a photo early; it saves a visit.
- Tell them what happens next and when.

Don't:
- Ask several questions at once, or send a checklist.
- Promise a repair date before a vendor confirms.
- Blame the tenant, or say "it's probably nothing".
- Give technical repair instructions beyond the safe first fixes.

## Tools

Exists: `create_job`, `find_vendors`, `web_search`, `request_quote`, `book_vendor`, `escalate_to_owner`, `report_to_owner`, `send_message`.

Missing: attachments read from tenant messages (photos) as job evidence, `notify_tenant` and access windows, `request_proof` / `complete_job`, an emergency severity that pages the owner, tenant records.
