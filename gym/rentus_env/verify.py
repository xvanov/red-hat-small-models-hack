"""The scorer. Deterministic: same trace + final state -> same score.

Each check passes or fails. reward = passed / total; a task passes when every check passes.

Check types
  state         a value in the final world state      {"path", "equals"|"in"|"exists"|"absent"|"contains"|
                                                        "not_contains"|"count_gte"|"count_eq"|"gte"|"lte", "normalize"?}
  never         a tool is never ATTEMPTED (optionally  {"tool", "before"?: "gate_complete"|"tool:<name>",
                only before a condition), or an item    "thread"?}   or   {"asked": "<item>", "thread"}
                is never asked on a thread
  style         every message the operator attempted   {"rule": "max_two_sentences"|"one_question"|
                to a renter obeys a style rule          "no_long_dash"|"language"|"first_person",
                                                        "thread"?, "language"?, "scope"?: "attempted"|"sent"}
  tool_called   a tool was called (successfully by     {"tool", "ok"?: true, "args"?: {...}, "min"?: 1,
                default) with matching args             "max"?, "distinct_arg"?}
  escalated     the owner was (or was not) escalated   {"expect"?: true, "ref"?, "reason_any"?: [...]}
  budget        spend and effort stayed in bounds      {"spend_max"?: number|"policy", "max_tool_calls"?,
                                                        "max_repeat_failures"?}
  message       what the operator SENT to a thread     {"thread", "contains_any"?, "contains_all"?,
                                                        "not_contains"?}
"""
from __future__ import annotations

import re
from typing import Any

from .counterparts import classify_question

CHECK_TYPES = ("state", "never", "style", "tool_called", "escalated", "budget", "message")

_MISSING = object()


# ------------------------------------------------------------------------------- state paths
_SEG = re.compile(r"([^.\[\]]+)(?:\[([^\]]*)\])?")
_ID_KEYS = ("renter_id", "thread_id", "listing_id", "room_id", "job_id", "quote_id", "vendor_id",
            "event_id", "esc_id", "post_id", "name")


def _matches(item: Any, sel: str) -> bool:
    if not isinstance(item, dict):
        return str(item) == sel
    if "=" in sel:
        k, v = sel.split("=", 1)
        got = item.get(k.strip())
        return got is not None and _norm(got) == _norm(v.strip())
    if any(str(item.get(k)) == sel for k in _ID_KEYS):
        return True
    return sel in (item.get("thread_ids") or [])


def resolve(doc: Any, path: str) -> Any:
    """Path like `register[t_maria].gate.move_in.date` or `listings[status=live]`.

    `[sel]` on a list keeps matching items (one match -> that item, else the list of matches);
    `[*]` keeps all. Lenient leaf: `.date`/`.value` under a scalar returns the scalar,
    so `gate.move_in.date` also reads a gate stored as `"move_in": "2026-11-01"`.
    """
    cur = doc
    for m in _SEG.finditer(path):
        key, sel = m.group(1), m.group(2)
        if isinstance(cur, dict):
            cur = cur.get(key, _MISSING)
        elif isinstance(cur, list) and key.isdigit():
            cur = cur[int(key)] if int(key) < len(cur) else _MISSING
        elif cur is not _MISSING and not isinstance(cur, (dict, list)) and key in ("date", "value"):
            pass  # lenient leaf
        else:
            return _MISSING
        if cur is _MISSING:
            return _MISSING
        if sel is not None:
            if isinstance(cur, dict):
                cur = list(cur.values())
            if not isinstance(cur, list):
                return _MISSING
            if sel != "*":
                hits = [x for x in cur if _matches(x, sel)]
                if not hits:
                    return _MISSING
                cur = hits[0] if len(hits) == 1 else hits
    return cur


def _norm(v: Any, how: str | None = None) -> Any:
    if isinstance(v, dict):
        for k in ("date", "value"):
            if k in v and v[k] is not None:
                return _norm(v[k], how)
        return v
    if how == "phone":
        d = re.sub(r"\D", "", str(v))
        return d[-10:]
    if how == "date":
        m = re.search(r"\d{4}-\d{2}-\d{2}", str(v))
        return m.group(0) if m else str(v)
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if how == "bool" or s.lower() in ("true", "false", "yes", "no"):
        return s.lower() in ("true", "yes", "1", "si", "sí")
    try:
        return float(s)
    except ValueError:
        return s.lower()


def _count(v: Any) -> int:
    if v is _MISSING or v is None:
        return 0
    if isinstance(v, (list, dict)):
        return len(v)
    return 1


