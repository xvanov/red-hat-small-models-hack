"""Reply guards enforced by send_message (live-demo safety, Oct 17).

1. Booking claims. The operator may only say a showing time is PROPOSED and pending the owner's
   confirmation. Saying it is confirmed, booked, scheduled, set or agreed is allowed only once the
   renter has a calendar event with status "confirmed" (the owner's click).
2. Language consistency. A reply must be in the renter's language: a mostly-English draft on a
   Spanish thread (or the reverse) is sent back for a rewrite.

Both are deterministic regex / word-list checks, no model.
"""
from __future__ import annotations

import re

from .style import sentences

# ----------------------------------------------------------------------------- booking claims

_DAYS = (r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tue|tues|wed|thu|thurs|fri|sat|sun"
         r"|lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo")
# The sentence is about a showing or a time (claims without this context, like "your phone is
# confirmed" or "rent is set at $750", are not booking claims).
SCHEDULE_CONTEXT = re.compile(
    r"\b(?:showing|visit|tour|viewing|appointment|walkthrough|walk-through|meeting|time|slot"
    r"|today|tonight|tomorrow|morning|afternoon|evening|noon|o'?clock|" + _DAYS + r")\b"
    r"|\b\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)|\b\d{1,2}:\d{2}\b"
    r"|\b(?:visita|cita|hora|horario|ma[nñ]ana|tarde|noche|mediod[ií]a|recorrido)\b|\ba las \d",
    re.IGNORECASE)

# Assertions that a time is fixed. English and Spanish.
_EN_STATE = r"(?:confirmed|booked|scheduled|locked in|all set|set up|set|reserved|on the calendar|agreed)"
_ES_STATE = r"(?:confirmad[oa]s?|agendad[oa]s?|reservad[oa]s?|programad[oa]s?|apartad[oa]s?|fijad[oa]s?|acordad[oa]s?)"
CLAIM = re.compile(
    # "the showing is confirmed", "it's booked", "that time has been scheduled", "we're all set"
    r"\b(?:is|are|'s|’s|'re|’re|has been|have been|was|were|got|now)\s+(?:now\s+|all\s+)?" + _EN_STATE + r"\b"
    # "confirmed for Saturday", "booked at 3pm", "scheduled on the 24th"
    r"|\b(?:confirmed|booked|scheduled|locked in|reserved|all set)\s+(?:for|at|on)\b"
    # "I've confirmed / booked / scheduled", "we booked"
    r"|\b(?:i|we)(?:'ve|’ve| have)?\s+(?:just\s+)?(?:confirmed|booked|scheduled|locked in|reserved|set up)\b"
    r"|\bsee you\b|\bit'?s a date\b|\ball set\b"
    # Spanish: "la visita está confirmada", "queda agendada", "ya quedó", "te confirmo la visita",
    # "quedamos el sábado", "nos vemos el lunes", "todo listo"
    r"|\b" + _ES_STATE + r"\b"
    r"|\bte (?:confirmo|agendo|reservo|aparto)\s+(?:la|tu|el)\s+(?:visita|cita|hora|horario|recorrido)\b"
    r"|\bquedamos\b|\bnos vemos\b|\btodo listo\b|\bya qued[oó]\b",
    re.IGNORECASE)

# Claims that stand alone as a whole sentence ("Confirmed!", "Perfecto, agendado.") or name the
# renter as booked ("you're booked") count even without a time in the sentence.
STRONG = re.compile(
    r"^\s*(?:(?:ok(?:ay)?|great|perfect|perfecto|listo|genial|done|super|s[uú]per)[,!\s]+)?"
    r"(?:confirmed|booked|scheduled|confirmad[oa]|agendad[oa]|reservad[oa])\s*$"
    r"|\byou(?:'re|’re| are)\s+(?:now\s+)?(?:booked|confirmed|scheduled)\b"
    r"|\bsee you then\b|\bnos vemos entonces\b",
    re.IGNORECASE)

