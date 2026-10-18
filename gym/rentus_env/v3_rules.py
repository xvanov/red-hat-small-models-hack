"""Protocol Amendment 1 scoring rules for v3 twin tasks (docs/eval-protocol.md, "Amendment 1").

`apply_v3_rules(task)` returns a rewritten copy of a v3 leasing twin task. It is applied by both
`RolloutSession` (counterpart script) and `verify` (checks), is deterministic and idempotent, and leaves
every non-v3 task untouched, so v1/v2 scores are unchanged.

What it changes, and the review finding behind each change:
  script  Renter lines are keyed to the RENTER's own labelled items, not to the questions the owner
          happened to ask historically (scorer-privacy #3). A line that carries a non-gate behaviour
          (hard no, not now, price push, question, small talk) is a `"when_asked": "next"` line: it answers
          the next operator message whatever it asks, at the latest at its historical reply position.
  checks  - "showing proposed" from the historical outcome is replaced by a rule check (R-SHOW-1, R-PHIL-2):
            gate complete in the gold facts and move-in within SHOWING_WINDOW_DAYS -> a showing must be
            proposed; further out is R-PARK-6, whose threshold is open (concierge.md §8 q8), so unscored.
          - "does not spam a silent renter" (historical owner count + 2) is replaced by R-STYLE-3 /
            R-GHOST-1: at most one follow-up question after an unanswered question (`followups`).
          - every task where asking is allowed must ask at least one missing gate item (`asks_gate_item`),
            so a single greeting cannot pass a ghosted task (scorer-privacy #4).
          - every gate item the renter never gave must not be recorded as answered (`gate_not_invented`,
            scorer-privacy #5, R-GATE-1).
          - the price escalation needs price words in its reason (R-ESC-1, scorer-privacy #4).
          - "does not re-ask" counts only DELIVERED messages (`scope: sent`, G2; scorer-privacy #16).
          - "offers the 6-month floor" is dropped when the send_message guard could never see the renter's
            shorter-lease ask (the guard would refuse every config's 6-month message; scorer-privacy #8).
          - checks a tool guard makes impossible to fail are tagged `guard_enforced` and reported apart.
"""
from __future__ import annotations

import copy
from datetime import date

from .counterparts import classify_question

RULES_VERSION = "amendment-1"
GATE = ("lease", "move_in", "phone", "reason", "occupants")
BEHAVIOR_INTENTS = ("hard_no", "not_now", "price_negotiation", "question", "small_talk")
SHOWING_WINDOW_DAYS = 45
PRICE_WORDS = ["price", "discount", "rent", "cheaper", "lower", "deal", "precio", "descuento", "renta", "$"]

# send_message refuses these before delivery (tools/rentus_tools/impl/inbox.py), so a check on SENT text
# for the same rule cannot fail. Tagged, and reported separately as "guard-enforced".
GUARD_STYLE_RULES = {"language", "first_person", "max_two_sentences", "one_question", "no_long_dash"}


def _items_of(gold: dict) -> list[str]:
    out = [f for f in GATE if (gold.get(f) or {}).get("status") not in (None, "absent")]
    if "scheduling" in (gold.get("intents") or []):
        out.append("showing")
    return out


def _renter_blocks(turns: list[dict]) -> tuple[list[str], list[dict]]:
    """(opening texts, reply blocks). Consecutive renter turns merge; owner/operator turns split blocks."""
    opening, blocks, cur, seen_op = [], [], None, False
    for t in turns:
        if t.get("role") in ("operator", "owner"):
            seen_op, cur = True, None
            continue
        if not t.get("gold"):
            continue
        if not seen_op:
            opening.append(t["text"])
            continue
        if cur is None:
            cur = {"texts": [], "items": [], "intents": [], "turn": t["i"]}
            blocks.append(cur)
        cur["texts"].append(t["text"])
        cur["items"] += [x for x in _items_of(t["gold"]) if x not in cur["items"]]
        cur["intents"] += [x for x in t["gold"].get("intents") or [] if x not in cur["intents"]]
    return opening, blocks


def rule_script(cp: dict) -> list[dict]:
    ts = cp.get("twin_script") or {}
    opening, blocks = _renter_blocks(ts.get("turns") or [])
    keep_reuse = [l for l in cp.get("script") or [] if l.get("reuse")]
    if not opening:
        opening = [l["say"] for l in cp.get("script") or [] if l.get("after") == "start"]
    lines = [{"after": "start", "say": " ".join(opening)}] if opening else []
    for j, b in enumerate(blocks, start=1):
        say = " ".join(b["texts"])
        beh = [i for i in b["intents"] if i in BEHAVIOR_INTENTS]
        if beh:
            lines.append({"when_asked": "next", "at_reply": j, "say": say, "behavior": beh})
        elif b["items"]:
            lines.append({"when_asked": b["items"][0] if len(b["items"]) == 1 else b["items"], "say": say})
        else:
            lines.append({"when_asked": "any", "say": say})
    return lines + keep_reuse


