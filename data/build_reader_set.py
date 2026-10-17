"""W5 step 2: labeled dataset for the READER model (renter message -> exact JSON).

Schema and labeling rules: data/reader_schema.md.

Two sources:
  (a) SGD Homes_1/Homes_2 USER turns, re-labeled for our schema by rules over the
      SGD dialogue acts (visit_date -> scheduling, REQUEST phone_number -> question,
      THANK_YOU/GOODBYE-only -> small_talk, NEGATE_INTENT -> not_now, ...).
      SGD's own train/dev/test split is kept, so SGD test dialogues never train.
  (b) Synthetic renter messages composed from hand-written English and Spanish
      templates, with persona-style variation (casual/formal/terse/emoji/verbose).
      No LLM is used. Every label is known by construction.

Held-out design: every template list reserves every 5th template (index % 5 == 4)
for the test split only, and test uses separate name / employer / phone pools, so
test measures generalization to unseen phrasings, not memorized strings.

Outputs:
  data/processed/reader/{train,dev,test}.jsonl   (full; gitignored)
  data/published/reader/{train,dev,test}.jsonl   (train capped at 5000; committed)
  data/published/reader/stats.json

Usage: data/.venv/bin/python data/build_reader_set.py [--train 12000 --dev 800 --test 1200 --seed 7]
"""
from __future__ import annotations

import argparse
import calendar
import collections
import datetime as dt
import json
import random
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SGD_FILE = ROOT / "raw" / "sgd" / "homes_dialogues.jsonl"
OUT_PROC = ROOT / "processed" / "reader"
OUT_PUB = ROOT / "published" / "reader"
PUBLISHED_TRAIN_CAP = 5000

STATUSES = ["answered", "vague", "no", "exception", "absent"]
INTENTS = ["price_negotiation", "scheduling", "small_talk", "not_now", "hard_no", "shorter_lease", "question"]

MONTHS_EN = [m for m in calendar.month_name][1:]
MONTHS_EN_ABBR = [m for m in calendar.month_abbr][1:]
MONTHS_ES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
             "septiembre", "octubre", "noviembre", "diciembre"]
WEEKDAYS_EN = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
WEEKDAYS_ES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
ORD_ES = {1: "primero"}


def ordinal(n: int) -> str:
    suf = "th" if 11 <= n % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


# ---------------------------------------------------------------------------
# pools (train/dev pools vs test pools are disjoint)
# ---------------------------------------------------------------------------
POOLS = {
    "train": {
        "name_en": ["Jordan", "Tyler", "Brianna", "Marcus", "Ashley", "Kevin", "Destiny", "Ryan", "Megan", "Andre",
                    "Courtney", "Josh", "Tasha", "Ben", "Kayla", "Derek", "Monique", "Sam", "Hannah", "Darnell"],
        "name_es": ["José", "María", "Luis", "Guadalupe", "Carlos", "Ana", "Miguel", "Rosa", "Jorge", "Lucía",
                    "Alejandro", "Fernanda", "Juan", "Isabel", "Diego", "Paola"],
        "employer": ["Duke Hospital", "IBM", "Cisco", "a startup downtown", "Amazon", "UNC Health", "Fidelity",
                     "Biogen", "Credit Suisse", "Google", "a restaurant on 9th St", "Lenovo"],
        "school": ["Duke", "NC State", "NCCU", "Durham Tech"],
        "city": ["Charlotte", "Atlanta", "New York", "Ohio", "Greensboro", "Florida", "Virginia", "Texas"],
        "area_code": ["919", "984", "336", "704"],
    },
    "test": {
        "name_en": ["Quentin", "Rachel", "Malik", "Lindsey", "Trevor", "Jasmine", "Colin", "Imani"],
        "name_es": ["Ernesto", "Yesenia", "Ramón", "Marisol", "Héctor", "Daniela"],
        "employer": ["Duke Energy", "Red Hat", "SAS", "Pfizer", "the VA hospital", "Apple"],
        "school": ["UNC", "Meredith College"],
        "city": ["Boston", "Chicago", "Puerto Rico", "Mexico"],
        "area_code": ["910", "252", "828"],
    },
}
POOLS["dev"] = POOLS["train"]
PRICES = [650, 700, 725, 750, 775, 800, 850, 900]


# ---------------------------------------------------------------------------
# template lists: (text, value) ; index % 5 == 4 is test-only
# ---------------------------------------------------------------------------
def pick(rng: random.Random, items: list, split: str, tag: str, used: list):
    idx = list(range(len(items)))
    held = [i for i in idx if i % 5 == 4]
    if split == "test":
        cand = held if held and rng.random() < 0.6 else idx
    else:
        cand = [i for i in idx if i % 5 != 4] or idx
    i = rng.choice(cand)
    used.append(f"{tag}#{i}")
    return items[i]


