"""The live daemon: poll every channel, and for each allowlisted inbound message run one operator turn.

    .venv/bin/python -m channels.live              # poll forever (LIVE_POLL_SECONDS, default 8)
    .venv/bin/python -m channels.live --once       # one poll + turns, then exit

Per thread, the operator's World and model history persist in the thread file (runs/live/threads/), so a restart
continues the conversation. The World is live mode with one room (the real Appling Way listing, as in the D20
pilot); the operator's send_message on this thread goes to `LiveSendAdapter`, which calls outbound.deliver()
(allowlist, kill switch, rate cap, then the real provider). Escalations and owner reports become approval items.
"""
from __future__ import annotations

import copy
import os
import queue
import re
import sys
import threading
import time
import traceback
from datetime import datetime
from zoneinfo import ZoneInfo

from . import compose, config, demo, outbound, providers, registry, roles
from .store import CHANNEL_WORLD, Store, now_iso

REPO = config.REPO
for sub in ("operator", "tools"):
    if str(REPO / sub) not in sys.path:
        sys.path.insert(0, str(REPO / sub))
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

# The final config (gym/confirmatory_v3.json, Amendment 6): prompt v4 + concierge tool descriptions + guard
# stand-down, on top of guard+prompt3+style+rhist+readermodel (the reader model comes from READER_BASE_URL).
FINAL_CONFIG = {"prompt_version": "v4", "tool_descriptions": "concierge", "guard_stand_down": True,
                "renter_guard": True, "style_precheck": True, "keep_reasoning_in_history": True,
                "verifier": True, "reader": True}
GATE_MAP = {"lease": "lease", "move_in": "move_in", "phone": "phone", "reason": "reason", "people": "occupants"}
STAGE_MAP = {"new": "inquiry", "qualifying": "qualifying", "qualified": "qualified", "showing_proposed": "showing",
             "showing_confirmed": "showing", "applied": "application", "leased": "application", "not_now": "lost",
             "lost": "lost"}
MAX_TURN_ATTEMPTS = 3


# ====================================================================== adapter (send_message -> real send)

class LiveSendAdapter:
    """rentus_tools LiveAdapter for the live threads of this daemon.

    During a daemon turn (begin_turn .. take_buffer) send_message calls are buffered and delivered at turn end as
    one composed reply (compose.py). Outside a turn they are delivered immediately."""

    def __init__(self, store: Store):
        self.store = store
        self.buffer: dict[str, list[str]] = {}   # live thread id -> texts, only while that thread's turn runs
        self._mu = threading.Lock()
        self.links: dict[str, str] = {}

    def add_lease_link(self, world, thread, url) -> None:
        from . import lease_link
        live_id = thread.get("live_id") or thread["thread_id"]
        if lease_link.link_kind() == "signing":
            self.links[live_id] = f"Here's the link to review and sign your lease: {url}"
        else:
            self.links[live_id] = f"Here's the link to complete your application and lease paperwork: {url}"

    def begin_turn(self, thread_id: str) -> None:
        with self._mu:
            self.buffer[thread_id] = []

    def take_buffer(self, thread_id: str) -> list[str]:
        with self._mu:
            return self.buffer.pop(thread_id, None) or []

    def publish_listing(self, world, listing, channel):
        from rentus_tools.errors import ToolError
        raise ToolError("POLICY_BLOCKED", "live conversation channels do not publish listings")

    def send_message(self, world, thread, text, attachments):
        from rentus_tools.errors import ToolError
        live_id = thread.get("live_id") or thread["thread_id"]
        with self._mu:
            buffered = live_id in self.buffer
            if buffered:
                self.buffer[live_id].append(text)
        if buffered:
            return {"status": "sent", "screenshot": None,
                    "note": "queued: this turn's messages go out together as one reply when the turn ends"}
        res = outbound.deliver(self.store, live_id, text, origin="operator")
        if res["status"] == "sent":
            return {"status": "sent", "screenshot": None, "external_message_id": res.get("provider_id")}
        if res["status"] == "awaiting_approval":
            return {"status": "awaiting_approval", "screenshot": None,
                    "note": "not sent: " + (res.get("error") or "") + "; saved for the owner's approval"}
        raise ToolError("UPSTREAM_ERROR", f"send failed: {res.get('error')}", retryable=False)


ADAPTER: LiveSendAdapter | None = None


def register_adapters(store: Store) -> LiveSendAdapter:
    from rentus_tools import live
    global ADAPTER
    a = LiveSendAdapter(store)
    ADAPTER = a
    roles.install_lease_tool(a.add_lease_link)
    registry.load_from_env()
    for ch in set(CHANNEL_WORLD.values()) | {spec.world_channel for spec in registry.EXTRA.values()}:
        live.register(ch, a)
    return a


# ====================================================================== polling

def sources(provs: dict | None = None) -> list[tuple[str, object]]:
    provs = provs or outbound.get_providers()
    out = [(f"sms:{n}", p) for n, p in (provs.get("sms") or {}).items()]
    out += [(k, provs[k]) for k in ("email", "email_zoho", "messenger") if provs.get(k) is not None]
    registry.load_from_env()
    out += [(name, spec.provider) for name, spec in registry.EXTRA.items()]
    return out


