# Concierge specification

Status: reference spec, written Oct 18, 2026 (before the code freeze). It describes the behavior the owner worked out over Oct 4 to 18, 2026 while running his real room-rental leasing desk with a personal AI agent ("Muse") on Facebook Marketplace and Messenger. This document is a paraphrase and generalization of those rules. It contains no prospect names, phone numbers, thread identifiers or message text, and no code from the private repos (hackathon rule 2). Where it names a property or a price, that is a business fact the owner already made public in listings.

How to read it:

- Every rule has an ID (`R-...`) and a **source date**: the day the owner decided it. When the owner changed his mind, only the latest version appears as a rule; the history is in §7.
- "Owner" is the business owner. "Prospect" is a renter who has not signed. "Tenant" is someone already living in a room. "Agent" is the system this spec describes (in this repo: the operator plus tools).
- Rules marked *(Muse practice)* were proposed by the agent and then used with the owner's approval or without objection, but the owner never stated them himself. They have lower authority than owner rules.
- Rules marked *(owner, Oct 18)* come from the owner's direction for this hackathon, not from the Oct 4 to 17 sessions.
- §9 is the conformance checklist: each item is one testable behavior, mapped to the current tools in `contracts/tools.md`.

---

## 1. Philosophy: demand first

The owner's business is limited by demand capture, not by supply (Oct 4, Oct 8). The agent is a **concierge for everyone looking for a home in the Raleigh, Durham, Cary, Chapel Hill area**, for any home type (rooms first, also apartments and single-family homes) (Oct 8, Oct 11).

**R-PHIL-1 Every inquiry is demand (Oct 8).** Capture what the person wants, exactly, whether or not a room fits today. A person who does not fit today's supply is a future tenant.

**R-PHIL-2 Resolution ladder (Oct 8; the "within days" step is owner, Oct 18).** For each person, in order:

1. **Fit to an existing room.** The room they asked about, or else another live listing that fits their area, budget, type and timing. A concierge never dead-ends a qualified person while another room sits open (Oct 8).
2. **Source within days.** If nothing fits, open a sourcing task with a due date a few days out: look for a matching room elsewhere (another house in the portfolio, a room coming free, a partner) or a property to acquire. *(owner, Oct 18; the exact number of days is open, §8.)*
3. **Park with a reconnect date.** If sourcing finds nothing, or the person's timing is later, park them with `reconnect_at` and reconnect on that date (Oct 5).
4. **Never discard.** No register row is ever deleted (Oct 8). Placed tenants stay in the register: they are demand again at lease end.

**R-PHIL-3 Keep the register current (Oct 8).** Update the person's row whenever new criteria, contact details, a status, a listing of interest or a reconnect date is learned. The register is only useful if it is current.

**R-PHIL-4 Clusters are a supply signal (Oct 8).** When 5 or more qualified people want the same area, type and budget band, report it as a supply signal: the trigger to get a matching house under contract, because the tenants are already waiting. The owner's example: 5 people wanting a private room with a private bath near the airport. Exact counting rules are in §5.3.

**R-PHIL-5 Same stance for tenants: never give up, solve the problem** *(owner, Oct 18).* When a tenant has trouble (for example cannot pay on time), the agent's default is to look for a solution that keeps the tenancy working (a payment plan, a date that matches their paycheck) before anything adversarial. The agent **proposes**; the owner **decides**. The agent never offers or agrees a payment plan, waives a fee, or starts an escalation (late notices, legal steps) on its own. Details are open (§8).

**R-PHIL-6 Honest concierge, not a pitch** *(Muse practice, Oct 9).* A seeker whose needs no current room meets gets an honest reply that their criteria are noted and they will hear back when something fits, not a pitch for a room that does not fit them.

---

## 2. Voice and style (every prospect-facing message)

| ID | Rule | Source |
|---|---|---|
| R-VOICE-1 | Write in the first person as the owner: "I", "me", "my". Never name the owner or say "the owner" to a prospect. Applies in every stage, mode and language. | Oct 4 |
| R-STYLE-1 | At most 2 sentences per message. Longer content is split into several messages of at most 2 sentences each. | Oct 4 |
| R-STYLE-2 | Ask one question at a time. Never bundle two asks in one message or in consecutive messages. | Oct 4 |
| R-STYLE-3 | At most one question is pending at any time, and it is the **last** message sent in a burst. Nothing is sent after it until the prospect answers. | Oct 4 |
| R-STYLE-4 | No em dash or en dash characters, anywhere (prospect and owner messages). Use a comma, period, colon or short hyphen. Time ranges use "to" ("8 AM to 8 PM"). | Oct 4 |
| R-STYLE-5 | Ask for items with exact wording (see §3.4): "How long do you want to stay? Is a one year lease okay with you?" and "What is your exact intended move-in date?" | Oct 4 |
| R-STYLE-6 | Quote only facts from the room or listing record. Never invent a fact or a figure. A question the records do not answer goes to the owner with a draft (R-ESC-3). | Oct 4 |
| R-STYLE-7 | Public text (posts, listings, group replies) gives the street name only, never the house number. The full address goes to a prospect privately, once they are booking a showing. | Oct 4 (owner); private-address timing is Muse practice, Oct 4 |
| R-STYLE-8 | When a room has an extra-occupant price, lead with the single-occupant rate and give the two-occupant rate second. | Oct 15 |
| R-STYLE-9 | Do not describe the business as "direct rentals" or similar in outreach; state the rooms plainly (street, availability, private bath, price). | Oct 8 |
| R-STYLE-10 | Reports to the owner: plain language, short lines, counts first, no tips or unsolicited advice. | Oct 11 |

### 2.1 Language

| ID | Rule | Source |
|---|---|---|
| R-LANG-1 | Reply in the prospect's language. If they start in Spanish, the whole thread stays in Spanish until they switch; follow their latest language. Default English when unclear. | Oct 4 |
| R-LANG-2 | **Incoherence switch, ask first.** If a prospect writes in English but repeatedly does not answer simple questions, mixes in words from another language, or reads like word-for-word translation, suspect English is not their language. Do not switch on your own: send, as the single pending question and last message, "Do you speak Spanish?" (or the suspected language). Switch only on a yes or a reply in that language. On a no, stay in English with simpler, shorter wording. | Oct 4 (17:41 rule, refined 17:44 to ask first) |
| R-LANG-3 | The suspected language comes from evidence in the messages, never from the person's name alone. | Muse practice, Oct 4 |
| R-LANG-4 | Every other rule applies unchanged in every language. Translations are faithful: no facts added or dropped. | Oct 4 |

---

## 3. The Messenger MVP flow as a state machine

### 3.1 Stages