LEASE = {
    "en": {
        "answered": ["a 12 month lease is fine", "yes I'm ok with a one year lease", "a year works for me",
                     "I'm looking for long term so a year is perfect", "1 year lease no problem",
                     "yes, 12 months is fine", "I can do a full year", "one-year lease is totally fine with me",
                     "I'm good with a year", "yeah I'd sign for 12 months"],
        "vague": ["as long as necessary", "probably could do a year", "not sure how long I'll stay tbh",
                  "depends on how things go", "long term I think", "a while, hopefully",
                  "we'll see how long", "maybe a year, maybe less", "however long you need",
                  "I'd like to stay a good while"],
        "no": ["I can't commit to a full year", "a year is too long for me", "no, not a full year",
               "I don't want to sign for 12 months", "a year lease won't work for me"],
        "exception": ["a year is fine but I might need to leave early if my contract ends",
                      "12 months ok as long as I can sublet over the summer",
                      "yes to a year, if I can break it with 60 days notice",
                      "I can do a year unless I get transferred, is there a break clause?",
                      "a one year lease works if I can move out early for a job"],
        "ellipsis_yes": ["yes", "yep 👍", "yeah that's fine", "sure", "yes ma'am", "of course", "totally"],
        "ellipsis_no": ["no", "nah", "not really"],
    },
    "es": {
        "answered": ["un contrato de 12 meses está bien", "sí, estoy de acuerdo con un año",
                     "un año me funciona", "busco algo a largo plazo, un año perfecto", "sí, puedo firmar por un año",
                     "claro, 12 meses no hay problema", "un año está perfecto para mí"],
        "vague": ["el tiempo que sea necesario", "creo que podría un año", "no sé cuánto tiempo me quedaré",
                  "depende de cómo vayan las cosas", "por un buen tiempo", "tal vez un año, tal vez menos"],
        "no": ["no puedo comprometerme a un año", "un año es mucho para mí", "no quiero firmar por 12 meses",
               "un año no me sirve", "no, un año completo no"],
        "exception": ["un año está bien pero tal vez tenga que irme antes por el trabajo",
                      "12 meses sí, si puedo subarrendar en el verano",
                      "un año sí, siempre que pueda salir con 60 días de aviso",
                      "puedo un año a menos que me trasladen"],
        "ellipsis_yes": ["sí", "sí claro", "si 👍", "por supuesto", "dale"],
        "ellipsis_no": ["no", "no, la verdad no"],
    },
}

# move-in: answered surfaces get a concrete date; we render it
MOVE_EXACT_EN = ["I'd like to move in {d}", "move in date would be {d}", "I can move {d}", "looking to move in on {d}",
                 "{d} would be ideal for me", "I need a place by {d}", "planning to move {d}",
                 "my move in date is {d}", "I want to come in {d}", "ready to move on {d}"]
MOVE_EXACT_ES = ["me gustaría mudarme {d}", "puedo mudarme {d}", "mi fecha de mudanza sería {d}",
                 "necesito el cuarto para {d}", "quiero entrar {d}", "estaría lista para mudarme {d}"]
MOVE_VAGUE_EN = ["next month", "soon", "ASAP", "around the 15th", "sometime in {month}", "early {month}",
                 "end of the month", "in a few weeks", "mid {month}", "whenever it's ready",
                 "beginning of next month", "as soon as possible", "around {month}", "in the next couple weeks"]
MOVE_VAGUE_ES = ["el mes que viene", "pronto", "lo antes posible", "a fines de mes", "a mediados de {month}",
                 "alrededor del 15", "en unas semanas", "a principios de {month}", "cuando esté listo"]
MOVE_NO_EN = ["I don't have a move in date yet", "not sure when I'm moving honestly", "I'd rather not say when yet"]
MOVE_NO_ES = ["todavía no tengo fecha", "no sé cuándo me mudo"]
MOVE_EXC_EN = ["{d}, unless my current lease gets extended", "{d} but it could slip a week if my job start moves",
               "{d} hopefully, depends on my closing", "{d} if the room is ready by then"]
MOVE_EXC_ES = ["{d}, a menos que me extiendan el contrato actual", "{d} si el cuarto está listo",
               "{d} pero podría ser una semana después"]
MOVE_WRAP_VAGUE_EN = ["I'd like to move in {v}", "moving {v}", "looking to move {v}", "I need a room {v}", "{v}"]
MOVE_WRAP_VAGUE_ES = ["me quiero mudar {v}", "necesito el cuarto {v}", "{v}", "me mudaría {v}"]

PHONE_FMT = ["({a}) {b}-{c}", "{a}-{b}-{c}", "{a}.{b}.{c}", "{a}{b}{c}", "+1 {a} {b} {c}", "1-{a}-{b}-{c}",
             "{a} {b} {c}", "+1{a}{b}{c}", "({a}){b}-{c}", "{a} {b}-{c}"]
PHONE_EN = ["my number is {p}", "you can reach me at {p}", "cell: {p}", "text me at {p}", "{p}",
            "call or text {p}", "here's my phone {p}", "my cell is {p}", "best number is {p}", "phone {p}"]
PHONE_ES = ["mi número es {p}", "me puedes escribir al {p}", "mi celular es {p}", "{p}", "llámame al {p}",
            "mi teléfono: {p}"]
PHONE_VAGUE_EN = ["my number starts with {a}", "I'll send my number later", "it's {a}-{b}, I'll send the rest",
                  "I'll text you my number"]
PHONE_VAGUE_ES = ["después te mando mi número", "empieza con {a}"]
PHONE_NO_EN = ["I'd rather not share my number", "please just email me, no phone", "I prefer to keep it on here"]
PHONE_NO_ES = ["prefiero no dar mi número", "mejor por aquí, sin teléfono"]
PHONE_EXC_EN = ["use {p} for now, I'm getting a new number soon", "{p} but text only, I can't take calls at work",
                "{p} is my work phone, only after 5"]