def poll_source(store: Store, key: str, prov, allow: config.Allowlist | None = None) -> list[str]:
    """Poll one provider; store admitted inbound messages; return thread ids that need a turn. Each source keeps
    its own seen set / error / start time in state.json, so sources can be polled from separate threads."""
    allow = allow or config.Allowlist.load()
    with store.locked():
        st = store.state()
        st.setdefault("source_started", {}).setdefault(key, now_iso())
        store.save_state(st)
    since = datetime.fromisoformat(st["started"])
    seen = set(st.get("seen", {}).get(key, []))
    # a source added later (e.g. the Zoho info@ inbox) only answers mail that arrives after it was added
    since_k = max(since, datetime.fromisoformat(st["source_started"][key])) if key == "email_zoho" else since
    demo_on = demo.enabled()
    touched: list[str] = []
    err = None
    try:
        if demo_on and key.split(":")[0] in ("sms", "email", "email_zoho", "messenger"):
            kw = {"include_unlisted": True}
            if key == "email":
                kw["demo_to"] = demo.email_to()
            items = prov.poll(allow, since_k, seen, **kw)
        else:
            items = prov.poll(allow, since_k, seen)
    except Exception as e:
        items = []
        err = f"{type(e).__name__}: {str(e)[:150]}"
    for it in items:
        seen.add(it["ext_id"])
        listed = allow.allows(it["channel"], it["contact"])
        spec = registry.EXTRA.get(it["channel"])
        is_demo = False
        if not listed and demo_on and it["channel"] in ("sms", "email", "messenger"):
            with store.locked():
                is_demo = demo.admit(store, it["channel"], it["contact"], it["text"], ts=it.get("ts"),
                                     meta=it.get("meta"))
        if not listed and not is_demo and not (spec and spec.drafts_for_unlisted()):
            continue  # never stored, never passed to a model
        with store.locked():
            t = store.ensure_thread(it["channel"], it["contact"], line=it.get("line"),
                                    line_last4=it.get("line_last4"), renter_name=it.get("renter_name"))
            t["allowlisted"] = listed  # unlisted (drafts-only channel): every reply waits for the owner
            if is_demo and not t.get("demo"):
                t.update(demo=True, role="prospect", stage="inquiry")
            if any(m.get("ext_id") == it["ext_id"] for m in t["messages"]):
                continue
            store.add_message(t, "in", it["text"], "received", ext_id=it["ext_id"], ts=it.get("ts"))
            t["last_in_epoch"] = time.time()
            if it["channel"] == "email":
                meta = it.get("meta") or {}
                em = t.setdefault("email", {})
                if meta.get("subject"):
                    s = meta["subject"]
                    while s.lower().startswith(("re:", "fwd:", "fw:")):
                        s = s.split(":", 1)[1].strip()
                    em["subject"] = s
                em["references"] = (meta.get("references") or []) + [meta.get("message_id")]
                if meta.get("inbox") == "zoho" and not listed:  # strangers to info@: keep the conversation on info@
                    em["reply_to"] = "info@rentus.homes"
            if t.get("opted_out") and re.fullmatch(r"\s*(start|unstop|yes)\s*", it["text"] or "", re.I):
                t["opted_out"] = False  # carrier-style re-subscribe; no reply to the keyword itself
                t["pending_turn"] = False
                t["trace"].append({"ts": now_iso(), "actor": "tool", "name": "opt_in",
                                   "summary": "contact sent START: messages allowed again", "ok": True})
            elif providers.is_opt_out(it["text"]) and (it["channel"] == "sms" or t.get("demo")):
                t["opted_out"] = True
                t["pending_turn"] = False
                t["trace"].append({"ts": now_iso(), "actor": "tool", "name": "opt_out",
                                   "summary": "contact sent STOP: no more messages on this thread", "ok": True})
            elif not t.get("opted_out"):  # after STOP: stored, but no more turns
                t["pending_turn"] = True
                t["turn_attempts"] = 0
            store.save_thread(t)
            touched.append(t["thread_id"])
    with store.locked():
        cur = store.state()
        cur.setdefault("seen", {})[key] = sorted(seen)[-2000:]
        errs = cur.setdefault("errors", {})
        if err:
            errs[key] = err
        else:
            errs.pop(key, None)
        cur["last_poll"] = now_iso()
        cur.setdefault("last_poll_by_source", {})[key] = now_iso()
        store.save_state(cur)
    if err:
        raise PollError(key, err)
    return touched


class PollError(RuntimeError):
    def __init__(self, key, msg):
        super().__init__(f"{key}: {msg}")
        self.key, self.msg = key, msg


def poll_all(store: Store, provs: dict | None = None, allow: config.Allowlist | None = None) -> list[str]:
    """Poll every provider once, in order (tests, --once)."""
    allow = allow or config.Allowlist.load()
    touched: list[str] = []
    for key, prov in sources(provs):
        try:
            touched += poll_source(store, key, prov, allow)
        except PollError:
            pass
    return touched


# ====================================================================== one operator turn

