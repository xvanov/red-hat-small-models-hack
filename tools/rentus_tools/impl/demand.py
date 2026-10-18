"""Concierge / demand capture tools (docs/spec/concierge.md §1, §3.1, §3.3, §3.7, §3.8, §5).

Every inquiry is demand. The demand record lives on the renter's register row under `demand`
(one row per person, channel agnostic; rows are never deleted):

    demand = {criteria: {areas_raw, areas, budget, type, private_bath, move_in, move_in_raw, stay_months,
                         occupants, pets, furnished, language},
              status: new|contacted|qualifying|qualified|sourcing|parked|applied|placed|closed,
              listing_of_interest, interest_history[], sources[{channel, thread_id, captured_at}], proxy,
              sourcing{opened_at, due_at, results[], outcome}, paused_reason, reconnect_at,
              followup{mode, kind, anchor_at, gap_index, next_checkin_at, checkins_sent, last_evaluated_at},
              captured_at, updated_at}

Tools: listing_disclosure, capture_demand, match_inventory, search_external_rooms, park_prospect,
log_followup, due_followups, cluster_report. Deterministic; tools never read the wall clock.
"""
from __future__ import annotations

import copy
import json
import re
from datetime import date, datetime, timedelta

from ..core import tool
from ..errors import ToolError
from ..world import FIXTURES
from ._util import need, normalize_phone, num
from .demand_guards import public_street
from .demand_match import resolve_areas, room_fit, stated_count
from .register import _floor, gate_missing, upsert_renter

DEMAND_STATUSES = ("new", "contacted", "qualifying", "qualified", "sourcing", "parked", "applied", "placed", "closed")
# register.status -> demand.status (spec §5.2)
FROM_REGISTER = {"new": "new", "qualifying": "qualifying", "qualified": "qualified", "showing_proposed": "qualified",
                 "showing_confirmed": "qualified", "applied": "applied", "leased": "placed", "not_now": "parked",
                 "lost": "closed"}
CRITERIA_KEYS = ("area", "budget", "type", "private_bath", "move_in", "stay_months", "occupants", "pets", "furnished",
                 "language")
CADENCE_HOURS = [12, 12, 12, 12, 24, 24, 48, 96, 192, 384]          # R-APP-3
RECONNECT_CADENCE_HOURS = [48, 96, 192, 384]                       # R-PARK-5
COLD_DAYS = 45

MONTHS = {m: i + 1 for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                          "september", "october", "november", "december"])}
MONTHS.update({m[:3]: i for m, i in list(MONTHS.items())})
MONTHS.update({m: i + 1 for i, m in enumerate(["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
                                               "septiembre", "octubre", "noviembre", "diciembre"])})
MONTHS["sept"] = 9
MONTHS["setiembre"] = 9
MONTH_NAMES_EN = list(MONTHS)[:12]
MONTH_NAMES_ES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
                  "noviembre", "diciembre"]


# ----------------------------------------------------------------------------- helpers

def _row_for_thread(world, thread_id: str) -> dict | None:
    return next((r for r in world.register if thread_id in r.get("thread_ids", [])), None)


def _thread(world, row: dict) -> dict | None:
    for tid in row.get("thread_ids", []):
        t = world.get("threads", tid)
        if t:
            return t
    return None


def _zip_areas(world) -> dict:
    return {r.get("zip"): r.get("area") for r in world.rooms if r.get("zip")}


def _empty_demand(now: str) -> dict:
    return {"criteria": {"areas_raw": [], "areas": [], "budget": None, "type": None, "private_bath": None,
                         "move_in": None, "move_in_raw": None, "stay_months": None, "occupants": None, "pets": None,
                         "furnished": None, "language": None},
            "status": "new", "listing_of_interest": None, "interest_history": [], "sources": [], "proxy": False,
            "sourcing": None, "paused_reason": None, "reconnect_at": None, "followup": None,
            "captured_at": now, "updated_at": now}


def demand_of(world, row: dict) -> dict:
    d = row.get("demand")
    if not isinstance(d, dict):
        d = _empty_demand(world.clock["now"])
        row["demand"] = d
    return d


def sync_status(world, row: dict) -> str:
    """Derive demand.status from the register status (spec §5.2), with sourcing as an overlay on active rows."""
    d = demand_of(world, row)
    reg = row.get("status", "new")
    st = FROM_REGISTER.get(reg, d.get("status") or "new")
    if reg == "escalated":
        st = d.get("status") or "qualifying"
    if st == "new" and any(m.get("from") == "operator" for t in [_thread(world, row)] if t for m in t["messages"]):
        st = "contacted"
    if st == "qualifying" and not gate_missing(row, _floor(world)):
        st = "qualified"
    src = d.get("sourcing") or {}
    if src and not src.get("outcome") and st in ("new", "contacted", "qualifying", "qualified"):
        st = "sourcing"
    d["status"] = st
    return st


