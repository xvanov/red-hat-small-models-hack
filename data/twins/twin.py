"""Step 3: write a synthetic TWIN of every labeled real thread.

A twin keeps the real thread's SHAPE and nothing else:
  same turns in the same order (renter / owner), same per-message reader labels (which items are
  answered, vague, refused or conditional; the intents; the language of each message, so a language
  switch stays a switch), same style hints (short/long, emoji, casing), same timing gaps (scaled),
  and the same ending (a ghosted thread ends where the renter went silent).
Everything else is new: the renter is a persona sampled from nvidia/Nemotron-Personas-USA, and the
dates, phone number (fictional 555-01xx), reason, job, details and every word are invented.

By default the generator NEVER sees the real wording: it gets only the label skeleton above.
--show-original passes the real text as a tone reference (still local, and the prompt forbids
copying); filter.py checks every twin line against every real line either way.

Each twin is verified: its renter messages are re-labeled with the same labeler, and the labels must
equal the target skeleton (statuses, values, intents, language). Mismatches are fed back for a rewrite
(--attempts). The twin's gold labels = the original's labels with the twin's own dates, phone and
reason (remapped), so they are known by construction and confirmed by the re-label.

Output: work/twins.jsonl (synthetic; still links to the real thread id, so it stays in work/).
Usage: data/twins/.venv/bin/python data/twins/twin.py [--fixture] [--limit N] [--attempts 3] [--show-original]
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import random
import re
import sys
from datetime import date, datetime, timedelta

import personas as persona_pool
import time

from common import (FIELDS, LocalLLM, Paths, common_args, detect_lang, hid, is_cp, label_message, log_timing, pii_hits,
                    pmap, read_jsonl, setup, stratified_sample, to_context, write_jsonl)
from label import RULE_FIELDS, RULE_INTENTS, reader_presence, rule_labels

MONTHS_EN = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
             "November", "December"]
MONTHS_ES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
             "noviembre", "diciembre"]
AREA_CODES = ["919", "984", "336", "704", "828", "910", "252"]
QUESTION_TOPICS = ["laundry", "whether it is furnished", "what utilities cost", "internet speed", "kitchen use",
                   "the deposit", "whether the bathroom is shared", "parking", "bus access", "storage space",
                   "quiet hours", "who the housemates are", "air conditioning", "the pet policy", "the lease start"]
TWIN_WINDOW = (date(2026, 10, 19), date(2027, 2, 26))  # twin threads start in the sandbox's season

FIELD_GUIDE = {
    "lease": {"answered": "clearly agree to a one-year lease",
              "vague": "be noncommittal about a one-year lease (probably / depends / not sure), no clear yes or no",
              "no": "refuse a one-year lease",
              "exception": "agree to a one-year lease but attach a condition you invent (subletting part of it, a job contingency...)"},
    "move_in": {"answered": "give the move-in date {date} (write it as month name + day, no weekday)",
                "vague": "give only a vague move-in time with NO resolvable day (just a month, 'soon', 'end of the month', 'in a few weeks')",
                "no": "decline to give a move-in date",
                "exception": "give the move-in date {date} (month name + day) but with a condition you invent"},
    "phone": {"answered": "give this phone number exactly: {phone}",
              "vague": "do NOT give a full number: give only part of {phone} or say you will send it later",
              "no": "decline to share a phone number",
              "exception": "give this phone number exactly: {phone}, with a caveat (temporary, work phone, text only...)"},
    "occupants": {"answered": "make clear that {occ} will move in",
                  "vague": "be unsure how many people will move in (maybe someone else too)",
                  "no": "decline to say how many people",
                  "exception": "{occ} will move in, plus someone who stays only part-time"},
    "reason": {"answered": "give a concrete reason for moving that fits the persona (new job, school, lease ending...)",
               "vague": "give only a vague reason (need a change, personal reasons)",
               "no": "decline to say why you are moving"},
}
INTENT_GUIDE = {
    "price_negotiation": "ask for a lower price, a discount or a deal",
    "scheduling": "ask to see the room, or propose / accept a showing time (a viewing, not the move-in)",
    "small_talk": "only pleasantries (thanks, ok, a compliment, an emoji), no qualifying content and no request",
    "not_now": "say you are interested but the timing is later",
    "hard_no": "say you are no longer interested / to stop contacting you",
    "shorter_lease": "ask for a lease shorter than 12 months or month-to-month",
    "question": "ask a factual question about the room or listing: {topic}",
}
ACT_GUIDE = {
    "greet": "a greeting", "confirm_available": "tells them the room is available", "ask_lease": "finds out if a one-year lease works",
    "ask_move_in": "finds out the move-in date", "ask_phone": "gets their phone number", "ask_occupants": "finds out how many people",
    "ask_reason": "finds out why they are moving", "give_price": "mentions the rent (a plausible figure $650-$1,000)",
    "answer_question": "answers the renter's question", "decline_discount": "politely turns down a lower price",
    "offer_shorter_lease": "says the shortest lease possible is 6 months", "propose_showing": "suggests a showing time",
    "confirm_showing": "confirms the showing", "send_application": "says the application link is on its way (no link)",
    "follow_up": "checks in", "close": "wraps up politely", "other": "replies naturally",
}

SYSTEM = """You write SYNTHETIC "twin" chat threads for a public research dataset about room-rental inquiries.
A twin copies only the structure of a conversation: who speaks when, and what each message does. You invent all content.

