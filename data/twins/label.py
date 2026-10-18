"""Step 2: label every real thread.

  * each renter message: the reader schema (data/reader_schema.md), by Lightning with the reader's own
    prompt (reader/prompt.py) and reasoning on. --labeler reader uses the fine-tuned reader instead.
  * each owner message: what it does (acts below), and each thread: stage outcomes
    (qualified / showing / applied / ghosted / no) plus the final stage, by Lightning.
  * per renter message, a deterministic difficulty score and style features (length, emoji, casing).

Output: work/labeled.jsonl (real text, stays private) and the publishable statistics card
<published>/stats_card.json (real data: data/published/twins/[dev/]stats_card.json): aggregates only, any count below --min-cell shown as "<k".

Usage: data/twins/.venv/bin/python data/twins/label.py [--fixture] [--limit N] [--labeler lightning|reader]
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from collections import Counter
from datetime import datetime

import time

from common import (FIELDS, REPO, LocalLLM, Paths, common_args, is_cp, label_message, log_timing, pmap, read_jsonl,
                    setup, stratified_sample, to_context, write_json, write_jsonl)

OWNER_ACTS = ("greet", "confirm_available", "ask_lease", "ask_move_in", "ask_phone", "ask_occupants", "ask_reason",
              "give_price", "answer_question", "decline_discount", "offer_shorter_lease", "propose_showing",
              "confirm_showing", "send_application", "follow_up", "close", "other")
OUTCOMES = ("qualified", "showing", "applied", "ghosted", "no")
STAGES = ("inquiry", "qualifying", "qualified", "showing", "applied", "no", "ghosted")

THREAD_SYSTEM = f"""You annotate an anonymized chat between a small landlord (renting rooms) and a person asking about a room.
For EVERY landlord message, list what it does, using only these acts: {", ".join(OWNER_ACTS)}.
Then judge the thread outcome:
- qualified: the renter answered the qualifying questions (lease, move-in date, phone, reason, number of people) well enough to go on
- showing: a showing/visit was proposed AND accepted by the renter
- applied: the renter was sent or completed an application, or the landlord moved to signing
- ghosted: the renter stopped replying while the landlord was still waiting for an answer
- no: the renter said they are not interested / not now, or the landlord declined them
final_stage is one of: {", ".join(STAGES)} (the furthest point reached; "no" or "ghosted" when the thread ended that way).
Return JSON only: {{"owner_acts": {{"<message number>": [acts]}}, "outcome": {{"qualified": bool, "showing": bool, "applied": bool, "ghosted": bool, "no": bool}}, "final_stage": "..."}}"""

OPS_OWNER_ACTS = ("greet", "ask_details", "request_photo", "troubleshoot", "schedule_visit", "give_access_info",
                  "confirm", "acknowledge", "rent_or_payment_reminder", "utility_notice", "policy_statement",
                  "negotiate_price", "approve_or_pay", "decline", "follow_up", "close", "other")
TENANT_ACTS = ("report_problem", "send_photo", "answer_question", "ask_question", "propose_time", "confirm",
               "acknowledge", "payment_update", "ask_delay_or_partial", "housemate_issue", "move_out_or_renewal",
               "thanks", "complain", "other")
VENDOR_ACTS = ("introduce_or_reply_to_lead", "ask_details", "send_quote", "propose_time", "confirm_visit",
               "running_late", "cancel_or_reschedule", "decline_job", "send_photo_or_proof", "report_done",
               "request_payment", "acknowledge", "follow_up", "other")
OPS_TOPICS = ("plumbing", "electrical", "internet", "locks_keys_doors", "hvac", "appliance", "structure_roof_gutter",
              "pest", "landscaping", "cleaning_trash", "rent_payment", "utility_split", "house_rules_conflict",
              "move_out_deposit", "renewal", "packages_mail", "other")
OPS_OUTCOMES = ("resolved", "vendor_booked", "quote_only", "owner_visit", "escalated_or_legal", "unresolved", "ghosted")


def ops_system(category: str) -> str:
    who = "a tenant who lives in one of his houses" if category == "ops" else "a contractor or service company"
    cp_acts = TENANT_ACTS if category == "ops" else VENDOR_ACTS
    return f"""You annotate an anonymized chat between a small landlord (he rents rooms in shared houses) and {who}.