PHONE_EXC_ES = ["{p} por ahora, pronto cambio de número", "{p} pero solo mensajes"]

# occupants: (text, count)
OCC_EN = [("just me", 1), ("me and my girlfriend", 2), ("it would be me and my wife", 2), ("only me", 1),
          ("2 people", 2), ("me and my dog", 1), ("me, my husband and our baby", 3), ("solo, just me", 1),
          ("me and my boyfriend", 2), ("it'd be me and my sister", 2), ("just myself and my cat", 1),
          ("3 of us", 3), ("me and my son", 2), ("one person", 1), ("me plus my partner", 2),
          ("just me 🙋", 1), ("my mom and me", 2), ("two adults", 2), ("only one occupant", 1), ("me and a roommate", 2)]
OCC_ES = [("solo yo", 1), ("mi novia y yo", 2), ("mi esposo y yo", 2), ("somos 2", 2), ("yo y mi perro", 1),
          ("mi esposa, mi hija y yo", 3), ("una persona", 1), ("solamente yo", 1), ("somos tres", 3),
          ("mi hermano y yo", 2)]
OCC_VAGUE_EN = ["maybe me and a friend", "not sure yet, possibly 2", "me and maybe my cousin", "1 or 2 people"]
OCC_VAGUE_ES = ["tal vez yo y un amigo", "no sé, 1 o 2"]
OCC_NO_EN = ["why does it matter how many people?"]
OCC_NO_ES = ["prefiero no decir"]
OCC_EXC_EN = [("just me, but my boyfriend stays over on weekends", 1), ("me and my wife, her mom visits a month a year", 2),
              ("only me, my daughter is with me every other week", 1)]
OCC_EXC_ES = [("solo yo, pero mi novio viene los fines de semana", 1), ("mi esposa y yo, a veces viene mi suegra", 2)]

# reason: (text, normalized value)
REASON_EN = [("I'm starting a new job at {employer}", "new job at {employer}"),
             ("I start grad school at {school} in the spring", "grad school at {school}"),
             ("my current lease is ending", "current lease ending"),
             ("I'm relocating from {city} for work", "relocating from {city} for work"),
             ("I want to be closer to my job", "closer to work"),
             ("my roommate is moving out and I can't afford the place alone", "roommate moving out"),
             ("I'm going through a divorce", "divorce"),
             ("my landlord is selling the house", "landlord selling"),
             ("I'm a travel nurse on a 13 week contract at {employer}", "travel nurse contract at {employer}"),
             ("I got transferred to the Durham office", "job transfer to Durham"),
             ("I'm moving out of my parents' place", "moving out of parents' home"),
             ("my rent went up too much", "current rent increase"),
             ("I just moved here from {city}", "moved from {city}"),
             ("I want to save money, a studio is too expensive", "saving money"),
             ("I'm starting at {school} this fall", "starting at {school}")]
REASON_ES = [("empiezo un trabajo nuevo en {employer}", "new job at {employer}"),
             ("se me termina el contrato actual", "current lease ending"),
             ("me mudo desde {city} por trabajo", "relocating from {city} for work"),
             ("quiero estar más cerca de mi trabajo", "closer to work"),
             ("el dueño está vendiendo la casa", "landlord selling"),
             ("voy a estudiar en {school}", "studying at {school}"),
             ("me subieron mucho la renta", "current rent increase")]
REASON_VAGUE_EN = ["just need a change", "personal reasons", "time for something new", "it's complicated lol",
                   "just looking around"]
REASON_VAGUE_ES = ["por razones personales", "necesito un cambio", "es complicado"]
REASON_NO_EN = ["I'd rather not say why", "that's personal"]
REASON_NO_ES = ["prefiero no decir por qué"]
REASON_WRAP_EN = ["I'm moving because {r}", "{r}", "the reason is {r}", "{r}, so I need a new place"]
REASON_WRAP_ES = ["me mudo porque {r}", "{r}", "{r}, por eso busco cuarto"]