def _room_of_interest(world, loi: str | None) -> dict | None:
    if not loi:
        return None
    lst = world.get("listings", loi)
    return world.get("rooms", lst["room_id"]) if lst else world.get("rooms", loi)


def room_available(world, room: dict) -> bool:
    if str(room.get("status", "")).lower() in ("leased", "filled", "off_market", "unavailable"):
        return False
    ls = [l for l in world.listings if l.get("room_id") == room["room_id"]]
    if not ls:
        return True
    return any(l.get("status") in ("live", "draft") for l in ls)


def room_live(world, room_id: str) -> bool:
    return any(l.get("room_id") == room_id and l.get("status") == "live" for l in world.listings)


def _room_card(world, room: dict, score: int | None = None, reasons=None) -> dict:
    out = {"room_id": room["room_id"], "street": public_street(room.get("address", "")), "area": room.get("area"),
           "type": room.get("type"), "rent": room.get("rent"), "private_bath": room.get("private_bath"),
           "available_from": room.get("available_from"), "live_listing": room_live(world, room["room_id"])}
    lst = next((l for l in world.listings if l.get("room_id") == room["room_id"] and l.get("status") == "live"), None)
    if lst:
        out["listing_id"] = lst["listing_id"]
    if score is not None:
        out["score"] = score
        out["reasons"] = reasons or []
    return out


def fits_for(world, row: dict, exclude: set | None = None, limit: int = 5) -> tuple[bool, list[dict], list[dict]]:
    """(matchable, fitting available rooms best first, rejected rooms with the reason)."""
    c = demand_of(world, row)["criteria"]
    if stated_count(c) < 2:
        return False, [], []
    occ = c.get("occupants") or (row.get("gate", {}).get("occupants") or {}).get("value")
    crit = {**c, "occupants": occ}
    fits, rejected = [], []
    for room in world.rooms:
        if exclude and room["room_id"] in exclude:
            continue
        if not room_available(world, room):
            continue
        ok, score, reasons = room_fit(room, crit, _floor(world))
        if ok:
            if room_live(world, room["room_id"]):
                score += 10
                reasons = reasons + ["live listing"]
            fits.append(_room_card(world, room, score, reasons))
        else:
            rejected.append({"room_id": room["room_id"], "reason": reasons[0]})
    fits.sort(key=lambda f: (-f["score"], f["room_id"]))
    return True, fits[:limit], rejected


def _plus_hours(ts: str, hours: float) -> str:
    return (datetime.fromisoformat(ts) + timedelta(hours=hours)).isoformat(timespec="seconds")


def _as_dt(s: str | None, world) -> datetime:
    if not s:
        return world.now()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return datetime.fromisoformat(s + "T09:00:00")
    return datetime.fromisoformat(s)


# ----------------------------------------------------------------------------- timeframe -> reconnect_at

def resolve_timeframe(timeframe: str | None, today: date) -> tuple[date, str]:
    """(reconnect date, how). A named month means the 1st of that month (next occurrence), an exact date is
    that date, 'next month' is the 1st of next month, 'in N weeks/months' adds; nothing usable is +30 days."""
    t = (timeframe or "").strip().lower()
    if not t:
        return today + timedelta(days=30), "default_30_days"
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", t)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3))), "exact_date"
        except ValueError:
            pass
    month_re = "|".join(sorted(MONTHS, key=len, reverse=True))
    m = re.search(rf"\b({month_re})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?:,?\s*(\d{{4}}))?", t) or \
        re.search(rf"\b(\d{{1,2}})\s+(?:de\s+)?({month_re})\b(?:\s+(?:de\s+)?(\d{{4}}))?", t)
    if m:
        a, b, y = m.group(1), m.group(2), m.group(3)
        mon, day = (MONTHS[a], int(b)) if a in MONTHS else (MONTHS[b], int(a))
        year = int(y) if y else today.year
        try:
            d = date(year, mon, day)
            if not y and d <= today:
                d = date(year + 1, mon, day)
            return d, "exact_date"
        except ValueError:
            pass
    m = re.search(rf"\b({month_re})\b(?:\s+(?:de\s+)?(\d{{4}}))?", t)
    if m and not re.search(r"\bmay (?:be|i|we|not)\b", t):
        mon = MONTHS[m.group(1)]
        year = int(m.group(2)) if m.group(2) else today.year
        d = date(year, mon, 1)
        if not m.group(2) and d <= today:
            d = date(year + 1, mon, 1)
        return d, "named_month"
    if re.search(r"\bnext month\b|\bel (?:pr[oó]ximo|siguiente) mes\b|\bel mes que viene\b", t):
        y, mo = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
        return date(y, mo, 1), "next_month"
    if re.search(r"\bnext year\b|\bel (?:pr[oó]ximo )?a[nñ]o (?:que viene|pr[oó]ximo)\b", t):
        return date(today.year + 1, 1, 1), "next_year"
    words = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "six": 6, "un": 1, "una": 1, "dos": 2,
             "tres": 3, "cuatro": 4, "seis": 6, "couple": 2, "few": 3}
    m = re.search(r"\b(?:in|en|dentro de)\s+(?:a\s+)?(\d+|a|an|one|two|three|four|six|un|una|dos|tres|cuatro|seis|couple|few)"
                  r"(?:\s+of)?\s+(days?|d[ií]as?|weeks?|semanas?|months?|meses?)\b", t)
    if m:
        n = int(m.group(1)) if m.group(1).isdigit() else words[m.group(1)]
        unit = m.group(2)
        if unit.startswith(("week", "seman")):
            return today + timedelta(weeks=n), "relative"
        if unit.startswith(("month", "mes")):
            return today + timedelta(days=30 * n), "relative"
        return today + timedelta(days=n), "relative"
    return today + timedelta(days=30), "default_30_days"


