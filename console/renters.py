"""Scripted counterparts (contract section 7): no model, just script matching.

A counterpart's script is a list of steps:
  {"after": "start", "say": "..."}           fires when the run starts
  {"when_asked": "move_in", "say": "..."}    fires when the operator's last message asks for that item
Steps are consumed in order per key, so a repeated `when_asked` gives the next answer
(for example a vague date first, then the exact date when asked again).
"""
from __future__ import annotations

import re

# What the operator is asking about, from its last message. English + Spanish.
ASK_PATTERNS: dict[str, re.Pattern] = {
    "lease": re.compile(r"\blease\b|12[- ]month|one[- ]year|\bcontrato\b|\baño\b|12 meses", re.I),
    "move_in": re.compile(r"move in|move-in|moving|exact (day|date)|which (day|date)|mudar|mudanza|qué (día|fecha)|fecha", re.I),
    "occupants": re.compile(r"how many|people|who (will|would) (live|be)|occupants|cuántas personas|personas", re.I),
    "phone": re.compile(r"phone|number to reach|teléfono|número", re.I),
    "reason": re.compile(r"what brings|reason|prompting|why are you|qué te trae|motivo|por qué", re.I),
    "showing": re.compile(r"show(ing)? the room|does that work|te funciona|visita|mostrar", re.I),
}


def asked_items(text: str) -> list[str]:
    return [k for k, p in ASK_PATTERNS.items() if p.search(text or "")]


class Counterpart:
    def __init__(self, spec: dict):
        self.id: str = spec.get("id", "renter:anon")
        self.name: str = spec.get("name") or self.id.split(":", 1)[-1].capitalize()
        self.channel: str = spec.get("channel", "marketplace")
        self.language: str = spec.get("language", "en")
        self.script: list[dict] = list(spec.get("script", []))
        self.used: set[int] = set()
        self.thread_id: str | None = None

    def opening(self) -> list[str]:
        out = []
        for i, step in enumerate(self.script):
            if step.get("after") == "start" and i not in self.used:
                self.used.add(i)
                out.append(step.get("say", ""))
        return out

    def reply_to(self, operator_text: str) -> str | None:
        """Next scripted line answering what the operator asked, or None."""
        for item in asked_items(operator_text):
            for i, step in enumerate(self.script):
                if i in self.used:
                    continue
                if step.get("when_asked") == item:
                    self.used.add(i)
                    return step.get("say")
        return None


# Synthetic renters, written here (no real people). classifier v2 + reusable confirmations keep a scripted
# renter from going silent when the operator rephrases (docs/task-v2-changes.md).
MARIA = {"id": "renter:maria", "name": "María", "channel": "marketplace", "language": "es", "classifier": "v2",
         "script": [
             {"after": "start", "say": "Hola, empiezo un trabajo nuevo en Duke. ¿Sigue disponible el cuarto con baño privado?"},
             {"when_asked": "lease", "say": "Sí, un año está bien."},
             {"when_asked": "move_in", "say": "a principios de noviembre"},
             {"when_asked": "move_in", "say": "El 1 de noviembre."},
             {"when_asked": "move_in", "say": "Sí, el 1 de noviembre.", "reuse": True},
             {"when_asked": "phone", "say": "919 555 0142"},
             {"when_asked": "reason", "say": "Empiezo un trabajo nuevo en Duke."},
             {"when_asked": "reason", "say": "Por el trabajo nuevo en Duke.", "reuse": True},
             {"when_asked": "occupants", "say": "Solo yo."},
             {"when_asked": "showing", "say": "Sí, perfecto, gracias.", "reuse": True},
         ]}
DEVON = {"id": "renter:devon", "name": "Devon", "channel": "roomies", "language": "en", "classifier": "v2",
         "script": [
             {"after": "start", "say": "Hey, is the private bath room still open? It would be just me. Is the rent negotiable at all?"},
             {"when_asked": "lease", "say": "Yeah, a year works for me."},
             {"when_asked": "move_in", "say": "November 1st."},
             {"when_asked": "move_in", "say": "Yes, November 1st.", "reuse": True},
             {"when_asked": "phone", "say": "(919) 555-0187"},
             {"when_asked": "reason", "say": "My current lease is ending."},
             {"when_asked": "occupants", "say": "Just me."},
             {"when_asked": "occupants", "say": "Just me, one person.", "reuse": True},
             {"when_asked": "showing", "say": "Works for me, thanks.", "reuse": True},
         ]}
SAM = {"id": "renter:sam", "name": "Sam", "channel": "craigslist", "language": "en", "classifier": "v2",
       "script": [
           {"after": "start", "say": "Is this available? I only need it for 3 months."},
           {"when_asked": "lease", "say": "No, I can't do a full year, sorry."},
       ]}

# Free play (no gym scenario): these write in once a listing is live. Synthetic, no real people.
DEFAULT_COUNTERPARTS: list[dict] = [MARIA, DEVON, SAM]