def check_state(c: dict, ctx: dict) -> tuple[bool, str]:
    v = resolve(ctx["state"], c["path"])
    how = c.get("normalize")
    if "exists" in c:
        ok = (v is not _MISSING and v is not None) == bool(c["exists"])
        return ok, f"{c['path']} {'present' if v is not _MISSING else 'missing'}"
    if c.get("absent"):
        return v is _MISSING or v is None, f"{c['path']}={_short(v)}"
    if "count_gte" in c:
        return _count(v) >= c["count_gte"], f"count={_count(v)}"
    if "count_eq" in c:
        return _count(v) == c["count_eq"], f"count={_count(v)}"
    if v is _MISSING:
        return False, f"{c['path']} missing"
    if "equals" in c:
        return _norm(v, how) == _norm(c["equals"], how), f"{c['path']}={_short(v)}"
    if "in" in c:
        return _norm(v, how) in [_norm(x, how) for x in c["in"]], f"{c['path']}={_short(v)}"
    if "not_contains" in c:
        hay = " ".join(map(str, v)) if isinstance(v, list) else str(v)
        return str(c["not_contains"]).lower() not in hay.lower(), f"{c['path']}={_short(v)}"
    if "contains" in c:
        hay = " ".join(map(str, v)) if isinstance(v, list) else str(v)
        return str(c["contains"]).lower() in hay.lower(), f"{c['path']}={_short(v)}"
    if "gte" in c or "lte" in c:
        try:
            x = float(_norm(v, how))
        except (TypeError, ValueError):
            return False, f"{c['path']} not numeric: {_short(v)}"
        ok = ("gte" not in c or x >= c["gte"]) and ("lte" not in c or x <= c["lte"])
        return ok, f"{c['path']}={x}"
    return v is not None, f"{c['path']}={_short(v)}"


# --------------------------------------------------------------------------------- trace ones
def check_never(c: dict, ctx: dict) -> tuple[bool, str]:
    if "asked" in c:  # the operator never asks this item on this thread (e.g. info already volunteered)
        for e in ctx["trace"]:
            if e["tool"] == "send_message" and isinstance(e.get("args"), dict) \
                    and e["args"].get("thread_id") == c.get("thread") \
                    and classify_question(str(e["args"].get("text", ""))) == c["asked"]:
                return False, f"asked {c['asked']} again at step {e['i']}"
        return True, "ok"
    tool, before = c["tool"], c.get("before")
    for e in ctx["trace"]:
        if e["tool"] != tool:
            continue
        if before is None:
            return False, f"{tool} called at step {e['i']}"
        if before == "gate_complete":
            gates = e.get("gate_before") or {}
            if c.get("thread"):
                if not gates.get(c["thread"], False):
                    return False, f"{tool} at step {e['i']} before {c['thread']} gate complete"
            elif not gates or not any(gates.values()):
                return False, f"{tool} at step {e['i']} before any gate complete"
        elif before.startswith("tool:"):
            first = next((x["i"] for x in ctx["trace"] if x["tool"] == before[5:] and x["ok"]), None)
            if first is None or first > e["i"]:
                return False, f"{tool} at step {e['i']} before {before[5:]}"
    return True, "ok"


_LONG_DASH = re.compile("[–—]")
_ES = re.compile(r"\b(el|la|los|las|de|que|y|en|un|una|para|con|por|es|tu|te|cuarto|habitaci[oó]n|"
                 r"gracias|hola|s[ií]|fecha|mudar|cu[aá]ndo|est[aá]|puedo|tengo)\b|[¿¡ñáéíóú]", re.I)
_EN = re.compile(r"\b(the|and|you|is|to|for|with|your|room|thanks|what|when|are|can|it|of|I)\b", re.I)


def sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s]


def looks_spanish(text: str) -> bool:
    return len(_ES.findall(text)) > len(_EN.findall(text))


def _operator_messages(ctx: dict, thread: str | None, scope: str) -> list[str]:
    out = []
    for e in ctx["trace"]:
        if e["tool"] != "send_message" or not isinstance(e.get("args"), dict):
            continue
        if scope == "sent" and not e["ok"]:
            continue
        if thread and e["args"].get("thread_id") != thread:
            continue
        out.append(str(e["args"].get("text", "")))
    return out


def check_style(c: dict, ctx: dict) -> tuple[bool, str]:
    rule = c["rule"]
    msgs = _operator_messages(ctx, c.get("thread"), c.get("scope", "attempted"))
    if not msgs:
        return (not c.get("require_messages", True)), "no messages to the renter"
    for m in msgs:
        bad = None
        if rule == "max_two_sentences" and len(sentences(m)) > 2:
            bad = "more than 2 sentences"
        elif rule == "one_question" and m.count("?") > 1:
            bad = "more than one question"
        elif rule == "no_long_dash" and _LONG_DASH.search(m):
            bad = "long dash"
        elif rule == "language":
            want = c.get("language", "en")
            if (want == "es") != looks_spanish(m):
                bad = f"not in {want}"
        elif rule == "first_person" and re.search(r"\bthe (owner|landlord)\b|\bel due[nñ]o\b", m, re.I):
            bad = "speaks about the owner in the third person"
        if bad:
            return False, f"{bad}: {_short(m, 90)}"
    return True, f"{len(msgs)} messages ok"


def _arg_match(want: Any, got: Any) -> bool:
    if isinstance(want, dict):
        return isinstance(got, dict) and all(_arg_match(v, got.get(k)) for k, v in want.items())
    if isinstance(want, list):
        return any(_arg_match(w, got) for w in want)
    if isinstance(want, str) and isinstance(got, str):
        return want.lower() in got.lower()
    return got is not None and _norm(want) == _norm(got)


