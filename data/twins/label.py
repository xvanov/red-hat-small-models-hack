"""Step 2: label every real thread.

  * each renter message: the reader schema (data/reader_schema.md), by Lightning with the reader's own
    prompt (reader/prompt.py) and reasoning on. --labeler reader uses the fine-tuned reader instead.
  * each owner message: what it does (acts below), and each thread: stage outcomes
    (qualified / showing / applied / ghosted / no) plus the final stage, by Lightning.
  * per renter message, a deterministic difficulty score and style features (length, emoji, casing).

Output: work/labeled.jsonl (real text, stays private) and the publishable statistics card
<published>/stats_card.json: aggregates only, any count below --min-cell shown as "<k".

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

from common import (FIELDS, REPO, LocalLLM, Paths, common_args, label_message, log_timing, pmap, read_jsonl, setup,
                    stratified_sample, to_context, write_json, write_jsonl)

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


def label_renter_turn(llm_label: LocalLLM, th: dict, k: int) -> None:
    t = th["turns"][k]
    t["labels"] = label_message(llm_label, t["ts"][:10], to_context(th["turns"][:k]), t["text"], tag=th["thread_id"])
    t["style"] = style_of(t["text"])


def label_thread(llm_op: LocalLLM, th: dict) -> dict:
    """Thread-level labels; renter messages are already labeled (label_renter_turn)."""
    turns = th["turns"]
    prev_lang = None
    for k, t in enumerate(turns):
        if t["role"] != "renter":
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
    last_renter = max(t["i"] for t in turns if t["role"] == "renter")
    trailing_owner = [t for t in turns if t["i"] > last_renter]
    hard = bool(set((turns[last_renter].get("labels") or {}).get("intents", [])) & {"hard_no"})
    asked_last = bool(trailing_owner) and "?" in trailing_owner[-1]["text"]
    th["features"] = {"trailing_owner_turns": len(trailing_owner), "renter_went_silent": asked_last and not hard,
                      "renter_turns": sum(t["role"] == "renter" for t in turns),
                      "owner_turns": sum(t["role"] == "owner" for t in turns)}
    if th["features"]["renter_went_silent"]:
        th["outcome"]["ghosted"] = True
    fs = (out or {}).get("final_stage")
    th["final_stage"] = fs if fs in STAGES else ("ghosted" if th["outcome"]["ghosted"] else "inquiry")
    th["labeled"] = out is not None and all(t.get("labels") for t in turns if t["role"] == "renter")
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

    rmsgs = [t for th in threads for t in th["turns"] if t["role"] == "renter" and t.get("labels")]
    omsgs = [t for th in threads for t in th["turns"] if t["role"] == "owner"]
    delays = []
    for th in threads:
        for a, b in zip(th["turns"], th["turns"][1:]):
            if a["role"] == "owner" and b["role"] == "renter":
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
        "outcomes": {o: {"threads": cell(sum(th["outcome"][o] for th in threads)),
                         "rate": round(sum(th["outcome"][o] for th in threads) / n, 2) if n >= k else None}
                     for o in OUTCOMES},
        "final_stage": cnt(Counter(th["final_stage"] for th in threads)),
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
    P = Paths.make(a.fixture)
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
    op = LocalLLM("operator", P.work / "cache")  # thread outcomes and owner acts: one call per thread
    lab = (LocalLLM("operator", P.work / "cache", reasoning=a.label_reasoning == "on") if a.labeler == "lightning"
           else LocalLLM("reader", P.work / "cache"))
    print(f"labeling {len(threads)} threads, {sum(len(t['turns']) for t in threads)} messages")
    jobs = [(th, k) for th in threads for k, t in enumerate(th["turns"]) if t["role"] == "renter"]
    pmap(lambda j: label_renter_turn(lab, *j), jobs, a.workers)  # every message in parallel, then each thread
    out = pmap(lambda th: label_thread(op, th), threads, a.workers)
    op.require_healthy("label")
    lab.require_healthy("label")
    write_jsonl(P.work / "labeled.jsonl", out)
    k = a.min_cell if a.min_cell is not None else (1 if a.fixture else 5)
    card = stats_card(out, k, a.labeler)
    card["models"] = {"labeler": lab.model, "operator": op.model, "label_reasoning": lab.reasoning}
    log_timing(P.work, "label", len(out), time.time() - t0, [lab, op])
    print("model calls:", op.stats(), lab.stats() if lab is not op else "", file=sys.stderr)
    write_json(P.published / "stats_card.json", card)
    print(json.dumps({x: card[x] for x in ("threads", "renter_messages", "outcomes", "unlabeled_threads")}, indent=1))


if __name__ == "__main__":
    main()
