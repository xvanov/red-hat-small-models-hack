"""call(world, name, args): validate, inject faults, run, record events, return the envelope."""
from __future__ import annotations

import difflib
import json
from typing import Any, Callable

try:
    import jsonschema
except ImportError:  # minimal built-in validator keeps the package importable with zero deps
    jsonschema = None

from .errors import ToolError, ok
from .events import EventSink
from .faults import corrupt, corrupt_field, error_for, pick_fault
from .schemas import PARAMS
from .world import World

REGISTRY: dict[str, Callable[..., Any]] = {}
# Extra guidance appended to an INVALID_ARGS hint from argument validation.
ARG_HINTS = {"find_vendors": "give job_id from create_job, or the 5-digit zip from job.zip or get_room; never guess a zip"}


def tool(name: str):
    def deco(fn):
        assert name in PARAMS, f"{name} has no schema in schemas.PARAMS"
        REGISTRY[name] = fn
        return fn
    return deco


def _arg_summary(name: str) -> str:
    p = PARAMS[name]
    parts = []
    for k, v in p["properties"].items():
        t = v.get("type", "any")
        if "enum" in v:
            t = "|".join(v["enum"])
        parts.append(f"{k} ({t}{'' if k in p['required'] else ', optional'})")
    out = f"{name} args: " + (", ".join(parts) or "none")
    return f"{out}; {ARG_HINTS[name]}" if name in ARG_HINTS else out


def validate_args(name: str, args: Any) -> dict:
    if name not in PARAMS:
        close = difflib.get_close_matches(name, list(PARAMS), n=3)
        raise ToolError("INVALID_ARGS", f"unknown tool {name!r}",
                        hint=f"did you mean {', '.join(close)}?" if close else "see the tool list")
    if args is None:
        args = {}
    if isinstance(args, str):
        try:
            args = json.loads(args) if args.strip() else {}
        except json.JSONDecodeError as e:
            raise ToolError("INVALID_ARGS", f"{name}: arguments are not valid JSON ({e.msg})", hint=_arg_summary(name))
    if not isinstance(args, dict):
        raise ToolError("INVALID_ARGS", f"{name}: arguments must be a JSON object", hint=_arg_summary(name))
    schema = PARAMS[name]
    unknown = [k for k in args if k not in schema["properties"]]
    if unknown:
        raise ToolError("INVALID_ARGS", f"{name}: unknown argument(s) {', '.join(map(repr, unknown))}",
                        hint=_arg_summary(name))
    missing = [k for k in schema["required"] if k not in args or args[k] is None]
    if missing:
        raise ToolError("INVALID_ARGS", f"{name}: missing required argument(s) {', '.join(map(repr, missing))}",
                        hint=_arg_summary(name))
    first = _first_error(schema, args)
    if first:
        where, kind, value, instance, msg = first
        if kind == "pattern":
            msg = f"{instance!r} has the wrong format"
            if "T" in value:
                msg += " (expected YYYY-MM-DDTHH:MM)"
            elif r"\d{5}" in value:
                msg += " (expected a 5-digit ZIP)"
            else:
                msg += " (expected YYYY-MM-DD)"
        raise ToolError("INVALID_ARGS", f"{name}: argument {where}: {msg}", hint=_arg_summary(name))
    return args


_TYPES = {"string": str, "number": (int, float), "integer": int, "boolean": bool, "array": list, "object": dict}


def _first_error(schema: dict, args: dict):
    """(where, validator, validator_value, instance, message) for the first problem, or None."""
    if jsonschema is not None:
        errors = sorted(jsonschema.Draft202012Validator(schema).iter_errors(args), key=lambda e: list(e.path))
        if not errors:
            return None
        e = errors[0]
        return ".".join(str(p) for p in e.path) or "(args)", e.validator, e.validator_value, e.instance, e.message
    import re
    for k, v in args.items():
        ps = schema["properties"][k]
        t = ps.get("type")
        if t and (not isinstance(v, _TYPES[t]) or (t in ("number", "integer") and isinstance(v, bool))):
            return k, "type", t, v, f"{v!r} is not of type {t!r}"
        if "enum" in ps and v not in ps["enum"]:
            return k, "enum", ps["enum"], v, f"{v!r} is not one of {ps['enum']}"
        if "pattern" in ps and not re.search(ps["pattern"], v):
            return k, "pattern", ps["pattern"], v, "bad format"
        if "minimum" in ps and v < ps["minimum"]:
            return k, "minimum", ps["minimum"], v, f"{v} is less than {ps['minimum']}"
        if t == "array" and "items" in ps:
            it = ps["items"].get("type")
            for x in v:
                if it and not isinstance(x, _TYPES[it]):
                    return k, "type", it, x, f"{x!r} is not of type {it!r}"
    return None


def call(world: World, name: str, args: Any = None, *, sink: EventSink | None = None,
         actor: str = "operator", call_id: str | None = None) -> dict:
    """Run one tool. Never raises for tool-level problems; returns {"ok":..., "data"|"error":...}."""
    from . import impl  # noqa: F401  (registers tools)
    sink = sink if sink is not None else getattr(world, "sink", None)
    base = {"tool": name, "call_id": call_id}
    if sink:
        sink.emit("tool_call", actor, {**base, "args": args})
    fault = None
    try:
        args = validate_args(name, args)
        fault = pick_fault(world, name, args)
        if fault and fault["kind"] != "malformed":
            raise error_for(fault["kind"], name)
        data = REGISTRY[name](world, **args)
        result = ok(data)
        if fault:  # malformed: the action happened, the response is garbage
            result = ok(corrupt_field(data, fault["field"], fault.get("field_mode", "wrong_type"))
                        if fault.get("field") else corrupt(data))
    except ToolError as e:
        result = e.envelope()
    except Exception as e:  # a bug in a tool must not crash the agent loop
        result = ToolError("UPSTREAM_ERROR", f"{name}: internal error {type(e).__name__}: {e}", retryable=False).envelope()
    if sink:
        sink.emit("tool_result", "system", {**base, "result": result, "fault": fault["kind"] if fault else None})
        if result["ok"] and name == "escalate_to_owner":
            sink.emit("escalation", actor, result["data"])
        if result["ok"] and name == "report_to_owner":
            sink.emit("owner_message", actor, {"summary": args.get("summary")})
    return result