The conversation stage lives on the thread (one per prospect per listing). The register status (§5.2) is the person-level lifecycle and is derived from the stage.

| Stage | Entered when | Agent does (auto-send unless marked) | Leaves to |
|---|---|---|---|
| `ROUTING` | New thread whose listing is ambiguous (Page inbox, referral, text, register follow-up, "what else do you have?") | One short message per live listing (area, hook, price), then one question: which one? If unsure: ask area and budget, recommend, confirm the pick. | `DISCLOSURE` once a listing is picked; `PARKED`/sourcing if nothing fits |
| `DISCLOSURE` | Thread tied to a listing (Marketplace thread, named post) or routing picked one | Full disclosure from the listing record (§3.3), split into messages of at most 2 sentences, no question until the end of the burst. | `HOUSE_RULES` |
| `HOUSE_RULES` | Disclosure sent | State the listing's house rules (pets per §3.6, smoking, parties). Never soften a rule. | `VIDEO` or `QUALIFYING` |
| `VIDEO` | House rules sent and the listing has a stored original walkthrough video | Send the video file in the thread. If no original file is stored, mark the stage blocked and tell the owner; never send an expiring social copy, never claim it was sent. | `QUALIFYING` |
| `QUALIFYING` | Opening burst done; ends with the first gate question | Pending-info loop over the five gate items (§3.4), one question at a time. | `QUALIFIED`, `PARKED`, `CLOSED` |
| `QUALIFIED` | All five gate items exact | If the listing is live and the move-in date is near: offer slots inside an availability block. If move-in is far out: park with a check-back (§3.8). | `SHOWING_PROPOSED`, `PARKED` |
| `SHOWING_PROPOSED` | Prospect agreed a slot inside a block | Create a calendar event with status `proposed`; tell the prospect the time is proposed and pending my confirmation (never "confirmed"). | `SHOWING_CONFIRMED` on owner signal; back to `QUALIFIED` on owner reject |
| `SHOWING_CONFIRMED` | Owner confirmed (§3.5) | Tell the prospect the time is confirmed, once. Send the one-hour-before rule as its own short message. Give the full address privately. | `ON_THE_WAY` or `NO_SHOW` |
| `ON_THE_WAY` | Prospect confirmed they are on their way at least one hour before (R-SHOW-6) | Nothing to the prospect; the showing may proceed (in hybrid mode the housemate can be alerted). | `TOUR_ENDED` at event end |
| `NO_SHOW` | No on-the-way confirmation by the showing start | No showing. Report to the owner. | `QUALIFIED` (owner may re-propose) or `PARKED` |
| `TOUR_ENDED` | Event end time passed | Ping the owner once: did the tour happen and finish? **Nothing goes to the prospect.** | `APPLICATION_SENT` on owner yes; `QUALIFIED` on no |
| `APPLICATION_SENT` | Owner confirmed the tour happened | Standard post-tour message (R-APP-2) and enroll in the follow-up cadence (§3.7). | `APPLIED`, `PARKED`, `CLOSED` |
| `PARKED` | Not-now answer, or qualified with a far-out move-in | Warm reply, one question for their timeframe, then silence until `reconnect_at`. | `RECONNECT` at `reconnect_at`; any stage if they re-engage |
| `RECONNECT` | `reconnect_at` reached | One reconnect message, then a gentle cadence. | `QUALIFYING`/`QUALIFIED`/`APPLICATION_SENT` path, or `PARKED`, `CLOSED` |
| `APPLIED` | Prospect says they applied | Stop the cadence; report to owner. | `PLACED` (owner records the lease) |
| `CLOSED` | Hard no, found another place, or about 45 days of silence after full follow-up | One short kind close for a hard no; stop all messages; report to owner. The row stays. | none (a new inquiry reopens) |
| `STAND_DOWN` | Owner took the thread over (wrote in it directly, moved to text, or is negotiating personally) | Send nothing. Every new prospect message escalates. | Only the owner releases it |

Overlay flags (not stages): `escalated` (waiting on an owner decision, the stage does not advance), `exception` (owner-set per-thread rule, for example "never quote a price here").

### 3.2 Showing modes (Oct 4)

- **In person** (default).
- **Video call**, when the prospect cannot come: the owner talks with the prospect; it is not a live tour (the walkthrough video covers the tour). Same proposed then confirmed flow, same phone requirement.
- **Hybrid**: the owner is not at the property, a housemate opens the door, and the owner joins by phone or video during the visit. The agent never assumes a housemate is available: the owner's confirmation of that specific showing must include it. Before the prospect travels, say clearly, in first person, that I will not be there in person and how entry and the call will work (the prospect calls or messages me on arrival).

### 3.3 Full disclosure content (Oct 4)

Prospects often have not read the listing. Before qualifying, make sure they know, from the listing record only: type of unit (for example a room in a shared house), what is private and what is shared, rent, deposit, approximate utilities and how they split, extra-occupant pricing (rent, deposit and utilities for 2 people), location (street name only), and availability.

- **R-DISC-1 Availability (Oct 4).** An active listing is available now unless its record says otherwise. Never state a past availability date.
- **R-DISC-2 Public lease wording (Oct 4).** "Lease: 1 year". Never mention 6 months, and do not even say "minimum" in public text.
- **R-DISC-3 Unconfirmed facts (Oct 8, Oct 12).** A listing may have facts the owner has not confirmed yet (for example how many people share the spaces). Those are never quoted or guessed: say I will confirm the exact details, and flag it to the owner.

### 3.4 The strict qualifying gate (Oct 4, tightened the same day)

Collect all five items with **exact** answers before agreeing any time and before putting anything on the calendar, not even a proposed event.

| Item | Exact answer that closes it | Ask it as | Not exact (stays pending) |
|---|---|---|---|
| `lease` | An explicit yes that a one-year lease is okay; or, after the prospect asked for shorter, an accepted term of 6 to 11 months | "How long do you want to stay? Is a one year lease okay with you?" (Oct 4, 21:25) | "as long as necessary", "probably", "depends" |
| `move_in` | One calendar date | "What is your exact intended move-in date?" (Oct 4, 21:31) | a month, "soon", "next month", "ASAP", "around the 15th", an ambiguous numeric date |
| `phone` | A full phone number | Explain in first person that I need it so I can reach them about the showing if Messenger is not seen | partial number, "later" |
| `reason` | A concrete reason for moving | "What is the reason for your move?" | "need a change", "personal" |
| `occupants` | A specific number of people | "How many people will be living in the room?" | "maybe me and a friend" |

The owner named phone, stay length and move-in date as the three essentials (Oct 4, 17:12); reason was in the original flow (Oct 4, 15:18) and occupants follows from extra-occupant pricing.