def _days_between(a: str, b: str) -> int | None:
    try:
        return (date.fromisoformat(b[:10]) - date.fromisoformat(a[:10])).days
    except (TypeError, ValueError):
        return None


def _shorter_visible(text: str) -> bool:
    """Would send_message's lease-floor guard see this renter line as a shorter-lease ask?"""
    try:
        from rentus_tools.impl.inbox import SHORTER_ASK, read_reply_fallback
    except Exception:  # noqa: BLE001 - tools not importable: keep the check (conservative)
        return True
    return bool(SHORTER_ASK.search(text) or "shorter_lease" in read_reply_fallback(text).get("intents", []))


def rule_checks(task: dict, cp: dict) -> tuple[list[dict], list[str]]:
    tid = cp.get("thread_id")
    ts = cp.get("twin_script") or {}
    gold = ts.get("gold_facts") or {}
    sub = (task.get("subcategory") or "").removeprefix("twin_")
    notes, out = [], []
    turns = ts.get("turns") or []
    for c in task.get("checks") or []:
        name = c.get("name") or ""
        if name == "showing proposed" or name.startswith("does not spam"):
            notes.append(f"dropped historical check {name!r}")
            continue
        c = dict(c)
        if c.get("type") == "never" and "asked" in c:
            c["scope"] = "sent"
        if c.get("type") == "escalated" and name == "price ask escalated" and not c.get("reason_any"):
            c["reason_any"] = PRICE_WORDS
        if name.startswith("offers the 6-month floor"):
            asks = [t["text"] for t in turns if (t.get("gold") or {}).get("intents") and "shorter_lease" in t["gold"]["intents"]]
            if asks and not any(_shorter_visible(x) for x in asks):
                notes.append("dropped 'offers the 6-month floor': the lease-floor guard cannot see the renter's ask")
                continue
        if c.get("type") == "style" and c.get("rule") in GUARD_STYLE_RULES and c.get("scope") == "sent":
            c["guard_enforced"] = True
        out.append(c)
    st = lambda f: (gold.get(f) or {}).get("status")  # noqa: E731
    never_given = [f for f in GATE if st(f) not in ("answered", "exception", "no")]
    if never_given:
        out.append({"type": "gate_not_invented", "thread": tid, "items": never_given,
                    "name": "no invented gate values", "rule": "R-GATE-1"})
    volunteered = set()   # exact items the renter gave before the operator spoke: nothing to ask there
    for t in turns:
        if t.get("role") in ("operator", "owner"):
            break
        g = t.get("gold") or {}
        volunteered |= {f for f in GATE if (g.get(f) or {}).get("status") in ("answered", "exception")}
    to_ask = [f for f in GATE if f not in volunteered]
    if sub not in ("hard_no", "not_now") and to_ask:
        out.append({"type": "asks_gate_item", "thread": tid, "items": to_ask,
                    "name": "asks a missing gate item", "rule": "R-GATE-2"})
    if sub not in ("hard_no", "not_now"):
        complete = all((gold.get(f) or {}).get("status") in ("answered", "exception") for f in GATE)
        mi = (gold.get("move_in") or {}).get("date")
        now = ((task.get("initial_state") or {}).get("clock") or {}).get("now") or ""
        days = _days_between(now, mi) if mi else None
        if complete and days is not None and days <= SHOWING_WINDOW_DAYS:
            out.append({"type": "tool_called", "tool": "propose_showing", "ok": True, "name": "showing proposed (rule)",
                        "rule": "R-SHOW-1"})
        elif complete:
            notes.append("gate complete but move-in beyond the showing window: R-PARK-6 threshold open, unscored")
    out.append({"type": "followups", "thread": tid, "max_unanswered_questions": 2,
                "name": "at most one follow-up after an unanswered question", "rule": "R-STYLE-3/R-GHOST-1"})
    return out, notes


def apply_v3_rules(task: dict) -> dict:
    if task.get("version") != "v3" or task.get("rules") == RULES_VERSION or task.get("category") != "leasing":
        return task
    cps = task.get("counterparts") or []
    if len(cps) != 1 or not (cps[0].get("twin_script") or {}).get("turns"):
        return task
    t = copy.deepcopy(task)
    cp = t["counterparts"][0]
    cp["script"] = rule_script(cp)
    t["checks"], t["rules_notes"] = rule_checks(t, cp)
    t["rules"] = RULES_VERSION
    return t


# ------------------------------------------------------------------------------ check helpers
def asked_items(trace: list[dict], thread: str, sent_only: bool = True) -> list[str]:
    out = []
    for e in trace:
        if e.get("tool") != "send_message" or not isinstance(e.get("args"), dict):
            continue
        if sent_only and not e.get("ok"):
            continue
        if e["args"].get("thread_id") != thread:
            continue
        item = classify_question(str(e["args"].get("text", "")), "v2")
        if item:
            out.append(item)
    return out

