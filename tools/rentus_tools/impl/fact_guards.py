"""Unconfirmed-fact guard (post-freeze safety fix, Oct 18; concierge spec R-DISC-3, C18).

A room record may mark facts the owner has not confirmed: `unconfirmed: ["lease_min_months", "deposit", ...]`.
A core fact field that is missing or null (`lease_min_months`, `deposit`, `utilities`) counts as unconfirmed too.
Public listing text and renter messages may never state an unconfirmed fact; they say "message us for
details" (listings) or "I'll confirm the exact details" and escalate (messages).

Fact keys: lease_min_months, deposit, utilities, furnished, shared_spaces, house_rules.
Deterministic EN/ES regex checks, one sentence at a time, no model.
"""
from __future__ import annotations

import re

from ..errors import ToolError

FACT_KEYS = ("lease_min_months", "deposit", "utilities", "furnished", "shared_spaces", "house_rules")
# Record fields whose absence means "not confirmed" (every inventory room carries all three).
CORE_FIELDS = ("lease_min_months", "deposit", "utilities")
ALIASES = {"lease": "lease_min_months", "lease_length": "lease_min_months", "lease_term": "lease_min_months",
           "rules": "house_rules", "furnishing": "furnished", "shared": "shared_spaces"}

LABEL = {"lease_min_months": "lease length", "deposit": "deposit", "utilities": "utilities",
         "furnished": "furnishing", "shared_spaces": "shared spaces", "house_rules": "house rules"}


def unconfirmed_facts(room: dict | None) -> set[str]:
    if not room:
        return set()
    out = {ALIASES.get(str(k), str(k)) for k in (room.get("unconfirmed") or [])}
    out |= {f for f in CORE_FIELDS if room.get(f) in (None, "")}
    return out


# ----------------------------------------------------------------------------- patterns

_NUM_EN = r"one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|eighteen|twenty[- ]four"
_NUM_ES = r"dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|once|doce|dieciocho|veinticuatro"
_N = r"(?:\d{1,2}|" + _NUM_EN + "|" + _NUM_ES + r")"
# Durations that are not a lease: "available in 2 months", "6 months ago", "hace un año", "one month's rent".
_NOT_BEFORE = r"(?<!\bin )(?<!\bwithin )(?<!\ben )(?<!\bhace )(?<!\bdentro de )(?<!\bevery )(?<!\bcada )"
_NOT_AFTER = r"(?!\s*(?:ago|old|free|'s|’s|of rent|de renta|de alquiler|gratis))"

LEASE = re.compile(
    # "1 year", "12 months", "one-year", "6 meses", "doce meses", "1 año"
    r"\b" + _NOT_BEFORE + _N + r"[- ]?(?:years?|yrs?|months?|mos?|a[nñ]os?|meses|mes)\b" + _NOT_AFTER
    # "un año" / "a one year" / "a year lease"
    + r"|(?<!\bhace )\bun a[nñ]o\b(?!\s*(?:atr[aá]s|pasado))|\ba (?:full |whole )?year[- ]?(?:long )?(?:lease|contract|term|minimum|min)\b"
    r"|\b(?:minimum|min\.?|shortest)\s+(?:lease|stay|term|contract|commitment|rental period)\b"
    r"|\b(?:lease|stay|term|contract|commitment)\s+(?:minimum|min)\b"
    r"|\b(?:yearly|annual|year[- ]long|long[- ]term|short[- ]term)\s+(?:lease|contract|term|rental|commitment)\b"
    r"|\bmonth[- ]to[- ]month\b|\bmes a mes\b"
    r"|\bcontrato\s+(?:m[ií]nimo|anual|de\s+(?:un|1|12|doce|seis|6|\d{1,2})\b)|\bplazo\s+m[ií]nimo\b"
    r"|\bm[ií]nimo\s+de\s+" + _N + r"?\s*(?:a[nñ]os?|meses)\b"
    r"|\blease\s*(?:term|length)?\s*(?::|is|of|for)\s*(?:at least\s+|a\s+)?(?:" + _N + r"|a year|annual|yearly)\b",
    re.IGNORECASE)

_DEP_WORD = r"(?:security\s+)?deposits?|dep[oó]sitos?|fianza"
_DEP_QUAL = (r"\$\s?\d|\d|\b(?:no|zero|free|waived|none|one|first|last|half|full|month'?s?|equal|refundable|required"
             r"|un mes|sin|ning[uú]n|gratis|reembolsable|igual|requerido)\b")
DEPOSIT = re.compile(
    r"\b(?:" + _DEP_WORD + r")\b[^.;\n]{0,40}?(?:" + _DEP_QUAL + r")"
    r"|(?:\$\s?\d[\d,]*|\b(?:no|zero|one month'?s?|first month'?s?|half|sin|un mes de)\b)[^.;\n]{0,20}?\b(?:" + _DEP_WORD + r")\b",
    re.IGNORECASE)