For EVERY landlord message list what it does, using only: {", ".join(OPS_OWNER_ACTS)}.
For EVERY {"tenant" if category == "ops" else "contractor"} message list what it does, using only: {", ".join(cp_acts)}.
topic: the main matter, one of {", ".join(OPS_TOPICS)}.
outcome (true/false each): {", ".join(OPS_OUTCOMES)}.
Return JSON only: {{"owner_acts": {{"<message number>": [acts]}}, "cp_acts": {{"<message number>": [acts]}}, "topic": "...", "outcome": {{"resolved": bool, ...}}}}"""


# ---- cheap rule-based cross-check (regex), compared with the reader (messages) and Lightning (thread outcomes)
RULES = {
    "phone": re.compile(r"\[PHONE|\b\d{3}[\s.\-]?\d{3}[\s.\-]?\d{4}\b"),
    "move_in": re.compile(r"\b(move|moving|mudar|mudo|mudanza|start|asap|right away|next (week|month)|end of (the )?month|"
                          r"january|february|march|april|june|july|august|september|october|november|december|"
                          r"enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre|"
                          r"\d{1,2}/\d{1,2})\b", re.I),
    "lease": re.compile(r"\b(lease|year|12 months?|contract|contrato|a[nñ]o|month[- ]to[- ]month|\d+ months?|\d+ meses)\b", re.I),
    "occupants": re.compile(r"\b(just me|only me|myself|my (girlfriend|boyfriend|wife|husband|son|daughter|kid|partner|friend)|"
                            r"two of us|couple|both of us|solo yo|mi (esposa|esposo|novia|novio|hijo|hija)|somos \d|dos personas)\b", re.I),
    "reason": re.compile(r"\b(job|work|working|school|student|college|university|relocat|transfer|nurse|lease (is )?end|"
                         r"trabajo|escuela|estudi)\b", re.I),
    "price_negotiation": re.compile(r"\b(discount|lower|cheaper|negotiat|best price|any (deal|wiggle)|less than|"
                                    r"descuento|m[aá]s barato|rebaja)\b", re.I),
    "scheduling": re.compile(r"\b(see (it|the room|the place)|tour|view(ing)?|visit|showing|come (by|see|over)|stop by|"
                             r"ver (el|la) (cuarto|casa|habitaci)|visitar)\b", re.I),
    "shorter_lease": re.compile(r"\b(month[- ]to[- ]month|short[- ]term|[1-9] months?|summer|sublet|temporar|"
                                r"mes a mes|[1-9] meses)\b", re.I),
    "hard_no": re.compile(r"\b(not interested|no longer (interested|need)|found (a|another|something)|"
                          r"going (with|to go with) (another|a different)|ya encontr|no me interesa)\b", re.I),
    "question": re.compile(r"\?"),
}
RULE_FIELDS = ("phone", "move_in", "lease", "occupants", "reason")
RULE_INTENTS = ("price_negotiation", "scheduling", "shorter_lease", "hard_no", "question")


def rule_labels(text: str) -> dict:
    return {k: bool(rx.search(text or "")) for k, rx in RULES.items()}


def reader_presence(lab: dict) -> dict:
    out = {f: lab[f]["status"] != "absent" for f in RULE_FIELDS}
    out.update({i: i in lab["intents"] for i in RULE_INTENTS})
    return out


def rule_outcomes(th: dict) -> dict:
    turns = th["turns"]
    txt_o = " ".join(t["text"] for t in turns if t["role"] == "owner")
    txt_c = " ".join(t["text"] for t in turns if t["role"] != "owner")
    return {"applied": bool(re.search(r"applica|apply|aplicaci|solicitud|background check", txt_o + " " + txt_c, re.I)),
            "showing": bool(re.search(r"\[ADDRESS\]|see you (at|then|tomorrow)|on my way|i'?m here|be there", txt_o + " " + txt_c, re.I)),
            "no": bool(RULES["hard_no"].search(txt_c) or re.search(r"\b(has been|was|got) (taken|rented)|no longer available", txt_o, re.I)),
            "ghosted": th["features"]["renter_went_silent"]}


def kappa(pairs: list[tuple[bool, bool]]):
    n = len(pairs)
    if not n:
        return None
    po = sum(a == b for a, b in pairs) / n
    pa, pb = sum(a for a, _ in pairs) / n, sum(b for _, b in pairs) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    return round((po - pe) / (1 - pe), 3) if pe < 1 else None


def agreement(threads: list[dict]) -> dict:
    """Reader vs rules per message key; Lightning vs rules per leasing thread outcome. Rates and kappa only."""
    msg = {}
    rows = [t for th in threads for t in th["turns"] if is_cp(t) and t.get("labels") and not t.get("media")]
    for k in RULE_FIELDS + RULE_INTENTS:
        pairs = [(reader_presence(t["labels"])[k], t["rule"][k]) for t in rows]
        msg[k] = {"n": len(pairs), "agree": round(sum(a == b for a, b in pairs) / len(pairs), 3) if pairs else None,
                  "kappa": kappa(pairs), "reader_only": sum(a and not b for a, b in pairs),
                  "rule_only": sum(b and not a for a, b in pairs)}
    lt = [th for th in threads if th.get("category", "leasing") == "leasing"]
    thr = {}
    for k in ("applied", "showing", "no", "ghosted"):
        pairs = [(th["outcome"][k], th["rule_outcome"][k]) for th in lt]
        thr[k] = {"n": len(pairs), "agree": round(sum(a == b for a, b in pairs) / len(pairs), 3) if pairs else None,
                  "kappa": kappa(pairs)}
    any_dis = sum(any(reader_presence(t["labels"])[k] != t["rule"][k] for k in RULE_FIELDS + RULE_INTENTS) for t in rows)
    return {"messages": len(rows), "messages_any_disagreement": any_dis,
            "message_disagreement_rate": round(any_dis / len(rows), 3) if rows else None,
            "per_key_reader_vs_rule": msg, "leasing_threads": len(lt), "thread_outcome_lightning_vs_rule": thr}


sys.path.insert(0, str(REPO / "gym"))
from rentus_env.counterparts import classify_question  # noqa: E402

ASK_ACT = {"lease": "ask_lease", "move_in": "ask_move_in", "phone": "ask_phone", "occupants": "ask_occupants",
           "reason": "ask_reason", "showing": "propose_showing"}

EMOJI = re.compile(r"[\U0001F300-\U0001FAFF☀-➿]")


def style_of(text: str) -> dict:
    words = len(text.split())
    letters = [c for c in text if c.isalpha()]
    return {"words": words,
            "length": "short" if words <= 5 else ("medium" if words <= 18 else "long"),
            "emoji": bool(EMOJI.search(text)),
            "casing": ("lower" if letters and all(not c.isupper() for c in letters) else
                       "upper" if letters and sum(c.isupper() for c in letters) / len(letters) > 0.7 else "normal"),
            "punctuation": "none" if not re.search(r"[.!?¿¡,]", text) else "normal"}


def difficulty(labels: dict, lang_switched: bool) -> tuple[int, str]:
    s = sum(labels[f]["status"] in ("vague", "exception") for f in FIELDS)
    s += sum(labels[f]["status"] == "no" for f in FIELDS)
    s += len([i for i in labels["intents"] if i in ("price_negotiation", "shorter_lease", "not_now", "hard_no")])
    s += int(len([f for f in FIELDS if labels[f]["status"] != "absent"]) >= 2)
    s += int(lang_switched)
    return s, ("easy" if s == 0 else "medium" if s <= 2 else "hard")


def empty_labels(lang: str) -> dict:
    lab = {f: ({"status": "absent", "date": None, "raw": None} if f == "move_in" else {"status": "absent", "value": None})
           for f in FIELDS}
    lab.update({"intents": [], "language": lang if lang in ("en", "es") else "en"})
    return lab


def label_renter_turn(llm_label: LocalLLM, th: dict, k: int) -> None:
    t = th["turns"][k]
    t["style"] = style_of(t["text"])
    t["rule"] = rule_labels(t["text"])
    if t.get("date_damaged"):
        t["unscorable"] = ["move_in"]  # eval-protocol 2.2: the anonymizer destroyed the date
    if t.get("media"):  # photo-only message: nothing to read
        t["labels"] = empty_labels(th["language"])
        return
    t["labels"] = label_message(llm_label, t["ts"][:10], to_context(th["turns"][:k]), t["text"], tag=th["thread_id"])


def label_thread(llm_op: LocalLLM, th: dict) -> dict:
    """Thread-level labels; renter messages are already labeled (label_renter_turn)."""
    turns = th["turns"]
    if th.get("category", "leasing") != "leasing":
        return label_ops_thread(llm_op, th)
    prev_lang = None
    for k, t in enumerate(turns):
        if not is_cp(t):
            continue
        lab = t["labels"]
        switched = prev_lang is not None and lab is not None and lab["language"] != prev_lang
        if lab:
            t["difficulty_score"], t["difficulty"] = difficulty(lab, switched)
            prev_lang = lab["language"]
    lines = [f"[{t['i']}] {'landlord' if t['role'] == 'owner' else 'renter'}: {t['text'][:400]}" for t in turns]
    out = llm_op.chat_json([{"role": "system", "content": THREAD_SYSTEM}, {"role": "user", "content": "\n".join(lines)}],
                           temperature=0.0, max_tokens=10000, cache_key="thread")
    acts = (out or {}).get("owner_acts") or {}
    for t in turns:
        if t["role"] == "owner":
            got = acts.get(str(t["i"])) or acts.get(t["i"]) or []
            # which item a question asks is decided by the Gym's own deterministic classifier (the same one the
            # scripted renters use), not by the model, which tends to shift asks by one message
            got = [x for x in got if x in OWNER_ACTS and not x.startswith("ask_") and x != "propose_showing"]
            asked = classify_question(t["text"], "v2")
            if asked in ASK_ACT:
                got.append(ASK_ACT[asked])
            t["acts"] = got or ["other"]
    oc = (out or {}).get("outcome") or {}
    th["outcome"] = {k: bool(oc.get(k)) for k in OUTCOMES}
    # deterministic ghosting signal: the renter never answered the owner's last message(s)
    last_renter = max(t["i"] for t in turns if is_cp(t))
    trailing_owner = [t for t in turns if t["i"] > last_renter]
    hard = bool(set((turns[last_renter].get("labels") or {}).get("intents", [])) & {"hard_no"})
    asked_last = bool(trailing_owner) and "?" in trailing_owner[-1]["text"]
    th["features"] = {"trailing_owner_turns": len(trailing_owner), "renter_went_silent": asked_last and not hard,
                      "renter_turns": sum(is_cp(t) for t in turns),
                      "owner_turns": sum(t["role"] == "owner" for t in turns)}
    if th["features"]["renter_went_silent"]:
        th["outcome"]["ghosted"] = True
    fs = (out or {}).get("final_stage")
    th["final_stage"] = fs if fs in STAGES else ("ghosted" if th["outcome"]["ghosted"] else "inquiry")
    th["labeled"] = out is not None and all(t.get("labels") for t in turns if is_cp(t))
    th["rule_outcome"] = rule_outcomes(th)
    return th


def label_ops_thread(llm_op: LocalLLM, th: dict) -> dict:
    """Tenant-ops and contractor episodes: owner acts, counterpart acts, topic and outcome (Lightning, reasoning on)."""
    turns = th["turns"]
    cp_name = "tenant" if th["category"] == "ops" else "contractor"
    cp_vocab = TENANT_ACTS if th["category"] == "ops" else VENDOR_ACTS
    lines = [f"[{t['i']}] {'landlord' if t['role'] == 'owner' else cp_name}: {t['text'][:400]}" for t in turns]
    out = llm_op.chat_json([{"role": "system", "content": ops_system(th["category"])},
                            {"role": "user", "content": "\n".join(lines)}],
                           temperature=0.0, max_tokens=10000, cache_key="ops-thread")
    oa, ca = (out or {}).get("owner_acts") or {}, (out or {}).get("cp_acts") or {}
    for t in turns:
        got = (oa if t["role"] == "owner" else ca).get(str(t["i"])) or []
        vocab = OPS_OWNER_ACTS if t["role"] == "owner" else cp_vocab
        t["acts"] = [x for x in got if x in vocab] or (["send_photo" if th["category"] == "ops" else "send_photo_or_proof"]
                                                       if t.get("media") else ["other"])
        if is_cp(t) and t.get("labels"):
            t["difficulty_score"], t["difficulty"] = difficulty(t["labels"], False)
    topic = (out or {}).get("topic")
    th["topic"] = topic if topic in OPS_TOPICS else "other"
    oc = (out or {}).get("outcome") or {}
    th["outcome"] = {k: bool(oc.get(k)) for k in OPS_OUTCOMES}
    last_cp = max(t["i"] for t in turns if is_cp(t))
    trailing = [t for t in turns if t["i"] > last_cp]
    th["features"] = {"trailing_owner_turns": len(trailing),
                      "renter_went_silent": bool(trailing) and "?" in trailing[-1]["text"],
                      "renter_turns": sum(is_cp(t) for t in turns), "owner_turns": sum(not is_cp(t) for t in turns)}
    if th["features"]["renter_went_silent"]:
        th["outcome"]["ghosted"] = True
    th["final_stage"] = next((k for k in ("resolved", "vendor_booked", "owner_visit", "quote_only", "escalated_or_legal",
                                          "ghosted") if th["outcome"][k]), "unresolved")
    th["labeled"] = out is not None and all(t.get("labels") for t in turns if is_cp(t))
    th["rule_outcome"] = None
    return th


# --------------------------------------------------------------------------------------------- stats card
def pct(xs, q):
    xs = sorted(xs)
    if not xs:
        return None
    k = (len(xs) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return round(xs[lo] + (xs[hi] - xs[lo]) * (k - lo), 1)


def stats_card(threads: list[dict], k: int, labeler: str) -> dict:
    def cell(n):
        return n if n >= k else f"<{k}"

    def cnt(c: Counter):
        return {key: cell(v) for key, v in sorted(c.items(), key=lambda x: (-x[1], str(x[0])))}

    lease_threads = [th for th in threads if th.get("category", "leasing") == "leasing"]
    rmsgs = [t for th in lease_threads for t in th["turns"] if is_cp(t) and t.get("labels") and not t.get("media")]
    omsgs = [t for th in threads for t in th["turns"] if t["role"] == "owner"]
    delays = []
    for th in threads:
        for a, b in zip(th["turns"], th["turns"][1:]):
            if a["role"] == "owner" and is_cp(b):
                delays.append((datetime.fromisoformat(b["ts"]) - datetime.fromisoformat(a["ts"])).total_seconds() / 60)
    n = len(threads)
    return {
        "what": "Aggregate statistics of the owner's real rental-inquiry threads that the twins mirror. "
                "Counts only; no text, names, dates or identifiers. Cells below the minimum are shown as '<k'.",
        "min_cell": k, "labeler": labeler,
        "threads": cell(n), "renter_messages": cell(len(rmsgs)), "owner_messages": cell(len(omsgs)),
        "by_channel": cnt(Counter(th["channel"] for th in threads)),
        "thread_language": cnt(Counter("mixed" if th["language_switch"] else th["language"] for th in threads)),
        "turns_per_thread": {"p25": pct([len(th["turns"]) for th in threads], .25),
                             "median": pct([len(th["turns"]) for th in threads], .5),
                             "p75": pct([len(th["turns"]) for th in threads], .75)} if n >= k else f"<{k} threads",
        "renter_reply_minutes": {"median": pct(delays, .5), "p75": pct(delays, .75)} if len(delays) >= k else f"<{k}",
        "field_status": {f: cnt(Counter(t["labels"][f]["status"] for t in rmsgs if t["labels"][f]["status"] != "absent"))
                         for f in FIELDS},
        "intents": cnt(Counter(i for t in rmsgs for i in t["labels"]["intents"])),
        "renter_message_language": cnt(Counter(t["labels"]["language"] for t in rmsgs)),
        "renter_message_length": cnt(Counter(t["style"]["length"] for t in rmsgs)),
        "difficulty": cnt(Counter(t["difficulty"] for t in rmsgs if t.get("difficulty"))),
        "owner_acts": cnt(Counter(x for t in omsgs for x in t.get("acts", []))),
        "by_category": cnt(Counter(th.get("category", "leasing") for th in threads)),
        "outcomes_leasing": {o: {"threads": cell(sum(th["outcome"][o] for th in lease_threads)),
                                 "rate": round(sum(th["outcome"][o] for th in lease_threads) / len(lease_threads), 2)
                                 if len(lease_threads) >= k else None} for o in OUTCOMES},
        "final_stage": cnt(Counter(th["final_stage"] for th in threads)),
        "ops_topics": cnt(Counter(th.get("topic") for th in threads if th.get("category") == "ops")),
        "contractor_topics": cnt(Counter(th.get("topic") for th in threads if th.get("category") == "contractor")),
        "ops_outcomes": cnt(Counter(o for th in threads if th.get("category") in ("ops", "contractor")
                                    for o, v in th["outcome"].items() if v)),
        "media_only_messages": cell(sum(bool(t.get("media")) for th in threads for t in th["turns"])),
        "move_in_unscorable_messages": cell(sum(bool(t.get("unscorable")) for th in threads for t in th["turns"])),
        "unlabeled_threads": sum(not th.get("labeled") for th in threads),
    }


def main():
    ap = common_args(argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter))
    ap.add_argument("--labeler", choices=["lightning", "reader"], default="lightning")
    ap.add_argument("--label-reasoning", choices=["on", "off"], default="on",
                    help="Lightning reasoning for message labels. off is ~30x faster but on the fixture agreed with "
                         "reasoning-on labels on all five fields for 8/42 messages (on vs on: 36/42)")
    ap.add_argument("--min-cell", type=int, default=None, help="suppress stats cells below this (default 5; 1 on --fixture)")
    a = ap.parse_args()
    setup(a)
    P = Paths.make(a.fixture, a.split)
    threads = read_jsonl(P.work / "threads.jsonl")[: a.limit]
    # strata before labels exist: channel x language x a cheap outcome proxy (ended on an unanswered owner
    # question = likely ghosted; short / long thread)
    threads = stratified_sample(threads, a.sample, lambda t: (
        t["channel"], "mixed" if t["language_switch"] else t["language"],
        "owner_last" if t["turns"][-1]["role"] == "owner" and "?" in t["turns"][-1]["text"] else "renter_last",
        "short" if len(t["turns"]) <= 6 else "long"))
    if not threads:
        sys.exit("no threads: run ingest.py first")
    t0 = time.time()
    op = LocalLLM("operator", P.cache)  # thread outcomes and owner acts: one call per thread
    lab = (LocalLLM("operator", P.cache, reasoning=a.label_reasoning == "on") if a.labeler == "lightning"
           else LocalLLM("reader", P.cache))
    print(f"labeling {len(threads)} threads, {sum(len(t['turns']) for t in threads)} messages")
    jobs = [(th, k) for th in threads for k, t in enumerate(th["turns"]) if is_cp(t)]
    pmap(lambda j: label_renter_turn(lab, *j), jobs, a.workers)  # every message in parallel, then each thread
    out = pmap(lambda th: label_thread(op, th), threads, a.workers)
    op.require_healthy("label")
    lab.require_healthy("label")
    write_jsonl(P.work / "labeled.jsonl", out)
    k = a.min_cell if a.min_cell is not None else (1 if a.fixture else 5)
    card = stats_card(out, k, a.labeler)
    card["models"] = {"labeler": lab.model, "operator": op.model, "label_reasoning": lab.reasoning}
    agr = agreement(out)
    card["label_agreement"] = agr
    write_json(P.work / "label_agreement.json", agr)
    card["split"] = P.split
    log_timing(P.work, "label", len(out), time.time() - t0, [lab, op])
    print("model calls:", op.stats(), lab.stats() if lab is not op else "", file=sys.stderr)
    write_json(P.published / "stats_card.json", card)
    print(json.dumps({x: card[x] for x in ("threads", "renter_messages", "by_category", "unlabeled_threads")}, indent=1))
    print(json.dumps(agr, indent=1))


if __name__ == "__main__":
    main()