def _now_ny() -> str:
    return datetime.now(ZoneInfo("America/New_York")).replace(tzinfo=None).isoformat(timespec="seconds")


def world_tid(thread_id: str) -> str:
    """The id the model sees: no colons (the model drops a 'messenger:' prefix), unique per live thread."""
    return "t_" + thread_id.replace(":", "_")


def _new_world(t: dict):
    import rentus_tools as rt
    ROOM = roles.live_room()
    w = rt.load()
    w.rooms[:] = [ROOM]
    w.listings[:] = []
    w.threads[:] = []
    wch = registry.world_channel(t["channel"])
    wid = world_tid(t["thread_id"])
    w.threads.append({"thread_id": wid, "live_id": t["thread_id"], "channel": wch,
                      "renter_name": t.get("renter_name") or "", "room_id": ROOM["room_id"], "messages": []})
    ch = w.channels.setdefault(wch, {"posts": [], "threads": []})
    if isinstance(ch, dict) and wid not in ch.setdefault("threads", []):
        ch["threads"].append(wid)
    w._normalize()
    roles.seed_world(w, t, wid)
    return w


def _summ(x, n=160) -> str:
    s = x if isinstance(x, str) else __import__("json").dumps(x, ensure_ascii=False, default=str)
    return s if len(s) <= n else s[:n - 1] + "…"


def trace_from_events(events: list[dict]) -> list[dict]:
    out = []
    for e in events:
        typ, d = e.get("type"), e.get("data") or {}
        ts = e.get("ts") or now_iso()
        if typ == "tool_result":
            env = d.get("result") or {}
            name = d.get("tool", "")
            ok = bool(env.get("ok"))
            summary = _summ(env.get("data") if ok else (env.get("error") or {}).get("message", ""))
            out.append({"ts": ts, "actor": "reader" if name == "read_reply" else "tool", "name": name,
                        "summary": summary, "ok": ok})
        elif typ == "verifier" and d.get("ok") is False:
            out.append({"ts": ts, "actor": "verifier", "name": d.get("stage", "verifier"),
                        "summary": _summ(d.get("problems") or d.get("code") or d.get("note") or d), "ok": False})
        elif typ == "model_message" and d.get("text"):
            out.append({"ts": ts, "actor": "operator", "name": "model_message", "summary": _summ(d["text"]),
                        "ok": True})
    return out


def gate_and_stage(w, thread_id: str) -> tuple[dict, str | None]:
    row = next((r for r in getattr(w, "register", []) if thread_id in (r.get("thread_ids") or [])), None)
    gate = {}
    for k, src in GATE_MAP.items():
        g = ((row or {}).get("gate") or {}).get(src) or {}
        stt = g.get("status", "absent")
        gate[k] = "exact" if stt in ("answered", "exception", "no") else "vague" if stt == "vague" else "missing"
    stage = STAGE_MAP.get((row or {}).get("status")) if row else None
    return gate, stage


_MODEL: dict = {}


def _config():
    from rentus_operator.cli import load_env, probe
    from rentus_operator.config import RunConfig
    load_env()
    try:
        from dotenv import dotenv_values
        for k, v in dotenv_values(REPO / ".env").items():
            if k.startswith("READER_") and v and k not in os.environ:
                os.environ[k] = v
    except Exception:
        pass
    # Speed for live chat: reasoning off per request (chat_template_kwargs.enable_thinking=False; docs/vllm.md:
    # ~2x turns/s, p95 8.1 -> 2.6 s). LIVE_REASONING=1 restores the measured final config's server default.
    reasoning = None if (config.env("LIVE_REASONING", "0") or "0").strip() == "1" else False
    cfg = RunConfig(**FINAL_CONFIG, reasoning=reasoning)
    if "OPERATOR_MODEL" not in os.environ:
        if "model" not in _MODEL:  # cleared after any failed turn, so a restarted endpoint is re-probed
            models = probe(cfg.base_url, cfg.api_key)
            if not models:
                raise RuntimeError("operator endpoint not reachable (OPERATOR_BASE_URL)")
            _MODEL["model"] = models[0]
        cfg = cfg.with_(model=_MODEL["model"])
    return cfg


IDS_RE = re.compile(r"\b(t_[a-z_]+_[0-9a-f_]+|(sms|email|messenger)[:_][0-9a-z:_]+|renter:[\w-]+|"
                    r"(ESC|RPT)[-_]?\d+|R_[A-Z_]+|[0-9a-f]{10,})\b|[\w.+-]+@[\w-]+(?:\.[\w-]+)+|\+?1?\d{10,11}\b")


def readable(text: str, n: int = 280, name: str | None = None) -> str:
    """Owner-facing text without internal ids (thread ids, renter ids, ESC/RPT ids, hashes, raw emails/phones).
    An id the sentence needs ("sent to <id>") becomes the contact's name; "on thread <id>" is dropped."""
    s = IDS_RE.sub("§", text or "")
    s = re.sub(r"\s*\(\s*§?\s*\)", "", s)
    s = re.sub(r"[`'\"\[]?§[`'\"\]]?", "§", s)
    s = re.sub(r"\s*\b(on|in|for|from)\s+(the\s+)?thread\s+§", "", s)
    s = re.sub(r"\s*\b(thread|renter|ref|id)\s+§", "", s, flags=re.I)
    s = s.replace("§", name or "the contact")
    s = re.sub(r"\s+([,.;:!?])", r"\1", s)
    s = re.sub(r"([,;:])(?=[.!?])", "", s)
    s = re.sub(r"\s{2,}", " ", s).strip(" ,;:")
    return s if len(s) <= n else s[:n - 1] + "…"