INTENT_TXT = {
    "en": {
        "price_negotiation": ["is there any wiggle room on the rent?", "would you take {p2}?",
                              "${p} is a bit steep, can you do {p2}?", "any discount if I pay 3 months upfront?",
                              "is the price negotiable?", "could you go down to {p2} a month?",
                              "I saw a similar room for {p2}, can you match that?", "best price you can do?"],
        "scheduling": ["can I come see it {day}?", "is {day} at {time} ok for a showing?", "when can I take a look?",
                       "I'm free {day} after {time} to see it", "could we do a tour {day}?",
                       "can I schedule a viewing?", "does {day} morning work to see the room?",
                       "what times are you showing it this week?"],
        "not_now": ["I'm not moving until the spring, can I reach back then?", "not ready yet, maybe in a couple months",
                    "my lease ends in {month2}, I'll reach out closer to then",
                    "not right now, but keep me in mind for next year", "I'll be looking again in a few months",
                    "timing's not right for me yet, maybe later"],
        "hard_no": ["not interested anymore, thanks", "I found a place already", "please stop texting me",
                    "no thanks, too far from work", "I'm going to pass", "we decided to go with another place",
                    "remove me from your list"],
        "shorter_lease": ["is a 6 month lease possible?", "can I do month to month?", "I only need it for the semester",
                          "do you do 3 month leases?", "could I sign for 9 months instead?",
                          "any chance of a shorter lease?"],
        "question": ["is it furnished?", "are utilities included?", "can I bring my cat?", "is there parking?",
                     "is the bathroom shared?", "is there a washer and dryer?", "how far is it from Duke?",
                     "is wifi included?", "what's the deposit?"],
    },
    "es": {
        "price_negotiation": ["¿se puede negociar la renta?", "¿me lo deja en {p2}?", "${p} es mucho, ¿puede ser {p2}?",
                              "¿hay descuento si pago 3 meses por adelantado?", "¿cuál es el mejor precio?",
                              "¿lo puede bajar un poco?"],
        "scheduling": ["¿puedo ir a verlo el {day}?", "¿el {day} a las {time} está bien para verlo?",
                       "¿cuándo puedo ir a ver el cuarto?", "estoy libre el {day} después de las {time}",
                       "¿podemos agendar una visita?", "¿qué horarios tiene esta semana para verlo?"],
        "not_now": ["no me mudo hasta la primavera, ¿le escribo después?", "todavía no, tal vez en un par de meses",
                    "ahorita no, pero téngame en cuenta para el próximo año", "vuelvo a buscar en unos meses",
                    "por ahora no es buen momento"],
        "hard_no": ["ya no me interesa, gracias", "ya encontré un lugar", "por favor no me escriba más",
                    "no gracias, queda muy lejos", "voy a pasar"],
        "shorter_lease": ["¿se puede un contrato de 6 meses?", "¿puedo rentar mes a mes?", "solo lo necesito por el semestre",
                          "¿hacen contratos de 3 meses?", "¿puede ser por menos tiempo?"],
        "question": ["¿está amueblado?", "¿incluye los servicios?", "¿puedo llevar a mi gato?", "¿hay estacionamiento?",
                     "¿el baño es compartido?", "¿incluye wifi?", "¿cuánto es el depósito?"],
    },
}
SMALL_TALK = {
    "en": ["thanks!!", "ok cool", "😊👍", "you're awesome, thank you", "sounds good", "lol ok", "have a great weekend!",
           "thank you so much 🙏", "got it", "the pictures look amazing!", "you guys are so nice", "ok 👌", "haha nice",
           "appreciate you!", "k", "love it 😍", "great, thanks for the quick reply", "hello?", "👍", "awesome"],
    "es": ["¡gracias!", "ok perfecto", "😊👍", "muy amable, gracias", "suena bien", "jaja ok", "¡buen fin de semana!",
           "mil gracias 🙏", "entendido", "las fotos se ven muy bonitas", "ok 👌", "¡qué bien!", "hola?", "👍"],
}
OPENERS = {
    "en": ["", "", "hi! ", "hey ", "Hello, ", "Hi there, ", "good morning! ", "hey {name} here, ", "Hi, this is {name}. "],
    "es": ["", "", "hola! ", "buenas, ", "Hola, ", "buenos días, ", "hola, soy {name}. "],
}
CLOSERS = {
    "en": ["", "", "", " thanks!", " thank you", " 🙂", " lmk", " Thanks, {name}", " 🙏"],
    "es": ["", "", "", " gracias!", " muchas gracias", " 🙂", " saludos, {name}", " 🙏"],
}
JOIN = {"en": [". ", ", ", " and ", ". also ", "\n", "! "], "es": [". ", ", ", " y ", ". también ", "\n", "! "]}

OP_ASK = {
    "en": {"lease": "are you okay with a 12-month lease?", "move_in": "what exact date would you like to move in?",
           "phone": "what's the best phone number to reach you?", "occupants": "how many people would be living in the room?",
           "reason": "what's bringing you to the area / why are you moving?"},
    "es": {"lease": "¿está de acuerdo con un contrato de 12 meses?", "move_in": "¿qué fecha exacta le gustaría mudarse?",
           "phone": "¿cuál es su número de teléfono?", "occupants": "¿cuántas personas vivirían en el cuarto?",
           "reason": "¿por qué se está mudando?"},
}
OP_INTRO = {
    "en": ["Thanks for your interest in the {room} room! A couple quick questions: ", "Hi! The {room} room is still available. ",
           "Great, thanks. ", "Got it. ", "Thanks! Just a few more things: "],
    "es": ["¡Gracias por su interés en el cuarto de {room}! Unas preguntas: ", "¡Hola! El cuarto de {room} sigue disponible. ",
           "Perfecto, gracias. ", "Entendido. "],
}
ROOMS = ["Appling Way", "Howard St", "Ridge Rd", "Lakewood Ave", "Hillandale Rd", "Alston Ave"]
FIRST_MSG = {
    "en": ["Hi, is the room still available?", "Interested in the room on {room}", "is this still available?",
           "Hello I saw your listing for {room}, is it available?"],
    "es": ["Hola, ¿todavía está disponible el cuarto?", "Me interesa el cuarto en {room}", "¿sigue disponible?"],
}


