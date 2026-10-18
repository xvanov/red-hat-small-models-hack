"""Build the concierge train tasks (gym/tasks/concierge/train.jsonl).

Each task is a normal Gym task (initial_state, counterparts, checks; contracts/tools.md §7, §9) plus:
  "category": "concierge", "operator_config": {"prompt_version": "v4", "tool_descriptions": "concierge"}
  "reference": the privileged reference player's steps (read by reference.py, never shown to a model):
      {"call": tool, "args": {...}, "save"?: {"var": "data.key"}}     args strings may use $var
      {"send_each": "$var"}                                            send_message each text in a saved list
All renters are fictional and scripted; rooms come from data/published/inventory.json (fictional).
Train split only: held-out sets belong to the coordinator.

    python gym/tasks/concierge/build.py && python gym/tasks/concierge/reference.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "tools"))

import rentus_tools as rt  # noqa: E402
from rentus_tools.impl.demand_guards import public_street  # noqa: E402

NOW = "2026-10-17T10:00:00"
CFG = {"prompt_version": "v4", "tool_descriptions": "concierge"}
WORLD = rt.load(patch={"clock": {"now": NOW}})
LEASE_Q = {"en": "How long do you want to stay? Is a one year lease okay with you?",
           "es": "¿Cuánto tiempo quieres quedarte? ¿Te funciona un contrato de un año?"}
COMPLETE_GATE = {"lease": {"status": "answered", "value": True},
                 "move_in": {"status": "answered", "date": "2026-11-01", "raw": "Nov 1"},
                 "phone": {"status": "answered", "value": "+19195550188"},
                 "occupants": {"status": "answered", "value": 1},
                 "reason": {"status": "answered", "value": "new job in Durham"}}


def room(rid):
    return WORLD.get("rooms", rid)


def street(rid):
    return public_street(room(rid)["address"])


def house_no(rid):
    return room(rid)["address"].split()[0]


def listing(rid, status="live"):
    r = room(rid)
    return {"listing_id": f"L_{rid}", "room_id": rid, "status": status, "title": f"Room on {street(rid)}",
            "body": f"${r['rent']} a month, lease 1 year.", "price": r["rent"],
            "channels": {"marketplace": {"post_id": f"P_{rid}", "status": "live" if status == "live" else "removed"}}}


def cp(name, tid, lang, script, rid=None, lid=None, channel="marketplace"):
    out = {"id": f"renter:{name.lower()}", "name": name, "thread_id": tid, "channel": channel, "language": lang,
           "classifier": "v2", "script": script}
    if rid:
        out["room_of_interest"] = rid
    if lid:
        out["listing_id"] = lid
    return out


def style(tid, lang):
    return [{"type": "style", "rule": "first_person", "thread": tid, "scope": "attempted", "name": "first person, every draft"},
            {"type": "style", "rule": "language", "language": lang, "thread": tid, "scope": "sent"},
            {"type": "style", "rule": "max_two_sentences", "thread": tid, "scope": "sent"},
            {"type": "budget", "max_repeat_failures": 2}]


def task(tid_, sub, initial, counterparts, checks, reference, owner=None, max_turns=30):
    t = {"id": f"concierge-{sub}-{tid_}", "split": "train", "version": "concierge-v1", "category": "concierge",
         "subcategory": sub, "operator_config": CFG, "initial_state": {"clock": {"now": NOW}, **initial},
         "counterparts": counterparts, "faults": [], "max_turns": max_turns, "checks": checks, "reference": reference}
    if owner:
        t["owner_instruction"] = owner
    return t


TASKS = []

# ---------------------------------------------------------------- 1. disclosure, house rules, then the gate
for n, (rid, name, lang, opening, extra_ref, extra_checks) in enumerate([
    ("R005", "Amy", "en", "Hi, is the room on Marrowstone St still available?", {}, []),
    ("R023", "Lucia", "es", "Hola, ¿todavía está disponible el cuarto?", {}, []),
    ("R001", "Omar", "en", "Hi! Is it still available? I have a cat, is that ok?", {"pets": "cat"},
     [{"type": "message", "thread": "t_omar", "contains_any": ["cats are okay", "cats ok"]}]),
    ("R012", "Bea", "en", "Hello, I'm interested in the room. Is it available?", {}, []),
], 1):
    tid = f"t_{name.lower()}"
    r = room(rid)
    yes = "Yes, a year works for me." if lang == "en" else "Sí, un año está bien."
    ref = [{"call": "read_thread", "args": {"thread_id": tid}},
           {"call": "capture_demand", "args": {"thread_id": tid, "criteria": {**extra_ref, "language": lang},
                                               "listing_of_interest": f"L_{rid}"}},
           {"call": "listing_disclosure", "args": {"thread_id": tid}, "save": {"msgs": "messages", "rules": "house_rules"}},
           {"send_each": "$msgs", "thread_id": tid}, {"send_each": "$rules", "thread_id": tid},
           {"call": "send_message", "args": {"thread_id": tid, "text": LEASE_Q[lang]}},
           {"call": "read_reply", "args": {"thread_id": tid, "pending_item": "lease"}},
           {"call": "upsert_renter", "args": {"thread_id": tid, "fields": {"gate": {"lease": {"status": "answered", "value": True}}}}}]
    rules_word = "no smoking" if lang == "en" else "no se fuma"
    checks = [{"type": "tool_called", "tool": "capture_demand", "name": "inquiry captured as demand"},
              {"type": "tool_called", "tool": "listing_disclosure"},
              {"type": "never", "tool": "send_message", "before": "tool:listing_disclosure", "name": "disclosure before any reply"},
              {"type": "message", "thread": tid, "contains_all": [f"${r['rent']:,}", street(rid)], "name": "rent and street disclosed"},
              {"type": "message", "thread": tid, "contains_any": [rules_word], "name": "house rules stated"},
              {"type": "message", "thread": tid, "not_contains": [house_no(rid)], "name": "no house number"},
              {"type": "state", "path": f"register[{tid}].demand.listing_of_interest", "equals": f"L_{rid}"},
              {"type": "state", "path": f"register[{tid}].gate.lease.value", "equals": True},
              *extra_checks, *style(tid, lang)]
    TASKS.append(task(f"{n:03d}", "disclosure", {"listings": [listing(rid)]},
                      [cp(name, tid, lang, [{"after": "start", "say": opening}, {"when_asked": "lease", "say": yes}], rid, f"L_{rid}")],
                      checks, ref))

# ---------------------------------------------------------------- 2. asked room filled -> offer other open rooms
for n, (rid, name, lang, area, budget, bath) in enumerate([
    ("R005", "Ken", "en", "Durham", 900, True),
    ("R023", "Rosa", "es", "Raleigh", 800, None),
    ("R012", "Tim", "en", "Durham", 950, True),
], 1):
    tid = f"t_{name.lower()}"
    crit = {"area": area, "budget": budget, **({"private_bath": True} if bath else {}), "language": lang}
    w = rt.load(patch={"clock": {"now": NOW}, "listings": [listing(rid, "filled")],
                       "threads": [{"thread_id": tid, "channel": "marketplace", "renter_name": name, "language": lang,
                                    "listing_id": f"L_{rid}", "messages": [{"from": "renter", "text": "hi"}]}]})
    alts = rt.call(w, "capture_demand", {"thread_id": tid, "criteria": crit})["data"]["alternatives"][:2]
    assert len(alts) == 2, (rid, alts)
    if lang == "en":
        opening = f"Is the {street(rid)} room still available? I'm looking in {area}, up to ${budget}" + \
                  (", with a private bath." if bath else ".")
        offers = [f"The room on {a['street']} in {a['area']} is ${a['rent']:,} a month." for a in alts]
        lead = "Sorry, that room was just taken, but I have two others that fit what you want."
        ask, pick = "Which one interests you?", "The first one sounds good."
    else:
        opening = f"Hola, ¿sigue disponible el cuarto de {street(rid)}? Busco en {area}, máximo ${budget} al mes."
        offers = [f"El cuarto de {a['street']} en {a['area']} cuesta ${a['rent']:,} al mes." for a in alts]
        lead = "Lo siento, ese cuarto ya se rentó, pero tengo otros dos que te pueden servir."
        ask, pick = "¿Cuál te interesa?", "El primero, por favor."
    ref = [{"call": "read_thread", "args": {"thread_id": tid}},
           {"call": "capture_demand", "args": {"thread_id": tid, "criteria": crit}},
           {"call": "send_message", "args": {"thread_id": tid, "text": lead}},
           *[{"call": "send_message", "args": {"thread_id": tid, "text": o}} for o in offers],
           {"call": "send_message", "args": {"thread_id": tid, "text": ask}},
           {"call": "capture_demand", "args": {"thread_id": tid, "listing_of_interest": alts[0]["room_id"]}}]
    checks = [{"type": "tool_called", "tool": "capture_demand", "name": "inquiry captured as demand"},
              {"type": "state", "path": f"register[{tid}].demand.criteria.budget", "equals": budget},
              {"type": "message", "thread": tid, "contains_any": [a["street"] for a in alts], "name": "another open room offered"},
              {"type": "message", "thread": tid, "not_contains": [house_no(a["room_id"]) for a in alts], "name": "no house number"},
              {"type": "state", "path": f"register[{tid}].demand.listing_of_interest", "in": [a["room_id"] for a in alts] +
               [a.get("listing_id") for a in alts if a.get("listing_id")], "name": "pick recorded as listing_of_interest"},
              {"type": "never", "tool": "propose_showing"}, *style(tid, lang)]
    TASKS.append(task(f"{n:03d}", "alternatives", {"listings": [listing(rid, "filled")]},
                      [cp(name, tid, lang, [{"after": "start", "say": opening}, {"when_asked": "other", "say": pick}], rid, f"L_{rid}")],
                      checks, ref))

# ---------------------------------------------------------------- 3. nothing fits -> honest reply + sourcing
for n, (name, lang, crit, opening, honest) in enumerate([
    ("Ivy", "en", {"area": "Apex", "budget": 800, "private_bath": True, "type": "room"},
     "Hi, do you have a room in Apex with a private bathroom? My budget is $800.",
     "I don't have a room in Apex right now, but I've noted what you're looking for and I'll reach out when something fits."),
    ("Mateo", "es", {"area": "Raleigh", "budget": 1400, "type": "apartment"},
     "Hola, busco un apartamento completo en Raleigh, hasta $1400 al mes.",
     "Ahora no tengo apartamentos completos, pero anoté lo que buscas y te aviso cuando tenga algo que te sirva."),
], 1):
    tid = f"t_{name.lower()}"
    w = rt.load(patch={"clock": {"now": NOW}, "threads": [{"thread_id": tid, "channel": "email", "renter_name": name,
                                                            "language": lang, "messages": [{"from": "renter", "text": "hi"}]}]})
    rid_ = rt.call(w, "capture_demand", {"thread_id": tid, "criteria": crit})["data"]["renter_id"]
    leads = rt.call(w, "search_external_rooms", {"renter_id": rid_})["data"]["leads"]
    ref = [{"call": "read_thread", "args": {"thread_id": tid}},
           {"call": "capture_demand", "args": {"thread_id": tid, "criteria": {**crit, "language": lang}}, "save": {"rid": "renter_id"}},
           {"call": "send_message", "args": {"thread_id": tid, "text": honest}},
           {"call": "search_external_rooms", "args": {"renter_id": "$rid"}},
           {"call": "report_to_owner", "args": {"summary": f"{name}: no room fits ({json.dumps(crit)}); sourcing open, "
                                                           f"leads {', '.join(l['ext_id'] for l in leads)}."}}]
    checks = [{"type": "tool_called", "tool": "capture_demand"},
              {"type": "tool_called", "tool": "search_external_rooms", "name": "sourcing opened"},
              {"type": "state", "path": f"register[{tid}].demand.status", "equals": "sourcing"},
              {"type": "state", "path": f"register[{tid}].demand.criteria.budget", "equals": crit["budget"]},
              {"type": "message", "thread": tid, "contains_any": ["noted", "note", "reach out", "let you know", "anoté", "aviso"],
               "name": "honest noted reply"},
              {"type": "message", "thread": tid, "not_contains": [l["street"] for l in leads], "name": "no off-inventory pitch"},
              {"type": "tool_called", "tool": "report_to_owner"}, {"type": "never", "tool": "propose_showing"}, *style(tid, lang)]
    TASKS.append(task(f"{n:03d}", "sourcing", {}, [cp(name, tid, lang, [{"after": "start", "say": opening}], channel="email")],
                      checks, ref))

# ---------------------------------------------------------------- 4. not now -> park with reconnect_at
for n, (name, lang, opening, warm, ask, answer, timeframe, want) in enumerate([
    ("Nina", "en", "Thanks, but I'm not looking until January.",
     "No problem at all, staying in touch is fine.", None, None, "January", "2027-01-01"),
    ("Jorge", "es", "Gracias, pero no busco hasta enero.",
     "No hay problema, con gusto seguimos en contacto.", None, None, "enero", "2027-01-01"),
    ("Sam", "en", "Not looking right now, maybe later.",
     "No problem, staying in touch is fine.", "When do you plan to start looking again?", "Honestly no idea yet.", None, "2026-11-16"),
    ("Paz", "en", "I'm not ready yet, probably next month.",
     "No problem, staying in touch is fine.", None, None, "next month", "2026-11-01"),
], 1):
    tid = f"t_{name.lower()}"
    script = [{"after": "start", "say": opening}]
    if answer:
        script.append({"when_asked": ["move_in", "other"], "say": answer})
    ref = [{"call": "read_thread", "args": {"thread_id": tid}},
           {"call": "capture_demand", "args": {"thread_id": tid, "criteria": {"language": lang}}, "save": {"rid": "renter_id"}},
           {"call": "send_message", "args": {"thread_id": tid, "text": warm}}]
    if ask:
        ref.append({"call": "send_message", "args": {"thread_id": tid, "text": ask}})
    args = {"renter_id": "$rid", "reason": opening}
    if timeframe:
        args["timeframe"] = timeframe
    ref += [{"call": "park_prospect", "args": args},
            {"call": "report_to_owner", "args": {"summary": f"{name} parked until {want}."}}]
    checks = [{"type": "tool_called", "tool": "park_prospect", "name": "parked, not closed"},
              {"type": "state", "path": f"register[{tid}].status", "equals": "not_now"},
              {"type": "state", "path": f"register[{tid}].reconnect_at", "equals": want, "normalize": "date",
               "name": "reconnect_at from their timeframe"},
              {"type": "state", "path": f"register[{tid}].paused_reason", "exists": True},
              {"type": "tool_called", "tool": "report_to_owner"}, {"type": "never", "tool": "propose_showing"}, *style(tid, lang)]
    TASKS.append(task(f"{n:03d}", "park", {"listings": [listing("R005")]},
                      [cp(name, tid, lang, script, "R005", "L_R005")], checks, ref))

# ---------------------------------------------------------------- 5. proposed showing: first person, never "the owner"
for n, (name, lang, opening, reply) in enumerate([
    ("Maria", "en", "Hi again, is my showing on Saturday confirmed?",
     "I've penciled in Saturday at 11 AM and I'll confirm it shortly."),
    ("Elena", "es", "Hola, ¿ya está confirmada mi visita del sábado?",
     "Te propuse el sábado a las 11 y te lo confirmo en breve."),
], 1):
    tid = f"t_{name.lower()}"
    rid_ = f"renter:{name.lower()}"
    init = {"listings": [listing("R023")],
            "register": [{"renter_id": rid_, "thread_ids": [tid], "name": name, "phone": "+19195550188", "gate": COMPLETE_GATE,
                          "wants": {}, "status": "showing_proposed", "listing_of_interest": "L_R023", "language": lang}],
            "calendar": [{"event_id": "E001", "title": f"Showing R023 with {name}", "start": "2026-10-24T11:00",
                          "end": "2026-10-24T11:30", "status": "proposed", "renter_id": rid_, "room_id": "R023"}]}
    ref = [{"call": "read_thread", "args": {"thread_id": tid}}, {"call": "send_message", "args": {"thread_id": tid, "text": reply}}]
    checks = [{"type": "tool_called", "tool": "send_message", "args": {"thread_id": tid}, "name": "renter answered"},
              {"type": "message", "thread": tid, "not_contains": ["owner", "dueño", "landlord"]},
              {"type": "tool_called", "tool": "send_message", "ok": False, "min": 0, "max": 1, "name": "at most 1 refused draft"},
              *style(tid, lang)]
    TASKS.append(task(f"{n:03d}", "first_person", init, [cp(name, tid, lang, [{"after": "start", "say": opening}], "R023", "L_R023")],
                      checks, ref))

# ---------------------------------------------------------------- 6. owner confirmed: tell once + one-hour rule
for n, (name, lang, msgs) in enumerate([
    ("Grace", "en", ["Good news, your showing is confirmed for Saturday, October 24 at 11 AM.",
                     "Please message me by 10 AM that day to confirm you're on your way, otherwise there is no showing."]),
    ("Sofia", "es", ["Buenas noticias, tu visita está confirmada para el sábado 24 de octubre a las 11.",
                     "Por favor escríbeme antes de las 10 de ese día para confirmar que vienes en camino, si no, no hay visita."]),
], 1):
    tid = f"t_{name.lower()}"
    rid_ = f"renter:{name.lower()}"
    init = {"listings": [listing("R023")],
            "threads": [{"thread_id": tid, "channel": "marketplace", "renter_name": name, "language": lang, "listing_id": "L_R023",
                         "messages": [{"from": "renter", "text": "Ok, gracias." if lang == "es" else "Ok, thanks.",
                                       "ts": "2026-10-16T18:00:00"}]}],
            "register": [{"renter_id": rid_, "thread_ids": [tid], "name": name, "phone": "+19195550188", "gate": COMPLETE_GATE,
                          "wants": {}, "status": "showing_confirmed", "listing_of_interest": "L_R023", "language": lang}],
            "calendar": [{"event_id": "E001", "title": f"Showing R023 with {name}", "start": "2026-10-24T11:00",
                          "end": "2026-10-24T11:30", "status": "confirmed", "renter_id": rid_, "room_id": "R023",
                          "decided_by": "owner", "on_the_way_by": "2026-10-24T10:00"}]}
    ref = [{"call": "read_thread", "args": {"thread_id": tid}},
           *[{"call": "send_message", "args": {"thread_id": tid, "text": m}} for m in msgs]]
    checks = [{"type": "message", "thread": tid, "contains_any": ["confirmed", "confirmada"], "name": "told confirmed"},
              {"type": "message", "thread": tid, "contains_any": ["10 AM", "10:00", "one hour", "an hour", "las 10", "una hora"],
               "name": "one-hour-before rule"},
              {"type": "tool_called", "tool": "send_message", "args": {"thread_id": tid}, "min": 2, "max": 3,
               "name": "rule sent as its own message"}, *style(tid, lang)]
    TASKS.append(task(f"{n:03d}", "owner_confirmed", init, [cp(name, tid, lang, [])], checks, ref,
                      owner=f"I confirmed {name}'s showing for Saturday Oct 24 at 11 AM. Let them know."))

# ---------------------------------------------------------------- 7. due follow-ups: reconnect
for n, (name, filled) in enumerate([("Jo", False), ("Lee", True)], 1):
    tid = f"t_{name.lower()}"
    rid_ = f"renter:{name.lower()}"
    demand = {"criteria": {"areas_raw": ["Durham"], "areas": ["Durham"], "budget": 850, "type": None, "private_bath": True,
                           "move_in": None, "move_in_raw": None, "stay_months": None, "occupants": None, "pets": None,
                           "furnished": None, "language": "en"},
              "status": "parked", "listing_of_interest": "L_R005", "interest_history": [],
              "sources": [{"channel": "marketplace", "thread_id": tid, "captured_at": "2026-09-16T10:00:00"}], "proxy": False,
              "sourcing": None, "paused_reason": "not looking until mid October", "reconnect_at": "2026-10-16",
              "followup": {"mode": "reconnect", "kind": "reconnect", "anchor_at": "2026-09-16T10:00:00", "gap_index": 0,
                           "next_checkin_at": "2026-10-16T09:00:00", "checkins_sent": 0, "last_evaluated_at": "2026-09-16T10:00:00"},
              "captured_at": "2026-09-16T10:00:00", "updated_at": "2026-09-16T10:00:00"}
    init = {"listings": [listing("R005", "filled" if filled else "live")],
            "threads": [{"thread_id": tid, "channel": "marketplace", "renter_name": name, "language": "en", "listing_id": "L_R005",
                         "messages": [{"from": "renter", "text": "Not looking until mid October, sorry.", "ts": "2026-09-16T09:50:00"},
                                      {"from": "operator", "text": "No problem, staying in touch is fine.", "ts": "2026-09-16T10:00:00"}]}],
            "register": [{"renter_id": rid_, "thread_ids": [tid], "name": name, "phone": None, "gate": {}, "wants": {"area": "Durham"},
                          "status": "not_now", "listing_of_interest": "L_R005", "language": "en",
                          "paused_reason": "not looking until mid October", "reconnect_at": "2026-10-16", "demand": demand}]}
    text = (f"Hi {name}, we spoke last month and you mentioned looking again around now. Are you starting to look again?" if filled else
            f"Hi {name}, you mentioned looking again around now, and the room on {street('R005')} is still open. Are you starting to look again?")
    ref = [{"call": "due_followups", "args": {}}, {"call": "read_thread", "args": {"thread_id": tid}},
           {"call": "send_message", "args": {"thread_id": tid, "text": text}},
           {"call": "log_followup", "args": {"renter_id": rid_, "event": "reconnect_sent"}},
           {"call": "report_to_owner", "args": {"summary": f"Reconnect sent to {name}."}}]
    checks = [{"type": "tool_called", "tool": "due_followups"},
              {"type": "tool_called", "tool": "log_followup", "args": {"event": "reconnect_sent"}},
              {"type": "state", "path": f"register[{tid}].status", "equals": "qualifying", "name": "back to active"},
              {"type": "message", "thread": tid, "contains_any": ["look"], "name": "one reconnect message"},
              {"type": "tool_called", "tool": "send_message", "args": {"thread_id": tid}, "max": 1, "name": "exactly one reconnect"},
              *style(tid, "en")]
    if filled:
        checks.append({"type": "message", "thread": tid, "not_contains": [street("R005")], "name": "no filled room named"})
    script = [{"when_asked": "other", "say": "Yes, still looking!"}]
    TASKS.append(task(f"{n:03d}", "reconnect", init, [cp(name, tid, "en", script)], checks, ref,
                      owner="Work the follow-ups that are due today."))

# ---------------------------------------------------------------- 8. cluster report: signal vs nominal
for n, (sub, n_q, n_u) in enumerate([("signal", 5, 2), ("nominal", 3, 2)], 1):
    w = rt.load(patch={"clock": {"now": NOW}, "threads": [
        {"thread_id": f"t_c{i}", "channel": ["marketplace", "email", "sms"][i % 3], "renter_name": f"Seeker {i}",
         "language": "en", "messages": [{"from": "renter", "text": "hi"}]} for i in range(n_q + n_u + 2)]})
    for i in range(n_q + n_u + 2):
        crit = ({"area": "near the airport", "budget": 760 + 20 * i, "type": "room", "private_bath": True} if i < n_q + n_u
                else {"area": "Chapel Hill", "budget": 600, "type": "room"})
        rt.call(w, "capture_demand", {"thread_id": f"t_c{i}", "criteria": crit})
        if i < n_q:
            gate = dict(COMPLETE_GATE, phone={"status": "answered", "value": f"+1919555{2000 + i}"})
            rt.call(w, "upsert_renter", {"thread_id": f"t_c{i}", "fields": {"gate": gate}})
    summary = rt.call(w, "cluster_report", {})["data"]["summary"]
    init = {"threads": w.threads, "register": w.register}
    ref = [{"call": "cluster_report", "args": {}, "save": {"summary": "summary"}},
           {"call": "report_to_owner", "args": {"summary": "$summary"}}]
    checks = [{"type": "tool_called", "tool": "cluster_report"}, {"type": "tool_called", "tool": "report_to_owner"},
              {"type": "never", "tool": "send_message", "name": "report goes to the owner only"}]
    if sub == "signal":
        checks.append({"type": "state", "path": "owner_reports", "contains": "SUPPLY SIGNAL", "name": "supply signal reported"})
        checks.append({"type": "state", "path": "owner_reports", "contains": "Morrisville"})
    else:
        checks.append({"type": "state", "path": "owner_reports", "not_contains": "SUPPLY SIGNAL", "name": "nominal five is not a signal"})
        checks.append({"type": "state", "path": "owner_reports", "contains": "nominal"})
    TASKS.append(task(f"{n:03d}", f"cluster_{sub}", init, [], checks, ref, owner="Send me this week's demand report.", max_turns=10))

# ---------------------------------------------------------------- 9. public listing: street only
for n, rid in enumerate(["R005", "R016"], 1):
    r = room(rid)
    title = f"Room on {street(rid)} in {r['area']}, {'private bath' if r['private_bath'] else 'shared bath'}"
    body = f"${r['rent']} a month, deposit ${r['deposit']}. Lease: 1 year."
    ref = [{"call": "get_room", "args": {"room_id": rid}}, {"call": "match_renters", "args": {"room_id": rid}},
           {"call": "check_listing_compliance", "args": {"text": f"{title}\n{body}"}},
           {"call": "create_listing", "args": {"room_id": rid, "title": title, "body": body, "price": r["rent"]},
            "save": {"lid": "listing.listing_id"}},
           {"call": "publish_listing", "args": {"listing_id": "$lid", "channel": "marketplace"}},
           {"call": "report_to_owner", "args": {"summary": "Live on marketplace."}}]
    checks = [{"type": "tool_called", "tool": "publish_listing", "args": {"channel": "marketplace"}},
              {"type": "state", "path": f"listings[{rid}].body", "not_contains": house_no(rid), "name": "no house number in body"},
              {"type": "state", "path": f"listings[{rid}].title", "not_contains": house_no(rid), "name": "no house number in title"},
              {"type": "never", "tool": "publish_listing", "before": "tool:match_renters", "name": "waiting demand checked first"},
              {"type": "tool_called", "tool": "report_to_owner"}]
    TASKS.append(task(f"{n:03d}", "listing_street_only", {}, [], checks, ref, max_turns=15,
                      owner=f"The room at {r['address'].split(',')[0]} (room {rid}) is open. Post it on marketplace."))

# ---------------------------------------------------------------- 10. same person on two channels -> one row
for n, (a, b, phone) in enumerate([("Zoe", "Zoe", "919-555-0177")], 1):
    ta, tb = "t_zoe_fb", "t_zoe_sms"
    ref = [{"call": "read_thread", "args": {"thread_id": ta}},
           {"call": "capture_demand", "args": {"thread_id": ta, "criteria": {"area": "Durham", "budget": 850}, "phone": phone}},
           {"call": "read_thread", "args": {"thread_id": tb}},
           {"call": "capture_demand", "args": {"thread_id": tb, "criteria": {"private_bath": True}, "phone": phone}}]
    checks = [{"type": "state", "path": "register", "count_eq": 1, "name": "one row per person"},
              {"type": "state", "path": f"register[{ta}].demand.sources", "count_eq": 2, "name": "both channels kept"},
              {"type": "state", "path": f"register[{tb}].demand.criteria.private_bath", "equals": True},
              {"type": "state", "path": f"register[{ta}].demand.criteria.budget", "equals": 850}]
    TASKS.append(task(f"{n:03d}", "dedupe", {"listings": [listing("R005")]},
                      [cp(a, ta, "en", [{"after": "start", "say": f"Hi, I'm looking for a room in Durham under $850. My number is {phone}."}]),
                       cp(b, tb, "en", [{"after": "start", "say": f"Hi, it's Zoe from Facebook, {phone}. I'd really like a private bath."}],
                          channel="sms")],
                      checks, ref, owner=None))


def main():
    out = HERE / "train.jsonl"
    with out.open("w") as f:
        for t in TASKS:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    print(f"wrote {len(TASKS)} tasks to {out.relative_to(REPO)}")


if __name__ == "__main__":
    main()
