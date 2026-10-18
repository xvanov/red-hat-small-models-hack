"""Maintenance triage and vendor spend (owner decisions D29, playbooks 10 and 13).

triage_maintenance: a safety-emergency screen first, every time (gas, smoke or fire, sparking or a burning
smell, active flooding, sewage backup, no heat in freezing weather, a night lockout, a CO alarm; English and
Spanish). An emergency alerts the owner at once (an open escalation written by the tool itself) and marks
the thread so its next message must be the safety instruction. Anything else gets triage questions, asked
one at a time, before a job.

compare_quotes: every expenditure needs the owner's approval (policy.spend_limit_usd = 0), so the quotes for
a job go to the owner side by side.
"""
from __future__ import annotations

import copy
import re

from ..core import tool
from ..errors import ToolError
from ._util import need

# category -> (pattern, severity, safety message en/es, words the first message must contain)
EMERGENCIES = [
    ("gas", re.compile(r"\bgas (?:smell|leak|odou?r)\b|\bsmell(?:s|ing)? (?:like )?gas\b|\bolor a gas\b|\bhuele a gas\b"
                       r"|\bfuga de gas\b", re.I),
     "Please leave the house now and don't touch any switches or flames. From outside, call the gas company's emergency line.",
     "Por favor sal de la casa ahora y no toques interruptores ni enciendas nada. Desde afuera, llama a la línea de emergencia del gas.",
     ["leave", "get out", "sal de", "salgan", "salir"]),
    ("carbon_monoxide", re.compile(r"\bcarbon monoxide\b|\bco (?:alarm|detector)\b|\bmon[oó]xido\b", re.I),
     "Please get everyone outside now and call 911.",
     "Por favor salgan todos de la casa ahora y llamen al 911.",
     ["911"]),
    ("fire", re.compile(r"\bsmoke\b|\bfire\b|\bflames?\b|\bburning smell\b|\bsmells? (?:like )?burning\b|\bsparks?\b|\bsparking\b"
                        r"|\bhumo\b|\bfuego\b|\bincendio\b|\bllamas\b|\bchispas?\b|\bolor a quemado\b|\bhuele a quemado\b", re.I),
     "Please get out of the house now and call 911.",
     "Por favor sal de la casa ahora y llama al 911.",
     ["911"]),
    ("flooding", re.compile(r"\bflood\w*|\bburst pipe\b|\bpipe (?:burst|broke)\b|\bwater (?:everywhere|pouring|gushing)\b"
                            r"|\binund\w*|\bse (?:revent|romp)i[oó] (?:un|el) (?:tubo|caño)\b|\bagua por todas partes\b", re.I),
     "Please turn off the main water shutoff if you know where it is, and stay away from outlets.",
     "Por favor cierra la llave de paso principal si sabes dónde está, y aléjate de los enchufes.",
     ["shutoff", "shut off", "main water", "llave de paso"]),
    ("sewage", re.compile(r"\bsewage\b|\bsewer (?:back|smell)\w*|\baguas negras\b|\bdrenaje (?:se )?(?:desbord|regres)\w*", re.I),
     "Please stop using the water and the toilets for now.",
     "Por favor dejen de usar el agua y los baños por ahora.",
     ["stop using", "dejen de usar", "no usen"]),
]
NO_HEAT = re.compile(r"\bno heat\b|\bheat(?:er|ing)? (?:is |isn'?t |not |stopped |quit )?(?:not )?working\b|\bheat(?:er)? (?:went out|broke)\b"
                     r"|\bsin calefacci[oó]n\b|\bla calefacci[oó]n no (?:sirve|funciona)\b", re.I)
COLD = re.compile(r"\bfreez\w*|\bbelow (?:32|zero)\b|\bcongel\w*|\bbajo cero\b|\bhelad\w*", re.I)
LOCKOUT = re.compile(r"\blocked out\b|\bcan'?t get (?:in|inside)\b|\bme qued[eé] afuera\b|\bno puedo entrar\b"
                     r"|\bbroken (?:front |back )?(?:door|lock)\b", re.I)

