"""Adapter over the tools package.

Uses rentus_tools (W3) when importable, otherwise the local shim. Set
RENTUS_TOOLS_BACKEND=shim to force the shim (the offline tests do this).
Everything the operator needs from the tools side goes through this module, so
when the real package lands only this file has to follow its API.
"""
from __future__ import annotations

import copy
import os
import re
from types import ModuleType

from . import shim


def backend(name: str | None = None) -> ModuleType:
    choice = name or os.environ.get("RENTUS_TOOLS_BACKEND", "auto")
    if choice != "shim":
        try:
            import rentus_tools  # type: ignore
            return rentus_tools
        except ImportError:
            if choice == "real":
                raise
    return shim


def tool_schemas(be: ModuleType, variant: str = "verbose", reader: bool = True) -> list[dict]:
    """OpenAI tool schemas, with the description variant applied."""
    getter = getattr(be, "tools_for", None)
    tools = None
    if callable(getter):
        try:
            tools = getter(variant)
        except TypeError:
            tools = None
    tools = copy.deepcopy(tools if tools is not None else be.TOOLS)
    if not reader:
        tools = [t for t in tools if t["function"]["name"] != "read_reply"]
    if variant == "terse":
        for t in tools:
            f = t["function"]
            f["description"] = _first_sentence(f.get("description", ""))
            for p in f.get("parameters", {}).get("properties", {}).values():
                p.pop("description", None)
    return tools


def _first_sentence(s: str) -> str:
    m = re.match(r"(.+?[.!?])(\s|$)", s.strip())
    return m.group(1) if m else s.strip()


def call(be: ModuleType, world, name: str, args: dict) -> dict:
    return be.call(world, name, args)


def state(world) -> dict:
    """The world's state as a plain dict, whatever the World class looks like."""
    if isinstance(world, dict):
        return world
    for attr in ("state", "data", "doc"):
        v = getattr(world, attr, None)
        if isinstance(v, dict):
            return v
    for meth in ("to_dict", "snapshot"):
        f = getattr(world, meth, None)
        if callable(f):
            v = f()
            if isinstance(v, dict):
                return v
    raise TypeError(f"cannot read state from {type(world).__name__}")


def snapshot(world) -> dict:
    return copy.deepcopy({k: v for k, v in state(world).items() if not str(k).startswith("_")})


def new_world(be: ModuleType, patch: dict | None = None):
    for ctor in ("new_world", "load_world"):
        f = getattr(be, ctor, None)
        if callable(f):
            return f(patch) if patch is not None else f()
    W = getattr(be, "World", None)
    if W is not None:
        for m in ("load", "from_inventory", "default"):
            f = getattr(W, m, None)
            if callable(f):
                try:
                    return f(patch=patch) if patch else f()
                except TypeError:
                    continue
        return W()
    return shim.new_world(patch)


def make_sink(be: ModuleType, run_id: str, path=None, on_event=None):
    Sink = getattr(be, "EventSink", None) or shim.EventSink
    try:
        return Sink(run_id=run_id, path=path, on_event=on_event)
    except TypeError:
        try:
            return Sink(run_id, path)
        except TypeError:
            return shim.EventSink(run_id=run_id, path=path, on_event=on_event)


def emit(sink, type: str, actor: str, data: dict):
    if sink is None:
        return None
    fn = getattr(sink, "emit", None)
    if callable(fn):
        try:
            return fn(type=type, actor=actor, data=data)
        except TypeError:
            return fn({"type": type, "actor": actor, "data": data})
    if callable(sink):
        return sink({"type": type, "actor": actor, "data": data})
    return None