Hard rules:
1. Write exactly the turns listed, in order, with the given speaker. One JSON entry per turn, nothing added or dropped.
2. Each renter message must do exactly what its spec says and nothing more. Never mention an item the spec does not list
   (no unrequested move-in date, phone, head count, lease answer or reason), because every message is graded against its spec.
3. Use the exact dates and phone number given in the specs, nothing else that looks like a date or phone.
4. Write each message in the language given for it ("en" English, "es" informal Latin American Spanish).
5. Match the style hint: length (short <= 5 words, medium 6-18, long > 18), lowercase/emoji/no punctuation when asked.
6. The renter is the persona given (use their first name only if a message would naturally include it). Invent their job,
   reason and details from the persona. The landlord rents rooms in Durham, NC, is brief and friendly, and writes in the first person.
7. Never write a street address, house number, URL, email, last name or a real business name.
8. Originality: every sentence must be newly written. Do not reuse any phrase of four or more words from any source text,
   and avoid stock template phrases.
9. Sound like real people texting: casual, natural, varied. Never echo the spec's wording ("I agree to a one-year lease",
   "timing is later", "I confirm the room is available" are wrong); say it the way a person would.
10. "does" and "must" describe a message's PURPOSE, not its words: never write "I ask", "I confirm", "I accept".
Return JSON only: {"turns": [{"i": <turn number>, "speaker": "renter"|"landlord", "text": "<message>"}, ...]}
Each entry's speaker must equal the listed speaker for that turn number."""

OPS_SYSTEM = """You write SYNTHETIC "twin" chat threads for a public research dataset about running shared rental houses.
The chat is between a landlord (he rents rooms in shared houses in Durham, NC) and {who}.
A twin copies only the structure of a real conversation: who speaks when, and what each message does. You invent all content.

Hard rules:
1. Write exactly the turns listed, in order, with the given speaker. One JSON entry per turn, nothing added or dropped.
2. Each message must do what its "does" list says. The matter of the chat is: {topic}. Invent the concrete details
   (which fixture, symptoms, times, amounts) yourself; keep them consistent across the chat.
3. Write each message in the language given for it ("en" English, "es" informal Latin American Spanish).
4. Match the style hint: length (short <= 5 words, medium 6-18, long > 18), lowercase/emoji when asked.
5. The {cp} is the persona given. The landlord is brief, polite, direct, writes in the first person, no emoji.
6. Never write a street address, house number, URL, email, phone number, last name, lockbox or door code, or a real
   business name. Say "the house" or a room name instead of an address.
7. Originality: every sentence must be newly written; avoid stock template phrases.
8. Sound like real people texting: casual, natural, varied. Never echo the spec's wording.
Return JSON only: {{"turns": [{{"i": <turn number>, "speaker": "{cp}"|"landlord", "text": "<message>"}}, ...]}}
Each entry's speaker must equal the listed speaker for that turn number."""

