"""Shared prompt, target serialization and output parsing for the reader.

Every backend (base model, fine-tuned model, Lightning) sees exactly the same
system prompt and user message, so the eval compares models, not prompts.
The fine-tuned model is trained on this same prompt, so serving it needs no
extra glue: send build_messages(row) and parse the reply with parse_output().
"""
from __future__ import annotations

import json
import re

STATUSES = ("answered", "vague", "no", "exception", "absent")
INTENTS = ("price_negotiation", "scheduling", "small_talk", "not_now", "hard_no", "shorter_lease", "question")
FIELDS = ("lease", "move_in", "phone", "occupants", "reason")

SYSTEM_PROMPT = """You read one message from a person asking about a room for rent and return JSON only.
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
language: "es" if the message is Spanish, else "en"."""


def user_message(inp: dict) -> str:
    lines = [f"Today: {inp['today']}"]
    if inp.get("context"):
        lines.append("Thread so far:")
        lines += [f"{c['role']}: {c['text']}" for c in inp["context"]]
    else:
        lines.append("Thread so far: (none)")
    lines.append("Latest renter message:")
    lines.append(inp["message"])
    return "\n".join(lines)


def build_messages(inp: dict) -> list[dict]:
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user_message(inp)}]


def canonical(out: dict) -> dict:
    """Fixed key order and intent order, so the training target is deterministic."""
    o = {}
    for f in FIELDS:
        src = out.get(f) or {}
        if f == "move_in":
            o[f] = {"status": src.get("status", "absent"), "date": src.get("date"), "raw": src.get("raw")}
        else:
            o[f] = {"status": src.get("status", "absent"), "value": src.get("value")}
    intents = out.get("intents") or []
    o["intents"] = [i for i in INTENTS if i in intents] + [i for i in intents if i not in INTENTS]
    o["language"] = out.get("language", "en")
    return o


def target_text(out: dict) -> str:
    return json.dumps(canonical(out), ensure_ascii=False, separators=(",", ":"))


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.M)
_THINK = re.compile(r"<think>.*?</think>", re.S)


def parse_output(text: str | None) -> dict | None:
    """Lenient parse: strip reasoning and code fences, take the outermost {...}.
    Returns None when no JSON object can be recovered (counted as invalid)."""
    if not text:
        return None
    t = _THINK.sub("", text)
    if "</think>" in t:
        t = t.split("</think>")[-1]
    t = _FENCE.sub("", t.strip())
    start, end = t.find("{"), t.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        obj = json.loads(t[start:end + 1])
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def schema_valid(obj: dict | None) -> bool:
    """Structurally valid reader JSON: every field present with a known status, intents a list."""
    if not isinstance(obj, dict):
        return False
    for f in FIELDS:
        v = obj.get(f)
        if not isinstance(v, dict) or v.get("status") not in STATUSES:
            return False
    return isinstance(obj.get("intents"), list) and obj.get("language") in ("en", "es")
