"""Conformance check types. Standard types (state, never, style, tool_called, escalated, budget, message)
are delegated to gym/rentus_env/verify.py unchanged; the types below exist only for this suite.

Every message check reads what was actually SENT (a send_message that succeeded), because conformance is
about what reaches the prospect: a draft the tools refused never reached anyone.

Phase filters (any message/owner check): "phase": k | "phases": [k, ...] | "before_phase": k | "from_phase": k.
Phase 0 is the first operator run; a scenario's `phases[k]` starts run k (owner signal, clock jump, new
renter message). The runner records where each phase starts in the trace.

Custom types
  burst_question_last      {thread}  in every burst (operator messages with no renter message in between)
                           only the last message holds a question; nothing is sent after an unanswered question
  disclosure_before_questions {thread, facts: {label: [alternatives]}}  every fact group appears in the
                           messages sent before the first gate question
  reply_to_line            {thread, after_renter_contains | phase, last_asks?, asks_any?, contains_any?,
                           contains_all?, not_contains?, regex_absent?, min_messages?, max_messages?,
                           no_question?, one_question_total?}  the operator's response to one renter message
  reask_differs            {thread, item}  the item was asked at least twice and the re-ask is new wording
  msg                      {thread, contains_any?, contains_all?, not_contains?, regex_present?, regex_absent?}
  count_messages           {thread, contains_any | regex, eq? | min? | max?}  messages matching, counted
  message_order            {thread, sequence: [[alts], ...], last_contains?}  groups first appear in this order
  separate_messages        {thread, a: [alts], b: [alts]}  both appear, never in the same message
  no_send                  {thread}  nothing sent to the thread (in the filtered phases)
  owner_notified           {contains_any?, min?, max?, kinds?: [escalate, report]}  owner escalations/reports
  owner_text               {rule: no_long_dash}  every escalation reason/draft and owner report
  no_time_offer_before_gate {thread}  no clock time offered while that renter's gate was incomplete
  listing_text             {regex_absent}  title/body of every create_listing / update_listing attempt
  event_ok                 {thread, start?, end?}  each proposed event sits inside showing hours / the
                           given window and overlaps no other showing for the room
  register_key             {thread, key, equals?, normalize?, exists?}  a key anywhere in the renter's row
                           (or a demand register row) e.g. reconnect_at, proxy, sourcing
  register_rows            {gte_initial?: true, count_eq?}  register size checks
  no_delete_tool           {}  no tool can delete a register row
  probe                    {step, path, equals? | includes? | excludes? | above?: [a, b] | exists?}
                           for tool-probe scenarios: a value in one step's result envelope
"""
from __future__ import annotations

import difflib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
GYM = HERE.parent
if str(GYM) not in sys.path:
    sys.path.insert(0, str(GYM))

import importlib  # noqa: E402
V = importlib.import_module("rentus_env.verify")
from rentus_env.counterparts import classify_question  # noqa: E402

GATE = ("lease", "move_in", "phone", "reason", "occupants")
CUSTOM = ("burst_question_last", "disclosure_before_questions", "reply_to_line", "reask_differs", "msg",
          "count_messages", "message_order", "separate_messages", "no_send", "owner_notified", "owner_text",
          "no_time_offer_before_gate", "listing_text", "event_ok", "register_key", "register_rows",
          "no_delete_tool", "probe", "figures_in", "no_confirm_claim", "language_before")

TIME_OFFER = re.compile(r"\b\d{1,2}(:\d{2})?\s?(am|pm|a\.m\.|p\.m\.)\b|\b\d{1,2}:\d{2}\b|\b(noon|mediod[ií]a)\b", re.I)


# ----------------------------------------------------------------------------------- helpers
def phase_of(ctx: dict, i: int) -> int:
    k = 0
    for n, p in enumerate(ctx.get("phases") or []):
        if i >= p["start"]:
            k = n
    return k