def with_live_note(history, cfg, w, role: str = "prospect"):
    """The live-channel note (compose.LIVE_NOTE) appended to the operator's system prompt. No operator hook
    exists for extra instructions, so the daemon builds the first system message itself (the same load_prompt
    the loop would call) and passes it as history; older threads get the note added to their system message."""
    from rentus_operator import toolbox
    from rentus_operator.config import load_prompt
    note = compose.LIVE_NOTE + "\n" + roles.note(role)
    if history:
        h = list(history)
        if h and h[0].get("role") == "system" and compose.LIVE_NOTE not in (h[0].get("content") or ""):
            h[0] = {**h[0], "content": (h[0].get("content") or "") + "\n\n" + note}
        return h
    pol = toolbox.state(w).get("policy") or {}
    facts = {"today": toolbox.today(w), "spend_limit_usd": pol.get("spend_limit_usd"),
             "showing_hours": pol.get("showing_hours")}
    return [{"role": "system", "content": load_prompt(cfg, facts) + "\n\n" + note}]


CANNED = {"en": "Glad to help! Let me know if you have any questions.",
          "es": "¡Con gusto! Avísame si tienes alguna pregunta."}
GATE_LABEL = {"lease": "lease", "move_in": "move-in date", "phone": "phone", "reason": "reason for moving",
              "occupants": "number of people"}


def gate_note(w, wid: str) -> str:
    """Per-turn status for the model, appended after the renter's words: which gate items the register already
    has (never ask them again) and which one to ask next."""
    row = next((r for r in getattr(w, "register", []) if wid in (r.get("thread_ids") or [])), None)
    if not row:
        return ""
    g = row.get("gate") or {}
    done, todo = [], []
    for k in ("lease", "move_in", "phone", "reason", "occupants"):
        it = g.get(k) or {}
        if it.get("status") in ("answered", "exception", "no"):
            v = it.get("date") or it.get("value")
            done.append(f"{GATE_LABEL[k]}={v}" if v not in (None, "") else GATE_LABEL[k])
        else:
            todo.append(GATE_LABEL[k])
    if not done:
        return ""
    nxt = f"; ask next: {todo[0]}" if todo else "; all five answered: propose a showing"
    return f"\n\n[Status, not from the renter: already answered: {', '.join(done)} (never ask these again){nxt}.]"


def content_free_skip(store: Store, thread_id: str, new_in: list[dict]) -> dict | None:
    """"ok" / "thanks" / an emoji / an empty body: no model turn. If our last message asked something still
    unanswered, just wait; otherwise one short canned line, at most once per hour per thread."""
    if not new_in or not all(is_ack(m["text"]) for m in new_in):
        return None
    with store.locked():
        t = store.get_thread(thread_id)
        last_out = next((m for m in reversed(t["messages"]) if m["direction"] == "out" and m.get("status") == "sent"),
                        None)
        if last_out is None:  # never a canned first reply: the model answers (with the disclosure)
            return None
        t["world_synced"] = sorted(set(t.get("world_synced") or []) | {m["id"] for m in new_in})
        t["pending_turn"] = False
        t["busy"], t["busy_since"], t["turn_owner"] = False, None, None
        pending_q = bool(last_out and (last_out.get("text") or "").rstrip().endswith("?"))
        recent = time.time() - float(t.get("last_canned_epoch") or 0) < 3600
        send_canned = not pending_q and not recent and t.get("role", "prospect") == "prospect"
        if send_canned:
            t["last_canned_epoch"] = time.time()
        t["trace"].append({"ts": now_iso(), "actor": "operator", "name": "content_free",
                           "summary": "short acknowledgement: " + ("one canned line" if send_canned else
                                                                   "no reply (waiting for their answer)"), "ok": True})
        store.save_thread(t)
    if send_canned:
        lang = "es" if demo.is_spanish(" ".join((m["text"] or "") for m in t["messages"][-6:])) else "en"
        outbound.deliver(store, thread_id, CANNED[lang], origin="operator")
    return {"ok": True, "status": "content_free", "seconds": 0.0}


ACK_RE = re.compile(r"(?i)[\W_]*(ok(ay)?|k|kk|thanks?|thank you|thx|ty|cool|great|perfect|got it|nice|gracias|vale|"
                    r"listo|ok gracias|sounds good)?[\W_]*")


def is_ack(text: str) -> bool:
    """Content-free: ok / thanks / an emoji / an empty body (a photo with no text)."""
    return bool(ACK_RE.fullmatch((text or "").strip()))


