"""Scripted counterparts (renters, tenants, vendors). No model, per decision D4.

A counterpart's script is a list of lines:
  {"after": "start", "say": "..."}            sent when the rollout starts (opens the thread)
  {"when_asked": "<item>", "say": "..."}      reply when the operator's last question asks <item>
  {"when_asked": "any", "say": "..."}         reply to any operator message that asks something
                                              no scripted line covers (or to the first message
                                              at all, when it has no question)
  {"when_asked": "next", "at_reply": j, "say": "..."}
                                              Amendment 1 (v3): a line carrying a non-gate behaviour
                                              (hard no, not now, price push, question). It answers the
                                              next operator message WHATEVER it asks, once every earlier
                                              one-shot line is used, and at the latest on the j-th
                                              operator message to this counterpart.
Lines are consumed in order, once each. If nothing matches, the counterpart stays silent.

<item> is one of: lease, move_in, phone, reason, occupants, showing, other.

Task set v2 additions (all opt-in, so v1 tasks replay exactly as before):
  "when_asked" may be a list of items ("other" or "move_in" for a not-now timeframe).
  {"...", "reuse": true}     a line that is never consumed. Reusable lines are tried only after every
                             unused one-shot line for the same item, so they act as fallbacks: a
                             confirmation of an answer already given ("yes, Nov 1 is my date"), or a
                             generic "what else do you need?" for a question no line covers. A reusable
                             "any" line answers only a message that asks something.
  spec "classifier": "v2"    a question the v1 rules call "other" but that is about the room's
                             availability or a different date ("it's available from Jan 1, would that
                             work?") counts as a move_in question, and one naming a lease length in
                             months ("would 6 months work for you?") counts as a lease question.
"""
from __future__ import annotations

import re

ITEMS = ("lease", "move_in", "phone", "reason", "occupants", "showing", "other")

# Order matters: the first item whose pattern hits the question wins.
_PATTERNS = [
    ("occupants", r"how many (people|persons|of you|occupants|adults)|anyone (else )?(moving|living|staying)|"
                  r"just you|by yourself|alone|occupants|who (will|would) (be )?(living|moving)|"
                  r"cu[aá]ntas personas|cu[aá]ntos (ser[aá]n|vivir[aá]n)|vivir[aá]s? sol[oa]|personas"),
    ("phone", r"phone|number (to|where|so)|best number|reach you|text you|call you|"
              r"tel[eé]fono|n[uú]mero|celular|contactarte|llamarte"),
    ("lease", r"lease|how long|one year|1 year|12 months|a year|stay (for|long)|"
              r"contrato|un a[nñ]o|cu[aá]nto tiempo|plazo"),
    ("reason", r"\bwhy\b|reason|what brings|what'?s (bringing|prompting)|moving (here|to)|"
               r"motivo|por qu[eé]|raz[oó]n|qu[eé] te trae"),
    ("move_in", r"move[- ]?in|moving in|when (do|would|are|can) you (want|like|plan|need|looking)|"
                r"start date|what date|exact date|when.*move|"
                r"mudar|mudanza|fecha|cu[aá]ndo"),
    ("showing", r"showing|see the room|tour|visit|come (by|see)|time works|which time|"
                r"visita|ver el cuarto|ver la habitaci[oó]n"),
]


# v2 only: an "other" question about availability / a different date is a move_in question.
_AVAIL_V2 = re.compile(r"availab|earliest|instead|later date|different date|that date|this date|work for you|"
                       r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.? \d{1,2}\b|\b\d{1,2}/\d{1,2}\b|"
                       r"disponible|en su lugar|en vez|esa fecha|otra fecha|te funciona|"
                       r"\b(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\b")


# v2 only: an "other" question naming a lease length in months is a lease question.
_TERM_V2 = re.compile(r"\b(\d{1,2}|six|nine|seis|nueve)[- ]?(months?|meses)\b")


def last_question(text: str) -> str | None:
    """The last sentence of `text` that ends with '?', or None."""
    if not text or "?" not in text:
        return None
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    qs = [p for p in parts if p.rstrip().endswith("?")]
    if not qs:
        return text[: text.rfind("?") + 1]
    q = qs[-1]
    return q[q.find("¿"):] if "¿" in q else q


def classify_question(text: str, version: str = "v1") -> str | None:
    """Which qualifying item the operator's message asks for. None if it asks nothing."""
    q = last_question(text)
    if q is None:
        return None
    low = q.lower()
    for item, pat in _PATTERNS:
        if re.search(pat, low):
            return item
    if version == "v2" and _TERM_V2.search(low):  # "would 6 months work for you?" is about the lease (D23)
        return "lease"
    if version == "v2" and _AVAIL_V2.search(low):
        return "move_in"
    return "other"


def _asks(line: dict, item: str) -> bool:
    w = line.get("when_asked")
    return item in w if isinstance(w, list) else w == item


class Counterpart:
    def __init__(self, spec: dict):
        self.id = spec["id"]
        self.channel = spec.get("channel", "marketplace")
        self.language = spec.get("language", "en")
        self.name = spec.get("name") or self.id.split(":", 1)[-1].replace("_", " ").title()
        self.thread_id = spec.get("thread_id") or "t_" + self.id.split(":", 1)[-1]
        self.script = list(spec.get("script", []))
        self.room_id = spec.get("room_of_interest")
        self.listing_id = spec.get("listing_id")
        self.classifier = spec.get("classifier", "v1")
        self.used: set[int] = set()
        self.replies_sent = 0
        self.operator_msgs = 0

    def opening(self) -> list[str]:
        out = []
        for i, line in enumerate(self.script):
            if line.get("after") == "start":
                self.used.add(i)
                out.append(line["say"])
        return out

    def respond(self, operator_text: str) -> tuple[str | None, str | None]:
        """Returns (asked_item, reply_text or None)."""
        item = classify_question(operator_text, self.classifier)
        self.operator_msgs += 1
        nxt = self._due_next()
        if nxt is not None:
            self.used.add(nxt)
            self.replies_sent += 1
            return item, self.script[nxt]["say"]
        if item is not None:
            hit = self._take(item, reuse=False) or self._take(item, reuse=True)
            if hit is not None:
                return item, hit
        if item is not None or self.replies_sent == 0:
            hit = self._take("any", reuse=False)
            if hit is not None:
                return item, hit
        if item is not None:
            hit = self._take("any", reuse=True)
            if hit is not None:
                return item, hit
        return item, None

    def _due_next(self) -> int | None:
        """Index of a "next" line that is due now, else None."""
        for i, line in enumerate(self.script):
            if line.get("when_asked") != "next" or i in self.used:
                continue
            earlier = [k for k, l in enumerate(self.script[:i])
                       if not l.get("reuse") and l.get("after") != "start" and k not in self.used]
            if not earlier or self.operator_msgs >= int(line.get("at_reply") or 10 ** 6):
                return i
            return None
        return None

    def _take(self, item: str, reuse: bool) -> str | None:
        for i, line in enumerate(self.script):
            if bool(line.get("reuse")) != reuse or not _asks(line, item):
                continue
            if not reuse and i in self.used:
                continue
            if not reuse:
                self.used.add(i)
            self.replies_sent += 1
            return line["say"]
        return None
