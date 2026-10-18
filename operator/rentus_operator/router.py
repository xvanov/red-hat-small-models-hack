"""Triage router: the 0.6B reader reads every inbound renter message before Lightning does.

Per inbound burst the router picks one decision, logs it as an event (type "verifier", actor "router", data.stage "router"), and
only then, if a reply is owed, hands Lightning one turn with the reader's parse injected:

  NO_OP            platform system texts ("X reacted to your message"), duplicates, and
                   emoji-only / thank-you acks while no question of ours is pending. Lightning
                   is not called.
  RECORD_ONLY      the message is pure data the reader extracted with high confidence (the
                   model reader and the rule-based reader agree, value validates). Code writes it
                   to the register; Lightning is called only if a reply is actually owed.
  BATCH            two or more messages arrived before we answered: read each, merge the
                   parses, one Lightning turn for the whole burst.
  ESCALATE_DIRECT  hard no (both readers agree), or abuse: code escalates to the owner queue
                   with the reader's structured summary (and marks a hard no "lost"). Lightning
                   writes the single courteous close for a hard no; abuse gets no reply.
  LIGHTNING        everything else, with the reader's parse in the turn's context.

Every renter-facing message is still written by Lightning: the router never sends anything.
High-confidence register writes are the only state the router changes (plus the escalation).

`run_conversation()` is the event-driven driver: inbound -> route -> (maybe) one Lightning turn,
which ends as soon as its send_message to the thread succeeds; the renter's next message is the
next inbound event. Enabled by RunConfig(router=True); with it off, nothing here runs.
"""
from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass, field

from . import toolbox
from .config import RunConfig
from .loop import RunResult, make_client, run

NO_OP, RECORD_ONLY, BATCH, ESCALATE_DIRECT, LIGHTNING = (
    "NO_OP", "RECORD_ONLY", "BATCH", "ESCALATE_DIRECT", "LIGHTNING")
DECISIONS = (NO_OP, RECORD_ONLY, BATCH, ESCALATE_DIRECT, LIGHTNING)

FIELDS = ("lease", "move_in", "phone", "occupants", "reason")
GOOD = ("answered", "exception")
STATUS_RANK = {"answered": 4, "exception": 4, "no": 3, "vague": 2, "absent": 0}
CLOSED_STATUSES = {"showing_proposed", "showing_confirmed", "applied", "leased", "not_now", "lost", "escalated"}

# Platform system texts, never written by a person.
SYSTEM_RX = re.compile(
    r"^\s*[\w.'-]+(?:\s[\w.'-]+){0,2}\s(?:reacted|liked|loved|emphasi[sz]ed|laughed at|disliked|questioned)\b"
    r"[^?]{0,20}?\b(?:to\s)?(?:your|a|this|the)\s(?:message|photo|link|comment|listing)\.?\s*$|"
    r"^\s*(?:liked|loved|laughed at|emphasi[sz]ed|disliked|questioned)\s[\"“].*[\"”]\s*$|"
    r"^\s*[\w.'-]+(?:\s[\w.'-]+){0,2}\s(?:unsent|deleted|removed)\s(?:a|this|the)\smessage\.?\s*$|"
    r"^\s*(?:you are now connected|you're now connected|this conversation (?:is|was) (?:started|marked)|"
    r"missed (?:voice |video )?call|\[(?:sticker|gif|image|attachment)\])\b.*$|"
    r"^\s*[\w.'-]+(?:\s[\w.'-]+){0,2}\s(?:is typing|started (?:the|this) (?:chat|conversation)|"
    r"(?:joined|left) (?:the|this) (?:chat|conversation|group))\.?\s*$", re.I)
ACK_WORDS = {"ok", "okay", "k", "kk", "thanks", "thank you", "thx", "ty", "tysm", "cool", "great", "nice",
             "perfect", "awesome", "sounds good", "got it", "alright", "yes thanks", "gracias", "muchas gracias",
             "vale", "perfecto", "listo", "de nada", "ok gracias", "okay thanks", "ok thanks", "ok thank you"}
ABUSE_RX = re.compile(r"\b(?:fuck(?:ing)?|f\*+k|motherf\w*|bitch|cunt|asshole|retard\w*|scam(?:mer)?s?\b.*\breport|"
                      r"i(?:'ll| will) (?:kill|hurt|find) you|hijo de puta|pendejo|chinga\w*)\b", re.I)