TRADES = [
    ("plumber", "leak", re.compile(r"\bleak\w*|\bdrip\w*|\bgotea\w*|\bfuga\b", re.I),
     ["Where exactly is the water coming from, under the sink, the base of the toilet or the ceiling?",
      "Is it dripping or running?", "Can you send me a photo of where it's coming from?"],
     ["¿De dónde sale el agua exactamente, debajo del lavabo, de la base del inodoro o del techo?",
      "¿Gotea o corre el agua?", "¿Me puedes mandar una foto de dónde sale?"]),
    ("plumber", "clog", re.compile(r"\bclog\w*|\bdrain\w*|\btoilet\b|\bback(?:ed|s)? up\b|\btapad\w*|\binodoro\b|\bbaño no\b", re.I),
     ["Is it one drain or several?", "Have you tried a plunger yet?"],
     ["¿Es un solo desagüe o varios?", "¿Ya probaste con un destapador?"]),
    ("plumber", "hot_water", re.compile(r"\bhot water\b|\bwater heater\b|\bagua caliente\b|\bcalentador\b", re.I),
     ["Is it every tap or just one?", "Is there any water around the heater?", "Can you send me a photo of the heater's label?"],
     ["¿Es en todas las llaves o solo en una?", "¿Hay agua alrededor del calentador?", "¿Me mandas una foto de la etiqueta del calentador?"]),
    ("electrician", "electrical", re.compile(r"\boutlet\w*|\bbreaker\w*|\bno power\b|\blights? (?:out|off|flicker)\w*|\benchufe\w*"
                                             r"|\bbreaker\b|\bsin luz\b|\bse fue la luz\b", re.I),
     ["What exactly stopped working?", "Did a breaker trip in the panel?"],
     ["¿Qué dejó de funcionar exactamente?", "¿Se botó algún breaker en el panel?"]),
    ("hvac", "hvac", re.compile(r"\bac\b|\ba/c\b|\bair condition\w*|\bheat\w*|\bthermostat\b|\baire\b|\bcalefacci[oó]n\b|\btermostato\b", re.I),
     ["What does the thermostat show right now?", "Is any air blowing from the vents?", "Can you send me a photo of the unit's label?"],
     ["¿Qué muestra el termostato ahora?", "¿Sale aire por las rejillas?", "¿Me mandas una foto de la etiqueta del equipo?"]),
    (None, "internet", re.compile(r"\binternet\b|\bwi-?fi\b|\brouter\b", re.I),
     ["Which lights are on on the router?", "Have you tried unplugging it for 30 seconds?"],
     ["¿Qué luces están prendidas en el router?", "¿Ya probaste desconectarlo 30 segundos?"]),
    (None, "lock_door", re.compile(r"\block\b|\bdoor\b|\bkey\b|\bcerradura\b|\bpuerta\b|\bllave\b", re.I),
     ["Can you get in safely right now?", "What exactly is stuck?"],
     ["¿Puedes entrar sin problema ahora mismo?", "¿Qué es exactamente lo que está trabado?"]),
    (None, "appliance", re.compile(r"\bfridge\b|\brefrigerator\b|\bwasher\b|\bdryer\b|\bdishwasher\b|\bstove\b|\boven\b|\bnevera\b"
                                   r"|\brefrigerador\b|\blavadora\b|\bsecadora\b|\bestufa\b|\bhorno\b", re.I),
     ["What does it do, or not do, exactly?", "Can you send me a photo of the model label?"],
     ["¿Qué hace o qué deja de hacer exactamente?", "¿Me mandas una foto de la etiqueta del modelo?"]),
    (None, "pests", re.compile(r"\broach\w*|\bmice\b|\bmouse\b|\brats?\b|\bbugs?\b|\bants\b|\bcucaracha\w*|\bratones?\b|\bplaga\b|\bhormigas\b", re.I),
     ["What kind of pest is it, and where do you see them?", "Can you send me a photo?"],
     ["¿Qué tipo de plaga es y dónde la ves?", "¿Me mandas una foto?"]),
]


def _thread_lang(thread: dict) -> str:
    from .guards import thread_language
    return thread_language(thread) or thread.get("language") or "en"


