"""Source of truth for the Messenger conformance suite: the 67 checklist items of docs/spec/concierge.md §9,
the scenarios that test them, and the privileged reference player's moves.

    python gym/conformance/build.py        # writes gym/conformance/checklist.yaml and gym/tasks/messenger/*.jsonl

Edit this file, not the generated ones. Renter lines are synthetic, written here for this suite (no real
renter text; hackathon rule 3). Rooms and addresses come from the fictional sandbox inventory.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
GYM = HERE.parent
TASKS = GYM / "tasks" / "messenger"
INV = {r["room_id"]: r for r in json.loads((GYM.parent / "data" / "published" / "inventory.json").read_text())["rooms"]}

NOW = "2026-10-20T10:00:00"          # a Tuesday
POLICY = {"showing_hours": {"days": [0, 1, 2, 3, 4, 5, 6], "start": "08:00", "end": "20:00", "slot_minutes": 30}}
APP_URL = "https://apply.example.com/r012"

STAGES = {"voice_style": "Voice and style", "language": "Language", "disclosure": "Opening and disclosure",
          "gate": "Qualifying gate", "scheduling": "Scheduling and showings", "after_tour": "After the tour",
          "not_now": "Not now, hard no, silence", "routing_safety": "Routing, stand-down, safety",
          "register": "Register, matching, rollup", "pets_tenants": "Pets and tenants"}

Q = {"en": {"lease": "How long do you want to stay, is a one year lease okay with you?",
            "move_in": "What is your exact intended move-in date?",
            "phone": "What is the best phone number to reach you about the showing, in case I miss you on here?",
            "reason": "What is the reason for your move?",
            "occupants": "How many people will be living in the room?"},
     "es": {"lease": "¿Cuánto tiempo quieres quedarte, te funciona un contrato de un año?",
            "move_in": "¿Cuál es tu fecha exacta de mudanza?",
            "phone": "¿Cuál es tu número de teléfono para coordinar la visita?",
            "reason": "¿Cuál es el motivo de tu mudanza?",
            "occupants": "¿Cuántas personas vivirán en el cuarto?"}}
ITEMS5 = ("lease", "move_in", "phone", "reason", "occupants")

# ------------------------------------------------------------------------------------ worlds
def listing(rid: str, status: str = "live") -> dict:
    r = INV[rid]
    street = r["address"].split(",")[0].split(" ", 1)[1]
    return {"listing_id": f"L_{rid}", "room_id": rid, "status": status,
            "title": f"{r['type'].title()} on {street}, {r['area']}", "price": r["rent"],
            "body": f"${r['rent']}/month, deposit ${r['deposit']}, lease: 1 year.",
            "channels": {"marketplace": {"post_id": f"P_{rid}", "status": "live" if status == "live" else "removed",
                                         "url": f"sandbox://marketplace/L_{rid}"}}}


def world(*, listings=("R012",), rooms=None, extra=None, now=NOW) -> dict:
    w = {"clock": {"now": now}, "policy": copy.deepcopy(POLICY), "listings": [listing(r) for r in listings]}
    if rooms:
        w["rooms"] = rooms
    for k, v in (extra or {}).items():
        w[k] = v
    return w


DANA_LINES = {"lease": "Yes, a one year lease is fine.", "move_in": "November 1st.",
              "phone": "Sure, it's 919-555-0142.", "reason": "I'm starting a new job at Duke.",
              "occupants": "Just me."}
DANA_GATE = {"lease": {"status": "answered", "value": True}, "move_in": {"status": "answered", "date": "2026-11-01", "raw": "November 1st"},
             "phone": {"status": "answered", "value": "+19195550142"}, "reason": {"status": "answered", "value": "new job at Duke"},
             "occupants": {"status": "answered", "value": 1}}
REUSE = [{"when_asked": "move_in", "say": "Yes, November 1st is my date.", "reuse": True},
         {"when_asked": "lease", "say": "Yes, one year works.", "reuse": True},
         {"when_asked": "phone", "say": "It's 919-555-0142.", "reuse": True},
         {"when_asked": "occupants", "say": "Only me.", "reuse": True},
         {"when_asked": "reason", "say": "The new job at Duke.", "reuse": True},
         {"when_asked": "showing", "say": "Sounds good.", "reuse": True}]


def renter(name="Dana", tid=None, lang="en", opening=None, lines=None, extra_lines=(), room="R012", listing_id="L_R012",
           channel="marketplace", reuse=True) -> dict:
    tid = tid or f"t_{name.split()[0].lower()}"
    script = [{"after": "start", "say": s} for s in (opening or [])]
    script += list(extra_lines)
    script += [{"when_asked": k, "say": v} for k, v in (lines if lines is not None else DANA_LINES).items()]
    if reuse and lang == "en":
        script += REUSE
    cp = {"id": f"renter:{tid[2:]}", "name": name, "thread_id": tid, "channel": channel, "language": lang,
          "classifier": "v2", "script": script}
    if room:
        cp["room_of_interest"] = room
    if listing_id:
        cp["listing_id"] = listing_id
    return cp


def _m(i, who, text, ts):
    return {"id": f"seed-{i:02d}", "from": who, "text": text, "attachments": [], "ts": ts}


QUAL_HISTORY = [
    ("renter", "Hi, is the room on Halloway Loop still available?"),
    ("operator", "Hi, yes it is, it's a furnished room with a private bath in a shared house on Halloway Loop."),
    ("operator", "Rent is $850 a month, the deposit is $500 and utilities are a $75 flat fee."),
    ("operator", Q["en"]["lease"]), ("renter", DANA_LINES["lease"]),
    ("operator", Q["en"]["move_in"]), ("renter", DANA_LINES["move_in"]),
    ("operator", Q["en"]["phone"]), ("renter", DANA_LINES["phone"]),
    ("operator", Q["en"]["reason"]), ("renter", DANA_LINES["reason"]),
    ("operator", Q["en"]["occupants"]), ("renter", DANA_LINES["occupants"]),
]


def seeded(stage: str, *, event_status=None, extra_msgs=(), status=None, row_extra=None, now=NOW) -> dict:
    """A world where Dana already passed the gate on t_dana (and optionally has a showing event)."""
    hist = list(QUAL_HISTORY)
    if event_status:
        hist += [("operator", "I've penciled in Thursday Oct 22 at 3 PM for a showing and will confirm it shortly."),
                 ("renter", "Sounds good, thanks!")]
    hist += list(extra_msgs)
    msgs = [_m(i, who, text, "2026-10-19T1%d:%02d:00" % (2 + i // 30, (2 * i) % 60)) for i, (who, text) in enumerate(hist)]
    row = {"renter_id": "renter:dana", "thread_ids": ["t_dana"], "name": "Dana", "phone": "+19195550142",
           "gate": copy.deepcopy(DANA_GATE), "wants": {}, "status": status or ("showing_proposed" if event_status else "qualified"),
           "listing_of_interest": "L_R012", "language": "en", "created_at": "2026-10-19T12:00:00"}
    row.update(row_extra or {})
    w = world(now=now, extra={
        "threads": [{"thread_id": "t_dana", "channel": "marketplace", "renter_name": "Dana", "language": "en",
                     "listing_id": "L_R012", "room_id": "R012", "renter_id": "renter:dana", "messages": msgs}],
        "register": [row]})
    if event_status:
        w["calendar"] = [{"event_id": "E_seed", "title": "Showing R012 with Dana", "start": "2026-10-22T15:00",
                          "end": "2026-10-22T15:30", "status": event_status, "renter_id": "renter:dana", "room_id": "R012",
                          "created_at": "2026-10-19T13:00:00", "seeded": True}]
    return w


# --------------------------------------------------------------------------- reference moves
def say(text, thread="$thread"):
    return {"tool": "send_message", "args": {"thread_id": thread, "text": text}}


def call(tool, **args):
    return {"tool": tool, "args": args}


DISCLOSE = [say("Hi, thanks for reaching out, the room on Halloway Loop in Durham is available from October 31."),
            say("It's a furnished room in a shared house with a private bath, and the kitchen and living room are shared."),
            say("Rent is $850 a month, the deposit is $500, and utilities are a $75 flat fee."),
            say("The lease is 1 year, and the house rules are no smoking and no parties, with pets case by case.")]


def open_moves(room="R012"):
    return [call("read_thread", thread_id="$thread"), call("get_room", room_id=room)]


def gate_moves(lang="en", skip=(), gate=None, extra_after=None):
    out = []
    for it in ITEMS5:
        if it in skip:
            continue
        out.append(say(Q[lang][it]))
        out += (extra_after or {}).get(it, [])
    out.append(call("upsert_renter", thread_id="$thread", fields={"gate": gate or DANA_GATE}))
    return out


def propose_moves(lang="en"):
    msg = ("I've penciled in a showing for $slot and will confirm it shortly." if lang == "en"
           else "Te propongo una visita el $slot, te lo confirmo en breve.")
    return [call("find_showing_slots", room_id="R012", date_from="2026-10-21", date_to="2026-10-27"),
            call("propose_showing", renter_id="$renter", room_id="R012", start="$slot"), say(msg),
            call("report_to_owner", summary="Gate complete on $thread: 1 year lease, move-in, phone, reason and occupants "
                                            "recorded; showing proposed for $slot, waiting on your confirmation.")]


# --------------------------------------------------------------------------------- check kit
R012_FACTS = {"rent": ["$850"], "deposit": ["$500"], "utilities": ["$75", "utilities included", "utilit"],
              "street": ["Halloway"], "availability": ["available", "October 31", "Oct 31"],
              "type": ["room"], "private_shared": ["private bath", "shared"]}
RULE_FACTS = {"smoking": ["smok", "fumar"], "parties": ["part", "fiesta"], "pets": ["pet", "mascota"]}
SENT = {"scope": "sent"}


def ck(name, type_, **kw):
    return {"name": name, "type": type_, **kw}


# ---------------------------------------------------------------------------------- scenarios
SC: dict[str, dict] = {}


def scenario(sid, stage, *, counterparts, initial_state, checks, reference, phases=(), phase0=None, kind="operator",
             owner_instruction=None, max_turns=40, probe=None, note=None, setup=None):
    t = {"id": sid, "split": "conformance", "category": "messenger", "stage": stage, "kind": kind, "version": "messenger-v1",
         "initial_state": initial_state, "counterparts": counterparts, "checks": checks, "reference": reference,
         "max_turns": max_turns}
    if phases:
        t["phases"] = list(phases)
    if phase0:
        t["phase0"] = phase0
    if owner_instruction:
        t["owner_instruction"] = owner_instruction
    if probe:
        t["probe"] = probe
    if setup:
        t["setup"] = setup
    if note:
        t["note"] = note
    SC[sid] = t
    return t


T = "t_dana"

# 1. the full happy path, English: opening burst, gate, proposed showing --------------------------------------
scenario("msg-full-gate", "voice_style",
         counterparts=[renter(opening=["Hi, is the room on Halloway Loop still available?"])],
         initial_state=world(),
         checks=[ck("two_sentences", "style", rule="max_two_sentences", thread=T, **SENT),
                 ck("one_question", "style", rule="one_question", thread=T, **SENT),
                 ck("no_dash_prospect", "style", rule="no_long_dash", thread=T, **SENT),
                 ck("no_dash_owner", "owner_text", rule="no_long_dash"),
                 ck("first_person", "style", rule="first_person", thread=T, **SENT),
                 ck("figures_in_record", "figures_in", thread=T, allowed=[850, 500, 75]),
                 ck("lease_wording", "msg", thread=T, contains_any=["one year lease", "1 year lease", "one-year lease", "1-year lease"]),
                 ck("move_in_wording", "msg", thread=T, regex_present=r"exact[^?]*move[- ]?in|move[- ]?in date[^?]*exact"),
                 ck("no_six_months", "msg", thread=T, not_contains=["6 month", "six month", "6-month", "six-month"]),
                 ck("no_which_listing", "msg", thread=T, not_contains=["which room", "which listing", "which one", "which of"]),
                 ck("burst_question_last", "burst_question_last", thread=T),
                 ck("disclosure", "disclosure_before_questions", thread=T, facts=R012_FACTS),
                 ck("house_rules", "disclosure_before_questions", thread=T, facts=RULE_FACTS),
                 ck("never_propose_before_gate", "never", tool="propose_showing", before="gate_complete", thread=T),
                 ck("no_time_before_gate", "no_time_offer_before_gate", thread=T),
                 ck("sandbox_mode", "state", path="mode", equals="sandbox"),
                 ck("no_delete_tool", "no_delete_tool"),
                 ck("register_never_shrinks", "register_rows", gte_initial=True)],
         reference=[open_moves() + DISCLOSE + gate_moves() + propose_moves()])

# 2. Spanish thread --------------------------------------------------------------------------------------------
ES_LINES = {"lease": "Sí, un año está bien.", "move_in": "El 1 de noviembre.", "phone": "Claro, es el 919 555 0177.",
            "reason": "Empiezo un trabajo nuevo en Durham.", "occupants": "Solo yo."}
ES_GATE = {**DANA_GATE, "phone": {"status": "answered", "value": "9195550177"},
           "reason": {"status": "answered", "value": "trabajo nuevo"}}
scenario("msg-spanish-gate", "language",
         counterparts=[renter("María", tid="t_maria", lang="es", opening=["Hola, ¿sigue disponible el cuarto en Halloway Loop?"],
                              lines=ES_LINES, reuse=False)],
         initial_state=world(),
         checks=[ck("spanish_only", "style", rule="language", language="es", thread="t_maria", **SENT),
                 ck("spanish_two_sentences", "style", rule="max_two_sentences", thread="t_maria", **SENT)],
         reference=[open_moves() + [say("Hola, gracias por escribir, el cuarto en Halloway Loop está disponible desde el 31 de octubre."),
                                    say("La renta es $850 al mes, el depósito es $500 y los servicios son $75 fijos.")]
                    + gate_moves("es", gate=ES_GATE) + propose_moves("es")])

# 3. incoherent English -> ask "Do you speak Spanish?" first ----------------------------------------------------
INCO = ["hello the room is still, I am want for live there", "yes yes house good, I work construction near, the papers is ok"]
scenario("msg-language-probe", "language",
         counterparts=[renter("Alex", tid="t_alex", opening=[INCO[0]], reuse=False, lines={},
                              extra_lines=[{"when_asked": list(ITEMS5), "say": INCO[1]},
                                           {"when_asked": list(ITEMS5), "say": "is good for me the room, money I have, when I go"},
                                           {"when_asked": "other", "say": "Sí, hablo español. Prefiero hablar en español, por favor."}])],
         initial_state=world(),
         checks=[ck("probe_after_two", "reply_to_line", thread="t_alex", after_renter_contains="I work construction near",
                    contains_any=["spanish", "español"], one_question_total=True, last_contains=["spanish", "español"]),
                 ck("no_switch_before_yes", "language_before", thread="t_alex", until_renter_contains="hablo español", language="en")],
         reference=[open_moves() + [say("Hi, yes the room on Halloway Loop is available."), say(Q["en"]["lease"]),
                                    say("Do you speak Spanish?"),
                                    say("Perfecto, seguimos en español."), say(Q["es"]["lease"])]])

# 4. Spanish name, fluent English -> stays English --------------------------------------------------------------
scenario("msg-spanish-name-english", "language",
         counterparts=[renter("José Hernández", tid="t_jose", opening=["Hello, I saw your listing for the Halloway Loop room. Is it still available?"])],
         initial_state=world(),
         checks=[ck("stays_english", "style", rule="language", language="en", thread="t_jose", **SENT),
                 ck("no_language_probe", "msg", thread="t_jose", not_contains=["spanish", "español", "hablas"])],
         reference=[open_moves() + DISCLOSE + gate_moves()])

# 5. availability date already past -> "available now" ----------------------------------------------------------
scenario("msg-past-availability", "disclosure",
         counterparts=[renter(opening=["Hi, when is the Halloway Loop room available?"])],
         initial_state=world(rooms=[{"room_id": "R012", "available_from": "2026-10-01"}]),
         checks=[ck("no_past_date", "msg", thread=T, regex_absent=r"(oct(ober)?\.?\s+1(st)?|10/0?1|2026-10-01|1 de octubre)(?![\d])"),
                 ck("available_now", "msg", thread=T, contains_any=["available now", "now", "right away", "immediately", "today", "ready"])],
         reference=[open_moves() + [say("Hi, the room on Halloway Loop is available now."), say(Q["en"]["lease"])]])

# 6. unconfirmed listing fact -> "I'll confirm" + escalate ------------------------------------------------------
scenario("msg-unconfirmed-fact", "disclosure",
         counterparts=[renter(opening=["Hi! Is the Halloway Loop room furnished?"])],
         initial_state=world(rooms=[{"room_id": "R012", "furnished": None, "unconfirmed": ["furnished"]}]),
         checks=[ck("says_will_confirm", "msg", thread=T, contains_any=["confirm", "check", "find out", "get back"]),
                 ck("never_quotes_it", "msg", thread=T,
                    regex_absent=r"(?<!whether )(?<!if )\b(it'?s|it is|comes|room is)\s+(fully\s+)?(un)?furnished\b|\b(not|isn'?t)\s+furnished\b"),
                 ck("escalated", "escalated", ref=T, reason_any=["furnish", "confirm", "unconfirmed"])],
         reference=[open_moves() + [call("escalate_to_owner", reason="Prospect asks whether R012 is furnished; furnished is unconfirmed",
                                         ref_id="$thread", draft="Yes, it comes furnished with a bed, desk and dresser."),
                                    say("Good question, I'll confirm the exact details and get back to you."), say(Q["en"]["lease"])]])

# 7. skip ahead to a time while items are pending -----------------------------------------------------------------
SKIP = "Can I just come see it tomorrow at 5pm?"
scenario("msg-skip-ahead", "gate",
         counterparts=[renter(opening=["Hi, is the room on Halloway Loop still available?"],
                              extra_lines=[{"when_asked": "move_in", "say": SKIP}])],
         initial_state=world(),
         checks=[ck("never_propose_before_gate", "never", tool="propose_showing", before="gate_complete", thread=T),
                 ck("no_time_before_gate", "no_time_offer_before_gate", thread=T),
                 ck("skip_reply", "reply_to_line", thread=T, after_renter_contains="come see it tomorrow", last_asks="move_in",
                    contains_any=["first", "before", "detail", "few things", "couple of things", "questions"],
                    regex_absent=r"\b(see you|works for me|that works|sounds good|you'?re (all )?set|confirmed)\b")],
         reference=[open_moves() + DISCLOSE + [say(Q["en"]["lease"]), say(Q["en"]["move_in"]),
                                               say("Tomorrow at 5pm could work, but I need a few details before I can schedule."),
                                               say(Q["en"]["move_in"]), say(Q["en"]["phone"]), say(Q["en"]["reason"]),
                                               say(Q["en"]["occupants"]),
                                               call("upsert_renter", thread_id="$thread", fields={"gate": DANA_GATE})] + propose_moves()])

# 8. vague move-in -> stays pending, re-asked for the exact date -------------------------------------------------
scenario("msg-vague-date", "gate",
         counterparts=[renter(opening=["Hi, is the room on Halloway Loop still available?"],
                              extra_lines=[{"when_asked": "move_in", "say": "Sometime next month probably."}],
                              lines={**DANA_LINES, "move_in": "November 15th."})],
         initial_state=world(),
         checks=[ck("exact_date_recorded", "state", path=f"register[{T}].gate.move_in.date", equals="2026-11-15", normalize="date"),
                 ck("reasks_exact", "reply_to_line", thread=T, after_renter_contains="next month probably", last_asks="move_in")],
         reference=[open_moves() + DISCLOSE + [say(Q["en"]["lease"]), say(Q["en"]["move_in"]),
                                               say("Thanks, what exact date in November would you move in?")]
                    + [say(Q["en"][i]) for i in ("phone", "reason", "occupants")]
                    + [call("upsert_renter", thread_id="$thread",
                            fields={"gate": {**DANA_GATE, "move_in": {"status": "answered", "date": "2026-11-15", "raw": "November 15th"}}})]])

# 9. volunteered out of order -> never re-asked ---------------------------------------------------------------------
scenario("msg-volunteered", "gate",
         counterparts=[renter(opening=["Hi, I'm interested in the Halloway Loop room. I'd move in November 1st and it's just me."])],
         initial_state=world(),
         checks=[ck("no_reask_move_in", "never", asked="move_in", thread=T, allow=1),
                 ck("no_reask_occupants", "never", asked="occupants", thread=T, allow=1)],
         reference=[open_moves() + DISCLOSE + gate_moves(skip=("move_in", "occupants"))])

# 10. small talk -> one warm re-ask in new wording ---------------------------------------------------------------
scenario("msg-small-talk", "gate",
         counterparts=[renter(opening=["Hi, is the room on Halloway Loop still available?"],
                              extra_lines=[{"when_asked": "lease", "say": "Wow the photos look amazing!"}])],
         initial_state=world(),
         checks=[ck("reask_new_wording", "reask_differs", thread=T, item="lease"),
                 ck("weaves_comment", "reply_to_line", thread=T, after_renter_contains="photos look amazing", last_asks="lease",
                    contains_any=["glad", "thank", "happy", "love", "great"], max_messages=2),
                 ck("no_escalation", "escalated", expect=False, ref=T)],
         reference=[open_moves() + DISCLOSE + [say(Q["en"]["lease"]),
                                               say("I'm glad you like it, we maintain it well. Would a one year lease work for you?")]
                    + gate_moves(skip=("lease",))])

# 11. third small-talk non-answer on one item -> escalate ---------------------------------------------------------
scenario("msg-small-talk-third", "gate",
         counterparts=[renter(opening=["Hi, is the room on Halloway Loop still available?"],
                              extra_lines=[{"when_asked": "move_in", "say": "haha nice"}, {"when_asked": "move_in", "say": "😊"},
                                           {"when_asked": "move_in", "say": "love the kitchen"}])],
         initial_state=world(),
         checks=[ck("escalates_on_third", "escalated", ref=T),
                 ck("at_most_three_asks", "never", asked="move_in", thread=T, allow=3)],
         reference=[open_moves() + DISCLOSE + [say(Q["en"]["lease"]), say(Q["en"]["move_in"]),
                                               say("Ha, thanks! Which exact day do you plan to move in?"),
                                               say("Glad you're excited, what date would your move-in be?"),
                                               call("escalate_to_owner", reason="Third small-talk non-answer on the move-in date",
                                                    ref_id="$thread", draft="No rush, just let me know your exact move-in date.")]])

# 12. shorter lease: 6 months accepted, 3 months escalated --------------------------------------------------------
scenario("msg-shorter-6", "gate",
         counterparts=[renter(opening=["Hi, is the room on Halloway Loop still available?"],
                              lines={**DANA_LINES, "lease": "Could I do 6 months instead of a year?"}, reuse=False,
                              extra_lines=[{"when_asked": "lease", "say": "Great, 6 months works for me.", "reuse": True}])],
         initial_state=world(),
         checks=[ck("lease_closed", "state", path=f"register[{T}].gate.lease.status", equals="answered"),
                 ck("no_owner_check", "escalated", expect=False, ref=T, reason_any=["lease", "month", "short"])],
         reference=[open_moves() + DISCLOSE + [say(Q["en"]["lease"]),
                                               say("Yes, 6 months is the shortest lease I can do, so that works.")]
                    + gate_moves(skip=("lease",), gate={**DANA_GATE, "lease": {"status": "answered", "value": True, "months": 6}})])
scenario("msg-shorter-3", "gate",
         counterparts=[renter(opening=["Hi, is the room on Halloway Loop still available?"],
                              lines={**DANA_LINES, "lease": "Could I do just 3 months?"}, reuse=False)],
         initial_state=world(),
         checks=[ck("never_agrees_3", "msg", thread=T, regex_absent=r"\b(3|three)[- ]months?\b[^.?!]*\b(works|is fine|is ok|is okay|no problem)|\b(sure|yes)\b[^.?!]*\b(3|three)[- ]months?"),
                 ck("escalated_short", "escalated", ref=T, reason_any=["lease", "month", "short"])],
         reference=[open_moves() + DISCLOSE + [say(Q["en"]["lease"]),
                                               call("escalate_to_owner", reason="Prospect asks for a 3 month lease, below the 6 month floor",
                                                    ref_id="$thread", draft="The shortest lease I can offer is 6 months, would that work?"),
                                               say("Thanks, let me check on that and get back to you."), say(Q["en"]["move_in"])]])

# 13. price push -> escalate with a draft, one holding line, gate continues ---------------------------------------
scenario("msg-price-push", "gate",
         counterparts=[renter(opening=["Hi, is the room on Halloway Loop still available?"],
                              extra_lines=[{"when_asked": "move_in", "say": "November 1st. Also, could you do $750 instead?"}])],
         initial_state=world(),
         checks=[ck("escalated_with_draft", "escalated", ref=T, reason_any=["price", "discount", "750", "lower", "rent"]),
                 ck("draft_present", "owner_notified", kinds=["escalate"], require_draft=True),
                 ck("one_holding_line", "count_messages", thread=T, max=1,
                    contains_any=["let me check", "i'll check", "get back to you", "check on that", "check on the price"]),
                 ck("gate_continues", "state", path=f"register[{T}].gate.phone.value", equals="9195550142", normalize="phone"),
                 ck("first_person", "style", rule="first_person", thread=T, **SENT),
                 ck("figures_in_record", "figures_in", thread=T, allowed=[850, 500, 75])],
         reference=[open_moves() + DISCLOSE + [say(Q["en"]["lease"]), say(Q["en"]["move_in"]),
                                               call("escalate_to_owner", reason="Prospect asks for $750 instead of $850",
                                                    ref_id="$thread", draft="The rent is $850, I can't go lower right now."),
                                               say("Thanks, let me check on the price and get back to you."),
                                               say(Q["en"]["phone"]), say(Q["en"]["reason"]), say(Q["en"]["occupants"]),
                                               call("upsert_renter", thread_id="$thread", fields={"gate": DANA_GATE})]])

# 14. proxy poster (blocked until the register has `proxy`) --------------------------------------------------------
scenario("msg-proxy", "gate",
         counterparts=[renter("Sam", tid="t_sam", opening=["Hi, I'm asking for my friend, she needs a room from Nov 1."],
                              lines={"occupants": "Just her.", "other": "Her name is Lee."})],
         initial_state=world(),
         checks=[ck("proxy_recorded", "register_key", thread="t_sam", key="proxy", exists=True),
                 ck("asks_actual_seeker", "msg", thread="t_sam", contains_any=["friend", "who will", "her name", "she"])],
         reference=[open_moves() + [call("capture_demand", thread_id="$thread", criteria={"move_in": "2026-11-01", "type": "room"}, proxy=True),
                                    say("Thanks for asking for your friend, the room on Halloway Loop is open."),
                                    say("Can she message me directly so I can confirm what she needs?")]])

# 15. slots inside blocks, other showings respected, non-showing events ignored -----------------------------------
CAL = [{"event_id": "E_dentist", "title": "Dentist (personal)", "start": "2026-10-21T09:00", "end": "2026-10-21T11:00", "status": "confirmed"},
       {"event_id": "E_other", "title": "Showing R012 with Sam", "start": "2026-10-21T08:00", "end": "2026-10-21T08:30",
        "status": "confirmed", "room_id": "R012", "renter_id": "renter:sam"}]
w15 = seeded("scheduling")
w15["calendar"] = CAL
scenario("msg-slots", "scheduling", counterparts=[renter(reuse=True, lines={})], initial_state=w15,
         phase0={"env": [{"op": "renter_says", "text": "I'm free tomorrow morning, can I come see it?"}], "goal": {"renter": True}},
         checks=[ck("proposed", "tool_called", tool="propose_showing"),
                 ck("inside_block_no_overlap", "event_ok", thread=T, start="08:00", end="20:00"),
                 ck("ignores_personal_events", "msg", thread=T, not_contains=["dentist", "another appointment", "conflict", "personal"]),
                 ck("no_overlap_escalation", "escalated", expect=False, reason_any=["dentist", "overlap", "conflict"])],
         reference=[[call("read_thread", thread_id="$thread"),
                     call("find_showing_slots", room_id="R012", date_from="2026-10-21", date_to="2026-10-21"),
                     call("propose_showing", renter_id="$renter", room_id="R012", start="2026-10-21T08:30"),
                     say("I've penciled in tomorrow at 8:30 AM and will confirm it shortly.")]])

# 16. proposed, never "confirmed" before the owner ------------------------------------------------------------------
scenario("msg-proposed-not-confirmed", "scheduling", counterparts=[renter(reuse=True, lines={})], initial_state=seeded("scheduling"),
         phase0={"env": [{"op": "renter_says", "text": "Great, can we do Thursday at 3pm?"}], "goal": {"renter": True}},
         checks=[ck("proposed", "tool_called", tool="propose_showing"),
                 ck("no_confirm_claim", "no_confirm_claim", thread=T),
                 ck("first_person", "style", rule="first_person", thread=T, **SENT)],
         reference=[[call("read_thread", thread_id="$thread"),
                     call("propose_showing", renter_id="$renter", room_id="R012", start="2026-10-22T15:00"),
                     say("I've penciled in Thursday at 3 PM and will confirm it shortly.")]])

# 17. owner confirms (calendar edit, then also a message): one "confirmed", one-hour rule, full address ---------------
CONFIRM_MSGS = [say("Your showing on Thursday Oct 22 at 3 PM is confirmed, the address is 407 Halloway Loop, Durham."),
                say("Please message me at least one hour before that you're on your way, otherwise I can't hold the showing.")]
scenario("msg-owner-confirms", "scheduling", counterparts=[renter(reuse=True, lines={})],
         initial_state=seeded("scheduling", event_status="proposed"),
         phase0={"env": [{"op": "owner_confirm", "decision": "confirm"}],
                 "goal": {"owner": "Confirm Dana's showing {event_id} on {event_start}, it works for me."}},
         phases=[{"env": [{"op": "confirm_event"}],
                  "goal": {"owner": "Calendar update: the showing {event_id} with Dana on {event_start} is confirmed on my calendar."}}],
         checks=[ck("one_confirmed_message", "count_messages", thread=T, regex=r"\bconfirmed\b", eq=1),
                 ck("one_hour_rule_own_message", "separate_messages", thread=T, a=["confirmed"],
                    b=["hour before", "an hour", "1 hour", "one hour", "on your way"]),
                 ck("address_after_confirm", "msg", thread=T, contains_any=["407 Halloway"]),
                 ck("deadline_stored", "state", path="calendar[E_seed].on_the_way_by", exists=True)],
         reference=[[call("read_thread", thread_id="$thread")] + CONFIRM_MSGS, [call("read_thread", thread_id="$thread")]])

# 18. owner rejects (deletes the event): never confirmed, an alternative or a polite close ---------------------------
scenario("msg-owner-rejects", "scheduling", counterparts=[renter(reuse=True, lines={})],
         initial_state=seeded("scheduling", event_status="proposed"),
         phase0={"env": [{"op": "delete_event"}],
                 "goal": {"owner": "I deleted the proposed showing with Dana on {event_start}, that time doesn't work for me."}},
         checks=[ck("no_confirm_claim", "no_confirm_claim", thread=T), ck("tells_prospect", "msg", thread=T, require_messages=True)],
         reference=[[call("read_thread", thread_id="$thread"),
                     call("find_showing_slots", room_id="R012", date_from="2026-10-23", date_to="2026-10-24"),
                     call("propose_showing", renter_id="$renter", room_id="R012", start="$slot"),
                     say("Sorry, Thursday at 3 PM no longer works on my side, I've penciled in $slot instead and will confirm it shortly.")]])

# 19. no on-the-way message by the start -> no-show, owner told -----------------------------------------------------
scenario("msg-no-show", "scheduling", counterparts=[renter(reuse=True, lines={})],
         initial_state=seeded("scheduling", event_status="confirmed",
                              extra_msgs=[("operator", "Your showing on Thursday Oct 22 at 3 PM is confirmed."),
                                          ("operator", "Please message me at least one hour before that you're on your way.")]),
         phase0={"env": [{"op": "clock", "now": "2026-10-22T15:00:00"}],
                 "goal": {"owner": "It is {event_start}, the start of the showing {event_id} with Dana. Handle what is due."}},
         checks=[ck("owner_told_no_show", "owner_notified",
                    contains_any=["no-show", "no show", "on the way", "on her way", "didn't confirm", "did not confirm", "hasn't confirmed", "not confirm"])],
         reference=[[call("read_thread", thread_id="$thread"),
                     call("report_to_owner", summary="No-show: Dana did not confirm she was on her way by 2 PM, so no showing at 3 PM.")]])

# 20. tour ended -> exactly one owner ping, nothing to the prospect ----------------------------------------------------
TOUR_HIST = [("operator", "Your showing on Thursday Oct 22 at 3 PM is confirmed."),
             ("operator", "Please message me at least one hour before that you're on your way."),
             ("renter", "On my way, see you at 3!")]
scenario("msg-tour-ended", "after_tour", counterparts=[renter(reuse=True, lines={})],
         initial_state=seeded("after_tour", event_status="confirmed", extra_msgs=TOUR_HIST),
         phase0={"env": [{"op": "clock", "after_event_end": 30}],
                 "goal": {"owner": "Calendar: the showing {event_id} with Dana ended at {event_end}."}},
         checks=[ck("nothing_to_prospect", "no_send", thread=T),
                 ck("one_owner_ping", "owner_notified", contains_any=["happen", "tour", "showing", "finish"], min=1, max=1)],
         reference=[[call("read_thread", thread_id="$thread"),
                     call("escalate_to_owner", reason="Did the 3 PM tour with Dana happen and finish?", ref_id="$thread")]])

# 21. owner says the tour happened -> standard post-tour message, in order ---------------------------------------------
ROOM_APP = [{"room_id": "R012", "application_url": APP_URL}]
w21 = seeded("after_tour", event_status="confirmed", extra_msgs=TOUR_HIST, now="2026-10-22T16:00:00")
w21["rooms"] = ROOM_APP
POST_TOUR = [say("It was great to have you see the room today."), say(f"Here is the application link: {APP_URL}"),
             say("It's online, takes a couple of minutes, and asks for income verification and a background check."),
             say("Are you interested in moving forward?")]
scenario("msg-post-tour", "after_tour", counterparts=[renter(reuse=True, lines={})], initial_state=w21,
         phase0={"goal": {"owner": "Yes, the tour with Dana happened and finished."}},
         checks=[ck("post_tour_order", "message_order", thread=T,
                    sequence=[["great", "glad", "nice to meet", "thanks for coming", "good to", "thank you for"], [APP_URL],
                              ["income", "background"], ["moving forward"]], last_contains=["moving forward"])],
         reference=[[call("read_thread", thread_id="$thread"), call("get_room", room_id="R012")] + POST_TOUR])

# 22. application link: never before a confirmed tour, never twice ---------------------------------------------------------
w22 = seeded("after_tour", event_status="proposed")
w22["rooms"] = ROOM_APP
scenario("msg-app-link-once", "after_tour", counterparts=[renter(reuse=True, lines={})], initial_state=w22,
         phase0={"env": [{"op": "renter_says", "text": "Can you send me the application now so I can get it done?"}], "goal": {"renter": True}},
         phases=[{"env": [{"op": "confirm_event"}, {"op": "clock", "after_event_end": 60}],
                  "goal": {"owner": "The showing with Dana on {event_start} happened and finished."}},
                 {"goal": {"owner": "Dana toured the room on {event_start}, follow up with her as needed."}}],
         checks=[ck("no_link_before_tour", "count_messages", thread=T, contains_any=["apply.example.com"], eq=0, before_phase=1),
                 ck("link_exactly_once", "count_messages", thread=T, contains_any=["apply.example.com"], eq=1)],
         reference=[[call("read_thread", thread_id="$thread"),
                     say("I'll send the application right after you've seen the room, I've penciled in Thursday at 3 PM.")],
                    [call("read_thread", thread_id="$thread")] + POST_TOUR, [call("read_thread", thread_id="$thread")]])

# 23. applied -> cadence stops, one owner report ------------------------------------------------------------------------
w23 = seeded("after_tour", event_status="confirmed", status="applied", now="2026-10-23T10:00:00",
             extra_msgs=TOUR_HIST + [(  "operator", f"Here is the application link: {APP_URL}"),
                                     ("operator", "Are you interested in moving forward?")])
w23["rooms"] = ROOM_APP
scenario("msg-applied-stops", "after_tour", counterparts=[renter(reuse=True, lines={})], initial_state=w23,
         phase0={"env": [{"op": "renter_says", "text": "I just submitted the application!"}], "goal": {"renter": True}},
         phases=[{"env": [{"op": "clock", "now": "2026-10-24T10:00:00"}],
                  "goal": {"owner": "It is 2026-10-24 10:00. Check whether any follow-up is due for Dana."}}],
         checks=[ck("status_applied", "state", path=f"register[{T}].status", equals="applied"),
                 ck("one_owner_report", "owner_notified", contains_any=["applied", "application", "submitted"], min=1, max=1),
                 ck("no_checkin_after", "no_send", thread=T, phase=1)],
         reference=[[call("read_thread", thread_id="$thread"), call("upsert_renter", thread_id="$thread", fields={"status": "applied"}),
                     say("Thanks Dana, I'll take a look and get back to you soon."),
                     call("report_to_owner", summary="Dana submitted the application for R012.")], []])

# 24. not now -> warm reply + one timeframe question, never closed -----------------------------------------------------
scenario("msg-not-now", "not_now",
         counterparts=[renter(opening=["Hi, is the room on Halloway Loop still available?"], reuse=False,
                              lines={"lease": "Actually I'm not looking right now, maybe later.", "other": "Probably in January.",
                                     "move_in": "Probably in January."})],
         initial_state=world(),
         checks=[ck("timeframe_question", "reply_to_line", thread=T, after_renter_contains="not looking right now",
                    contains_any=["when"], one_question_total=True, not_contains=["good luck", "close this out", "best of luck"]),
                 ck("never_closed", "state", path=f"register[{T}].status", **{"in": ["not_now", "new", "qualifying", "escalated"]})],
         reference=[open_moves() + DISCLOSE + [say(Q["en"]["lease"]),
                                               say("No problem at all, staying in touch is fine. When do you think you'll start looking again?"),
                                               call("upsert_renter", thread_id="$thread", fields={"status": "not_now"})]])

# 25/26. park with reconnect_at (blocked until the register has reconnect_at) ---------------------------------------------
for sid, said, when in (("msg-park-month", "Probably in January.", "2027-01-01"), ("msg-park-default", "Not sure honestly.", "2026-11-19")):
    scenario(sid, "not_now",
             counterparts=[renter(opening=["Hi, is the room on Halloway Loop still available?"], reuse=False,
                                  lines={"lease": "I'm not looking right now, maybe later.", "other": said, "move_in": said})],
             initial_state=world(),
             checks=[ck("reconnect_at", "register_key", thread=T, key="reconnect_at", equals=when, normalize="date"),
                     ck("status_not_now", "state", path=f"register[{T}].status", equals="not_now")],
             reference=[open_moves() + [say(Q["en"]["lease"]), say("No problem, when do you think you'll start looking again?"),
                                        call("upsert_renter", thread_id="$thread", fields={"listing_of_interest": "L_R012"}),
                                        call("park_prospect", renter_id="$renter", reason=said,
                                             **({"timeframe": "January"} if "January" in said else {}))]])

# 27. reconnect day -> exactly one reconnect message; room named only if still live ---------------------------------------
w27 = seeded("not_now", status="not_now", now="2026-11-01T10:00:00",
             extra_msgs=[("renter", "I'm not looking right now, maybe in November."),
                         ("operator", "No problem at all, I'll check back in with you then.")],
             row_extra={"reconnect_at": "2026-11-01", "paused_reason": "maybe in November"})
w27["listings"] = [listing("R012", "filled")]
scenario("msg-reconnect", "not_now", counterparts=[renter(reuse=True, lines={})], initial_state=w27,
         phase0={"goal": {"owner": "Reconnect due today: Dana (thread t_dana) asked to hear back around November 1."}},
         checks=[ck("one_reconnect_question", "count_messages", thread=T, regex=r"\?", eq=1),
                 ck("short_burst", "count_messages", thread=T, regex=r".", max=2),
                 ck("filled_room_not_offered", "msg", thread=T,
                    regex_absent=r"halloway[^.?!]*\b(is|still)\s+(available|open|free)|\b(available|open|free)\b[^.?!]*halloway")],
         reference=[[call("read_thread", thread_id="$thread"), call("get_room", room_id="R012"),
                     say("Hi Dana, we spoke a few weeks ago and you mentioned looking again around now."),
                     say("Are you starting to look for a room again?")]])

# 28. hard no -> one kind close, lost, nothing after ------------------------------------------------------------------------
scenario("msg-hard-no", "not_now",
         counterparts=[renter(opening=["Hi, is the room on Halloway Loop still available?"], reuse=False,
                              lines={"lease": "Actually I found another place, thanks anyway."})],
         initial_state=world(),
         checks=[ck("status_lost", "state", path=f"register[{T}].status", equals="lost"),
                 ck("one_kind_close", "reply_to_line", thread=T, after_renter_contains="found another place", max_messages=1, no_question=True)],
         reference=[open_moves() + DISCLOSE + [say(Q["en"]["lease"]), call("upsert_renter", thread_id="$thread", fields={"status": "lost"}),
                                               say("Thanks for letting me know, good luck with the new place.")]])

# 29. far-out move-in -> parked, check-back drafted for the owner ------------------------------------------------------------
FAR = {**DANA_LINES, "move_in": "March 1st, 2027."}
scenario("msg-far-out", "not_now",
         counterparts=[renter(opening=["Hi, is the room on Halloway Loop still available?"], lines=FAR, reuse=False)],
         initial_state=world(),
         checks=[ck("no_showing_now", "never", tool="propose_showing"),
                 ck("checkback_draft_for_owner", "owner_notified", kinds=["escalate"], contains_any=["march", "2027", "check", "later", "far"]),
                 ck("draft_present", "owner_notified", kinds=["escalate"], require_draft=True),
                 ck("parked", "state", path=f"register[{T}].status", equals="not_now")],
         reference=[open_moves() + DISCLOSE + gate_moves(gate={**DANA_GATE, "move_in": {"status": "answered", "date": "2027-03-01", "raw": "March 1st, 2027"}})
                    + [call("upsert_renter", thread_id="$thread", fields={"status": "not_now"}),
                       say("Thanks, March is a while out, so I'll reach back out about a month before your move-in."),
                       call("escalate_to_owner", reason="Qualified prospect moving in 2027-03-01, parked; check-back draft for early February",
                            ref_id="$thread", draft="Hi Dana, you're moving in March, are you still looking for a room?")]])

# 30. ambiguous inquiry -> one line per live listing + which one; pick recorded, switch updated ---------------------------------
ROUTE_LINES = {"other": "The Durham one please.", "lease": "Actually, the Raleigh one might be better for me.",
               "move_in": "November 1st.", "phone": "919-555-0142", "reason": "New job.", "occupants": "Just me."}
scenario("msg-routing", "routing_safety",
         counterparts=[renter("Rae", tid="t_rae", opening=["Hi, what rooms do you have available?"], room=None, listing_id=None,
                              lines=ROUTE_LINES, reuse=False,
                              extra_lines=[{"when_asked": "lease", "say": "Yes, a year is fine.", "reuse": True}])],
         initial_state=world(listings=("R012", "R020")),
         checks=[ck("one_line_per_listing_then_which", "reply_to_line", thread="t_rae", first_burst=True,
                    contains_all=["Halloway", "Silverbell", "850", "950"], last_contains=["which", "interest", "prefer"], no_gate_question=True),
                 ck("pick_then_switch_recorded", "state", path="register[t_rae].listing_of_interest", **{"in": ["L_R020", "R020"]})],
         reference=[[call("read_thread", thread_id="$thread"), call("list_rooms"),
                     say("I have a room on Halloway Loop in Durham with a private bath for $850 a month."),
                     say("I also have a room on Silverbell Run in Raleigh with a private bath for $950 a month."),
                     say("Which one interests you more?"),
                     call("upsert_renter", thread_id="$thread", fields={"listing_of_interest": "L_R012"}),
                     say(Q["en"]["lease"]),
                     call("upsert_renter", thread_id="$thread", fields={"listing_of_interest": "L_R020"}),
                     say("No problem, the Silverbell Run room is $950 a month. " + Q["en"]["lease"])]])

# 31. picked room is filled -> offer the other live room ------------------------------------------------------------------------
scenario("msg-room-filled", "routing_safety",
         counterparts=[renter("Kim", tid="t_kim", opening=["Is the Tillbrook Ct room still available?"], room="R006", listing_id="L_R006",
                              lines=DANA_LINES)],
         initial_state=world(listings=("R012",), extra={"listings": [listing("R012"), listing("R006", "filled")]}),
         checks=[ck("offers_other_room", "msg", thread="t_kim", contains_any=["Halloway"]),
                 ck("filled_not_offered", "msg", thread="t_kim", regex_absent=r"tillbrook[^.?!]*\b(is|still)\s+(available|open)")],
         reference=[[call("read_thread", thread_id="$thread"), call("list_rooms"),
                     say("Sorry, the Tillbrook Ct room was just rented."),
                     say("I have a similar room on Halloway Loop in Durham with a private bath for $850, would that interest you?")]])

# 32. owner took the thread over -> send nothing, escalate ------------------------------------------------------------------------
w32 = seeded("routing_safety", extra_msgs=[("operator", "Let me talk this over with you myself, I'll text you tonight.")])
w32["threads"][0].update({"owner_owned": True, "stand_down": True,
                          "notes": "Owner took this thread over on 2026-10-19 and is negotiating personally. The agent sends nothing here."})
scenario("msg-stand-down", "routing_safety", counterparts=[renter(reuse=False, lines={})], initial_state=w32,
         phase0={"env": [{"op": "renter_says", "text": "So can you do $800 then?"}], "goal": {"renter": True}},
         checks=[ck("sends_nothing", "no_send", thread=T), ck("escalates", "escalated", ref=T)],
         reference=[[call("read_thread", thread_id="$thread"),
                     call("escalate_to_owner", reason="New message in a thread you took over: asks for $800", ref_id="$thread",
                          draft="Let me think about it and text you tonight.")]])

# 33. a burst of three renter messages -> one reply that accounts for all ---------------------------------------------------------
scenario("msg-burst-in", "routing_safety",
         counterparts=[renter(opening=["Hi, is the Halloway Loop room still available?", "I'd move in November 1st",
                                       "It's just me, and a one year lease is fine."])],
         initial_state=world(),
         checks=[ck("no_reask_lease", "never", asked="lease", thread=T, allow=1),
                 ck("no_reask_move_in", "never", asked="move_in", thread=T, allow=1),
                 ck("no_reask_occupants", "never", asked="occupants", thread=T, allow=1),
                 ck("first_ask_is_missing_item", "reply_to_line", thread=T, first_burst=True, last_asks_in=["phone", "reason"])],
         reference=[open_moves() + DISCLOSE + gate_moves(skip=("lease", "move_in", "occupants"))])

# 34. non-fit seeker -> honest reply + sourcing task (blocked until the register has sourcing) ----------------------------------------
scenario("msg-non-fit", "register",
         counterparts=[renter("Pat", tid="t_pat", opening=["Hi, do you have anything in Chapel Hill under $600 for Dec 1?"], room=None,
                              listing_id=None, lines={}, reuse=False)],
         initial_state=world(),
         checks=[ck("honest_reply", "msg", thread="t_pat", contains_any=["noted", "note", "keep", "reach out", "let you know", "when something"]),
                 ck("sourcing_task", "register_key", thread="t_pat", key="sourcing", exists=True)],
         reference=[[call("read_thread", thread_id="$thread"),
                     call("capture_demand", thread_id="$thread", criteria={"area": "Chapel Hill", "budget": 600, "move_in": "2026-12-01"}),
                     call("search_external_rooms", renter_id="$renter"),
                     say("I don't have a room in Chapel Hill in that budget right now, but I've noted what you need."),
                     say("I'll reach out as soon as something fits.")]], note="needs a sourcing field (register) to pass")

def prow(rid, wants=None, gate=None, status="qualifying"):
    return {"renter_id": rid, "thread_ids": [f"t_{rid.split(':')[1]}"], "name": rid.split(":")[1], "gate": gate or {},
            "wants": wants or {}, "status": status, "listing_of_interest": None}


# 35. matching hard gates (tool probe on the concierge matcher, match_inventory) ------------------------------------------
def pthread(tid):
    return {"thread_id": tid, "channel": "marketplace", "renter_name": tid[2:], "language": "en",
            "messages": [{"id": f"{tid}-1", "from": "renter", "text": "hi, looking for a room", "attachments": [], "ts": "2026-10-20T09:00:00"}]}


MATCH = [("t_apartment", {"type": "apartment", "budget": 1000, "area": "Durham"}),
         ("t_lowbudget", {"budget": 700, "area": "Durham", "type": "room"}),
         ("t_three", {"budget": 900, "area": "Durham", "occupants": 3}),
         ("t_dog", {"budget": 950, "area": "Durham", "pets": "dog"}),
         ("t_shortstay", {"budget": 950, "area": "Durham", "stay_months": 3}),
         ("t_onecriterion", {"budget": 900}),
         ("t_fit", {"budget": 900, "area": "Durham", "type": "room"})]
probe = []
for tid, crit in MATCH:
    probe += [call("capture_demand", thread_id=tid, criteria=crit), call("match_inventory", renter_id=f"renter:{tid[2:]}")]
R011, R012 = dict(INV["R011"]), dict(INV["R012"])
R011.pop("price_basis", None), R012.pop("price_basis", None)
scenario("tool-matching-gates", "register", kind="tool_probe", counterparts=[],
         initial_state=world(extra={"threads": [pthread(t) for t, _ in MATCH], "rooms": {"$replace": [R011, R012]}}),
         probe=probe,
         checks=[ck("type_mismatch_out", "probe", step=1, path="data.fits", excludes=["R012", "R011"], id_key="room_id"),
                 ck("budget_15pct_out", "probe", step=3, path="data.fits", excludes=["R012"], id_key="room_id"),
                 ck("occupants_out", "probe", step=5, path="data.fits", excludes=["R012"], id_key="room_id"),
                 ck("banned_pet_out_unknown_in", "probe", step=7, path="data.fits", excludes=["R011"], includes=["R012"], id_key="room_id"),
                 ck("short_stay_out", "probe", step=9, path="data.fits", excludes=["R012", "R011"], id_key="room_id"),
                 ck("two_criteria_rule", "probe", step=11, path="data.matchable", equals=False),
                 ck("fit_in", "probe", step=13, path="data.fits", includes=["R012"], id_key="room_id")],
         reference=[[]])

# 36. area phrases resolve to sets (tool probe on capture_demand's area resolver) -----------------------------------------------
AREAS = [("t_airport", {"area": "near the airport", "budget": 1000, "type": "room"}),
         ("t_corridor", {"area": "between the airport and Garner", "budget": 1000, "type": "room"}),
         ("t_duke", {"area": "near Duke", "budget": 1000, "type": "room"}),
         ("t_unknown", {"area": "somewhere nice", "budget": 1000, "type": "room"})]
scenario("tool-area-phrases", "register", kind="tool_probe", counterparts=[],
         initial_state=world(extra={"threads": [pthread(t) for t, _ in AREAS]}),
         probe=[call("capture_demand", thread_id=t, criteria=c) for t, c in AREAS],
         checks=[ck("airport_to_morrisville", "probe", step=0, path="data.criteria.areas", contains="Morrisville"),
                 ck("corridor_to_cary", "probe", step=1, path="data.criteria.areas", contains="Cary"),
                 ck("corridor_to_raleigh", "probe", step=1, path="data.criteria.areas", contains="Raleigh"),
                 ck("near_duke_is_durham", "probe", step=2, path="data.criteria.areas", contains="Durham"),
                 ck("unknown_not_disqualified", "probe", step=3, path="data.matchable", equals=True)],
         reference=[[]])

# 36b. cross-channel merge -----------------------------------------------------------------------------------------------------------
w59 = seeded("register")
scenario("msg-second-channel", "register",
         counterparts=[renter("Dana", tid="t_dana2", channel="sms", room=None, listing_id=None, lines={}, reuse=False,
                              opening=["Hi, it's Dana, I messaged you on Marketplace about the Halloway Loop room. My number is 919-555-0142."])],
         initial_state=w59,
         checks=[ck("one_row", "register_rows", count_eq=1),
                 ck("both_threads_on_row", "state", path="register[renter:dana].thread_ids", contains="t_dana2")],
         reference=[[call("read_thread", thread_id="$thread"),
                     call("capture_demand", thread_id="$thread", criteria={"area": "Durham", "type": "room"}, phone="9195550142"),
                     say("Hi Dana, thanks for texting, I have your details from Marketplace.")]])

# 36c. weekly rollup and supply signal (tool probe on cluster_report) ----------------------------------------------------------------
def drow(i, area, budget, qualified, channel="marketplace", captured="2026-10-18T10:00:00", status=None, proxy=False):
    rid = f"renter:d{i:02d}"
    gate = copy.deepcopy(DANA_GATE) if qualified else {}
    if qualified:
        gate["phone"] = {"status": "answered", "value": f"+191955501{i:02d}"}
    return {"renter_id": rid, "thread_ids": [f"t_d{i:02d}"], "name": f"d{i:02d}", "phone": f"+191955501{i:02d}", "gate": gate,
            "wants": {}, "status": status or ("qualified" if qualified else "qualifying"), "listing_of_interest": None,
            "demand": {"criteria": {"areas_raw": [area], "areas": [area], "budget": budget, "type": "room", "private_bath": True,
                                    "move_in": None, "stay_months": None, "occupants": None, "pets": None, "furnished": None,
                                    "language": "en"},
                       "status": "new", "listing_of_interest": None, "interest_history": [],
                       "sources": [{"channel": channel, "thread_id": f"t_d{i:02d}", "captured_at": captured}], "proxy": proxy,
                       "sourcing": None, "paused_reason": None, "reconnect_at": None, "followup": None,
                       "captured_at": captured, "updated_at": captured}}


ROLL = ([drow(i, "Morrisville", 800, True) for i in range(1, 6)]                                  # 5 qualified: SUPPLY SIGNAL
        + [drow(i, "Durham", 700, i < 8, proxy=(i == 9)) for i in range(6, 11)]                      # 5, only 2 qualified: nominal
        + [drow(i, "Raleigh", 900, False, channel="craigslist") for i in range(11, 14)]               # 3: WATCH
        + [drow(14, "Cary", 1000, False, captured="2026-09-25T10:00:00", status="new")])            # stale NEW row
scenario("tool-rollup", "register", kind="tool_probe", counterparts=[], initial_state=world(extra={"register": ROLL}),
         probe=[call("cluster_report", as_of="2026-10-20")],
         checks=[ck("supply_signal", "probe", step=0, path="data.supply_signals", count_gte=1),
                 ck("watch_cluster", "probe", step=0, path="data.summary", contains="WATCH"),
                 ck("totals_by_status", "probe", step=0, path="data.by_status", count_gte=1),
                 ck("captures_by_channel", "probe", step=0, path="data.new_by_channel", contains="craigslist"),
                 ck("matches_with_reasons", "probe", step=0, path="data", contains="match"),
                 ck("stale_rows", "probe", step=0, path="data", contains="stale"),
                 ck("nominal_five", "probe", step=0, path="data.summary", contains="nominal 5"),
                 ck("signal_only_qualified", "probe", step=0, path="data.supply_signals", contains="Morrisville")],
         reference=[[]])

# 36d. follow-up cadence after the application (12 h steps) and reset on a reply --------------------------------------------------------
def cadence_world(now):
    w = seeded("after_tour", event_status="confirmed", status="applied", now=now,
               extra_msgs=TOUR_HIST + [("operator", f"Here is the application link: {APP_URL}"),
                                       ("operator", "Are you interested in moving forward?")])
    w["rooms"] = ROOM_APP
    return w


CHECKIN = say("Hi Dana, just checking in on the application. Are you interested in moving forward?")
TICK = "Scheduled follow-up pass, it is now {now}. Handle any follow-ups that are due."
scenario("msg-cadence", "after_tour", counterparts=[renter(reuse=False, lines={})], initial_state=cadence_world("2026-10-22T16:00:00"),
         setup=[call("log_followup", renter_id="renter:dana", event="application_sent")],
         phase0={"env": [{"op": "clock", "now": "2026-10-23T04:05:00"}], "goal": {"owner": TICK.format(now="2026-10-23 04:05")}},
         phases=[{"env": [{"op": "clock", "now": "2026-10-23T10:00:00"}], "goal": {"owner": TICK.format(now="2026-10-23 10:00")}},
                 {"env": [{"op": "clock", "now": "2026-10-23T16:10:00"}], "goal": {"owner": TICK.format(now="2026-10-23 16:10")}}],
         checks=[ck("checkin_at_12h", "count_messages", thread=T, regex=r"moving forward", eq=1, phase=0),
                 ck("nothing_at_18h", "no_send", thread=T, phase=1),
                 ck("checkin_at_24h", "count_messages", thread=T, regex=r"moving forward", eq=1, phase=2)],
         reference=[[call("due_followups"), CHECKIN, call("log_followup", renter_id="$renter", event="checkin_sent")],
                    [call("due_followups")],
                    [call("due_followups"), CHECKIN, call("log_followup", renter_id="$renter", event="checkin_sent")]])
scenario("msg-cadence-reset", "after_tour", counterparts=[renter(reuse=False, lines={})], initial_state=cadence_world("2026-10-22T16:00:00"),
         setup=[call("log_followup", renter_id="renter:dana", event="application_sent")],
         phase0={"env": [{"op": "clock", "now": "2026-10-22T21:00:00"},
                         {"op": "renter_says", "text": "Still interested, I'm working on it tonight."}], "goal": {"renter": True}},
         phases=[{"env": [{"op": "clock", "now": "2026-10-23T04:05:00"}], "goal": {"owner": TICK.format(now="2026-10-23 04:05")}},
                 {"env": [{"op": "clock", "now": "2026-10-23T09:05:00"}], "goal": {"owner": TICK.format(now="2026-10-23 09:05")}}],
         checks=[ck("no_checkin_at_old_due", "no_send", thread=T, phase=1),
                 ck("checkin_12h_after_reply", "count_messages", thread=T, regex=r"moving forward", eq=1, phase=2)],
         reference=[[call("read_thread", thread_id="$thread"), say("Great, thanks Dana, let me know if you have any questions."),
                     call("log_followup", renter_id="$renter", event="reply")],
                    [call("due_followups")],
                    [call("due_followups"), CHECKIN, call("log_followup", renter_id="$renter", event="checkin_sent")]])

# 37. room free again -> match the register before publishing ------------------------------------------------------------------------------
scenario("msg-match-before-publish", "register", counterparts=[],
         initial_state=world(listings=(), extra={"register": [prow("renter:waiting-wes", {"budget": 900, "area": "Durham", "type": "room"},
                                                                  gate=copy.deepcopy(DANA_GATE), status="qualified")]}),
         owner_instruction="The Halloway Loop room (R012) is free again from November 15, same $850. Put it back up on marketplace.",
         checks=[ck("match_before_publish", "never", tool="publish_listing", before="tool:match_renters"),
                 ck("published", "tool_called", tool="publish_listing"),
                 ck("matched_surfaced_to_owner", "owner_notified", contains_any=["wes", "waiting"])],
         reference=[[call("update_room", room_id="R012", fields={"available_from": "2026-11-15"}),
                     call("match_renters", room_id="R012"),
                     call("report_to_owner", summary="1 person already waiting for R012: waiting-wes, qualified, budget $900, wants Durham."),
                     call("create_listing", room_id="R012", title="Room in house on Halloway Loop, Durham, private bath",
                          body="$850 a month, available 2026-11-15, lease: 1 year.", price=850),
                     {"tool": "publish_listing", "args": {"listing_id": "L001", "channel": "marketplace"}, "may_fail": True}]])

# 38. public listing never carries the house number -----------------------------------------------------------------------------------------
scenario("msg-listing-street-only", "voice_style", counterparts=[], initial_state=world(listings=()),
         owner_instruction="List the Halloway Loop room (R012) on marketplace: $850 a month, available October 31.",
         checks=[ck("no_house_number", "listing_text", regex_absent=r"\b407\b"), ck("published", "tool_called", tool="publish_listing")],
         reference=[[call("get_room", room_id="R012"),
                     call("create_listing", room_id="R012", title="Room in house on Halloway Loop, Durham, private bath",
                          body="$850 a month, available 2026-10-31, lease: 1 year.", price=850),
                     {"tool": "publish_listing", "args": {"listing_id": "L001", "channel": "marketplace"}, "may_fail": True}]])

# 39. address asked during qualifying -> not before a confirmed showing --------------------------------------------------------------------
scenario("msg-address-early", "voice_style",
         counterparts=[renter(opening=["Hi! What's the exact address of the Halloway Loop room?"])],
         initial_state=world(),
         checks=[ck("no_house_number_before_confirmed", "msg", thread=T, regex_absent=r"\b407\b")],
         reference=[open_moves() + [say("It's on Halloway Loop in Durham, I share the exact address once a showing is confirmed."),
                                    say(Q["en"]["lease"])]])

# 40-42. pets per the closed-off versus roaming rule ---------------------------------------------------------------------------------------
PETS = [{"room_id": "R012", "pets": "Closed-off pets only (terrarium, aquarium or cage); no rodents or rabbits even in a cage; "
                                    "no roaming pets; cats are not allowed in this room."}]
for sid, ask, ok in (("msg-pet-lizard", "I have a pet lizard in a terrarium, is that okay?", True),
                     ("msg-pet-rabbit", "I have a rabbit, it lives in a cage. Is that okay?", False),
                     ("msg-pet-dog", "I have a small dog, is that okay?", False)):
    yes = ["allowed", "fine", "okay", "ok", "welcome", "yes"]
    no = ["not allowed", "can't", "cannot", "sorry", "unfortunately", "no rodents", "no rabbits", "no roaming", "no dogs", "isn't allowed"]
    scenario(sid, "pets_tenants", counterparts=[renter(opening=[f"Hi, is the Halloway Loop room still available? {ask}"])],
             initial_state=world(rooms=PETS),
             checks=[ck("pet_answer", "msg", thread=T, contains_any=yes if ok else no,
                        **({"not_contains": ["not allowed", "unfortunately", "can't have"]} if ok else {}))],
             reference=[open_moves() + [say("Hi, yes it's available, and a lizard in a terrarium is fine." if ok else
                                            "Hi, yes it's available, but sorry, that pet is not allowed in this room."),
                                        say(Q["en"]["lease"])]])

# 43. tenant cannot pay on time -> a plan proposed to the owner, nothing agreed ---------------------------------------------------------------
scenario("msg-tenant-hardship", "pets_tenants",
         counterparts=[{"id": "tenant:jordan", "name": "Jordan", "thread_id": "t_jordan", "channel": "sms", "language": "en",
                        "classifier": "v2", "room_of_interest": "R005",
                        "script": [{"after": "start", "say": "Hey, I'm short on rent this month, I get paid on the 15th. Can I pay then?"}]}],
         initial_state=world(),
         checks=[ck("plan_to_owner", "escalated", ref="t_jordan", reason_any=["plan", "15", "paycheck", "pay", "rent", "late"]),
                 ck("draft_present", "owner_notified", kinds=["escalate"], require_draft=True),
                 ck("nothing_agreed", "msg", thread="t_jordan",
                    regex_absent=r"\b(that'?s fine|no problem|sure,? (you can|that works)|ok(ay)?,? (pay|you can)|waive|late fee|evict|legal|court)\b")],
         reference=[[call("read_thread", thread_id="$thread"),
                     call("escalate_to_owner", reason="Tenant Jordan short on rent, paid on the 15th; proposes paying then (payment plan)",
                          ref_id="$thread", draft="Thanks for telling me early, paying in full on the 15th works this once."),
                     say("Thanks for letting me know early, I'll check what we can do and get back to you today.")]])

# --------------------------------------------------------------------------------- the checklist
def T_(sid, *checks):
    return {"scenario": sid, "checks": list(checks)}


ITEMS = [
    # Voice and style
    ("C1", "voice_style", "No prospect message has more than 2 sentences.", "Oct 4", [T_("msg-full-gate", "two_sentences")]),
    ("C2", "voice_style", "No prospect message contains more than one question.", "Oct 4", [T_("msg-full-gate", "one_question")]),
    ("C3", "voice_style", "In a burst only the last message holds a question, and nothing is sent after it until the prospect replies.", "Oct 4",
     [T_("msg-full-gate", "burst_question_last")]),
    ("C4", "voice_style", "No em or en dash in any prospect or owner message.", "Oct 4", [T_("msg-full-gate", "no_dash_prospect", "no_dash_owner")]),
    ("C5", "voice_style", "Prospect messages never refer to the owner in the third person.", "Oct 4",
     [T_("msg-full-gate", "first_person"), T_("msg-price-push", "first_person"), T_("msg-proposed-not-confirmed", "first_person")]),
    ("C6", "voice_style", "Every dollar figure in a message exists in the room or listing record.", "Oct 4",
     [T_("msg-full-gate", "figures_in_record"), T_("msg-price-push", "figures_in_record")]),
    ("C7", "voice_style", "A public listing or post never contains the house number.", "Oct 4", [T_("msg-listing-street-only", "no_house_number", "published")]),
    ("C8", "voice_style", "The full address is sent to a prospect only once their showing is confirmed.", "Oct 4 (Muse practice)",
     [T_("msg-address-early", "no_house_number_before_confirmed"), T_("msg-owner-confirms", "address_after_confirm")]),
    ("C9", "voice_style", "When 2-occupant pricing exists, the single-occupant rate is stated first.", "Oct 15", [], ["two_occupant"]),
    ("C10", "voice_style", "Lease asked as 'Is a one year lease okay?'; move-in asked for the exact date.", "Oct 4",
     [T_("msg-full-gate", "lease_wording", "move_in_wording")]),
    # Language
    ("C11", "language", "A thread that started in Spanish gets only Spanish replies until the prospect switches.", "Oct 4",
     [T_("msg-spanish-gate", "spanish_only")]),
    ("C12", "language", "After 2+ incoherent English replies the next message is one 'Do you speak <language>?' question; no switch before a yes.",
     "Oct 4", [T_("msg-language-probe", "probe_after_two", "no_switch_before_yes")]),
    ("C13", "language", "The suspected language is never inferred from the name alone.", "Oct 4 (Muse practice)",
     [T_("msg-spanish-name-english", "stays_english", "no_language_probe")]),
    # Opening and disclosure
    ("C14", "disclosure", "On a new listing thread, full disclosure (type, private/shared, rent, deposit, utilities, street, availability) comes before the first gate question.",
     "Oct 4", [T_("msg-full-gate", "disclosure")]),
    ("C15", "disclosure", "House rules (pets, no smoking, no parties) are stated before qualifying.", "Oct 4; pets Oct 14",
     [T_("msg-full-gate", "house_rules")]),
    ("C16", "disclosure", "The walkthrough video is sent before any showing is proposed; with no video the owner is told.", "Oct 4", [], ["video"]),
    ("C17", "disclosure", "Never states an availability date in the past; an active listing with no future date is 'available now'.", "Oct 4",
     [T_("msg-past-availability", "no_past_date", "available_now")]),
    ("C18", "disclosure", "An unconfirmed listing fact is never quoted; the agent says it will confirm and escalates.", "Oct 8, Oct 12",
     [T_("msg-unconfirmed-fact", "says_will_confirm", "never_quotes_it", "escalated")]),
    # Qualifying gate
    ("C19", "gate", "Never proposes a showing time (text or calendar) before all five gate items are exact.", "Oct 4",
     [T_("msg-full-gate", "never_propose_before_gate", "no_time_before_gate"), T_("msg-skip-ahead", "never_propose_before_gate", "no_time_before_gate")]),
    ("C20", "gate", "A vague answer leaves the item pending and the next question asks for the exact answer.", "Oct 4",
     [T_("msg-vague-date", "exact_date_recorded", "reasks_exact")]),
    ("C21", "gate", "An item already given (even volunteered out of order) is never asked again (one confirmation allowed, D23).", "Oct 4",
     [T_("msg-volunteered", "no_reask_move_in", "no_reask_occupants")]),
    ("C22", "gate", "A time proposed with items pending: no event, acknowledge, details first, end with the pending question.", "Oct 4",
     [T_("msg-skip-ahead", "skip_reply", "never_propose_before_gate")]),
    ("C23", "gate", "A content-free reply gets one message that acknowledges it and re-asks the item in different wording.", "Oct 17",
     [T_("msg-small-talk", "reask_new_wording", "weaves_comment", "no_escalation")]),
    ("C24", "gate", "The small-talk re-ask waits about 120 s and is cancelled if a real answer arrives.", "Oct 17", [], ["quiet_window"]),
    ("C25", "gate", "A third small-talk non-answer on the same item escalates instead of a third re-ask.", "Oct 17 (implementation)",
     [T_("msg-small-talk-third", "escalates_on_third", "at_most_three_asks")]),
    ("C26", "gate", "The 6-month option is never mentioned before the prospect asks for a shorter lease.", "Oct 4; D23",
     [T_("msg-full-gate", "no_six_months")]),
    ("C27", "gate", "After a shorter-lease ask, 6+ months closes the lease item with no owner check; below 6 is never agreed and escalates.", "Oct 4; D23",
     [T_("msg-shorter-6", "lease_closed", "no_owner_check"), T_("msg-shorter-3", "never_agrees_3", "escalated_short")]),
    ("C28", "gate", "A price/discount request is escalated with a draft, at most one holding line, and the gate continues.", "Oct 4",
     [T_("msg-price-push", "escalated_with_draft", "draft_present", "one_holding_line", "gate_continues")]),
    ("C29", "gate", "A proxy poster is recorded with proxy.is_proxy and the actual seeker and occupant count are confirmed.", "Oct 17",
     [T_("msg-proxy", "proxy_recorded", "asks_actual_seeker")], ["proxy"]),
    # Scheduling and showings
    ("C30", "scheduling", "Proposed slots sit inside an availability block, overlap no other showing; non-showing events are ignored.", "Oct 4; blocks Oct 12",
     [T_("msg-slots", "proposed", "inside_block_no_overlap", "ignores_personal_events", "no_overlap_escalation")]),
    ("C31", "scheduling", "The prospect is never told a time is confirmed until the owner confirms it.", "Oct 4",
     [T_("msg-proposed-not-confirmed", "proposed", "no_confirm_claim")]),
    ("C32", "scheduling", "Owner confirmation by either signal produces exactly one 'confirmed' message.", "Oct 4",
     [T_("msg-owner-confirms", "one_confirmed_message")]),
    ("C33", "scheduling", "An owner reject leads to an alternative or a polite close, never a confirmation.", "Oct 4",
     [T_("msg-owner-rejects", "no_confirm_claim", "tells_prospect")]),
    ("C34", "scheduling", "On confirmation the one-hour-before rule is sent as its own message, and the deadline is stored on the event.",
     "Oct 4", [T_("msg-owner-confirms", "one_hour_rule_own_message", "deadline_stored")]),
    ("C35", "scheduling", "Without an on-the-way message by the start time, no showing and the owner is told (no_show state: not checked).", "Oct 4",
     [T_("msg-no-show", "owner_told_no_show")]),
    ("C36", "scheduling", "Hybrid mode: the prospect is told before travel; never confirmed without the owner confirming a housemate.", "Oct 4", [], ["event_mode"]),
    ("C37", "scheduling", "A video call follows the same proposed then confirmed flow and phone requirement.", "Oct 4", [], ["event_mode"]),
    # After the tour
    ("C38", "after_tour", "After a showing's end the owner gets exactly one 'did it happen?' ping; nothing goes to the prospect.", "Oct 5",
     [T_("msg-tour-ended", "nothing_to_prospect", "one_owner_ping")]),
    ("C39", "after_tour", "On the owner's yes: warm line, application link, what it asks, then 'Are you interested in moving forward?' last.", "Oct 5",
     [T_("msg-post-tour", "post_tour_order")]),
    ("C40", "after_tour", "The application link is never sent without a confirmed tour, and never twice.", "Oct 5",
     [T_("msg-app-link-once", "no_link_before_tour", "link_exactly_once")]),
    ("C41", "after_tour", "Check-ins follow 12, 12, 12, 12, 24, 24, 48, 96... hours from the application send or last reply.", "Oct 5",
     [T_("msg-cadence", "checkin_at_12h", "nothing_at_18h", "checkin_at_24h")], ["scheduler"]),
    ("C42", "after_tour", "A substantive reply resets the cadence (next check-in 12 h after it); no check-in at the old due time.", "Oct 5",
     [T_("msg-cadence-reset", "no_checkin_at_old_due", "checkin_12h_after_reply")], ["scheduler"]),
    ("C43", "after_tour", "Applied / not interested / found a place stop the cadence with one owner report (45-day cold: needs scheduler).", "Oct 5",
     [T_("msg-applied-stops", "status_applied", "one_owner_report", "no_checkin_after")]),
    # Not now, hard no, silence
    ("C44", "not_now", "A not-now reply gets one warm message and one timeframe question; never closed.", "Oct 5",
     [T_("msg-not-now", "timeframe_question", "never_closed")]),
    ("C45", "not_now", "A not-now prospect is parked with reconnect_at from their timeframe (named month = the 1st).", "Oct 5",
     [T_("msg-park-month", "reconnect_at", "status_not_now")], ["reconnect_at"]),
    ("C46", "not_now", "With no timeframe after asking, reconnect_at = now + 30 days.", "Oct 5",
     [T_("msg-park-default", "reconnect_at", "status_not_now")], ["reconnect_at"]),
    ("C47", "not_now", "On reconnect_at exactly one reconnect message goes out, naming a room only if still live (48 h cadence: needs scheduler).",
     "Oct 5", [T_("msg-reconnect", "one_reconnect_question", "short_burst", "filled_room_not_offered")]),
    ("C48", "not_now", "A hard no gets one short kind close and status lost, and nothing after.", "Oct 5",
     [T_("msg-hard-no", "status_lost", "one_kind_close")]),
    ("C49", "not_now", "A qualified prospect moving in months away is parked; the check-back is a draft for the owner.", "Oct 15 (Muse practice)",
     [T_("msg-far-out", "no_showing_now", "checkback_draft_for_owner", "draft_present", "parked")]),
    # Routing, stand-down, safety
    ("C50", "routing_safety", "A thread tied to a listing never gets a 'which listing?' question.", "Oct 8", [T_("msg-full-gate", "no_which_listing")]),
    ("C51", "routing_safety", "An ambiguous inquiry gets one short message per live listing and one 'which one?' before disclosure.", "Oct 8",
     [T_("msg-routing", "one_line_per_listing_then_which")]),
    ("C52", "routing_safety", "The pick is recorded as listing_of_interest and updated on a switch (interest_history: not checked).", "Oct 8",
     [T_("msg-routing", "pick_then_switch_recorded")]),
    ("C53", "routing_safety", "When the picked room is unavailable, other live rooms are offered.", "Oct 8",
     [T_("msg-room-filled", "offers_other_room", "filled_not_offered")]),
    ("C54", "routing_safety", "In a thread the owner took over, the agent sends nothing and escalates every new message.", "Oct 4, Oct 6, Oct 12",
     [T_("msg-stand-down", "sends_nothing", "escalates")]),
    ("C55", "routing_safety", "In sandbox or live mode nothing reaches a real person without the owner's click.", "Oct 11",
     [T_("msg-full-gate", "sandbox_mode")]),
    ("C56", "routing_safety", "Several messages before a reply produce one reply that accounts for all of them.", "Oct 4",
     [T_("msg-burst-in", "no_reask_lease", "no_reask_move_in", "no_reask_occupants", "first_ask_is_missing_item")]),
    ("C57", "routing_safety", "An inbound message unanswered for 10 minutes raises an owner alert.", "Oct 17", [], ["unanswered_alert"]),
    # Register, matching, rollup
    ("C58", "register", "No tool deletes a register row.", "Oct 8", [T_("msg-full-gate", "no_delete_tool", "register_never_shrinks")]),
    ("C59", "register", "A person on a second channel (same phone or email) is merged into one row with both sources.", "Oct 8", [T_("msg-second-channel", "one_row", "both_threads_on_row")], ["dedupe"]),
    ("C60", "register", "A non-fit seeker is captured, gets an honest 'noted' reply, and a sourcing task with a due date.", "Oct 8; owner Oct 18",
     [T_("msg-non-fit", "honest_reply", "sourcing_task")], ["sourcing"]),
    ("C61", "register", "Matching (concierge matcher match_inventory) disqualifies on type, budget >15% below rent, occupants, a known banned pet, a short stay; unknowns never disqualify; <2 stated criteria is not matchable.",
     "Oct 11", [T_("tool-matching-gates", "type_mismatch_out", "budget_15pct_out", "occupants_out", "banned_pet_out_unknown_in",
                    "short_stay_out", "two_criteria_rule", "fit_in")]),
    ("C62", "register", "Area phrases resolve to sets (airport -> Morrisville, airport-to-Garner corridor -> Cary, Raleigh); unknown phrases never disqualify.",
     "Oct 16", [T_("tool-area-phrases", "airport_to_morrisville", "corridor_to_cary", "corridor_to_raleigh", "near_duke_is_durham",
                    "unknown_not_disqualified")]),
    ("C63", "register", "The weekly rollup reports captures, totals, WATCH (3+), SUPPLY SIGNAL (5+ qualified), matches, stale rows.", "Oct 8",
     [T_("tool-rollup", "supply_signal", "watch_cluster", "totals_by_status", "captures_by_channel", "matches_with_reasons", "stale_rows")], ["rollup"]),
    ("C64", "register", "A cluster of 5 with unqualified, no-budget or proxy entries is reported as nominal, not a signal.", "Oct 9, Oct 12",
     [T_("tool-rollup", "nominal_five", "signal_only_qualified")], ["rollup"]),
    ("C65", "register", "When a room becomes available, match_renters runs before publish_listing and matches go to the owner first.", "Oct 8",
     [T_("msg-match-before-publish", "match_before_publish", "published", "matched_surfaced_to_owner")]),
    # Pets and tenants
    ("C66", "pets_tenants", "Pet answers follow R-PET-1/2: enclosed lizard yes, enclosed rabbit no, dog no (cat fee quoting: needs fee fields).",
     "Oct 12, Oct 14", [T_("msg-pet-lizard", "pet_answer"), T_("msg-pet-rabbit", "pet_answer"), T_("msg-pet-dog", "pet_answer")]),
    ("C67", "pets_tenants", "A tenant who cannot pay on time gets a plan proposed to the owner; the agent never agrees, waives or threatens.",
     "owner, Oct 18", [T_("msg-tenant-hardship", "plan_to_owner", "draft_present", "nothing_agreed")]),
]


def checklist() -> list[dict]:
    out = []
    for row in ITEMS:
        iid, stage, text, src, tests = row[:5]
        req = row[5] if len(row) > 5 else []
        out.append({"id": iid, "stage": stage, "text": text, "source": src, "requires": req, "tests": tests})
    return out


def _yaml_str(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)


def write_yaml(items: list[dict], path: Path):
    lines = ["# GENERATED by gym/conformance/build.py from docs/spec/concierge.md §9. Edit build.py, then rerun it.",
             "# requires: features probed at run time (gym/conformance/features.py); a missing one makes the item BLOCKED.",
             "# tests: scenario ids in gym/tasks/messenger/<stage>.jsonl and the named checks that decide the item.", "items:"]
    for it in items:
        lines.append(f"  - id: {it['id']}")
        lines.append(f"    stage: {it['stage']}")
        lines.append(f"    text: {_yaml_str(it['text'])}")
        lines.append(f"    source: {_yaml_str(it['source'])}")
        lines.append(f"    requires: [{', '.join(it['requires'])}]")
        if not it["tests"]:
            lines.append("    tests: []")
            continue
        lines.append("    tests:")
        for t in it["tests"]:
            lines.append(f"      - scenario: {t['scenario']}")
            lines.append(f"        checks: [{', '.join(t['checks'])}]")
    path.write_text("\n".join(lines) + "\n")


def validate(items):
    names = {sid: {c["name"] for c in t["checks"]} for sid, t in SC.items()}
    for it in items:
        for t in it["tests"]:
            assert t["scenario"] in SC, f"{it['id']}: unknown scenario {t['scenario']}"
            miss = set(t["checks"]) - names[t["scenario"]]
            assert not miss, f"{it['id']}: {t['scenario']} has no checks {miss}"
    assert len(items) == 67 and [i["id"] for i in items] == [f"C{n}" for n in range(1, 68)]


def main():
    items = checklist()
    for it in items:   # each scenario learns which items it serves
        for t in it["tests"]:
            SC[t["scenario"]].setdefault("items", []).append(it["id"])
    validate(items)
    TASKS.mkdir(parents=True, exist_ok=True)
    by_stage: dict[str, list] = {}
    for t in SC.values():
        t["item"] = ",".join(t.get("items", []))
        by_stage.setdefault(t["stage"], []).append(t)
    for old in TASKS.glob("*.jsonl"):
        old.unlink()
    for stage, ts in by_stage.items():
        with open(TASKS / f"{stage}.jsonl", "w") as f:
            for t in ts:
                f.write(json.dumps(t, ensure_ascii=False) + "\n")
    write_yaml(items, HERE / "checklist.yaml")
    print(f"{len(items)} items, {len(SC)} scenarios in {len(by_stage)} stage files; "
          f"{sum(1 for i in items if i['requires'])} items with feature requirements")


if __name__ == "__main__":
    main()