def _phase_ok(c: dict, k: int) -> bool:
    if "phase" in c:
        return k == c["phase"]
    if "phases" in c:
        return k in c["phases"]
    if "before_phase" in c:
        return k < c["before_phase"]
    if "from_phase" in c:
        return k >= c["from_phase"]
    return True


def sent(ctx: dict, c: dict, thread: str | None = None) -> list[dict]:
    """Successful send_message entries (filtered by thread and phase), in order."""
    thread = thread if thread is not None else c.get("thread")
    out = []
    for e in ctx["trace"]:
        if e["tool"] != "send_message" or not e.get("ok") or not isinstance(e.get("args"), dict):
            continue
        if thread and e["args"].get("thread_id") != thread:
            continue
        if not _phase_ok(c, phase_of(ctx, e["i"])):
            continue
        out.append(e)
    return out


def text(e: dict) -> str:
    return str((e.get("args") or {}).get("text", ""))


def _low(s: str) -> str:
    return s.lower().replace("’", "'")


def _any(hay: str, alts) -> bool:
    return any(_low(a) in _low(hay) for a in alts)


def asks(t: str) -> str | None:
    return classify_question(t, "v2")


def _short(s: str, n: int = 80) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def _renter_row(state: dict, thread: str) -> dict | None:
    for r in state.get("register") or []:
        if thread in (r.get("thread_ids") or []) or r.get("thread_id") == thread or r.get("renter_id") == thread:
            return r
    return None


def _find_key(doc: Any, key: str, depth: int = 0):
    if depth > 4:
        return None
    if isinstance(doc, dict):
        if key in doc:
            return doc[key]
        for v in doc.values():
            got = _find_key(v, key, depth + 1)
            if got is not None:
                return got
    return None


def _owner_entries(ctx: dict, c: dict) -> list[tuple[str, str]]:
    kinds = c.get("kinds") or ["escalate", "report"]
    out = []
    for e in ctx["trace"]:
        if not e.get("ok") or not isinstance(e.get("args"), dict) or not _phase_ok(c, phase_of(ctx, e["i"])):
            continue
        a = e["args"]
        if e["tool"] == "escalate_to_owner" and "escalate" in kinds:
            if c.get("require_draft") and not str(a.get("draft") or "").strip():
                continue
            out.append(("escalate", f"{a.get('reason', '')} {a.get('draft') or ''}"))
        elif e["tool"] == "report_to_owner" and "report" in kinds:
            out.append(("report", str(a.get("summary", ""))))
        elif e["tool"].startswith("notify_owner") and "report" in kinds:
            out.append(("report", " ".join(str(v) for v in a.values())))
    return out


# ------------------------------------------------------------------------------- check types
def c_burst_question_last(c, ctx):
    msgs = sent(ctx, c)
    if not msgs:
        return False, "no messages"
    renter_phase_starts = {p["start"] for p in ctx.get("phases") or [] if p.get("renter_msg")}
    pending = None
    for e in msgs:
        if pending is not None and not any(pending < s <= e["i"] for s in renter_phase_starts):
            return False, f"sent after an unanswered question: {_short(text(e))}"
        pending = e["i"] if "?" in text(e) and not e.get("reply") else None
    return True, f"{len(msgs)} messages, every question ends its burst"


def c_disclosure_before_questions(c, ctx):
    before = []
    for e in sent(ctx, c):
        if asks(text(e)) in GATE:
            break
        before.append(text(e))
    hay = " ".join(before)
    missing = [k for k, alts in c["facts"].items() if not _any(hay, alts)]
    if missing:
        return False, f"before the first gate question ({len(before)} msgs) missing: {', '.join(missing)}"
    return True, f"all {len(c['facts'])} facts in {len(before)} messages"