# ----------------------------------------------------------------------------- disclosure

# Room types with their articles (EN, ES). "{shared}" is filled only when shared spaces are confirmed.
_TYPE_EN = {"room in house": "a private room in a{shared} house", "room in townhouse": "a private room in a{shared} townhouse",
            "room in duplex": "a private room in a{shared} duplex", "bedroom in house": "a bedroom in a{shared} house",
            "basement suite": "a basement suite in a house", "studio": "a studio", "apartment": "an apartment"}
_TYPE_ES = {"room in house": "un cuarto privado en una casa{shared}",
            "room in townhouse": "un cuarto privado en una casa adosada{shared}",
            "room in duplex": "un cuarto privado en un dúplex{shared}", "bedroom in house": "una habitación en una casa{shared}",
            "basement suite": "un sótano independiente en una casa", "studio": "un estudio", "apartment": "un apartamento"}
_SHARED_EN, _SHARED_ES = " shared", {"casa": " compartida", "casa adosada": " compartida", "dúplex": " compartido"}
DISCLOSURE_MAX_CHARS = 160   # target per message (one SMS segment); never more than 2 sentences (R-STYLE)


def room_kind(room_type: str, lang: str = "en", shared: bool = True) -> str:
    """'bedroom in house' -> 'a bedroom in a house' / 'una habitación en una casa' (articles always present)."""
    t = (room_type or "").strip().lower()
    if lang == "es":
        tpl = _TYPE_ES.get(t)
        if tpl is None:
            return "un cuarto"
        tail = re.search(r"en (?:una|un) ([\wúé ]+)\{shared\}", tpl)
        return tpl.replace("{shared}", _SHARED_ES.get(tail.group(1), "") if (shared and tail) else "")
    tpl = _TYPE_EN.get(t)
    if tpl is None:  # unknown type: add the articles it lacks ("loft in house" -> "a loft in a house")
        tpl = re.sub(r"\b(in|on) (?!a |an |the )", r"\1 a ", t or "room")
        tpl = ("an " if tpl[:1] in "aeiou" else "a ") + tpl
        return tpl
    return tpl.replace("{shared}", _SHARED_EN if shared else "")


def _money(v) -> str:
    f = num(v)
    return f"${f:,.0f}" if f is not None and float(f).is_integer() else f"${f:,.2f}"


def pack_messages(sentences: list[str], max_chars: int = DISCLOSURE_MAX_CHARS) -> list[str]:
    """Greedy: join consecutive sentences into one message while it stays at most 2 sentences and max_chars."""
    out, cur, n = [], "", 0
    for s in sentences:
        s = s.strip()
        if not s:
            continue
        if cur and n < 2 and len(cur) + 1 + len(s) <= max_chars:
            cur, n = f"{cur} {s}", n + 1
        else:
            if cur:
                out.append(cur)
            cur, n = s, 1
    if cur:
        out.append(cur)
    return out


