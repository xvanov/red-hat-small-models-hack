# 07. Post-tour application nudges

## Goal

Turn a finished tour into an application, or into a clear answer, with check-ins that stay friendly as they space out. Spec: §3.7 (R-APP-1 to R-APP-3).

## What the real threads show (aggregate)

By 2026 the owner sent the application form to nearly everyone who toured. The application asks for income proof and a background check; real blockers were missing pay stubs (bank statements or an offer letter work), a parent paying, and simple busyness. The owner's good moves: telling a stuck applicant to submit the rest first and add documents later, and asking the direct "are you still interested in moving forward?". The thing to drop: repeating "did you get a chance to fill in the application?" in identical words.

## Ideal flow

1. Tour end time passes: ask the owner once whether it happened. Nothing goes to the prospect before his yes.
2. On yes, in order, short messages: a warm line that they got to see the room; the application link; one line that it is online, takes a couple of minutes, and asks for income verification and a background check; last, "Are you interested in moving forward?"
3. Check-ins on the cadence 12, 12, 12, 12, 24, 24, 48, 96 hours and doubling, from the later of the send and their last reply. Re-read the thread before each one.
4. Early check-ins offer help ("anything blocking you on the form?"); later ones are lighter. Each ends on the moving-forward question.
5. A blocker comes up: solve it with facts the owner has approved (other income documents accepted, guarantor allowed), else escalate.
6. Stop on applied (report, owner approves applicants), not interested (kind close), or about 45 days of silence (close cold).

## Decision points

| Situation | Agent does | Owner |
|---|---|---|
| "No pay stubs" / self-employed / cash income | Say what other proof is accepted, if the owner has set it; else escalate | escalate |
| Parent or guarantor paying | Capture; escalate for approval | escalate |
| "I applied" | Stop cadence, report | approves |
| Asks to hold the room | "The deposit holds the room" only if that is the owner's rule; never promise a hold | escalate |
| Another applicant is ahead | Honest, factual, no pressure tactics | owner decides |

## Phrasing

Do:
- Make it feel easy: a couple of minutes, online.
- Offer help with the specific step, not generic "let me know".
- Vary the wording on every check-in.

Don't:
- Send the link before the owner confirms the tour, or twice for the same tour.
- Invent urgency ("someone else is about to take it") unless it is a fact the owner gave.
- Approve or reject an application. That is the owner's call.

## Tools

Exists: `send_message`, `upsert_renter` (status `applied`, `lost`), `report_to_owner`, `escalate_to_owner`.

Missing: `confirm_tour(event_id, happened)`, `send_application(renter_id)` (with a send-once guard), `record_application(renter_id, status, docs)`, follow-up state and `schedule_followup`, an application link on rooms or policy.
