"""Demand matching helpers (docs/spec/concierge.md §5.4): area resolver, pet rules, hard gates, scoring.

Pure functions over plain dicts, shared by the demand tools and the cluster report.
"""
from __future__ import annotations

import re
from datetime import date

from ._util import num

CANON = ("Durham", "Raleigh", "Chapel Hill", "Cary", "Morrisville", "Garner", "Carrboro", "Apex", "Wake Forest",
         "Hillsborough")
ALIASES = {"rdu": None, "airport": None, "duke": "Durham", "nccu": "Durham", "unc": "Chapel Hill",
           "nc state": "Raleigh", "ncsu": "Raleigh", "downtown raleigh": "Raleigh", "downtown durham": "Durham",
           "southpoint": "Durham", "north hills": "Raleigh", "brier creek": "Raleigh", "carrboro": "Carrboro"}
# Landmarks that expand to a set (Oct 16): the airport sits between four towns.
LANDMARKS = {
    "airport": ["Morrisville", "Cary", "Raleigh", "Durham"],
    "rdu": ["Morrisville", "Cary", "Raleigh", "Durham"],
    "rtp": ["Durham", "Morrisville"],
    "research triangle park": ["Durham", "Morrisville"],
}
# "between X and Y" corridors, endpoints included.
CORRIDORS = {
    frozenset({"airport", "Garner"}): ["Morrisville", "Cary", "Raleigh", "Garner"],
    frozenset({"Durham", "Raleigh"}): ["Durham", "Morrisville", "Cary", "Raleigh"],
    frozenset({"Chapel Hill", "Durham"}): ["Chapel Hill", "Durham"],
    frozenset({"Chapel Hill", "Raleigh"}): ["Chapel Hill", "Durham", "Morrisville", "Cary", "Raleigh"],
    frozenset({"airport", "Durham"}): ["Durham", "Morrisville"],
    frozenset({"airport", "Raleigh"}): ["Morrisville", "Raleigh"],
}
ADJACENT = {frozenset(p) for p in [("Durham", "Chapel Hill"), ("Durham", "Morrisville"), ("Raleigh", "Cary"),
                                     ("Raleigh", "Garner"), ("Cary", "Morrisville"), ("Chapel Hill", "Carrboro"),
                                     ("Cary", "Apex"), ("Raleigh", "Wake Forest"), ("Durham", "Hillsborough")]}


def _canon_word(phrase: str) -> str | None:
    p = phrase.strip().lower()
    for c in CANON:
        if c.lower() in p:
            return c
    for k, v in ALIASES.items():
        if k in p and v:
            return v
    if re.search(r"\b(airport|rdu)\b", p):
        return "airport"
    return None


def resolve_areas(raw, zip_areas: dict | None = None) -> list[str]:
    """Area phrase(s) -> ordered list of canonical areas. Unknown phrases resolve to nothing (never a disqualifier)."""
    phrases = raw if isinstance(raw, list) else ([raw] if raw else [])
    out: list[str] = []

    def add(xs):
        for x in xs:
            if x and x not in out and x != "airport":
                out.append(x)

    for ph in phrases:
        p = str(ph).strip()
        low = p.lower()
        m = re.search(r"\bbetween (.+?) and (.+)$", low)
        if m:
            a, b = _canon_word(m.group(1)), _canon_word(m.group(2))
            if a and b:
                corridor = CORRIDORS.get(frozenset({a, b}))
                if corridor:
                    add(corridor)
                else:
                    for x in (a, b):
                        add(LANDMARKS["airport"] if x == "airport" else [x])
                continue
        z = re.search(r"\b(27\d{3})\b", p)
        if z and zip_areas and z.group(1) in zip_areas:
            add([zip_areas[z.group(1)]])
            continue
        hit = False
        for k, v in LANDMARKS.items():
            if re.search(rf"\b{re.escape(k)}\b", low):
                add(v)
                hit = True
                break
        if hit:
            continue
        for part in re.split(r"\s*(?:,|/|\bor\b|\bo\b|&|\band\b|\by\b)\s*", low):
            c = _canon_word(part)
            if c and c != "airport":
                add([c])
    return out


def area_fit(room_area: str, wanted: list[str]) -> str:
    """'exact' | 'adjacent' | 'no' | 'unknown' (no stated area)."""
    if not wanted:
        return "unknown"
    if room_area in wanted:
        return "exact"
    if any(frozenset({room_area, w}) in ADJACENT for w in wanted):
        return "adjacent"
    return "no"


# ----------------------------------------------------------------------------- pets (R-PET-1, R-PET-2)