def disclosure_messages(world, room: dict, lang: str = "en") -> dict:
    """Short messages (at most 2 sentences, about 160 characters each) from the room record's CONFIRMED facts
    only (fact_guards.unconfirmed_facts), then the house rules as their own message(s)."""
    from .fact_guards import unconfirmed_facts
    unconf = set(room.get("unconfirmed") or []) | unconfirmed_facts(room)
    street = public_street(room.get("address", ""))
    area = room.get("area", "")
    avail = room.get("available_from")
    now_avail = (not avail) or avail <= world.today()
    es = lang == "es"
    rtype = room.get("type", "")
    shared_ok = "shared_spaces" not in unconf
    kind = room_kind(rtype, lang, shared=shared_ok)
    bath = room.get("private_bath")
    sents = []
    # 1. type, street (never the house number), private bath / entrance, shared spaces
    if es:
        s1 = f"Es {kind} en {street}, {area}"
        feats = []
        if "private_bath" not in unconf and bath is not None:
            feats.append("baño privado" if bath else "baño compartido")
        if room.get("own_entrance") and "own_entrance" not in unconf:
            feats.append("entrada propia")
        if feats:
            s1 += ", con " + " y ".join(feats)
        sents.append(s1 + ".")
        if "room in" in rtype and shared_ok:
            sents.append("La cocina y las áreas comunes son compartidas.")
    else:
        s1 = f"It's {kind} on {street} in {area}"
        feats = []
        if "private_bath" not in unconf and bath is not None:
            feats.append("a private bathroom" if bath else "a shared bathroom")
        if room.get("own_entrance") and "own_entrance" not in unconf:
            feats.append("its own entrance")
        if feats:
            s1 += ", with " + " and ".join(feats)
        sents.append(s1 + ".")
        if "room in" in rtype and shared_ok:
            sents.append("The kitchen and living areas are shared.")
    # 2. rent, deposit, utilities
    util = str(room.get("utilities") or "").lower()
    if "rent" not in unconf and room.get("rent") is not None:
        if es:
            s2 = f"La renta es {_money(room['rent'])} al mes"
            if "deposit" not in unconf and room.get("deposit") is not None:
                s2 += f" y el depósito es {_money(room['deposit'])}"
            sents.append(s2 + ".")
            if "utilities" not in unconf and util:
                sents.append("Los servicios están incluidos." if "included" in util else
                             f"Los servicios son {_money(re.search(r'[0-9.]+', util).group(0))} al mes fijos." if "$" in util else
                             "Los servicios se dividen en partes iguales entre los compañeros.")
        else:
            s2 = f"Rent is {_money(room['rent'])} a month"
            if "deposit" not in unconf and room.get("deposit") is not None:
                s2 += f" and the deposit is {_money(room['deposit'])}"
            sents.append(s2 + ".")
            if "utilities" not in unconf and util:
                sents.append("Utilities are included." if "included" in util else
                             f"Utilities are a flat {_money(re.search(r'[0-9.]+', util).group(0))} a month." if "$" in util else
                             "Utilities are split evenly among the housemates.")
    # 3. availability (never a past date) and the public lease wording, only when the lease is confirmed
    lease_ok = "lease_min_months" not in unconf
    if es:
        when = "ya" if now_avail else f"desde el {int(avail[8:])} de {MONTH_NAMES_ES[int(avail[5:7]) - 1]}"
        sents.append(f"Está disponible {when}, y el contrato es de 1 año." if lease_ok else f"Está disponible {when}.")
    else:
        when = "now" if now_avail else f"from {MONTH_NAMES_EN[int(avail[5:7]) - 1].title()} {int(avail[8:])}"
        sents.append(f"It's available {when}, and the lease is 1 year." if lease_ok else f"It's available {when}.")
    msgs = pack_messages(sents)
    # house rules: smoking, parties, pets (R-PET-1..3), as their own message(s)
    pets = str(room.get("pets") or "").lower()
    pets_unknown = "pets" in unconf or not pets or "unconfirmed" in pets
    rule_sents = []
    if "house_rules" in unconf:
        rule_sents.append("Te confirmo las reglas de la casa y lo de mascotas." if es and pets_unknown else
                          "Te confirmo las reglas de la casa." if es else
                          "I'll confirm the house rules and pet details for you." if pets_unknown else
                          "I'll confirm the house rules for you.")
    else:
        rule_sents.append("Las reglas de la casa: no se fuma adentro y no se permiten fiestas." if es else
                          "House rules: no smoking inside and no parties.")
    if not ("house_rules" in unconf and pets_unknown):
        if es:
            rule_sents.append("Sobre mascotas, te confirmo los detalles." if pets_unknown else
                              "No se permiten mascotas." if pets in ("no", "none") else
                              "Se aceptan gatos y mascotas en jaula o terrario, pero no roedores ni conejos." if "cat" in pets else
                              "Se aceptan perros pequeños y mascotas en jaula o terrario, pero no roedores ni conejos." if "dog" in pets else
                              "Las mascotas se ven caso por caso, cuéntame cuál tienes.")
        else:
            rule_sents.append("On pets, I'll confirm the details for you." if pets_unknown else
                              "No pets, sorry." if pets in ("no", "none") else
                              "Cats are okay, and so are caged or terrarium pets, but no rodents or rabbits." if "cat" in pets else
                              "Small dogs are okay, and so are caged or terrarium pets, but no rodents or rabbits." if "dog" in pets else
                              "Pets are case by case, so tell me about yours.")
    rules = pack_messages(rule_sents)
    return {"room_id": room["room_id"], "language": lang, "messages": msgs, "house_rules": rules,
            "sequence": msgs + rules}


