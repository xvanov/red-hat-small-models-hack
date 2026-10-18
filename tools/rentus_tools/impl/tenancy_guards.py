"""Tenancy send guards (owner decisions D29), enforced by send_message.

1. Guardrailed promises. The agent is a full property manager, but a discount, a hold, a waived fee, a
   payment plan or grace, a deposit return, a repair date, a rule exception or an enforcement step reaches a
   tenant or prospect only when the owner pre-approved it (a record in `world.approvals` for that person, or
   ref_id '*'), or it sits inside an owner-set bound (`policy.promise_bounds[kind]`). Otherwise send_message
   refuses with a hint to escalate_to_owner with the message as the draft. Hedged sentences ("let me check on
   the discount") and, for plans and grace, questions ("how do you plan to pay?") are not promises.
2. Late fee only from the lease: naming a late fee on a tenant thread whose lease has none is refused.
3. Languages: Spanish is handled; a Russian thread (or a Russian draft) is drafted for the owner instead.
4. Safety first: after triage_maintenance flags an emergency on a thread, the first message on it must be
   the safety instruction.

Deterministic regex checks, no model.
"""
from __future__ import annotations

import re

KIND_LABEL = {"discount": "a discount", "hold": "a hold", "waive_fee": "a waived fee", "payment_plan": "a payment plan",
              "grace": "extra time to pay", "deposit_return": "a deposit return", "repair_date": "a repair date",
              "rule_exception": "a rule exception", "enforcement": "an enforcement step"}

_DAY = r"(?:today|tomorrow|tonight|monday|tuesday|wednesday|thursday|friday|saturday|sunday|this week|next week)"
_DIA = r"(?:hoy|mañana|esta semana|lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo)"
PROMISE = {
    "discount": re.compile(
        r"\bdiscount\w*|\b\d+\s?%\s?off\b|\$\s?\d[\d,]*\s+off\b|\boff (?:the|your) (?:first month|rent)\b"
        r"|\b(?:lower|reduce|drop)\w* (?:the |your )?(?:rent|price)\b|\bdescuento\w*|\brebaj\w*|\bbajar (?:la|tu) renta\b",
        re.I),
    "hold": re.compile(
        r"\b(?:hold|reserve|save|keep)\w* (?:the |this |that |your )?(?:room|spot|place|it) (?:for you|until)\b"
        r"|\bi(?:'ll| will| can) hold\b|\bon hold for you\b|\bte (?:lo |la )?(?:aparto|guardo|reservo)\b", re.I),
    "waive_fee": re.compile(
        r"\bwaiv\w*|\bno late fee\b|\bwon'?t (?:charge|add|apply) (?:you )?(?:a |the |any )?(?:late )?fee|\bskip (?:the |your )?(?:late )?fee"
        r"|\bforget (?:about )?the (?:late )?fee|\b(?:perdon|condon|quit)\w* (?:el|la|tu) (?:recargo|multa|cargo)|\bsin (?:recargo|multa)\b",
        re.I),
    "payment_plan": re.compile(
        r"\bpayment plan\b|\bplan de pagos?\b|\bpay (?:it |the rent )?in (?:two|2|three|3) (?:parts|payments|installments)\b"
        r"|\bsplit (?:the|your|it)\b|\binstallments?\b|\bcuotas?\b|\ben dos pagos\b"
        r"|\b(?:you can|it'?s (?:fine|ok(?:ay)?) to) pay (?:the rest|the balance|it) (?:on|by|next|later|after|with)\b"
        r"|\bpuedes pagar (?:el resto|lo que falta) (?:el|para|despu[eé]s|con)\b", re.I),
    "grace": re.compile(
        r"\bthat works this time\b|\b(?:it'?s|that'?s) (?:fine|ok(?:ay)?) (?:this time|to pay (?:on|by|late))\b"
        r"|\bpor esta vez\b|\bno hay problema si pagas\b", re.I),
    "deposit_return": re.compile(
        r"\b(?:return|refund|give (?:you )?back|send (?:you )?back)\w* (?:\$\s?\d[\d,.]* (?:of |from )?)?(?:your |the )?(?:full |whole )?deposit\b"
        r"|\bdeposit (?:back|refund)\b|\bdevol\w* (?:el |tu |su )?(?:dep[oó]sito)\b|\breembols\w*", re.I),
    "repair_date": re.compile(
        r"\b(?:fix|repair)\w*\b[^.?!]{0,40}\b" + _DAY + r"\b|\b(?:plumber|electrician|technician|vendor|someone|tech|"
        r"hvac|contractor)\b[^.?!]{0,30}\b(?:will|is going to|'ll|is)\b[^.?!]{0,15}\b(?:come|coming|be there|stop by)\b[^.?!]{0,30}\b"
        + _DAY + r"\b|\b(?:arregl|repar)\w*\b[^.?!]{0,40}\b" + _DIA + r"\b|\b(?:t[eé]cnico|plomero|electricista)\b[^.?!]{0,30}"
        r"\b(?:viene|vendr[aá]|va a ir|pasa)\b[^.?!]{0,30}\b" + _DIA + r"\b", re.I),
    "rule_exception": re.compile(
        r"\b(?:make|making|made) an exception\b|\bexcepci[oó]n\b|\b(?:you can|it'?s (?:fine|ok(?:ay)?) to) "
        r"(?:smoke|have (?:a )?part(?:y|ies)|keep (?:the|your) (?:dog|pet))\b|\bi(?:'ll| will) allow\b", re.I),
    "enforcement": re.compile(
        r"\bevict\w*|\bdesalo\w*|\bdesahuci\w*|\bcourt\b|\btribunal\b|\bjuzgado\b|\blawyer|\battorney|\babogad\w*"
        r"|\blegal action\b|\bacci[oó]n legal\b|\bnotice to (?:vacate|quit)\b|\bcredit (?:report|bureau)\w*|\bsmall claims\b"
        r"|\bterminat\w* (?:your|the) lease\b|\bcollections? agency\b", re.I),
}
# Not a promise: the agent says it will check, cannot promise, or relays that it is the owner's call.
HEDGE = re.compile(
    r"\b(?:check|ask|look into|see what|confirm|get back to you|let you know|come back to you|can'?t promise|cannot promise"
    r"|not able to|unable to|can'?t (?:offer|do|give|waive)|no puedo|revis\w*|consult\w*|te (?:aviso|confirmo|digo)"
    r"|averigu\w*|veo qu[eé])\b", re.I)
