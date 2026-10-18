# Demo video script (target 4:00, hard limit 3 to 5 minutes)

Follows the organizers' structure (`docs/hackathon/README.md` §7): intro 20 to 30 s, pitch 30 to 40 s, live demo 45 to 60 s, how it's built 60 to 90 s, so-what 20 to 30 s. One take, no cuts in the live part. Camera on. Every number below is final (`docs/results.md`, "Confirmatory results (v3)").

## Before you hit record (5 minutes)

1. `scripts/demo.sh`. Both dots in the top bar must be green: **Nemotron 3.5 Lightning · vLLM** and **reader · 0.6B**. Grey means a tunnel is down: run `scripts/demo.sh` again.
2. Channel daemon running (`.venv/bin/python -m channels.live status`: SMS, Messenger and email connected, `send_enabled` true). The channel dots in the top bar are green.
3. Open the console at **http://100.64.38.18:8080** in a 1920×1080 window at 100% zoom, tab **Inbox**. Archive old test threads (`python -m channels.live archive all`) so the new one is on top.
4. Phone ready, **not** the allowlisted owner number, with (888) 891-2046 saved and the Rentus Homes Facebook Page open in Messenger.
5. Publish the new Appling Way post (Assistant tab, Facebook Page row, **Publish**) and paste its link into `{{FB_POST_URL}}` in README.md and docs/submission.md.
6. Rehearse once: text the line "Hi, is the Appling Way room still available?" and time the reply (usually 10 to 30 s). Archive that thread.
7. Recorder with the camera bubble bottom-left.

If the GPU is unreachable, do not fake it: the console shows grey dots and the daemon queues replies. Say so on camera and show the Model and Data tabs.

## 1. Intro (0:00 to 0:25)

**Screen:** console, Inbox tab, camera on.

> "Hi, I'm Kalin, team Rentus. I rent out rooms in Durham, North Carolina. We built Rentus Operator: small open models on one GPU that answer my renters, book showings and handle repairs, and only come to me when a decision is mine to make."

## 2. Pitch (0:25 to 1:00)

> "Renting a room is the same loop all day. Write the listing, post it everywhere, answer the same questions in English and Spanish, and check five things about every renter: a one-year lease, an exact move-in date, a phone number, a reason, and how many people. Then book a showing."
>
> "Here one open model does all of that: NVIDIA Nemotron 3.5 Lightning on Red Hat vLLM, calling 41 tools. Plain code checks every call it makes, and a tiny model we fine-tuned reads each renter's message. And this is running for real right now, on my real phone line, my Facebook Page and my email."

## 3. Live demo (1:00 to 2:00)

| Do | Point at | Say |
|---|---|---|
| **Text (888) 891-2046** from the phone, on camera: "Hi, is the Appling Way room still available? I'd move in early November." | Phone to the camera | "I'm texting my business line as a renter would." |
| Wait for the reply on the phone; then click the new thread at the top of **Inbox** | The reply bubble, then the five qualification dots | "That reply came from Lightning. It answered only from facts I confirmed, and it caught that 'early November' isn't a date, so it asks for the exact day. Each dot is one of the five questions: green is exact, amber is vague." |
| Open the **Activity** drawer | Tool calls, reader parse, verifier rows | "Every step is here: the reader turning my message into exact data, each tool call, and the code checks that would stop a false 'you're booked'." |
| Optional, if time: message the **Rentus Homes Page** in Messenger in Spanish | The Messenger thread appearing in Inbox | "Same on Messenger, and it answers in the renter's language." |
| Click **Assistant**; show the last listing run (or type `Appling Way room free Nov 1, $750, private bath`) | Listing card, per-site status, Facebook Page row | "This is me talking to it. It wrote the listing, ran a fair-housing check, and filled the listing sites. It stops before the final submit, and the Facebook post goes up only when I click Publish." |
| Click **Pipeline** | Gate progress per person, a showing row | "Every renter in one place, from first message to showing. Showings go on my Google Calendar, only inside the hours I marked as available." |

Plain-language guards to mention once if there is time: it never states a fact I haven't confirmed, never claims something is booked when it isn't, speaks as me, asks before spending money, runs a fair-housing check, and I can switch it off or a renter can text STOP.

## 4. How it's built (2:00 to 3:30)

**Click** the **Model** tab.

> "Three parts. Lightning, 30 billion parameters with 3 billion active, does all the talking and every tool call. The reader is Qwen3 0.6B that we fine-tuned. The verifier is ordinary code. That's 30.6 billion parameters, under the 33 billion limit."

> "We pre-registered the test before running it: 46 held-out conversations built as twins of my real leasing threads, frozen before any model saw them, scored in NeMo Gym. The same Lightning weights go from fully passing 9.2 percent of tasks with our starting setup to 58.2 percent with the final one, only by changing the prompt, the tool descriptions and the checks around it. Claude Opus 5.5 on the same harness passed 61.1 percent. We also tried letting code decide when to call the model: 80 percent fewer calls, but only 13 percent passed, so it's off."

> "On 90 renter messages I labeled myself, blind, our 0.6B reader gets 52 percent exactly right, Lightning prompted 27 percent, Opus 67 percent. So it beats the big model at this one job, not the frontier."

Scroll to the serving section.

> "vLLM serves both models on one card. Caching the shared prompt gave 76 percent more throughput, and turning reasoning off for routine tool calls doubled the turns per second. The 4-bit version crashed under load, so we serve full precision: slower, but zero crashes."

**Click** the **Data** tab.

> "Everything is open: the reader model and two datasets on Hugging Face, built from open data and synthetic twins of my threads. No real renter text is published or sent to an outside API."

## 5. So what (3:30 to 4:00)

**Screen:** back to **Inbox**, the live thread.

> "For a small landlord this is the difference between living in the inbox and making a few decisions a day. It runs on one GPU, renter data stays on it, every step is visible, and we measured it honestly, including where it didn't win. Try it yourself at demo.rentus.homes. Thanks for watching."

## Timing check

| Section | Target | Organizer range |
|---|---|---|
| Intro | 0:00 to 0:25 | 20 to 30 s |
| Pitch | 0:25 to 1:00 | 30 to 40 s |
| Live demo | 1:00 to 2:00 | 45 to 60 s |
| How it's built | 2:00 to 3:30 | 60 to 90 s |
| So what | 3:30 to 4:00 | 20 to 30 s |

If the SMS reply is slow, keep going: open the Activity drawer while it runs (the thread shows "Operator is typing…"), and come back to the phone when it lands.