OPS_ACT_GUIDE = {
    # owner (ops)
    "ask_details": "asks for details", "request_photo": "asks for a photo or video", "troubleshoot": "suggests a quick fix to try first",
    "schedule_visit": "arranges a visit time", "give_access_info": "explains how to get in (no codes)", "confirm": "confirms",
    "acknowledge": "acknowledges briefly", "rent_or_payment_reminder": "reminds about a payment", "utility_notice": "states this month's utility share",
    "policy_statement": "states a house policy", "negotiate_price": "pushes back on the price", "approve_or_pay": "approves the work or says payment is sent",
    "decline": "declines", "follow_up": "checks in", "close": "wraps up", "greet": "a greeting", "other": "replies naturally",
    # tenant
    "report_problem": "reports a problem in the house", "send_photo": "sends a photo", "answer_question": "answers the question",
    "ask_question": "asks a question", "propose_time": "suggests a time", "payment_update": "gives a payment update",
    "ask_delay_or_partial": "asks to pay later or in part", "housemate_issue": "raises an issue with a housemate",
    "move_out_or_renewal": "talks about moving out or renewing", "thanks": "says thanks", "complain": "complains",
    # vendor
    "introduce_or_reply_to_lead": "introduces themselves / replies to the job request", "send_quote": "gives a price or estimate",
    "confirm_visit": "confirms the visit", "running_late": "says they are running late", "cancel_or_reschedule": "cancels or moves the visit",
    "decline_job": "turns the job down", "send_photo_or_proof": "sends photos or proof of the work", "report_done": "says the work is done",
    "request_payment": "asks to be paid",
}
MEDIA_TOKEN = re.compile(r"\[(photo|video|audio|file)\]")


# --------------------------------------------------------------------------------------------- helpers
def date_h(d: date, lang: str) -> str:
    return f"{d.day} de {MONTHS_ES[d.month - 1]}" if lang == "es" else f"{MONTHS_EN[d.month - 1]} {d.day}"


def occ_h(n, lang):
    if n == 1:
        return "only the renter (one person)"
    return f"{n} people in total"


def persona_name(p: dict) -> str:
    m = re.match(r"\s*([A-Z][\w'\-]+)", p.get("persona") or "")
    return m.group(1) if m else "Alex"


def plan(th: dict, pool: list[dict], salt: str) -> dict:
    """Everything random about a twin, decided up front and seeded by the thread: persona, start date,
    timing, new dates and phone."""
    rng = random.Random(hid(salt, th["thread_id"], "twin"))
    persona = rng.choice(pool)
    span = (TWIN_WINDOW[1] - TWIN_WINDOW[0]).days
    start = datetime.combine(TWIN_WINDOW[0] + timedelta(days=rng.randrange(span)), datetime.min.time())
    start = start.replace(hour=rng.randint(8, 20), minute=rng.randrange(60))
    orig = [datetime.fromisoformat(t["ts"]) for t in th["turns"]]
    ts = [start]
    for a, b in zip(orig, orig[1:]):
        gap = max(0.0, (b - a).total_seconds()) * rng.uniform(0.8, 1.25)
        ts.append(ts[-1] + timedelta(seconds=max(30, gap)))
    phone_digits = f"{rng.choice(AREA_CODES)}55501{rng.randrange(100):02d}"
    fmt = rng.choice(["{a}-{b}-{c}", "({a}) {b}-{c}", "{a} {b} {c}", "{a}.{b}.{c}", "{a}{b}{c}"])
    phone_h = fmt.format(a=phone_digits[:3], b=phone_digits[3:6], c=phone_digits[6:])
    date_map = {}
    for k, t in enumerate(th["turns"]):
        lab = t.get("labels") or {}
        mi = lab.get("move_in") or {}
        if mi.get("status") in ("answered", "exception"):
            key = mi.get("date") or f"none{k}"
            if key not in date_map:
                try:
                    delta = (date.fromisoformat(mi["date"]) - date.fromisoformat(t["ts"][:10])).days
                except (TypeError, ValueError):
                    delta = rng.randint(10, 45)
                nd = ts[k].date() + timedelta(days=max(1, delta + rng.randint(-6, 6)))
                date_map[key] = nd.isoformat()
    return {"persona": persona, "name": persona_name(persona), "ts": [x.isoformat(timespec="minutes") for x in ts],
            "phone": "+1" + phone_digits, "phone_h": phone_h, "date_map": date_map,
            "topics": rng.sample(QUESTION_TOPICS, len(QUESTION_TOPICS))}