# ----------------------------------------------------------------------------------- signals
def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", (text or "").lower(), flags=re.U)).strip()


def is_system_text(text: str) -> bool:
    return bool(SYSTEM_RX.search(text or ""))


def is_ack(text: str) -> bool:
    """Emoji-only, punctuation-only, or a bare thank-you / ok."""
    core = re.sub(r"[!.,?¡¿~]+", " ", re.sub(r"[^\w\s!.,?¡¿~']", "", text or "", flags=re.U)).lower()
    core = re.sub(r"\s+", " ", core).strip()
    return core == "" or core.rstrip("s") in ACK_WORDS or core in ACK_WORDS or core.replace(" so much", "") in ACK_WORDS


def is_abusive(text: str) -> bool:
    return bool(ABUSE_RX.search(text or ""))


def question_pending(thread_msgs: list[dict]) -> bool:
    """Our last message on the thread asked something."""
    for m in reversed(thread_msgs):
        if m.get("from") in ("operator", "owner"):
            return "?" in (m.get("text") or "")
    return True   # we never wrote: an opening message is always owed a reply


# ----------------------------------------------------------------------------------- state
def _threads(st: dict) -> list[dict]:
    ts = st.get("threads") or []
    return list(ts.values()) if isinstance(ts, dict) else list(ts)


def thread_of(world, thread_id: str) -> dict | None:
    return next((t for t in _threads(toolbox.state(world)) if t.get("thread_id") == thread_id), None)


def renter_row(world, thread_id: str) -> dict | None:
    for r in toolbox.state(world).get("register") or []:
        if thread_id in (r.get("thread_ids") or []) or r.get("thread_id") == thread_id:
            return r
    return None


def gate_missing(row: dict | None, floor: int = 6) -> list[str]:
    """Same strict rule as the register tool's gate_missing."""
    g = (row or {}).get("gate") or {}
    miss = []
    for k in FIELDS:
        v = g.get(k) or {}
        ok = v.get("status") in GOOD and (v.get("date") if k == "move_in" else v.get("value"))
        if k == "lease":   # mirrors rentus_tools register.lease_ok (D23: an accepted term >= the floor passes)
            m = v.get("months")
            ok = v.get("status") == "answered" and (m >= floor if isinstance(m, int) and not isinstance(m, bool)
                                                    else v.get("value") is True)
        if k == "reason":
            ok = v.get("status") == "answered" and v.get("value")
        if not ok:
            miss.append(k)
    return miss


# ----------------------------------------------------------------------------------- reading
def _fallback_reader():
    try:
        from rentus_tools.impl.reader import read_reply_fallback  # type: ignore
        return read_reply_fallback
    except Exception:  # noqa: BLE001 - shim backend: no second reader, so nothing counts as confident
        return None


def _same_value(field_: str, a: dict, b: dict) -> bool:
    if a.get("status") not in GOOD or b.get("status") not in GOOD:
        return False
    if field_ == "move_in":
        return bool(a.get("date")) and a.get("date") == b.get("date")
    va, vb = a.get("value"), b.get("value")
    if field_ == "reason":
        return bool(va) and bool(vb)        # free text: agreement that a concrete reason was given
    return va is not None and va == vb


def confident_items(parse: dict, check: dict | None, text: str) -> dict:
    """Gate items both readers agree on, in the register's shape. Empty without a second reader."""
    if not check:
        return {}
    out = {}
    for f in FIELDS:
        a, b = parse.get(f) or {}, check.get(f) or {}
        if not _same_value(f, a, b):
            continue
        if f == "phone" and len(re.sub(r"\D", "", text or "")) < 10:
            continue
        if f == "lease" and a.get("value") is not True:
            continue
        item = {"status": a["status"]}
        if f == "move_in":
            item.update({"date": a.get("date"), "raw": a.get("raw")})
        else:
            item["value"] = a.get("value")
        out[f] = item
    return out


