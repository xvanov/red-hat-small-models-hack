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
        m = self.mod
        patch = copy.deepcopy(patch or {})
        if self.name == "shim":
            return _apply_patch(m.new_world({}), patch)
        W = getattr(m, "World", None)
        if W is not None:
            for ctor in ("from_scenario", "load"):
                f = getattr(W, ctor, None)
                if f is None:
                    continue
                try:
                    return f(patch) if ctor == "from_scenario" else _apply_patch(f(INVENTORY), patch)
                except TypeError:
                    continue
            try:
                return _apply_patch(W(), patch)
            except TypeError:
                pass
        if hasattr(m, "new_world"):
            return m.new_world(patch)
        raise RuntimeError("cannot construct a World from rentus_tools")

    def call(self, world, name: str, args: dict) -> dict:
        return self.mod.call(world, name, args)

    def tool_names(self) -> list[str]:
        return [t["function"]["name"] if "function" in t else t["name"] for t in self.TOOLS]


def state(world) -> dict:
    """The world's JSON document, whatever object wraps it."""
    if isinstance(world, dict):
        return world
    for attr in ("state", "data", "doc", "_state"):
        v = getattr(world, attr, None)
        if isinstance(v, dict):
            return v
    if hasattr(world, "to_dict"):
        return world.to_dict()
    raise TypeError(f"cannot read world state from {type(world).__name__}")


def snapshot(world) -> dict:
    s = state(world)
    return json.loads(json.dumps({k: v for k, v in s.items() if not str(k).startswith("_")}, default=str))


def _apply_patch(world, patch: dict):
    s = state(world)
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(s.get(k), dict) and k != "policy":
            s[k].update(v)
        elif k == "policy" and isinstance(s.get(k), dict):
            s[k].update(v)
        else:
            s[k] = v
    return world
