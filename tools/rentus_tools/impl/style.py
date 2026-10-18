"""Message style rules enforced by send_message."""
from __future__ import annotations

import re

ABBREV = re.compile(r"\b(St|Dr|Ave|Rd|Blvd|Ln|Ct|Mr|Mrs|Ms|Sr|Sra|Jr|No|Apt|approx|vs|etc|Sta|Av)\.", re.IGNORECASE)
DOTTED = re.compile(r"\b(?:[a-zA-Z]\.){2,}")          # a.m., p.m., e.g., i.e., U.S.
URL = re.compile(r"https?://\S+|www\.\S+|\S+@\S+\.\w+")
DECIMAL = re.compile(r"(?<=\d)\.(?=\d)")
LONG_DASH = re.compile(r"[‒–—―]|--")
TERMINATOR = re.compile(r"[.!?…]+[\"')\]]*(?=\s|$)")


def sentences(text: str) -> list[str]:
    t = URL.sub("URL", text)
    t = DOTTED.sub(lambda m: m.group(0).replace(".", ""), t)
    t = ABBREV.sub(lambda m: m.group(1), t)
    t = DECIMAL.sub(",", t)
    out = []
    for line in re.split(r"\n+", t):
        for part in TERMINATOR.split(line):
            if re.search(r"[\w\d]", part):
                out.append(part.strip())
    return out


SHORT_TERM = re.compile(
    r"\bmonth[- ]to[- ]month\b|\bmes a mes\b|\b(\d{1,2})[- ]?(?:month|mes)(?:es|s)?(?:[- ](?:lease|term|contract)|\s+(?:lease|term|contract|contrato))\b"
    r"|\b(?:lease|contract|contrato|term)\s+(?:of|de)\s+(\d{1,2})\s+(?:months|meses)\b", re.IGNORECASE)


_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
          "ten": 10, "eleven": 11, "uno": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7,
          "ocho": 8, "nueve": 9, "diez": 10, "once": 11}
_N = r"(\d{1,2}|" + "|".join(_WORDS) + r")"
# Naming a shortest term without the word "lease": "6 months is the shortest", "the minimum is six months",
# "six-month lease", "contrato de seis meses" (owner decision D23: the floor is revealed only on request).
FLOOR_TERM = re.compile(
    r"\b" + _N + r"[- ]?(?:months?|meses)\s+(?:is|es|would be|ser[ií]a)\s+(?:the |my |our |el |lo )?(?:shortest|minimum|min|m[ií]nimo|m[aá]s corto)"
    r"|\b(?:shortest|minimum|m[ií]nimo|m[aá]s corto)\b[^.?!\n]{0,40}?\b" + _N + r"[- ]?(?:months?|meses)\b"
    r"|\b(" + "|".join(_WORDS) + r")[- ]?(?:month|mes)(?:es|s)?(?:[- ](?:lease|term|contract)|\s+(?:lease|term|contract|contrato))\b"
    r"|\b(?:contrato|lease|term)\s+(?:of|de)\s+(" + "|".join(_WORDS) + r")\s+(?:months|meses)\b", re.IGNORECASE)


def _num(n: str) -> int:
    return int(n) if n.isdigit() else _WORDS[n.lower()]


def lease_terms(text: str) -> list[tuple[str, int | None]]:
    out = []
    for m in SHORT_TERM.finditer(text):
        n = m.group(1) or m.group(2)
        out.append((m.group(0), int(n) if n else 1))
    seen = {p for p, _ in out}
    for m in FLOOR_TERM.finditer(text):
        n = next(g for g in m.groups() if g)
        if m.group(0) not in seen:
            out.append((m.group(0), _num(n)))
    return out


# The owner's canonical two-part lease question is ONE pending item (concierge spec R-STYLE-5, §3.4):
# "How long do you want to stay? Is a one year lease okay with you?" and its Spanish form. Its first "?" does
# not count toward the one-question rule; any other second question still does.
LEASE_PAIR = re.compile(
    r"how long (?:do|would) you (?:want|like|plan|intend) to stay\s*\?\s*"
    r"(?:and\s+)?(?:is|would|will) (?:a )?(?:one|1|12)[- ](?:year|month)s?(?: lease)? (?:be )?(?:okay|ok|fine|good|work)(?: (?:with|for) you)?\s*\?"
    r"|¿?\s*cu[aá]nto tiempo (?:quieres|quiere|deseas|desea|piensas|planeas|te gustar[ií]a) quedarte\s*\?\s*"
    r"¿?\s*(?:te|le) (?:funciona|parece bien|sirve|queda bien|est[aá] bien|va bien) (?:un )?contrato de (?:un|1|12) (?:a[nñ]o|meses)\s*\?",
    re.IGNORECASE)


def question_count(text: str) -> int:
    """Question marks, counting the canonical two-part lease question as one."""
    return text.count("?") - len(LEASE_PAIR.findall(text))


def style_violations(text: str) -> list[tuple[str, str]]:
    """Return (rule, message) pairs; empty when the text passes."""
    v = []
    n = len(sentences(text)) - len(LEASE_PAIR.findall(text))   # the canonical lease pair is one unit
    if n > 2:
        v.append(("max_two_sentences", f"text has {n} sentences; the limit is 2"))
    q = question_count(text)
    if q > 1:
        v.append(("one_question", f"text asks {q} questions; ask one thing at a time"))
    if LONG_DASH.search(text):
        v.append(("no_long_dashes", "text contains an em/en dash; use a comma or a period"))
    return v