def needs_answer(text: str) -> bool:
    """A renter batch that must not go unanswered: a question or a substantive message (not ok/thanks/emoji)."""
    t = (text or "").strip()
    if not t or re.fullmatch(r"(?i)[\W_]*(ok(ay)?|k|thanks?|thank you|thx|ty|cool|great|perfect|got it|gracias|vale|"
                             r"listo|si|sí|yes|no|stop|start)?[\W_]*", t):
        return False
    return "?" in t or len(t) > 15


EMERGENCY_RE = re.compile(r"overflow|flood|water (is )?(coming|pouring|leaking) (through|from) the ceiling|"
                          r"through the (kitchen )?ceiling|burst pipe|gas (smell|leak)|smell(s)? gas|\bfire\b|smoke|"
                          r"sparks?|carbon monoxide|co alarm|inundaci|fuga de gas|incendio", re.I)


def flush(store: Store, thread_id: str, channel: str, renter_text: str, gate: dict | None = None) -> dict | None:
    """Deliver this turn's buffered operator messages as one composed reply. Returns a trace entry."""
    if ADAPTER is None:
        return None
    texts = ADAPTER.take_buffer(thread_id)
    link = (ADAPTER.links or {}).pop(thread_id, None)
    if link:
        texts = texts + [link]
    if not texts and not EMERGENCY_RE.search(renter_text or ""):
        return None
    with store.locked():
        tt = store.get_thread(thread_id) or {}
    filled = {k if k != "people" else "occupants" for k, v in (gate or tt.get("gate") or {}).items() if v == "exact"}
    first = not any(m["direction"] == "out" and m.get("status") == "sent" for m in tt.get("messages", []))
    prospect = tt.get("role", "prospect") == "prospect"
    parts = compose.compose(texts, channel, renter_text, filled=filled if prospect else None, first=first,
                            prospect=prospect)
    emergency = EMERGENCY_RE.search(renter_text or "")
    if emergency and prospect and not tt.get("emergency_alerted"):
        # deterministic safety first: whatever the model wrote, the reply opens with safety advice and no questions
        gas = re.search(r"gas|fire|smoke|spark|burning|carbon monoxide|co alarm", renter_text, re.I)
        safety = ("Please leave the house now and call 911." if gas else
                  "Please turn off the water at the valve behind the toilet or the main shut-off, and stay clear of "
                  "the wet ceiling.")
        rest = [p_ for p_ in parts if "?" not in p_]
        parts = [f"{safety} I've alerted the owner and I'm getting help to you now."] + rest[:1]
        with store.locked():
            t = store.get_thread(thread_id)
            t["emergency_alerted"] = now_iso()
            t["needs_owner"] = True
            store.save_thread(t)
            store.add_approval(thread_id, "EMERGENCY reported: " + (renter_text or "")[:160], "", kind="escalation")
    if tt.get("demo") and not tt.get("disclosed") and parts and "AI assistant" in parts[0]:
        with store.locked():
            t = store.get_thread(thread_id)
            t["disclosed"] = now_iso()
            store.save_thread(t)
        tt = dict(tt, disclosed=True)
    if tt.get("demo") and not tt.get("disclosed") and parts:
        d = demo.disclosure("es" if demo.is_spanish(renter_text) else "en")
        if channel == "email":  # the email already opens with "Hi <name>,"
            d = d.removeprefix("Hi, ").removeprefix("Hola, ")
            d = d[:1].upper() + d[1:]
        body0 = re.sub(r"^(hi|hello|hey|hola|buenas)( there)?[,!.]?\s+", "", parts[0], flags=re.I)  # one greeting only
        body0 = body0[:1].upper() + body0[1:]
        parts[0] = d + ("\n\n" if channel == "email" else " ") + body0
    results = [outbound.deliver(store, thread_id, p, origin="operator") for p in parts]
    ok = all(r.get("status") in ("sent", "awaiting_approval") for r in results)
    if tt.get("demo") and any(r.get("status") == "sent" for r in results):
        with store.locked():
            t = store.get_thread(thread_id)
            t["disclosed"] = t.get("disclosed") or now_iso()
            store.save_thread(t)
    if link and any(r.get("status") == "sent" for r in results):
        with store.locked():
            t = store.get_thread(thread_id)
            t["lease_sent"] = now_iso()
            store.save_thread(t)
    return {"ts": now_iso(), "actor": "tool", "name": "deliver_reply", "ok": ok,
            "summary": f"{len(texts)} operator message(s) sent as {len(parts)} {channel} message(s): "
                       + ", ".join(r.get("status", "?") for r in results)}


def _pid_alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError, TypeError):
        return False


def _fail_turn(store: Store, thread_id: str, err: str) -> dict:
    _MODEL.clear()
    with store.locked():
        t = store.get_thread(thread_id)
        t["busy"], t["busy_since"], t["turn_owner"] = False, None, None
        t["turn_attempts"] = int(t.get("turn_attempts", 0)) + 1
        t["trace"].append({"ts": now_iso(), "actor": "operator", "name": "turn_error", "summary": err, "ok": False})
        if t["turn_attempts"] >= MAX_TURN_ATTEMPTS:
            t["pending_turn"] = False
            t["needs_owner"] = True
            store.add_approval(thread_id, "The assistant could not answer this message after "
                               f"{MAX_TURN_ATTEMPTS} tries ({readable(err, 120)}). Please reply by hand.", "",
                               kind="error")
        store.save_thread(t)
    return {"ok": False, "error": err}


