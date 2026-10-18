# Demo video script (target 4:00, hard limit 3 to 5 minutes)

Follows the organizers' structure (`docs/hackathon/README.md` §7): intro 20 to 30 s, pitch 30 to 40 s, live demo 45 to 60 s, how it's built 60 to 90 s, so-what 20 to 30 s. One take, no cuts in the live part. Camera on. Numbers in `{{...}}` are filled by `scripts/fill_results.py --write`; if one is still a placeholder when you record, say the sentence without the number rather than guessing.

## Before you hit record (5 minutes)

1. `scripts/demo.sh`. Both badges in the top bar must be green: **Nemotron 3.5 Lightning 30B · vLLM** and **reader · 0.6B** (not "reader · rules"). Grey means a tunnel is down: run `scripts/demo.sh` again.
2. Open **http://100.64.38.18:8080** in a 1920×1080 window at 100% zoom (same console as localhost:8080). Click **Reset**.
3. Phone (on Tailscale): open **http://100.64.38.18:8080/approve**. It should say nothing needs you.
4. Rehearse once: **▶ Demo run**, let it finish, then **Reset**. The run takes 75 to 130 s on the live models.
5. Loom (or any recorder) with the camera bubble bottom-left, away from the trace.

If the GPU is unreachable: `CONSOLE_FORCE_STUB=1 scripts/demo.sh`. The badge then says **stub**; say so out loud and do not present it as the model.

## 1. Intro (0:00 to 0:25)

**Screen:** console after Reset, camera on.

> "Hi, I'm Kalin, team Rentus. I rent out about fifty rooms in Durham, North Carolina. We built Rentus Operator: small open models on one GPU that run my leasing desk and my maintenance calls, and only come to me when a decision is mine to make."

## 2. Pitch (0:25 to 1:00)

**Click ▶ Demo run as you start talking.** Step 1 (listing) plays while you pitch; the blue bar on top names each step.

> "Renting a room is the same loop all day. Write the listing, post it everywhere, answer the same questions in English and Spanish, check five things about every renter: a one-year lease, an exact move-in date, a phone number, a reason and how many people. Then book a showing. Then a tenant texts that the sink is leaking."
>
> "One open model does all of that here: NVIDIA Nemotron 3.5 Lightning on vLLM, calling 41 tools. Plain code checks every call it makes. And a tiny model we fine-tuned reads each renter's message. Everything stays on our GPU."

**Point at** the Marketplace / Roomies / Craigslist cards in the channel strip as they turn live: "That listing was just written from the room record, fair-housing checked and posted to three sites."

## 3. Live demo (1:00 to 2:00)

Keep talking over the run. Read the bar's line if you lose your place.

| When the bar says | Point at | Say |
|---|---|---|
| **Two renters at once** | María's and Devon's cards under Inquiries, their gate bars | "Two renters write at the same time. María writes in Spanish and gets Spanish back. Each bar is the five questions: green is an exact answer, striped is vague. She said 'early November', so it asks for the exact day." |
| **Break something** | Red and amber rows in the Live trace (tick **recoveries only** if it is busy) | "Now we break things on purpose: Marketplace rate-limits us and the reader returns garbage. The verifier catches the bad data and the operator retries. Nothing broken reaches a renter." |
| **Plumber job** | Maintenance card under the pipeline | "A tenant's sink leaks. It opens a job and asks three plumbers for quotes. One never answers, so it moves on, books the cheapest under my $400 limit and texts the tenant." |
| **Owner approves on the phone** | Hold the phone to the camera | "Devon offered $700. It is not allowed to change a price, so it asked me and kept qualifying him." **On the phone: tap Edit, type "Thanks for asking, the rent is firm at $750 a month.", tap Send edit.** "That exact sentence goes to Devon." |
| **Done** | Demand register (right) | "Both renters qualified, showings waiting for my confirmation, the plumber booked. I made one decision." |

If the run is still going at 2:00, keep narrating the trace (every row is the model or the verifier acting live) and move on when it reaches **Done**.

## 4. How it's built (2:00 to 3:30)

**Click** the **⤢** button on the evidence panel (bottom right) to make it big. Tab **Why trust it**.

> "Three parts. Lightning, 30 billion parameters with 3 billion active, does all the talking and every tool call. The reader is Qwen3 0.6B, fine-tuned on 14,000 open and synthetic messages in English and Spanish, and published on Hugging Face. The verifier is ordinary code. That's 30.6 billion parameters, under the 33 billion limit."

> "We pre-registered the test before running it. We built 46 held-out conversations as twins of my real leasing threads: same shape, invented people, frozen before any model saw them. The same Lightning weights go from 9 percent of tasks fully right with our starting setup to 58 percent with the final one, only by changing the prompt, the tool descriptions and the harness, each change measured in NeMo Gym. Claude Opus 5.5 on the exact same harness: 61 percent."

> "On messages I labeled myself, blind, our 0.6B reader gets 0.522 exactly right, Lightning prompted 0.267, Opus 0.667, and ours answers in half a second for free."

**Click** tab **Performance**.

> "vLLM serves both models on one card. Caching the shared prompt gave 76 percent more throughput. Turning reasoning off for routine tool calls doubled the turns per second. The 4-bit version crashed under load, so we tracked it down and serve the full-precision weights: slower, but zero crashes."

**Click** tab **Real world**, then **Open the live post ↗** for two seconds, then back.

> "And it isn't only a sandbox. The operator wrote this listing on our real Facebook Page and I posted it unedited. Replies run in shadow mode: it drafts, I send."

## 5. So what (3:30 to 4:00)

**Click ⤢** again to shrink the panel.

> "For a small landlord this is the difference between living in the inbox and making a few decisions a day. It runs on one GPU, renter data stays on it, every step is on screen including when something breaks, and we measured it honestly, including where it didn't win. The code, the Gym environment, the datasets and the reader model are all open. Thanks for watching."

## Timing check

| Section | Target | Organizer range |
|---|---|---|
| Intro | 0:00 to 0:25 | 20 to 30 s |
| Pitch (demo run starts here) | 0:25 to 1:00 | 30 to 40 s |
| Live demo | 1:00 to 2:00 | 45 to 60 s |
| How it's built | 2:00 to 3:30 | 60 to 90 s |
| So what | 3:30 to 4:00 | 20 to 30 s |

If the run stalls on a long model turn, **Reset** and **▶ Demo run** restart cleanly in a second; cut nothing, just say "restarting the run".
