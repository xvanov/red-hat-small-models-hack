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


