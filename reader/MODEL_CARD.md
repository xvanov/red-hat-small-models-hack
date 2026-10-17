---
license: cc-by-sa-4.0
base_model: Qwen/Qwen3-0.6B
language: [en, es]
pipeline_tag: text-generation
library_name: transformers
tags: [information-extraction, json, rental, leasing, small-model, trl, sft]
datasets: [google-research-datasets/schema_guided_dstc8]
---

# rentus-reader-qwen3-0.6b

A small **reader** for room-rental conversations: given the thread so far and the latest renter
message, it returns one exact JSON object saying which qualifying items the message answers
(one-year lease, move-in date, phone, occupants, reason for moving) and how (`answered`,
`vague`, `no`, `exception`, `absent`), plus intents and language (English or Spanish).

It is the "reader" tool of Rentus Operator (NVIDIA x Red Hat Small Models Hack, Raleigh, Oct 2026):
the operator model (Nemotron 3.5 Lightning) calls it like a calculator instead of judging on its
own whether "next month" is a move-in date. The hard cases it is trained for: vague dates
("next month", "around the 15th", an ambiguous "1/11") must never be marked answered; a showing
date is not a move-in date; pets are not occupants; a request for the property's phone is not a
renter phone; relative dates resolve against the given `Today`.

## Use

Serve with vLLM (`vllm serve OWNER/rentus-reader-qwen3-0.6b --max-model-len 4096`) and send the system prompt below plus a
user message of the form:

```
Today: 2026-10-17
Thread so far:
operator: When would you like to move in?
Latest renter message:
el primero de noviembre, somos dos
```

The reply is JSON only, for example
`{"lease":{"status":"absent","value":null},"move_in":{"status":"answered","date":"2026-11-01","raw":"el primero de noviembre"},...}`.
The chat template defaults to thinking off. The exact system prompt is in `reader/prompt.py` of the
project repo and reproduced at the end of this card.

## Training

- Base: `Qwen/Qwen3-0.6B` (0.6B parameters by its model card, Apache 2.0), full-parameter SFT with TRL
  `SFTTrainer`, completion-only loss on the canonical JSON, early stopping on dev loss.
- Data: 14,000 training rows (12,000 bilingual synthetic template rows + 2,000 relabelled
  SGD "Homes" dialogue turns), 1,100 dev, 1,419 held-out test never used for training or tuning.
  Method and sources: `docs/data-provenance.md` and `data/reader_schema.md` in the project repo.
- Run: 876 optimizer steps, effective batch 32, lr 3e-05,
  33.2 min on one NVIDIA RTX PRO 6000 Blackwell Server Edition.

## Evaluation (held-out test, 1,419 rows)

Field columns are status-and-value accuracy (move-in compares status and the resolved date).
Exact match requires every field, the intent set and the language to be right.
"Vague-date trap" is the share of vague move-in answers a system wrongly marked answered or exception.

| System | Exact match | JSON valid | Lease | Move-in | Phone | Occupants | Reason | Intent F1 (micro) | Language | Vague-date trap (lower is better) |
|---|---|---|---|---|---|---|---|---|---|---|
| Deterministic regex fallback (no model) | 0.575 | 1.000 | 0.886 | 0.994 | 0.998 | 0.977 | 0.877 | 0.772 | 0.998 | 0.012 |
| Qwen/Qwen3-0.6B base, same prompt | 0.000 | 0.910 | 0.106 | 0.023 | 0.011 | 0.028 | 0.004 | 0.105 | 0.699 | 0.082 |
| **This model** (Qwen/Qwen3-0.6B + SFT) | 0.791 | 1.000 | 0.991 | 0.977 | 0.997 | 0.999 | 0.865 | 0.951 | 1.000 | 0.012 |
| Nemotron 3.5 Lightning 30B-A3B (operator), same prompt | 0.106 | 0.985 | 0.569 | 0.554 | 0.827 | 0.721 | 0.534 | 0.450 | 0.944 | 0.365 |

## License and provenance

Weights are released under **CC BY-SA 4.0** because part of the training data derives from the
Schema-Guided Dialogue dataset (Google Research, CC BY-SA 4.0); the ShareAlike terms carry over.
The base model is Apache 2.0. Synthetic rows were generated with code written at the event and are
published with their method. No real tenant or renter data was used.

## Limitations

Trained for room-rental leasing in the US (phone numbers normalized to +1). English and Spanish only.
Synthetic templates dominate the training set, so unusual phrasing can still fool it; the operator
treats its output as a tool result checked by deterministic code, not as ground truth.

## System prompt

```
You read one message from a person asking about a room for rent and return JSON only.
Describe ONLY the latest renter message. Use the thread only to interpret it (a bare "yes" answers the lease question only if the operator just asked it).

Return exactly this JSON object, no prose, no code fences:
{"lease":{"status":S,"value":true|false|null},"move_in":{"status":S,"date":"YYYY-MM-DD"|null,"raw":"span as written"|null},"phone":{"status":S,"value":"+1XXXXXXXXXX"|null},"occupants":{"status":S,"value":integer|null},"reason":{"status":S,"value":"short normalized reason"|null},"intents":[zero or more label strings, e.g. "scheduling","question"],"language":"en"|"es"}
S is one of: answered, vague, no, exception, absent (absent = the message does not touch this item).

lease (one-year lease): answered = explicit yes (true). vague = "probably", "as long as necessary", "depends" (null). no = refuses a year (false). exception = yes with a condition such as subletting (true).
move_in: answered = a resolvable calendar day ("Nov 1st", "el primero de noviembre", "this Saturday", "the 15th" = next 15th). vague = only a month, "soon", "ASAP", "next month", "around the 15th", "a fines de mes", or a numeric date like "1/11" where both parts are 1-12 and differ (month/day order is ambiguous); date null. no = declines. exception = a date with a condition; date filled. Resolve relative dates against Today; a bare month-day is the next occurrence on or after Today. raw = the date words exactly as written. A showing/visit date is NOT a move-in date.
phone: answered = full 10-digit US number in any format, normalized to E.164 (+1 and 10 digits). vague = partial number or "I'll send it later". no = declines. exception = number with a caveat ("this one is temporary"), value filled. A request for the property's phone number is not a renter phone.
occupants: number of people moving in (pets do not count: "me and my dog" = 1). vague = "maybe me and a friend". no = declines. exception = core count plus a part-time guest; value = core count.
reason (why they are moving): answered = concrete reason ("new job at Duke", "current lease ending"), value is a short normalized phrase. vague = "need a change", "personal reasons" (null). no = declines (null).
Values are null whenever status is vague, no or absent, except lease no = false.
intents (a JSON list of label strings, zero or more, in this order): price_negotiation (asks for lower price or a deal), scheduling (wants to see the room or proposes/asks a showing time), small_talk (no qualifying content and no request: thanks, ok, emojis, compliments), not_now (interested but timing is later), hard_no (no longer interested / stop), shorter_lease (asks for less than 12 months or month-to-month), question (factual question about the room or listing).
language: "es" if the message is Spanish, else "en".
```
