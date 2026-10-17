"""Find the sandbox tools.

Prefers the real `rentus_tools` package (tools/, W3). Falls back to the operator's local shim
(operator/rentus_operator/shim.py) so the gym runs before W3 lands. Either way the interface
is the contract's: TOOLS (OpenAI function format) and call(world, name, args) -> envelope.
"""
from __future__ import annotations

import copy
import importlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
INVENTORY = REPO / "data" / "published" / "inventory.json"

for p in (REPO / "tools", REPO / "operator"):
    if p.exists() and str(p) not in sys.path:
        sys.path.insert(0, str(p))


class Backend:
    """Uniform access to whichever tool package is present."""

    def __init__(self, prefer: str = "auto"):
        self.name, self.mod = self._load(prefer)
        self.TOOLS = list(self.mod.TOOLS)

    @staticmethod
    def _load(prefer):
        order = {"auto": ["rentus_tools", "shim"], "tools": ["rentus_tools"], "shim": ["shim"]}[prefer]
        errors = []
        for name in order:
            try:
                if name == "rentus_tools":
                    mod = importlib.import_module("rentus_tools")
                    if not hasattr(mod, "call") or not hasattr(mod, "TOOLS"):
                        raise ImportError("rentus_tools has no call/TOOLS yet")
                else:
                    mod = importlib.import_module("rentus_operator.shim")
                return name, mod
            except Exception as e:  # noqa: BLE001 - report every reason
                errors.append(f"{name}: {e}")
        raise ImportError("no sandbox tools available: " + "; ".join(errors))

    # ---- world -------------------------------------------------------------------------------
    def new_world(self, patch: dict | None):
        patch = copy.deepcopy(patch or {})
        if self.name == "shim":
            patch = _unwrap_replace(patch)
            if isinstance(patch.get("clock"), dict):
                patch["clock"] = patch["clock"].get("now")
            return _apply_patch(self.mod.new_world({}), patch)
        return self.mod.load(patch=patch)

    def call(self, world, name: str, args: dict, **kw) -> dict:
        if self.name == "shim":
            return self.mod.call(world, name, args)
        return self.mod.call(world, name, args, **kw)

    def tool_names(self) -> list[str]:
        return [t["function"]["name"] if "function" in t else t["name"] for t in self.TOOLS]

    def tool_schemas(self, variant: str = "verbose") -> list[dict]:
        fn = getattr(self.mod, "tool_schemas", None)
        if callable(fn) and self.name != "shim":
            return fn(variant)
        return copy.deepcopy(self.TOOLS)

    # live (mutable) views of world collections
    @staticmethod
    def coll(world, key: str):
        return world.setdefault(key, []) if isinstance(world, dict) else getattr(world, key)

    @staticmethod
    def now(world) -> str:
        c = world.get("clock") if isinstance(world, dict) else world.clock
        return c.get("now") if isinstance(c, dict) else str(c or "")

    def gate_complete(self, world, renter: dict) -> bool:
        fn = getattr(self.mod, "gate_complete", None)
        if fn is not None and self.name != "shim" and renter.get("renter_id"):
            return bool(fn(world, renter["renter_id"]))
        from .session import gate_complete
        return gate_complete(renter)


def _unwrap_replace(v):
    if isinstance(v, dict):
        if set(v) == {"$replace"}:
            return _unwrap_replace(v["$replace"])
        return {k: _unwrap_replace(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_unwrap_replace(x) for x in v]
    return v


def state(world) -> dict:
    """The world's JSON document, whatever object wraps it."""
    if isinstance(world, dict):
        return world
    if hasattr(world, "to_dict"):
        return world.to_dict()  # a copy: read-only use
    raise TypeError(f"cannot read world state from {type(world).__name__}")


def snapshot(world) -> dict:
    s = state(world)
    return json.loads(json.dumps({k: v for k, v in s.items() if not str(k).startswith("_")}, default=str))


def _apply_patch(world: dict, patch: dict):
    s = world
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(s.get(k), dict) and k != "policy":
            s[k].update(v)
        elif k == "policy" and isinstance(s.get(k), dict):
            s[k].update(v)
        else:
            s[k] = v
    return world
