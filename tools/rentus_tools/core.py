"""call(world, name, args): validate, inject faults, run, record events, return the envelope."""
from __future__ import annotations

import difflib
import json
from typing import Any, Callable

import jsonschema

from .errors import ToolError, ok
from .events import EventSink
from .faults import corrupt, error_for, pick_fault
from .schemas import PARAMS
from .world import World

REGISTRY: dict[str, Callable[..., Any]] = {}


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
    return f"{name} args: " + (", ".join(parts) or "none")


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
    errors = sorted(jsonschema.Draft202012Validator(schema).iter_errors(args), key=lambda e: list(e.path))
    if errors:
        e = errors[0]
        where = ".".join(str(p) for p in e.path) or "(args)"
        msg = e.message
        if e.validator == "pattern":
            msg = f"{e.instance!r} has the wrong format"
            if "T" in e.validator_value:
                msg += " (expected YYYY-MM-DDTHH:MM)"
            elif r"\d{5}" in e.validator_value:
                msg += " (expected a 5-digit ZIP)"
            else:
                msg += " (expected YYYY-MM-DD)"
        raise ToolError("INVALID_ARGS", f"{name}: argument {where}: {msg}", hint=_arg_summary(name))
    return args


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
            result = ok(corrupt(data))
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