def _response_to(c, ctx) -> list[dict] | None:
    msgs = sent(ctx, {k: v for k, v in c.items() if k in ("phase", "phases", "before_phase", "from_phase")})
    if c.get("first_burst"):
        out = []
        for e in msgs:
            out.append(e)
            if e.get("reply"):
                break
        return out
    if "after_renter_contains" in c:
        needle = _low(c["after_renter_contains"])
        start = None
        for n, e in enumerate(msgs):
            if needle in _low(str(e.get("reply") or "")):
                start = n + 1
                break
        if start is None:   # the renter line opened a phase (renter_says) or the thread (opening)
            for p in ctx.get("phases") or []:
                rm = p.get("renter_msg") or {}
                if needle in _low(rm.get("text", "")):
                    start = next((n for n, e in enumerate(msgs) if e["i"] >= p["start"]), len(msgs))
                    break
        if start is None:
            return None
        out = []
        for e in msgs[start:]:
            out.append(e)
            if e.get("reply"):
                break
        return out
    return msgs


def c_reply_to_line(c, ctx):
    burst = _response_to(c, ctx)
    if burst is None:
        return False, f"renter line {c.get('after_renter_contains')!r} never reached"
    texts = [text(e) for e in burst]
    hay = " ".join(texts)
    if len(burst) < c.get("min_messages", 1):
        return False, f"{len(burst)} messages in response"
    if "max_messages" in c and len(burst) > c["max_messages"]:
        return False, f"{len(burst)} messages > {c['max_messages']}"
    if c.get("last_asks") and asks(texts[-1]) != c["last_asks"]:
        return False, f"last message asks {asks(texts[-1])}, want {c['last_asks']}: {_short(texts[-1])}"
    if c.get("last_asks_in") and asks(texts[-1]) not in c["last_asks_in"]:
        return False, f"last message asks {asks(texts[-1])}, want one of {c['last_asks_in']}: {_short(texts[-1])}"
    if c.get("last_contains") and not _any(texts[-1], c["last_contains"]):
        return False, f"last message lacks {c['last_contains']}: {_short(texts[-1])}"
    if c.get("no_gate_question"):
        bad = [t for t in texts if asks(t) in GATE]
        if bad:
            return False, f"gate question in the response: {_short(bad[0])}"
    if c.get("asks_any") and not any(asks(t) in c["asks_any"] for t in texts):
        return False, f"no message asks {c['asks_any']}"
    if c.get("contains_any") and not _any(hay, c["contains_any"]):
        return False, f"none of {c['contains_any']}: {_short(hay)}"
    if c.get("contains_all") and not all(_any(hay, [w]) for w in c["contains_all"]):
        return False, f"not all of {c['contains_all']}: {_short(hay)}"
    for w in c.get("not_contains") or []:
        if _any(hay, [w]):
            return False, f"contains {w!r}"
    if c.get("regex_absent") and re.search(c["regex_absent"], hay, re.I):
        return False, f"matches /{c['regex_absent']}/: {_short(hay)}"
    if c.get("no_question") and "?" in hay:
        return False, "asks a question"
    if c.get("one_question_total") and hay.count("?") != 1:
        return False, f"{hay.count('?')} questions in the response"
    return True, f"{len(burst)} messages ok"


def c_reask_differs(c, ctx):
    asks_ = [text(e) for e in sent(ctx, c) if asks(text(e)) == c["item"]]
    if len(asks_) < 2:
        return False, f"{c['item']} asked {len(asks_)} time(s); want a re-ask"
    a, b = _low(asks_[0]), _low(asks_[1])
    ratio = difflib.SequenceMatcher(None, a, b).ratio()
    return (a != b and ratio < c.get("max_similarity", 0.9)), f"similarity {ratio:.2f}"


def c_msg(c, ctx):
    msgs = [text(e) for e in sent(ctx, c)]
    hay = " ".join(msgs)
    if c.get("require_messages") and not msgs:
        return False, "no messages"
    if c.get("contains_any") and not _any(hay, c["contains_any"]):
        return False, f"none of {c['contains_any']}"
    if c.get("contains_all") and not all(_any(hay, [w]) for w in c["contains_all"]):
        return False, f"not all of {c['contains_all']}"
    for w in c.get("not_contains") or []:
        if _any(hay, [w]):
            m = next(t for t in msgs if _any(t, [w]))
            return False, f"sent {w!r}: {_short(m)}"
    if c.get("regex_present") and not re.search(c["regex_present"], hay, re.I):
        return False, f"no match for /{c['regex_present']}/"
    if c.get("regex_absent"):
        for t in msgs:
            if re.search(c["regex_absent"], t, re.I):
                return False, f"matches /{c['regex_absent']}/: {_short(t)}"
    return True, f"{len(msgs)} messages ok"