def merge_parses(parses: list[dict]) -> dict:
    """One parse for a burst: per field the most decisive status (a later message wins a tie)."""
    if not parses:
        return {}
    out = {"intents": [], "language": parses[-1].get("language", "en")}
    for f in FIELDS:
        best = None
        for p in parses:
            v = p.get(f) or {"status": "absent"}
            if best is None or STATUS_RANK.get(v.get("status"), 0) >= STATUS_RANK.get(best.get("status"), 0):
                best = v
        out[f] = best
    for p in parses:
        for i in p.get("intents") or []:
            if i not in out["intents"]:
                out["intents"].append(i)
    if len(out["intents"]) > 1 and "small_talk" in out["intents"]:
        out["intents"].remove("small_talk")
    return out


def parse_summary(parse: dict) -> str:
    bits = []
    for f in FIELDS:
        v = parse.get(f) or {}
        st = v.get("status", "absent")
        if st == "absent":
            continue
        val = v.get("date") if f == "move_in" else v.get("value")
        raw = v.get("raw") if f == "move_in" and not val else None
        bits.append(f"{f}={st}" + (f"({json.dumps(val, ensure_ascii=False)})" if val is not None else "")
                    + (f"(said {json.dumps(raw, ensure_ascii=False)})" if raw else ""))
    bits.append(f"intents={parse.get('intents') or []}")
    bits.append(f"language={parse.get('language', 'en')}")
    return ", ".join(bits)


def register_summary(row: dict | None) -> str:
    g = (row or {}).get("gate") or {}
    bits = []
    for f in FIELDS:
        v = g.get(f) or {}
        if v.get("status") in GOOD:
            val = v.get("date") if f == "move_in" else v.get("value")
            bits.append(f"{f}={json.dumps(val, ensure_ascii=False)}")
    if row and row.get("renter_id"):
        bits.append(f"renter_id={row['renter_id']}")
    return ", ".join(bits)


def protect_gate(args: dict, row: dict | None) -> tuple[dict, list[str]]:
    """Router mode: drop gate items from an upsert_renter call that would erase an item already recorded with an
    exact value (a status-only or value-less update). Returns (args to run, items dropped)."""
    fields = (args or {}).get("fields")
    gate = fields.get("gate") if isinstance(fields, dict) else None
    if not isinstance(gate, dict) or not row:
        return args, []
    have = row.get("gate") or {}
    dropped = []
    for k, v in list(gate.items()):
        cur = have.get(k) or {}
        cur_val = cur.get("date") if k == "move_in" else cur.get("value")
        if cur.get("status") not in GOOD or cur_val in (None, ""):
            continue
        new_val = (v.get("date") if k == "move_in" else v.get("value")) if isinstance(v, dict) else v
        if new_val in (None, "") or (isinstance(v, dict) and v.get("status", "answered") not in GOOD) \
                or (k == "lease" and not isinstance(new_val, bool)):
            dropped.append(k)
    if not dropped:
        return args, []
    gate = {k: v for k, v in gate.items() if k not in dropped}
    fields = {k: v for k, v in fields.items() if k != "gate"} | ({"gate": gate} if gate else {})
    return {**args, "fields": fields}, dropped


# ----------------------------------------------------------------------------------- decision
@dataclass
class Decision:
    decision: str
    thread_id: str
    reason: str
    message_ids: list[str] = field(default_factory=list)
    texts: list[str] = field(default_factory=list)
    parse: dict | None = None
    recorded: dict = field(default_factory=dict)
    escalation: str | None = None
    reply_owed: bool = False
    note: str | None = None          # the context injected into Lightning's turn

    @property
    def invoke_lightning(self) -> bool:
        return self.reply_owed and self.decision != NO_OP

    def event(self) -> dict:
        return {"decision": self.decision, "thread_id": self.thread_id, "reason": self.reason,
                "message_ids": self.message_ids, "n_messages": len(self.texts),
                "parse": self.parse, "recorded": self.recorded, "escalation": self.escalation,
                "reply_owed": self.reply_owed, "lightning": self.invoke_lightning}


