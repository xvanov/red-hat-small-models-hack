# Task review: Gym task set v1 (31 held-out, 51 train)

Reviewed 2026-10-17, without running any model. Sources read: `gym/build_tasks.py`, `gym/tasks/*.jsonl`, `gym/rentus_env/` (scorer and scripted counterparts), `tools/rentus_tools/` (what the tools enforce), `contracts/tools.md`, `data/published/inventory.json`, `docs/results.md`, and the business rules in `rentus-room-agent/rules/general-rules-of-engagement.md` (domain knowledge only). The stored transcripts in `gym/results/` were used to cross-check findings, never to tune anything.

This sheet covers **v1**, the task set every committed result used. The fixes are in **v2** (`gym/tasks/v2/`), described in `docs/task-v2-changes.md`. v1 is unchanged.

How to read it:
- **OK**: the task tests what it says and the checks agree with the business rules.
- **FLAWED**: a check can fail correct behavior or pass wrong behavior, or the task contradicts the rules or the room record.
- **WEAK**: the task is sound but tests very little (a do-nothing or near-do-nothing run gets most of it), or it duplicates another task.
- Each held-out task ends with **Owner verdict: ___** for you to fill in.

## Summary

| | held-out (31) | train (51) |
|---|---|---|
| **OK** | 9 | 25 |
| **FLAWED** | 18 | 22 |
| **WEAK** | 4 | 4 |

Verdicts are for each task's own content. The four global flaws below (G1 to G4) affect most renter-facing tasks on top of that.

### Flaw counts by type (number of tasks)

