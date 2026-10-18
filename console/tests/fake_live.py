"""In-memory stand-in for channels.live.api, for console tests only (CONSOLE_LIVE_MODULE=console.tests.fake_live).

Synthetic people and text, written for the tests. Same function signatures as the live contract.
"""
from __future__ import annotations

import itertools
import threading
import time

_LOCK = threading.Lock()
_IDS = itertools.count(100)


def _ts(minutes_ago: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(time.time() - minutes_ago * 60))


THREADS: dict[str, dict] = {
    "t_test_sam": {
        "thread_id": "t_test_sam", "channel": "messenger", "contact_display": "Sam Test", "renter_name": "Sam",
        "stage": "qualifying", "unread": True, "needs_owner": True,
        "gate": {"lease": "exact", "move_in": "vague", "phone": "missing", "reason": "exact", "people": "exact"},
        "messages": [
            {"id": "m1", "direction": "in", "text": "Hi, is the room with the private bath still available?", "ts": _ts(30), "status": "received", "channel": "messenger"},
            {"id": "m2", "direction": "out", "text": "Hi Sam, yes it is. When would you like to move in, and how long a lease are you looking for?", "ts": _ts(29), "status": "sent", "channel": "messenger"},
            {"id": "m3", "direction": "in", "text": "Sometime early next month, 12 months, just me. I'm starting at the hospital. Can you do $700?", "ts": _ts(5), "status": "received", "channel": "messenger"},
        ],
        "trace": [
            {"ts": _ts(5), "actor": "tool", "name": "read_inbox", "summary": "1 new message on messenger", "ok": True},
            {"ts": _ts(5), "actor": "reader", "name": "read_reply", "summary": "lease 12 mo (exact), move-in early next month (vague), people 1", "ok": True},
            {"ts": _ts(5), "actor": "operator", "name": "send_message", "summary": "draft promised a discount", "ok": False},
            {"ts": _ts(5), "actor": "verifier", "name": "price_guard", "summary": "rent changes need the owner: drafted, sent for approval", "ok": True},
            {"ts": _ts(5), "actor": "operator", "name": "escalate_to_owner", "summary": "asked the owner about $700", "ok": True},
        ],
    },
    "t_test_lee": {
        "thread_id": "t_test_lee", "channel": "sms", "contact_display": "+1 555 0100", "renter_name": "Lee",
        "stage": "qualified", "unread": False, "needs_owner": False,
        "gate": {"lease": "exact", "move_in": "exact", "phone": "exact", "reason": "exact", "people": "exact"},
        "messages": [
            {"id": "m4", "direction": "in", "text": "Saw the listing, can I see it Saturday?", "ts": _ts(120), "status": "received", "channel": "sms"},
            {"id": "m5", "direction": "out", "text": "Sure. Saturday 11am or 2pm works.", "ts": _ts(118), "status": "sent", "channel": "sms"},
        ],
        "trace": [{"ts": _ts(118), "actor": "tool", "name": "send_message", "summary": "sent via sms", "ok": True}],
    },
    "t_test_mp": {
        "thread_id": "t_test_mp", "channel": "messenger_personal", "contact_display": "Alex Test", "renter_name": "Alex",
        "stage": "inquiry", "unread": True, "needs_owner": True, "gate": {"people": "exact"},
        "messages": [
            {"id": "m6", "direction": "in", "text": "Is this still available?", "ts": _ts(2), "status": "received", "channel": "messenger_personal"},
            {"id": "m7", "direction": "out", "text": "Hi Alex, yes it is! When are you hoping to move in?", "ts": _ts(1), "status": "awaiting_approval", "channel": "messenger_personal"},
        ],
        "trace": [{"ts": _ts(1), "actor": "operator", "name": "send_message", "summary": "drafted a reply (Marketplace replies need approval)", "ok": True}],
    },
}
APPROVALS: dict[str, dict] = {
    "ap_2": {"id": "ap_2", "thread_id": "t_test_mp", "kind": "draft", "reason": "Marketplace reply", "draft_text": "Hi Alex, yes it is! When are you hoping to move in?", "created": _ts(1)},
    "ap_1": {"id": "ap_1", "thread_id": "t_test_sam", "kind": "escalation", "reason": "Asked for $700 instead of $750",
             "draft_text": "Thanks Sam. The rent is $750 a month; I can check with the owner about anything else.", "created": _ts(5)},
}
APPROVALS["ap_3"] = {"id": "ap_3", "thread_id": "t_test_lee", "kind": "report", "draft_text": "", "created": _ts(3),
                     "reason": "thread_id 'sms:9f8e7d6c5b4a' not found in store; reply skipped, will retry on the next poll"}
