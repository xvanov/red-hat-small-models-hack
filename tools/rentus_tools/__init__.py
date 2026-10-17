"""rentus_tools: sandbox tools for the Rentus Operator (contracts/tools.md).

    import rentus_tools as rt
    world = rt.load(patch=task["initial_state"])
    world.faults = task.get("faults", [])
    sink = rt.EventSink.for_run("r_abc")
    result = rt.call(world, "list_rooms", {"area": "Durham"}, sink=sink)
    tools = rt.tool_schemas("verbose")   # or rt.TOOLS
"""
from .core import REGISTRY, call, validate_args
from .errors import ToolError
from .events import EventSink
from .schemas import DESCRIPTIONS, PARAMS, TOOL_NAMES, TOOLS, tool_schemas
from .world import World, diff, get_path, load, load_file
from . import impl  # noqa: F401  (registers every tool)

__all__ = ["call", "validate_args", "REGISTRY", "ToolError", "EventSink", "TOOLS", "TOOL_NAMES", "PARAMS",
           "DESCRIPTIONS", "tool_schemas", "World", "load", "load_file", "diff", "get_path", "gate_complete"]


def gate_complete(world: World, renter_id: str) -> bool:
    """True when propose_showing would accept this renter's gate (scorers use this)."""
    from .impl.register import gate_missing
    r = world.get("register", renter_id)
    return bool(r) and not gate_missing(r)