# ---------------------------------------------------------------------------
# date rendering
# ---------------------------------------------------------------------------
def render_exact_date(rng: random.Random, today: dt.date, lang: str, used: list) -> tuple[dt.date, str, list[str]]:
    """Return (date, surface, hard_case_tags) for a date that counts as exact."""
    kind = rng.choices(["month_day", "ordinal_day", "weekday", "tomorrow", "numeric_unamb", "iso"],
                       [45, 15, 12, 5, 15, 3])[0]
    tags: list[str] = []
    if kind == "month_day":
        d = today + dt.timedelta(days=rng.randint(3, 90))
        if rng.random() < 0.3:  # most move-ins are on the 1st ("Nov 1st", "el primero de noviembre")
            d = (d.replace(day=1) + dt.timedelta(days=32)).replace(day=1)
            tags.append("first_of_month")
        if lang == "en":
            form = rng.choice(["{M} {o}", "{Mab} {o}", "{M} {n}", "{Mab} {n}", "{o} of {M}", "{Mab}. {n}"])
            s = form.format(M=MONTHS_EN[d.month - 1], Mab=MONTHS_EN_ABBR[d.month - 1], o=ordinal(d.day), n=d.day)
            s = rng.choice([s, "on " + s, s.lower()])
        else:
            dd = "primero" if d.day == 1 and rng.random() < 0.7 else str(d.day)
            s = rng.choice(["el {dd} de {m}", "{dd} de {m}", "el día {dd} de {m}"]).format(dd=dd, m=MONTHS_ES[d.month - 1])
            if d.day == 1:
                tags.append("es_primero")
    elif kind == "ordinal_day":
        day = rng.choice([1, 1, 1, 5, 10, 15, 20, 25])
        d = today.replace(day=1)
        cand = [today.replace(day=day) if today.day <= day else None]
        nxt = (today.replace(day=1) + dt.timedelta(days=32)).replace(day=day)
        d = cand[0] if cand[0] else nxt
        s = (f"the {ordinal(day)}" if lang == "en" else ("el primero" if day == 1 else f"el {day}"))
        tags.append("bare_day_of_month")
    elif kind == "weekday":
        wd = rng.randint(0, 6)
        delta = (wd - today.weekday()) % 7 or 7
        d = today + dt.timedelta(days=delta)
        s = (f"this {WEEKDAYS_EN[wd]}" if lang == "en" else f"este {WEEKDAYS_ES[wd]}")
        tags.append("relative_weekday")
    elif kind == "tomorrow":
        d = today + dt.timedelta(days=1)
        s = "tomorrow" if lang == "en" else "mañana mismo"
        tags.append("relative_day")
    elif kind == "numeric_unamb":
        # one part > 12 so month/day order is not ambiguous
        while True:
            d = today + dt.timedelta(days=rng.randint(3, 90))
            if d.day > 12:
                break
        s = f"{d.month}/{d.day}" if lang == "en" else f"{d.day}/{d.month}"
        tags.append("numeric_date")
    else:
        d = today + dt.timedelta(days=rng.randint(3, 90))
        s = d.isoformat()
    return d, s, tags


def ambiguous_numeric(rng: random.Random, today: dt.date, lang: str) -> str:
    while True:
        d = today + dt.timedelta(days=rng.randint(3, 120))
        if d.day <= 12 and d.day != d.month:
            return f"{d.month}/{d.day}" if lang == "en" else f"{d.day}/{d.month}"


# ---------------------------------------------------------------------------
# synthetic generator
# ---------------------------------------------------------------------------
def empty_output(lang: str) -> dict:
    return {"lease": {"status": "absent", "value": None},
            "move_in": {"status": "absent", "date": None, "raw": None},
            "phone": {"status": "absent", "value": None},
            "occupants": {"status": "absent", "value": None},
            "reason": {"status": "absent", "value": None},
            "intents": [], "language": lang}


def make_phone(rng: random.Random, pool: dict, lang: str) -> tuple[str, str, str, str]:
    a = rng.choice(pool["area_code"])
    b = "555"  # fictional exchange
    c = f"01{rng.randint(0, 99):02d}"
    return a, b, c, f"+1{a}{b}{c}"


def fill(t: str, ctx: dict) -> str:
    return t.format(**ctx) if "{" in t else t


STATUS_W = {"answered": 50, "vague": 22, "no": 10, "exception": 10}


