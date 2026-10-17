"""read_reply: renter message -> reader JSON (data/reader_schema.md).

Two backends:
- HTTP: when READER_BASE_URL is set, POST an OpenAI-compatible chat completion to
  $READER_BASE_URL/chat/completions with model $READER_MODEL (default "rentus-reader"), using the
  shared prompt in reader/prompt.py when importable. Bad or missing JSON falls back.
- Deterministic fallback: `read_reply_fallback()`, regex rules in English and Spanish.

The result carries `backend` ("model" | "fallback") next to the schema fields.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from datetime import date, timedelta

from ..core import tool
from ..errors import ToolError
from ..world import find_repo_root
from ._util import PHONE_RE, need

FIELDS = ("lease", "move_in", "phone", "occupants", "reason")
INTENTS = ("price_negotiation", "scheduling", "small_talk", "not_now", "hard_no", "shorter_lease", "question")
STATUSES = ("answered", "vague", "no", "exception", "absent")


def _rx(*parts: str) -> re.Pattern:
    return re.compile("|".join(f"(?:{p})" for p in parts), re.IGNORECASE)


# ---------------------------------------------------------------------------- language

ES_WORDS = {"hola", "buenas", "buenos", "días", "dias", "gracias", "cuarto", "quiero", "puedo", "somos", "mudo", "mudarme",
            "mudaría", "mudar", "mudanza", "año", "meses", "contrato", "soy", "mi", "yo", "también", "tambien", "por", "para",
            "está", "esta", "el", "la", "los", "las", "de", "que", "con", "sí", "si", "pero", "necesito", "trabajo", "nuevo",
            "número", "numero", "teléfono", "telefono", "celular", "saludos", "muchas", "esposa", "esposo", "novio", "novia",
            "verlo", "ver", "cuándo", "cuando", "porque", "fecha", "todavía", "todavia", "solo", "una", "persona", "tiempo",
            "depende", "pronto", "semana", "semanas", "mes", "viene", "fines", "renta", "precio", "hay", "incluye", "amueblado",
            "estacionamiento", "depósito", "deposito", "lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo",
            "noviembre", "diciembre", "octubre", "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
            "septiembre", "perfecto", "claro", "entendido", "amable", "jaja", "favor", "escriba", "encontré", "lugar", "lejos",
            "ahorita", "téngame", "vuelvo", "buscar", "prefiero", "decir", "dar", "aquí", "aqui", "mando", "después", "empieza",
            "estudiar", "busco", "termina", "subieron", "desde", "estoy", "libre", "qué", "horarios", "tiene", "llevar", "gato",
            "qué", "bien", "mil", "fin", "buen", "mucho", "bajar", "poco", "deja", "descuento", "pago", "adelantado", "negociar",
            "lista", "listo", "esté", "gustaría", "sería", "ser", "podría", "tal", "vez", "amigo", "hija", "hijo", "suegra", "mamá"}
EN_WORDS = {"the", "and", "is", "i", "me", "my", "you", "to", "a", "it", "for", "of", "in", "on", "can", "would", "with",
            "just", "thanks", "thank", "hi", "hey", "hello", "move", "moving", "year", "lease", "room", "this", "that", "be",
            "are", "what", "when", "how", "at", "we", "our", "your", "number", "phone", "please", "good", "morning", "only",
            "here", "there", "want", "need", "like", "do", "not", "yes", "ok", "okay", "see", "place", "work", "job", "new"}


def detect_language(text: str) -> str:
    t = text.lower()
    if re.search(r"[¿¡ñ]", t):
        return "es"
    words = re.findall(r"[a-záéíóúüñ]+", t)
    es = sum(w in ES_WORDS for w in words) + 2 * len(re.findall(r"[áéíóú]", t))
    en = sum(w in EN_WORDS for w in words)
    # ambiguous short tokens shared by both languages
    if es > en:
        return "es"
    return "en"


# ---------------------------------------------------------------------------- dates

MONTHS = {"jan": 1, "january": 1, "enero": 1, "feb": 2, "february": 2, "febrero": 2, "mar": 3, "march": 3, "marzo": 3,
          "apr": 4, "april": 4, "abril": 4, "may": 5, "mayo": 5, "jun": 6, "june": 6, "junio": 6, "jul": 7, "july": 7,
          "julio": 7, "aug": 8, "august": 8, "agosto": 8, "sep": 9, "sept": 9, "september": 9, "septiembre": 9,
          "setiembre": 9, "oct": 10, "october": 10, "octubre": 10, "nov": 11, "november": 11, "noviembre": 11,
          "dec": 12, "december": 12, "diciembre": 12}
WEEKDAYS = {"monday": 0, "mon": 0, "lunes": 0, "tuesday": 1, "tues": 1, "martes": 1, "wednesday": 2, "miércoles": 2,
            "miercoles": 2, "thursday": 3, "thurs": 3, "jueves": 3, "friday": 4, "viernes": 4, "saturday": 5, "sábado": 5,
            "sabado": 5, "sunday": 6, "domingo": 6}
MON = "|".join(sorted(MONTHS, key=len, reverse=True))
WD = "|".join(sorted(WEEKDAYS, key=len, reverse=True))
ORD = r"(\d{1,2})(?:st|nd|rd|th|ro|º)?"

DATE_PATTERNS = [
    ("iso", re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")),
    ("numeric", re.compile(r"(?<![\d/])(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?(?![\d/])")),
    ("month_day", re.compile(rf"\b(?:on\s+)?({MON})\.?\s+{ORD}\b(?!\s*(?:am|pm|:))", re.I)),
    ("day_of_month", re.compile(rf"\b(?:on\s+)?(?:the\s+)?{ORD}\s+of\s+({MON})\b", re.I)),
    ("es_day_month", re.compile(rf"\b(?:el\s+)?(\d{{1,2}}|primero)\s+de\s+({MON})\b", re.I)),
    ("this_weekday", re.compile(rf"\b(?:this|next|este|esta|el próximo|el proximo|próximo|proximo)\s+({WD})\b", re.I)),
    ("relative", re.compile(r"\b(tomorrow|today|tonight|mañana mismo|pasado mañana|hoy)\b|(?<!la )(?<!en la )(?<!por la )\bmañana\b(?! (?:en|por) la)", re.I)),
    ("bare_day", re.compile(r"\b(?:on\s+)?the\s+(\d{1,2})(?:st|nd|rd|th)\b|\bel (primero)\b(?!\s+de)|\bel\s+(\d{1,2})(?!\s*(?:de|/|:|\d|personas|meses|años|días|%))\b", re.I)),
]

VAGUE_DATE = _rx(
    r"\b(?:beginning|start|end|middle) of (?:next|the|this) month\b", r"\bnext month\b", r"\bel mes que viene\b",
    r"\bel próximo mes\b|\bel proximo mes\b", r"\bas soon as possible\b", r"\basap\b", r"\blo antes posible\b",
    r"\bcuanto antes\b", r"\b(?:soon|pronto)\b(?! cambio)",
    r"\baround (?:the )?\d{1,2}(?:st|nd|rd|th)?\b", r"\balrededor del \d{1,2}\b", r"\baround (?:" + MON + r")\b",
    r"\b(?:early|mid|late|end of|beginning of)[- ](?:" + MON + r")\b", r"\ba (?:principios|mediados|fines|finales) de (?:" + MON + r"|mes)\b",
    r"\b(?:a )?fines de mes\b|\ba finales de mes\b", r"\bend of the month\b|\bend of month\b",
    r"\bin the next (?:couple|few) (?:of )?weeks\b|\bin a (?:few|couple) (?:of )?weeks\b|\ben unas semanas\b|\ben un par de semanas\b",
    r"\bcuando esté listo\b|\bcuando este listo\b|\bwhenever it'?s ready\b",
    r"\b(?:in|en|by|para)\s+(?:" + MON + r")\b(?!\.?\s*\d)",
)
MOVE_NO = _rx(r"don'?t have a move[- ]in date", r"todavía no tengo fecha|todavia no tengo fecha", r"no sé cuándo me mudo|no se cuando me mudo",
              r"not sure when i'?m moving", r"rather not say when", r"prefiero no decir cuándo|prefiero no decir cuando",
              r"no tengo fecha", r"don'?t know when i'?ll move")
MOVE_COND = _rx(r"unless my (?:current )?lease", r"a menos que me extiendan", r"si el cuarto está listo|si el cuarto esta listo",
                r"if the room is ready", r"depends on my closing", r"hopefully,? depends", r"could slip a week",
                r"podría ser una semana después|podria ser una semana despues", r"if my job start moves", r"unless .* extended",
                r"depende de mi cierre", r"si todo sale bien")
VISIT_CTX = _rx(r"\bsee (?:it|the|you|them|that)\b|\b(?:view|tour|visit|look at|take a look|showing|viewing|appointment|schedule|come by|stop by|ver(?:lo|la)?|visita|visitar|cita|agendar)\b")
MOVE_CTX = _rx(r"\bmov(?:e|es|ing)\b|\bmove[- ]in\b|\bmud(?:o|ar|arme|aría|aria|anza)\b|\bcome in\b|\bstart\b|\bneed (?:a|the) (?:place|room)\b",
               r"\bnecesito el cuarto\b|\blista para\b|\bby\b|\bplanning\b|\bentrar\b")


def _next_on_or_after(today: date, month: int, day: int) -> date | None:
    for y in (today.year, today.year + 1):
        try:
            d = date(y, month, day)
        except ValueError:
            continue
        if d >= today:
            return d
    return None


def _next_day_of_month(today: date, day: int) -> date | None:
    y, m = today.year, today.month
    for _ in range(3):
        try:
            d = date(y, m, day)
            if d >= today:
                return d
        except ValueError:
            pass
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return None


def find_dates(text: str, today: date) -> list[dict]:
    """All date expressions: {start, end, raw, date|None, ambiguous}."""
    found: list[dict] = []
    taken: list[tuple[int, int]] = []

    def add(m, d, ambiguous=False, kind=""):
        s, e = m.span()
        if any(not (e <= a or s >= b) for a, b in taken):
            return
        taken.append((s, e))
        found.append({"start": s, "end": e, "raw": m.group(0).strip(), "date": d.isoformat() if d else None,
                      "ambiguous": ambiguous, "kind": kind})

    for kind, rx in DATE_PATTERNS:
        for m in rx.finditer(text):
            g = m.groups()
            if kind == "iso":
                try:
                    add(m, date(int(g[0]), int(g[1]), int(g[2])), kind=kind)
                except ValueError:
                    pass
            elif kind == "numeric":
                a, b = int(g[0]), int(g[1])
                if g[2] is None and (re.match(r"\s*(?:people|personas|of us|adults)", text[m.end():], re.I)):
                    continue
                year = int(g[2]) + (2000 if g[2] and len(g[2]) == 2 else 0) if g[2] else None
                if a > 12 and 1 <= b <= 12:
                    mo, dy, amb = b, a, False
                elif b > 12 and 1 <= a <= 12:
                    mo, dy, amb = a, b, False
                elif 1 <= a <= 12 and 1 <= b <= 12:
                    mo, dy, amb = a, b, a != b
                else:
                    continue
                if amb:
                    add(m, None, True, kind)
                    continue
                try:
                    d = date(year, mo, dy) if year else _next_on_or_after(today, mo, dy)
                except ValueError:
                    d = None
                if d:
                    add(m, d, kind=kind)
            elif kind == "month_day":
                d = _next_on_or_after(today, MONTHS[g[0].lower()], int(g[1]))
                if d:
                    add(m, d, kind=kind)
            elif kind == "day_of_month":
                d = _next_on_or_after(today, MONTHS[g[1].lower()], int(g[0]))
                if d:
                    add(m, d, kind=kind)
            elif kind == "es_day_month":
                day = 1 if g[0].lower() == "primero" else int(g[0])
                d = _next_on_or_after(today, MONTHS[g[1].lower()], day)
                if d:
                    add(m, d, kind=kind)
            elif kind == "this_weekday":
                wd = WEEKDAYS[g[0].lower()]
                delta = (wd - today.weekday()) % 7
                if delta == 0:
                    delta = 7
                add(m, today + timedelta(days=delta), kind=kind)
            elif kind == "relative":
                w = m.group(0).lower()
                if w in ("today", "tonight", "hoy"):
                    add(m, today, kind=kind)
                elif w == "pasado mañana":
                    add(m, today + timedelta(days=2), kind=kind)
                else:
                    add(m, today + timedelta(days=1), kind=kind)
            elif kind == "bare_day":
                day = 1 if (g[1] or "").lower() == "primero" else int(g[0] or g[2])
                d = _next_day_of_month(today, day) if 1 <= day <= 31 else None
                if d:
                    add(m, d, kind=kind)
    found.sort(key=lambda x: x["start"])
    return found


def _is_visit(text: str, span: dict) -> bool:
    """Is this date about a showing rather than move-in? Look at the surrounding clause."""
    lo = max(0, span["start"] - 45)
    hi = min(len(text), span["end"] + 35)
    window = text[lo:hi]
    clause_start = max(text.rfind(c, 0, span["start"]) for c in ".!?\n,")
    clause_end = min([i for i in (text.find(c, span["end"]) for c in ".!?\n,") if i >= 0] or [len(text)])
    clause = text[clause_start + 1:clause_end + 1]
    if VISIT_CTX.search(clause) and not MOVE_CTX.search(clause):
        return True
    if VISIT_CTX.search(clause) and MOVE_CTX.search(clause):
        # whichever keyword is closer to the date wins
        v = min((abs(m.start() - (span["start"] - clause_start)) for m in VISIT_CTX.finditer(clause)), default=999)
        mv = min((abs(m.start() - (span["start"] - clause_start)) for m in MOVE_CTX.finditer(clause)), default=999)
        return v < mv
    return bool(VISIT_CTX.search(window) and not MOVE_CTX.search(window))


# ---------------------------------------------------------------------------- field rules

LEASE_EXC = _rx(r"sublet", r"subarrendar", r"break it with \d+ days", r"siempre que pueda salir", r"unless i get transferred",
                r"a menos que me trasladen", r"leave early", r"irme antes", r"break clause", r"cláusula de salida",
                r"as long as i can (?:leave|break|sublet)", r"if i can (?:leave|break)")
LEASE_NO = _rx(r"can'?t commit to a (?:full )?year", r"cannot commit to a (?:full )?year", r"no puedo comprometerme",
               r"a year is too long", r"un año es mucho", r"not a full year", r"don'?t want to sign for (?:12 months|a year)",
               r"no quiero firmar por (?:12 meses|un año)", r"un año no me sirve", r"can'?t do a (?:full )?year",
               r"no (?:puedo|quiero) (?:un año|12 meses)", r"won'?t do a year", r"no to a year")
LEASE_VAGUE = _rx(r"as long as (?:necessary|needed)", r"el tiempo que sea necesario", r"probably (?:could|can) do a year",
                  r"creo que podría un año|creo que podria un año", r"not sure how long", r"no sé cuánto tiempo|no se cuanto tiempo",
                  r"depends on how things go", r"depende de cómo|depende de como", r"maybe a year", r"tal vez un año",
                  r"a while,? hopefully", r"we'?ll see how long", r"however long you need", r"maybe less",
                  r"lo que haga falta", r"no estoy segur[oa] (?:de )?cuánto")
LEASE_YES = _rx(
    r"(?:a|one|1|full|un)[- ]?(?:year|año)(?: lease)? (?:works|is (?:fine|perfect|ok|okay|great|good)|perfect|me funciona|está bien|esta bien|perfecto|sí|si\b|no hay problema|ok)",
    r"(?:12|twelve)[- ]?(?:months?|meses|month lease)(?: lease)? (?:is |are )?(?:fine|ok|okay|works|good|sí|si\b|está bien|esta bien|no hay problema|me funciona)",
    r"contrato de 12 meses está bien|contrato de 12 meses esta bien", r"de acuerdo con (?:un año|12 meses|el contrato)",
    r"(?:can|could|will) do a (?:full )?year", r"(?:good|fine|ok|okay) with a (?:full )?year", r"yes to a year",
    r"one[- ]year lease is (?:totally )?fine", r"(?:12|twelve)[- ]month lease is (?:totally )?fine", r"(?:looking for )?long term so a year",
    r"a largo plazo", r"puedo (?:hacer )?un año", r"un año perfecto", r"i can do 12 months", r"a year is (?:totally )?fine",
    r"happy to sign (?:for )?a year", r"sign a (?:12[- ]month|one[- ]year|year) lease",
    r"(?:ok|okay|fine|good|happy|cool)(?: with)? (?:a |an )?(?:one[- ]year|1[- ]year|12[- ]month|year)(?: lease)?",
    r"(?:un año|12 meses|el contrato de un año)(?: me)? (?:está|esta|es|parece) (?:perfecto|bien|ok|buen[oa])",
    r"acepto (?:el contrato de )?(?:un año|12 meses)", r"(?:year|12[- ]month) lease (?:works|sounds good|is ok)")
YES_WORDS = _rx(r"^(?:yes|yeah|yep|yup|ya|sure|of course|totally|definitely|absolutely|correct|that'?s fine|that works|sounds good|sí|si|claro|por supuesto|de acuerdo|está bien|esta bien|perfecto|vale|totalmente)\b")
NO_WORDS = _rx(r"^(?:no|nope|nah|not really|no thanks|no gracias|la verdad no)\b")

PHONE_NO = _rx(r"rather not (?:share|give) (?:my|a) (?:number|phone)", r"prefiero no dar (?:mi|el) (?:número|numero|teléfono|telefono)",
               r"just email me", r"no phone", r"sin teléfono|sin telefono", r"keep it on here", r"mejor por aquí|mejor por aqui",
               r"don'?t (?:want to )?(?:give|share) (?:out )?my number")
PHONE_VAGUE = _rx(r"(?:number )?starts with \d{3}", r"empieza con \d{3}", r"(?:send|text) (?:you )?my number", r"send (?:it|the rest) later",
                  r"i'?ll send the rest", r"después te mando mi número|despues te mando mi numero|te mando mi número|te mando mi numero",
                  r"send my number later", r"\b\d{3}[-. ]\d{3}\b(?![-. ]?\d)")
PHONE_EXC = _rx(r"for now", r"new number soon", r"por ahora", r"cambio de número|cambio de numero", r"text only", r"solo mensajes",
                r"work phone", r"only after \d", r"temporary", r"temporal", r"can'?t take calls", r"no puedo contestar")

PERSON_NOUNS = r"(?:wife|husband|partner|girlfriend|boyfriend|fianc[eé]e?|sister|brother|friend|son|daughter|kid|child|baby|mom|mother|dad|father|cousin|roommate|aunt|uncle|grandma|grandmother|niece|nephew|best friend|bf|gf)"
PET_NOUNS = r"(?:dog|cat|pup|puppy|kitten|pet|bird|fish|hamster|rabbit|bunny|perro|gato|gata|perrita|perrito|gatito|mascota)"
ES_PERSON = r"(?:esposa|esposo|novia|novio|pareja|hermana|hermano|amiga|amigo|hijo|hija|bebé|bebe|mamá|mama|madre|papá|papa|padre|prim[oa]|suegra|suegro|tía|tia|tío|tio|sobrin[oa]|abuel[oa])"
NUMS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "uno": 1, "una": 1, "un": 1, "dos": 2, "tres": 3,
        "cuatro": 4, "cinco": 5, "seis": 6}
NUMW = r"(\d|one|two|three|four|five|six|dos|tres|cuatro|cinco|seis)"

OCC_EXC = _rx(r"stays? (?:over )?(?:on )?(?:the )?weekends", r"viene los fines de semana", r"a veces viene", r"visits a month",
              r"is with me every other week", r"está conmigo cada dos semanas|esta conmigo cada dos semanas", r"part[- ]time",
              r"visits (?:sometimes|often|on weekends)", r"(?:her|his|my) mom visits", r"cada otra semana")
OCC_VAGUE = _rx(r"maybe me and", r"me and maybe", r"tal vez yo y", r"yo y tal vez", r"\b1 (?:o|or) 2\b", r"\bone or two\b",
                r"possibly \d", r"not sure yet,? possibly", r"\buno o dos\b", r"posiblemente \d", r"might be \d")
OCC_NO = _rx(r"why does it matter how many", r"por qué importa cuántas|por que importa cuantas", r"rather not say how many",
             r"prefiero no decir cuántos|prefiero no decir cuantos")
OCC_ONE = _rx(r"\bjust (?:me|myself)\b", r"\bonly (?:me|myself)\b", r"\bsolo yo\b", r"\bsolamente yo\b", r"\bnada más yo\b|\bnomás yo\b",
              r"\bone person\b", r"\buna persona\b", r"\bonly one (?:occupant|person)\b", r"\bjust one (?:person|occupant)\b",
              r"\bjust 1\b", r"\bsolo una persona\b", r"\bit'?s just me\b", r"\bsolo, just me\b", r"\bme myself\b",
              r"\bsoy solo yo\b", r"\bviviría solo\b|\bviviria solo\b|\bvivo sol[oa]\b")


def _count_people(text: str) -> int | None:
    t = text.lower()
    m = re.search(rf"\b{NUMW}\s+(?:of us|people|adults|persons|personas|adultos)\b", t)
    if m:
        return NUMS.get(m.group(1), None) or int(m.group(1)) if m.group(1).isdigit() else NUMS[m.group(1)]
    m = re.search(rf"\bsomos\s+{NUMW}\b", t)
    if m:
        return int(m.group(1)) if m.group(1).isdigit() else NUMS[m.group(1)]
    m = re.search(rf"\bnosotros\s+{NUMW}\b", t)
    if m:
        return int(m.group(1)) if m.group(1).isdigit() else NUMS[m.group(1)]
    # "me, my husband and our baby" / "me and my wife" / "my mom and me" / "just myself and my cat"
    m = re.search(r"\b(?:it'?d be |it would be |just |only )?(?:me|myself|i)\b((?:\s*,\s*(?:my|our)\s+[\w ]+?)*\s*(?:,\s*)?(?:and|&|\+)\s+(?:my|our|a)\s+[\w]+(?:\s+friend)?)", t)
    if m:
        tail = m.group(1)
        persons = len(re.findall(rf"\b{PERSON_NOUNS}s?\b", tail))
        return 1 + persons
    m = re.search(rf"\b(?:my|our)\s+({PERSON_NOUNS})\s+and\s+(?:me|i)\b", t)
    if m:
        return 2
    m = re.search(rf"\b((?:mi|nuestr[oa])\s+{ES_PERSON}(?:\s*,\s*(?:mi|nuestr[oa])\s+{ES_PERSON})*)\s+y\s+yo\b", t)
    if m:
        return 1 + len(re.findall(ES_PERSON, m.group(1)))
    m = re.search(rf"\byo\s+y\s+(?:mi|nuestr[oa])\s+({ES_PERSON}|\w+)\b", t)
    if m:
        return 2 if re.fullmatch(ES_PERSON, m.group(1)) else 1
    if OCC_ONE.search(t):
        return 1
    return None


REASON_NO = _rx(r"rather not say why", r"prefiero no decir por qué|prefiero no decir por que", r"that'?s personal", r"\bes personal\b",
                r"prefer not to say why", r"no quiero decir por qué")
REASON_VAGUE = _rx(r"need a change", r"personal reasons", r"razones personales", r"necesito un cambio", r"time for something new", r"it'?s complicated",
                   r"es complicado", r"un cambio", r"algo nuevo", r"just because", r"porque sí", r"ready for a change")
CAP_STOP = r"(?=$|[.!?,;\n]| and | y | so | in the (?:spring|fall|summer|winter)| this (?:spring|fall)| en (?:la )?(?:primavera|otoño)| por eso| thanks| thank| gracias| muchas| saludos| also| también| tambien| lmk| but | pero |\s+[\U0001F300-\U0001FAFF])"
ENTITY = rf"(.+?){CAP_STOP}"
REASON_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(rf"\btravel nurse on a \d+[- ]week contract at {ENTITY}", re.I), "travel nurse contract at {0}"),
    (re.compile(rf"\benfermer[oa] viajer[oa] con (?:un )?contrato de \d+ semanas en {ENTITY}", re.I), "travel nurse contract at {0}"),
    (re.compile(rf"\b(?:starting|start|got|have) a new job at {ENTITY}", re.I), "new job at {0}"),
    (re.compile(rf"\bnew job at {ENTITY}", re.I), "new job at {0}"),
    (re.compile(rf"\b(?:empiezo|comienzo|tengo) un (?:trabajo nuevo|nuevo trabajo) en {ENTITY}", re.I), "new job at {0}"),
    (re.compile(rf"\bstart(?:ing)? grad school at {ENTITY}", re.I), "grad school at {0}"),
    (re.compile(rf"\bempiezo (?:la )?maestría en {ENTITY}|\bempiezo el posgrado en {ENTITY}", re.I), "grad school at {0}"),
    (re.compile(rf"\bvoy a estudiar en {ENTITY}", re.I), "studying at {0}"),
    (re.compile(rf"\b(?:i'?m |im )?(?:starting school|studying|going to school) at {ENTITY}", re.I), "studying at {0}"),
    (re.compile(r"\brelocating from (.+?) for work", re.I), "relocating from {0} for work"),
    (re.compile(r"\bme mudo desde (.+?) por trabajo", re.I), "relocating from {0} for work"),
    (re.compile(rf"\bjust moved here from {ENTITY}", re.I), "moved from {0}"),
    (re.compile(rf"\bacabo de (?:llegar|mudarme) (?:aquí )?(?:de|desde) {ENTITY}", re.I), "moved from {0}"),
    (re.compile(r"\b(?:my )?(?:current )?lease is ending\b|\blease ending\b|\bse me termina el contrato\b|\bmi contrato (?:actual )?se termina\b|\bmy lease is up\b", re.I), "current lease ending"),
    (re.compile(r"\bmoving out of my parents'?|\bsalgo de casa de mis padres\b|\bme voy de casa de mis padres\b", re.I), "moving out of parents' home"),
    (re.compile(r"\brent went up\b|\bme subieron (?:mucho )?la renta\b|\brent increase\b|\bsubió la renta\b", re.I), "current rent increase"),
    (re.compile(r"\bsave money\b|\bsaving money\b|\bquiero ahorrar\b|\bahorrar dinero\b", re.I), "saving money"),
    (re.compile(r"\broommate is moving out\b|\bmi compañer[oa] de cuarto se (?:va|muda)\b", re.I), "roommate moving out"),
    (re.compile(r"\bdivorc(?:e|io)\b", re.I), "divorce"),
    (re.compile(r"\blandlord is selling\b|\bel dueño (?:está|esta) vendiendo\b|\bvenden la casa\b", re.I), "landlord selling"),
    (re.compile(r"\bcloser to (?:my )?work\b|\bmás cerca de mi trabajo\b|\bmas cerca de mi trabajo\b", re.I), "closer to work"),
]
ACRONYMS = {"unc", "nccu", "ibm", "sas", "nc", "rti", "ncsu", "gsk", "ny", "la", "usa", "duke"}


def _entity_case(s: str) -> str:
    s = s.strip().strip("'\" ")
    if re.match(r"(?i)^(a|an|the|una?|el|la)\s", s):
        return s.lower() if s == s.upper() else s
    if s.islower() or s.isupper():
        return " ".join(w.upper() if w.lower() in ACRONYMS - {"duke"} else w.capitalize() for w in s.split())
    return s


INTENT_RULES: dict[str, re.Pattern] = {
    "price_negotiation": _rx(r"wiggle room", r"negociar", r"me lo deja en", r"would (?:u|you) take \$?\d", r"can you do \$?\d",
                             r"puede ser \$?\d", r"\$\d+ es mucho", r"is a bit steep|(?:rent|price) is too (?:expensive|much|high)|too expensive for me", r"discount", r"descuento",
                             r"lo puede bajar|bajar(?:le)? (?:un poco|el precio)", r"go down to", r"can (?:you|u) match", r"best price",
                             r"lower (?:the )?(?:rent|price)", r"cheaper", r"más barato|mas barato", r"any deal", r"negotiable",
                             r"rebaja", r"deal on (?:the )?rent", r"\bknock\b.*\boff\b"),
    "scheduling": _rx(r"come see it", r"(?:to|can i) see (?:it|the room|the place)", r"\bshowing\b", r"\bviewing\b", r"ir a ver(?:lo|la)?",
                      r"\bverlo\b|\bverla\b|ver el cuarto", r"take a look", r"estoy libre", r"i'?m free|im free", r"schedule",
                      r"horarios", r"agendar", r"\bvisita\b|\bvisitar\b", r"\btour\b", r"\bvisit\b", r"stop by|come by",
                      r"appointment", r"\bcita\b", r"make a schedule", r"what times are you"),
    "small_talk": re.compile(r"^$"),
    "not_now": _rx(r"not moving until", r"no me mudo hasta", r"not ready yet", r"todavía no,|todavia no,", r"in a couple (?:of )?months",
                   r"en un par de meses", r"reach out closer", r"reach back", r"téngame en cuenta|tengame en cuenta",
                   r"keep me in mind", r"ahorita no", r"vuelvo a buscar", r"timing'?s not right", r"maybe later", r"not right now",
                   r"más adelante|mas adelante", r"next year", r"el próximo año|el proximo año", r"le escribo después"),
    "hard_no": _rx(r"not interested", r"no longer interested", r"ya no me interesa", r"no me interesa", r"found a place",
                   r"ya encontré|ya encontre", r"stop texting", r"no me escriba más|no me escriba mas", r"remove me",
                   r"no thanks,? too far", r"no gracias,? queda", r"go with another place", r"went with another", r"stop contacting",
                   r"unsubscribe", r"don'?t contact me", r"decidimos ir con otro|ya rentamos otro|nos quedamos con otro"),
    "shorter_lease": _rx(r"\b(?:[1-9]|1[01])[- ]month leases?\b", r"month[- ]to[- ]month", r"mes a mes", r"for the semester",
                         r"por el semestre", r"contratos? de (?:[1-9]|1[01]) meses", r"shorter lease", r"short[- ]term", r"contrato más corto|contrato mas corto",
                         r"less than (?:a year|12 months)", r"only need it for \d", r"solo por \d+ meses", r"\b\d{1,2} months? only\b",
                         r"menos de un año"),
    "question": _rx(r"is it furnished", r"amueblado", r"utilities included", r"incluye los servicios", r"servicios incluidos",
                    r"(?:can i|puedo) (?:bring|llevar) (?:my|a mi)", r"is there (?:parking|a washer|laundry|a dryer)",
                    r"estacionamiento", r"washer|dryer|lavadora|secadora", r"how far is it", r"qué tan lejos|que tan lejos",
                    r"wifi included|incluye (?:el )?wifi|is (?:the )?wifi", r"what'?s the deposit|how much is the deposit",
                    r"cuánto es el depósito|cuanto es el deposito", r"pets? allowed|se permiten mascotas", r"is it (?:still )?available",
                    r"sigue disponible|todavía está disponible|todavia esta disponible", r"what'?s the address|cuál es la dirección",
                    r"(?:your|the) (?:phone )?number\??$|what number (?:can|should) i call|número de la propiedad|su número",
                    r"is there a (?:private )?bath", r"baño privado", r"what'?s included", r"qué incluye|que incluye",
                    r"pets?(?: are)? allowed|allow(?:s)? pets|permit pets|pets policy|furnished|furniture",
                    r"(?:contact|phone) number|their number|how do i contact", r"how much is (?:the )?rent|cuánto es la renta|cuanto es la renta", r"is (?:the )?room big"),
}
SMALL_TALK = _rx(r"^(?:thanks|thank you|thx|ty|gracias|mil gracias|muchas gracias|ok|okay|okey|cool|great|perfect|perfecto|got it|entendido|"
                 r"lol|haha|jaja|nice|love it|you'?re awesome|appreciate|muy amable|qué bien|que bien|have a great|buen fin|"
                 r"hello\?|hola\?|hi\?|you guys are|sounds good|awesome|genial|excelente|bueno|good to know|👍|😊|🙏)")
GREETING = re.compile(r"^\s*(?:hi|hey|hello|hola|buenas|buenos días|buenos dias|good morning|good afternoon|hi there|hey there)\b[!,.\s]*"
                      r"(?:(?:this is|it'?s|soy|i'?m)\s+\w+[.!,]?\s*|\w+ here[.!,]?\s*)?", re.I)
SIGNOFF = re.compile(r"(?:\s*(?:thanks|thank you|thank u|thx|gracias|muchas gracias|saludos|lmk|tbh)[!.,]*(?:,?\s*\w+)?[.!]?)+\s*$", re.I)
EMOJI = re.compile(r"[\U0001F000-\U0001FAFF☀-➿⭐✨️‍]+")


AFFIRM = _rx(r"^(?:that'?s (?:right|correct|great|it|about it)|that is (?:right|correct)|yes,? (?:that|now|please|i)|sounds (?:good|great|right)|works for me|i need that|perfect)")
PLEASANTRY = re.compile(
    r"\b(?:thanks?(?:'s)?|thank (?:you|u)|thx|ty|very much|so much|a lot|gracias|mil|muchas|ok(?:ay)?|okey|cool|great|perfect(?:o)?|"
    r"got it|entendido|lol|haha|jaja|nice|love it|you'?re|u'?re|awesome|appreciate(?: you| it)?|muy amable|qué bien|que bien|"
    r"have a (?:great|good|nice) (?:weekend|day)|buen fin de semana|hello|hola|hi|hey|you guys are so nice|sounds|really|good|"
    r"genial|excelente|bueno|yes|yeah|sure|no|this is fine|fine|for me|that is|that'?s|correct|it is|right|great apartment|"
    r"like a|for the quick reply|the|and|i|it|is|so|a|un|una|de|el|la|for|me|you|u|much|bunch|works?|that|all|need|help|now|"
    r"this|should|what|wanted|exactly|already|everything|anything|else|today|bye|goodbye|adiós|adios|wonderful|amazing|"
    r"helpful|of|my|to|very|lot|alright|all right|please|noted|great job|good job|apartment|place)\b", re.I)


def is_small_talk(core: str) -> bool:
    c = core.lower()
    if not re.search(r"[a-záéíóúñ]", c):
        return True
    rest = PLEASANTRY.sub(" ", c)
    rest = re.sub(r"[^a-záéíóúñ]+", " ", rest).strip()
    return len(rest.split()) == 0


def _core(text: str) -> str:
    t = EMOJI.sub(" ", text)
    t = GREETING.sub("", t.strip())
    t = SIGNOFF.sub("", t.strip())
    return re.sub(r"\s+", " ", t).strip(" .,!")


PENDING_RX = {
    "lease": re.compile(r"lease|12[- ]month|one[- ]year|a year|contrato|un año", re.I),
    "move_in": re.compile(r"move[- ]in|move in|moving|date|mudar|mudanza|fecha", re.I),
    "phone": re.compile(r"phone|number|teléfono|telefono|número|numero|celular", re.I),
    "occupants": re.compile(r"how many|people|occupants|cuántas personas|cuantas personas|living with|vivirían|vivirian", re.I),
    "reason": re.compile(r"\bwhy\b|reason|bringing you|por qué|por que|motivo", re.I),
}


def infer_pending(context: list[dict] | None) -> list[str]:
    if not context or context[-1].get("role") != "operator":
        return []
    t = context[-1].get("text", "")
    return [k for k, rx in PENDING_RX.items() if rx.search(t)]


def empty_output(language: str = "en") -> dict:
    return {"lease": {"status": "absent", "value": None}, "move_in": {"status": "absent", "date": None, "raw": None},
            "phone": {"status": "absent", "value": None}, "occupants": {"status": "absent", "value": None},
            "reason": {"status": "absent", "value": None}, "intents": [], "language": language}


def read_reply_fallback(text: str, pending_item: str | None = None, context: list[dict] | None = None,
                        today: str | date | None = None) -> dict:
    """Deterministic reader. Returns the reader JSON for the latest message `text`."""
    if isinstance(today, str):
        today = date.fromisoformat(today[:10])
    today = today or date.today()
    msg = text or ""
    low = msg.lower()
    out = empty_output(detect_language(msg))
    pend = [pending_item] if pending_item else infer_pending(context)
    core = _core(msg)

    # ---- phone
    pm = PHONE_RE.search(msg)
    if pm:
        val = f"+1{pm.group(1)}{pm.group(2)}{pm.group(3)}"
        out["phone"] = {"status": "exception" if PHONE_EXC.search(low) else "answered", "value": val}
    elif PHONE_NO.search(low):
        out["phone"] = {"status": "no", "value": None}
    elif PHONE_VAGUE.search(low):
        out["phone"] = {"status": "vague", "value": None}

    # ---- lease
    if LEASE_EXC.search(low):
        out["lease"] = {"status": "exception", "value": True}
    elif LEASE_NO.search(low):
        out["lease"] = {"status": "no", "value": False}
    elif LEASE_VAGUE.search(low):
        out["lease"] = {"status": "vague", "value": None}
    elif LEASE_YES.search(low):
        out["lease"] = {"status": "answered", "value": True}
    elif (gl := _generic_lease(low)) is not None:
        out["lease"] = gl
    elif "lease" in pend and len(re.split(r"[,.!?\n]", core)[0].split()) <= 3:
        c = re.split(r"[,.!?\n]", core)[0].lower().strip()
        if YES_WORDS.search(c):
            out["lease"] = {"status": "answered", "value": True}
        elif NO_WORDS.search(c):
            out["lease"] = {"status": "no", "value": False}

    # ---- move-in (dates near showing words are visits, not move-in)
    dates = [d for d in find_dates(msg, today) if not _is_visit(msg, d)]
    ctx_text = " ".join(c.get("text", "") for c in (context or []))
    if dates and "move_in" not in pend and not MOVE_CTX.search(msg) and VISIT_CTX.search(ctx_text) \
            and not re.search(r"move[- ]?in|mudar|mudanza|fecha de", ctx_text, re.I):
        dates = []  # a bare date answering a visit-scheduling thread is a showing date
        visit_date = True
    else:
        visit_date = False
    vague = VAGUE_DATE.search(msg)
    if MOVE_NO.search(low):
        out["move_in"] = {"status": "no", "date": None, "raw": None}
    elif dates and not (vague and vague.start() < dates[0]["start"] and not dates[0]["date"]):
        d = dates[0]
        if d["ambiguous"]:
            out["move_in"] = {"status": "vague", "date": None, "raw": d["raw"]}
        elif vague and _overlaps(vague.span(), (d["start"], d["end"])):
            out["move_in"] = {"status": "vague", "date": None, "raw": vague.group(0).strip()}
        else:
            st = "exception" if MOVE_COND.search(low) else "answered"
            out["move_in"] = {"status": st, "date": d["date"], "raw": d["raw"]}
    elif vague and not _vague_is_other(msg, vague):
        out["move_in"] = {"status": "vague", "date": None, "raw": vague.group(0).strip()}

    # ---- occupants
    n = _count_people(msg)
    if OCC_NO.search(low):
        out["occupants"] = {"status": "no", "value": None}
    elif OCC_VAGUE.search(low):
        out["occupants"] = {"status": "vague", "value": None}
    elif n is not None:
        out["occupants"] = {"status": "exception" if OCC_EXC.search(low) else "answered", "value": n}
    elif "occupants" in pend and re.fullmatch(rf"(?:{NUMW}|just me|solo yo)", core.lower()):
        w = core.lower()
        out["occupants"] = {"status": "answered", "value": 1 if "me" in w or "yo" in w else (int(w) if w.isdigit() else NUMS[w])}

    # ---- reason
    if REASON_NO.search(low):
        out["reason"] = {"status": "no", "value": None}
    else:
        for rx, fmt in REASON_RULES:
            m = rx.search(msg)
            if m:
                groups = [g for g in m.groups() if g]
                out["reason"] = {"status": "answered", "value": fmt.format(*[_entity_case(g) for g in groups])}
                break
        else:
            if REASON_VAGUE.search(low):
                out["reason"] = {"status": "vague", "value": None}
            elif (gm := GENERIC_REASON.search(msg)) and len(gm.group(1).split()) >= 2:
                out["reason"] = {"status": "answered", "value": gm.group(1).strip().rstrip(".")}

    # bare "I'd rather not say" / "prefiero no decir": attribute to what was asked
    if re.search(r"\b(?:prefiero no decir|i'?d rather not say|rather not say|prefer not to say)\b(?!\s+(?:why|por qué|por que|when|cuándo|cuando|how many))", low):
        target = next((p for p in pend if out[p]["status"] == "absent"), None)
        if target is None and out["occupants"]["status"] == "absent" and out["reason"]["status"] != "no":
            target = "occupants"
        if target:
            out[target] = {"status": "no", "value": False if target == "lease" else None}
            if target == "move_in":
                out[target] = {"status": "no", "date": None, "raw": None}

    # ---- intents
    intents = []
    for name, rx in INTENT_RULES.items():
        if name == "small_talk":
            continue
        if rx.search(msg):
            intents.append(name)
    if "question" in intents and "scheduling" in intents and not re.search(r"\?", msg.split("?")[0] + "?"):
        pass
    if "question" not in intents and "?" in msg:
        qpart = " ".join(seg for seg in re.split(r"(?<=[?.!\n])", msg) if "?" in seg)
        if ROOM_TOPIC.search(qpart) and not INTENT_RULES["scheduling"].search(qpart) and not INTENT_RULES["price_negotiation"].search(qpart) \
                and not INTENT_RULES["shorter_lease"].search(qpart) and not re.search(r"\b(?:find|search|look for|busca)\b", qpart, re.I):
            intents.append("question")
    if "shorter_lease" not in intents and re.search(r"\b(?:only need it|solo lo necesito) (?:for|por) (?:the |el )?(?:semester|semestre|summer|verano)", low):
        intents.append("shorter_lease")
    fields_hit = any(out[f]["status"] != "absent" for f in FIELDS)
    last_op = (context[-1]["text"] if context and context[-1].get("role") == "operator" else "")
    visit_asked = bool(re.search(r"\b(?:visit|schedule|appointment|tour|see the|viewing|showing|ver el|visita|cita)\b", last_op, re.I))
    if visit_date and "scheduling" not in intents:
        intents.append("scheduling")
    if visit_asked and not fields_hit and not intents:
        c = core.lower()
        if YES_WORDS.search(c) or AFFIRM.search(c) or find_dates(msg, today):
            intents.append("scheduling")
    if not fields_hit and not intents and is_small_talk(core):
        intents.append("small_talk")
    out["intents"] = [i for i in INTENTS if i in intents]
    return out


TERM = r"(?:(?:a|one|1|full|whole|un|1-)\s?[- ]?(?:year|yr|año)|12[- ]?(?:months?|meses|mo)|twelve months|one[- ]year|year[- ]long)"
POS = r"(?:fine|ok|okay|good|great|perfect|works?|sure|yes|no problem|happy|cool|sounds good|totally|absolutely|definitely|deal|agree|"\
      r"bien|perfecto|sí|funciona|de acuerdo|claro|sin problema|vale|acepto|me sirve|está bien|no hay bronca)"
NEG = r"(?:can'?t|cannot|don'?t|won'?t|too long|not|no puedo|no quiero|demasiado|es mucho|no me sirve|nope|rather not|prefer not)"


def _generic_lease(low: str) -> dict | None:
    for m in re.finditer(TERM, low):
        win = low[max(0, m.start() - 30):m.end() + 30]
        if re.search(r"\b(?:maybe|probably|perhaps|not sure|tal vez|quizás|quizas|a lo mejor|depends|depende)\b", win):
            return {"status": "vague", "value": None}
        if re.search(rf"\b{NEG}\b", win):
            return {"status": "no", "value": False}
        if re.search(rf"\b{POS}\b", win):
            return {"status": "answered", "value": True}
    return None


GENERIC_REASON = re.compile(r"(?:i'?m moving because|im moving because|moving because|the reason is|me mudo porque|la razón es|la razon es)\s+(?:i'?m\s+|im\s+)?(.+?)(?=$|[.!?;\n]|,| and | y | also| también| thanks| gracias)", re.I)
QUESTION_TOPICS = re.compile(r"\?.*$|^.*\?", re.S)
ROOM_TOPIC = re.compile(r"\b(?:furnished|furniture|utilit\w*|parking|laundry|washer|dryer|pets?|dogs?|cats?|deposit|wifi|internet|kitchen|"
                        r"bath(?:room)?|include[sd]?|ac|a/c|air|heat\w*|bus|close to|how far|distance|neighborhood|roommates?|quiet|"
                        r"smok\w*|guests?|application|fee|amueblado|servicios|estacionamiento|lavadora|mascotas?|depósito|deposito|"
                        r"cocina|baño|incluye|internet|compañeros|ruido|fumar|visitas|solicitud|cuota|available|disponible)\b", re.I)


def _overlaps(a, b) -> bool:
    return not (a[1] <= b[0] or a[0] >= b[1])


def _vague_is_other(text: str, m: re.Match) -> bool:
    """A month mention that is about something else ("my lease ends in January", "next year")."""
    s = m.group(0).lower()
    before = text[max(0, m.start() - 30):m.start()].lower()
    if re.search(r"lease ends|contrato termina|not moving until|no me mudo hasta|reach out|grad school|start", before):
        return True
    if s in ("soon", "pronto") and re.search(r"number|número|numero|ending|termina|cambio|getting|reply|hear", before):
        return True
    return bool(re.match(r"(?:in|en|by|para)\s", s) and re.search(r"\b(?:visit|see|showing|ver)\b", before))


# ---------------------------------------------------------------------------- validation + HTTP

def valid_reader_json(obj) -> bool:
    if not isinstance(obj, dict):
        return False
    for f in FIELDS:
        v = obj.get(f)
        if not isinstance(v, dict) or v.get("status") not in STATUSES:
            return False
    return isinstance(obj.get("intents"), list) and obj.get("language") in ("en", "es")


def _shared_prompt():
    root = find_repo_root()
    if root and (root / "reader" / "prompt.py").exists():
        import importlib.util
        spec = importlib.util.spec_from_file_location("rentus_reader_prompt", root / "reader" / "prompt.py")
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
            return mod
        except Exception:
            return None
    return None


def _http_read(inp: dict) -> dict | None:
    base = os.environ.get("READER_BASE_URL")
    if not base:
        return None
    model = os.environ.get("READER_MODEL", "rentus-reader")
    mod = _shared_prompt()
    if mod:
        messages = mod.build_messages(inp)
    else:
        ctx = "\n".join(f"{c['role']}: {c['text']}" for c in inp.get("context") or []) or "(none)"
        messages = [{"role": "system", "content": "Read the latest renter message and return reader JSON only "
                                                  "(fields lease, move_in, phone, occupants, reason, intents, language)."},
                    {"role": "user", "content": f"Today: {inp['today']}\nThread so far:\n{ctx}\nLatest renter message:\n{inp['message']}"}]
    body = {"model": model, "messages": messages, "temperature": 0.0, "max_tokens": 400,
            "chat_template_kwargs": {"enable_thinking": False}}
    headers = {"Content-Type": "application/json"}
    key = os.environ.get("READER_API_KEY")
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(base.rstrip("/") + "/chat/completions", data=json.dumps(body).encode(), headers=headers,
                                 method="POST")
    try:
        with urllib.request.urlopen(req, timeout=float(os.environ.get("READER_TIMEOUT", "20"))) as resp:
            text = json.loads(resp.read())["choices"][0]["message"].get("content") or ""
    except Exception as e:  # network, HTTP, shape: fall back
        print(f"[rentus_tools] reader HTTP backend failed ({type(e).__name__}); using fallback", file=sys.stderr)
        return None
    obj = mod.parse_output(text) if mod else _parse_json(text)
    if not valid_reader_json(obj):
        return None
    return obj


def _parse_json(text: str):
    t = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    s, e = t.find("{"), t.rfind("}")
    if s < 0 or e <= s:
        return None
    try:
        return json.loads(t[s:e + 1])
    except json.JSONDecodeError:
        return None


@tool("read_reply")
def read_reply(world, thread_id: str | None = None, text: str | None = None, pending_item: str | None = None):
    if (thread_id is None) == (text is None):
        raise ToolError("INVALID_ARGS", "read_reply: give exactly one of thread_id or text",
                        hint="read_reply args: thread_id (string) OR text (string), pending_item (optional)")
    context: list[dict] = []
    if thread_id is not None:
        t = need(world, "threads", thread_id, "thread", "list_threads")
        msgs = t["messages"]
        idx = max((i for i, m in enumerate(msgs) if m["from"] == "renter"), default=None)
        if idx is None:
            raise ToolError("NOT_FOUND", f"thread {thread_id} has no renter message to read")
        text = msgs[idx]["text"]
        context = [{"role": m["from"], "text": m["text"]} for m in msgs[:idx]][-6:]
    if not text.strip():
        raise ToolError("INVALID_ARGS", "read_reply: text is empty")
    inp = {"today": world.today(), "context": context, "message": text}
    if pending_item and not (context and context[-1]["role"] == "operator"):
        # let the model backend see what was asked
        inp["context"] = context + [{"role": "operator", "text": f"(asked about: {pending_item})"}]
    obj = _http_read(inp)
    backend = "model"
    if obj is None:
        obj = read_reply_fallback(text, pending_item=pending_item, context=context, today=world.today())
        backend = "fallback"
    out = {k: obj.get(k) for k in (*FIELDS, "intents", "language")}
    out["backend"] = backend
    if thread_id:
        out["thread_id"] = thread_id
    return out
