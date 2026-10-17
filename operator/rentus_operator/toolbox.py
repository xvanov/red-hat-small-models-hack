"""Adapter over the tools package.

Uses rentus_tools (W3) when importable, otherwise the local shim. Set
RENTUS_TOOLS_BACKEND=shim to force the shim (the offline tests do this), or
=real to require the real package. Everything the operator needs from the tools
side goes through this module.

Both backends share one convention: call(world, name, args, sink=, actor=,
call_id=) runs the tool AND emits tool_call / tool_result / escalation /
owner_message events to the sink, so the loop never emits those itself.
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


# P2.1 (c): description variant "v2" = the verbose set with these overrides. Lives here, not in tools/,
# so the tools package stays fixed; it applies to the local loop and the NeMo rollouts alike.
DESCRIPTIONS_V2 = {
    "send_message": ("The ONLY way a renter or tenant sees anything you write: plain assistant text is never "
                     "delivered. Every reply to a renter is one send_message call. Style rules are enforced: at most "
                     "2 sentences (a greeting like 'Hi Sam!' counts as one), at most one question mark, no em or en "
                     "dashes, no dollar figure or lease term that is not in the room or listing record. Ask for one "
                     "missing item at a time; the renter's answer comes back in data.replies."),
    "check_listing_compliance": ("Required before create_listing and before any publish_listing: check the exact "
                                 "title and body against fair-housing advertising rules (24 CFR 100.75). Returns "
                                 "findings with a suggested rewrite for each problem phrase; use the rewrites."),
    "request_quote": ("Ask one vendor for a quote on a job. Ask at least two vendors. Returns TIMEOUT if the vendor "
                      "does not respond; then ask another vendor."),
    "upsert_renter": ("Create or update the renter record for a thread. Call it after every renter answer (and for "
                      "facts the renter volunteered in the first message). Put gate answers from read_reply under "
                      "fields.gate (lease, move_in, phone, occupants, reason) and preferences under fields.wants."),
}


def tool_schemas(be: ModuleType, variant: str = "verbose", reader: bool = True) -> list[dict]:
    """OpenAI tool schemas with the description variant applied."""
    if variant == "v2":
        tools = tool_schemas(be, "verbose", reader)
        for t in tools:
            f = t["function"]
            if f["name"] in DESCRIPTIONS_V2:
                f["description"] = DESCRIPTIONS_V2[f["name"]]
        return tools
    tools = None
    fn = getattr(be, "tool_schemas", None)
    if callable(fn) and be is not shim:
        try:
            tools = fn(variant)
        except (KeyError, TypeError):
            tools = None
    native = tools is not None
    tools = copy.deepcopy(tools if native else be.TOOLS)
    if not reader:
        tools = [t for t in tools if t["function"]["name"] != "read_reply"]
    if variant == "terse" and not native:
        for t in tools:
            f = t["function"]
            f["description"] = _first_sentence(f.get("description", ""))
            for p in f.get("parameters", {}).get("properties", {}).values():
                p.pop("description", None)
    return tools


def _first_sentence(s: str) -> str:
    m = re.match(r"(.+?[.!?])(\s|$)", s.strip())
    return m.group(1) if m else s.strip()


def call(be: ModuleType, world, name: str, args: dict, *, sink=None, actor: str = "operator",
         call_id: str | None = None) -> dict:
    return be.call(world, name, args, sink=sink, actor=actor, call_id=call_id)


def state(world) -> dict:
    """The world's state as a plain dict (a copy for the real World)."""
    if isinstance(world, dict):
        return world
    for meth in ("to_dict", "snapshot"):
        f = getattr(world, meth, None)
        if callable(f):
            v = f()
            if isinstance(v, dict):
                return v
    raise TypeError(f"cannot read state from {type(world).__name__}")


def snapshot(world) -> dict:
    return copy.deepcopy({k: v for k, v in state(world).items() if not str(k).startswith("_")})


def today(world) -> str | None:
    c = state(world).get("clock")
    if isinstance(c, dict):
        c = c.get("now")
    return str(c)[:10] if c else None


def add_room(world, room: dict) -> bool:
    """Add a room record if no room has that room_id. Works on both backends."""
    rooms = world["rooms"] if isinstance(world, dict) else getattr(world, "rooms")
    if any(r.get("room_id") == room.get("room_id") for r in rooms):
        return False
    room = copy.deepcopy(room)
    room.setdefault("address_public", room.get("address"))
    rooms.append(room)
    return True


def new_world(be: ModuleType, patch: dict | None = None):
    return be.load(patch=patch)


def make_sink(be: ModuleType, run_id: str, path=None, on_event=None):
    Sink = getattr(be, "EventSink", None) or shim.EventSink
    sink = Sink(run_id=run_id, path=path)
    if on_event is not None:
        if hasattr(sink, "subscribers"):
            sink.subscribers.append(on_event)
        else:
            sink.on_event = on_event
    return sink


def emit(sink, type: str, actor: str, data: dict):
    if sink is None:
        return None
    return sink.emit(type, actor, data)