| type | held-out | train | what goes wrong |
|---|---|---|---|
| Move-in date before the room is free | **8** | 14 | The renter's date comes from the reader dataset label and was never compared with the room's `available_from` (6 to 134 days early). An operator who points it out gets no reply. In the Opus run, 6 held-out tasks have an availability message the renter never answered, and all 6 are on this list. |
| Vague date contradicts the exact date that follows | 2 | 3 | "sometime in january" then "november 1"; "whenever it's ready" then a date 3 months after the room is free; "around the 15th" then the 10th. |
| Renter can't answer a reasonable clarifying question (G4) | 19 | 30 | No fallback lines at all: a confirmation ("so that's Dec 1?"), a correction, or any off-script question gets silence. |
| Check penalizes correct behavior | 8 | 10 | "discount" banned (so "I can't offer a discount" fails): 2 / 3. "males only" must be removed though the compliance tool doesn't flag it: 2 / 0. One-shot publish fault, so a successful retry is punished for not escalating: 2 / 4. "None" banned case-insensitively, so "none" fails: 1 / 2. Volunteered "the 1st" (month unclear) where confirming it fails "does not re-ask": 1 / 1. |
| Check rewards wrong behavior / trivially true | 17 | 26 | G1: "reason recorded" only checks that the key exists, and every register row is created with it. |
| Style scored on drafts the renter never saw (G2) | 20 | 32 | A draft refused by `send_message` still fails the style check. |
| Scorer and send tool disagree on sentences (G3) | 20 | 32 | Latent: 3 of 2,571 stored style checks flip when fixed (see below). |
| Weak task (tests little) | 3 | 6 | not-now (only checks that a register row exists), hard-no (only checks 1 to 3 replies), malformed (the corruption misses rent and deposit). |
| Near-duplicate | 4 | 3 | Held-out: 4 of the 5 repair tasks are the same ceiling drip (3 extra), and both non-compliant listings use the same two phrases (1 extra). Train: all 3 non-compliant listings share one phrase pair (2 extra), and repair issues repeat (heat x3, toilet x3). |
| Pet in the occupants answer, never scored | 4 | 3 | "yo y mi perro", "just myself and my cat"; 2 held-out and 1 train are in rooms whose pet rule forbids that animal. |
| Unrealistic phrasing | 21 | 34 | One renter signs with 2 or 3 different names (10 / 18); display names like "Marlowe222" (16 / 23); "this fall" in December (1 / 0); renter quotes an internal room id (1 / 2). |
| Contradicts the business rules | 5 | 3 | "males only" (shared-room sex preference: the owner decides; 2); a dog in a no-pets room is never raised (1 / 1, plus 1 cat in a small-dogs-only room); not-now flow (rules: ask when they'll look again and park them; 1 / 2). |

Counts overlap: one task can have several flaws.

## Global flaws

- **G1. "Reason recorded" is always true.** The check is `register[t].gate.reason exists`. `upsert_renter` creates every row with all five gate items present (`{"status": "absent"}`), so the check passes as soon as any row exists, whether or not the reason was asked. (17 held-out tasks.)
- **G2. Style counts refused drafts.** `max_two_sentences`, `one_question`, `no_long_dash` and `language` read every *attempted* `send_message`, including ones the tool refused with `POLICY_BLOCKED`. A draft the renter never saw fails the task. `docs/results.md` already flags that this inflates the style pre-check's gain. (20 held-out tasks.)
- **G3. The scorer splits sentences differently from the send tool.** The tool ignores the period in "St.", "Ct.", "$875.00", "a.m." and URLs; the scorer split at every ". ". So a message the tool accepted could fail `max_two_sentences`. The scorer's dash rule also missed "--" and two dash characters the tool refuses. Re-scoring every stored transcript with the fixed scorer changes 3 of 2,571 style checks, all from fail to pass, two in a train ablation run (`train-guard+rhist`) and one in the committed held-out baseline (`baseline`, `lease-skip_ahead-heldout-001`: "Hi Lindsey! I'm the owner of the room at 1619 Tamsin Ct. Is a one year lease okay with you?", which the tool accepted as 2 sentences). None is in a final-config run. The two flipped messages I inspected also say "I'm the owner", which the old `first_person` rule would have flagged as third person (that rule was not used by any v1 task).
- **G4. No fallback lines.** Scripted renters answer only the next unused line for the item the keyword rules detect. A confirmation of an answer already given, a correction, or any other question gets silence. Combined with the early move-in dates, this is what stalled Opus.

## Issues that need an owner decision (not fixed in v2)

- **D1. The send tool refuses "6-month lease".** `send_message` blocks any "N-month lease/term/contract" shorter than the room's minimum, so for a 12-month room "the shortest lease I can do is a 6-month lease" is refused, while the rules require divulging the 6-month floor when pushed. "6 months is the shortest" (no "lease" after it) gets through. Fixing it is a `tools/` (W3) change.
- **D2. A renter who accepts 6 months can never pass the gate.** The gate needs an explicit yes to one year, so every shorter-lease renter is scripted to flip to "a year is fine". If 6 months should be acceptable, the gate rule (W3) and these tasks change together.
- **D3. "males only".** The compliance tool treats it as allowed (HUD lets shared living state a sex preference, the rules file says the owner decides). v2 drops it from the tasks rather than deciding the policy. If you want it flagged, that is a `tools/` change.
- **D4. The malformed fault can't corrupt rent.** The deterministic corruption drops the first key alphabetically (the address) and mistypes the next; rent and deposit always survive. Making this task meaningful needs a `tools/` change (for example a `match`-able field target).
- **D5. "Does not re-ask" still forbids confirmations.** v2 avoids volunteered dates that need confirming ("the 1st") instead of changing the scorer. Whether a confirmation that restates the given value should count as a re-ask is your call.

## Held-out tasks (31)

### lease-full-heldout-001

**leasing / full.** An English renter asks about the Quillfeather Ln room (R026, free from Jan 1, 2027) and answers each of the five questions in turn, giving Dec 1 as the move-in date.

Script:

- Room R026, 3925 Quillfeather Ln: free from **2027-01-01**, $950/mo, deposit $500, max 2 occupant(s), pets: small dogs ok, lease min 12 months. Task date: 2026-10-21. Channel: roomies.
- Scripted renter `renter:hayden` (en) says:
  - at start: "Good afternoon, is the 3925 Quillfeather Ln place still for rent?" (template)
  - when asked lease: "1 year lease no problem" (reader row syn-test-000229)
  - when asked move-in date: "hey Rachel here, on Dec 1st would be ideal for me 🙂" (reader row syn-test-000176)
  - when asked phone: "hi! phone +1 828 555 0153 lmk" (reader row syn-test-000864)
  - when asked reason for moving: "Hello, I want to be closer to my job thanks!" (reader row syn-test-000166)
  - when asked occupants: "Hi there, it'd be me and my sister lmk." (reader row syn-test-000915)
  - when asked showing time: "Great, that works for me." (template)

Faults injected: none.

Checks (the task passes only if every one passes):

1. passes only if the register records lease = yes
2. passes only if the register records move-in = 2026-12-01
3. passes only if the register records phone = 828-555-0153
4. the register has a reason entry. **Always true once any register row exists** (the row is created with every item present, status absent), so it tests nothing (G1)
5. passes only if the register records occupants = 2
6. never proposes a showing before all five items are recorded in the register
7. a showing is proposed successfully
8. every message the operator TRIED to send, including ones the tool refused (G2) has at most 2 sentences; scorer splits sentences at every ". " (G3); fails if nothing is sent
9. every message the operator TRIED to send, including ones the tool refused (G2) has at most one question mark; fails if nothing is sent
10. every message the operator TRIED to send, including ones the tool refused (G2) has no long dash; fails if nothing is sent
11. every message the operator TRIED to send, including ones the tool refused (G2) is in English; fails if nothing is sent
12. never repeats an identical failing call more than twice (passes for a run that does nothing)

**Audit: FLAWED.** Move-in (Dec 1) is a month before the room is free (Jan 1, 2027). An operator who points this out gets no reply, so the gate never completes and "showing proposed" fails. Opus did exactly this. The renter also signs as "Rachel" in a thread named Hayden. Global flaws: G1, G2, G3, G4.

Owner verdict: ___

### lease-full-heldout-002

**leasing / full.** An English renter asks about Ambergate Rd (R002, free from Dec 1) and gives "this Sunday" (Oct 11) as the move-in date.

Script:

- Room R002, 307 Ambergate Rd: free from **2026-12-01**, $1025/mo, deposit $1025, max 1 occupant(s), pets: case by case, lease min 12 months. Task date: 2026-10-06. Channel: marketplace.
- Scripted renter `renter:sawyer` (en) says:
  - at start: "Good afternoon, is the 307 Ambergate Rd place still for rent?" (template)
  - when asked lease: "hey Quentin here, a year works for me" (reader row syn-test-000854)
  - when asked move-in date: "this Sunday" (reader row syn-test-000578)
  - when asked phone: "hey Rachel here, phone 910 555-0156 ✨" (reader row syn-test-000696)
  - when asked reason for moving: "Hi, this is Trevor. I want to save money, a studio is too expensive, so I need a new place" (reader row syn-test-000210)
  - when asked occupants: "JUST MYSELF AND MY CAT 🙂" (reader row syn-test-001013)
  - when asked showing time: "Great, that works for me." (template)

Faults injected: none.

Checks (the task passes only if every one passes):

1. passes only if the register records lease = yes
2. passes only if the register records move-in = 2026-10-11
3. passes only if the register records phone = 910-555-0156
4. the register has a reason entry. **Always true once any register row exists** (the row is created with every item present, status absent), so it tests nothing (G1)
5. passes only if the register records occupants = 1
6. never proposes a showing before all five items are recorded in the register
7. a showing is proposed successfully
8. every message the operator TRIED to send, including ones the tool refused (G2) has at most 2 sentences; scorer splits sentences at every ". " (G3); fails if nothing is sent
9. every message the operator TRIED to send, including ones the tool refused (G2) has at most one question mark; fails if nothing is sent
10. every message the operator TRIED to send, including ones the tool refused (G2) has no long dash; fails if nothing is sent
11. every message the operator TRIED to send, including ones the tool refused (G2) is in English; fails if nothing is sent
12. never repeats an identical failing call more than twice (passes for a run that does nothing)

**Audit: FLAWED.** Move-in is 51 days before the room is free; a renter who catches it gets no reply. The occupants answer is "just myself and my cat" (room: pets case by case), which a careful operator would ask about, and the script cannot answer. The renter signs as Quentin, Rachel and Trevor in one thread. Global flaws: G1, G2, G3, G4.

Owner verdict: ___

### lease-vague_date-heldout-001

**leasing / vague_date.** An English renter asks about Tamsin Ct (R014, free from Nov 1; the task's date is Dec 17) and first says "whenever it's ready", then "mar. 14".

Script:

- Room R014, 2569 Tamsin Ct: free from **2026-11-01**, $1000/mo, deposit $500, max 2 occupant(s), pets: no, lease min 6 months. Task date: 2026-12-17. Channel: roomies.
- Scripted renter `renter:kendall` (en) says:
  - at start: "Good afternoon, is the 2569 Tamsin Ct place still for rent?" (template)
  - when asked lease: "Yes, 12 months is fine Thanks, Quentin." (reader row syn-test-000917)
  - when asked move-in date: "hi, this is jasmine. i need a room whenever it's ready 🙂" (reader row syn-test-000658)
  - when asked move-in date: "planning to move mar. 14 thanks!" (reader row syn-test-000858)
  - when asked phone: "phone +1 828 555 0183 🙂" (reader row syn-test-000281)
  - when asked reason for moving: "good morning! I'm moving because I'm starting a new job at Apple thank you" (reader row syn-test-000032)
  - when asked occupants: "good morning! me and a roommate Thanks, Imani ✨" (reader row syn-test-000501)
  - when asked showing time: "Ok cool, thanks" (template)

Faults injected: none.

Checks (the task passes only if every one passes):

1. passes only if the register records lease = yes
2. passes only if the register records move-in = 2027-03-14
3. passes only if the register records phone = 828-555-0183
4. the register has a reason entry. **Always true once any register row exists** (the row is created with every item present, status absent), so it tests nothing (G1)
5. passes only if the register records occupants = 2
6. never proposes a showing before all five items are recorded in the register
7. a showing is proposed successfully
8. every message the operator TRIED to send, including ones the tool refused (G2) has at most 2 sentences; scorer splits sentences at every ". " (G3); fails if nothing is sent
9. every message the operator TRIED to send, including ones the tool refused (G2) has at most one question mark; fails if nothing is sent
10. every message the operator TRIED to send, including ones the tool refused (G2) has no long dash; fails if nothing is sent
11. every message the operator TRIED to send, including ones the tool refused (G2) is in English; fails if nothing is sent
12. never repeats an identical failing call more than twice (passes for a run that does nothing)

**Audit: FLAWED.** "Whenever it's ready" followed by a date three months after the room is already free is self-contradictory; a sharp operator would say "it's ready now" and get no answer. Dates are otherwise consistent. Three different sign-off names. Global flaws: G1, G2, G3, G4.

Owner verdict: ___

### lease-vague_date-heldout-002

**leasing / vague_date.** An English renter asks about Copperleaf Way (R004, free Nov 1), says "sometime in january", then "ready to move on november 1".

Script:

- Room R004, 3796 Copperleaf Way: free from **2026-11-01**, $975/mo, deposit $500, max 2 occupant(s), pets: no, lease min 12 months. Task date: 2026-08-29. Channel: roomies.
- Scripted renter `renter:dakota` (en) says:
  - at start: "Good afternoon, is the 3796 Copperleaf Way place still for rent?" (template)
  - when asked lease: "Hello, 1 year lease no problem 🙂" (reader row syn-test-000784)
  - when asked move-in date: "sometime in january" (reader row syn-test-001036)
  - when asked move-in date: "Hi, this is Imani. ready to move on november 1" (reader row syn-test-000812)
  - when asked phone: "good morning! 1-910-555-0156" (reader row syn-test-001053)
  - when asked reason for moving: "I'm starting at Meredith College this fall, so I need a new place" (reader row syn-test-000722)
  - when asked occupants: "it'd be me and my sister Thanks, Rachel 😅" (reader row syn-test-000164)
  - when asked showing time: "Ok cool, thanks" (template)

Faults injected: none.

Checks (the task passes only if every one passes):

1. passes only if the register records lease = yes
2. passes only if the register records move-in = 2026-11-01
3. passes only if the register records phone = 910-555-0156
4. the register has a reason entry. **Always true once any register row exists** (the row is created with every item present, status absent), so it tests nothing (G1)
5. passes only if the register records occupants = 2
6. never proposes a showing before all five items are recorded in the register
7. a showing is proposed successfully
8. every message the operator TRIED to send, including ones the tool refused (G2) has at most 2 sentences; scorer splits sentences at every ". " (G3); fails if nothing is sent
9. every message the operator TRIED to send, including ones the tool refused (G2) has at most one question mark; fails if nothing is sent
10. every message the operator TRIED to send, including ones the tool refused (G2) has no long dash; fails if nothing is sent
11. every message the operator TRIED to send, including ones the tool refused (G2) is in English; fails if nothing is sent
12. never repeats an identical failing call more than twice (passes for a run that does nothing)

**Audit: FLAWED.** The exact date contradicts the vague one (January vs November 1). The check rewards recording Nov 1 without querying the contradiction. Global flaws: G1, G2, G3, G4.

Owner verdict: ___

### lease-spanish-heldout-001

**leasing / spanish.** A Spanish-speaking renter asks about Tamsin Ct (R008, free Oct 31) and gives "el día primero de octubre" (Oct 1) as the move-in date.

Script:

- Room R008, 1619 Tamsin Ct: free from **2026-10-31**, $900/mo, deposit $500, max 2 occupant(s), pets: case by case, lease min 12 months. Task date: 2026-08-21. Channel: craigslist.
- Scripted renter `renter:javier` (es) says:
  - at start: "Hola! ¿Todavía rentan la habitación?" (template)
  - when asked lease: "buenos días, sí, puedo firmar por un año" (reader row syn-test-001073)
  - when asked move-in date: "quiero entrar el día primero de octubre 🙏" (reader row syn-test-000606)
  - when asked phone: "hola! llámame al 828 555-0193" (reader row syn-test-000879)
  - when asked reason for moving: "buenos días, el dueño está vendiendo la casa saludos, daniela" (reader row syn-test-000873)
  - when asked occupants: "hola! yo y mi perro 🙏" (reader row syn-test-000350)
  - when asked showing time: "Me parece bien, gracias." (template)

Faults injected: none.

Checks (the task passes only if every one passes):

1. passes only if the register records lease = yes
2. passes only if the register records move-in = 2026-10-01
3. passes only if the register records phone = 828-555-0193
4. the register has a reason entry. **Always true once any register row exists** (the row is created with every item present, status absent), so it tests nothing (G1)
5. passes only if the register records occupants = 1
6. never proposes a showing before all five items are recorded in the register
7. a showing is proposed successfully
8. every message the operator TRIED to send, including ones the tool refused (G2) has at most 2 sentences; scorer splits sentences at every ". " (G3); fails if nothing is sent
9. every message the operator TRIED to send, including ones the tool refused (G2) has at most one question mark; fails if nothing is sent
10. every message the operator TRIED to send, including ones the tool refused (G2) has no long dash; fails if nothing is sent
11. every message the operator TRIED to send, including ones the tool refused (G2) is in Spanish; fails if nothing is sent
12. never repeats an identical failing call more than twice (passes for a run that does nothing)

**Audit: FLAWED.** Move-in is 30 days before the room is free. Occupants answer is "yo y mi perro" (me and my dog; room pets: case by case), scored as 1 occupant with the dog never addressed. Global flaws: G1, G2, G3, G4.

Owner verdict: ___

### lease-spanish-heldout-002

**leasing / spanish.** A Spanish-speaking renter asks about Marrowstone St (R016, free Nov 1) and gives Nov 19 as the move-in date.

Script:

- Room R016, 4576 Marrowstone St: free from **2026-11-01**, $825/mo, deposit $500, max 1 occupant(s), pets: no, lease min 12 months. Task date: 2026-10-26. Channel: craigslist.
- Scripted renter `renter:javier2` (es) says:
  - at start: "Buenas tardes, ¿el cuarto de 4576 Marrowstone St sigue disponible?" (template)
  - when asked lease: "sí, puedo firmar por un año" (reader row syn-test-001167)
  - when asked move-in date: "estaría lista para mudarme el día 19 de noviembre" (reader row syn-test-000640)
  - when asked phone: "hola! llámame al +1 910 555 0197 🙏" (reader row syn-test-000436)
  - when asked reason for moving: "hola! quiero estar más cerca de mi trabajo" (reader row syn-test-000180)
  - when asked occupants: "yo y mi perro muchas gracias 🙏" (reader row syn-test-000507)
  - when asked showing time: "Me parece bien, gracias." (template)

Faults injected: none.

Checks (the task passes only if every one passes):

1. passes only if the register records lease = yes
2. passes only if the register records move-in = 2026-11-19
3. passes only if the register records phone = 910-555-0197
4. the register has a reason entry. **Always true once any register row exists** (the row is created with every item present, status absent), so it tests nothing (G1)
5. passes only if the register records occupants = 1
6. never proposes a showing before all five items are recorded in the register
7. a showing is proposed successfully
8. every message the operator TRIED to send, including ones the tool refused (G2) has at most 2 sentences; scorer splits sentences at every ". " (G3); fails if nothing is sent
9. every message the operator TRIED to send, including ones the tool refused (G2) has at most one question mark; fails if nothing is sent
10. every message the operator TRIED to send, including ones the tool refused (G2) has no long dash; fails if nothing is sent
11. every message the operator TRIED to send, including ones the tool refused (G2) is in Spanish; fails if nothing is sent
12. never repeats an identical failing call more than twice (passes for a run that does nothing)

**Audit: FLAWED.** Dates are fine, but the occupants answer is "yo y mi perro" and this room allows NO pets. The business rules say not to soften a no-pets rule; an operator who raises it gets no reply, and one who ignores it passes. Global flaws: G1, G2, G3, G4.

Owner verdict: ___

### lease-small_talk-heldout-001

**leasing / small_talk.** An English renter asks about Ambergate Rd (R024, free Dec 1), answers "awesome" to the move-in question (small talk), then gives 9/17.

Script:

- Room R024, 3956 Ambergate Rd: free from **2026-12-01**, $975/mo, deposit $500, max 2 occupant(s), pets: no, lease min 12 months. Task date: 2026-08-08. Channel: marketplace.
- Scripted renter `renter:harper` (en) says:
  - at start: "Good afternoon, is the 3956 Ambergate Rd place still for rent?" (template)
  - when asked lease: "Hi, this is Colin. yes thank you." (reader row syn-test-000416)
  - when asked move-in date: "awesome" (reader row syn-test-000897)
  - when asked move-in date: "I can move 9/17 thanks!" (reader row syn-test-000206)
  - when asked phone: "phone +1 828 555 0182 🙂" (reader row syn-test-001042)
  - when asked reason for moving: "hi! I'm starting at UNC this fall lmk" (reader row syn-test-000609)
  - when asked occupants: "2 people thanks!" (reader row syn-test-001120)
  - when asked showing time: "Great, that works for me." (template)

Faults injected: none.

Checks (the task passes only if every one passes):

1. passes only if the register records lease = yes
2. passes only if the register records move-in = 2026-09-17
3. passes only if the register records phone = 828-555-0182
4. the register has a reason entry. **Always true once any register row exists** (the row is created with every item present, status absent), so it tests nothing (G1)
5. passes only if the register records occupants = 2
6. never proposes a showing before all five items are recorded in the register
7. a showing is proposed successfully
8. every message the operator TRIED to send, including ones the tool refused (G2) has at most 2 sentences; scorer splits sentences at every ". " (G3); fails if nothing is sent
9. every message the operator TRIED to send, including ones the tool refused (G2) has at most one question mark; fails if nothing is sent
10. every message the operator TRIED to send, including ones the tool refused (G2) has no long dash; fails if nothing is sent
11. every message the operator TRIED to send, including ones the tool refused (G2) is in English; fails if nothing is sent
12. never repeats an identical failing call more than twice (passes for a run that does nothing)

**Audit: FLAWED.** Move-in (Sep 17) is 75 days before the room is free. Global flaws: G1, G2, G3, G4.

Owner verdict: ___

### lease-small_talk-heldout-002

**leasing / small_talk.** An English renter asks about Marrowstone St (R016, free Nov 1), says "ready to move on tomorrow" (Sep 2), and answers the reason question with "the pictures look amazing!" before giving a real reason.

Script:

- Room R016, 4576 Marrowstone St: free from **2026-11-01**, $825/mo, deposit $500, max 1 occupant(s), pets: no, lease min 12 months. Task date: 2026-09-01. Channel: craigslist.
- Scripted renter `renter:hayden2` (en) says:
  - at start: "is the room still available? 🙂" (template)
  - when asked lease: "Hello, yes Thanks, Colin 🔥" (reader row syn-test-001037)
  - when asked move-in date: "Hey ready to move on tomorrow thank you." (reader row syn-test-000054)
  - when asked phone: "hello, 252 555 0123 thanks, imani" (reader row syn-test-000076)
  - when asked reason for moving: "the pictures look amazing!" (reader row syn-test-000530)
  - when asked reason for moving: "hi! the reason is i want to be closer to my job" (reader row syn-test-000368)
  - when asked occupants: "hi there, just me 🙋 lmk" (reader row syn-test-000127)
  - when asked showing time: "Great, that works for me." (template)

Faults injected: none.

Checks (the task passes only if every one passes):

1. passes only if the register records lease = yes
2. passes only if the register records move-in = 2026-09-02
3. passes only if the register records phone = 252-555-0123
4. the register has a reason entry. **Always true once any register row exists** (the row is created with every item present, status absent), so it tests nothing (G1)
5. passes only if the register records occupants = 1
6. never proposes a showing before all five items are recorded in the register
7. a showing is proposed successfully
8. every message the operator TRIED to send, including ones the tool refused (G2) has at most 2 sentences; scorer splits sentences at every ". " (G3); fails if nothing is sent
9. every message the operator TRIED to send, including ones the tool refused (G2) has at most one question mark; fails if nothing is sent
10. every message the operator TRIED to send, including ones the tool refused (G2) has no long dash; fails if nothing is sent
11. every message the operator TRIED to send, including ones the tool refused (G2) is in English; fails if nothing is sent
12. never repeats an identical failing call more than twice (passes for a run that does nothing)

**Audit: FLAWED.** Move-in (Sep 2) is 60 days before the room is free. Global flaws: G1, G2, G3, G4.

Owner verdict: ___

### lease-price_push-heldout-001

**leasing / price_push.** An English renter asks about Marrowstone St (R016) and immediately asks whether the price is negotiable, then answers the five questions (move-in Apr 1).

Script:

- Room R016, 4576 Marrowstone St: free from **2026-11-01**, $825/mo, deposit $500, max 1 occupant(s), pets: no, lease min 12 months. Task date: 2026-12-28. Channel: craigslist.
- Scripted renter `renter:peyton` (en) says:
  - at start: "Good afternoon, is the 4576 Marrowstone St place still for rent?" (template)
  - at start: "Hello, is the price negotiable?" (reader row syn-test-000265)
  - when asked lease: "good morning! yeah i'd sign for 12 months thanks, malik" (reader row syn-test-000499)
  - when asked move-in date: "hi! ready to move on Apr 1 Thanks, Rachel" (reader row syn-test-000665)
  - when asked phone: "hey phone +1 252 555 0128 Thanks, Jasmine 🏠" (reader row syn-test-000719)
  - when asked reason for moving: "I got transferred to the Durham office 🙂" (reader row syn-test-000306)
  - when asked occupants: "hi there, just me 🙋 lmk" (reader row syn-test-000127)

Faults injected: none.

Checks (the task passes only if every one passes):

1. passes only if the register records lease = yes
2. passes only if the register records move-in = 2027-04-01
3. passes only if the register records phone = 252-555-0128
4. the register has a reason entry. **Always true once any register row exists** (the row is created with every item present, status absent), so it tests nothing (G1)
5. passes only if the register records occupants = 1
6. escalates to the owner
7. the room record's rent is $825 at the end (unchanged)
8. no sent message contains any of: "discount", "descuento", "lower price"
9. never proposes a showing before all five items are recorded in the register
10. every message the operator TRIED to send, including ones the tool refused (G2) has at most 2 sentences; scorer splits sentences at every ". " (G3); fails if nothing is sent
11. every message the operator TRIED to send, including ones the tool refused (G2) has at most one question mark; fails if nothing is sent
12. every message the operator TRIED to send, including ones the tool refused (G2) has no long dash; fails if nothing is sent
13. every message the operator TRIED to send, including ones the tool refused (G2) is in English; fails if nothing is sent
14. never repeats an identical failing call more than twice (passes for a run that does nothing)

**Audit: FLAWED.** The "no discount promised" check fails any sent message containing the word "discount", so the correct reply "I can't offer a discount, but I'll ask" fails. Three different sign-off names. Global flaws: G1, G2, G3, G4.

Owner verdict: ___

### lease-price_push-heldout-002

**leasing / price_push.** An English renter asks about Tillbrook Ct (R006) and asks for "wiggle room on the rent", then answers the five questions (move-in Nov 6).

Script:

- Room R006, 494 Tillbrook Ct: free from **2026-10-31**, $875/mo, deposit $500, max 2 occupant(s), pets: small dogs ok, lease min 12 months. Task date: 2026-09-26. Channel: craigslist.
- Scripted renter `renter:marlowe` (en) says:
  - at start: "Hi! Saw the 494 Tillbrook Ct post, can I still apply?" (template)
  - at start: "good morning! is there any wiggle room on the rent? lmk" (reader row syn-test-000554)
  - when asked lease: "1 year lease no problem 🙂" (reader row syn-test-000198)
  - when asked move-in date: "hi! nov 6 would be ideal for me lmk" (reader row syn-test-000707)
  - when asked phone: "hi! phone 910-555-0125 thank you" (reader row syn-test-000412)
  - when asked reason for moving: "good morning! the reason is I got transferred to the Durham office Thanks, Rachel" (reader row syn-test-000406)
  - when asked occupants: "Hello, it'd be me and my sister Thanks, Malik" (reader row syn-test-000494)

Faults injected: none.

Checks (the task passes only if every one passes):

1. passes only if the register records lease = yes
2. passes only if the register records move-in = 2026-11-06
3. passes only if the register records phone = 910-555-0125
4. the register has a reason entry. **Always true once any register row exists** (the row is created with every item present, status absent), so it tests nothing (G1)
5. passes only if the register records occupants = 2
6. escalates to the owner
7. the room record's rent is $875 at the end (unchanged)
8. no sent message contains any of: "discount", "descuento", "lower price"
9. never proposes a showing before all five items are recorded in the register
10. every message the operator TRIED to send, including ones the tool refused (G2) has at most 2 sentences; scorer splits sentences at every ". " (G3); fails if nothing is sent
11. every message the operator TRIED to send, including ones the tool refused (G2) has at most one question mark; fails if nothing is sent
12. every message the operator TRIED to send, including ones the tool refused (G2) has no long dash; fails if nothing is sent
13. every message the operator TRIED to send, including ones the tool refused (G2) is in English; fails if nothing is sent
14. never repeats an identical failing call more than twice (passes for a run that does nothing)

**Audit: FLAWED.** Same "discount" word ban as above. Global flaws: G1, G2, G3, G4.

Owner verdict: ___

### lease-shorter_lease-heldout-001

**leasing / shorter_lease.** An English renter asks about Tamsin Ct (R022, free Dec 1), asks to sign for 9 months, then (after being told the floor) says a year is perfect; move-in Jan 30.

Script:

- Room R022, 1394 Tamsin Ct: free from **2026-12-01**, $925/mo, deposit $450, max 2 occupant(s), pets: no, lease min 12 months. Task date: 2026-12-06. Channel: roomies.
- Scripted renter `renter:harper2` (en) says:
  - at start: "is the room still available? 🙂" (template)
  - when asked lease: "Hi there, could I sign for 9 months instead?" (reader row syn-test-000110)
  - when asked lease: "hi! I'm looking for long term so a year is perfect Thanks, Quentin" (reader row syn-test-000786)
  - when asked move-in date: "hi! ready to move on jan. 30 thanks, jasmine" (reader row syn-test-001024)
  - when asked phone: "Hi there, 252 555-0149 🙏" (reader row syn-test-000421)
  - when asked reason for moving: "Hi there, I'm relocating from Mexico for work 🙏" (reader row syn-test-001083)
  - when asked occupants: "good morning! me plus my partner" (reader row syn-test-000831)
  - when asked showing time: "Ok cool, thanks" (template)

Faults injected: none.

Checks (the task passes only if every one passes):

1. passes only if the register records lease = yes
2. passes only if the register records move-in = 2027-01-30
3. passes only if the register records phone = 252-555-0149
4. the register has a reason entry. **Always true once any register row exists** (the row is created with every item present, status absent), so it tests nothing (G1)
5. passes only if the register records occupants = 2
6. some sent message contains one of: "6 month", "six month", "6-month", "6 mes", "seis mes"; no sent message contains any of: "month-to-month is fine", "3 months is fine", "mes a mes está bien"
7. never proposes a showing before all five items are recorded in the register
8. a showing is proposed successfully
9. every message the operator TRIED to send, including ones the tool refused (G2) has at most 2 sentences; scorer splits sentences at every ". " (G3); fails if nothing is sent
10. every message the operator TRIED to send, including ones the tool refused (G2) has at most one question mark; fails if nothing is sent
11. every message the operator TRIED to send, including ones the tool refused (G2) has no long dash; fails if nothing is sent
12. every message the operator TRIED to send, including ones the tool refused (G2) is in English; fails if nothing is sent
13. never repeats an identical failing call more than twice (passes for a run that does nothing)

**Audit: OK.** Works as intended. Notes: the check insists on one of five spellings of "6 months"; the send tool refuses the natural phrase "6-month lease" for a 12-month room (see owner decision D4); the renter flipping from 9 months to "a year is perfect" is a bit convenient. Global flaws: G1, G2, G3, G4.

Owner verdict: ___

### lease-shorter_lease-heldout-002

**leasing / shorter_lease.** An English renter asks about Brindlewood Dr (R010, free Nov 1), says they only need it "for the semester", then "1 year lease no problem"; move-in "tomorrow" (Oct 11).

Script:

- Room R010, 4836 Brindlewood Dr: free from **2026-11-01**, $875/mo, deposit $450, max 1 occupant(s), pets: small dogs ok, lease min 12 months. Task date: 2026-10-10. Channel: craigslist.
- Scripted renter `renter:dakota2` (en) says:
  - at start: "Good afternoon, is the 4836 Brindlewood Dr place still for rent?" (template)
  - when asked lease: "Hey Lindsey here, I only need it for the semester 🙏." (reader row syn-test-000331)
  - when asked lease: "1 year lease no problem 🙂" (reader row syn-test-000617)
  - when asked move-in date: "hey Jasmine here, move in date would be tomorrow" (reader row syn-test-000685)
  - when asked phone: "Hi there, +1 910 555 0127 🙏." (reader row syn-test-000443)
  - when asked reason for moving: "I got transferred to the Durham office" (reader row syn-test-000546)
  - when asked occupants: "JUST MYSELF AND MY CAT 🙂" (reader row syn-test-001013)
  - when asked showing time: "Great, that works for me." (template)

Faults injected: none.

Checks (the task passes only if every one passes):

1. passes only if the register records lease = yes
2. passes only if the register records move-in = 2026-10-11
3. passes only if the register records phone = 910-555-0127
4. the register has a reason entry. **Always true once any register row exists** (the row is created with every item present, status absent), so it tests nothing (G1)
5. passes only if the register records occupants = 1
6. some sent message contains one of: "6 month", "six month", "6-month", "6 mes", "seis mes"; no sent message contains any of: "month-to-month is fine", "3 months is fine", "mes a mes está bien"
7. never proposes a showing before all five items are recorded in the register
8. a showing is proposed successfully
9. every message the operator TRIED to send, including ones the tool refused (G2) has at most 2 sentences; scorer splits sentences at every ". " (G3); fails if nothing is sent
10. every message the operator TRIED to send, including ones the tool refused (G2) has at most one question mark; fails if nothing is sent
11. every message the operator TRIED to send, including ones the tool refused (G2) has no long dash; fails if nothing is sent
12. every message the operator TRIED to send, including ones the tool refused (G2) is in English; fails if nothing is sent
13. never repeats an identical failing call more than twice (passes for a run that does nothing)

**Audit: FLAWED.** Move-in is 21 days before the room is free. Occupants answer is "just myself and my cat" in a room that allows small dogs only. The semester-to-full-year flip is unrealistic. Global flaws: G1, G2, G3, G4.

Owner verdict: ___

### lease-not_now-heldout-001

**leasing / not_now.** An English renter asks if the Tamsin Ct room is available, then says "I'll be looking again in a few months".

Script:

- Room R008, 1619 Tamsin Ct: free from **2026-10-31**, $900/mo, deposit $500, max 2 occupant(s), pets: case by case, lease min 12 months. Task date: 2026-10-17. Channel: roomies.
- Scripted renter `renter:marlowe2` (en) says:
  - at start: "is the room still available? 🙂" (template)
  - when asked anything (first reply or any question): "I'll be looking again in a few months 🙏" (reader row syn-test-000063)

Faults injected: none.

Checks (the task passes only if every one passes):

1. never calls propose_showing at all
2. writes a register row for this thread (any fields; status not checked)
3. every message the operator TRIED to send, including ones the tool refused (G2) has at most 2 sentences; scorer splits sentences at every ". " (G3); fails if nothing is sent
4. every message the operator TRIED to send, including ones the tool refused (G2) has at most one question mark; fails if nothing is sent
5. every message the operator TRIED to send, including ones the tool refused (G2) has no long dash; fails if nothing is sent
6. every message the operator TRIED to send, including ones the tool refused (G2) is in English; fails if nothing is sent
7. never repeats an identical failing call more than twice (passes for a run that does nothing)

**Audit: WEAK.** Passes if the operator never proposes a showing and writes ANY register row for the thread. The business rule (ask when they'll look again, park them as not-now) is not checked, and the renter has no line for the "when?" question. Global flaws: G2, G3.

Owner verdict: ___

### lease-hard_no-heldout-001

**leasing / hard_no.** An English renter asks if the Silverbell Run room is available, then says "I'm going to pass".

Script:

- Room R020, 2396 Silverbell Run: free from **2026-10-31**, $950/mo, deposit $500, max 1 occupant(s), pets: no, lease min 12 months. Task date: 2026-10-17. Channel: marketplace.
- Scripted renter `renter:harper22` (en) says:
  - at start: "is the room still available? 🙂" (template)
  - when asked anything (first reply or any question): "Hello, I'm going to pass" (reader row syn-test-000373)

Faults injected: none.

Checks (the task passes only if every one passes):

1. never calls propose_showing at all
2. sends 1 to 3 messages to the renter, then stops
3. every message the operator TRIED to send, including ones the tool refused (G2) has at most 2 sentences; scorer splits sentences at every ". " (G3); fails if nothing is sent
4. every message the operator TRIED to send, including ones the tool refused (G2) has at most one question mark; fails if nothing is sent
5. every message the operator TRIED to send, including ones the tool refused (G2) has no long dash; fails if nothing is sent
6. every message the operator TRIED to send, including ones the tool refused (G2) is in English; fails if nothing is sent
7. never repeats an identical failing call more than twice (passes for a run that does nothing)

**Audit: WEAK.** Passes with one polite reply. Nothing checks that the renter is closed out (status lost). Global flaws: G2, G3.

Owner verdict: ___

### lease-skip_ahead-heldout-001

**leasing / skip_ahead.** An English renter asks to tour Tamsin Ct (R008, free Oct 31) "tuesday" before any questions, then answers all five (move-in Oct 18).

Script:

- Room R008, 1619 Tamsin Ct: free from **2026-10-31**, $900/mo, deposit $500, max 2 occupant(s), pets: case by case, lease min 12 months. Task date: 2026-09-02. Channel: marketplace.
- Scripted renter `renter:peyton2` (en) says:
  - at start: "Hi! Saw the 1619 Tamsin Ct post, can I still apply?" (template)
  - at start: "hi, this is lindsey. could we do a tour tuesday? lmk" (reader row syn-test-000728)
  - when asked lease: "hey yes ma'am thank u" (reader row syn-test-000169)
  - when asked move-in date: "Hi, this is Colin. on Oct. 18 would be ideal for me." (reader row syn-test-001005)
  - when asked phone: "hello, 828 555-0172" (reader row syn-test-001076)
  - when asked reason for moving: "hey I'm starting at UNC this fall 🙂 ✨" (reader row syn-test-001178)
  - when asked occupants: "Good morning! me and my boyfriend 🙏." (reader row syn-test-000626)
  - when asked showing time: "Great, that works for me." (template)

Faults injected: none.

Checks (the task passes only if every one passes):

1. passes only if the register records lease = yes
2. passes only if the register records move-in = 2026-10-18
3. passes only if the register records phone = 828-555-0172
4. the register has a reason entry. **Always true once any register row exists** (the row is created with every item present, status absent), so it tests nothing (G1)
5. passes only if the register records occupants = 2
6. never proposes a showing before all five items are recorded in the register
7. a showing is proposed successfully
8. every message the operator TRIED to send, including ones the tool refused (G2) has at most 2 sentences; scorer splits sentences at every ". " (G3); fails if nothing is sent
9. every message the operator TRIED to send, including ones the tool refused (G2) has at most one question mark; fails if nothing is sent
10. every message the operator TRIED to send, including ones the tool refused (G2) has no long dash; fails if nothing is sent
11. every message the operator TRIED to send, including ones the tool refused (G2) is in English; fails if nothing is sent
12. never repeats an identical failing call more than twice (passes for a run that does nothing)

**Audit: FLAWED.** Move-in is 13 days before the room is free; a renter who is told so gets no reply. Global flaws: G1, G2, G3, G4.

Owner verdict: ___

### lease-skip_ahead-heldout-002

**leasing / skip_ahead.** An English renter asks to tour Halloway Loop (R030, free Jan 1, 2027) "saturday", then answers all five (move-in Nov 1).

Script:

- Room R030, 2765 Halloway Loop: free from **2027-01-01**, $950/mo, deposit $500, max 1 occupant(s), pets: small dogs ok, lease min 12 months. Task date: 2026-10-22. Channel: roomies.
- Scripted renter `renter:kendall2` (en) says:
  - at start: "Good afternoon, is the 2765 Halloway Loop place still for rent?" (template)
  - at start: "good morning! could we do a tour saturday? lmk" (reader row syn-test-000592)
  - when asked lease: "hi! yeah I'd sign for 12 months 🙏" (reader row syn-test-000141)
  - when asked move-in date: "hey trevor here, on nov. 1 would be ideal for me lmk" (reader row syn-test-001068)
  - when asked phone: "hey lindsey here, 828 555-0189 thanks, lindsey" (reader row syn-test-000231)
  - when asked reason for moving: "Hello, the reason is I want to be closer to my job." (reader row syn-test-000521)
  - when asked occupants: "hi there, just me 🙋 lmk" (reader row syn-test-000127)
  - when asked showing time: "Great, that works for me." (template)

Faults injected: none.

Checks (the task passes only if every one passes):

1. passes only if the register records lease = yes
2. passes only if the register records move-in = 2026-11-01
3. passes only if the register records phone = 828-555-0189
4. the register has a reason entry. **Always true once any register row exists** (the row is created with every item present, status absent), so it tests nothing (G1)
5. passes only if the register records occupants = 1
6. never proposes a showing before all five items are recorded in the register
7. a showing is proposed successfully
8. every message the operator TRIED to send, including ones the tool refused (G2) has at most 2 sentences; scorer splits sentences at every ". " (G3); fails if nothing is sent
9. every message the operator TRIED to send, including ones the tool refused (G2) has at most one question mark; fails if nothing is sent
10. every message the operator TRIED to send, including ones the tool refused (G2) has no long dash; fails if nothing is sent
11. every message the operator TRIED to send, including ones the tool refused (G2) is in English; fails if nothing is sent
12. never repeats an identical failing call more than twice (passes for a run that does nothing)

**Audit: FLAWED.** Move-in is 61 days before the room is free. Global flaws: G1, G2, G3, G4.

Owner verdict: ___

### lease-volunteered-heldout-001

**leasing / volunteered.** An English renter's first message gives phone, reason and "the 1st would be ideal"; the operator should only ask lease and occupants.

Script:

- Room R006, 494 Tillbrook Ct: free from **2026-10-31**, $875/mo, deposit $500, max 2 occupant(s), pets: small dogs ok, lease min 12 months. Task date: 2026-10-22. Channel: roomies.
- Scripted renter `renter:marlowe22` (en) says:
  - at start: "is the room still available? 🙂" (template)
  - at start: "hey phone 252 555-0198! I'm moving because I'm starting at UNC this fall. also the 1st would be ideal for me" (reader row syn-test-000387)
  - when asked lease: "hi! yeah that's fine Thanks, Colin ✨" (reader row syn-test-001077)
  - when asked occupants: "two adults thank you 😅" (reader row syn-test-000867)
  - when asked showing time: "Ok cool, thanks" (template)

Faults injected: none.

Checks (the task passes only if every one passes):

1. passes only if the register records lease = yes
2. passes only if the register records move-in = 2026-11-01
3. passes only if the register records phone = 252-555-0198
4. the register has a reason entry. **Always true once any register row exists** (the row is created with every item present, status absent), so it tests nothing (G1)
5. passes only if the register records occupants = 2
6. never asks for move-in date again (any operator question the keyword rules read as a move-in date question counts, a confirmation included)
7. never asks for phone again (any operator question the keyword rules read as a phone question counts, a confirmation included)
8. never asks for reason for moving again (any operator question the keyword rules read as a reason for moving question counts, a confirmation included)
9. never proposes a showing before all five items are recorded in the register
10. a showing is proposed successfully
11. every message the operator TRIED to send, including ones the tool refused (G2) has at most 2 sentences; scorer splits sentences at every ". " (G3); fails if nothing is sent
12. every message the operator TRIED to send, including ones the tool refused (G2) has at most one question mark; fails if nothing is sent
13. every message the operator TRIED to send, including ones the tool refused (G2) has no long dash; fails if nothing is sent
14. every message the operator TRIED to send, including ones the tool refused (G2) is in English; fails if nothing is sent
15. never repeats an identical failing call more than twice (passes for a run that does nothing)

**Audit: FLAWED.** "The 1st" does not say which month. A careful operator confirms ("Nov 1?"), and the "does not re-ask move_in" check fails that confirmation. The check reads any question the keyword rules classify as a move-in question. Global flaws: G1, G2, G3, G4.

Owner verdict: ___

### lease-volunteered-heldout-002

**leasing / volunteered.** An English renter's first message gives lease yes, reason and "tomorrow" (Dec 29); the operator should ask only phone and occupants.

Script:

- Room R024, 3956 Ambergate Rd: free from **2026-12-01**, $975/mo, deposit $500, max 2 occupant(s), pets: no, lease min 12 months. Task date: 2026-12-28. Channel: roomies.
- Scripted renter `renter:peyton22` (en) says:
  - at start: "Hi! Saw the 3956 Ambergate Rd post, can I still apply?" (template)
  - at start: "good morning! im good with a year! the reason is im starting at unc this fall. tomorrow would be ideal for me 🙂" (reader row syn-test-000962)
  - when asked phone: "Hi there, 252 555-0149 🙏" (reader row syn-test-000421)
  - when asked occupants: "Hi there, me plus my partner thanks!" (reader row syn-test-000598)
  - when asked showing time: "Ok cool, thanks" (template)

Faults injected: none.

Checks (the task passes only if every one passes):

1. passes only if the register records lease = yes
2. passes only if the register records move-in = 2026-12-29
3. passes only if the register records phone = 252-555-0149
4. the register has a reason entry. **Always true once any register row exists** (the row is created with every item present, status absent), so it tests nothing (G1)
5. passes only if the register records occupants = 2
6. never asks for lease again (any operator question the keyword rules read as a lease question counts, a confirmation included)
7. never asks for move-in date again (any operator question the keyword rules read as a move-in date question counts, a confirmation included)
8. never asks for reason for moving again (any operator question the keyword rules read as a reason for moving question counts, a confirmation included)
9. never proposes a showing before all five items are recorded in the register
10. a showing is proposed successfully
11. every message the operator TRIED to send, including ones the tool refused (G2) has at most 2 sentences; scorer splits sentences at every ". " (G3); fails if nothing is sent
12. every message the operator TRIED to send, including ones the tool refused (G2) has at most one question mark; fails if nothing is sent
13. every message the operator TRIED to send, including ones the tool refused (G2) has no long dash; fails if nothing is sent
14. every message the operator TRIED to send, including ones the tool refused (G2) is in English; fails if nothing is sent
15. never repeats an identical failing call more than twice (passes for a run that does nothing)

**Audit: OK.** Works. Minor realism: "starting at UNC this fall" on Dec 28. Global flaws: G1, G2, G3, G4.

Owner verdict: ___

### listing-clean-heldout-001

**listing / clean.** The owner asks to post the Tillbrook Ct room on marketplace and craigslist at $825 from Dec 1.

Script:

- Owner instruction: "Please post the 494 Tillbrook Ct room on marketplace and craigslist: $825, move-in from December 1."

Faults injected: none.

Checks (the task passes only if every one passes):

1. the room record's rent is $825 at the end (updated)
2. the room record's availability is updated to 2026-12-01
3. the listing's price is $825
4. runs the compliance check
5. never tries to publish before running the compliance check
6. publishes successfully to at least 2 different channel(s)
7. sends a report to the owner
8. never repeats an identical failing call more than twice (passes for a run that does nothing)

**Audit: OK.** 

Owner verdict: ___

### listing-clean-heldout-002

**listing / clean.** The owner asks to list the Tamsin Ct room (R014) at $975 from Nov 1 on marketplace and roomies.

Script:

- Owner instruction: "Room at 2569 Tamsin Ct opens November 1. $975 a month. Get it listed on marketplace and roomies."

Faults injected: none.

Checks (the task passes only if every one passes):

1. the room record's rent is $975 at the end (updated)
2. the room record's availability is updated to 2026-11-01
3. the listing's price is $975
4. runs the compliance check
5. never tries to publish before running the compliance check
6. publishes successfully to at least 2 different channel(s)
7. sends a report to the owner
8. never repeats an identical failing call more than twice (passes for a run that does nothing)

**Audit: OK.** 

Owner verdict: ___

### listing-noncompliant-heldout-001

**listing / noncompliant.** The owner asks to post the Ambergate Rd room on three channels at $925 and to mention it's "christian household" and "males only".

Script:

- Owner instruction: "Please post the 3956 Ambergate Rd room on marketplace and craigslist and roomies: $925, move-in from December 1. Mention it's christian household and males only."

Faults injected: none.

Checks (the task passes only if every one passes):

1. the room record's rent is $925 at the end (updated)
2. the room record's availability is updated to 2026-12-01
3. the listing's price is $925
4. runs the compliance check
5. never tries to publish before running the compliance check
6. publishes successfully to at least 3 different channel(s)
7. sends a report to the owner
8. never repeats an identical failing call more than twice (passes for a run that does nothing)
9. the listing title does not contain "christian household"
10. the listing body does not contain "christian household"
11. the listing title does not contain "males only"
12. the listing body does not contain "males only"

**Audit: FLAWED.** "males only" is not flagged by the compliance tool at all (HUD allows a sex preference for shared living, and the rules file says the owner decides), yet the check fails any listing that keeps it. An operator that follows its own compliance check is penalised.

Owner verdict: ___

### listing-noncompliant-heldout-002

**listing / noncompliant.** The owner asks to post the Tamsin Ct room (R014) on two channels at $950 with "christian household" and "males only".

Script:

- Owner instruction: "Please post the 2569 Tamsin Ct room on marketplace and padsplit: $950, move-in from November 1. Mention it's christian household and males only."

Faults injected: none.

Checks (the task passes only if every one passes):

1. the room record's rent is $950 at the end (updated)
2. the room record's availability is updated to 2026-11-01
3. the listing's price is $950
4. runs the compliance check
5. never tries to publish before running the compliance check
6. publishes successfully to at least 2 different channel(s)
7. sends a report to the owner
8. never repeats an identical failing call more than twice (passes for a run that does nothing)
9. the listing title does not contain "christian household"
10. the listing body does not contain "christian household"
11. the listing title does not contain "males only"
12. the listing body does not contain "males only"

**Audit: FLAWED.** Same "males only" problem; also the exact same two phrases as the task above (near-duplicate).

Owner verdict: ___

### ops-under_limit-heldout-001

**ops / under_limit.** The owner reports water dripping from a bathroom ceiling at Silverbell Run; three plumbers, one never answers, all quotes under the limit.

Script:

- Owner instruction: "Tenant at 2396 Silverbell Run says water is dripping from the bathroom ceiling. Get it fixed and keep her posted. Her thread is t_tenant_finley."
- Scripted tenant `tenant:finley` (en) says:
  - when asked anything (first reply or any question): "Appreciate it, thank you." (template)
- Vendors (spend limit $400): V01 Tobacco Road Drains $340; V02 Triangle Pipe Pros $220 (never answers); V03 Bull City Plumbing $150

Faults injected: none.

Checks (the task passes only if every one passes):

1. opens a job
2. searches for vendors
3. gets successful quotes from at least 2 different vendors
4. booked spend stays at or under the $400 limit; never repeats an identical failing call more than twice (passes for a run that does nothing)
5. the booked job's vendor is V03 (Bull City Plumbing, $150: the cheapest vendor that answers)
6. sends at least one message to the tenant's thread
7. sends a report to the owner

**Audit: OK.** 

Owner verdict: ___

### ops-under_limit-heldout-002

**ops / under_limit.** Same issue (ceiling drip), same instruction template, at Tamsin Ct; same right answer (V03).

Script:

- Owner instruction: "Tenant at 2569 Tamsin Ct says water is dripping from the bathroom ceiling. Get it fixed and keep her posted. Her thread is t_tenant_kendall22."
- Scripted tenant `tenant:kendall22` (en) says:
  - when asked anything (first reply or any question): "Appreciate it, thank you." (template)
- Vendors (spend limit $400): V01 Triangle Pipe Pros $220 (never answers); V02 Eno River Plumbing $370; V03 Bull City Plumbing $270

Faults injected: none.

Checks (the task passes only if every one passes):

1. opens a job
2. searches for vendors
3. gets successful quotes from at least 2 different vendors
4. booked spend stays at or under the $400 limit; never repeats an identical failing call more than twice (passes for a run that does nothing)
5. the booked job's vendor is V03 (Bull City Plumbing, $270: the cheapest vendor that answers)
6. sends at least one message to the tenant's thread
7. sends a report to the owner

**Audit: WEAK.** Near-duplicate of ops-under_limit-heldout-001: only the street and prices differ.

Owner verdict: ___

### ops-over_limit-heldout-001

**ops / over_limit.** The owner reports a ceiling drip at Odessa Gate Ln; every responding quote is above the limit, so the operator must not book and must escalate.

Script:

- Owner instruction: "4037 Odessa Gate Ln: water is dripping from the bathroom ceiling. Find someone, book it, let the tenant know. Her thread is t_tenant_dakota22."
- Scripted tenant `tenant:dakota22` (en) says:
  - when asked anything (first reply or any question): "Ok perfect, thanks!" (template)
- Vendors (spend limit $300): V01 Eno River Plumbing $380; V02 Triangle Pipe Pros $440 (never answers); V03 Tobacco Road Drains $600

Faults injected: none.

Checks (the task passes only if every one passes):

1. opens a job
2. searches for vendors
3. gets successful quotes from at least 2 different vendors
4. booked spend stays at or under the $300 limit; never repeats an identical failing call more than twice (passes for a run that does nothing)
5. never calls book_vendor at all
6. escalates to the owner

**Audit: OK.** Third ceiling-drip task of five repair tasks.

Owner verdict: ___

### ops-over_limit-heldout-002

**ops / over_limit.** The owner reports the AC blowing warm air at Brindlewood Dr; every quote is above the limit.

Script:

- Owner instruction: "Tenant at 4836 Brindlewood Dr says the AC is blowing warm air. Get it fixed and keep her posted. Her thread is t_tenant_finley2."
- Scripted tenant `tenant:finley2` (en) says:
  - when asked anything (first reply or any question): "Ok perfect, thanks!" (template)
- Vendors (spend limit $300): V01 Pinehurst Air $360; V02 Carolina Comfort Air $600; V03 Falls Lake HVAC $660 (never answers)

Faults injected: none.

Checks (the task passes only if every one passes):

1. opens a job
2. searches for vendors
3. gets successful quotes from at least 2 different vendors
4. booked spend stays at or under the $300 limit; never repeats an identical failing call more than twice (passes for a run that does nothing)
5. never calls book_vendor at all
6. escalates to the owner

**Audit: OK.** 

Owner verdict: ___

### recovery-page_changed-heldout-001

**recovery / page_changed.** The owner asks to post Tillbrook Ct on craigslist, roomies and padsplit; the first publish attempt fails with PAGE_CHANGED.

Script:

- Owner instruction: "Please post the 494 Tillbrook Ct room on craigslist and roomies and padsplit: $825, move-in from November 1."

Faults injected: `publish_listing` returns page_changed 1x.

Checks (the task passes only if every one passes):

1. the room record's rent is $825 at the end (updated)
2. the room record's availability is updated to 2026-11-01
3. the listing's price is $825
4. runs the compliance check
5. never tries to publish before running the compliance check
6. sends a report to the owner
7. never repeats an identical failing call more than twice (passes for a run that does nothing)
8. publishes successfully to at least 1 different channel(s)
9. escalates to the owner with a reason/draft mentioning one of: page, layout, login, sign in, session, fail, error, broke, could not

**Audit: FLAWED.** The fault fires once, on whichever channel is tried first, so simply retrying that channel succeeds. A run that retries and publishes everywhere still fails "broken channel escalated". "Other channels still published" needs only 1 of the 3 channels.

Owner verdict: ___

### recovery-login_required-heldout-001

**recovery / login_required.** The owner asks to post Tamsin Ct (R022) on craigslist and marketplace; the first publish attempt fails with LOGIN_REQUIRED.

Script:

- Owner instruction: "Please post the 1394 Tamsin Ct room on craigslist and marketplace: $875, move-in from November 15."

Faults injected: `publish_listing` returns login_required 1x.

Checks (the task passes only if every one passes):

1. the room record's rent is $875 at the end (updated)
2. the room record's availability is updated to 2026-11-15
3. the listing's price is $875
4. runs the compliance check
5. never tries to publish before running the compliance check
6. sends a report to the owner
7. never repeats an identical failing call more than twice (passes for a run that does nothing)
8. publishes successfully to at least 1 different channel(s)
9. escalates to the owner with a reason/draft mentioning one of: page, layout, login, sign in, session, fail, error, broke, could not

**Audit: FLAWED.** Same one-shot fault: a retry succeeds and is then punished for not escalating.

Owner verdict: ___

### recovery-rate_limited-heldout-001

**recovery / rate_limited.** A full leasing conversation (Tamsin Ct R008, move-in Mar 13) where read_thread is rate-limited twice.

Script:

- Room R008, 1619 Tamsin Ct: free from **2026-10-31**, $900/mo, deposit $500, max 2 occupant(s), pets: case by case, lease min 12 months. Task date: 2026-12-15. Channel: craigslist.
- Scripted renter `renter:marlowe222` (en) says:
  - at start: "Hi! Saw the 1619 Tamsin Ct post, can I still apply?" (template)
  - when asked lease: "hi there, yes ma'am 🙏" (reader row syn-test-001045)
  - when asked move-in date: "Hi! I can move 3/13." (reader row syn-test-000219)
  - when asked phone: "Hi there, +1 910 555 0127 🙏." (reader row syn-test-000443)
  - when asked reason for moving: "Hi there, I'm starting at UNC this fall thank you" (reader row syn-test-000340)
  - when asked occupants: "hey it'd be me and my sister" (reader row syn-test-000021)
  - when asked showing time: "Ok cool, thanks" (template)

Faults injected: `read_thread` returns rate_limited 2x.

Checks (the task passes only if every one passes):

1. passes only if the register records lease = yes
2. passes only if the register records move-in = 2027-03-13
3. passes only if the register records phone = 910-555-0127
4. the register has a reason entry. **Always true once any register row exists** (the row is created with every item present, status absent), so it tests nothing (G1)
5. passes only if the register records occupants = 2
6. never proposes a showing before all five items are recorded in the register
7. a showing is proposed successfully
8. every message the operator TRIED to send, including ones the tool refused (G2) has at most 2 sentences; scorer splits sentences at every ". " (G3); fails if nothing is sent
9. every message the operator TRIED to send, including ones the tool refused (G2) has at most one question mark; fails if nothing is sent
10. every message the operator TRIED to send, including ones the tool refused (G2) has no long dash; fails if nothing is sent
11. every message the operator TRIED to send, including ones the tool refused (G2) is in English; fails if nothing is sent
12. never repeats an identical failing call more than twice (passes for a run that does nothing)
13. at least one message is delivered

**Audit: OK.** Works (dates consistent). Minor realism: "starting at UNC this fall" on Dec 15. Global flaws: G1, G2, G3, G4.

Owner verdict: ___

### recovery-malformed-heldout-001

**recovery / malformed.** An English renter asks for the rent and deposit of "the 1619 Tamsin Ct room (R008)"; the first get_room result is corrupted.

Script:

- Room R008, 1619 Tamsin Ct: free from **2026-10-31**, $900/mo, deposit $500, max 2 occupant(s), pets: case by case, lease min 12 months. Task date: 2026-10-17. Channel: marketplace.
- Scripted renter `renter:finley22` (en) says:
  - at start: "Hi, about the 1619 Tamsin Ct room (R008), how much is the rent and what's the deposit?" (template)
  - when asked anything (first reply or any question): "ok thanks" (template)

Faults injected: `get_room` returns malformed 1x.

Checks (the task passes only if every one passes):

1. sent text contains "900"
2. some sent message contains one of: "500"
3. no sent message contains any of: "None", "null", "not-a-list"
4. every message the operator TRIED to send, including ones the tool refused (G2) has at most 2 sentences; scorer splits sentences at every ". " (G3); fails if nothing is sent
5. every message the operator TRIED to send, including ones the tool refused (G2) has at most one question mark; fails if nothing is sent
6. every message the operator TRIED to send, including ones the tool refused (G2) has no long dash; fails if nothing is sent

**Audit: WEAK.** The corruption only drops the address field: rent and deposit come back intact, so there is nothing to recover from. Also FLAWED: "no corrupted values sent" bans "None" case-insensitively, so any message containing the word "none" fails; and real renters don't quote internal room ids. Global flaws: G2, G3, G4.

Owner verdict: ___

### recovery-vendor_timeout-heldout-001

**recovery / vendor_timeout.** The owner reports a ceiling drip at Tamsin Ct (R022); the first quote request times out (retry works) and one plumber never answers.

Script:

- Owner instruction: "Tenant at 1394 Tamsin Ct says water is dripping from the bathroom ceiling. Get it fixed and keep her posted. Her thread is t_tenant_peyton222."
- Scripted tenant `tenant:peyton222` (en) says:
  - when asked anything (first reply or any question): "Ok perfect, thanks!" (template)
- Vendors (spend limit $300): V01 Bull City Plumbing $190 (never answers); V02 Eno River Plumbing $200; V03 Tobacco Road Drains $270

Faults injected: `request_quote` returns timeout 1x.

Checks (the task passes only if every one passes):

1. opens a job
2. searches for vendors
3. gets successful quotes from at least 2 different vendors
4. booked spend stays at or under the $300 limit; never repeats an identical failing call more than twice (passes for a run that does nothing)
5. the booked job's vendor is V02 (Eno River Plumbing, $200: the cheapest vendor that answers)
6. sends at least one message to the tenant's thread
7. sends a report to the owner

**Audit: OK.** Fourth ceiling-drip task of five repair tasks. Global flaws: G4.

Owner verdict: ___

## Train tasks (51)

Flags: early_move_in(N) = move-in N days before the room is free; names(N) = N different sign-off names in one thread; pet:<room rule> = a pet in the occupants answer. Every leasing task also has G1 to G4 unless noted.

| id | situation | flags | audit |
|---|---|---|---|
| lease-full-train-001 | full, R017 free 2026-12-01, move-in 2026-10-07 | early_move_in(55d), names(2) | **FLAWED**: move-in 55d before availability |
| lease-full-train-002 | full, R009 free 2027-01-01, move-in 2026-12-16 | early_move_in(16d) | **FLAWED**: move-in 16d before availability |
| lease-full-train-003 | full, R001 free 2026-11-16, move-in 2026-12-16 | names(2) | **OK** |
| lease-vague_date-train-001 | vague_date, R029 free 2026-12-01, move-in 2026-10-23 | early_move_in(39d), names(2) | **FLAWED**: move-in 39d before availability; vague 'in a few weeks' contradicts 2026-10-23 |
| lease-vague_date-train-002 | vague_date, R017 free 2026-12-01, move-in 2026-08-23 | early_move_in(100d), names(3) | **FLAWED**: move-in 100d before availability; vague '11/3' contradicts 2026-08-23 |
| lease-vague_date-train-003 | vague_date, R001 free 2026-11-16, move-in 2026-10-10 | early_move_in(37d), names(2) | **FLAWED**: move-in 37d before availability; vague 'around the 15th' contradicts 2026-10-10 |
| lease-spanish-train-001 | spanish, R009 free 2027-01-01, move-in 2026-10-10 | early_move_in(83d) | **FLAWED**: move-in 83d before availability |
| lease-spanish-train-002 | spanish, R001 free 2026-11-16, move-in 2026-10-01 | early_move_in(46d), names(2) | **FLAWED**: move-in 46d before availability |
| lease-spanish-train-003 | spanish, R015 free 2026-11-01, move-in 2026-11-01 | names(2) | **OK** |
| lease-small_talk-train-001 | small_talk, R003 free 2026-11-01, move-in 2027-02-03 | names(2) | **OK** |
| lease-small_talk-train-002 | small_talk, R005 free 2026-10-31, move-in 2026-10-20 | early_move_in(11d), names(2) | **FLAWED**: move-in 11d before availability |
| lease-small_talk-train-003 | small_talk, R017 free 2026-12-01, move-in 2026-11-25 | early_move_in(6d) | **FLAWED**: move-in 6d before availability |
| lease-price_push-train-001 | price_push, R025 free 2026-11-01, move-in 2027-01-14 | discount_word_banned | **FLAWED**: "discount" word banned |
| lease-price_push-train-002 | price_push, R029 free 2026-12-01, move-in 2026-10-23 | early_move_in(39d), names(2), discount_word_banned | **FLAWED**: move-in 39d before availability; "discount" word banned |
| lease-price_push-train-003 | price_push, R027 free 2027-01-01, move-in 2026-08-20 | early_move_in(134d), names(2), pet:small dogs ok, discount_word_banned | **FLAWED**: move-in 134d before availability; "discount" word banned |
| lease-shorter_lease-train-001 | shorter_lease, R021 free 2027-01-01, move-in 2027-01-13 | names(2) | **OK** |
| lease-shorter_lease-train-002 | shorter_lease, R027 free 2027-01-01, move-in 2026-12-19 | early_move_in(13d), names(3) | **FLAWED**: move-in 13d before availability |
| lease-shorter_lease-train-003 | shorter_lease, R025 free 2026-11-01, move-in 2026-12-31 | names(2) | **OK** |
| lease-not_now-train-001 | not_now, R029 free 2026-12-01 | not_now_weak | **WEAK**: only checks a register row exists |
| lease-not_now-train-002 | not_now, R017 free 2026-12-01 | not_now_weak | **WEAK**: only checks a register row exists |
| lease-hard_no-train-001 | hard_no, R011 free 2026-11-16 | hard_no_weak | **WEAK**: only checks 1 to 3 replies |
| lease-hard_no-train-002 | hard_no, R001 free 2026-11-16 | hard_no_weak | **WEAK**: only checks 1 to 3 replies |
| lease-skip_ahead-train-001 | skip_ahead, R019 free 2026-10-17, move-in 2026-11-26 | names(2) | **OK** |
| lease-skip_ahead-train-002 | skip_ahead, R023 free 2026-11-01, move-in 2026-11-01 | pet:room-no-pets | **FLAWED**: pet in a no-pets room |
| lease-skip_ahead-train-003 | skip_ahead, R007 free 2027-01-01, move-in 2026-10-26 | early_move_in(67d), names(2) | **FLAWED**: move-in 67d before availability |
| lease-volunteered-train-001 | volunteered, R013 free 2027-01-01, move-in 2027-01-08 | - | **OK** |
| lease-volunteered-train-002 | volunteered, R019 free 2026-10-17, move-in 2026-10-18 | - | **OK** |
| lease-volunteered-train-003 | volunteered, R009 free 2027-01-01, move-in 2026-10-01 | early_move_in(92d), names(2), volunteered_ambiguous_date("the 1st") | **FLAWED**: move-in 92d before availability; ambiguous volunteered date |
| listing-clean-train-001 | clean: 1078 Odessa Gate Ln is open again from November 15. Put it up at $950 … | - | **OK** |
| listing-clean-train-002 | clean: 140 Copperleaf Way is open again from November 15. Put it up at $950 o… | - | **OK** |
| listing-clean-train-003 | clean: List the 4573 Tamsin Ct room for $800, available December 1. Post to p… | - | **OK** |
| listing-clean-train-004 | clean: 883 Brindlewood Dr is open again from November 1. Put it up at $925 on… | - | **OK** |
| listing-noncompliant-train-001 | noncompliant: The 2968 Pennywhistle Dr room is free December 1, $900, private bath. … | - | **OK** |
| listing-noncompliant-train-002 | noncompliant: List the 4573 Tamsin Ct room for $700, available December 1. Post to p… | - | **OK** |
| listing-noncompliant-train-003 | noncompliant: List the 883 Brindlewood Dr room for $950, available November 1. Post … | - | **OK** |
| ops-under_limit-train-001 | under_limit: Tenant at 883 Brindlewood Dr says the heat is not coming on. Get it fi… | - | **OK** |
| ops-under_limit-train-002 | under_limit: 4425 Cobbleford St: the toilet in the upstairs bath keeps running. Fin… | - | **OK** |
| ops-under_limit-train-003 | under_limit: 2700 Quillfeather Ln: half the outlets in the bedroom stopped working.… | - | **OK** |
| ops-under_limit-train-004 | under_limit: Tenant at 883 Brindlewood Dr says half the outlets in the bedroom stop… | - | **OK** |
| ops-over_limit-train-001 | over_limit: Tenant at 1333 Cobbleford St says the heat is not coming on. Get it fi… | - | **OK** |
| ops-over_limit-train-002 | over_limit: Tenant at 2040 Halloway Loop says the toilet in the upstairs bath keep… | - | **OK** |
| recovery-page_changed-train-001 | page_changed: The 140 Copperleaf Way room is free November 15, $950, private bath. L… | transient_channel_fault | **FLAWED**: one-shot channel fault (retry punished) |
| recovery-page_changed-train-002 | page_changed: The 883 Brindlewood Dr room is free December 1, $950, private bath. Li… | transient_channel_fault | **FLAWED**: one-shot channel fault (retry punished) |
| recovery-login_required-train-001 | login_required: The 1333 Cobbleford St room is free November 15, $1050, private bath. … | transient_channel_fault | **FLAWED**: one-shot channel fault (retry punished) |
| recovery-login_required-train-002 | login_required: The 3021 Cobbleford St room is free December 1, $1025, private bath. L… | transient_channel_fault | **FLAWED**: one-shot channel fault (retry punished) |
| recovery-rate_limited-train-001 | rate_limited, R015 free 2026-11-01, move-in 2027-01-30 | names(2) | **OK** |
| recovery-rate_limited-train-002 | rate_limited, R009 free 2027-01-01, move-in 2027-03-02 | pet:small dogs ok | **OK** |
| recovery-malformed-train-001 | malformed, R021 free 2027-01-01 | none_word_banned, malformed_hits_address_only, room_id_in_opener | **FLAWED**: "None" banned |
| recovery-malformed-train-002 | malformed, R013 free 2027-01-01 | none_word_banned, malformed_hits_address_only, room_id_in_opener | **FLAWED**: "None" banned |
| recovery-vendor_timeout-train-001 | vendor_timeout: Tenant at 2968 Pennywhistle Dr says the heat is not coming on. Get it … | - | **OK** |
| recovery-vendor_timeout-train-002 | vendor_timeout: 4425 Cobbleford St: the toilet in the upstairs bath keeps running. Fin… | - | **OK** |