class Router:
    """Holds which renter messages it has already routed; one per conversation (or inbox)."""

    def __init__(self, world, backend, sink=None, cfg: RunConfig | None = None):
        self.world, self.be, self.sink, self.cfg = world, backend, sink, cfg or RunConfig()
        self.seen: set[str] = set()
        self.fallback = _fallback_reader()

    def _call(self, name: str, args: dict) -> dict:
        try:
            return toolbox.call(self.be, self.world, name, args, sink=self.sink, actor="router",
                                call_id=f"router_{uuid.uuid4().hex[:6]}")
        except Exception as e:  # noqa: BLE001 - the router must never crash a conversation
            return {"ok": False, "error": {"code": "UPSTREAM_ERROR", "message": f"{type(e).__name__}: {e}"}}

    def pending(self, thread_id: str) -> list[dict]:
        """Renter messages after our last message that the router has not routed yet."""
        t = thread_of(self.world, thread_id) or {}
        msgs = t.get("messages") or []
        last_ours = max((i for i, m in enumerate(msgs) if m.get("from") in ("operator", "owner")), default=-1)
        return [m for m in msgs[last_ours + 1:] if m.get("from") not in ("operator", "owner")
                and self._mid(m) not in self.seen]

    def ready(self, thread_id: str, now_ts: float | None = None) -> bool:
        """Live inbox: route only after cfg.router_quiet_s of silence, so a burst becomes one BATCH.
        Message ts are ISO strings; with quiet_s 0 (the Gym) anything pending is ready."""
        new = self.pending(thread_id)
        if not new:
            return False
        if self.cfg.router_quiet_s <= 0:
            return True
        from datetime import datetime
        try:
            last = datetime.fromisoformat(str(new[-1].get("ts"))).timestamp()
        except (TypeError, ValueError):
            return True
        return (now_ts if now_ts is not None else time.time()) - last >= self.cfg.router_quiet_s

    @staticmethod
    def _mid(m: dict) -> str:
        return m.get("id") or f"{m.get('ts')}|{m.get('text')}"

    def _read(self, thread_id: str, text: str, is_latest: bool, context: list[dict]) -> tuple[dict, dict | None]:
        args = {"thread_id": thread_id} if is_latest else {"text": text}
        env = self._call("read_reply", args)
        parse = env.get("data") if env.get("ok") else None
        check = None
        if self.fallback is not None:
            try:
                check = self.fallback(text, context=context, today=toolbox.today(self.world))
            except Exception:  # noqa: BLE001
                check = None
        if not isinstance(parse, dict) or parse.get("backend") == "fallback":
            # the model reader is down (read_reply fell back to rules): one reader only, nothing is confident
            parse = parse if isinstance(parse, dict) else (check or {"intents": [], "language": "en"})
            check = None
        return parse, check

    def route(self, thread_id: str) -> Decision:
        t = thread_of(self.world, thread_id) or {}
        msgs = t.get("messages") or []
        new = self.pending(thread_id)
        d = self._decide(thread_id, t, msgs, new)
        self.seen.update(self._mid(m) for m in new)
        toolbox.emit(self.sink, "verifier", "router", {"stage": "router", **d.event()})
        return d

    def _decide(self, thread_id: str, t: dict, msgs: list[dict], new: list[dict]) -> Decision:
        ids = [self._mid(m) for m in new]
        texts = [m.get("text") or "" for m in new]
        mk = lambda dec, why, **kw: Decision(dec, thread_id, why, ids, texts, **kw)  # noqa: E731
        if not new:
            return mk(NO_OP, "no new renter message")

        # a duplicate = the same text re-sent before we answered; a repeat that answers a new question of ours is not
        last_ours = max((i for i, m in enumerate(msgs) if m.get("from") in ("operator", "owner")), default=-1)
        earlier = {_norm(m.get("text")) for m in msgs[last_ours + 1:] if m.get("from") not in ("operator", "owner")
                   and self._mid(m) not in ids}
        asked = question_pending(msgs)
        keep, dropped, seen_now = [], [], set()
        for m in new:
            txt, n = m.get("text") or "", _norm(m.get("text"))
            if is_system_text(txt):
                dropped.append("system text")
            elif n and (n in earlier or n in seen_now):
                dropped.append("duplicate")
            elif is_ack(txt) and not asked:
                dropped.append("ack with no question pending")
            else:
                keep.append(m)
            seen_now.add(n)
        if not keep:
            return mk(NO_OP, "; ".join(sorted(set(dropped))))

        if any(is_abusive(m.get("text")) for m in keep):
            summary = "abusive message: " + " | ".join(m.get("text", "")[:200] for m in keep)
            env = self._call("escalate_to_owner", {"reason": f"[router] {summary}"[:500], "ref_id": thread_id})
            esc = ((env.get("data") or {}).get("escalation") or {}).get("esc_id")
            return mk(ESCALATE_DIRECT, "abuse", escalation=esc, reply_owed=False)

        # read every kept message (the 0.6B reader, cross-checked by the rule reader)
        all_idx = {self._mid(m): i for i, m in enumerate(msgs)}
        parses, confident = [], {}
        for j, m in enumerate(keep):
            i = all_idx.get(self._mid(m), len(msgs))
            ctx = [{"role": x.get("from"), "text": x.get("text")} for x in msgs[:i]][-6:]
            parse, check = self._read(thread_id, m.get("text") or "", j == len(keep) - 1 and m is new[-1], ctx)
            parses.append(parse)
            for k, v in confident_items(parse, check, m.get("text") or "").items():
                confident[k] = v
            if check is not None and "hard_no" in (parse.get("intents") or []) and "hard_no" in (check.get("intents") or []):
                parse["_hard_no_agreed"] = True
        parse = merge_parses(parses)
        hard_no = any(p.get("_hard_no_agreed") for p in parses)
        for p in parses:
            p.pop("_hard_no_agreed", None)

        row = renter_row(self.world, thread_id)
        if hard_no:
            env = self._call("escalate_to_owner", {"ref_id": thread_id, "reason": (
                f"[router] renter {t.get('renter_name') or thread_id} said no, closed as not interested. "
                f"Reader: {parse_summary(parse)}")[:500]})
            esc = ((env.get("data") or {}).get("escalation") or {}).get("esc_id")
            up = self._call("upsert_renter", {"thread_id": thread_id, "fields": {"status": "lost"}})
            rec = {"status": "lost"} if up.get("ok") else {}
            ours = [m for m in msgs if m.get("from") in ("operator", "owner")]
            owed = not ((row or {}).get("status") == "lost")   # one courteous close, never a second
            d = mk(ESCALATE_DIRECT, "hard no (model and rule reader agree)", parse=parse, recorded=rec,
                   escalation=esc, reply_owed=owed)
            d.note = self._note_close(t, thread_id, texts, parse, esc, first=not ours)
            return d

        # high-confidence data goes to the register by code (never overwriting an answered item)
        have = ((row or {}).get("gate") or {})
        to_write = {k: v for k, v in confident.items() if (have.get(k) or {}).get("status") not in GOOD}
        recorded = {}
        if to_write:
            up = self._call("upsert_renter", {"thread_id": thread_id, "fields": {"gate": to_write}})
            if up.get("ok"):
                recorded = to_write
                row = (up.get("data") or {}).get("renter") or renter_row(self.world, thread_id)

        other = [f for f in FIELDS if (parse.get(f) or {}).get("status", "absent") != "absent" and f not in confident]
        intents = [i for i in parse.get("intents") or [] if i != "small_talk"]
        pure_data = bool(recorded) and not other and not intents
        closed = (row or {}).get("status") in CLOSED_STATUSES
        missing = gate_missing(row)
        # a reply is owed unless the renter's file is closed and they asked nothing new
        owed = not (closed and not intents and not any("?" in x for x in texts))
        if pure_data:
            dec, why = RECORD_ONLY, f"pure data, recorded {sorted(recorded)}"
        else:
            dec, why = LIGHTNING, "needs the operator"
        if len(keep) > 1 and dec != NO_OP:
            why = f"{len(keep)} messages merged; {why}" + (f" ({dec})" if dec != LIGHTNING else "")
            dec = BATCH
        d = mk(dec, why, parse=parse, recorded=recorded, reply_owed=owed)
        d.note = self._note(t, thread_id, [m.get("text") or "" for m in keep], parse, recorded, missing,
                            first=not any(m.get("from") in ("operator", "owner") for m in msgs))
        return d

    # ---- what Lightning sees for this turn
    def _head(self, t: dict, thread_id: str, texts: list[str]) -> str:
        who = t.get("renter_name") or "a renter"
        said = "\n".join(f'  "{x}"' for x in texts)
        n = "message" if len(texts) == 1 else f"{len(texts)} messages (sent in a row, answer them together)"
        return f"[router] New renter {n} on {t.get('channel', 'a channel')} thread {thread_id} from {who}:\n{said}"

    def _note(self, t, thread_id, texts, parse, recorded, missing, first) -> str:
        lines = [self._head(t, thread_id, texts),
                 f"Reader parse (already done for these messages, do not call read_reply for them): {parse_summary(parse)}."]
        if recorded:
            lines.append("Already recorded to the register by code, do not record again: "
                         + ", ".join(f"{k}={json.dumps(v.get('date') if k == 'move_in' else v.get('value'), ensure_ascii=False)}"
                                     for k, v in recorded.items()) + ".")
        reg_now = register_summary(renter_row(self.world, thread_id))
        if reg_now:
            lines.append(f"Register now: {reg_now}.")
        lines.append("Gate items still missing: " + (", ".join(missing) if missing else
                     "none, the gate is complete: do not call upsert_renter for gate items again, go to "
                     "find_showing_slots and propose_showing") + ".")
        if first:
            lines.append("This is the first message on the thread: read_thread and get_room first.")
        lines.append(f"Record with upsert_renter any answered item the router did not record, do any other action "
                     f"(find_showing_slots, propose_showing, escalate_to_owner) BEFORE replying: your turn ends as soon "
                     f"as your send_message to {thread_id} succeeds, and the renter's answer comes as the next message.")
        return "\n".join(lines)

    def _note_close(self, t, thread_id, texts, parse, esc, first) -> str:
        return "\n".join([
            self._head(t, thread_id, texts),
            f"Reader parse (already done): {parse_summary(parse)}.",
            f"The router already escalated this to the owner ({esc or 'escalation'}) and marked the renter lost in the "
            "register. Do not call any other tool" + (" except read_thread" if first else "") + ".",
            f"Write one short, kind closing reply in your own words with send_message to {thread_id}: no question, "
            "no more qualifying. Your turn ends when it is sent."])


