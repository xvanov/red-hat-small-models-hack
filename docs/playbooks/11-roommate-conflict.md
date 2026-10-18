# 11. Roommate conflict

## Goal

Lower the temperature, turn a complaint into a specific, fair house-wide expectation, and keep everyone housed. The agent never takes sides in writing and never judges people. Spec: none yet (new).

## What the real threads show (aggregate)

House-rule and conflict topics appear in about 100 threads: cleaning and dishes, noise and quiet hours, guests, laundry timing, parking and driveway blocking, temperature, shared food and items. Cleaning and trash rotation alone runs through about 240 threads, mostly tenants among themselves. The owner's good moves: asking clarifying questions before acting (what kind of noise, what time of day, how often), sending a reminder to everyone rather than singling someone out, defining a standard concretely (leave a shared space as you found it or better), and answering an abusive message with a short, factual note of obligations and no insults back. The weaker moves: sharp public rebukes in the group chat and messages that read as choosing a side.

## Ideal flow

1. **Listen and clarify in private.** Thank the person, then one question at a time: what exactly, when, how often, has it been raised with the housemate.
2. **Check the record:** the house rules and the lease. Is there a rule that covers it (quiet hours, guests, cleaning rotation)?
3. **First response is general, not personal:** a friendly house-wide reminder of the rule, without names (`broadcast_to_house`, missing). Tell the reporter that you sent it.
4. **Repeat complaint:** a private, calm message to the housemate concerned: the rule, the specific behavior, what you need from them. No quoting the complainer.
5. **Still going, or it is serious:** escalate to the owner with a short timeline and drafts.
6. **Someone leaves angry or gives notice in anger:** acknowledge calmly, confirm the facts (notice date, what the lease says about utilities and the room's condition), and report to the owner. Do not argue.

## Decision points (escalate immediately on any of these)

| Signal | Agent does |
|---|---|
| Threats, violence, harassment, or someone feeling unsafe | Safety first (911 if in danger); escalate at once |
| Accusations about race, religion, origin, disability, sex, family status | No comment on the claim; escalate at once (fair housing) |
| Police, a lawyer, or the courts mentioned | Holding line; escalate |
| Same complaint a third time | Escalate with the timeline |
| Unauthorized occupant, a guest effectively living there | Facts only; escalate |
| Someone requests a room move | Check live rooms; escalate |

## Phrasing

Do:
- Use "everyone" and the rule, not names, in group messages.
- Be concrete: "please run laundry outside quiet hours, 10 PM to 8 AM".
- Keep it brief and calm, even when the other person is not.

Don't:
- Forward one tenant's words or name to another.
- Use sarcasm, capitals, or "I asked you this already" in a group.
- Decide who is right, or describe anyone's character.
- Mention eviction or penalties; that is the owner's call.

## Tools

Exists: `send_message`, `escalate_to_owner`, `report_to_owner`, `list_rooms`.

Missing: `broadcast_to_house`, house rules as a structured record, tenant records, multi-party (group) threads in world state.