def classify(text: str, hour: int) -> dict:
    for cat, pat, en, es, must in EMERGENCIES:
        if pat.search(text):
            return {"emergency": True, "category": cat, "en": en, "es": es, "must_any": must}
    if NO_HEAT.search(text) and COLD.search(text):
        return {"emergency": True, "category": "no_heat_freezing",
                "en": "Thanks for telling me right away, I'm arranging help now. Please keep warm in the meantime.",
                "es": "Gracias por avisarme de inmediato, ya estoy consiguiendo ayuda. Mientras tanto, abrígate bien.",
                "must_any": ["arranging help", "consiguiendo ayuda"]}
    if LOCKOUT.search(text) and (hour >= 20 or hour < 7 or re.search(r"\bnight\b|\btonight\b|\bnoche\b", text, re.I)):
        return {"emergency": True, "category": "night_lockout",
                "en": "Your safety comes first, so please wait somewhere safe and well lit. I'm on it now.",
                "es": "Tu seguridad es lo primero, espera en un lugar seguro e iluminado. Ya me estoy ocupando.",
                "must_any": ["safe", "segur"]}
    for trade, issue, pat, qen, qes in TRADES:
        if pat.search(text):
            return {"emergency": False, "trade": trade, "issue": issue, "en": qen, "es": qes}
    return {"emergency": False, "trade": None, "issue": "unknown",
            "en": ["What exactly is happening, and where?", "Can you send me a photo?"],
            "es": ["¿Qué pasa exactamente y dónde?", "¿Me mandas una foto?"]}


@tool("triage_maintenance")
def triage_maintenance(world, thread_id: str, text: str | None = None):
    th = need(world, "threads", thread_id, "thread", "list_threads")
    if text is None:
        text = next((m.get("text") or "" for m in reversed(th.get("messages", [])) if m.get("from") == "renter"), "")
    if not text.strip():
        raise ToolError("INVALID_ARGS", "no tenant message to triage", hint="pass text")
    lang = "es" if _thread_lang(th) == "es" else "en"
    c = classify(text, world.now().hour)
    if c["emergency"]:
        safety = c[lang]
        th["emergency"] = {"category": c["category"], "must_any": c["must_any"], "safety_message": safety,
                           "safety_sent": False, "flagged_at": world.clock["now"]}
        reason = f"SAFETY EMERGENCY: {c['category'].replace('_', ' ')}"
        esc = next((e for e in world.escalations if e.get("ref_id") == thread_id and e.get("reason") == reason
                    and e.get("status") == "open"), None)
        if esc is None:
            esc = {"esc_id": world.next_id("ESC"), "reason": reason, "ref_id": thread_id, "ref_type": "thread_id",
                   "thread_id": thread_id, "draft": f"Tenant report: \"{text[:200]}\". Safety instructions sent first.",
                   "status": "open", "created_at": world.clock["now"], "priority": "immediate", "auto": True}
            world.escalations.append(esc)
        return {"emergency": True, "category": c["category"], "safety_message": safety, "owner_alerted": esc["esc_id"],
                "severity": "emergency",
                "next_step": ("send safety_message NOW as its own message (send_message refuses anything else first); the "
                              "owner is already alerted; then create_job with severity emergency; never promise a repair time")}
    qs = c[lang]
    return {"emergency": False, "trade": c["trade"], "issue": c["issue"], "questions": qs, "next_question": qs[0],
            "next_step": ("acknowledge in a few words and ask next_question (one question per message; skip what they already "
                          "told you); try the safe first fix where there is one; when you know enough, create_job with what was "
                          "tried; quotes go to the owner side by side (every expenditure needs the owner's approval)")}


@tool("compare_quotes")
def compare_quotes(world, job_id: str):
    job = need(world, "jobs", job_id, "job")
    qs = sorted([q for q in world.quotes if q.get("job_id") == job_id], key=lambda q: (q["amount"], q["quote_id"]))
    if not qs:
        raise ToolError("NOT_FOUND", f"no quotes yet for {job_id}", hint="request_quote from vendors found with find_vendors")
    vend = {v["vendor_id"]: v for v in world.vendors}
    rows = []
    for q in qs:
        v = vend.get(q["vendor_id"], {})
        rows.append({"quote_id": q["quote_id"], "vendor_id": q["vendor_id"], "vendor": q.get("vendor_name") or v.get("name"),
                     "amount": q["amount"], "rating": v.get("rating"), "eta": q.get("eta"), "status": q.get("status")})
    side = f"{job_id} ({job.get('issue')}): " + "; ".join(
        f"{r['vendor']} ${r['amount']:,} (rated {r['rating']}, earliest {r['eta']}, {r['quote_id']})" for r in rows)
    side += f". Lowest: {rows[0]['vendor']} at ${rows[0]['amount']:,}. Approve one?"
    return {"job_id": job_id, "quotes": copy.deepcopy(rows), "side_by_side": side,
            "spend_limit_usd": world.policy.get("spend_limit_usd"),
            "next_step": ("every expenditure needs the owner's approval: escalate_to_owner(reason 'vendor quotes for approval', "
                          "ref_id the job_id, draft side_by_side); book_vendor only after the owner approves")}