def cp_speaker(th: dict) -> str:
    return {"leasing": "renter", "ops": "tenant", "contractor": "contractor"}[th.get("category", "leasing")]


def skeleton(th: dict, pl: dict) -> list[dict]:
    out = []
    cat = th.get("category", "leasing")
    for k, t in enumerate(th["turns"]):
        if t.get("media"):
            out.append({"i": t["i"], "speaker": "landlord" if t["role"] == "owner" else cp_speaker(th),
                        "fixed_text": t["text"], "does": ["sends only an attachment; the text is exactly " + t["text"]],
                        "language": t.get("lang", th["language"]), "_gold": None})
            continue
        if t["role"] == "owner":
            guide = ACT_GUIDE if cat == "leasing" else OPS_ACT_GUIDE
            out.append({"i": t["i"], "speaker": "landlord", "language": t.get("lang", th["language"]),
                        "does": [guide.get(a, a) for a in t.get("acts", ["other"])]})
            continue
        if cat != "leasing":
            lab = t.get("labels") or {}
            out.append({"i": t["i"], "speaker": cp_speaker(th), "language": lab.get("language") or t.get("lang", "en"),
                        "does": [OPS_ACT_GUIDE.get(a, a) for a in t.get("acts", ["other"])],
                        "style": {k2: t["style"][k2] for k2 in ("length", "emoji", "casing")}, "_gold": None})
            continue
        lab = t["labels"]
        lang = lab["language"]
        spec, gold = [], {"language": lang, "intents": list(lab["intents"])}
        for f in FIELDS:
            st = lab[f]["status"]
            if st == "absent":
                continue
            d = None
            if f == "move_in" and st in ("answered", "exception"):
                d = pl["date_map"].get(lab[f].get("date") or f"none{k}")
            txt = FIELD_GUIDE[f].get(st, "").format(date=date_h(date.fromisoformat(d), lang) if d else "",
                                                    phone=pl["phone_h"], occ=occ_h(lab["occupants"]["value"], lang))
            spec.append(f"{f}: {txt}")
            gold[f] = {"status": st, "date": d} if f == "move_in" else {"status": st, "value": lab[f].get("value")}
        absent = [f for f in FIELDS if lab[f]["status"] == "absent"]
        topic = pl["topics"][k % len(pl["topics"])]
        out.append({"i": t["i"], "speaker": "renter", "language": lang,
                    "must": spec + [f"intent: {INTENT_GUIDE[x].format(topic=topic)}" for x in lab["intents"]
                                    if x in INTENT_GUIDE],
                    "must_not_mention": absent, "style": {k2: t["style"][k2] for k2 in ("length", "emoji", "casing")},
                    "_gold": gold})
    return out


def structure_problem(twin_turns, skel) -> str | None:
    by_i = {t.get("i"): t.get("text") for t in twin_turns if isinstance(t, dict)}
    if sorted(by_i) != sorted(s["i"] for s in skel) or any(not isinstance(v, str) or not v.strip() for v in by_i.values()):
        return "the JSON must have exactly one non-empty text for each listed turn number"
    spk = {t.get("i"): t.get("speaker") for t in twin_turns if isinstance(t, dict)}
    swapped = [s["i"] for s in skel if spk.get(s["i"]) != s["speaker"]]
    if swapped:  # the model lost track of who is talking: every later turn is unusable
        return (f"turns {swapped[:6]}: wrong speaker; each turn must be written by its listed speaker "
                f"(renter or landlord), in the listed order")
    return None


def compare(lab: dict, gold: dict) -> list[str]:
    out = []
    for f in FIELDS:
        want = gold.get(f, {"status": "absent"})
        got = lab[f]
        if got["status"] != want["status"]:
            out.append(f"{f} reads as '{got['status']}' but must be '{want['status']}'"
                       + (" (do not mention it at all)" if want["status"] == "absent" else ""))
            continue
        if f == "move_in" and want.get("date") and got.get("date") != want["date"]:
            out.append(f"move-in date reads as {got.get('date')} but must be {want['date']}")
        if f in ("lease", "occupants") and want["status"] in ("answered", "exception", "no") and \
                want.get("value") is not None and got.get("value") != want["value"]:
            out.append(f"{f} value reads as {got.get('value')} but must be {want['value']}")
    gi, wi = set(lab["intents"]) - {"small_talk"}, set(gold["intents"]) - {"small_talk"}
    if gi != wi:
        if wi - gi:
            out.append(f"must also clearly do: {', '.join(sorted(wi - gi))}")
        if gi - wi:
            out.append(f"must NOT do: {', '.join(sorted(gi - wi))}")
    if lab["language"] != gold["language"]:
        out.append(f"must be in {gold['language']}")
    return out