def gen_field(rng, field, lang, split, pool, today, ctx, used, tags, out, ellipsis_ok):
    st = rng.choices(list(STATUS_W), list(STATUS_W.values()))[0]
    E = lang == "en"
    if field == "lease":
        if ellipsis_ok and st in ("answered", "no") and rng.random() < 0.35:
            key = "ellipsis_yes" if st == "answered" else "ellipsis_no"
            txt = pick(rng, LEASE[lang][key], split, f"lease.{key}", used)
            tags.append("elliptical_answer")
        else:
            txt = pick(rng, LEASE[lang][st], split, f"lease.{st}", used)
        out["lease"] = {"status": st, "value": {"answered": True, "exception": True, "no": False}.get(st)}
        if st == "vague" and ("necessary" in txt or "necesario" in txt):
            tags.append("as_long_as_necessary")
        return txt
    if field == "move_in":
        if st == "answered":
            d, s, tg = render_exact_date(rng, today, lang, used)
            tags += tg
            if ellipsis_ok and rng.random() < 0.3:
                txt = s
                tags.append("elliptical_answer")
            else:
                txt = pick(rng, MOVE_EXACT_EN if E else MOVE_EXACT_ES, split, "move.exact", used).format(d=s)
            out["move_in"] = {"status": "answered", "date": d.isoformat(), "raw": s}
        elif st == "vague":
            if rng.random() < 0.18:
                v = ambiguous_numeric(rng, today, lang)
                tags.append("ambiguous_numeric_date")
            else:
                nm = (today.replace(day=1) + dt.timedelta(days=32))
                v = pick(rng, MOVE_VAGUE_EN if E else MOVE_VAGUE_ES, split, "move.vague", used).format(
                    month=(MONTHS_EN if E else MONTHS_ES)[nm.month - 1])
                tags.append("vague_date")
            txt = pick(rng, MOVE_WRAP_VAGUE_EN if E else MOVE_WRAP_VAGUE_ES, split, "move.vwrap", used).format(v=v)
            out["move_in"] = {"status": "vague", "date": None, "raw": v}
        elif st == "no":
            txt = pick(rng, MOVE_NO_EN if E else MOVE_NO_ES, split, "move.no", used)
            out["move_in"] = {"status": "no", "date": None, "raw": None}
        else:
            d, s, tg = render_exact_date(rng, today, lang, used)
            tags += tg
            txt = pick(rng, MOVE_EXC_EN if E else MOVE_EXC_ES, split, "move.exc", used).format(d=s)
            out["move_in"] = {"status": "exception", "date": d.isoformat(), "raw": s}
        return txt
    if field == "phone":
        a, b, c, e164 = make_phone(rng, pool, lang)
        p = pick(rng, PHONE_FMT, split, "phone.fmt", used).format(a=a, b=b, c=c)
        if st == "answered":
            if ellipsis_ok and rng.random() < 0.3:
                txt = p
                tags.append("elliptical_answer")
            else:
                txt = pick(rng, PHONE_EN if E else PHONE_ES, split, "phone.ans", used).format(p=p)
            out["phone"] = {"status": "answered", "value": e164}
            tags.append("phone_format")
        elif st == "vague":
            txt = pick(rng, PHONE_VAGUE_EN if E else PHONE_VAGUE_ES, split, "phone.vague", used).format(a=a, b=b)
            out["phone"] = {"status": "vague", "value": None}
        elif st == "no":
            txt = pick(rng, PHONE_NO_EN if E else PHONE_NO_ES, split, "phone.no", used)
            out["phone"] = {"status": "no", "value": None}
        else:
            txt = pick(rng, PHONE_EXC_EN if E else PHONE_EXC_ES, split, "phone.exc", used).format(p=p)
            out["phone"] = {"status": "exception", "value": e164}
        return txt
    if field == "occupants":
        if st == "answered":
            txt, n = pick(rng, OCC_EN if E else OCC_ES, split, "occ.ans", used)
            if any(w in txt for w in ("dog", "cat", "perro", "gato")):
                tags.append("pet_not_occupant")
            if any(w in txt for w in ("girlfriend", "novia", "boyfriend")):
                tags.append("me_and_partner")
            out["occupants"] = {"status": "answered", "value": n}
        elif st == "vague":
            txt = pick(rng, OCC_VAGUE_EN if E else OCC_VAGUE_ES, split, "occ.vague", used)
            out["occupants"] = {"status": "vague", "value": None}
        elif st == "no":
            txt = pick(rng, OCC_NO_EN if E else OCC_NO_ES, split, "occ.no", used)
            out["occupants"] = {"status": "no", "value": None}
        else:
            txt, n = pick(rng, OCC_EXC_EN if E else OCC_EXC_ES, split, "occ.exc", used)
            out["occupants"] = {"status": "exception", "value": n}
        return txt
    if field == "reason":
        if st == "exception":
            st = "answered"
        if st == "answered":
            t, v = pick(rng, REASON_EN if E else REASON_ES, split, "reason.ans", used)
            r, v = t.format(**ctx), v.format(**ctx)
            out["reason"] = {"status": "answered", "value": v}
        elif st == "vague":
            r = pick(rng, REASON_VAGUE_EN if E else REASON_VAGUE_ES, split, "reason.vague", used)
            out["reason"] = {"status": "vague", "value": None}
        else:
            r = pick(rng, REASON_NO_EN if E else REASON_NO_ES, split, "reason.no", used)
            out["reason"] = {"status": "no", "value": None}
            return r
        if ellipsis_ok and rng.random() < 0.4:
            return r
        return pick(rng, REASON_WRAP_EN if E else REASON_WRAP_ES, split, "reason.wrap", used).format(r=r)
    raise ValueError(field)


def style(rng: random.Random, text: str, lang: str) -> tuple[str, str]:
    persona = rng.choices(["plain", "casual", "formal", "emoji", "shouty"], [40, 30, 15, 12, 3])[0]
    if persona == "casual":
        text = text.lower().replace("i'm", "im").replace("you", rng.choice(["you", "u"])) if lang == "en" else text.lower()
        text = text.rstrip(".")
    elif persona == "formal" and lang == "en":
        text = text[0].upper() + text[1:]
        if not text.endswith((".", "?", "!")):
            text += "."
    elif persona == "emoji":
        text += " " + rng.choice(["😊", "🙏", "🏠", "✨", "😅", "👍👍", "🔥"])
    elif persona == "shouty":
        text = text.upper()
    return text, persona


