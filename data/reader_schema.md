# Reader label schema (W5 -> W6)

One row = one renter message to read. The reader sees the thread context and the
latest renter message and returns JSON that describes **only the latest message**.
Context is there to interpret it (a bare "yes" answers the lease question only if
the operator just asked it).

## Row format (`data/processed/reader/*.jsonl`, `data/published/reader/*.jsonl`)

```json
{
  "id": "syn-train-000123",
  "source": "synthetic" | "sgd",
  "input": {
    "today": "2026-10-17",
    "context": [{"role": "operator" | "renter", "text": "..."}],
    "message": "latest renter message"
  },
  "output": {
    "lease":     {"status": S, "value": true | false | null},
    "move_in":   {"status": S, "date": "YYYY-MM-DD" | null, "raw": "span as written" | null},
    "phone":     {"status": S, "value": "+19195550123" | null},
    "occupants": {"status": S, "value": 2 | null},
    "reason":    {"status": S, "value": "short normalized reason" | null},
    "intents":   ["price_negotiation", ...],
    "language":  "en" | "es"
  },
  "meta": {"templates": [...], "hard_cases": [...]}
}
```

`S` is one of `answered | vague | no | exception | absent`.

## Status rules

| Field | answered | vague | no | exception |
|---|---|---|---|---|
| lease (one-year lease) | explicit yes; value `true` | "probably", "as long as necessary", "depends"; value `null` | refuses a year; value `false` | yes with a condition ("if I can sublet in summer"); value `true` |
| move_in | a resolvable calendar day: "Nov 1st", "el primero de noviembre", "this Saturday", "the 15th" (next 15th) | a month, "soon", "ASAP", "next month", "around the 15th", "a fines de mes", **and any numeric date where both parts are 1-12 and differ ("1/11")** because month/day order is ambiguous | declines to give one | a date with a condition ("Nov 1 unless my lease extends"); date filled |
| phone | full 10-digit US number in any format; value normalized to E.164 | partial number, "I'll send it later" | declines | number with a caveat ("this one is temporary"); value filled |
| occupants | count of people (pets don't count: "me and my dog" = 1) | "maybe me and a friend" | declines | count plus a part-time guest ("just me, my boyfriend stays weekends"); value = core count |
| reason | concrete reason ("new job at Duke", "lease ending") | "need a change", "personal reasons" | declines | (unused) |

Relative dates resolve against `input.today`; a bare month-day picks the next
occurrence on or after today.

## Intents (multi-label, may be empty)

- `price_negotiation` asks for a lower price, discount or deal
- `scheduling` wants to see the room / proposes or asks for a showing time
- `small_talk` the message carries no qualifying content and no request (thanks, ok, emojis, compliments)
- `not_now` interested but the timing is later ("not moving until spring")
- `hard_no` no longer interested / stop contacting
- `shorter_lease` asks for less than 12 months / month-to-month
- `question` asks a factual question about the room or listing (furnished, utilities, pets, the property's phone)

A request for the **property's** phone number is `question`, never a renter phone.
A showing date (SGD `visit_date`) is `scheduling`, never a move-in date.