@tool("listing_disclosure")
def listing_disclosure(world, room_id: str | None = None, thread_id: str | None = None):
    from .inbox import thread_room
    from .guards import thread_language
    lang = "en"
    room = None
    if thread_id:
        t = need(world, "threads", thread_id, "thread", "list_threads")
        lang = thread_language(t) or "en"
        room, _ = thread_room(world, t)
    if room_id:
        room = need(world, "rooms", room_id, "room", "list_rooms")
    if room is None:
        raise ToolError("INVALID_ARGS", "listing_disclosure: give room_id, or a thread_id tied to a room",
                        hint="for an ambiguous inquiry, ask which listing first (one short line per live room)")
    out = disclosure_messages(world, room, lang)
    out["next_step"] = ("send each entry of sequence (messages, then house_rules), unchanged, as its own send_message "
                        "(no question in any of them); "
                        "then ask the first missing gate item as the single question in the last message")
    return out


# ----------------------------------------------------------------------------- capture + match

def _norm_criteria(world, raw: dict) -> dict:
    bad = [k for k in raw if k not in CRITERIA_KEYS]
    if bad:
        raise ToolError("INVALID_ARGS", f"capture_demand: unknown criteria {', '.join(bad)}",
                        hint=f"criteria keys: {', '.join(CRITERIA_KEYS)}; leave unstated ones out (never guess)")
    out = {}
    for k, v in raw.items():
        if v in (None, "", []):
            continue
        if k == "area":
            out["areas_raw"] = [str(x) for x in (v if isinstance(v, list) else [v])]
        elif k in ("budget",):
            if num(v) is None or isinstance(v, bool):
                raise ToolError("INVALID_ARGS", "criteria.budget must be a number (USD per month)")
            out[k] = num(v)
        elif k in ("stay_months", "occupants"):
            if isinstance(v, bool) or num(v) is None or num(v) < 1 or int(num(v)) != num(v):
                raise ToolError("INVALID_ARGS", f"criteria.{k} must be a positive whole number")
            out[k] = int(num(v))
        elif k in ("private_bath", "furnished"):
            if not isinstance(v, bool):
                raise ToolError("INVALID_ARGS", f"criteria.{k} must be true or false (leave it out when unstated)")
            out[k] = v
        elif k == "move_in":
            s = str(v)
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
                out["move_in"], out["move_in_raw"] = s, None
            else:
                out["move_in_raw"] = s
        elif k == "language":
            out[k] = str(v)[:2].lower()
        else:
            out[k] = str(v)
    return out


@tool("capture_demand")
def capture_demand(world, thread_id: str, criteria: dict | None = None, listing_of_interest: str | None = None,
                   phone: str | None = None, email: str | None = None, proxy: bool | None = None):
    t = need(world, "threads", thread_id, "thread", "list_threads")
    crit = _norm_criteria(world, criteria or {})
    now = world.clock["now"]
    row = _row_for_thread(world, thread_id)
    merged_from = None
    p = normalize_phone(phone) if phone else None
    if phone and p is None:
        raise ToolError("INVALID_ARGS", f"phone {phone!r} is not a 10-digit US number")
    if row is None and (p or email):   # a second channel for a person already on file: merge into that row
        for r in world.register:
            if (p and (r.get("phone") == p or (r.get("gate", {}).get("phone") or {}).get("value") == p)) or \
                    (email and r.get("email") and r["email"].lower() == email.lower()):
                r.setdefault("thread_ids", []).append(thread_id)
                row, merged_from = r, r["renter_id"]
                break
    created = False
    if row is None:
        res = upsert_renter(world, thread_id, {})
        row, created = _row_for_thread(world, thread_id), res["created"]
    d = demand_of(world, row)
    c = d["criteria"]
    c.update(crit)
    if "areas_raw" in crit:
        c["areas"] = resolve_areas(c["areas_raw"], _zip_areas(world))
    if not c.get("language"):
        c["language"] = t.get("language")
    if proxy is not None:
        d["proxy"] = bool(proxy)
    src = {"channel": t.get("channel"), "thread_id": thread_id}
    if not any(s.get("channel") == src["channel"] and s.get("thread_id") == thread_id for s in d["sources"]):
        d["sources"].append({**src, "captured_at": now})
    loi = listing_of_interest or t.get("listing_id") or t.get("room_id") or row.get("listing_of_interest")
    if loi:
        if not (world.get("listings", loi) or world.get("rooms", loi)):
            raise ToolError("NOT_FOUND", f"listing_of_interest {loi!r} is neither a listing_id nor a room_id")
        if d.get("listing_of_interest") and d["listing_of_interest"] != loi:
            d["interest_history"].append({"listing": d["listing_of_interest"], "until": now})
        d["listing_of_interest"] = loi
        row["listing_of_interest"] = loi
    # mirror into the register's wants so match_renters sees the same criteria
    wants = row.setdefault("wants", {})
    if c.get("areas_raw"):
        wants["area"] = c["areas"][0] if c.get("areas") else c["areas_raw"][0]
    for k in ("budget", "type", "private_bath", "pets"):
        if c.get(k) is not None:
            wants[k] = c[k]
    if c.get("move_in"):
        wants["move_in"] = c["move_in"]
    if p:
        row["phone"] = row.get("phone") or p
    if email:
        row["email"] = row.get("email") or email
    d["updated_at"] = now
    row["updated_at"] = now
    status = sync_status(world, row)

    asked = _room_of_interest(world, d.get("listing_of_interest"))
    matchable, fits, _ = fits_for(world, row, exclude={asked["room_id"]} if asked else None, limit=3)
    out = {"renter_id": row["renter_id"], "created": created, "merged_into": merged_from, "status": status,
           "criteria": copy.deepcopy(c), "stated_criteria": stated_count(c), "matchable": matchable}
    if asked:
        avail = room_available(world, asked)
        ok, _, reasons = room_fit(asked, {**c, "occupants": c.get("occupants")}, _floor(world)) if matchable else (True, 0, [])
        out["asked"] = {**_room_card(world, asked), "available": avail, "fits": bool(ok), "why": reasons}
    out["alternatives"] = fits
    if asked and out["asked"]["available"] and out["asked"]["fits"]:
        out["next_step"] = ("the room they asked about is open: listing_disclosure, send the disclosure and house rules, "
                            "then ask the first missing gate item")
    elif fits:
        why = "is no longer available" if asked and not out["asked"]["available"] else "does not fit what they want" if asked else "was not named"
        out["next_step"] = (f"the room they asked about {why}: offer the alternatives, one short message per room "
                            "(street, area, price, no house number), then one question: which one interests them?")
    elif not matchable:
        out["next_step"] = "fewer than 2 stated criteria: ask for their area or budget (one question), then capture again"
    else:
        out["next_step"] = ("nothing in the inventory fits: send an honest reply that you have noted what they want and "
                            "will reach out when something fits (no pitch), then search_external_rooms to open sourcing")
    return out


