"""Shadow inbox for the real-world pilot (D20). Reads Rentus Homes Page conversations, NEVER replies.

  python -m channels.pilot_shadow                 # poll every 180 s (PILOT_SHADOW_INTERVAL), forever
  python -m channels.pilot_shadow --once          # one poll
  python -m channels.pilot_shadow --selftest "Is the room still available?"   # synthetic message, no Graph

For each new renter message in a Page Messenger conversation, the operator (Lightning, verifier and
read_reply on) runs against a SANDBOX world that holds only the Appling Way room and that conversation.
Its send_message calls land in the sandbox world as drafts; this module has no code path that posts to
the Graph API (GET requests only). Per conversation, the sandbox world and model history persist under
runs/pilot/threads/ so the gate carries across messages.

Outputs (runs/ is gitignored; shadow.jsonl holds real renter text and must never be committed):
  runs/pilot/shadow.jsonl   one row per renter message: text, drafts, escalations, gate, status
  runs/pilot/stats.json     aggregate counters only: inquiries, drafts, gate_items_captured, escalations
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
import time
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "runs" / "pilot"
THREADS = OUT / "threads"
SHADOW = OUT / "shadow.jsonl"
STATS = OUT / "stats.json"
CHANNEL = "facebook_page"

sys.path.insert(0, str(REPO / "operator"))

from channels.facebook_page import FacebookError, _call, _creds  # noqa: E402
from channels.pilot_post import ROOM  # noqa: E402


# ---- Graph (read only) ---------------------------------------------------------------

def fetch_conversations(limit: int = 25) -> list[dict]:
    page_id, token = _creds()
    body = _call("GET", f"{page_id}/conversations", token,
                 params={"platform": "messenger", "fields": "id,updated_time", "limit": limit})
    convs = []
    for c in body.get("data", []):
        m = _call("GET", c["id"], token, params={"fields": "messages.limit(25){id,created_time,from,message}"})
        msgs = sorted(m.get("messages", {}).get("data", []), key=lambda x: x.get("created_time", ""))
        convs.append({"id": c["id"], "updated_time": c.get("updated_time"), "page_id": page_id, "messages": msgs})
    return convs


# ---- per-conversation sandbox state ---------------------------------------------------

def _key(conv_id: str) -> str:
    return hashlib.sha256(conv_id.encode()).hexdigest()[:12]


def _load_state(conv_id: str) -> dict:
    p = THREADS / f"{_key(conv_id)}.json"
    return json.loads(p.read_text()) if p.exists() else {"conv_id": conv_id, "seen": [], "world": None,
                                                        "history": None}


def _save_state(st: dict) -> None:
    THREADS.mkdir(parents=True, exist_ok=True)
    (THREADS / f"{_key(st['conv_id'])}.json").write_text(json.dumps(st, ensure_ascii=False, default=str))


def _world(st: dict, thread_id: str, renter_name: str):
    import rentus_tools as rt

    if st.get("world"):
        w = rt.World.from_dict(st["world"])
    else:
        w = rt.load()
        w.rooms[:] = [copy.deepcopy(ROOM)]
        w.listings[:] = []
        w.threads.append({"thread_id": thread_id, "channel": CHANNEL, "renter_name": renter_name,
                          "room_id": ROOM["room_id"], "messages": []})
        w._normalize()
    w.mode = "sandbox"  # shadow: send_message only records a draft in this sandbox world
    return w


def _thread(w, thread_id: str) -> dict:
    return next(t for t in w.threads if t["thread_id"] == thread_id)


def _gate_answered(w) -> int:
    n = 0
    for r in w.register:
        for v in (r.get("gate") or {}).values():
            if isinstance(v, dict) and v.get("status") == "answered":
                n += 1
    return n


# ---- one renter message -> operator in shadow ----------------------------------------

def shadow_one(st: dict, thread_id: str, renter_name: str, text: str, msg_id: str, ts: str | None) -> dict:
    from rentus_operator import toolbox
    from rentus_operator.cli import load_env
    from rentus_operator.config import RunConfig
    from rentus_operator.loop import run

    load_env()
    # the best held-out Gym config (docs/results.md: guard+prompt3+style+rhist)
    cfg = RunConfig(prompt_version="v3", reader=True, verifier=True, renter_guard=True, style_precheck=True,
                    keep_reasoning_in_history=True)
    if "OPERATOR_MODEL" not in os.environ:
        from rentus_operator.cli import probe
        models = probe(cfg.base_url, cfg.api_key)
        if not models:
            raise RuntimeError("operator endpoint not reachable")
        cfg = cfg.with_(model=models[0])
    be = toolbox.backend("real")
    w = _world(st, thread_id, renter_name)
    t = _thread(w, thread_id)
    n_before = len(t["messages"])
    esc_before = len(w.escalations)
    gate_before = _gate_answered(w)
    t["messages"].append({"id": msg_id, "from": "renter", "text": text, "attachments": [],
                          "ts": ts or w.clock["now"]})
    run_id = f"shadow_{_key(st['conv_id'])}_{len(st['seen'])}"
    sink = toolbox.make_sink(be, run_id, path=OUT / "events" / f"{run_id}.jsonl")
    res = run(w, {"thread_id": thread_id, "channel": CHANNEL, "renter_name": renter_name, "text": text},
              config=cfg, sink=sink, backend=be, run_id=run_id, history=st.get("history"))
    drafts = [m["text"] for m in t["messages"][n_before + 1:] if m.get("from") == "operator"]
    escs = [{"reason": e.get("reason"), "draft": e.get("draft")} for e in w.escalations[esc_before:]]
    reads = [((e.get("data") or {}).get("result") or {}).get("data") for e in res.events
             if e.get("type") == "tool_result" and (e.get("data") or {}).get("tool") == "read_reply"]
    gate = next((r.get("gate") for r in w.register if thread_id in r.get("thread_ids", [])), None)
    st["world"] = w.to_dict()
    st["history"] = res.messages
    return {"drafts": drafts, "escalations": escs, "reader": reads, "gate": gate, "status": res.status,
            "gate_new": max(0, _gate_answered(w) - gate_before), "run_id": run_id}


def _bump(**inc) -> dict:
    s = json.loads(STATS.read_text()) if STATS.exists() else {
        "inquiries": 0, "conversations": 0, "drafts": 0, "gate_items_captured": 0, "escalations": 0, "errors": 0}
    for k, v in inc.items():
        s[k] = s.get(k, 0) + v
    s["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    OUT.mkdir(parents=True, exist_ok=True)
    STATS.write_text(json.dumps(s, indent=2))
    return s


def _append(row: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with SHADOW.open("a") as fh:
        fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def poll_once() -> dict:
    convs = fetch_conversations()
    done = 0
    for c in convs:
        st = _load_state(c["id"])
        new_conv = not st["seen"]
        thread_id = f"fb:{_key(c['id'])}"
        for m in c["messages"]:
            if m["id"] in st["seen"]:
                continue
            st["seen"].append(m["id"])
            frm = m.get("from") or {}
            if frm.get("id") == c["page_id"]:  # the owner replied from the Page: keep it in the sandbox thread
                if st.get("world"):
                    import rentus_tools as rt
                    w = rt.World.from_dict(st["world"])
                    _thread(w, thread_id)["messages"].append({"id": m["id"], "from": "operator",
                                                              "text": m.get("message", ""), "attachments": [],
                                                              "ts": m.get("created_time")})
                    st["world"] = w.to_dict()
                _save_state(st)
                continue
            text = m.get("message") or ""
            if not text.strip():
                _save_state(st)
                continue
            row = {"at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "thread_id": thread_id, "message_id": m["id"],
                   "created_time": m.get("created_time"), "renter_text": text, "mode": "shadow"}
            try:
                out = shadow_one(st, thread_id, frm.get("name") or "a renter", text, m["id"], m.get("created_time"))
                row.update(out)
                _bump(inquiries=1, conversations=1 if new_conv else 0, drafts=len(out["drafts"]),
                      gate_items_captured=out["gate_new"], escalations=len(out["escalations"]))
            except Exception as e:  # keep polling; record the failure
                row.update({"status": "error", "error": f"{type(e).__name__}: {e}"[:400]})
                _bump(inquiries=1, conversations=1 if new_conv else 0, errors=1)
            new_conv = False
            _append(row)
            _save_state(st)
            done += 1
    return {"conversations": len(convs), "new_messages": done}


def selftest(text: str) -> int:
    st = {"conv_id": "selftest", "seen": [], "world": None, "history": None}
    out = shadow_one(st, "fb:selftest", "Test Renter", text, "selftest-m1", None)
    print(json.dumps(out, indent=2, ensure_ascii=False, default=str))
    return 0 if out["status"] in ("done", "done_unverified") else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="channels.pilot_shadow")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--selftest", metavar="TEXT")
    ap.add_argument("--interval", type=int, default=int(os.environ.get("PILOT_SHADOW_INTERVAL", "180")))
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest(a.selftest)
    if not STATS.exists():
        _bump()
    while True:
        try:
            r = poll_once()
            print(time.strftime("%H:%M:%S"), json.dumps(r), flush=True)
        except FacebookError as e:  # already scrubbed of the token
            print(time.strftime("%H:%M:%S"), "graph error:", e, flush=True)
        except Exception:
            print(time.strftime("%H:%M:%S"), traceback.format_exc(limit=3), flush=True)
        if a.once:
            return 0
        time.sleep(a.interval)


if __name__ == "__main__":
    sys.exit(main())
