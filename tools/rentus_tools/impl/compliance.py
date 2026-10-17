"""Deterministic fair-housing advertising check. Rules and citations: compliance_rules.md (same folder)."""
from __future__ import annotations

import re

# (pattern, rule, severity, suggestion). severity "violation" makes ok=false; "caution" is advisory.
_RULES: list[tuple[str, str, str, str]] = [
    # Familial status: 24 CFR 100.75(c)(1)-(2); HUD 1995 advertising guidance ("adults only", "no children").
    (r"\bno (kids|children|child|infants|babies|toddlers)\b", "familial_status", "violation",
     "remove; state the occupancy limit instead, e.g. 'maximum 2 occupants'"),
    (r"\b(adults?[- ]only|adult (community|household|building))\b", "familial_status", "violation",
     "remove; state the occupancy limit instead"),
    (r"\bno (families|family)\b", "familial_status", "violation", "remove"),
    (r"\b(perfect|ideal|great|best) for (a )?(single|singles|single professionals?|young professionals?|couples?|empty[- ]nesters)\b",
     "familial_status", "violation", "describe the room, not the renter, e.g. 'quiet room with a dedicated workspace'"),
    (r"\b(singles?|couples?|single professionals?) only\b", "familial_status", "violation", "describe the room, not the renter"),
    (r"\bmature (person|persons|adult|adults|couple|tenant|individual)s?\b", "familial_status", "violation", "remove"),
    (r"\b(sin|no) (niños|ninos|niñas|hijos|bebés|bebes)\b", "familial_status", "violation", "remove; state the occupancy limit"),
    (r"\bsolo (adultos|parejas|solteros|profesionales solteros)\b", "familial_status", "violation", "describe the room, not the renter"),
    (r"\bideal para (soltero|soltera|solteros|profesionales solteros|parejas)\b", "familial_status", "violation",
     "describe the room, not the renter"),
    # Religion: 24 CFR 100.75(c)(1); HUD guidance (religious preference; "Christian home").
    (r"\b(christian|catholic|jewish|muslim|mormon|hindu|buddhist) (home|household|house|family|only|tenants?|roommates?|community|environment)\b",
     "religion", "violation", "remove the religious description"),
    (r"\b(christians?|catholics?|jews|muslims|mormons|hindus|buddhists) only\b", "religion", "violation", "remove"),
    (r"\bno (christians?|catholics?|jews|muslims|mormons|hindus|buddhists|atheists)\b", "religion", "violation", "remove"),
    (r"\b(god[- ]fearing|church[- ]going|believers? only)\b", "religion", "violation", "remove"),
    (r"\b(hogar|casa|familia) cristian[ao]s?\b|\bsolo cristian[ao]s\b", "religion", "violation", "remove"),
    # Race, color, national origin: 24 CFR 100.75(c)(1), (c)(3); HUD guidance (racial/ethnic descriptors, "exclusive").
    (r"\b(white|black|asian|hispanic|latino|caucasian|african[- ]american|mexican|indian|chinese|arab)s?( people| tenants?| roommates?| applicants?| persons?)? only\b",
     "race_color_national_origin", "violation", "remove"),
    (r"\bno (whites?|blacks?|asians?|hispanics?|latinos?|mexicans?|indians?|immigrants?|foreigners?|arabs?)\b",
     "race_color_national_origin", "violation", "remove"),
    (r"\b(must|has to|should) speak english\b|\benglish (speakers?|speaking) only\b|\bamericans? only\b|\bus citizens? only\b",
     "race_color_national_origin", "violation", "remove; communicate in the renter's language instead"),
    (r"\bexclusive (neighborhood|community|area)\b|\bwhite neighborhood\b|\bethnic neighborhood\b",
     "race_color_national_origin", "caution", "describe amenities and location facts, not the neighbors"),
    # Handicap: 24 CFR 100.75(c)(1); HUD guidance (descriptions of renters' abilities; assistance animals).
    (r"\b(no|not suitable for) (wheelchairs?|handicapped|disabled|disabilities)\b|\bable[- ]bodied\b",
     "handicap", "violation", "describe the property instead, e.g. 'second-floor room, stairs only'"),
    (r"\b(must|has to) be able to (climb|walk|use) stairs\b|\bno mental(ly)? (illness|ill)\b|\bhealthy (tenants?|persons?) only\b",
     "handicap", "violation", "describe the property instead, e.g. 'second-floor walk-up'"),
    (r"\bno (service|assistance|emotional support|support) animals?\b|\bno esas?\b",
     "handicap", "violation", "say 'no pets; assistance animals welcome' instead"),
    # Sex: 24 CFR 100.75(c)(1). Shared-living sex preference is permitted by HUD guidance, so caution only.
    (r"\b(female|male|women|men|girls?|guys?|ladies)( only| roommates? only| tenants? only)\b|\bsolo (mujeres|hombres|chicas|chicos)\b",
     "sex", "caution", "allowed only for shared living space; otherwise remove"),
    (r"\bno (gays?|lesbians?|lgbt\w*|trans\w*)\b|\bstraight only\b", "sex", "violation", "remove"),
    # Source of income: not covered by 24 CFR 100.75; some localities protect it. Severity set by policy.
    (r"\bno (section ?8|sección ?8|vouchers?|housing (choice )?vouchers?|housing assistance|hcv)\b",
     "source_of_income", "caution", "remove; voucher holders are protected in some jurisdictions"),
]

COMPILED = [(re.compile(p, re.IGNORECASE), rule, sev, sug) for p, rule, sev, sug in _RULES]

CITATIONS = {
    "familial_status": "24 CFR 100.75(c)(1)-(2); 42 U.S.C. 3604(c)",
    "religion": "24 CFR 100.75(c)(1); 42 U.S.C. 3604(c)",
    "race_color_national_origin": "24 CFR 100.75(c)(1),(c)(3); 42 U.S.C. 3604(c)",
    "handicap": "24 CFR 100.75(c)(1); 42 U.S.C. 3604(c)",
    "sex": "24 CFR 100.75(c)(1); HUD 1995 advertising guidance (shared living)",
    "source_of_income": "local ordinance (not in 24 CFR 100.75)",
}


def check(text: str, policy: dict | None = None) -> dict:
    soi_protected = bool((policy or {}).get("source_of_income_protected"))
    findings = []
    for rx, rule, sev, sug in COMPILED:
        for m in rx.finditer(text or ""):
            s = sev
            if rule == "source_of_income" and soi_protected:
                s = "violation"
            findings.append({"phrase": m.group(0), "rule": rule, "severity": s, "citation": CITATIONS[rule],
                             "suggestion": sug, "start": m.start()})
    findings.sort(key=lambda f: f["start"])
    for f in findings:
        del f["start"]
    return {"ok": not any(f["severity"] == "violation" for f in findings), "findings": findings}