@tool("match_inventory")
def match_inventory(world, renter_id: str):
    row = need(world, "register", renter_id, "renter")
    matchable, fits, rejected = fits_for(world, row, limit=10)
    c = demand_of(world, row)["criteria"]
    if not matchable:
        return {"renter_id": renter_id, "matchable": False, "stated_criteria": stated_count(c), "fits": [],
                "hint": "need at least 2 stated criteria (area, budget, type, private bath, move-in, stay, occupants, pets)"}
    return {"renter_id": renter_id, "matchable": True, "stated_criteria": stated_count(c), "fits": fits,
            "rejected": rejected[:8]}


def _external_rooms() -> list[dict]:
    return json.loads((FIXTURES / "demand_external_rooms.json").read_text())["rooms"]


@tool("search_external_rooms")
def search_external_rooms(world, renter_id: str):
    row = need(world, "register", renter_id, "renter")
    d = demand_of(world, row)
    c = d["criteria"]
    occ = c.get("occupants") or (row.get("gate", {}).get("occupants") or {}).get("value")
    hits = []
    for x in _external_rooms():
        ok, score, reasons = room_fit({**x, "room_id": x["ext_id"]}, {**c, "occupants": occ}, _floor(world))
        if ok:
            hits.append({**x, "score": score, "reasons": reasons})
    hits.sort(key=lambda h: (-h["score"], h["ext_id"]))
    days = int(world.policy.get("sourcing_days") or world.policy.get("sourcing_window_days", 7))   # D29: 7 days
    now = world.clock["now"]
    due = _plus_hours(now, 24 * days)
    d["sourcing"] = {"opened_at": now, "due_at": due, "results": [h["ext_id"] for h in hits[:5]], "outcome": None}
    d["followup"] = {"mode": "sourcing", "kind": "sourcing_due", "anchor_at": now, "gap_index": 0,
                     "next_checkin_at": due, "checkins_sent": 0, "last_evaluated_at": now}
    d["updated_at"] = now
    status = sync_status(world, row)
    return {"renter_id": renter_id, "status": status, "sourcing": copy.deepcopy(d["sourcing"]), "leads": hits[:5],
            "next_step": ("these are off-inventory leads for the OWNER only: report_to_owner with them; never offer them to "
                          f"the prospect as your rooms. If nothing comes through by {due[:10]}, park_prospect.")}


# ----------------------------------------------------------------------------- park, follow-ups