def gold_of(s: dict, pl: dict) -> dict:
    """Gold for a twin renter message = its TRUTH SHEET: exactly the values the twin writer was instructed to express
    (statuses and intents from the reader's reading of the real message, with the twin's own new date and fictional
    phone). Checked against the twin's text by to_tasks.consistency(). reason is scored on status only."""
    g = s["_gold"]
    o = {}
    for f in FIELDS:
        w = g.get(f)
        if not w:
            o[f] = {"status": "absent", "date": None, "raw": None} if f == "move_in" else {"status": "absent", "value": None}
            continue
        st = w["status"]
        if f == "move_in":
            o[f] = {"status": st, "date": w.get("date") if st in ("answered", "exception") else None, "raw": None}
        elif f == "phone":
            o[f] = {"status": st, "value": pl["phone"] if st in ("answered", "exception") else None}
        elif f == "reason":
            o[f] = {"status": st, "value": None}
        elif f == "lease":
            o[f] = {"status": st, "value": {"answered": True, "exception": True, "no": False}.get(st)}
        else:
            o[f] = {"status": st, "value": w.get("value") if st in ("answered", "exception") else None}
    o["intents"] = list(g["intents"])
    o["language"] = g["language"]
    return o


def rule_flags(text: str, gold: dict) -> list[str]:
    """Keys where the cheap rules disagree with the gold on presence (flag for review, never a reason to drop)."""
    r = rule_labels(text)
    gp = reader_presence(gold)
    return [k for k in RULE_FIELDS + RULE_INTENTS if r[k] != gp[k]]