def pet_kind(pets) -> str | None:
    """Classify a seeker's pet: dog | cat | rodent_rabbit | enclosed | none | other | None (unstated)."""
    if pets in (None, ""):
        return None
    p = str(pets).lower()
    if re.search(r"^(no|none|no pets?|ninguna?|sin mascotas?)\b", p):
        return "none"
    if re.search(r"\b(rat|rats|mouse|mice|hamster|guinea pig|gerbil|rabbit|bunny|rodent|conejo|rata|h[aá]mster)\b", p):
        return "rodent_rabbit"
    if re.search(r"\b(dog|dogs|puppy|perr[oa]s?)\b", p):
        return "dog"
    if re.search(r"\b(cat|cats|kitten|gat[oa]s?)\b", p):
        return "cat"
    if re.search(r"\b(lizard|snake|gecko|fish|turtle|tortoise|aquarium|terrarium|iguana|pez|peces|tortuga|serpiente)\b", p):
        return "enclosed"
    return "other"


def pet_allowed(room_pets, kind: str | None) -> bool | None:
    """True/False when the room's rule decides, None when unknown (never disqualifies)."""
    if kind in (None, "none"):
        return True
    rule = str(room_pets or "").lower().strip()
    if not rule or "case" in rule or "unconfirmed" in rule:
        return None
    if rule in ("no", "none", "no pets"):
        return False  # a listing marked no pets stays no pets (R-PET-3)
    if kind == "rodent_rabbit":
        return False
    if kind == "enclosed":
        return True
    if kind == "cat":
        return "cat" in rule
    if kind == "dog":
        return "dog" in rule
    return None


# ----------------------------------------------------------------------------- matching

WHOLE_UNIT = re.compile(r"\b(apartment|apt|house|home|condo|studio|townhome|whole|entire|1br|1 bedroom|one bedroom|"
                        r"apartamento|casa)\b", re.I)


def wants_whole_unit(type_wanted) -> bool | None:
    if not type_wanted:
        return None
    t = str(type_wanted).lower()
    if re.search(r"\broom\b|\bcuarto\b|\bhabitaci[oó]n\b|\bsuite\b", t):
        return False
    return bool(WHOLE_UNIT.search(t))


STATED_KEYS = ("areas", "budget", "type", "private_bath", "move_in", "stay_months", "occupants", "pets")


def stated_count(c: dict) -> int:
    return sum(1 for k in STATED_KEYS if c.get(k) not in (None, "", []))


def room_fit(room: dict, c: dict, floor_months: int = 6) -> tuple[bool, int, list[str]]:
    """(fits, score, reasons). Hard gates per §5.4: type, budget more than 15% below rent, occupants over the
    room maximum, a known banned pet, a stay below the lease floor, a stated private bath the room lacks, and a
    stated area the room is neither in nor next to. Unknown values never disqualify."""
    reasons, score = [], 0
    rent = num(room.get("rent")) or 0
    whole = wants_whole_unit(c.get("type"))
    if whole:
        return False, 0, [f"wants a whole unit ({c.get('type')}), this is a {room.get('type')}"]
    if whole is False:
        score += 5
    b = num(c.get("budget"))
    if b is not None and rent:
        if b < rent * 0.85:
            return False, 0, [f"budget ${b:g} is more than 15% below rent ${rent:g}"]
        score += 20 if b >= rent else 8
        reasons.append(f"budget ${b:g} vs rent ${rent:g}")
    occ = c.get("occupants")
    if isinstance(occ, int) and room.get("max_occupants") and occ > room["max_occupants"]:
        return False, 0, [f"{occ} occupants, room max {room['max_occupants']}"]
    ok_pet = pet_allowed(room.get("pets"), pet_kind(c.get("pets")))
    if ok_pet is False:
        return False, 0, [f"pet ({c.get('pets')}) not allowed: {room.get('pets')}"]
    stay = num(c.get("stay_months"))
    if stay is not None and stay < min(int(room.get("lease_min_months") or 12), floor_months):
        return False, 0, [f"wants {stay:g} months, below the {floor_months}-month floor"]
    if c.get("private_bath") is True:
        if room.get("private_bath") is False:
            return False, 0, ["wants a private bath, this room shares one"]
        score += 15
        reasons.append("private bath")
    fit = area_fit(room.get("area", ""), c.get("areas") or [])
    if fit == "no":
        return False, 0, [f"wants {', '.join(c['areas'])}, room is in {room.get('area')}"]
    if fit == "exact":
        score += 20
        reasons.append(f"in {room['area']}")
    elif fit == "adjacent":
        score += 8
        reasons.append(f"{room['area']} is next to {', '.join(c['areas'])}")
    mi = c.get("move_in")
    try:
        d = date.fromisoformat(mi) if mi else None
    except ValueError:
        d = None
    if d and room.get("available_from"):
        gap = (date.fromisoformat(room["available_from"]) - d).days
        if gap <= 0:
            score += 10
            reasons.append(f"free by {mi}")
        elif gap <= 30:
            score += 3
            reasons.append(f"free {gap} days after {mi}")
        else:
            score -= 5
            reasons.append(f"free only from {room['available_from']}")
    return True, score, reasons
