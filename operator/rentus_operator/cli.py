r"""Run the operator on one instruction against the sandbox world and print a trace.

    python -m rentus_operator.cli "Appling Way room free Nov 1, \$750, private bath"
    python -m rentus_operator.cli --stub "..."          # scripted model, no GPU
    python -m rentus_operator.cli --no-verifier --tools terse "..."   # ablations
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

from . import toolbox
from .config import RunConfig
from .loop import run

REPO = Path(__file__).resolve().parents[2]
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "appling_way.json"

C = {"dim": "\033[2m", "b": "\033[1m", "red": "\033[31m", "grn": "\033[32m", "yel": "\033[33m", "cya": "\033[36m",
     "mag": "\033[35m", "x": "\033[0m"}


def load_env():
    """Read OPERATOR_* from the repo .env without printing anything."""
    p = REPO / ".env"
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip().removeprefix("export ").strip()
        if k.startswith("OPERATOR_") and k not in os.environ:
            os.environ[k] = v.strip().strip('"').strip("'")


def probe(base_url: str, api_key: str) -> list[str] | None:
    try:
        req = urllib.request.Request(base_url.rstrip("/") + "/models", headers={"Authorization": f"Bearer {api_key}"})
        with urllib.request.urlopen(req, timeout=3) as r:
            return [m["id"] for m in json.load(r).get("data", [])]
    except Exception:
        return None


def _short(v, n=160):
    s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, default=str)
    return s if len(s) <= n else s[: n - 1] + "…"


def printer(color: bool):
    c = C if color else {k: "" for k in C}

    def show(ev):
        t, d = ev["type"], ev.get("data", {})
        if t == "owner_message":
            if d.get("summary") is not None:
                print(f"  {c['b']}report -> owner{c['x']}: {d['summary']}")
            else:
                print(f"{c['b']}OWNER{c['x']}  {d.get('text')}")
        elif t == "model_message":
            if d.get("reasoning"):
                print(f"  {c['dim']}think: {_short(d['reasoning'], 120)}{c['x']}")
            if d.get("text"):
                print(f"{c['cya']}OPERATOR{c['x']}  {d['text']}")
        elif t == "tool_call":
            att = f" (attempt {d['attempt'] + 1})" if d.get("attempt") else ""
            print(f"  {c['mag']}->{c['x']} {d['tool']}({_short(d.get('args'), 140)}){att}")
        elif t == "tool_result":
            r = d.get("result") or {}
            if r.get("ok"):
                print(f"     {c['grn']}ok{c['x']} {c['dim']}{_short(r.get('data'), 140)}{c['x']}")
            else:
                e = r.get("error") or {}
                print(f"     {c['red']}{e.get('code')}{c['x']} {e.get('message')}")
        elif t == "verifier":
            if d.get("ok") and d.get("stage") == "self-check":
                print(f"  {c['grn']}verifier: self-check passed{c['x']}")
            elif not d.get("ok", True) or d.get("repaired") or d.get("action"):
                bits = d.get("problems") or d.get("repaired") or [f"{d.get('code')} -> {d.get('action')}"]
                print(f"  {c['yel']}verifier[{d.get('stage')}]: {_short('; '.join(map(str, bits)), 200)}{c['x']}")
        elif t in ("retry", "fallback"):
            print(f"  {c['yel']}{t}: {_short({k: v for k, v in d.items() if k != 'tool'}, 200)}{c['x']}")
        elif t == "escalation":
            tag = "forced " if d.get("forced") else ""
            print(f"  {c['red']}{tag}escalation{c['x']} -> owner: {_short(d.get('reason'), 180)}")
    return show


class Tee:
    def __init__(self, inner, show):
        self.inner, self.show, self.events = inner, show, []

    def emit(self, type, actor, data):
        ev = toolbox.emit(self.inner, type, actor, data) or {"type": type, "actor": actor, "data": data}
        ev = ev if isinstance(ev, dict) else {"type": type, "actor": actor, "data": data}
        self.events.append(ev)
        self.show(ev)
        return ev


def build_world(be, patch_path: str | None, fixture: bool):
    patch = json.loads(Path(patch_path).read_text()) if patch_path else None
    world = toolbox.new_world(be, patch)
    if fixture and FIXTURE.exists():
        rooms = toolbox.state(world).get("rooms", [])
        if not any("appling" in str(r.get("address", "")).lower() for r in rooms):
            toolbox.add_room(world, json.loads(FIXTURE.read_text())["room"])
    return world


def main(argv=None) -> int:
    load_env()
    ap = argparse.ArgumentParser(prog="rentus_operator.cli", description=__doc__.splitlines()[0])
    ap.add_argument("instruction")
    ap.add_argument("--stub", action="store_true", help="use the scripted stub model (no endpoint)")
    ap.add_argument("--prompt", default="v1")
    ap.add_argument("--tools", choices=["verbose", "terse"], default="verbose")
    ap.add_argument("--no-verifier", action="store_true")
    ap.add_argument("--no-reader", action="store_true")
    ap.add_argument("--reasoning", choices=["on", "off", "default"], default="default")
    ap.add_argument("--max-steps", type=int, default=30)
    ap.add_argument("--world", help="JSON patch over the inventory (scenario initial_state)")
    ap.add_argument("--no-fixture", action="store_true", help="do not add the fictional Appling Way room")
    ap.add_argument("--backend", choices=["auto", "shim", "real"], default="auto")
    ap.add_argument("--no-color", action="store_true")
    a = ap.parse_args(argv)

    cfg = RunConfig(prompt_version=a.prompt, tool_descriptions=a.tools, verifier=not a.no_verifier,
                    reader=not a.no_reader, max_steps=a.max_steps,
                    reasoning={"on": True, "off": False}.get(a.reasoning))
    be = toolbox.backend(a.backend)
    client = None
    if a.stub:
        from .stub_model import StubClient, listing_demo
        client = StubClient(listing_demo())
        cfg = cfg.with_(model="stub")
    else:
        models = probe(cfg.base_url, cfg.api_key)
        if models is None:
            print(f"endpoint {cfg.base_url} is not reachable; rerun with --stub for the scripted model",
                  file=sys.stderr)
            return 2
        if "OPERATOR_MODEL" not in os.environ and models:
            cfg = cfg.with_(model=models[0])

    world = build_world(be, a.world, not a.no_fixture)
    import uuid
    run_id = f"r_{uuid.uuid4().hex[:8]}"
    path = REPO / "runs" / run_id / "events.jsonl"
    sink = Tee(toolbox.make_sink(be, run_id, path=path), printer(not a.no_color and sys.stdout.isatty()))
    print(f"run {run_id}  backend={be.__name__}  model={cfg.model}  {cfg.label()}\n")
    res = run(world, a.instruction, client=client, config=cfg, sink=sink, backend=be, run_id=run_id)
    print(f"\nstatus={res.status} steps={res.steps} tool_calls={res.tool_calls} "
          f"escalations={len(res.escalations)} self_check={'ok' if not res.self_check else res.self_check}")
    print(f"events: {path if path.exists() else '(sink kept them in memory)'}")
    return 0 if res.status == "done" else 1


if __name__ == "__main__":
    sys.exit(main())