def make_twin(th: dict, pool, salt, gen: LocalLLM, show_original: bool) -> dict:
    """One draft of the whole thread, retried only if its structure is broken (turn count or speakers). The twin is
    NOT rewritten until a model reads it a certain way (that would select for text the labeler finds easy)."""
    pl = plan(th, pool, salt)
    skel = skeleton(th, pl)
    p = pl["persona"]
    cat = th.get("category", "leasing")
    persona_txt = (f"{pl['name']}, {p.get('age')}, {p.get('occupation') or ''}, from {p.get('city')}, {p.get('state')}. "
                   f"{(p.get('persona') or '')[:500]}")
    public = [{k: v for k, v in s.items() if not k.startswith("_")} for s in skel]
    if show_original:
        for s, t in zip(public, th["turns"]):
            s["tone_reference_do_not_copy"] = t["text"]
    if cat == "leasing":
        system = SYSTEM
    else:
        who = "a tenant who rents a room in one of his houses" if cat == "ops" else \
            "a contractor (handyman, tradesperson or service company) doing a job at one of his rental houses"
        system = OPS_SYSTEM.format(who=who, cp=cp_speaker(th), topic=(th.get("topic") or "other").replace("_", " "))
    user = (f"{cp_speaker(th).title()} persona: {persona_txt}\nThe thread starts on {pl['ts'][0][:10]}; messages are "
            f"spread over time like the original.\nTurns:\n{json.dumps(public, ensure_ascii=False, indent=1)}")
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    texts, probs = None, []
    for d in range(3):
        out = gen.chat_json(msgs, temperature=0.8, max_tokens=12000, cache_key=f"draft{d}", escalate=False)
        turns = (out or {}).get("turns") or []
        for x in turns:  # attachment-only turns are fixed; accept them whatever the model wrote
            sk = next((q for q in skel if q["i"] == (x.get("i") if isinstance(x, dict) else None)), None)
            if sk and sk.get("fixed_text") and isinstance(x, dict):
                x["text"], x["speaker"] = sk["fixed_text"], sk["speaker"]
        sp = structure_problem(turns, skel)
        if not sp:
            by_i = {t["i"]: t["text"] for t in turns}
            texts = [by_i[x["i"]] for x in skel]
            probs = []
            break
        probs = [sp]
        msgs = msgs[:2] + [{"role": "assistant", "content": json.dumps({"turns": turns}, ensure_ascii=False)},
                           {"role": "user", "content": sp + ". Rewrite the whole JSON."}]
    out_turns = []
    for k, s in enumerate(skel):
        orig = th["turns"][k]
        text = s.get("fixed_text") or (texts[k] if texts else "")
        t = {"i": s["i"], "role": "owner" if s["speaker"] == "landlord" else orig["role"], "ts": pl["ts"][k], "text": text}
        if is_cp(orig):
            t["style"] = s.get("style")
            t["difficulty"] = orig.get("difficulty")
            t["media"] = bool(orig.get("media"))
            if cat == "leasing" and s.get("_gold"):
                t["gold"] = gold_of(s, pl)
                t["unscorable"] = list(orig.get("unscorable") or [])
                t["flags"] = {"rule_vs_gold_on_twin": rule_flags(text, t["gold"]),
                              "reader_vs_rule_on_original": [x for x in RULE_FIELDS + RULE_INTENTS
                                                             if orig.get("rule") and orig.get("labels") and
                                                             reader_presence(orig["labels"])[x] != orig["rule"][x]]}
            else:
                t["acts"] = orig.get("acts", ["other"])
                t["language"] = s["language"]
        else:
            t["acts"] = orig.get("acts", ["other"])
            t["language"] = s["language"]
        out_turns.append(t)
    lang_off = sum(1 for s, t in zip(skel, out_turns) if s["speaker"] != "landlord" and not s.get("fixed_text")
                   and len(t["text"].split()) > 3 and detect_lang(t["text"]) != s["language"])
    return {
        "twin_id": "tw_" + hid(salt, th["thread_id"], "twin-id"), "source_thread": th["thread_id"],
        "category": cat, "topic": th.get("topic"), "counterpart": th.get("counterpart", "renter"),
        "persona": {"name": pl["name"], "age": p.get("age"), "sex": p.get("sex"), "occupation": p.get("occupation"),
                    "city": p.get("city"), "state": p.get("state"), "summary": p.get("persona"),
                    "source": persona_pool.DATASET, "source_uuid": p.get("uuid"), "license": persona_pool.LICENSE},
        "phone": pl["phone"], "channel": th["channel"], "language": th["language"],
        "language_switch": th["language_switch"], "start": pl["ts"][0], "turns": out_turns,
        "outcome": th.get("outcome"), "final_stage": th.get("final_stage"), "features": th.get("features"),
        "rules_period": bool(th.get("rules_period")),
        "verified": texts is not None, "problems": probs, "language_mismatch_turns": lang_off,
        "generator_saw_original": show_original,
    }


def main():
    ap = common_args(argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter))
    ap.add_argument("--show-original", action="store_true", help="give the generator the real text as a tone reference")
    ap.add_argument("--gen-reasoning", choices=["on", "off"], default="off",
                    help="Lightning reasoning while WRITING twins (default off: on spends ~30k tokens per draft and "
                         "often runs out before answering). Verification always reasons.")
    a = ap.parse_args()
    setup(a)
    P = Paths.make(a.fixture, a.split)
    threads = [t for t in read_jsonl(P.work / "labeled.jsonl") if t.get("labeled")][: a.limit]
    threads = stratified_sample(threads, a.sample, lambda t: (
        t.get("category", "leasing"), "mixed" if t["language_switch"] else t["language"], t.get("final_stage")))
    t0 = time.time()
    if not threads:
        sys.exit("no labeled threads: run label.py first")
    pool = persona_pool.load()
    gen = LocalLLM("operator", P.cache, reasoning=a.gen_reasoning == "on")
    salt = P.salt()
    twins = pmap(lambda th: make_twin(th, pool, salt, gen, a.show_original), threads, a.workers)
    gen.require_healthy("twin")
    write_jsonl(P.work / "twins.jsonl", twins)
    ok = sum(t["verified"] for t in twins)
    print(f"{len(twins)} twins, {ok} structurally complete (generation reasoning {a.gen_reasoning})")
    log_timing(P.work, "twin", len(twins), time.time() - t0, [gen])


if __name__ == "__main__":
    main()