def run_turn(store: Store, thread_id: str, *, runner=None) -> dict:
    """One operator turn on the thread's new inbound messages. `runner(world, inbound, history)` is injectable
    for tests and must return an object with .messages, .events, .status."""
    import rentus_tools as rt

    with store.locked():
        t = store.get_thread(thread_id)
        if t is None or not t.get("pending_turn"):
            return {"skipped": True}
        if t.get("busy") and _pid_alive(t.get("turn_owner")):  # any live turn, also another worker thread here
            return {"skipped": True, "busy": True}
        want = "prospect" if t.get("demo") else roles.role_for(t["channel"])
        if t.get("role", "prospect") != want:  # role changed in .env: start this contact's World fresh in the new role
            t.update(role=want, world=None, history=None, stage=roles.initial_stage(want), lease_sent=None,
                     world_synced=[m["id"] for m in t["messages"] if m["direction"] == "in"
                                   and m["id"] != (t["messages"][-1]["id"] if t["messages"] else None)])
        t["busy"], t["busy_since"], t["turn_owner"] = True, now_iso(), os.getpid()
        store.save_thread(t)
        world_d, history = t.get("world"), t.get("history")
        owner_pending = list(t.get("owner_pending") or [])
        synced = set(t.get("world_synced") or [])
        new_in = [m for m in t["messages"] if m["direction"] == "in" and m["id"] not in synced]
    skip = content_free_skip(store, thread_id, new_in)
    if skip is not None:
        return skip
    print(time.strftime("%H:%M:%S"), f"turn start {thread_id} ({len(new_in)} new message(s))", flush=True)
    t0 = time.time()
    try:
        w = rt.World.from_dict(world_d) if world_d else _new_world(t)
        w.mode = "live"
        w.clock["now"] = _now_ny()
        wt = next(x for x in w.threads if x.get("live_id") == thread_id or x["thread_id"] == thread_id)
        wid = wt["thread_id"]
        if t.get("renter_name"):
            wt["renter_name"] = t["renter_name"]
        for o in owner_pending:  # the owner's manual replies, so the operator sees them
            wt["messages"].append({"id": o["id"], "from": "operator", "text": o["text"], "attachments": [],
                                   "ts": w.clock["now"]})
        for m in new_in:
            wt["messages"].append({"id": m["id"], "from": "renter", "text": m["text"], "attachments": [],
                                   "ts": w.clock["now"]})
        esc0, rep0 = len(w.escalations), len(w.owner_reports)
        inbound = {"thread_id": wid, "channel": registry.world_channel(t["channel"]),
                   "renter_name": t.get("renter_name") or "a renter", "text": "\n".join(m["text"] for m in new_in)}
        status_note = gate_note(w, wid) if t.get("role", "prospect") == "prospect" else ""
        model_inbound = dict(inbound, text=inbound["text"] + status_note) if status_note else inbound
        if ADAPTER is not None:
            ADAPTER.begin_turn(thread_id)
        if runner is None:
            from rentus_operator import toolbox
            from rentus_operator.loop import run
            cfg = _config()
            history = with_live_note(history, cfg, w, t.get("role", "prospect"))
            be = toolbox.backend("real")
            run_id = f"live_{thread_id.replace(':', '_')}_{int(time.time())}"
            sink = toolbox.make_sink(be, run_id, path=store.root / "events" / f"{run_id}.jsonl")
            res = run(w, model_inbound, config=cfg, sink=sink, backend=be, run_id=run_id, history=history)
        else:
            res = runner(w, inbound, history)
    except Exception as e:
        if ADAPTER is not None:
            ADAPTER.take_buffer(thread_id)  # nothing from a failed turn goes out; the retry rebuilds it
        return _fail_turn(store, thread_id, f"{type(e).__name__}: {str(e)[:200]}")
    if getattr(res, "status", None) == "model_error":
        if ADAPTER is not None:
            ADAPTER.take_buffer(thread_id)
        return _fail_turn(store, thread_id, "model_error: " + str(getattr(res, "final_text", "") or "")[:160])
    try:
        delivered = flush(store, thread_id, t["channel"], inbound["text"], gate_and_stage(w, wid)[0])
        if delivered is None and needs_answer(inbound["text"]) and getattr(res, "status", "") in ("max_steps", "done",
                                                                                                  "done_unverified"):
            es = demo.is_spanish(inbound["text"])
            hold = ("Gracias por tu mensaje, te respondo en breve." if es else
                    "Thanks for your message, I'll get back to you shortly.")
            r_ = outbound.deliver(store, thread_id, hold, origin="operator")
            delivered = {"ts": now_iso(), "actor": "tool", "name": "holding_reply", "ok": r_.get("ok", False),
                         "summary": "the turn produced no reply to a question: sent a holding line (" +
                                    str(r_.get("status")) + ")"}
    except Exception as e:  # never leave the thread marked busy
        delivered = {"ts": now_iso(), "actor": "tool", "name": "deliver_reply", "ok": False,
                     "summary": f"delivery error {type(e).__name__}: {str(e)[:150]}"}
    with store.locked():
        t = store.get_thread(thread_id)
        t["busy"], t["busy_since"], t["turn_owner"] = False, None, None
        t["turn_attempts"] = 0
        if delivered:
            t["trace"].append(delivered)
        t["world"] = w.to_dict()
        t["history"] = res.messages
        t["world_synced"] = sorted(synced | {m["id"] for m in new_in})
        done_owner = {o["id"] for o in owner_pending}
        t["owner_pending"] = [o for o in t.get("owner_pending", []) if o["id"] not in done_owner]
        t["pending_turn"] = any(m["direction"] == "in" and m["id"] not in set(t["world_synced"]) for m in t["messages"])
        t["trace"].extend(trace_from_events(res.events))
        t["trace"] = t["trace"][-400:]
        gate, stage = gate_and_stage(w, wid)
        role = t.get("role", "prospect")
        if role == "tenant":
            stage = "tenant"
        elif role == "lease_signing":
            stage = "lease_sent" if t.get("lease_sent") else "lease_signing"
        t["gate"] = gate
        if stage:
            t["stage"] = stage
        disp = (t.get("renter_name") or "").split(" ")[0] or t.get("contact_display") or "the contact"
        for e in w.escalations[esc0:]:
            store.add_approval(thread_id, readable(e.get("reason") or "", name=disp) or "The assistant needs your decision",
                               e.get("draft") or "", kind="escalation")
            t["needs_owner"] = True
        reports = [readable(r.get("summary") or "", name=disp) for r in w.owner_reports[rep0:]]
        reports = [r for r in reports if r]
        if reports:  # at most one report item per thread: it replaces the previous pending one
            items = store.approvals()
            for x in items:
                if x["thread_id"] == thread_id and x.get("kind") == "report" and x.get("status") == "pending":
                    x["status"] = "superseded"
            store.save_approvals(items)
            store.add_approval(thread_id, " ".join(reports), "", kind="report")
        t["last_turn"] = {"status": res.status, "at": now_iso(), "seconds": round(time.time() - t0, 1)}
        store.save_thread(t)
    print(time.strftime("%H:%M:%S"), f"turn done {thread_id} {res.status} in {time.time() - t0:.1f}s", flush=True)
    return {"ok": True, "status": res.status, "seconds": round(time.time() - t0, 1)}