def check_tool_called(c: dict, ctx: dict) -> tuple[bool, str]:
    want_ok = c.get("ok", True)
    hits = [e for e in ctx["trace"] if e["tool"] == c["tool"] and (want_ok is None or e["ok"] == want_ok)
            and _arg_match(c.get("args") or {}, e.get("args") or {})]
    if c.get("distinct_arg"):
        n = len({str((e.get("args") or {}).get(c["distinct_arg"])) for e in hits})
    else:
        n = len(hits)
    lo, hi = c.get("min", 1), c.get("max")
    return n >= lo and (hi is None or n <= hi), f"{c['tool']} x{n}"


def check_escalated(c: dict, ctx: dict) -> tuple[bool, str]:
    escs = list(ctx["state"].get("escalations") or [])
    if c.get("ref"):
        escs = [e for e in escs if c["ref"].lower() in str(e.get("ref_id", "")).lower()]
    if c.get("reason_any"):
        escs = [e for e in escs if any(w.lower() in (str(e.get("reason", "")) + " " + str(e.get("draft", ""))).lower()
                                       for w in c["reason_any"])]
    expect = c.get("expect", True)
    return bool(escs) == expect, f"{len(escs)} matching escalations"


def check_budget(c: dict, ctx: dict) -> tuple[bool, str]:
    st = ctx["state"]
    notes = []
    if "spend_max" in c:
        cap = c["spend_max"]
        if cap == "policy":
            cap = (st.get("policy") or {}).get("spend_limit_usd", 0)
        spent = sum(float(j.get("cost") or 0) for j in st.get("jobs") or [] if j.get("status") in ("booked", "done"))
        if spent > float(cap):
            return False, f"spent {spent} > {cap}"
        notes.append(f"spent {spent}")
    if "max_tool_calls" in c:
        n = len(ctx["trace"])
        if n > c["max_tool_calls"]:
            return False, f"{n} tool calls > {c['max_tool_calls']}"
        notes.append(f"{n} calls")
    if "max_repeat_failures" in c:
        seen: dict[str, int] = {}
        for e in ctx["trace"]:
            if e["ok"]:
                continue
            key = e["tool"] + repr(sorted((e.get("args") or {}).items(), key=str))
            seen[key] = seen.get(key, 0) + 1
        worst = max(seen.values(), default=0)
        if worst > c["max_repeat_failures"]:
            return False, f"same failing call repeated {worst}x"
        notes.append(f"worst repeat {worst}")
    return True, ", ".join(notes) or "ok"


def check_message(c: dict, ctx: dict) -> tuple[bool, str]:
    text = " ".join(_operator_messages(ctx, c.get("thread"), "sent")).lower()
    if c.get("contains_any") and not any(w.lower() in text for w in c["contains_any"]):
        return False, f"none of {c['contains_any']} in sent text"
    if c.get("contains_all") and not all(w.lower() in text for w in c["contains_all"]):
        return False, f"not all of {c['contains_all']} in sent text"
    for w in c.get("not_contains") or []:
        if w.lower() in text:
            return False, f"sent forbidden text {w!r}"
    return True, "ok"


_CHECKS = {"state": check_state, "never": check_never, "style": check_style, "tool_called": check_tool_called,
           "escalated": check_escalated, "budget": check_budget, "message": check_message}


def _short(v: Any, n: int = 60) -> str:
    s = "<missing>" if v is _MISSING else str(v)
    return s if len(s) <= n else s[: n - 1] + "…"


def verify(task: dict, trace: list[dict], final_state: dict, final_text: str = "") -> dict:
    ctx = {"task": task, "trace": trace, "state": final_state, "final_text": final_text}
    results = []
    for i, c in enumerate(task.get("checks", [])):
        fn = _CHECKS.get(c.get("type"))
        if fn is None:
            ok, why = False, f"unknown check type {c.get('type')!r}"
        else:
            try:
                ok, why = fn(c, ctx)
            except Exception as e:  # noqa: BLE001 - a broken check fails, never crashes the run
                ok, why = False, f"check error {type(e).__name__}: {e}"
        results.append({"i": i, "type": c.get("type"), "name": c.get("name") or _name(c), "pass": bool(ok),
                        "detail": why})
    n = len(results)
    passed = sum(r["pass"] for r in results)
    return {"task_id": task.get("id"), "category": task.get("category"), "reward": passed / n if n else 0.0,
            "pass": n > 0 and passed == n, "checks_passed": passed, "checks_total": n, "checks": results,
            "tool_calls": len(trace)}


def _name(c: dict) -> str:
    t = c.get("type")
    if t == "state":
        return f"state:{c.get('path')}"
    if t in ("never", "tool_called"):
        return f"{t}:{c.get('tool')}" + (f"<{c['before']}" if c.get("before") else "")
    if t == "style":
        return f"style:{c.get('rule')}"
    return str(t)
