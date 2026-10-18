"""Contract the console imports. Every function reads/writes the on-disk store (runs/live/), so the console
process and the daemon process can be separate. Sends from here (approve, owner message, start) go out
immediately through outbound.deliver() with the same gates as the daemon. See channels/live/README.md.
"""
from __future__ import annotations

import time

from . import config, outbound, registry
from .store import Store, now_iso

PUBLIC_THREAD_KEYS = ("thread_id", "channel", "contact_display", "renter_name", "last_text", "last_ts", "unread",
                      "stage", "gate", "needs_owner")


def _store() -> Store:
    return Store()


_STATUS_CACHE: dict = {}


def _connected(p) -> tuple[bool, str]:
    """Provider connectivity, cached 60 s (each check is a network call)."""
    hit = _STATUS_CACHE.get(id(p))
    if hit and time.time() - hit[0] < 60:
        return hit[1]
    try:
        val = p.connected()
    except Exception as e:
        val = (False, type(e).__name__)
    _STATUS_CACHE[id(p)] = (time.time(), val)
    return val


def status() -> dict:
    provs = outbound.get_providers()
    chans = []
    for name, p in (provs.get("sms") or {}).items():
        ok, detail = _connected(p)
        chans.append({"channel": "sms", "line": p.display, "line_name": name, "connected": ok, "detail": detail})
    for key in ("email", "messenger"):
        p = provs.get(key)
        if p is None:
            chans.append({"channel": key, "line": "", "connected": False, "detail": "not configured"})
            continue
        ok, detail = _connected(p)
        if key == "messenger" and ok and not config.Allowlist.load().psids:
            detail += "; LIVE_ALLOW_MESSENGER_PSIDS not set, so no Messenger thread is processed yet"
        chans.append({"channel": key, "line": p.display, "connected": ok, "detail": detail})
    registry.load_from_env()
    for name, spec in registry.EXTRA.items():
        ok, detail = _connected(spec.provider)
        if spec.drafts_for_unlisted():
            detail += "; non-allowlisted chats get approval drafts only"
        chans.append({"channel": name, "line": getattr(spec.provider, "display", name), "connected": ok,
                      "detail": detail})
    st = _store()
    state = st.state()
    return {"channels": chans, "send_enabled": config.send_enabled(), "allowlist_size": config.Allowlist.load().size(),
            "sent_last_hour": st.sends_last_hour(), "max_per_hour": config.max_per_hour(),
            "last_poll": state.get("last_poll"), "poll_errors": state.get("errors", {})}


def _summary(t: dict) -> dict:
    last = t["messages"][-1] if t.get("messages") else {}
    s = {k: t.get(k) for k in PUBLIC_THREAD_KEYS}
    s.update({"last_text": last.get("text", ""), "last_ts": last.get("ts") or t.get("created"),
              "unread": int(t.get("unread", 0)), "needs_owner": bool(t.get("needs_owner")),
              "line": t.get("line"), "opted_out": bool(t.get("opted_out")), "busy": bool(t.get("pending_turn"))})
    return s


def list_threads() -> list[dict]:
    return sorted((_summary(t) for t in _store().all_threads()), key=lambda s: s["last_ts"] or "", reverse=True)


def get_thread(thread_id: str, mark_read: bool = True) -> dict:
    st = _store()
    with st.locked():
        t = st.get_thread(thread_id)
        if t is None:
            return {"error": f"unknown thread {thread_id}"}
        out = _summary(t)  # unread as it was before this read
        if mark_read and t.get("unread"):
            t["unread"] = 0
            st.save_thread(t)
    out["messages"] = [{k: m.get(k) for k in ("id", "direction", "text", "ts", "status", "channel")}
                       | ({"error": m["error"]} if m.get("error") else {}) for m in t["messages"]]
    out["trace"] = t.get("trace", [])
    return out


def list_approvals() -> list[dict]:
    return [{k: a.get(k) for k in ("id", "thread_id", "reason", "draft_text", "created", "kind")}
            for a in _store().approvals() if a.get("status") == "pending"]