# ====================================================================== loop

def tick(store: Store) -> dict:
    try:
        touched = poll_all(store)
    except Exception as e:
        touched = []
        print(time.strftime("%H:%M:%S"), "poll error:", type(e).__name__, str(e)[:200], flush=True)
    turns = []
    for t in store.all_threads():
        if t.get("pending_turn"):
            try:
                turns.append({t["thread_id"]: run_turn(store, t["thread_id"])})
            except Exception as e:  # never let one thread stop the others; counts as a failed attempt
                turns.append({t["thread_id"]: _fail_turn(store, t["thread_id"], f"{type(e).__name__}: {str(e)[:200]}")})
    return {"new": len(touched), "turns": turns}


def debounce_s() -> float:
    try:
        return float(config.env("LIVE_DEBOUNCE_S", "4") or 0)
    except ValueError:
        return 4.0


def _interval(key: str) -> float:
    name = {"sms": "LIVE_POLL_SMS", "messenger": "LIVE_POLL_MESSENGER", "email": "LIVE_POLL_EMAIL",
            "email_zoho": "LIVE_POLL_EMAIL"}.get(key.split(":")[0])
    default = {"LIVE_POLL_SMS": 2.0, "LIVE_POLL_MESSENGER": 3.0, "LIVE_POLL_EMAIL": 5.0}.get(name, config.poll_seconds())
    try:
        return float(config.env(name, str(default)) or default) if name else default
    except ValueError:
        return default