QUESTION_OK = {"payment_plan", "grace"}   # asking how they plan to pay is the collaborative first step


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?…])\s+|\n+", text)
    return [p.strip() for p in parts if p.strip()]


def _ids_for_thread(world, thread: dict) -> set[str]:
    ids = {thread["thread_id"]}
    if thread.get("room_id"):
        ids.add(thread["room_id"])
    if thread.get("listing_id"):
        ids.add(thread["listing_id"])
    for r in world.register:
        if thread["thread_id"] in r.get("thread_ids", []):
            ids.add(r["renter_id"])
    for t in world.tenants:
        if thread["thread_id"] in t.get("thread_ids", []):
            ids.add(t["tenant_id"])
            if t.get("room_id"):
                ids.add(t["room_id"])
    return ids


def _allowed(world, thread: dict, kind: str, sentence: str) -> bool:
    from ._util import dollar_figures
    ids = _ids_for_thread(world, thread)
    for a in world.approvals:
        if a.get("status", "approved") != "approved" or a.get("kind") != kind:
            continue
        if a.get("ref_id") in ids or a.get("ref_id") == "*":
            cap = a.get("max_usd")
            if cap is None or all(f <= float(cap) for f in dollar_figures(sentence)):
                return True
    bound = (world.policy.get("promise_bounds") or {}).get(kind)
    if bound is not None and bound is not False:
        cap = bound.get("max_usd") if isinstance(bound, dict) else None
        if cap is None or all(f <= float(cap) for f in dollar_figures(sentence)):
            return True
    from .tenancy import tenant_for_thread
    t = tenant_for_thread(world, thread["thread_id"])
    if t and kind in ("payment_plan", "grace") and (t.get("plan") or {}).get("status") in ("approved", "sent", "done"):
        return True
    if kind == "repair_date":   # a booked vendor's date is a fact, not a promise
        rooms = {x for x in ids if world.get("rooms", x)}
        if any(j.get("status") == "booked" and j.get("scheduled_for") and (j.get("room_id") in rooms or j.get("thread_id") == thread["thread_id"])
               for j in world.jobs):
            return True
    return False


def promise_violations(world, thread: dict, text: str) -> list[tuple[str, str]]:
    """(kind, sentence) for every commitment in `text` the owner has not approved for this person."""
    out = []
    for s in _sentences(text):
        is_q = s.endswith("?") or s.startswith("¿")
        for kind, pat in PROMISE.items():
            if not pat.search(s):
                continue
            if kind != "enforcement" and HEDGE.search(s):
                continue
            if is_q and kind in QUESTION_OK:
                continue
            if not _allowed(world, thread, kind, s):
                out.append((kind, s))
    return out


LATE_FEE_WORDS = re.compile(r"\blate fees?\b|\brecargos? por (?:pago )?(?:tard[ií]o|atraso|retraso)\b|\bmulta por (?:atraso|retraso)\b", re.I)


def late_fee_violation(world, thread: dict, text: str) -> str | None:
    """A late fee named on a tenant thread whose lease has none."""
    from .tenancy import tenant_for_thread
    t = tenant_for_thread(world, thread["thread_id"])
    if not t or (t.get("lease") or {}).get("late_fee") is not None:
        return None
    for s in _sentences(text):
        if LATE_FEE_WORDS.search(s) and not re.search(r"\bno late fee|\bsin recargo", s, re.I):
            return s
    return None


# ----------------------------------------------------------------------------- languages

CYRILLIC = re.compile(r"[Ѐ-ӿ]")


def _cyr_share(text: str) -> float:
    letters = re.findall(r"[^\W\d_]", text or "")
    return (sum(bool(CYRILLIC.match(c)) for c in letters) / len(letters)) if letters else 0.0


def owner_draft_language(world, thread: dict, text: str) -> str | None:
    """'ru' when this thread must be drafted for the owner (policy.languages.draft_for_owner)."""
    langs = (world.policy.get("languages") or {}).get("draft_for_owner") or []
    if "ru" not in langs:
        return None
    if thread.get("language") == "ru" or _cyr_share(text) > 0.3:
        return "ru"
    for m in reversed(thread.get("messages", [])):
        if m.get("from") == "renter":
            if _cyr_share(m.get("text") or "") > 0.3:
                return "ru"
            if re.search(r"[a-záéíóúñ]{3,}", (m.get("text") or "").lower()):
                return None
    return None


# ----------------------------------------------------------------------------- safety first

def safety_first_violation(thread: dict, text: str) -> dict | None:
    em = thread.get("emergency") or {}
    if not em or em.get("safety_sent"):
        return None
    if any(w in text.lower() for w in em.get("must_any", [])):
        return None
    return em


def mark_safety_sent(thread: dict, text: str) -> None:
    em = thread.get("emergency") or {}
    if em and not em.get("safety_sent") and any(w in text.lower() for w in em.get("must_any", [])):
        em["safety_sent"] = True
