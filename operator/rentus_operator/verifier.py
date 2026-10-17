"""Deterministic verifier: no model anywhere in this file.

Four jobs:
1. check_call    - before execution: tool exists, args parse as JSON (one repair
                   pass for trivial damage), args match the schema.
2. check_result  - after execution: envelope shape, and the data shape each tool
                   promises in contracts/tools.md §4 (catches §5 'malformed').
3. decide        - retry policy per error code: retry with bounded backoff,
                   fall back, or hand the model structured feedback.
4. self_check    - before the run ends: every claimed action is visible in the
                   world state (diff of before vs after).
Plus LoopGuard: the same failing call 3 times forces an escalation.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

ERROR_CODES = {"INVALID_ARGS", "NOT_FOUND", "CONFLICT", "RATE_LIMITED", "TIMEOUT", "LOGIN_REQUIRED",
               "PAGE_CHANGED", "UPSTREAM_ERROR", "POLICY_BLOCKED", "BUDGET_EXCEEDED"}
RETRYABLE = {"RATE_LIMITED", "TIMEOUT", "UPSTREAM_ERROR", "MALFORMED_RESULT"}
FALLBACK = {"PAGE_CHANGED", "LOGIN_REQUIRED"}
NO_RETRY = {"POLICY_BLOCKED", "BUDGET_EXCEEDED"}
LISTING_CHANNELS = ["marketplace", "roomies", "craigslist", "padsplit"]
READER_STATUS = {"answered", "vague", "no", "exception", "absent"}


# --------------------------------------------------------------------------- 1. calls

@dataclass
class CallCheck:
    ok: bool
    name: str
    args: dict | None = None
    repaired: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    def feedback(self) -> dict:
        return {"ok": False, "error": {"code": "INVALID_ARGS", "message": "; ".join(self.problems),
                                       "retryable": True},
                "verifier": {"stage": "pre-call", "action": "fix the arguments and call again",
                             "problems": self.problems}}


def _strip_fences(s: str) -> str:
    m = re.match(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", s, re.S)
    return m.group(1) if m else s


def repair_json(raw: str) -> tuple[object, list[str]]:
    """One repair pass for trivial damage. Returns (value, fixes) or raises ValueError."""
    fixes = []
    s = _strip_fences(raw.strip())
    if s != raw.strip():
        fixes.append("removed code fence")
    if re.search(r"\b(True|False|None)\b", s):
        s = re.sub(r"\bTrue\b", "true", re.sub(r"\bFalse\b", "false", re.sub(r"\bNone\b", "null", s)))
        fixes.append("python literals")
    if "'" in s and '"' not in s:
        s = s.replace("'", '"')
        fixes.append("single quotes")
    t = re.sub(r",\s*([}\]])", r"\1", s)
    if t != s:
        s = t
        fixes.append("trailing comma")
    opens = s.count("{") - s.count("}")
    sq = s.count("[") - s.count("]")
    if opens > 0 or sq > 0:
        s = s + "]" * max(sq, 0) + "}" * max(opens, 0)
        fixes.append("closed brackets")
    try:
        return json.loads(s), fixes
    except json.JSONDecodeError as e:
        raise ValueError(f"arguments are not valid JSON ({e.msg} at char {e.pos})") from None


def parse_args(raw) -> tuple[dict | None, list[str], str | None]:
    if isinstance(raw, dict):
        return raw, [], None
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return {}, ["empty arguments read as {}"], None
    try:
        val, fixes = json.loads(raw), []
    except (json.JSONDecodeError, TypeError):
        try:
            val, fixes = repair_json(str(raw))
        except ValueError as e:
            return None, [], str(e)
    if isinstance(val, str):  # double-encoded
        try:
            val, fixes = json.loads(val), fixes + ["double-encoded JSON"]
        except json.JSONDecodeError:
            pass
    if not isinstance(val, dict):
        return None, fixes, f"arguments must be a JSON object, got {type(val).__name__}"
    return val, fixes, None


_PY = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "object": dict, "array": list}


def _type_ok(v, t):
    if t == "null":
        return v is None
    if isinstance(t, list):
        return any(_type_ok(v, x) for x in t)
    if t in ("integer", "number") and isinstance(v, bool):
        return False
    py = _PY.get(t)
    return py is None or isinstance(v, py)


def _coerce(v, t):
    """Trivial type repairs: '750' -> 750, 'true' -> True. Returns (value, changed)."""
    if isinstance(v, str):
        if t == "integer" and re.fullmatch(r"-?\d+", v.strip()):
            return int(v), True
        if t == "number" and re.fullmatch(r"-?\$?\d+(\.\d+)?", v.strip()):
            return float(v.strip().lstrip("$")) if "." in v else int(v.strip().lstrip("$")), True
        if t == "boolean" and v.lower() in ("true", "false"):
            return v.lower() == "true", True
    if t == "string" and isinstance(v, (int, float)) and not isinstance(v, bool):
        return str(v), True
    return v, False


def validate(value, schema: dict, path: str = "args", fixes: list | None = None) -> list[str]:
    """Small JSON-schema subset: type, required, properties, additionalProperties, enum, items.
    Coerces trivial type mismatches in place (recorded in fixes)."""
    errs = []
    t = schema.get("type")
    if t and not _type_ok(value, t):
        return [f"{path} should be {t}, got {type(value).__name__}"]
    if "enum" in schema and value not in schema["enum"]:
        errs.append(f"{path} must be one of {schema['enum']}, got {value!r}")
    if isinstance(value, dict):
        props = schema.get("properties", {})
        for k in schema.get("required", []):
            if k not in value:
                errs.append(f"{path}.{k} is required")
        if schema.get("additionalProperties") is False:
            for k in value:
                if k not in props:
                    errs.append(f"{path}.{k} is not a parameter (allowed: {', '.join(props) or 'none'})")
        for k, sub in props.items():
            if k in value:
                st = sub.get("type")
                if st and not _type_ok(value[k], st) and fixes is not None:
                    nv, changed = _coerce(value[k], st)
                    if changed:
                        value[k] = nv
                        fixes.append(f"{path}.{k} coerced to {st}")
                errs += validate(value[k], sub, f"{path}.{k}", fixes)
    if isinstance(value, list) and "items" in schema:
        for i, item in enumerate(value):
            errs += validate(item, schema["items"], f"{path}[{i}]", fixes)
    return errs


class CallChecker:
    def __init__(self, tools: list[dict]):
        self.schemas = {t["function"]["name"]: t["function"].get("parameters", {"type": "object"}) for t in tools}

    def check(self, name: str, raw_args) -> CallCheck:
        if name not in self.schemas:
            close = [n for n in self.schemas if n.split("_")[-1] in name or name in n]
            return CallCheck(False, name, problems=[f"unknown tool '{name}'" +
                                                    (f", did you mean {close[0]}?" if close else "")])
        args, fixes, err = parse_args(raw_args)
        if err:
            return CallCheck(False, name, problems=[err])
        errs = validate(args, self.schemas[name], fixes=fixes)
        if errs:
            return CallCheck(False, name, args=args, repaired=fixes, problems=errs)
        return CallCheck(True, name, args=args, repaired=fixes)


# --------------------------------------------------------------------------- 2. results

NUM = (int, float)
SHAPES: dict[str, dict] = {
    "list_rooms": {"rooms": list},
    "get_room": {"room": {"room_id": str}},
    "update_room": {"room": {"room_id": str}},
    "create_listing": {"listing": {"listing_id": str, "status": str}},
    "update_listing": {"listing": {"listing_id": str}},
    "mark_filled": {"listing": {"listing_id": str, "status": str}},
    "publish_listing": {"post_id": str, "status": str},
    "get_listing_media": {"photos": list},
    "check_listing_compliance": {"ok": bool, "findings": list},
    "get_market_rent": {"zori": NUM},
    "list_threads": {"threads": list},
    "read_thread": {"thread": {"thread_id": str, "messages": list}},
    "send_message": {"message_id": str},
    "read_reply": {"lease": dict, "move_in": dict, "phone": dict, "occupants": dict, "reason": dict,
                   "intents": list, "language": str},
    "upsert_renter": {"renter": {"renter_id": str}},
    "match_renters": {"matches": list},
    "find_showing_slots": {"slots": list},
    "propose_showing": {"event": {"event_id": str, "status": str}},
    "web_search": {"results": list},
    "fetch_page": {"text": str},
    "find_vendors": {"vendors": list},
    "request_quote": {"quote": {"quote_id": str, "amount": NUM}},
    "book_vendor": {"job": {"job_id": str, "status": str}},
    "create_job": {"job": {"job_id": str}},
    "escalate_to_owner": {"escalation": {"esc_id": str}},
    "report_to_owner": {"ok": bool},
}


def _shape_errors(data, spec, path="data") -> list[str]:
    if not isinstance(data, dict):
        return [f"{path} should be an object, got {type(data).__name__}"]
    errs = []
    for k, want in spec.items():
        if k not in data or data[k] is None:
            errs.append(f"{path}.{k} missing")
        elif isinstance(want, dict):
            errs += _shape_errors(data[k], want, f"{path}.{k}")
        else:
            ok = isinstance(data[k], want) and not (want is NUM and isinstance(data[k], bool))
            if not ok:
                errs.append(f"{path}.{k} has wrong type {type(data[k]).__name__}")
    return errs


def check_result(name: str, env) -> list[str]:
    """Problems with a tool result; empty list means it looks sound."""
    if not isinstance(env, dict) or not isinstance(env.get("ok"), bool):
        return ["result is not an envelope {ok, data|error}"]
    if not env["ok"]:
        e = env.get("error")
        if not isinstance(e, dict) or not isinstance(e.get("code"), str):
            return ["error envelope without error.code"]
        if e["code"] not in ERROR_CODES:
            return [f"unknown error code {e['code']}"]
        return []
    if "data" not in env:
        return ["ok result without data"]
    spec = SHAPES.get(name)
    if not spec:
        return []
    data = env["data"]
    errs = _shape_errors(data, spec)
    if errs and len(spec) == 1:  # tolerate a flat object where the contract shows a wrapper
        (key, inner), = spec.items()
        if isinstance(inner, dict) and isinstance(data, dict) and not _shape_errors(data, inner):
            errs = []
    if not errs and name == "read_reply":
        for k in ("lease", "move_in", "phone", "occupants", "reason"):
            st = data[k].get("status")
            if st not in READER_STATUS:
                errs.append(f"data.{k}.status {st!r} not in {sorted(READER_STATUS)}")
        d = data["move_in"].get("date")
        if d is not None and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(d)):
            errs.append(f"data.move_in.date {d!r} is not YYYY-MM-DD")
    return errs


# --------------------------------------------------------------------------- 3. retry policy

@dataclass
class Decision:
    action: str               # "retry" | "fallback" | "feedback"
    delay_s: float = 0.0
    note: str = ""
    suggestion: str = ""
    alternatives: list[str] = field(default_factory=list)


def decide(name: str, args: dict, error: dict, attempt: int, *, max_retries: int, backoff_base_s: float,
           tried_channels: set[str] | None = None) -> Decision:
    code = error.get("code", "")
    hint = error.get("hint") or ""
    if name == "request_quote" and code == "TIMEOUT":
        return Decision("fallback", note="vendor did not respond",
                        suggestion="skip this vendor and request a quote from the next one")
    if code in FALLBACK:
        if name == "publish_listing":
            alts = [c for c in LISTING_CHANNELS if c not in (tried_channels or set())]
            return Decision("fallback", note=f"{args.get('channel')} automation is broken ({code})",
                            suggestion=("publish to " + ", ".join(alts) + " instead, and escalate the broken channel "
                                        "to the owner" if alts else "escalate the broken channel to the owner"),
                            alternatives=alts)
        return Decision("fallback", note=code, suggestion=hint or "use another route or escalate to the owner")
    if code in NO_RETRY:
        return Decision("feedback", note=f"{code}: {error.get('message', '')}",
                        suggestion=(hint or "do not repeat this call; change course or escalate_to_owner"))
    if (code in RETRYABLE or error.get("retryable")) and attempt < max_retries:
        return Decision("retry", delay_s=min(backoff_base_s * (2 ** attempt), 8.0), note=code)
    if code in RETRYABLE or error.get("retryable"):
        return Decision("feedback", note=f"{code} persisted after {attempt} retries",
                        suggestion=hint or "try a different approach or escalate_to_owner")
    return Decision("feedback", note=f"{code}: {error.get('message', '')}", suggestion=hint)


# --------------------------------------------------------------------------- loop guard

def signature(name: str, args) -> str:
    if isinstance(args, dict):
        return name + ":" + json.dumps(args, sort_keys=True, default=str)
    return name + ":raw:" + str(args)


class LoopGuard:
    def __init__(self, repeats: int = 3):
        self.repeats, self.fails, self.blocked, self.escalated = repeats, {}, set(), set()

    def failed(self, sig: str) -> bool:
        """Record a failure; True when this call has now failed `repeats` times."""
        self.fails[sig] = self.fails.get(sig, 0) + 1
        return self.fails[sig] >= self.repeats and sig not in self.escalated

    def count(self, sig: str) -> int:
        return self.fails.get(sig, 0)


def ref_from(args) -> str:
    if isinstance(args, dict):
        for k in ("thread_id", "listing_id", "job_id", "renter_id", "quote_id", "room_id", "vendor_id"):
            if isinstance(args.get(k), str):
                return args[k]
    return "run"


# --------------------------------------------------------------------------- 4. self-check

NEG = re.compile(r"\b(not|couldn't|could not|can't|cannot|failed|unable|didn't|did not|won't|no longer|pending)\b", re.I)


def _live_channels(state: dict) -> set[tuple[str, str]]:
    out = set()
    for l in state.get("listings", []) or []:
        for ch, post in (l.get("channels") or {}).items():
            if isinstance(post, dict) and post.get("status") in ("live", "ready_to_submit"):
                out.add((l.get("listing_id"), ch))
    return out


def _operator_msgs(state: dict) -> set[str]:
    out = set()
    threads = list(state.get("threads", []) or [])
    for ch in (state.get("channels") or {}).values():
        if isinstance(ch, dict):
            threads += ch.get("threads", []) or []
    for t in threads:
        for m in t.get("messages", []) or []:
            if m.get("from") == "operator":
                out.add(str(m.get("id")))
    return out


def _ids(state, coll, key, pred=lambda r: True):
    return {r.get(key) for r in state.get(coll, []) or [] if isinstance(r, dict) and pred(r)}


def self_check(before: dict, after: dict, ledger: list[dict], final_text: str) -> list[str]:
    """Claims vs world. `ledger` = successful executed calls [{name, args, data}]."""
    problems = []
    live = _live_channels(after)
    msgs = _operator_msgs(after)
    # (a) every successful call left its mark
    for c in ledger:
        n, a, d = c["name"], c["args"], c.get("data") or {}
        if n == "publish_listing" and (a.get("listing_id"), a.get("channel")) not in live:
            problems.append(f"publish_listing said ok but listing {a.get('listing_id')} is not live on {a.get('channel')}")
        elif n == "send_message" and d.get("message_id") and str(d["message_id"]) not in msgs:
            problems.append(f"send_message said ok but message {d['message_id']} is not in the thread")
        elif n == "propose_showing":
            eid = (d.get("event") or d).get("event_id")
            if eid not in _ids(after, "calendar", "event_id"):
                problems.append(f"propose_showing said ok but event {eid} is not on the calendar")
        elif n == "book_vendor":
            jid = (d.get("job") or d).get("job_id")
            if jid not in _ids(after, "jobs", "job_id", lambda j: j.get("status") in ("booked", "scheduled", "done")):
                problems.append(f"book_vendor said ok but job {jid} is not booked")
        elif n == "escalate_to_owner":
            eid = (d.get("escalation") or d).get("esc_id")
            if eid not in _ids(after, "escalations", "esc_id"):
                problems.append(f"escalation {eid} is missing from the world")

    # (b) claims in the final text are backed by new state
    new_live = live - _live_channels(before)
    new_msgs = msgs - _operator_msgs(before)
    new_events = _ids(after, "calendar", "event_id") - _ids(before, "calendar", "event_id")
    new_booked = (_ids(after, "jobs", "job_id", lambda j: j.get("status") == "booked")
                  - _ids(before, "jobs", "job_id", lambda j: j.get("status") == "booked"))
    new_esc = _ids(after, "escalations", "esc_id") - _ids(before, "escalations", "esc_id")
    for sent in re.split(r"(?<=[.!?\n])\s+", final_text or ""):
        low = sent.lower()
        if not low.strip() or NEG.search(low):
            continue
        if re.search(r"\b(posted|published|is live|went live|listed)\b", low):
            chans = [c for c in LISTING_CHANNELS if c in low]
            for ch in chans:
                if not any(c == ch for _, c in new_live | live):
                    problems.append(f"summary says the listing is live on {ch}, but it is not")
            if not chans and not new_live:
                problems.append("summary says a listing was posted, but nothing new is live")
        if re.search(r"\b(booked|hired)\b", low) and not new_booked:
            problems.append("summary says a vendor was booked, but no job is booked")
        if re.search(r"\bpropos(ed|e) (a )?(showing|time|tour)|\bscheduled (a )?(showing|tour)", low) and not new_events:
            problems.append("summary says a showing was proposed, but the calendar has no new event")
        if re.search(r"\bescalated\b", low) and not new_esc:
            problems.append("summary says something was escalated, but there is no new escalation")
        if re.search(r"\b(i (sent|replied|messaged|texted|answered))\b", low) and not new_msgs:
            problems.append("summary says a message was sent, but no operator message was added")
    return list(dict.fromkeys(problems))