# ----------------------------------------------------------------------------------- driver
@dataclass
class ConversationResult:
    run_id: str
    status: str
    final_text: str
    steps: int
    tool_calls: int
    messages: list[dict]
    ledger: list[dict]
    decisions: list[dict]
    lightning_turns: int
    escalations: list[str] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    self_check: list[str] = field(default_factory=list)
    config: str = ""


def run_conversation(world, inbound: dict, client=None, *, config: RunConfig | None = None, sink=None,
                     backend=None, history: list[dict] | None = None, run_id: str | None = None,
                     sleep=time.sleep, max_events: int = 40) -> ConversationResult:
    """Route every inbound renter message on `inbound["thread_id"]` until the thread goes quiet or the
    step budget (cfg.max_steps Lightning calls, the same budget a router-off run gets) is spent."""
    cfg = config or RunConfig(router=True)
    be = backend or toolbox.backend()
    run_id = run_id or f"r_{uuid.uuid4().hex[:8]}"
    if sink is None:
        sink = toolbox.make_sink(be, run_id)
    if client is None:
        client = make_client(cfg)
    tid = inbound["thread_id"]
    router = Router(world, be, sink, cfg)
    decisions, ledger, escalations, messages = [], [], [], list(history or [])
    steps = calls = turns = 0
    status, final_text, checks = "done", "", []
    for _ in range(max_events):
        if not router.pending(tid):
            break
        d = router.route(tid)
        decisions.append(d.event())
        if d.escalation:
            escalations.append(d.escalation)
        if not d.invoke_lightning:
            continue
        left = cfg.max_steps - steps
        if left <= 0:
            status = "max_steps"
            break
        goal = {"thread_id": tid, "channel": inbound.get("channel"), "renter_name": inbound.get("renter_name"),
                "router_note": d.note}
        res: RunResult = run(world, goal, client=client, config=cfg.with_(max_steps=left), sink=sink, backend=be,
                             history=messages or None, run_id=f"{run_id}-t{turns + 1}", sleep=sleep, end_on_send=tid)
        turns += 1
        steps += res.steps
        calls += res.tool_calls
        messages = res.messages
        ledger += res.ledger
        escalations += res.escalations
        status, final_text, checks = res.status, res.final_text or final_text, res.self_check
        if res.status in ("model_error",):
            break
    else:
        status = "max_events"
    return ConversationResult(run_id=run_id, status=status, final_text=final_text, steps=steps, tool_calls=calls,
                              messages=messages, ledger=ledger, decisions=decisions, lightning_turns=turns,
                              escalations=escalations, events=list(getattr(sink, "events", []) or []),
                              self_check=checks, config=cfg.label())