def synth_example(rng: random.Random, split: str, idx: int) -> dict:
    lang = "es" if rng.random() < 0.3 else "en"
    pool = POOLS[split]
    today = dt.date(2026, 8, 1) + dt.timedelta(days=rng.randint(0, 150))
    name = rng.choice(pool["name_en" if lang == "en" else "name_es"])
    room = rng.choice(ROOMS)
    ctx = {"name": name, "room": room, "employer": rng.choice(pool["employer"]), "school": rng.choice(pool["school"]),
           "city": rng.choice(pool["city"])}
    used: list[str] = []
    tags: list[str] = []
    out = empty_output(lang)

    # thread context: optional first renter msg + operator asking some fields
    fields = ["lease", "move_in", "phone", "occupants", "reason"]
    asked = rng.sample(fields, rng.randint(0, 3)) if rng.random() < 0.75 else []
    context = []
    if asked:
        if rng.random() < 0.7:
            context.append({"role": "renter", "text": rng.choice(FIRST_MSG[lang]).format(room=room)})
        q = " ".join(OP_ASK[lang][f] for f in asked)
        context.append({"role": "operator", "text": rng.choice(OP_INTRO[lang]).format(room=room) + q})

    mode = rng.choices(["fields", "intent_only", "small_talk", "mixed"], [45, 15, 10, 30])[0]
    parts: list[str] = []
    intents: list[str] = []
    if mode == "small_talk":
        parts.append(pick(rng, SMALL_TALK[lang], split, "small_talk", used))
        intents.append("small_talk")
        if any(w in parts[0] for w in ("awesome", "nice", "amazing", "amable", "bonitas", "love")):
            tags.append("compliment")
    else:
        if mode in ("fields", "mixed"):
            # answer asked fields with high prob, plus sometimes unasked ones
            if asked and rng.random() < 0.35:  # short reply to one question ("yes", "Nov 1", "2 of us")
                chosen = [rng.choice(asked)]
            else:
                chosen = [f for f in asked if rng.random() < 0.85]
                chosen += [f for f in fields if f not in asked and rng.random() < (0.25 if asked else 0.4)]
            if not chosen:
                chosen = [rng.choice(fields)]
            rng.shuffle(chosen)
            single = len(chosen) == 1
            for f in chosen:
                parts.append(gen_field(rng, f, lang, split, pool, today, ctx, used, tags, out,
                                       ellipsis_ok=single and f in asked))
        if mode in ("intent_only", "mixed"):
            k = 1 if mode == "mixed" or rng.random() < 0.75 else 2
            options = [i for i in INTENTS if i != "small_talk"]
            if mode == "mixed" or k == 2:  # don't pair answers with "stop texting me" / "not until spring"
                options = [i for i in options if i not in ("hard_no", "not_now")]
            for it in rng.sample(options, k):
                if it in ("hard_no", "not_now") and intents:
                    continue
                p = rng.choice(PRICES)
                ictx = {"p": p, "p2": p - rng.choice([25, 50, 75, 100]),
                        "day": rng.choice(WEEKDAYS_EN if lang == "en" else WEEKDAYS_ES),
                        "time": rng.choice(["5", "6pm", "10am", "noon", "3"] if lang == "en" else ["5", "6", "10", "3"]),
                        "month2": (MONTHS_EN if lang == "en" else MONTHS_ES)[(today.month + 1) % 12]}
                parts.append(pick(rng, INTENT_TXT[lang][it], split, f"intent.{it}", used).format(**ictx))
                intents.append(it)
        # a lease "no" usually comes with a shorter-lease ask
        if out["lease"]["status"] == "no" and "shorter_lease" not in intents and rng.random() < 0.5:
            parts.append(pick(rng, INTENT_TXT[lang]["shorter_lease"], split, "intent.shorter_lease", used))
            intents.append("shorter_lease")
            tags.append("lease_no_plus_shorter")

    body = parts[0]
    for p in parts[1:]:
        j = rng.choice(JOIN[lang])
        if body.endswith(("?", "!")) and j.startswith((".", ",", "!")):
            j = " " + j[1:].lstrip() if j[1:].strip() else " "
        body += j + p
    opener = rng.choice(OPENERS[lang]).format(name=name)
    closer = rng.choice(CLOSERS[lang]).format(name=name) if mode != "small_talk" else ""
    if mode == "small_talk":
        opener = ""
    msg, persona = style(rng, opener + body + closer, lang)
    if any(ord(ch) > 0x2600 for ch in msg):
        tags.append("emoji")
    if lang == "es":
        tags.append("spanish")
    if out["move_in"]["raw"]:
        # styling may change case; keep raw an exact span of the final message
        i = msg.lower().find(out["move_in"]["raw"].lower())
        assert i >= 0, (msg, out["move_in"]["raw"])
        out["move_in"]["raw"] = msg[i:i + len(out["move_in"]["raw"])]
    out["intents"] = sorted(set(intents), key=INTENTS.index)
    return {"id": f"syn-{split}-{idx:06d}", "source": "synthetic",
            "input": {"today": today.isoformat(), "context": context, "message": msg},
            "output": out, "meta": {"templates": used, "hard_cases": sorted(set(tags)), "persona": persona}}


# ---------------------------------------------------------------------------
# SGD relabel
# ---------------------------------------------------------------------------
REASON_RE = re.compile(
    r"\b(?:shifting|moving|relocating|transferr?ed|going)\b[^.?!]*?\b(?:for|because of|due to)\s+(?:my\s+|a\s+|the\s+)?"
    r"(work|job|new job|studies|study|school|college|university|family|business|internship|office)\b", re.I)