def decide(approval_id: str, decision: str, text: str | None = None) -> dict:
    if decision not in ("approve", "edit", "deny"):
        return {"ok": False, "error": "decision must be approve, edit or deny"}
    st = _store()
    with st.locked():
        items = st.approvals()
        a = next((x for x in items if x["id"] == approval_id), None)
        if a is None or a.get("status") != "pending":
            return {"ok": False, "error": "unknown or already decided approval"}
    out_text = (text if decision == "edit" else a.get("draft_text")) or ""
    result = {"ok": True, "sent": False}
    if decision in ("approve", "edit") and out_text.strip():
        result = outbound.deliver(st, a["thread_id"], out_text, origin="owner", approved=True,
                                  existing_message_id=a.get("message_id"))
        result["sent"] = result.get("status") == "sent"
        if result.get("status") == "awaiting_approval":  # still gated (kill switch / rate cap): keep one item
            with st.locked():
                items = st.approvals()
                for x in items:
                    if x["id"] == result.get("approval_id"):
                        x["status"] = "superseded"
                st.save_approvals(items)
            return {"ok": False, "error": result.get("error"), "status": "awaiting_approval"}
    elif decision == "deny" and a.get("message_id"):
        with st.locked():
            t = st.get_thread(a["thread_id"])
            for m in (t or {}).get("messages", []):
                if m["id"] == a["message_id"]:
                    m["status"] = "draft"
            if t:
                st.save_thread(t)
    with st.locked():
        items = st.approvals()
        for x in items:
            if x["id"] == approval_id:
                x["status"] = {"approve": "approved", "edit": "edited", "deny": "denied"}[decision]
                x["decided"] = now_iso()
                if decision == "edit":
                    x["final_text"] = out_text
        st.save_approvals(items)
        t = st.get_thread(a["thread_id"])
        if t is not None:
            t["needs_owner"] = any(x.get("status") == "pending" and x["thread_id"] == t["thread_id"]
                                   and x.get("kind") != "report" for x in items)
            st.save_thread(t)
    return {"ok": result.get("ok", True), "decision": decision, "sent": result.get("sent", False),
            "status": result.get("status"), "error": result.get("error")}


def send_owner_message(thread_id: str, text: str) -> dict:
    if not (text or "").strip():
        return {"ok": False, "error": "empty text"}
    st = _store()
    return outbound.deliver(st, thread_id, text.strip(), origin="owner", approved=True)


def start_conversation(channel: str, to: str, text: str, line: str | None = None) -> dict:
    """Owner kicks off a test: first outbound message to an allowlisted contact. channel: sms|email|messenger.
    For sms, `line` picks "tollfree" or "local" (default: the first configured line)."""
    registry.load_from_env()
    if channel not in ("sms", "email", "messenger") and channel not in registry.EXTRA:
        return {"ok": False, "error": "unknown channel " + repr(channel)}
    allow = config.Allowlist.load()
    contact = config.normalize_phone(to) if channel == "sms" else (to.strip().lower() if channel == "email" else to.strip())
    if not allow.allows(channel, contact):
        return {"ok": False, "error": "recipient is not on the live allowlist"}
    if not (text or "").strip():
        return {"ok": False, "error": "empty text"}
    st = _store()
    line_name, last4 = None, None
    if channel == "sms":
        lines = outbound.get_providers().get("sms") or {}
        line_name = line or next(iter(lines), None)
        if line_name not in lines:
            return {"ok": False, "error": f"SMS line {line_name!r} not configured"}
        last4 = lines[line_name].line.last4
    elif channel == "email":
        p = outbound.get_providers().get("email")
        line_name = p.display if p else None
    with st.locked():
        t = st.ensure_thread(channel, contact, line=line_name, line_last4=last4)
        st.save_thread(t)
    res = outbound.deliver(st, t["thread_id"], text.strip(), origin="owner", approved=True)
    res["thread_id"] = t["thread_id"]
    return res