# The sentence says the time is NOT final yet; then it is the allowed wording.
PENDING = re.compile(
    r"\b(?:pending|propos\w*|tentative\w*|not|isn'?t|aren'?t|won'?t|until|once|awaiting|waiting|unconfirmed"
    r"|(?:will|to|must|has to|needs? to|should)\s+(?:be\s+)?confirm\w*|confirmation"
    r"|pendiente|propuest\w*|propon\w*|tentativ\w*|todav[ií]a no|a[uú]n no|no est[aá]|no ha|hasta que|cuando"
    r"|por confirmar|confirmar[aá]|confirme|confirmaci[oó]n|esperando)\b",
    re.IGNORECASE)


def booking_claims(text: str) -> list[str]:
    """Sentences in `text` that tell the renter a showing/time is fixed. Questions and sentences
    that say the time is pending/proposed are not claims."""
    out = []
    for raw in re.split(r"(?<=[.!?…])\s+|\n+", text):
        s = raw.strip()
        if not s or s.endswith("?") or s.startswith("¿"):
            continue
        body = s.rstrip(".!…")
        if PENDING.search(body):
            continue
        if STRONG.search(body) or (CLAIM.search(body) and SCHEDULE_CONTEXT.search(body)):
            out.append(s)
    return out


def has_confirmed_showing(world, thread: dict) -> bool:
    """True when the thread's renter has a calendar event the owner confirmed."""
    renter_ids = {r["renter_id"] for r in world.register if thread["thread_id"] in r.get("thread_ids", [])}
    if thread.get("renter_id"):
        renter_ids.add(thread["renter_id"])
    return any(ev.get("status") == "confirmed" and ev.get("renter_id") in renter_ids for ev in world.calendar)


# ----------------------------------------------------------------------------- language

# Function words only: names, streets and towns ("Appling Way", "Calle del Sol", "Durham") are not
# in either list, so they never tip the count. Words shared by both languages ("a", "no", "me",
# "he", "son", "come", "sin", "pan", "gratis") are left out.
EN_STOP = frozenset("""
the is are was were be been and or but to of for with from at on in into by this that these those it its
you your yours we our us i i'm i'll i've it's that's there here what when where which who how why
can could would should will do does did have has had not just also very about any some one
hi hello hey thanks thank please yes yeah okay ok great sure let know if so than then
room available still lease month months move phone number showing see time works""".split())
ES_STOP = frozenset("""
el la los las un una unos unas de del al y o pero que en con por para es son está están estoy está esta
este esto eso ese esa lo le les se su sus tu tus te mi mis yo usted ustedes nosotros muy más ya también
hay tiene tengo puede puedo cuando donde cómo como qué cuál quién porque si sí bien hola gracias favor
buenas buenos días claro perfecto cuarto disponible contrato mes meses mudar teléfono número visita hora
nos vemos quedamos todavía aún ahora pronto""".split())


def stopword_counts(text: str) -> tuple[int, int]:
    words = re.findall(r"[a-záéíóúüñ']+", text.lower())
    return sum(w in EN_STOP for w in words), sum(w in ES_STOP for w in words)


def detect_language_strict(text: str, min_hits: int = 3, share: float = 0.75) -> str | None:
    """'en' or 'es' when the text clearly is one language, else None (too short or mixed)."""
    en, es = stopword_counts(text)
    if re.search(r"[¿¡]", text):
        es += 2
    total = en + es
    if total < min_hits:
        return None
    if en / total >= share:
        return "en"
    if es / total >= share:
        return "es"
    return None


def thread_language(thread: dict) -> str | None:
    """The renter's language: their latest message that is clearly one language, else thread.language."""
    for m in reversed(thread.get("messages", [])):
        if m.get("from") == "renter":
            lang = detect_language_strict(m.get("text") or "")
            if lang:
                return lang
    lang = thread.get("language")
    return lang if lang in ("en", "es") else None


def language_mismatch(thread: dict, text: str) -> tuple[str, str] | None:
    """(want, got) when the draft is clearly in the other language, else None."""
    want = thread_language(thread)
    got = detect_language_strict(text)
    if want and got and want != got:
        return want, got
    return None