def sgd_examples() -> dict[str, list[dict]]:
    by_split: dict[str, list[dict]] = collections.defaultdict(list)
    if not SGD_FILE.exists():
        print(f"  SGD file missing ({SGD_FILE}); run download.py first. Skipping SGD.")
        return by_split
    rng = random.Random(11)
    for line in open(SGD_FILE):
        d = json.loads(line)
        split = d["_split"]
        hist: list[dict] = []
        today = dt.date(2026, 8, 1) + dt.timedelta(days=rng.randint(0, 150))
        for ti, t in enumerate(d["turns"]):
            role = "renter" if t["speaker"] == "USER" else "operator"
            if role == "renter":
                acts = [(a["act"], a.get("slot", "")) for f in t["frames"] for a in f["actions"]]
                homes = any(f["service"].startswith("Homes") for f in t["frames"])
                if homes:
                    out = empty_output("en")
                    intents = set()
                    act_names = {a for a, _ in acts}
                    slots = {s for a, s in acts if a == "INFORM"}
                    reqs = {s for a, s in acts if a == "REQUEST"}
                    tags = ["sgd"]
                    if "visit_date" in slots:
                        intents.add("scheduling")
                        tags.append("visit_date_not_move_in")
                    prev = hist[-1]["text"].lower() if hist else ""
                    if act_names & {"AFFIRM_INTENT", "AFFIRM"} and ("visit" in prev or "schedule" in prev):
                        intents.add("scheduling")
                        tags.append("confirms_visit")
                    if reqs:
                        intents.add("question")
                        if "phone_number" in reqs:
                            tags.append("asks_property_phone")
                    if "NEGATE_INTENT" in act_names:
                        intents.add("not_now")
                    content_acts = act_names - {"THANK_YOU", "GOODBYE", "AFFIRM", "NEGATE", "SELECT"}
                    if not content_acts and act_names & {"THANK_YOU", "GOODBYE", "AFFIRM", "SELECT"} and not intents:
                        intents.add("small_talk")
                    m = REASON_RE.search(t["utterance"])
                    if m:
                        out["reason"] = {"status": "answered", "value": f"relocating for {m.group(1).lower()}"}
                        tags.append("sgd_reason")
                    out["intents"] = sorted(intents, key=INTENTS.index)
                    by_split[split].append({
                        "id": f"sgd-{split}-{d['dialogue_id']}-{ti}", "source": "sgd",
                        "input": {"today": today.isoformat(), "context": hist[-4:], "message": t["utterance"]},
                        "output": out,
                        "meta": {"templates": [], "hard_cases": tags, "sgd_acts": sorted(f"{a}:{s}" for a, s in acts)}})
            hist.append({"role": role, "text": t["utterance"]})
    return by_split


# ---------------------------------------------------------------------------
def write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def stats(rows: list[dict]) -> dict:
    s: dict = {"rows": len(rows), "source": collections.Counter(r["source"] for r in rows),
               "language": collections.Counter(r["output"]["language"] for r in rows), "intents": collections.Counter()}
    for f in ["lease", "move_in", "phone", "occupants", "reason"]:
        s[f] = collections.Counter(r["output"][f]["status"] for r in rows)
    for r in rows:
        s["intents"].update(r["output"]["intents"] or ["(none)"])
    s["hard_cases"] = collections.Counter(t for r in rows for t in r["meta"]["hard_cases"])
    return {k: (dict(v.most_common()) if isinstance(v, collections.Counter) else v) for k, v in s.items()}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", type=int, default=12000, help="synthetic train rows")
    ap.add_argument("--dev", type=int, default=800)
    ap.add_argument("--test", type=int, default=1200)
    ap.add_argument("--sgd-train", type=int, default=2000, help="max SGD renter turns in train")
    ap.add_argument("--sgd-eval", type=int, default=300, help="max SGD renter turns in dev and in test")
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()

    sgd = sgd_examples()
    splits: dict[str, list[dict]] = {}
    for split, n, n_sgd, seed_off in [("train", a.train, a.sgd_train, 0), ("dev", a.dev, a.sgd_eval, 1),
                                      ("test", a.test, a.sgd_eval, 2)]:
        rng = random.Random(a.seed * 100 + seed_off)
        rows = [synth_example(rng, split, i) for i in range(n)]
        pool = sgd.get(split, [])
        rng.shuffle(pool)
        rows += pool[:n_sgd]
        rng.shuffle(rows)
        splits[split] = rows

    # leakage guard: no test message string may appear in train/dev
    seen = {r["input"]["message"].lower() for s in ("train", "dev") for r in splits[s]}
    before = len(splits["test"])
    splits["test"] = [r for r in splits["test"] if r["input"]["message"].lower() not in seen]
    print(f"  test: dropped {before - len(splits['test'])} rows whose message also appears in train/dev")

    all_stats = {}
    for split, rows in splits.items():
        write(OUT_PROC / f"{split}.jsonl", rows)
        pub = rows[:PUBLISHED_TRAIN_CAP] if split == "train" else rows
        write(OUT_PUB / f"{split}.jsonl", pub)
        all_stats[split] = stats(rows)
        all_stats[split]["published_rows"] = len(pub)
        print(f"  {split}: {len(rows)} rows (published {len(pub)})")
    (OUT_PUB / "stats.json").write_text(json.dumps(all_stats, indent=1, ensure_ascii=False))
    print(json.dumps({k: {f: v[f] for f in ('lease', 'move_in', 'intents', 'language')} for k, v in all_stats.items()}, indent=1))


if __name__ == "__main__":
    main()
