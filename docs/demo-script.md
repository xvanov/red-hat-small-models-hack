# Demo video script (3 to 5 minutes)

Follows the organizers' structure: intro, pitch, live demo, how it's built, so-what. Every number below is on screen in the console's evidence panels, read from `docs/results.md` and the result files, so the narration matches what judges can check.

## Before you hit record (5 minutes)

1. `scripts/demo.sh`. Both badges must be green: **live · Nemotron 3.5 Lightning 30B · vLLM** and **reader · rentus-reader 0.6B · vLLM**. If either is grey, the GPU tunnel is down: rerun `scripts/demo.sh`.
2. Open `http://localhost:8080` in a 1920×1080 browser window, zoom 100%. Click **Reset**.
3. On the phone (on Tailscale), open the `phone:` URL that `scripts/demo.sh` printed (`http://100.64.38.18:8080/approve`). It should say "Nothing needs you right now."
4. Have the Facebook post open in a second tab: https://www.facebook.com/122140650357237994/posts/122140650345237994
5. Rehearse once with **▶ Demo run**, then **Reset**. The run takes 75 to 130 seconds on the live models (the model's turns vary).
6. Camera on (the organizers ask for it). Loom or any screen recorder.

If the GPU is unreachable on the day: `CONSOLE_FORCE_STUB=1 scripts/demo.sh` runs the console's rule-based stand-in. The badge then says **stub**; say so out loud and do not present it as the model.

## 1. Intro (20 to 30 s)

**Screen:** the console after Reset, camera on.

> "Hi, I'm K. I run about fifty rooms for rent in Durham, North Carolina. This is Rentus Operator: a small open model that does the leasing desk and the maintenance calls for me, and only comes to me when a decision is actually mine to make."

## 2. Pitch (30 to 40 s)

**Screen:** stay on the console. Point at the two green badges, then the empty lanes.

> "Renting a room means the same loop all day: write the listing, post it everywhere, answer the same questions in English and Spanish, check that a renter can do a one-year lease, has an exact move-in date, a phone number, a reason and a headcount, and then book a showing. Then a tenant texts that the sink is leaking and you start calling plumbers."
>
> "Big hosted models can do this, but they cost money on every message and every renter's message leaves your machine. We wanted to see if a 30-billion-parameter open model on one GPU could do it reliably. That's Nemotron 3.5 Lightning on vLLM, plus a tiny 0.6-billion model we fine-tuned to read renter messages."

## 3. Live demo (45 to 60 s of narration; the run itself takes 75 to 130 s)

**Click:** speed stays at **1×**. Click **▶ Demo run**. The blue bar on top names each step; read its line if you lose your place.

| When the bar says | Point at | Say |
|---|---|---|
| **1 List the room** | Owner chat, then the Marketplace / Roomies / Craigslist lanes | "I typed one line. It wrote the listing from the room record, checked it against fair-housing rules, and posted it to three sites." |
| **2 Two renters at once** | María's thread (Spanish) and Devon's (Roomies); the Demand register | "Two renters write in at the same time. María writes in Spanish and gets answered in Spanish. Every reply goes through the small reader model, and the checkmarks fill in: green is an exact answer, the yellow squiggle is vague. María said 'early November', so it asks again for the exact day." |
| **3 Break something** | The red and yellow rows in the Live trace | "Now we break things on purpose: Marketplace rate-limits us and the reader returns garbage. The verifier, which is plain code, not a model, catches the bad data, and the operator retries. Nothing broken reaches the renter." |
| **4 Plumber job** | SMS lane (Jordan), Ops panel on the right | "Meanwhile a tenant's sink is leaking. It opens a job, asks three plumbers for quotes. One never answers, so it moves on, books the cheapest one under my $400 limit, and texts the tenant." |
| **5 Owner approves on the phone** | Hold the phone up to the camera | "Devon asked if the rent is negotiable. It's not allowed to promise money, so it asked me and kept qualifying him. This is my phone." **On the phone: tap Edit, type "Thanks for asking, the rent is firm at $750 a month.", tap Send edit.** "And that exact sentence goes to Devon." |
| (only if the trace shows "Devon writes again") | Devon's thread | "If it answers him itself, Devon pushes once more, a discount for paying three months upfront, and payment terms always come to me." Then the phone, as above. |
| **Done** | Demand register: both renters with five checkmarks and a proposed showing | "Both renters fully qualified, showings proposed and waiting for my confirmation, the plumber booked. I made one decision." |

Optional, if there is time: open **Break something ▾ → Page changed**, then type `Appling Way room free Nov 1, $750, private bath. Post it on Craigslist too.` in the owner box. The Craigslist post fails, the trace shows the fallback, the other sites still go live, and the owner gets told which site broke.

## 4. How it's built (60 to 90 s)

**Click:** the **⤢** button on the bottom-right panel to make it big. Start on **Why trust it**.

> "Three parts. Nemotron 3.5 Lightning, 30 billion parameters, does all the talking and all the tool calls. The reader is Qwen3 0.6B that we fine-tuned on 14,000 open and synthetic messages in English and Spanish. The verifier is ordinary code. Together that's 30.6 billion parameters, under the 33 billion limit."

**Point at** the reader table.

> "On the same 400 held-out messages, our 0.6B reader gets every field exactly right 81 percent of the time. Claude Opus 5.5 prompted gets 74 percent, at 3 seconds and almost a cent per message. Ours takes half a second and costs nothing. It's published on Hugging Face."

**Click:** **Scoreboard**.

> "We built a NeMo Gym environment for this job: the same tools in a sandbox, scripted renters and vendors, and scorers, with 31 held-out tasks we never tuned on. The same Lightning weights went from 1 task out of 31 to 20 out of 31, only by changing the harness, the prompt and the verifier, one change at a time. Each bar is one change."

**Click:** **Why trust it** again, point at the operator table.

> "On those 31 tasks, Claude Opus 5.5 on the exact same harness passes 18, at 11 cents a task. Honestly that's parity, not a win, it's inside our noise. But ours runs on our own GPU, and renter messages never leave it."

**Click:** **Real world**.

> "And it's not only a sandbox. This listing on our real Facebook Page was written by the operator and posted unedited. Replies are read in shadow mode: it drafts, I send."

Click **Open the live post ↗** for two seconds, then back.

## 5. So what (20 to 30 s)

**Screen:** back to the console, panel small again.

> "For a small landlord this is the difference between living in the inbox and making five decisions a day. It runs on one GPU, keeps renter data local, and every step it takes is on screen, including when something breaks. The code, the Gym environment, the datasets and the reader model are all open. Thanks for watching."

## Timing check

| Section | Target | Notes |
|---|---|---|
| Intro | 0:00 to 0:25 | |
| Pitch | 0:25 to 1:00 | |
| Live demo | 1:00 to 2:20 | the run is about 80 s; keep talking over it |
| How it's built | 2:20 to 3:45 | |
| So what | 3:45 to 4:10 | total about 4 minutes |

If a step stalls on stage (the model takes a long turn), keep narrating the trace: every row is the model or the verifier acting live. **Reset** and **▶ Demo run** restart cleanly in a second.