@tool("park_prospect")
def park_prospect(world, renter_id: str, reason: str, timeframe: str | None = None):
    row = need(world, "register", renter_id, "renter")
    if not str(reason).strip():
        raise ToolError("INVALID_ARGS", "park_prospect: reason must not be empty", hint="their own words, e.g. 'not looking until January'")
    if row.get("status") in ("lost", "leased"):
        raise ToolError("CONFLICT", f"{renter_id} is {row['status']}; a closed or placed row is not parked",
                        hint="a new inquiry reopens it")
    when, how = resolve_timeframe(timeframe, world.now().date())
    d = demand_of(world, row)
    now = world.clock["now"]
    reconnect_at = when.isoformat()
    row["status"] = "not_now"
    row["paused_reason"] = reason
    row["reconnect_at"] = reconnect_at
    d.update({"paused_reason": reason, "reconnect_at": reconnect_at, "updated_at": now})
    if d.get("sourcing") and not d["sourcing"].get("outcome"):
        d["sourcing"]["outcome"] = "parked"
    d["followup"] = {"mode": "reconnect", "kind": "reconnect", "anchor_at": now, "gap_index": 0,
                     "next_checkin_at": f"{reconnect_at}T09:00:00", "checkins_sent": 0, "last_evaluated_at": now}
    sync_status(world, row)
    return {"renter_id": renter_id, "status": "not_now", "demand_status": d["status"], "reconnect_at": reconnect_at,
            "resolved_from": how, "timeframe": timeframe,
            "next_step": f"report_to_owner once (parked until {reconnect_at}); send the prospect nothing more until then"}


_EVENTS = ("application_sent", "checkin_sent", "reply", "reconnect_sent", "applied", "closed", "placed")


@tool("log_followup")
def log_followup(world, renter_id: str, event: str, note: str | None = None):
    row = need(world, "register", renter_id, "renter")
    if event not in _EVENTS:
        raise ToolError("INVALID_ARGS", f"event must be one of {', '.join(_EVENTS)}")
    d = demand_of(world, row)
    now = world.clock["now"]
    fu = d.get("followup") or {}
    if event == "application_sent":
        row["status"] = "applied"
        fu = {"mode": "application", "kind": "checkin", "anchor_at": now, "gap_index": 0,
              "next_checkin_at": _plus_hours(now, CADENCE_HOURS[0]), "checkins_sent": 0}
    elif event == "checkin_sent":
        if not fu.get("next_checkin_at"):
            raise ToolError("CONFLICT", f"{renter_id} has no follow-up cadence running")
        gaps = RECONNECT_CADENCE_HOURS if fu.get("mode") == "reconnect" else CADENCE_HOURS
        i = int(fu.get("gap_index", 0)) + 1
        gap = gaps[i] if i < len(gaps) else gaps[-1] * 2 ** (i - len(gaps) + 1)
        fu.update({"gap_index": i, "checkins_sent": int(fu.get("checkins_sent", 0)) + 1,
                   "next_checkin_at": _plus_hours(now, gap)})
    elif event == "reply":
        fu.update({"anchor_at": now, "gap_index": 0, "next_checkin_at": _plus_hours(now, 12)})
        fu.setdefault("mode", "application")
        fu["kind"] = "checkin"
    elif event == "reconnect_sent":
        row["status"] = "qualifying" if gate_missing(row, _floor(world)) else "qualified"
        d["reconnect_at"] = None
        fu = {"mode": "reconnect", "kind": "checkin", "anchor_at": now, "gap_index": 0,
              "next_checkin_at": _plus_hours(now, RECONNECT_CADENCE_HOURS[0]), "checkins_sent": 0}
    elif event in ("applied", "closed", "placed"):
        row["status"] = {"applied": "applied", "closed": "lost", "placed": "leased"}[event]
        fu.update({"next_checkin_at": None, "stopped": event, "stopped_at": now})
        if d.get("sourcing") and not d["sourcing"].get("outcome"):
            d["sourcing"]["outcome"] = event
    fu["last_evaluated_at"] = now
    if note:
        fu["note"] = note
    d["followup"] = fu
    d["updated_at"] = now
    row["updated_at"] = now
    status = sync_status(world, row)
    return {"renter_id": renter_id, "status": row["status"], "demand_status": status, "followup": copy.deepcopy(fu)}