_UTIL_WORD = r"utilit(?:y|ies)|bills|servicios|electric(?:ity)?|water|internet|wi-?fi|luz|agua"
_UTIL_QUAL = (r"\$\s?\d|\d|\b(?:included|incl|includes|split|divided|shared|extra|separate(?:ly)?|flat|paid|covered"
              r"|on top|plus|not included|incluid[oa]s?|divid\w*|compartid\w*|aparte|pagad\w*|fij[oa]s?|cubiert\w*)\b")
UTILITIES = re.compile(
    r"\b(?:" + _UTIL_WORD + r")\b[^.;\n]{0,30}?(?:" + _UTIL_QUAL + r")"
    r"|(?:\$\s?\d[\d,]*|\b(?:includes?|including|incluye|incluyen|with all|plus)\b)[^.;\n]{0,15}?\b(?:" + _UTIL_WORD + r")\b",
    re.IGNORECASE)

FURNISHED = re.compile(r"\b(?:un|semi-?|fully\s+|partially\s+)?furnished\b|\bfurniture\b|\bamueblad[oa]s?\b"
                       r"|\bsin amueblar\b|\bmuebles\b|\bamoblad[oa]s?\b|\bbed (?:and|&) (?:desk|dresser)\b", re.IGNORECASE)

SHARED = re.compile(
    r"\bshared\s+(?:kitchen|living|laundry|spaces?|areas?|common|bath(?:room)?s?)\b"
    r"|\b(?:kitchen|living (?:room|areas?)|common (?:areas?|spaces?)|laundry)\b[^.;\n]{0,40}?\b(?:shared|share)\b"
    r"|\bshare (?:the )?(?:kitchen|living|common|laundry)\b|\bhousemates?\b|\broommates?\b"
    r"|\b(?:cocina|sala|lavander[ií]a)\b[^.;\n]{0,40}?\bcompartid\w*|\bcompartid\w*\s+(?:la\s+)?cocina\b"
    r"|\b(?:[aá]reas?|espacios?) comunes\b|\bcompa[nñ]er[oa]s de casa\b", re.IGNORECASE)

RULES = re.compile(
    r"\bno[- ]smoking\b|\bnon[- ]?smok\w*|\bsmok\w*\s+(?:is\s+)?(?:not\s+)?(?:allowed|permitted|ok|prohibited|outside)\b"
    r"|\bno\s+(?:parties|guests|overnight guests|loud music)\b|\bquiet hours\b|\bhouse rules?\b\s*(?::|are|include)"
    r"|\bno se (?:permite|puede) fumar\b|\bno se fuma\b|\bprohibido fumar\b|\bno fumar\b|\bsin fiestas\b"
    r"|\bno se permiten (?:fiestas|visitas)\b|\breglas de la casa\b\s*(?::|son|incluyen)|\bhoras de silencio\b",
    re.IGNORECASE)

PATTERNS = {"lease_min_months": LEASE, "deposit": DEPOSIT, "utilities": UTILITIES, "furnished": FURNISHED,
            "shared_spaces": SHARED, "house_rules": RULES}

# A sentence that defers ("message us for details on furnishing", "te confirmo si está amueblado") does not
# state a qualitative fact. Lease, deposit and utilities patterns need a figure or a quantity, so no deferral.
DEFER = re.compile(r"\b(?:message us|ask us|contact us|details?|confirm\w*|let you know|get back to you"
                   r"|escr[ií]be(?:nos|me)|preg[uú]nta\w*|detalles?|confirm[oa]r?\w*|te aviso)\b", re.IGNORECASE)
QUALITATIVE = {"furnished", "shared_spaces", "house_rules"}


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?…])\s+|\n+", text or "") if s.strip()]


def unconfirmed_mentions(text: str, room: dict | None, skip_questions: bool = False) -> list[tuple[str, str]]:
    """(fact, phrase) pairs where `text` states a fact the room record does not confirm."""
    unconf = unconfirmed_facts(room) & set(PATTERNS)
    if not unconf:
        return []
    out = []
    for s in _sentences(text):
        if skip_questions and (s.endswith("?") or s.startswith("¿")):
            continue  # asking ("Is a one year lease okay with you?") states nothing about the record
        for fact in FACT_KEYS:
            if fact not in unconf:
                continue
            m = PATTERNS[fact].search(s)
            if not m:
                continue
            if DEFER.search(s) and (fact in QUALITATIVE or (fact == "utilities" and not re.search(r"\d", m.group(0)))):
                continue
            out.append((fact, m.group(0).strip()))
    return out


def check_unconfirmed(text: str, room: dict | None, where: str, skip_questions: bool = False) -> None:
    hits = unconfirmed_mentions(text, room, skip_questions)
    if not hits:
        return
    facts = sorted({f for f, _ in hits}, key=FACT_KEYS.index)
    shown = "; ".join(f"{LABEL[f]} ({p!r})" for f, p in hits)
    raise ToolError("POLICY_BLOCKED",
                    f"{where} states a fact that is not confirmed by the owner for {room.get('room_id')}: {shown}",
                    hint="not confirmed by the owner: leave it out and say 'message us for details' "
                         "(to a renter: 'I'll confirm the exact details'), or escalate_to_owner with a draft",
                    details={"rules": ["unconfirmed_fact"], "rewrite": True, "facts": facts,
                             "phrases": [p for _, p in hits]})
