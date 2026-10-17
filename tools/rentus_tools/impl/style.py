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


def lease_terms(text: str) -> list[tuple[str, int | None]]:
    out = []
    for m in SHORT_TERM.finditer(text):
        n = m.group(1) or m.group(2)
        out.append((m.group(0), int(n) if n else 1))
    return out


def style_violations(text: str) -> list[tuple[str, str]]:
    """Return (rule, message) pairs; empty when the text passes."""
    v = []
    n = len(sentences(text))
    if n > 2:
        v.append(("max_two_sentences", f"text has {n} sentences; the limit is 2"))
    q = text.count("?")
    if q > 1:
        v.append(("one_question", f"text asks {q} questions; ask one thing at a time"))
    if LONG_DASH.search(text):
        v.append(("no_long_dashes", "text contains an em/en dash; use a comma or a period"))
    return v