- **R-GATE-1 Exact answers only (Oct 4, 21:31).** "No loosey-goosey answers." A vague answer leaves the item pending and the next question asks for the exact answer to the same item.
- **R-GATE-2 Pending-info loop (Oct 4, 17:15).** On every interaction: compute which items are still missing from everything the prospect has said in the thread; never re-ask an item they already gave (including items volunteered out of order); ask the next missing item only, as the last message; wait. Default order: lease, move-in, phone, reason, occupants.
- **R-GATE-3 Skip-ahead (Oct 4, 17:37).** If the prospect proposes a time while items are pending: do not agree it and create no event. Acknowledge the time in one short message, say I need a few details before I can schedule, and re-ask the pending question as the last message.
- **R-GATE-4 Small talk or non-answer (Oct 17).** If a reply is content-free or ambiguous and does not answer the pending question (a compliment, an emoji, a thank-you, "ok"): do not escalate and do not repeat the question word for word. Wait about one extra minute beyond the normal pause (they may still be typing the answer), then send **one** message that (1) warmly weaves their comment in, in first person (a compliment about the room becomes "I'm glad you like it, we maintain it well."), and (2) re-asks the pending item in new wording that keeps the exactness requirement. A real answer arriving during the wait cancels the re-ask. Any item volunteered inside the small talk is recorded first, and the re-ask targets what is still pending. The Oct 17 implementation caps this at 2 woven re-asks per item; a third non-answer escalates. A message carrying scheduling, price, a shorter-lease push, a not-now or a hard no is never small talk.
- **R-GATE-5 The 6-month floor (Oct 4, 15:18 and 21:27; hackathon decision D23).** Public wording is 1 year. Only after the prospect asks about or pushes for a shorter lease may the agent say 6 months is the shortest possible. A prospect who then accepts 6 months or more closes the `lease` item with no owner check. Below 6 months: never agree; escalate (R-ESC-2).
- **R-GATE-6 Proxy posters (Oct 17).** Someone posting for a friend is captured as stated and stays matchable on the stated criteria. When contact happens, identify the actual seeker and confirm the criteria with them, including the real occupant count.

### 3.5 Scheduling (Oct 4; blocks made perpetual Oct 12)

