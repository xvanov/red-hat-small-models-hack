"""Live-channel delivery shaping: the operator's several send_message calls in one turn become ONE reply.

The evaluated operator (frozen) sends short messages one by one (the Gym's style rules: one fact per message). On
a real phone that reads as a burst of 5 texts. Here, per turn:
  - sentences are pooled in order; exact and near-duplicate sentences are dropped;
  - only the LAST question is kept (repeated / earlier questions are dropped), and it goes at the end;
  - the sentence that answers the renter's question (rent, availability, pets, ...) is moved first;
  - the result is split per channel: SMS one message <= 320 chars (two if longer), Messenger at most two,
    email one.
"""
from __future__ import annotations

import difflib
import re

SMS_MAX = 320
MSGR_MAX = 600

# renter question keyword -> words that mark the answering sentence
TOPICS = [
    (r"\b(rent|price|cost|how much|\$|per month|monthly)\b", r"\$\s?\d|\brent\b"),
    (r"\b(deposit)\b", r"\bdeposit\b"),
    (r"\b(available|availability|move in|move-in|earlier|when can|start date|still open)\b",
     r"\bavailable\b|\bmove[- ]in\b|\bfrom (january|february|march|april|may|june|july|august|september|october|"
     r"november|december)\b"),
    (r"\b(pet|pets|dog|cat)\b", r"\bpets?\b|\bdogs?\b|\bcats?\b"),
    (r"\b(lease|how long|month to month|short term)\b", r"\blease\b"),
    (r"\b(utilities|internet|wifi|electric)\b", r"\butilities\b|\binternet\b|\bwi-?fi\b"),
    (r"\b(where|address|location|located|area)\b", r"\b(way|street|road|durham|raleigh|chapel hill)\b"),
    (r"\b(bath|bathroom)\b", r"\bbath(room)?\b"),
    (r"\b(parking|park)\b", r"\bpark(ing)?\b"),
]

_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9¿¡\"'(])")


def sentences(text: str) -> list[str]:
    out = []
    for line in (text or "").splitlines():
        out += [s.strip() for s in _SPLIT.split(line.strip()) if s.strip()]
    return out


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9$ ]", "", s.lower()).strip()


def _near_dup(a: str, b: str) -> bool:
    na, nb = _norm(a), _norm(b)
    if na == nb:
        return True
    if re.findall(r"\d+", na) != re.findall(r"\d+", nb):  # different numbers ($750 vs $850) are different facts
        return False
    return difflib.SequenceMatcher(None, na, nb).ratio() >= 0.88


def merge(texts: list[str], renter_text: str = "") -> list[str]:
    """Pooled, de-duplicated sentences: statements (answer first), then the last question."""
    pool: list[str] = []
    for t in texts:
        for s in sentences(t):
            if not any(_near_dup(s, k) for k in pool):
                pool.append(s)
    questions = [s for s in pool if s.rstrip().endswith("?")]
    statements = [s for s in pool if not s.rstrip().endswith("?")]
    rq = (renter_text or "").lower()
    for ask, ans in TOPICS:
        if re.search(ask, rq):
            hit = next((s for s in statements if re.search(ans, s, re.I)), None)
            if hit:
                statements.remove(hit)
                statements.insert(0, hit)
            break
    return statements + questions[-1:]


def _pack(sents: list[str], limit: int, max_parts: int) -> list[str]:
    whole = " ".join(sents)
    if len(whole) <= limit or max_parts == 1 or len(sents) < 2:
        return [whole] if whole else []
    # two parts, split at the sentence boundary closest to the middle
    best, best_d = 1, None
    for i in range(1, len(sents)):
        d = abs(len(" ".join(sents[:i])) - len(" ".join(sents[i:])))
        if best_d is None or d < best_d:
            best, best_d = i, d
    return [" ".join(sents[:best]), " ".join(sents[best:])]


def compose(texts: list[str], channel: str, renter_text: str = "") -> list[str]:
    sents = merge(texts, renter_text)
    if not sents:
        return []
    if channel == "email":
        return ["\n\n".join([" ".join(sents[:-1]), sents[-1]]).strip() if len(sents) > 1 else sents[0]]
    if channel == "sms":
        return _pack(sents, SMS_MAX, 2)
    return _pack(sents, MSGR_MAX, 2)


LIVE_NOTE = """## Live channel (real renter, real phone)
- Answer the renter's actual question first, in the first sentence (for example the rent amount if they asked about rent). Then ask exactly one qualifying question that has not been answered yet. Never repeat a question in the same reply.
- Your send_message calls in this turn are combined into ONE reply to the renter, so do not repeat facts or questions across them.
- Before replying to anything the renter states, record it: `read_reply` on their message, then `upsert_renter` with every answered gate item (lease, move_in, phone, reason, occupants) and `capture_demand` with new criteria."""
