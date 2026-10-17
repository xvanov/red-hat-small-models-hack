"""Scripted counterparts (renters, tenants, vendors). No model, per decision D4.

A counterpart's script is a list of lines:
  {"after": "start", "say": "..."}            sent when the rollout starts (opens the thread)
  {"when_asked": "<item>", "say": "..."}      reply when the operator's last question asks <item>
  {"when_asked": "any", "say": "..."}         reply to any operator message that asks something
                                              no scripted line covers (or to the first message
                                              at all, when it has no question)
Lines are consumed in order, once each. If nothing matches, the counterpart stays silent.

<item> is one of: lease, move_in, phone, reason, occupants, showing, other.
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


def classify_question(text: str) -> str | None:
    """Which qualifying item the operator's message asks for. None if it asks nothing."""
    q = last_question(text)
    if q is None:
        return None
    low = q.lower()
    for item, pat in _PATTERNS:
        if re.search(pat, low):
            return item
    return "other"


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
        self.used: set[int] = set()
        self.replies_sent = 0

    def opening(self) -> list[str]:
        out = []
        for i, line in enumerate(self.script):
            if line.get("after") == "start":
                self.used.add(i)
                out.append(line["say"])
        return out

    def respond(self, operator_text: str) -> tuple[str | None, str | None]:
        """Returns (asked_item, reply_text or None)."""
        item = classify_question(operator_text)
        if item is not None:
            for i, line in enumerate(self.script):
                if i not in self.used and line.get("when_asked") == item:
                    self.used.add(i)
                    self.replies_sent += 1
                    return item, line["say"]
        if item is not None or self.replies_sent == 0:
            for i, line in enumerate(self.script):
                if i not in self.used and line.get("when_asked") == "any":
                    self.used.add(i)
                    self.replies_sent += 1
                    return item, line["say"]
        return item, None