def _matches(t: str, c: dict) -> bool:
    if c.get("regex"):
        return bool(re.search(c["regex"], t, re.I))
    return _any(t, c["contains_any"])


def c_count_messages(c, ctx):
    n = sum(1 for e in sent(ctx, c) if _matches(text(e), c))
    ok = ("eq" not in c or n == c["eq"]) and ("min" not in c or n >= c["min"]) and ("max" not in c or n <= c["max"])
    return ok, f"{n} matching messages"


def c_message_order(c, ctx):
    msgs = [text(e) for e in sent(ctx, c)]
    pos = []
    for g in c["sequence"]:
        where = next((n for n, t in enumerate(msgs) if _any(t, g)), None)
        if where is None:
            return False, f"never sent any of {g}"
        pos.append(where)
    if pos != sorted(pos):
        return False, f"out of order: message indexes {pos}"
    if c.get("last_contains") and not (msgs and _any(msgs[-1], c["last_contains"])):
        return False, f"last message lacks {c['last_contains']}: {_short(msgs[-1]) if msgs else ''}"
    return True, f"in order at {pos}"


def c_separate_messages(c, ctx):
    msgs = [text(e) for e in sent(ctx, c)]
    a = [n for n, t in enumerate(msgs) if _any(t, c["a"])]
    b = [n for n, t in enumerate(msgs) if _any(t, c["b"])]
    if not a or not b:
        return False, f"a present {bool(a)}, b present {bool(b)}"
    if set(a) & set(b) and not (set(a) - set(b)) and not (set(b) - set(a)):
        return False, "only ever said together in one message"
    return True, f"a at {a}, b at {b}"


def c_no_send(c, ctx):
    msgs = sent(ctx, c)
    return not msgs, (f"sent {len(msgs)}: {_short(text(msgs[0]))}" if msgs else "nothing sent")


def c_owner_notified(c, ctx):
    ents = _owner_entries(ctx, c)
    if c.get("contains_any"):
        ents = [x for x in ents if _any(x[1], c["contains_any"])]
    n = len(ents)
    ok = n >= c.get("min", 1) and ("max" not in c or n <= c["max"])
    return ok, f"{n} matching owner notifications"


def c_owner_text(c, ctx):
    ents = _owner_entries(ctx, c)
    for _, t in ents:
        if c.get("rule", "no_long_dash") == "no_long_dash" and V._LONG_DASH.search(t):
            return False, f"long dash in owner text: {_short(t)}"
    if c.get("require", False) and not ents:
        return False, "no owner text"
    return True, f"{len(ents)} owner texts ok"


def _times(t: str) -> set[str]:
    return {re.sub(r"[\s.:]|00", "", m.group(0).lower()) for m in TIME_OFFER.finditer(t)}


def c_no_time_offer_before_gate(c, ctx):
    said = set()
    for t in ctx.get("renter_texts") or []:
        said |= _times(t)
    for e in sent(ctx, c):
        if (e.get("gate_before") or {}).get(c["thread"]):
            continue
        offered = _times(text(e)) - said   # echoing the renter's own time is not an offer
        if offered:
            return False, f"time offered before the gate: {_short(text(e))}"
    return True, "ok"


_FIG = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)")


def c_figures_in(c, ctx):
    allowed = {float(x) for x in c["allowed"]}
    for e in sent(ctx, c):
        for m in _FIG.finditer(text(e)):
            v = float(m.group(1).replace(",", ""))
            if v not in allowed:
                return False, f"${m.group(1)} not in the record: {_short(text(e))}"
    return True, "every figure is in the record"


