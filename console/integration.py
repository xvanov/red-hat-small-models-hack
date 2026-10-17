"""Seams to the parallel workstreams: operator (W2), tools (W3), gym (W4), serving (W1).

Everything here is defensive: the other packages are being written at the same time,
so each import and each call is guarded, and the console falls back to its stub driver.
"""
from __future__ import annotations

import importlib
import inspect
import json
import os
import sys
import threading
import time
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parent.parent
RUNS = Path(os.environ.get("CONSOLE_RUNS_DIR") or REPO / "runs")
RESULTS = REPO / "results"
TASKS = REPO / "gym" / "tasks"
LIVE_LABEL = "live: Nemotron 3.5 Lightning on vLLM"

try:
    from dotenv import load_dotenv
    load_dotenv(REPO / ".env", override=False)
except Exception:
    pass

# Package folders from contract section 1; append (not insert) so nothing shadows stdlib.
for sub in ("tools", "operator", "gym"):
    p = REPO / sub
    if p.is_dir() and str(p) not in sys.path:
        sys.path.append(str(p))
if str(REPO) not in sys.path:
    sys.path.append(str(REPO))


def try_import(name: str):
    try:
        return importlib.import_module(name), None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


# ---------------- model badge ----------------
_badge_cache: dict = {"at": 0.0, "value": None}


def probe_backend(force: bool = False) -> dict:
    """Is OPERATOR_BASE_URL serving? Cached for 10 s."""
    if not force and _badge_cache["value"] and time.time() - _badge_cache["at"] < 10:
        return _badge_cache["value"]
    base = os.environ.get("OPERATOR_BASE_URL", "").rstrip("/")
    value = {"live": False, "label": "stub", "base_url_set": bool(base), "models": []}
    if base:
        try:
            r = httpx.get(base + "/models", timeout=1.5,
                          headers={"Authorization": "Bearer " + os.environ.get("OPERATOR_API_KEY", "none")})
            if r.status_code == 200:
                ids = [m.get("id") for m in r.json().get("data", [])]
                value = {"live": True, "label": LIVE_LABEL, "base_url_set": True, "models": ids}
        except Exception:
            pass
    op, err = try_import("rentus_operator")
    value["backend_up"] = value["live"]
    value["operator_package"] = op is not None
    value["operator_import_error"] = None if op else err
    if not op:
        value["live"] = False
        value["label"] = ("stub driver (vLLM is up, operator package not importable yet)"
                          if value["backend_up"] else "stub (console driver)")
    _badge_cache.update(at=time.time(), value=value)
    return value


