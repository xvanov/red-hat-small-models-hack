"""Concierge send guards (docs/spec/concierge.md R-VOICE-1, R-STYLE-7).

1. First person. Messages go out as the owner, so a prospect-facing message never talks about the
   owner in the third person: "the owner", "my landlord will", "the property manager", the owner's
   name, "el dueño", "la propietaria". "I'm the owner" / "soy el dueño" is first person and passes.
2. No house number in public text. Listings, posts and prospect messages give the street name only;
   the full address goes to a prospect privately once their showing is confirmed.

Deterministic regex checks, no model.
"""
from __future__ import annotations

import re

# ----------------------------------------------------------------------------- first person

_SELF = r"(?<!\bi'm )(?<!\bi’m )(?<!\bi am )(?<!\bas )(?<!\bsoy )(?<!\bcomo )"
THIRD_PERSON = re.compile(
    _SELF + r"\b(?:the|my|our)\s+(?:owner|landlord|landlady|homeowner|property\s+manager|manager|boss|"
    r"leasing\s+(?:agent|office|manager)|host)s?(?:'s|’s)?\b"
    r"|" + _SELF + r"\b(?:el|al|del|la|mi|nuestro|nuestra)\s+(?:due[nñ][oa]|propietari[oa]|caser[oa]|arrendador[a]?|"
    r"administrador[a]?|jef[ea]|encargad[oa])\b",
    re.IGNORECASE)

DEFAULT_OWNER_NAMES = ("Kalin",)

# A few common slips with the first-person wording to use instead.
_REWRITES = [
    (re.compile(r"pending (?:the|my) (?:owner|landlord|manager)(?:'s|’s)? confirmation", re.I),
     "pending my confirmation / I'll confirm it shortly"),
    (re.compile(r"(?:the|my) (?:owner|landlord|manager) will (\w+)", re.I), r"I will \1"),
    (re.compile(r"check with (?:the|my) (?:owner|landlord|manager)", re.I), "let me check on that"),
    (re.compile(r"(?:el|la) due[nñ][oa] (?:te )?(\w+)", re.I), r"yo te \1"),
]


def third_person_refs(text: str, owner_names=DEFAULT_OWNER_NAMES) -> list[str]:
    """Phrases in `text` that refer to the owner in the third person."""
    hits = [m.group(0) for m in THIRD_PERSON.finditer(text)]
    for name in owner_names or ():
        if name and re.search(rf"\b{re.escape(name)}\b", text, re.IGNORECASE):
            hits.append(name)
    return hits


def first_person_hint(text: str) -> str:
    for pat, repl in _REWRITES:
        m = pat.search(text)
        if m:
            return (f"you ARE the owner: rewrite in first person ('I', 'me', 'my'); e.g. "
                    f"'{m.group(0)}' -> '{m.expand(repl)}'")
    return ("you ARE the owner: rewrite in first person ('I', 'me', 'my'), e.g. 'I'll confirm it shortly' "
            "instead of 'pending the owner's confirmation' ('te lo confirmo en breve' instead of 'el dueño confirmará')")


def owner_names(world) -> tuple[str, ...]:
    names = (getattr(world, "policy", None) or {}).get("owner_names")
    if isinstance(names, str):
        names = [names]
    return tuple(names) if names else DEFAULT_OWNER_NAMES


# ----------------------------------------------------------------------------- house numbers

_SUFFIX = (r"(?:St|Street|Rd|Road|Ave|Avenue|Way|Dr|Drive|Ln|Lane|Ct|Court|Blvd|Boulevard|Pl|Place|Cir|Circle|"
           r"Pkwy|Parkway|Ter|Terrace|Trl|Trail|Hwy|Loop|Run|Gate\s+Ln)")
# "1316 Marrowstone St", "4110 Odessa Gate Ln", "307 ambergate rd"
GENERIC_ADDRESS = re.compile(r"(?<![\d$.,])\b\d{1,6}\s+(?:[A-Za-z][\w'’]*\s+){1,3}" + _SUFFIX + r"\b\.?",
                             re.IGNORECASE)


def split_address(address: str) -> tuple[str | None, str]:
    """('1316', 'Marrowstone St') from '1316 Marrowstone St, Durham, NC 27707 (fictional)'."""
    first = (address or "").split(",")[0].strip()
    m = re.match(r"^(\d+[A-Za-z]?)\s+(.+)$", first)
    if not m:
        return None, first
    return m.group(1), m.group(2).strip()


def public_street(address: str) -> str:
    """The street name only (no house number), e.g. 'Marrowstone St'."""
    return split_address(address)[1]


def house_numbers(text: str, rooms=()) -> list[str]:
    """Address-with-house-number phrases in `text`: any '<number> <Name> <St/Rd/...>' plus, for the given
    rooms, their own house number next to their street's first word."""
    hits = [m.group(0).strip() for m in GENERIC_ADDRESS.finditer(text or "")]
    for r in rooms or ():
        num, street = split_address(str(r.get("address") or ""))
        if not num or not street:
            continue
        word = re.escape(street.split()[0])
        m = re.search(rf"(?<![\d$]){re.escape(num)}\s*,?\s+{word}\b", text or "", re.IGNORECASE)
        if m and not any(m.group(0) in h or h in m.group(0) for h in hits):
            hits.append(m.group(0))
    return hits