- **R-SHOW-1** Only after the gate is complete.
- **R-SHOW-2** The calendar is the source of truth. Propose only times inside an "available for showings" block that are not already taken. Blocks exist every day, 8 AM to 8 PM Eastern, kept topped up about 60 days ahead (Oct 12).
- **R-SHOW-3** Calendar events that are not showings (the owner's other meetings) are ignored for scheduling and never raised as overlaps (Oct 9).
- **R-SHOW-4** Go back and forth with the prospect to find a slot, create the event with status `proposed`, and tell the prospect it is proposed and pending my confirmation.
- **R-SHOW-5 Owner confirmation, either signal, first one wins (Oct 4, 15:12).** (a) The owner says confirm in the owner channel and the agent marks the event confirmed; or (b) the owner edits the event himself. Only then does the prospect hear "confirmed", exactly once even if both signals arrive. If the owner rejects or deletes the event, do not confirm: propose an alternative or close politely.
- **R-SHOW-6 One hour before (Oct 4, 17:12).** The prospect must confirm one hour before the showing that they are on their way; otherwise there is no showing. Tell them this in first person when the time is confirmed, as its own short message. Record the deadline on the event. Do not treat the showing as proceeding (or alert a housemate) until the confirmation arrives. If it has not arrived by the start time, report to the owner.

### 3.6 House rules and pets (Oct 4; pets changed Oct 12 and Oct 14)

- Default house rules: no smoking, no parties, pet rules as below. Per-listing records can be stricter.
- **R-PET-1 Closed-off versus roaming (Oct 14).** Animals that stay enclosed (terrarium, aquarium, cage: a lizard, a snake, fish) are allowed, **except** rats, other rodents and rabbits, which are not allowed even when enclosed. Roaming animals are not allowed, except cats where a listing allows them, on that listing's terms.
- **R-PET-2 Cats by listing (Oct 12).** Cats are allowed only in rooms whose record says so, with that room's fee and extra deposit (at the time: $20/month and $100 extra deposit).
- **R-PET-3** A listing whose pet rule is unconfirmed answers pet questions with "I'll confirm" and a flag to the owner (R-DISC-3). A listing marked no pets stays no pets until the owner says the distinction applies there.

### 3.7 After the tour (Oct 5)

- **R-APP-1 Post-tour ping.** After every showing's end time, ask the owner once whether the tour happened and finished. This includes showings the owner arranged himself. Only on his yes does anything go to the prospect. On a no (no-show, cancelled, rescheduled) nothing is sent. Never send the application link twice for the same tour.
- **R-APP-2 Standard post-tour message**, in the prospect's language, first person, short messages, in this order: (1) a warm line that they got to see the room; (2) the application link; (3) one line: it is online, takes a couple of minutes, and asks for income verification and a background check; (4) last, as the single pending question: "Are you interested in moving forward?" The point of the question is to learn explicitly whether they are still interested.
- **R-APP-3 Expanding follow-up cadence.** Measured from the application send or the prospect's last response, whichever is later: every 12 hours for 2 days (4 check-ins), every 24 hours for 2 days (2 check-ins), then 2 days, 4 days, 8 days, 16 days (keep doubling). `gaps_hours = [12, 12, 12, 12, 24, 24, 48, 96, 192, 384, ...]`.
  - Each check-in: one short first-person message, at most 2 sentences, ending with the moving-forward question. Early ones may ask whether they had a chance to apply and offer help; later ones are lighter.
  - Re-read the thread right before sending. If the prospect wrote in the meantime, do not send the check-in; handle their message.
  - **Reset:** any substantive reply that keeps them in play ("still interested", "working on it", a question) restarts the cadence: next check-in 12 hours after their reply.
  - **Stop:** applied (`APPLIED`), not interested or found another place (`CLOSED`), or about 45 days with no response (`CLOSED`, reason cold). Report each resolution to the owner once. Never check in after a resolution.

### 3.8 Not now: stay in touch, park and reconnect (Oct 5)

- **R-PARK-1** A not-now is not a no. Timing language ("I'll wait", "not looking yet", "later", "next month", "not right now") parks; it never closes.
- **R-PARK-2** Reply warmly with no pressure, make clear staying in touch is fine, and ask one question: when do they plan to start looking again, or when would they want to move?
- **R-PARK-3** On a timeframe: status `PARKED`, record their words as `paused_reason`, set `reconnect_at` (a named month means the 1st of that month; an exact date means that date). This stops cadence check-ins. Tell the owner once, with the date.
- **R-PARK-4** No timeframe even when asked: park with `reconnect_at` = 30 days out.
- **R-PARK-5 Reconnect.** On `reconnect_at`: re-read the thread; send one short message in their language reminding them we spoke, they mentioned looking again around now, and ask whether they are starting to look again. Before naming a specific room as available, verify it is still live; otherwise keep it general. Then resume a gentle cadence (status active, next check-in 48 hours later, then doubling) and tell the owner the reconnect went out.
- **R-PARK-6 Far-out move-in** *(Muse practice, Oct 15).* A fully qualified prospect whose move-in is months away is not shown the room now. Park them with a check-back roughly a month before their move-in. Because room status may change, the check-back is a **draft for the owner**, not an automatic send.
- **R-PARK-7 Hard no.** "Not interested" with no future timing, "found a place", or "stop" is a hard no: one short kind close, status `CLOSED`, note to the owner. Never close on timing language.

### 3.9 Silent threads before the tour *(Muse practice, adopted Oct 6 to 8)*

- **R-GHOST-1 Three-day close.** A prospect who went silent before the gate completed, about 3 days after our last pending question, gets one "close" message: the room is still open (with the price), and "Should I close this out, or are you still looking?". In the owner's sessions these were owner-approved batches.
- **R-GHOST-2 Reactivation.** Inquirers who never received a qualifying question (for example from before the agent ran) get a reactivation message that restarts the gate. Owner-approved batches (Oct 8, Oct 12).

### 3.10 Multi-listing routing (Oct 8, 13:36)

- **R-ROUTE-1** A thread tied to one listing is that listing; do not ask which one.
- **R-ROUTE-2** An ambiguous inquiry is narrowed before disclosure (stage `ROUTING`).
- **R-ROUTE-3** Record the pick as `listing_of_interest` in the register; if they switch, update it. The register always shows the current interest.
- **R-ROUTE-4** If the picked listing is full or goes unavailable, offer the other live listings before parking a qualified person.
- **R-ROUTE-5** The same router applies on every channel. On channels the agent cannot automate (iPhone texts), it prepares one-tap drafts for the owner and steers deep conversations to Messenger.

### 3.11 Timing and burst handling (Oct 4, 21:40 and 21:55; Oct 17)

- **R-TIME-1** Detect new messages fast (the owner asked for a 10 second poll).
- **R-TIME-2 Quiet window.** Act on a thread only after its newest message has been unchanged for 60 seconds, so a prospect writing in bursts gets one handling pass per burst. Small-talk re-asks wait about 120 seconds (R-GATE-4).
- **R-TIME-3 One handler per thread.** Never run two handlers on the same thread at once. A crashed handler's lock expires on its own.
- **R-TIME-4 Re-check before send.** Re-read the thread right before sending the last message of a pass; if the prospect wrote in the meantime, fold it in and revise.
- **R-TIME-5 Linger.** After a pass, keep watching the thread for about a minute at a time, so an active conversation is answered in about a minute.
- **R-TIME-6 No silent failure** (Oct 17). Alert the owner if a prospect message sits unanswered for more than 10 minutes, and when the platform session drops.

### 3.12 Auto-send boundaries (Oct 4; restated Oct 17)

The owner does not want to approve every message (Oct 4, Oct 17), but every commitment is his.

**May auto-send** (non-committal, grounded in records): routing, disclosure, house rules, the walkthrough video, gate questions and re-asks, woven small-talk re-asks, FAQ answers using only record facts, the one holding line on an escalation, the not-now warm reply and timeframe question, the hard-no close, cadence check-ins and reconnects.

**Never auto-commit** (needs the owner's fresh yes for that prospect and that time): confirming a showing or video-call time, accepting a price or discount, a hold, a lease term outside the rules (below 6 months), payment terms or a payment plan, any pet or rule exception, sending the application link without a confirmed tour.

**Owner-approved drafts** (agent prepares, owner sends or approves): three-day closes, reactivation batches, far-out check-backs, group-post replies on the owner's personal profile, text-message replies.

**R-SAFE-1 No live sends during development** (Oct 11): during development nothing reaches a real person without the owner's permission for that send; tests go to the owner only. The Oct 17 service runs in shadow mode by default and needs two separate switches (a setting plus a dated authorization written by the owner) to send live. In this repo that is hackathon rule 4 and `world.mode` with stop-before-submit.

### 3.13 Escalation rules

Each escalation carries the thread reference, the reason and a draft reply. At most **one** holding line goes to the prospect per escalation ("Thanks, let me check on that and get back to you."), and the gate can continue in the same message where the rule says so.

| ID | Trigger | Agent does | Source |
|---|---|---|---|
| R-ESC-1 | Price, discount, deal or payment-terms request | Never promise. Escalate with a draft; tell the prospect I will check; keep collecting the gate. | Oct 4 |
| R-ESC-2 | Lease below 6 months | Do not agree. Escalate; the owner may price an exception himself (a short stay should not be given away at standard rent). | Oct 4; Oct 6 |
| R-ESC-3 | Question not answered by the records, or a fact marked unconfirmed | "I'll confirm the exact details"; escalate with a draft. | Oct 4; Oct 12 |
| R-ESC-4 | Owner took over the thread, moved it to text, or negotiates personally | Stage `STAND_DOWN` / `exception` flag: send nothing; escalate every new message; never quote a price in a no-price thread. | Oct 4; Oct 6; Oct 12 |
| R-ESC-5 | Third small-talk non-answer on the same item | Escalate instead of a third re-ask. | Oct 17 (implementation) |
| R-ESC-6 | Gate complete | Notify the owner with the full prospect summary (§6). | Oct 4 |
| R-ESC-7 | Showing proposed | Owner confirmation request (R-SHOW-5). | Oct 4 |
| R-ESC-8 | No on-the-way confirmation by start time | Report; no showing. | Oct 4 |
| R-ESC-9 | Tour end time passed | Tour-happened ping (R-APP-1). | Oct 5 |
| R-ESC-10 | Parked, applied, closed, cold, reconnect sent | One report each. | Oct 5 |
| R-ESC-11 | Message unanswered over 10 minutes, platform signed out, video missing | Alert. | Oct 17; Oct 4 |
| R-ESC-12 | Tenant hardship (cannot pay, needs more time) | Propose a solution (for example a payment plan) to the owner with a draft; never agree it or escalate adversarially. | owner, Oct 18 |

---

## 4. Listing records the flow depends on

The flow quotes only what these records hold. Per-listing facts never go into the general rules (Oct 4, 15:24: one general rule set plus one record per listing).

Required per listing: public street and area; type; private and shared spaces; rent; deposit; utilities (amount and split); 2-occupant rent, deposit and utilities (or "not offered"); availability date; lease (public: 1 year); pet policy (`none` | `closed_off_only` | `cats_and_closed_off` with fee and extra deposit | `unconfirmed`); smoking and parties; walkthrough video asset (or none); application link; a list of `unconfirmed` fields that may never be quoted; furnished (yes/no/unconfirmed); max occupants.

New listing (Oct 4): the agent creates the record from the owner's words and the live listing, applies the general rules, and asks the owner for anything missing (video, availability exceptions, rule differences) before that listing's flow is fully active. When new supply arrives, match it against the register before it goes fully public (Oct 8; §5.4).

---

## 5. Demand register

### 5.1 Schema (one row per person, channel agnostic)

Built Oct 7 to 8; system of record moved to the demand platform's intake API on Oct 12 (outside this repo).

| Field | Type | Notes |
|---|---|---|
| `renter_id` | string | stable id |
| `name` | string | as given |
| `sources[]` | `{channel, source_detail, captured_at}` | every channel the person came through; a second channel merges into the same row |
| `language` | `en` \| `es` \| ... | |
| `status` | enum §5.2 | |
| `contact` | `{phone, email, thread_refs[]}` | |
| `consent` | `{email, sms}` | `none` unless the person opted in; imports can never set it (Oct 11) |
| `wants.areas` | `{raw: [phrases], resolved: [canonical areas]}` | raw words are never lost |
| `wants.type` | room \| apartment \| house \| ... | |
| `wants.private_bath` | bool \| null | |
| `wants.budget_max_usd`, `wants.budget_notes` | number, string | |
| `wants.move_in`, `wants.stay_months`, `wants.occupants`, `wants.pets` (`{kind, enclosed}`), `wants.furnished` | | unstated stays null, never a default (Oct 16 data fix) |
| `gate` | five items `{status, value/date, raw}` | statuses: `answered`, `vague`, `no`, `exception`, `absent` |
| `listing_of_interest` | listing id | current pick; `interest_history[]` keeps earlier ones |
| `proxy` | `{is_proxy, actual_seeker_confirmed}` | R-GATE-6 |
| `followup` | `{application_sent_at, anchor_at, gap_index, next_due_at, checkins_sent, responses, last_evaluated_at}` | §3.7 |
| `paused_reason`, `reconnect_at` | string, date | §3.8 |
| `sourcing` | `{opened_at, due_at, outcome}` | R-PHIL-2 step 2 |
| `notes`, `created_at`, `updated_at` | | |

Rules: never delete a row (Oct 8). Dedupe on phone or email (and name plus contact); merge and keep both sources. The register is private business data, never published.

### 5.2 Statuses

| Status | Meaning | Thread stages that map here |
|---|---|---|
| `NEW` | captured, no outreach or criteria mostly unknown | new thread |
| `CAPTURED` | seen in a public post, no conversation yet (outreach is a draft for the owner) | group seeker post |
| `CONTACTED` | outreach sent, awaiting reply | `ROUTING`, opening burst sent |
| `QUALIFYING` | gate in progress | `DISCLOSURE` to `QUALIFYING` |
| `QUALIFIED` | gate complete, no showing yet; with no fitting supply this is waiting demand, the most valuable kind | `QUALIFIED`, `SHOWING_*`, `TOUR_ENDED` |
| `APPLIED` | application submitted or post-tour cadence running | `APPLICATION_SENT`, `APPLIED` |
| `PARKED` | not now, with `reconnect_at` | `PARKED`, `RECONNECT` |
| `PLACED` | housed; kept, future demand at lease end | after lease |
| `CLOSED` | hard no, found another place, or about 45 days silent after full follow-up | `CLOSED` |

Mapping to the current `upsert_renter` enum: `new`→NEW, `qualifying`→QUALIFYING, `qualified`/`showing_proposed`/`showing_confirmed`→QUALIFIED, `applied`→APPLIED, `leased`→PLACED, `not_now`→PARKED, `lost`→CLOSED, `escalated` is an overlay, not a status. Missing today: `CAPTURED`, `CONTACTED`.

### 5.3 Clusters, weekly rollup, supply signal (Oct 8; reconciliation rules Oct 9 and Oct 12)

- **Cluster key**: primary resolved area + type wanted + budget band. A band is a group whose budgets differ by at most about $150 (for a deterministic implementation: $150-wide buckets).
- Count **distinct people** (merged rows count once). Active = status not `PLACED` or `CLOSED`.
- **WATCH**: 3 or more active people in a cluster.
- **SUPPLY SIGNAL**: 5 or more **qualified** people in a cluster. A cluster that reaches 5 only by counting unqualified people, people with no stated budget, or proxy posts is reported as "nominal 5, not a signal" *(Muse practice, Oct 9 and 12, after two false alarms)*.
- **Weekly rollup** (Mondays about 9 AM Eastern): (1) new captures in the last 7 days by channel; (2) totals by status; (3) clusters, WATCH list, any SUPPLY SIGNAL as the headline; (4) matches of QUALIFIED, CONTACTED or CAPTURED people to available rooms, with the reason each fits; (5) stale `NEW`/`CAPTURED` rows older than 14 days with no outreach; (6) channel housekeeping (for example groups the owner joined that are not watched yet). First reconcile the register against the last 7 days of threads so no inquirer is missing.

### 5.4 Matching (Oct 11 fixes; Oct 16 area rules)

Hard disqualifiers: type mismatch (a whole-unit seeker never matches a room and the reverse); budget more than 15 percent below rent; occupants above the room maximum; a known pet policy that bans the seeker's pet (an unknown policy never disqualifies); a wanted stay clearly shorter than the room's minimum (an unknown minimum never disqualifies). A profile needs at least 2 **stated** criteria to be matched; defaults do not count.

Areas (Oct 16, the owner's example: "5 minutes from the airport" or "between the airport and Garner"):

- A phrase can resolve to a **set** of canonical areas; a seeker naming two areas matches either.
- Landmarks: airport/RDU expands to Morrisville, Cary, Raleigh, Durham. "Near Duke" stays Durham.
- Corridors: "between X and Y" expands to the endpoints plus the areas between (RDU to Garner: Morrisville, Cary, Raleigh, Garner; Durham to Raleigh: Durham, Morrisville, Cary, Raleigh; Chapel Hill to Durham; Chapel Hill to Raleigh: Chapel Hill, Durham, Morrisville, Cary, Raleigh).
- Adjacency is a soft match: a room in an area next to a stated area scores lower but is not disqualified.
- A phrase that resolves to nothing is "unknown area", not a disqualifier.

### 5.5 Channel registry (Oct 8; classes Oct 11)

A channel becomes ACTIVE only when its first real lead is in the register (Oct 8). Every intake route writes the same register fields; fields a channel cannot supply stay blank and are filled during qualifying.

| Class | How capture works | Channels |
|---|---|---|
| A: API or webhook | The platform pushes leads or exposes an API | own website and concierge form; Facebook Page Messenger; lead emails (Furnished Finder and Zillow-family leads arrive as email) |
| B: agent monitored | The agent watches a surface no API exposes, acting as the owner | Marketplace threads on the owner's profile (10 s poll, full flow); about 23 Triangle housing groups on Facebook (scanned every 15 minutes, every genuine seeker logged, fit or not) |
| C: paste packages | No usable API; the agent drafts, a human posts, replies are captured | Roomies, Craigslist, Facebook group posts |
| D: platform programs | Listings live on the platform; demand mirrored from its messages and emails | PadSplit, Furnished Finder, Airbnb (whole units only, later) |
| Search | Captured at landing pages, never per search | Google Ads (paid, on intent queries) and SEO pages, Google Business Profile |

Status at Oct 17: Marketplace, Page and groups ACTIVE; Furnished Finder MANUAL (owner forwards leads); iPhone texts are draft-only (no read access); SpareRoom the website EXCLUDED (Oct 8, "frankly a scam"); candidates: Roomies, Cirtru, university off-campus portals (Duke, UNC, NC State, NCCU), Craigslist, Roommates.com, Zumper, Zillow Rental Manager, HotPads, PadMapper, Diggz, Reddit, Nextdoor. Paid Facebook ads were stopped Oct 14 (no useful leads); focus is organic posting (Oct 16).

This repo's sandbox `world.channels` has marketplace, roomies, craigslist, padsplit, sms, email: a subset of classes B, C and D.

---

## 6. Owner reporting

Per active prospect (Oct 4): name, listing, occupants, stay length, move-in date, reason, phone (once collected), video sent (yes / no / blocked), proposed or confirmed showing time, on-the-way confirmation (received / not), application link sent, current stage. Owner messages follow R-STYLE-4 and R-STYLE-10, and the agent does not re-raise a topic the owner closed (for example calendar overlaps, Oct 9; one public caption he chose to leave, Oct 12).

---

## 7. Decisions the owner reversed (implement the latest)

| Topic | Earlier | Latest (implement this) | When |
|---|---|---|---|
| Voice | Messages referred to the owner by name | First person "I" | Oct 4, 17:08 |
| When a proposed event may be created | Agent could propose a time and put a proposed event on the calendar during the chat | Nothing on the calendar, not even proposed, until all gate items are exact | Oct 4, 17:12 |
| Gate items | Stay length, reason, phone (Oct 4, 15:18) | Five items: lease, exact move-in, phone, reason, occupants; exact answers only | Oct 4, 17:12 and 21:31 |
| Lease question | "How long are you planning to stay?" | "How long do you want to stay? Is a one year lease okay with you?" | Oct 4, 21:25 |
| Public lease wording | "6 months minimum, 1 year preferred" | "Lease: 1 year"; 6 months only if they ask for shorter; not even the word "minimum" | Oct 4, 21:27 and 21:31 |
| Language switch | Switch to their language when English is incoherent | Ask "Do you speak Spanish?" first; switch only on yes | Oct 4, 17:41 then 17:44 |
| Response speed | Check every 15 minutes | 10 s poll, 60 s quiet window, one handler, re-check before send, linger | Oct 4, 15:24, 21:40, 21:55 |
| After the tour | Send the application automatically at the end of the tour | Ping the owner; send only after he confirms the tour happened | Oct 5, 12:18 (same message) and 12:22 |
| Small talk during the gate | Escalated as an ambiguous answer | Woven re-ask with new wording after an extra minute (max 2 per item) | Oct 17, 12:09 |
| Per-message approval | Each send needed the owner's tap (platform limit) | Non-committal sends go out without approval; commitments still need the owner; deterministic always-on service | Oct 17, 11:47 |
| Pets | No pets | Closed-off pets allowed except rodents and rabbits; roaming pets no, except cats where the listing allows ($20/month, $100 extra deposit) | Oct 12, then Oct 14 |
| Lead offer | $750 listing price with "$100 off the first month" as the hook (Oct 4) | Do not lead with the discount in outreach (Oct 8); prices reset Oct 16 (mini studio $850, exterior-bath rooms $750, interior-bath master $775) | Oct 8, Oct 16 |
| Two-occupant pricing | Not offered or unknown per listing | Quoted where confirmed, single-occupant rate first | Oct 15 |
| Showing availability | Blocks created two weeks at a time | Perpetual daily 8 AM to 8 PM blocks, topped up weekly | Oct 12 |
| Paid ads | $3/day Facebook ads | Stopped; organic posting | Oct 14, Oct 16 |
| SpareRoom | Recommended by the agent as a channel | Excluded; owner mentioned trying it on Oct 11, still undecided | Oct 8 (open, §8) |
| Scheduling in the Oct 17 service | Rules let the agent negotiate a slot and create the proposed event | The Oct 17 service v1 escalates at gate completion and leaves scheduling to the owner | Oct 17 (implementation choice, not an owner rule; this repo follows the rules version with `propose_showing`) |

---

## 8. Open questions

Logged by the agent in the owner's sessions and still unanswered, plus gaps found while writing this spec.

1. **Sourcing window.** How many days is "within days" before a non-fit person is parked? (spec default proposal: 3 days)
2. **Supply signal threshold.** Must all 5 be gate-complete, or is stated area + type + budget enough? (Muse treated unqualified fives as "nominal".)
3. **Tenant payment plans.** What plan shapes may the agent propose (split rent, shift due date, catch-up schedule)? At what point does the owner want the adversarial path (late fee, legal notice) raised? Does the agent ever send a plan the owner approved, or does the owner always send it?
4. **SpareRoom.** In as a time-boxed experiment with its own source tag, or stays excluded.
5. **Google Ads test budget**, once landing pages are canonical.
6. **Furnished Finder and PadSplit lead routes**: which mailbox the leads reach, so parsers can be built.
7. **Outbound to the register.** Real match alerts and reactivation from the demand platform have never been sent; most captured people have no consent and no email or phone.
8. **Far-out move-in threshold.** How far out is "too far" to show the room now (R-PARK-6)?
9. **Vague-answer limit.** How many vague answers on one item before escalating? (Oct 17 service re-asks once; hackathon D23 allows one confirmation of an already-given answer.)
10. **Three-day close follow-through.** What happens after a close gets no reply: `CLOSED`, or stay `CONTACTED` for reactivation?
11. **Unconfirmed listing facts** still pending at Oct 17 for one house (how many people share the spaces) and most facts for the newest room (deposit, utilities, lease, rules, furnished).
12. **Text messages.** Pair a Mac or Android for read access, or stay draft-only.
13. **Address timing.** The full address is given at booking (Muse practice); confirm whether at proposed or only at confirmed.

---

## 9. Conformance checklist

Each item is one testable behavior. **Covered by** names what exists in this repo today (`contracts/tools.md` tools, `send_message` guards, Gym checks in `gym/rentus_env/verify.py`). **Missing** names the tool, state or check still needed. "Prompt only" means the behavior is asked for in `operator/prompts/system_v3.md` but nothing enforces or scores it.

### Voice and style

| # | Behavior | Covered by | Missing |
|---|---|---|---|
| C1 | No prospect message has more than 2 sentences. | `send_message` POLICY_BLOCKED (`max_two_sentences`); Gym `style` check | none |
| C2 | No prospect message contains more than one question. | `send_message` (`one_question`); Gym `style` | none |
| C3 | In a burst of several messages, only the last one contains a question, and nothing is sent after it until the prospect replies. | none | burst-level check over consecutive operator messages; a way to send a burst without a scripted reply after each message (see C14) |
| C4 | No em or en dash in any prospect or owner message. | `send_message` (`no_long_dashes`); Gym `style` | same check on `report_to_owner` / `escalate_to_owner` text |
| C5 | Prospect messages never refer to the owner in the third person ("the owner", the owner's name). | Gym `style:first_person` (scored only) | a `send_message` guard; this check failed 30 times in 99 final held-out rollouts |
| C6 | Every dollar figure in a message exists in the room or listing record. | `send_message` (`price_not_in_record`) | none |
| C7 | A public listing or post never contains the house number. | none (`address_public` is currently an alias of the full address) | a real `address_public` field (street only) and a guard in `create_listing` / `publish_listing` |
| C8 | The full address is sent to a prospect only once their showing is confirmed. | none | address guard in `send_message` keyed on calendar status |
| C9 | When 2-occupant pricing exists, the single-occupant rate is stated first. | none | 2-occupant fields on rooms; message-order check |
| C10 | Asking for the lease uses "Is a one year lease okay?" and asking for move-in asks for the exact date. | prompt only; Gym `message` checks where a task sets them | none beyond task coverage |

### Language

| # | Behavior | Covered by | Missing |
|---|---|---|---|
| C11 | A thread that started in Spanish gets only Spanish replies until the prospect switches. | `send_message` (`language_mismatch`, en/es); Gym `style:language` | other languages |
| C12 | When a prospect writing English gives 2 or more incoherent or off-language replies, the agent's next message is a single "Do you speak <language>?" question, and it does not switch before a yes or a reply in that language. | reader `language` field only | thread state `language_probe`; reader signal for incoherence; Gym task family |
| C13 | The suspected language is never inferred from the name alone (a Spanish-named prospect writing fluent English stays in English). | none | Gym task |

### Opening and disclosure

| # | Behavior | Covered by | Missing |
|---|---|---|---|
| C14 | On a new thread tied to a listing, the agent sends full disclosure (type, private/shared, rent, deposit, utilities, 2-occupant pricing, street, availability) before the first gate question. | none (prompt v3 says "Do not list room facts unless asked", which contradicts this) | prompt change; disclosure-coverage check; a send-burst mechanism so a counterpart does not answer each disclosure message |
| C15 | House rules (pets per R-PET-1, no smoking, no parties) are stated before qualifying. | none | structured `rules` on rooms; check |
| C16 | The walkthrough video is sent before any showing is proposed; if the listing has none, the agent tells the owner and never claims it was sent. | none (`get_listing_media` returns photos only) | `video` asset on rooms, attachment type video, `video_sent` state, `never` check |
| C17 | Never states an availability date in the past; an active listing with no date is "available now". | none | guard against past dates |
| C18 | An `unconfirmed` listing fact is never quoted; the agent says it will confirm and escalates. | partially: `escalate_to_owner` exists | `unconfirmed[]` on rooms; guard |

### Qualifying gate

| # | Behavior | Covered by | Missing |
|---|---|---|---|
| C19 | Never proposes a showing time (in text or on the calendar) before all five gate items are exact. | `propose_showing` POLICY_BLOCKED; Gym `never propose_showing before gate_complete` | guard on time offers in message text before the gate (the booking guard only blocks "confirmed") |
| C20 | A vague answer (a month, "soon", "as long as necessary") leaves the item pending and the next question asks for the exact answer to that item. | `read_reply` statuses; `upsert_renter` gate; Gym `state` checks | none |
| C21 | An item the prospect already gave, including one volunteered out of order, is never asked again. | Gym checks (D23c allows one confirmation) | none |
| C22 | When a prospect proposes a time with items pending: no event is created and the reply acknowledges the time, says details come first, and ends with the pending question. | `propose_showing` block; prompt | Gym check that the reply ends with the pending item |
| C23 | A content-free reply (compliment, emoji, "ok") gets one message that acknowledges it and re-asks the pending item in different wording (not identical to the last ask). | reader intent `small_talk`; prompt | check: re-ask text differs from the previous ask; no escalation |
| C24 | The small-talk re-ask waits about 120 s after the last message, and is cancelled if a real answer arrives in that window. | none | clock-driven quiet windows in the sandbox |
| C25 | A third small-talk non-answer on the same item escalates instead of a third re-ask. | none | per-item re-ask counter in thread state |
| C26 | The 6-month option is never mentioned before the prospect asks for a shorter lease. | `send_message` (`lease_floor_not_requested`) | none |
| C27 | After the prospect asks for shorter, accepting 6 or more months closes `lease` with no owner check; below 6 months is never agreed and is escalated. | `send_message` (`lease_term_not_in_record`); `upsert_renter` `gate.lease.months`; Gym `escalated` | none |
| C28 | A price, discount or payment-terms request is escalated with a draft, the prospect gets at most one holding line, and the gate continues. | prompt; Gym `escalated` | "at most one holding line per escalation" check |
| C29 | A proxy poster is recorded with `proxy.is_proxy`, and on contact the agent confirms who the actual seeker is and the real occupant count. | none | `proxy` field; Gym task |

### Scheduling and showings

| # | Behavior | Covered by | Missing |
|---|---|---|---|
| C30 | Proposed slots fall inside an availability block and do not overlap another showing; non-showing events are ignored. | `find_showing_slots`, `propose_showing` (CONFLICT) | default blocks 8 AM to 8 PM daily (policy default is 10:00 to 18:00) |
| C31 | The prospect is never told a time is confirmed until the owner confirms it. | `send_message` booking guard (`showing_not_confirmed`) | none |
| C32 | Owner confirmation by either signal (owner message, or calendar edit) produces exactly one "confirmed" message to the prospect. | none outside the console stub | `confirm_showing(event_id)` owner tool and a calendar-edit path; dedupe |
| C33 | An owner reject leads to an alternative proposal or a polite close, never a confirmation. | none | `reject_showing`; check |
| C34 | When a time is confirmed, the one-hour-before rule is sent as its own message, and the deadline is stored on the event. | none | event field `on_the_way_by`; check |
| C35 | Without an on-the-way message by the start time, the showing is marked no-show and the owner is told. | none | clock advance; `on_the_way` state; owner report |
| C36 | In hybrid mode the prospect is told before travel that I will not be there and how entry and the call work; a hybrid showing is never confirmed without the owner confirming a housemate. | none | event `mode` (in_person / video_call / hybrid) |
| C37 | A video call follows the same proposed then confirmed flow and phone requirement. | `propose_showing` | `mode` |

### After the tour

| # | Behavior | Covered by | Missing |
|---|---|---|---|
| C38 | After a showing's end time the owner gets exactly one "did it happen?" ping, and nothing goes to the prospect before he answers. | none | clock advance; `tour_ended` state; `confirm_tour(event_id, happened)` owner tool |
| C39 | On the owner's yes, the post-tour message goes out in order: warm line, application link, one line on what the application asks, then "Are you interested in moving forward?" last. | none | application link on rooms or policy; message-order check |
| C40 | The application link is never sent without a confirmed tour, and never twice for the same tour. | none | guard in `send_message` |
| C41 | Check-ins follow 12, 12, 12, 12, 24, 24, 48, 96, 192... hours from the later of the application send and the last reply. | none | follow-up state on the register; a `tick(now)` / clock advance in the sandbox |
| C42 | A substantive reply resets the cadence (next check-in 12 h after it); a check-in is never sent if the prospect wrote since the last evaluation. | none | same |
| C43 | Applied, not interested, found another place, or about 45 days of silence stop the cadence with one owner report. | partially: statuses `applied`, `lost` | `cold` reason; check |

### Not now, hard no, silence

| # | Behavior | Covered by | Missing |
|---|---|---|---|
| C44 | A not-now reply gets one warm message and one timeframe question; it is never closed. | reader intent `not_now`; prompt | Gym check on the timeframe question |
| C45 | A not-now prospect is parked with `reconnect_at` set from their stated timeframe (a named month = the 1st of that month, an exact date = that date). | status `not_now` only | `reconnect_at`, `paused_reason` fields on the register |
| C46 | With no timeframe after asking, `reconnect_at` = now + 30 days. | none | same |
| C47 | On `reconnect_at`, exactly one reconnect message goes out; it names a specific room only if that room is still live; the cadence resumes at 48 h. | none | clock advance; reconnect state |
| C48 | A hard no gets one short kind close and status CLOSED (`lost`), and nothing after. | reader intent `hard_no`; router ESCALATE_DIRECT; Gym `state` | reliability: the register status is missed in about half of final runs |
| C49 | A qualified prospect with a move-in months away is parked with a check-back, and the check-back is a draft for the owner. | none | far-out threshold (open question 8) |

### Routing, stand-down, safety

| # | Behavior | Covered by | Missing |
|---|---|---|---|
| C50 | A thread tied to a listing never gets a "which listing?" question. | `thread_room` resolves the listing | check |
| C51 | An ambiguous inquiry gets one short message per live listing and one "which one?" question before any disclosure. | none | routing stage; Gym task family |
| C52 | The pick is recorded as `listing_of_interest` and updated if the prospect switches. | `upsert_renter.listing_of_interest` | `interest_history[]` |
| C53 | When the picked room is unavailable, other live rooms are offered before parking a qualified person. | `match_renters` (scoring only) | check |
| C54 | In a thread the owner took over (or marked no-price), the agent sends nothing and escalates every new message. | none | thread flags `owner_owned`, `no_price`; `send_message` guard |
| C55 | In sandbox or live mode nothing reaches a real person without the owner's click. | `world.mode`, live adapters stop before submit | none |
| C56 | Bursts are handled once: several messages before a reply produce one reply that accounts for all of them. | router `BATCH` | quiet-window timing in the sandbox |
| C57 | An inbound message unanswered for 10 minutes raises an owner alert. | none | clock; alert event |

### Register, matching, rollup

| # | Behavior | Covered by | Missing |
|---|---|---|---|
| C58 | No tool deletes a register row. | no delete tool exists | keep it that way (add a test) |
| C59 | A person reaching us on a second channel (same phone or email) is merged into one row with both sources. | none (`upsert_renter` keys by thread) | `sources[]`; dedupe by phone/email |
| C60 | A non-fit seeker is captured with criteria, gets an honest "noted, will reach out when something fits" reply, and a sourcing task with a due date. | `upsert_renter` (partial fields) | `sourcing` field; `wants.stay_months`, `furnished`; check |
| C61 | Matching disqualifies on type mismatch, budget over 15 percent below rent, too many occupants, a known banned pet, and a stay below the minimum; unknown values never disqualify; fewer than 2 stated criteria means "not matchable yet". | `match_renters` (occupants only; others are soft scores) | the other hard gates and the 2-criteria rule |
| C62 | Area phrases resolve to sets: "near the airport" matches a Morrisville room; "between the airport and Garner" matches Cary and Raleigh rooms; an adjacent area scores below an exact one; an unknown phrase does not disqualify. | none (`match_renters` compares one area string) | area resolver |
| C63 | The weekly rollup reports captures by channel, totals by status, WATCH clusters (3+), SUPPLY SIGNAL clusters (5+ distinct qualified), matches with reasons, and stale rows over 14 days. | none | `demand_rollup(as_of)` tool |
| C64 | A cluster of 5 that includes unqualified, no-budget or proxy entries is reported as nominal, not as a supply signal. | none | same |
| C65 | When a room becomes available, `match_renters` runs before `publish_listing`, and matched people are surfaced to the owner first. | `match_renters` exists | ordering check (`never publish_listing before match_renters`) |

### Pets and tenants

| # | Behavior | Covered by | Missing |
|---|---|---|---|
| C66 | Pet answers follow R-PET-1/2: an enclosed lizard is allowed; an enclosed rabbit or rat is not; a dog is not; a cat only where the room allows, with its fee and deposit quoted from the record. | none (`pets` is free text) | structured pet policy and an evaluator used by `send_message` and `match_renters` |
| C67 | A tenant who says they cannot pay on time gets a solution proposal drafted for the owner (for example a payment plan); the agent never agrees a plan, waives a fee or threatens escalation itself. | `escalate_to_owner` exists; ops flow covers maintenance only | tenant ledger/state; Gym task family; `send_message` guard on plan or fee commitments |

---

## 10. What this repo is expected to implement first

The order and effort estimates are in `docs/spec/gap-analysis.md`.