THREADS["t_test_lee"]["busy"] = True
THREADS["t_test_lee"]["busy_since"] = _ts(0.2)
DECISIONS: list[tuple] = []


def status():
    return {"channels": [{"channel": "messenger", "line": "Test Page", "connected": True, "detail": "test"},
                         {"channel": "sms", "line": "+1 555 0000", "connected": True, "detail": "test"},
                         {"channel": "email", "line": "test@example.com", "connected": False, "detail": "not configured"}],
            "send_enabled": False, "allowlist_size": 2}


def list_threads():
    with _LOCK:
        out = []
        for t in THREADS.values():
            last = t["messages"][-1]
            out.append({k: v for k, v in t.items() if k not in ("messages", "trace")} | {"last_text": last["text"], "last_ts": last["ts"]})
        return out


def get_thread(thread_id):
    with _LOCK:
        t = THREADS.get(thread_id)
        if not t:
            return None
        last = t["messages"][-1]
        t["unread"] = False
        return dict(t, last_text=last["text"], last_ts=last["ts"], messages=list(t["messages"]), trace=list(t["trace"]))


def list_approvals():
    with _LOCK:
        return list(APPROVALS.values())


def decide(approval_id, decision, text=None):
    with _LOCK:
        a = APPROVALS.pop(approval_id, None)
        if not a:
            raise KeyError(approval_id)
        DECISIONS.append((approval_id, decision, text))
        if decision == "deny":
            t = THREADS[a["thread_id"]]
            t["messages"] = [m for m in t["messages"] if m["status"] != "awaiting_approval"]
        if decision != "deny":
            t = THREADS[a["thread_id"]]
            t["messages"] = [m for m in t["messages"] if m["status"] != "awaiting_approval"]
            t["messages"].append({"id": f"m{next(_IDS)}", "direction": "out", "text": text or a["draft_text"], "ts": _ts(0),
                                  "status": "sent", "channel": t["channel"]})
            t["needs_owner"] = False
        return {"ok": True, "decision": decision, "sent": decision != "deny", "status": "sent" if decision != "deny" else None}


def send_owner_message(thread_id, text):
    with _LOCK:
        t = THREADS[thread_id]
        if thread_id == "t_test_lee" and text.startswith("BLOCKED"):
            return {"ok": False, "status": "awaiting_approval", "error": "sending is switched off (kill switch)"}
        t["messages"].append({"id": f"m{next(_IDS)}", "direction": "out", "text": text, "ts": _ts(0), "status": "sent", "channel": t["channel"]})
        return {"ok": True, "status": "sent"}


def start_conversation(channel, to, text):
    with _LOCK:
        tid = f"t_test_{next(_IDS)}"
        THREADS[tid] = {"thread_id": tid, "channel": channel, "contact_display": to, "renter_name": None, "stage": "inquiry",
                        "unread": False, "needs_owner": False, "gate": {},
                        "messages": [{"id": f"m{next(_IDS)}", "direction": "out", "text": text, "ts": _ts(0), "status": "sent", "channel": channel}],
                        "trace": []}
        return {"thread_id": tid}