@tool("due_followups")
def due_followups(world, now: str | None = None):
    at = _as_dt(now, world) if now else world.now()
    out = []
    for row in world.register:
        d = row.get("demand") or {}
        fu = d.get("followup") or {}
        nxt = fu.get("next_checkin_at")
        if not nxt or row.get("status") in ("lost", "leased"):
            continue
        if datetime.fromisoformat(nxt) > at:
            continue
        kind = fu.get("kind") or "checkin"
        t = _thread(world, row)
        last = t["messages"][-1] if t and t.get("messages") else None
        anchor = fu.get("last_evaluated_at") or fu.get("anchor_at")
        if last and last.get("from") == "renter" and anchor and str(last.get("ts", "")) > anchor:
            kind = "reply_waiting"
        elif fu.get("mode") in ("application", "reconnect") and kind == "checkin" and fu.get("anchor_at") and \
                at - datetime.fromisoformat(fu["anchor_at"]) >= timedelta(days=COLD_DAYS):
            kind = "close_cold"
        item = {"renter_id": row["renter_id"], "kind": kind, "due_at": nxt, "thread_ids": row.get("thread_ids", []),
                "language": (d.get("criteria") or {}).get("language") or row.get("language"),
                "listing_of_interest": d.get("listing_of_interest") or row.get("listing_of_interest"),
                "paused_reason": d.get("paused_reason")}
        room = _room_of_interest(world, item["listing_of_interest"])
        if room:
            item["room_still_available"] = room_available(world, room)
        item["next_step"] = {
            "reconnect": "one short reconnect message: we spoke before, they mentioned looking again around now, are they "
                         "starting to look again? Name the room only if room_still_available; then log_followup reconnect_sent",
            "checkin": "one short first-person check-in ending with 'Are you interested in moving forward?'; then log_followup checkin_sent",
            "sourcing_due": "sourcing window is over: if a lead came through, offer it after the owner approves; otherwise park_prospect",
            "reply_waiting": "the prospect wrote since the last follow-up: handle their message instead of a check-in, then log_followup reply",
            "close_cold": f"{COLD_DAYS} days with no response: stop, log_followup closed (note cold), report_to_owner",
        }[kind]
        out.append(item)
    out.sort(key=lambda x: (x["due_at"], x["renter_id"]))
    return {"now": at.isoformat(timespec="seconds"), "due": out, "count": len(out)}


# ----------------------------------------------------------------------------- clusters

def _band(budget) -> str | None:
    b = num(budget)
    if b is None:
        return None
    lo = int(b // 150) * 150
    return f"${lo} to ${lo + 149}"


def _type_label(c: dict) -> str:
    t = str(c.get("type") or "room").lower()
    base = "whole unit" if re.search(r"apartment|house|home|condo|studio|whole|entire|apartamento|casa", t) and "room" not in t else "room"
    return base + (", private bath" if c.get("private_bath") else "")


@tool("cluster_report")
def cluster_report(world, as_of: str | None = None, min_watch: int = 3, min_signal: int = 5):
    at = _as_dt(as_of, world) if as_of else world.now()
    week_ago = (at - timedelta(days=7)).isoformat(timespec="seconds")
    by_status, by_channel, clusters, seen = {}, {}, {}, {}
    for row in world.register:
        d = row.get("demand")
        if not isinstance(d, dict):
            continue
        st = sync_status(world, row)
        by_status[st] = by_status.get(st, 0) + 1
        for s in d.get("sources", []):
            if s.get("captured_at", "") >= week_ago:
                by_channel[s.get("channel")] = by_channel.get(s.get("channel"), 0) + 1
        if st in ("placed", "closed"):
            continue
        person = row.get("phone") or (row.get("email") or "").lower() or row["renter_id"]
        if person in seen:
            continue
        seen[person] = row["renter_id"]
        c = d.get("criteria") or {}
        area = (c.get("areas") or ["unknown area"])[0]
        band = _band(c.get("budget")) or "no budget stated"
        key = (area, _type_label(c), band)
        cl = clusters.setdefault(key, {"area": area, "type": key[1], "budget_band": band, "people": [], "qualified": []})
        cl["people"].append(row["renter_id"])
        if not gate_missing(row, _floor(world)) and not d.get("proxy") and c.get("budget") is not None:
            cl["qualified"].append(row["renter_id"])
    out_clusters, lines, signals = [], [], []
    for cl in sorted(clusters.values(), key=lambda x: (-len(x["people"]), x["area"], x["type"], x["budget_band"])):
        n, q = len(cl["people"]), len(cl["qualified"])
        if q >= min_signal:
            label = "SUPPLY SIGNAL"
        elif n >= min_signal:
            label = f"nominal {n}, not a signal"
        elif n >= min_watch:
            label = "WATCH"
        else:
            label = None
        cl = {**cl, "count": n, "qualified_count": q, "label": label}
        out_clusters.append(cl)
        if label == "SUPPLY SIGNAL":
            signals.append(cl)
    for cl in signals:
        lines.append(f"SUPPLY SIGNAL: {cl['qualified_count']} qualified people want a {cl['type']} in {cl['area']}, "
                     f"{cl['budget_band']}.")
    lines.append("By status: " + ", ".join(f"{k} {v}" for k, v in sorted(by_status.items())) + ".")
    if by_channel:
        lines.append("New in 7 days by channel: " + ", ".join(f"{k} {v}" for k, v in sorted(by_channel.items())) + ".")
    for cl in out_clusters:
        if cl["label"] in ("WATCH",) or (cl["label"] or "").startswith("nominal"):
            lines.append(f"{cl['label']}: {cl['count']} people, {cl['type']} in {cl['area']}, {cl['budget_band']} "
                         f"({cl['qualified_count']} qualified).")
    return {"as_of": at.isoformat(timespec="seconds"), "clusters": [c for c in out_clusters if c["label"]],
            "supply_signals": signals, "by_status": by_status, "new_by_channel": by_channel,
            "summary": "\n".join(lines)}