_CLAIM = re.compile(r"\b(is|it'?s|you'?re|that'?s|we'?re|are|all|now)\s+(now\s+)?(confirmed|set|booked|locked in|scheduled)\b|"
                    r"\bsee you (then|thursday|tomorrow|on|at|there)\b|\bconfirmad[oa]\b|\bnos vemos\b", re.I)
_PENDING = re.compile(r"pending|propos|pencil|will confirm|i'?ll confirm|confirm (it|this|that|the time)?\s*(shortly|soon|later)|"
                      r"once i confirm|until i confirm|te (lo )?confirmo|pendiente", re.I)


def c_no_confirm_claim(c, ctx):
    for e in sent(ctx, c):
        for snt in re.split(r"(?<=[.!?])\s+", text(e)):
            if _CLAIM.search(snt) and not _PENDING.search(snt) and not snt.rstrip().endswith("?"):
                return False, f"claims a confirmed time: {_short(snt)}"
    return True, "no confirmation claimed"


def c_language_before(c, ctx):
    want = c.get("language", "en")
    needle = _low(c["until_renter_contains"])
    for e in sent(ctx, c):
        if (want == "es") != V.looks_spanish(text(e)):
            return False, f"not in {want} before the renter's yes: {_short(text(e))}"
        if e.get("reply") and needle in _low(str(e["reply"])):
            return True, "kept the language until the renter answered"
    return True, "kept the language (renter never switched)"


def c_listing_text(c, ctx):
    n = 0
    for e in ctx["trace"]:
        if e["tool"] in ("create_listing", "update_listing") and isinstance(e.get("args"), dict):
            a = e["args"]
            blob = " ".join(str(a.get(k, "")) for k in ("title", "body")) + " " + \
                " ".join(str(v) for v in (a.get("fields") or {}).values())
            n += 1
            if re.search(c["regex_absent"], blob, re.I):
                return False, f"listing text matches /{c['regex_absent']}/: {_short(blob)}"
    if c.get("require", True) and not n:
        return False, "no listing created"
    return True, f"{n} listing texts ok"


def c_event_ok(c, ctx):
    st = ctx["state"]
    row = _renter_row(st, c["thread"])
    if not row:
        return False, "no renter row"
    evs = [e for e in st.get("calendar") or [] if e.get("renter_id") == row["renter_id"]
           and e.get("status") in ("proposed", "confirmed") and not e.get("seeded")]
    if not evs:
        return False, "no proposed showing"
    h = (st.get("policy") or {}).get("showing_hours") or {}
    lo, hi = c.get("start", h.get("start", "10:00")), c.get("end", h.get("end", "18:00"))
    for ev in evs:
        s, e = datetime.fromisoformat(ev["start"]), datetime.fromisoformat(ev["end"])
        if not (lo <= s.strftime("%H:%M") and e.strftime("%H:%M") <= hi):
            return False, f"{ev['start']} outside {lo} to {hi}"
        for o in st.get("calendar") or []:
            if o is ev or o.get("event_id") == ev.get("event_id") or o.get("status") not in ("proposed", "confirmed"):
                continue
            if o.get("room_id") != ev.get("room_id"):
                continue
            if datetime.fromisoformat(o["start"]) < e and s < datetime.fromisoformat(o["end"]):
                return False, f"{ev['start']} overlaps {o.get('event_id')}"
    return True, f"{len(evs)} event(s) ok"


