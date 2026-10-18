"""Every real send goes through `deliver()`: allowlist, opt-out, kill switch and rate cap, then the provider.

A send that a gate stops is not lost: it becomes an approval item with the reason, and the message is kept in
the thread as "awaiting_approval". Owner approvals (api.decide) call deliver(..., approved=True), which still
honors the kill switch, the rate cap, opt-outs and the allowlist.
"""
from __future__ import annotations

from datetime import datetime, timezone

from . import config, providers
from .store import Store, short_hash

_PROVIDERS: dict | None = None


def set_providers(p: dict | None) -> None:
    """Tests inject fakes: {"sms": {line_name: obj}, "email": obj|None, "messenger": obj|None}."""
    global _PROVIDERS
    _PROVIDERS = p


def get_providers() -> dict:
    global _PROVIDERS
    if _PROVIDERS is None:
        ec = config.email_cfg()
        _PROVIDERS = {"sms": {ln.name: providers.TwilioSms(ln) for ln in config.sms_lines()},
                      "email": providers.ResendGmailEmail(ec) if ec else None,
                      "messenger": providers.Messenger()}
    return _PROVIDERS


def email_ref(t: dict) -> str:
    return short_hash(t["thread_id"])[:6]


def email_subject(t: dict) -> str:
    ref = f"[ref {email_ref(t)}]"
    subj = (t.get("email") or {}).get("subject")
    if not subj:
        return f"Rentus Homes: your room inquiry {ref}"
    if not subj.lower().startswith("re:"):
        subj = "Re: " + subj
    return subj if ref in subj else f"{subj} {ref}"


def _gate(store: Store, t: dict, allow: config.Allowlist, *, skip_allowlist: bool = False) -> str | None:
    """Why this send may not go out now, or None. skip_allowlist (owner-approved / owner-typed sends) lifts ONLY
    the allowlist check; opt-out, the kill switch and the rate cap always apply."""
    if not skip_allowlist and not allow.allows(t["channel"], t["contact"]):
        return "contact is not on the live allowlist: the owner must approve this draft"
    if t.get("opted_out"):
        return OPTED_OUT
    if not config.send_enabled():
        return "live sending is switched off (LIVE_SEND_ENABLED=0 or runs/live/STOP)"
    if store.sends_last_hour() >= config.max_per_hour():
        return f"rate cap reached ({config.max_per_hour()} messages in the last hour)"
    return None


OPTED_OUT = "this contact opted out (STOP): nothing can be sent"


def _provider_send(t: dict, text: str) -> dict:
    p = get_providers()
    ch = t["channel"]
    if ch == "sms":
        prov = p["sms"].get(t.get("line"))
        if prov is None:
            return {"ok": False, "status": "failed", "error": f"SMS line {t.get('line')!r} not configured"}
        return prov.send(t["contact"], text)
    if ch == "email":
        prov = p.get("email")
        if prov is None:
            return {"ok": False, "status": "failed", "error": "email not configured"}
        last_in = next((m for m in reversed(t["messages"]) if m["direction"] == "in" and m.get("ext_id")), None)
        em = t.get("email") or {}
        return prov.send(t["contact"], text, subject=email_subject(t),
                         in_reply_to=last_in["ext_id"] if last_in else None, references=em.get("references"))
    from . import registry
    if ch in registry.EXTRA:
        try:
            return registry.EXTRA[ch].provider.send(t["contact"], text)
        except Exception as e:
            return {"ok": False, "status": "failed", "error": f"{type(e).__name__}: {str(e)[:150]}"}
    if ch == "messenger":
        prov = p.get("messenger")
        if prov is None:
            return {"ok": False, "status": "failed", "error": "messenger not configured"}
        return prov.send(t["contact"], text)
    return {"ok": False, "status": "failed", "error": f"unknown channel {ch}"}


def deliver(store: Store, thread_id: str, text: str, *, origin: str, approved: bool = False,
            existing_message_id: str | None = None, make_approval: bool = True) -> dict:
    """origin: "operator" | "owner". Returns {"ok","status","message_id","provider_id","error","approval_id"}.

    Three steps so the provider's network call never holds the store lock: (1) under the lock, gate and reserve
    (the reservation counts toward the rate cap; the message is "sending"), (2) send, (3) under the lock, record.
    make_approval=False (used by api.decide for an existing approval) reports a gate block without adding a new
    approval item."""
    allow = config.Allowlist.load()
    with store.locked():
        t = store.get_thread(thread_id)
        if t is None:
            return {"ok": False, "status": "failed", "error": f"unknown thread {thread_id}"}
        msg = next((m for m in t["messages"] if m["id"] == existing_message_id), None) if existing_message_id else None
        if msg is None:
            msg = store.add_message(t, "out", text, "draft", origin=origin)
        else:
            msg["text"] = text
        reason = _gate(store, t, allow, skip_allowlist=approved)
        if reason:
            if reason == OPTED_OUT:
                msg["status"] = "failed"
                msg["error"] = reason
                store.save_thread(t)
                return {"ok": False, "status": "failed", "message_id": msg["id"], "error": reason}
            msg["status"] = "awaiting_approval"
            ap_id = None
            if make_approval:
                ap_id = store.add_approval(thread_id, reason, text, message_id=msg["id"])["id"]
                t["needs_owner"] = True
            store.save_thread(t)
            return {"ok": False, "status": "awaiting_approval", "message_id": msg["id"], "approval_id": ap_id,
                    "error": reason}
        msg["status"] = "sending"
        store.log_send({"attempted": True, "reserved": True, "thread_id": thread_id, "channel": t["channel"],
                        "line": t.get("line"), "origin": origin})
        store.save_thread(t)
        snapshot = {k: t.get(k) for k in ("channel", "line", "contact", "email", "thread_id")}
        snapshot["messages"] = list(t["messages"])
    try:
        res = _provider_send(snapshot, text)
    except Exception as e:  # providers should not raise; never leave a message stuck in "sending"
        res = {"ok": False, "status": "failed", "error": f"{type(e).__name__}: {str(e)[:150]}"}
    with store.locked():
        t = store.get_thread(thread_id)
        store.log_send({"attempted": False, "result": True, "thread_id": thread_id, "channel": t["channel"],
                        "line": t.get("line"), "origin": origin, "ok": res.get("ok"),
                        "provider_id": res.get("provider_id"), "provider_status": res.get("status"),
                        "error_code": res.get("error_code")})
        msg = next(m for m in t["messages"] if m["id"] == msg["id"])
        msg["status"] = "sent" if res.get("ok") else "failed"
        msg["provider_id"] = res.get("provider_id")
        msg["ts"] = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        if not res.get("ok"):
            msg["error"] = f"{res.get('error_code') or ''} {res.get('error') or ''}".strip()[:200]
        if t["channel"] == "email" and res.get("ok"):
            t.setdefault("email", {})["subject"] = email_subject(t).removeprefix("Re: ")
        if origin == "owner" and res.get("ok"):
            t.setdefault("owner_pending", []).append({"id": msg["id"], "text": text, "ts": msg["ts"]})
        store.save_thread(t)
        return {"ok": bool(res.get("ok")), "status": msg["status"], "message_id": msg["id"],
                "provider_id": res.get("provider_id"), "error": msg.get("error"),
                "error_code": res.get("error_code")}