class Runner:
    """One poller thread per source (a slow IMAP or Graph call never delays SMS) and a few turn workers fed by a
    queue: a turn starts the moment an inbound message is stored. One turn per thread at a time (busy marker in
    run_turn); a sweeper re-queues pending turns (retries) every few seconds. Pollers back off on errors (up to
    120 s) and on provider rate limits (at least 60 s)."""

    def __init__(self, store: Store, provs: dict | None = None, *, workers: int = 3, turn=None, log=print):
        self.store, self.provs = store, provs
        self.q: queue.Queue = queue.Queue()
        self.stop = threading.Event()
        self.turn = turn or (lambda tid: run_turn(store, tid))
        self.workers, self.log = workers, log
        self.threads: list[threading.Thread] = []
        self._queued: set = set()
        self._qmu = threading.Lock()

    def enqueue(self, tid: str) -> None:
        with self._qmu:
            if tid in self._queued:
                return
            self._queued.add(tid)
        self.q.put(tid)

    def _poller(self, key: str, prov) -> None:
        base = _interval(key)
        delay, fails = base, 0
        while not self.stop.is_set():
            try:
                for tid in poll_source(self.store, key, prov):
                    self.enqueue(tid)
                fails, delay = 0, base
            except PollError as e:
                fails += 1
                delay = min(base * (2 ** fails), 120.0)
                if "RateLimited" in e.msg:
                    delay = max(delay, 60.0)
                self.log(time.strftime("%H:%M:%S"), f"poll {key} failed ({e.msg[:120]}); next in {delay:.0f}s")
            except Exception as e:  # never let a poller die
                fails += 1
                delay = min(base * (2 ** fails), 120.0)
                self.log(time.strftime("%H:%M:%S"), f"poll {key} crashed: {type(e).__name__}: {str(e)[:120]}")
            self.stop.wait(delay)

    def _worker(self) -> None:
        while not self.stop.is_set():
            try:
                tid = self.q.get(timeout=0.5)
            except queue.Empty:
                continue
            with self._qmu:
                self._queued.discard(tid)
            t = self.store.get_thread(tid) or {}
            wait = debounce_s() - (time.time() - float(t.get("last_in_epoch") or 0))
            if t.get("pending_turn") and wait > 0:  # a renter often splits a message: wait for quiet first
                threading.Timer(wait, self.enqueue, args=(tid,)).start()
                continue
            try:
                r = self.turn(tid)
            except Exception as e:  # counts as a failed attempt; other threads keep going
                r = _fail_turn(self.store, tid, f"{type(e).__name__}: {str(e)[:200]}")
            if r and not r.get("skipped"):
                self.log(time.strftime("%H:%M:%S"), {tid: r})
                if (self.store.get_thread(tid) or {}).get("pending_turn"):
                    self.enqueue(tid)  # messages that arrived during the turn: one follow-up turn, never in parallel

    def _sweeper(self) -> None:
        while not self.stop.wait(5.0):
            try:
                for t in self.store.all_threads():
                    if t.get("pending_turn") and not t.get("busy"):
                        self.enqueue(t["thread_id"])
            except Exception:
                pass

    def start(self) -> "Runner":
        for key, prov in sources(self.provs):
            self.threads.append(threading.Thread(target=self._poller, args=(key, prov), name=f"poll-{key}", daemon=True))
        for i in range(self.workers):
            self.threads.append(threading.Thread(target=self._worker, name=f"turn-{i}", daemon=True))
        self.threads.append(threading.Thread(target=self._sweeper, name="sweeper", daemon=True))
        for th in self.threads:
            th.start()
        for t in self.store.all_threads():  # pending from before a restart
            if t.get("pending_turn"):
                self.enqueue(t["thread_id"])
        return self

    def close(self) -> None:
        self.stop.set()


class DaemonRunning(RuntimeError):
    pass


def acquire_daemon_lock(store: Store):
    """One daemon per store: an exclusive, non-blocking fcntl lock held for the life of the process."""
    import fcntl
    store.root.mkdir(parents=True, exist_ok=True)
    fh = open(store.root / "daemon.pid", "a+")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.seek(0)
        other = fh.read().strip()
        fh.close()
        raise DaemonRunning(f"another live daemon is running (pid {other or '?'})") from None
    fh.seek(0)
    fh.truncate()
    fh.write(str(os.getpid()))
    fh.flush()
    return fh


def main(once: bool = False) -> int:
    store = Store()
    try:
        lock = acquire_daemon_lock(store)  # noqa: F841  (held until exit)
    except DaemonRunning as e:
        print(str(e), file=sys.stderr)
        return 3
    with store.locked():  # a crash mid-turn left busy markers from our pid's predecessor: clear them
        for t in store.all_threads():
            changed = False
            if t.get("busy") and (not _pid_alive(t.get("turn_owner")) or t.get("turn_owner") == os.getpid()):
                t["busy"], t["busy_since"], t["turn_owner"] = False, None, None
                changed = True
            want = "prospect" if t.get("demo") else roles.role_for(t["channel"])
            if t.get("role", "prospect") != want:  # role changed in .env: fresh World in the new role; old messages
                t.update(role=want, world=None, history=None, stage=roles.initial_stage(want), lease_sent=None,
                         world_synced=[m["id"] for m in t["messages"] if m["direction"] == "in"])
                changed = True
            if changed:
                store.save_thread(t)
    register_adapters(store)
    with store.locked():
        since = demo.open_since(store)  # open mode: messages from before this moment are never answered
    allow = config.Allowlist.load()
    print(time.strftime("%H:%M:%S"), f"live daemon pid={os.getpid()}: dir={store.root} allowlist={allow.size()} "
          f"send_enabled={config.send_enabled()} public={'open since ' + since if since else ('keyword' if demo.keyword_mode() else 'off')} lines={[str(l) for l in config.sms_lines()]}", flush=True)
    if once:
        try:
            r = tick(store)
            print(time.strftime("%H:%M:%S"), r, flush=True)
        except Exception:
            print(time.strftime("%H:%M:%S"), traceback.format_exc(limit=3), flush=True)
        return 0
    runner = Runner(store, log=lambda *a: print(*a, flush=True)).start()
    print(time.strftime("%H:%M:%S"), "pollers: " + ", ".join(f"{k} every {_interval(k):g}s" for k, _ in sources()),
          flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        runner.close()
        return 0