# ---------------- scenarios ----------------
def list_scenarios() -> list[dict]:
    out = []
    if not TASKS.is_dir():
        return out
    for f in sorted(TASKS.glob("*.jsonl")):
        for i, line in enumerate(f.read_text().splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                t = json.loads(line)
            except json.JSONDecodeError:
                continue
            out.append({"id": t.get("id", f"{f.stem}-{i}"), "file": f.name, "split": t.get("split", f.stem),
                        "category": t.get("category"), "owner_instruction": t.get("owner_instruction"),
                        "n_counterparts": len(t.get("counterparts") or []), "task": t})
    return out


def get_scenario(sid: str) -> dict | None:
    return next((s["task"] for s in list_scenarios() if s["id"] == sid), None)


# ---------------- scoreboard ----------------
def _rate(d: dict):
    for k in ("pass_rate", "task_pass_rate", "score", "accuracy"):
        if isinstance(d.get(k), (int, float)):
            return d[k]
    if isinstance(d.get("passed"), (int, float)) and d.get("total"):
        return d["passed"] / d["total"]
    return None


def scoreboard() -> list[dict]:
    rows = []
    if not RESULTS.is_dir():
        return rows
    for f in sorted(RESULTS.glob("*/summary.json")):
        try:
            d = json.loads(f.read_text())
        except Exception as e:
            rows.append({"name": f.parent.name, "error": str(e)})
            continue
        checks = d.get("per_check") or d.get("checks") or d.get("per_check_rates") or {}
        if isinstance(checks, list):
            checks = {c.get("type") or c.get("name"): _rate(c) for c in checks if isinstance(c, dict)}
        name = f.parent.name
        rows.append({"name": name, "label": d.get("label") or d.get("variant") or name,
                     "kind": "baseline" if "baseline" in name.lower() or d.get("baseline") else "improved",
                     "split": d.get("split"), "model": d.get("model"),
                     "pass_rate": _rate(d), "n_tasks": d.get("n_tasks") or d.get("total"),
                     "checks": {k: v for k, v in checks.items() if isinstance(v, (int, float))},
                     "mtime": f.stat().st_mtime})
    return rows


# ---------------- world helpers (operator mode) ----------------
def world_to_dict(world) -> dict:
    for attr in ("to_dict", "snapshot", "dump", "as_dict"):
        fn = getattr(world, attr, None)
        if callable(fn):
            try:
                d = fn()
                if isinstance(d, dict):
                    return json.loads(json.dumps(d, default=str))
            except Exception:
                pass
    for attr in ("state", "data"):
        d = getattr(world, attr, None)
        if isinstance(d, dict):
            return json.loads(json.dumps(d, default=str))
    if isinstance(world, dict):
        return json.loads(json.dumps(world, default=str))
    return json.loads(json.dumps(getattr(world, "__dict__", {}), default=str))


def world_faults(world) -> list:
    if isinstance(world, dict):
        return world.setdefault("faults", [])
    f = getattr(world, "faults", None)
    if f is None:
        for attr in ("state", "data"):
            d = getattr(world, attr, None)
            if isinstance(d, dict):
                return d.setdefault("faults", [])
        world.faults = f = []
    return f


def _call_flex(fn, positional: dict, optional: dict):
    """Call fn mapping our names onto whatever parameters it declares."""
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return fn(*positional.values())
    params = sig.parameters
    has_kw = any(p.kind == p.VAR_KEYWORD for p in params.values())
    kwargs = {k: v for k, v in {**positional, **optional}.items() if k in params or has_kw}
    return fn(**kwargs)


class OperatorRun:
    """Runs the real rentus_operator.run(...) in a thread against a rentus_tools World."""
    mode = "operator"

    def __init__(self, run_id: str, run_dir: Path, goal: str, scenario: dict | None, speed: float, op, tools):
        self.run_id, self.run_dir, self.goal, self.scenario, self.speed = run_id, Path(run_dir), goal, scenario, speed
        self.op, self.tools = op, tools
        self.status = "starting"
        self.error = None
        self.lock = threading.RLock()
        self.world = self._make_world()
        self.thread = threading.Thread(target=self._main, name=f"op-{run_id}", daemon=True)

    def _make_world(self):
        World = getattr(self.tools, "World", None) or getattr(importlib.import_module("rentus_tools.world"), "World")
        patch = (self.scenario or {}).get("initial_state") or {}
        for ctor in ("from_scenario", "load"):
            fn = getattr(World, ctor, None)
            if callable(fn):
                try:
                    if ctor == "from_scenario" and self.scenario:
                        w = fn(self.scenario)
                    else:
                        w = _call_flex(fn, {}, {"patch": patch, "initial_state": patch,
                                                "run_id": self.run_id, "run_dir": str(self.run_dir),
                                                "events_path": str(self.run_dir / "events.jsonl")})
                    break
                except Exception:
                    continue
        else:
            w = World()
        faults = world_faults(w)
        faults.extend((self.scenario or {}).get("faults") or [])
        for attr, val in (("run_id", self.run_id), ("events_path", str(self.run_dir / "events.jsonl"))):
            try:
                if getattr(w, attr, None) in (None, ""):
                    setattr(w, attr, val)
            except Exception:
                pass
        return w

    def _client(self):
        badge = probe_backend()
        model = os.environ.get("OPERATOR_MODEL") or (badge["models"][0] if badge["models"] else "stub")
        if badge["live"]:
            for name in ("make_client", "client_for", "OpenAIClient"):
                fn = getattr(self.op, name, None)
                if callable(fn):
                    return _call_flex(fn, {}, {"base_url": os.environ["OPERATOR_BASE_URL"],
                                               "api_key": os.environ.get("OPERATOR_API_KEY", "none")}), model
            from openai import OpenAI  # noqa: WPS433 (only if operator exposes no factory)
            return OpenAI(base_url=os.environ["OPERATOR_BASE_URL"], api_key=os.environ.get("OPERATOR_API_KEY", "none")), model
        for name in ("StubClient", "StubModel", "stub_client", "make_stub_client"):
            fn = getattr(self.op, name, None)
            if callable(fn):
                return _call_flex(fn, {}, {"scenario": self.scenario}), "stub"
        stub_mod, _ = try_import("rentus_operator.stub")
        for name in ("StubClient", "StubModel", "make_client"):
            fn = getattr(stub_mod, name, None) if stub_mod else None
            if callable(fn):
                return _call_flex(fn, {}, {"scenario": self.scenario}), "stub"
        return None, "stub"

    def _main(self):
        self.status = "running"
        try:
            client, model = self._client()
            RunConfig = getattr(self.op, "RunConfig", None)
            opts = {"run_id": self.run_id, "runs_dir": str(self.run_dir.parent), "run_dir": str(self.run_dir),
                    "events_path": str(self.run_dir / "events.jsonl"), "speed": self.speed,
                    "max_turns": (self.scenario or {}).get("max_turns", 30), "scenario": self.scenario,
                    "counterparts": (self.scenario or {}).get("counterparts")}
            cfg = _call_flex(RunConfig, {}, opts) if RunConfig else None
            _call_flex(self.op.run, {"world": self.world, "goal": self.goal, "client": client, "model": model},
                       {"config": cfg, "cfg": cfg, "run_config": cfg} if cfg else opts)
            self.status = "idle"
        except Exception as e:
            self.error = f"{type(e).__name__}: {e}"
            self.status = "error"
            with (self.run_dir / "console.jsonl").open("a") as f:
                f.write(json.dumps({"type": "fallback", "actor": "system",
                                    "data": {"reason": "operator run crashed: " + self.error}}) + "\n")
        finally:
            self.save()

    def start(self):
        self.thread.start()

    def stop(self):
        stop = getattr(self.world, "stop", None) or getattr(self.op, "stop", None)
        if callable(stop):
            try:
                stop()
            except Exception:
                pass

    def snapshot(self) -> dict:
        with self.lock:
            return world_to_dict(self.world)

    def save(self):
        try:
            (self.run_dir / "world.json").write_text(json.dumps(self.snapshot(), indent=1, default=str))
        except Exception:
            pass

    def inject_fault(self, fault: dict):
        with self.lock:
            world_faults(self.world).append(fault)

    def owner_say(self, text: str):
        self._owner_inbox({"type": "owner_message", "text": text})

    def decide(self, esc_id: str, approve: bool, note: str = ""):
        self._owner_inbox({"type": "decision", "esc_id": esc_id, "approve": approve, "note": note})

    def _owner_inbox(self, msg: dict):
        """Deliver to the operator: a hook if it exposes one, else world.owner_inbox."""
        for name in ("owner_message", "deliver_owner_message", "owner_input"):
            fn = getattr(self.op, name, None)
            if callable(fn):
                try:
                    _call_flex(fn, {"world": self.world, "message": msg}, {"run_id": self.run_id})
                    return
                except Exception:
                    pass
        with self.lock:
            inbox = getattr(self.world, "owner_inbox", None)
            if inbox is None and isinstance(self.world, dict):
                inbox = self.world.setdefault("owner_inbox", [])
            elif inbox is None:
                try:
                    self.world.owner_inbox = inbox = []
                except Exception:
                    inbox = []
            inbox.append(msg)

    def set_speed(self, speed: float):
        self.speed = speed
        for obj in (self.world,):
            try:
                obj.speed = speed
            except Exception:
                pass