def c_register_key(c, ctx):
    st = ctx["state"]
    row = _renter_row(st, c["thread"])
    val = _find_key(row, c["key"]) if row else None
    if val is None:   # a separate demand register (lane 2) keyed by thread or renter
        for k, coll in st.items():
            if "demand" in str(k) and isinstance(coll, list):
                for r in coll:
                    if isinstance(r, dict) and (c["thread"] in str(r)):
                        val = _find_key(r, c["key"])
                        if val is not None:
                            break
    if c.get("exists") is not None:
        return (val not in (None, "", [], {})) == bool(c["exists"]), f"{c['key']}={_short(str(val))}"
    if val is None:
        return False, f"{c['key']} missing"
    if "equals" in c:
        return V._norm(val, c.get("normalize")) == V._norm(c["equals"], c.get("normalize")), f"{c['key']}={_short(str(val))}"
    if "in" in c:
        return V._norm(val, c.get("normalize")) in [V._norm(x, c.get("normalize")) for x in c["in"]], f"{c['key']}={val}"
    return True, f"{c['key']}={_short(str(val))}"


def c_register_rows(c, ctx):
    n = len(ctx["state"].get("register") or [])
    n0 = len((ctx.get("initial_state") or {}).get("register") or [])
    if c.get("gte_initial") and n < n0:
        return False, f"register shrank {n0} -> {n}"
    if "count_eq" in c and n != c["count_eq"]:
        return False, f"{n} rows, want {c['count_eq']}"
    return True, f"{n0} -> {n} rows"


def c_no_delete_tool(c, ctx):
    bad = [t for t in ctx.get("tool_names") or [] if re.search(r"delete|remove|purge|drop", t)
           and re.search(r"renter|register|demand|prospect|lead", t)]
    return not bad, (f"delete tools: {bad}" if bad else f"{len(ctx.get('tool_names') or [])} tools, none deletes a row")


def c_probe(c, ctx):
    res = (ctx.get("probe_results") or [])
    if c["step"] >= len(res):
        return False, f"step {c['step']} did not run"
    v = V.resolve(res[c["step"]], c["path"]) if c.get("path") else res[c["step"]]
    if v is V._MISSING:
        return ("exists" in c and not c["exists"]), f"{c.get('path')} missing"
    if "exists" in c:
        return bool(c["exists"]), f"{c['path']} present"
    if "equals" in c:
        return V._norm(v) == V._norm(c["equals"]), f"{c['path']}={_short(str(v))}"
    if "contains" in c:
        hay = json.dumps(v, default=str).lower()
        return str(c["contains"]).lower() in hay, f"{c['path']} {'has' if str(c['contains']).lower() in hay else 'lacks'} {c['contains']!r}"
    if "count_gte" in c:
        n = len(v) if isinstance(v, (list, dict)) else 0
        return n >= c["count_gte"], f"count {n}"
    if "includes" in c or "excludes" in c or "above" in c:
        key = c.get("id_key", "renter_id")
        ids = [m.get(key) for m in v] if isinstance(v, list) else []
        miss = [x for x in c.get("includes", []) if x not in ids]
        extra = [x for x in c.get("excludes", []) if x in ids]
        if miss or extra:
            return False, f"ranked {ids}: missing {miss}, should be excluded {extra}"
        if "above" in c:
            a, b = c["above"]
            if a not in ids or (b in ids and ids.index(a) > ids.index(b)):
                return False, f"{a} not above {b}: {ids}"
        return True, f"ranked {ids}"
    return True, f"{_short(str(v))}"


CHECKS = {name: globals()[f"c_{name}"] for name in CUSTOM}


def run_checks(task: dict, ctx: dict) -> list[dict]:
    """Score every check of a scenario. Standard types go through rentus_env.verify unchanged."""
    out = []
    for n, c in enumerate(task.get("checks", [])):
        t = c.get("type")
        try:
            if t in CHECKS:
                ok, why = CHECKS[t](c, ctx)
            elif t in V._CHECKS:
                ok, why = V._CHECKS[t](c, {"task": task, "trace": ctx["trace"], "state": ctx["state"], "final_text": ""})
            else:
                ok, why = False, f"unknown check type {t!r}"
        except Exception as e:  # noqa: BLE001 - a broken check fails, never crashes the run
            ok, why = False, f"check error {type(e).__name__}: {e}"
        out.append({"i": n, "type": t, "name": c.get("name") or t, "pass": bool(ok), "detail": why})
    return out
