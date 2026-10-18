"""Privileged reference policy: plays each task through the real sandbox tools with knowledge of
the task's expected answers. It is NOT a model and is never reported as one. It exists to prove
that every task is solvable under the tools' rules and that the scorer awards a perfect run 1.0
(a task the oracle cannot pass is a broken task).

    python gym/oracle.py --split heldout
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from rentus_env import RolloutSession, verify  # noqa: E402

Q = {"en": {"lease": "How long do you want to stay, is a one year lease okay with you?",
            "move_in": "What is your exact intended move-in date?",
            "phone": "What is the best phone number to reach you about the showing?",
            "reason": "What is the reason you are moving?",
            "occupants": "How many people will live in the room?",
            "showing": "I proposed a showing at {t}, pending confirmation. Does that time work for you?",
            "ack": "Thanks for writing, the room is available.",
            "floor": "The shortest lease I can do is 6 months.",
            "floor_offer": "The shortest lease I can do is a 6-month lease. Would a 6-month lease work for you?",
            "price": "I will check with my partner about the price and get back to you.",
            "close": "Thanks for letting me know, good luck with the search."},
     "es": {"lease": "¿Cuánto tiempo quieres quedarte, te funciona un contrato de un año?",
            "move_in": "¿Cuál es tu fecha exacta de mudanza?",
            "phone": "¿Cuál es tu número de teléfono para coordinar la visita?",
            "reason": "¿Cuál es el motivo de tu mudanza?",
            "occupants": "¿Cuántas personas vivirán en el cuarto?",
            "showing": "Propuse una visita el {t}, pendiente de confirmación. ¿Te funciona esa hora?",
            "ack": "Gracias por escribir, el cuarto está disponible.",
            "floor": "El contrato más corto que puedo ofrecer es de 6 meses.",
            "floor_offer": "El contrato más corto que puedo ofrecer es de 6 meses. ¿Te funciona un contrato de 6 meses?",
            "price": "Voy a consultar el precio y te aviso.",
            "close": "Gracias por avisarme, mucha suerte con la búsqueda."}}
ITEMS = ("lease", "move_in", "phone", "reason", "occupants")


def expected(task, tid):
    out = {}
    for c in task["checks"]:
        p = c.get("path", "")
        if c["type"] == "state" and p.startswith(f"register[{tid}].gate."):
            item = p.split(".")[2]
            out[item] = c.get("equals")
    return out


def lease_task(s: RolloutSession, t: dict):
    cp = t["counterparts"][0]
    tid, lang, sub = cp["thread_id"], cp["language"], t.get("subcategory")
    q = Q[lang]
    s.call("list_threads", {"unanswered_only": True})
    s.call("read_thread", {"thread_id": tid})
    room_id = cp["room_of_interest"]
    s.call("get_room", {"room_id": room_id})
    exp = expected(t, tid)
    if sub in ("not_now", "hard_no"):
        s.call("send_message", {"thread_id": tid, "text": q["ack"]})
        s.call("upsert_renter", {"thread_id": tid, "fields": {"status": "not_now" if sub == "not_now" else "lost"}})
        if sub == "hard_no":
            s.call("send_message", {"thread_id": tid, "text": q["close"]})
        return
    if sub == "price_push":
        s.call("escalate_to_owner", {"reason": "renter asks for a lower price", "ref_id": tid,
                                     "draft": q["price"]})
    script = cp["script"]
    volunteered = {c["asked"] for c in t["checks"] if c["type"] == "never" and "asked" in c}
    gate = {}
    for item in ITEMS:
        if item in volunteered:
            continue
        n_lines = sum(1 for ln in script if ln.get("when_asked") == item and not ln.get("reuse"))
        for k in range(max(1, n_lines)):
            text = q[item]
            if item == "lease" and sub == "shorter_lease" and k == 1 and exp.get("lease") == "answered":
                text = q["floor_offer"]  # D23 (a): the renter will accept 6 months
            elif item == "lease" and sub == "shorter_lease" and k == 1:
                text = q["floor"] + " " + q["lease"].split(", ")[-1].capitalize() if lang == "en" else \
                    q["floor"] + " ¿Te funciona un contrato de un año?"
            r = s.call("send_message", {"thread_id": tid, "text": text})
            if not r.get("ok"):
                print("  send refused:", r["error"], file=sys.stderr)
        last = next((m["text"] for m in reversed(s.transcript) if m["thread_id"] == tid and m["from"] == "renter"), "")
        if item == "move_in":
            gate[item] = {"status": "answered", "date": exp[item], "raw": last[:60]}
        elif item == "reason":
            gate[item] = {"status": "answered", "value": last[:80]}
        elif item == "lease" and exp[item] == "answered":  # accepted 6 months, refused a year (D23)
            gate[item] = {"status": "answered", "value": False, "months": 6}
        else:
            gate[item] = {"status": "answered", "value": exp[item]}
    for item in volunteered:
        if item == "move_in":
            gate[item] = {"status": "answered", "date": exp[item], "raw": None}
        elif item == "reason":
            gate[item] = {"status": "answered", "value": "volunteered"}
        else:
            gate[item] = {"status": "answered", "value": exp[item]}
    r = s.call("upsert_renter", {"thread_id": tid, "fields": {"gate": gate}})
    rid = r["data"]["renter"]["renter_id"]
    today = date.fromisoformat(s.backend.now(s.world)[:10])
    slots = s.call("find_showing_slots", {"room_id": room_id, "date_from": (today + timedelta(days=1)).isoformat(),
                                          "date_to": (today + timedelta(days=7)).isoformat()})
    start = slots["data"]["slots"][0]
    start = start["start"] if isinstance(start, dict) else start
    s.call("propose_showing", {"renter_id": rid, "room_id": room_id, "start": start[:16]})
    s.call("send_message", {"thread_id": tid, "text": q["showing"].format(t=start[:16].replace("T", " "))})


def _room_by_street(s, street):
    rooms = s.call("list_rooms", {})["data"]["rooms"]
    for r in rooms:
        if street.lower() in json.dumps(r).lower():
            return r
    raise LookupError(street)


def listing_task(s: RolloutSession, t: dict):
    instr = t["owner_instruction"]
    checks = t["checks"]
    rid = next(c["path"].split("[")[1].split("]")[0] for c in checks if c.get("path", "").startswith("rooms["))
    price = next(c["equals"] for c in checks if c.get("path", "").endswith(".rent"))
    avail = next(c["equals"] for c in checks if c.get("path", "").endswith(".available_from"))
    chans = [c for c in ("marketplace", "roomies", "craigslist", "padsplit") if c in instr]
    s.call("list_rooms", {})
    room = s.call("get_room", {"room_id": rid})["data"]["room"]
    s.call("update_room", {"room_id": rid, "fields": {"rent": price, "available_from": avail}})
    title = f"{room['type'].title()} in {room['area']}, {'private bath' if room['private_bath'] else 'shared bath'}"
    body = f"${price} a month, available {avail}. 1 year minimum. Deposit ${room['deposit']}."
    s.call("check_listing_compliance", {"text": f"{title}\n{body}"})
    lid = s.call("create_listing", {"room_id": rid, "title": title, "body": body, "price": price})["data"]["listing"]["listing_id"]
    live = []
    for ch in chans:
        r = s.call("publish_listing", {"listing_id": lid, "channel": ch})
        if r.get("ok"):
            live.append(ch)
        else:
            s.call("escalate_to_owner", {"reason": f"publish to {ch} failed: {r['error']['code']} {r['error']['message']}",
                                         "ref_id": lid})
    s.call("report_to_owner", {"summary": f"Listing {lid} is live on {', '.join(live)}."})


def ops_task(s: RolloutSession, t: dict):
    vend = t["initial_state"]["vendors"]["$replace"]
    trade, zip_ = vend[0]["trade"], vend[0]["service_area"][0]
    limit = t["initial_state"]["policy"]["spend_limit_usd"]
    tenant = t["counterparts"][0]["thread_id"]
    rooms = s.call("list_rooms", {})["data"]["rooms"]
    room = next(r for r in rooms if r.get("zip") == zip_ or zip_ in json.dumps(r))
    job = s.call("create_job", {"property": room["room_id"], "issue": t["owner_instruction"][:80], "severity": "medium"})
    jid = job["data"]["job"]["job_id"]
    vs = s.call("find_vendors", {"trade": trade, "zip": zip_})["data"]["vendors"]
    quotes = []
    for v in vs:
        r = s.call("request_quote", {"vendor_id": v["vendor_id"], "job_id": jid, "description": "repair"})
        if not r.get("ok") and r["error"]["code"] == "TIMEOUT" and r["error"].get("retryable"):
            r = s.call("request_quote", {"vendor_id": v["vendor_id"], "job_id": jid, "description": "repair"})
        if r.get("ok"):
            quotes.append(r["data"]["quote"])
    ok = [q for q in quotes if q["amount"] <= limit]
    if ok:
        best = min(ok, key=lambda q: q["amount"])
        s.call("book_vendor", {"quote_id": best["quote_id"]})
        s.call("send_message", {"thread_id": tenant, "text": f"I booked {best['vendor_name']} for {best['eta']}."})
        s.call("report_to_owner", {"summary": f"Booked {best['vendor_name']} at ${best['amount']}."})
    else:
        s.call("escalate_to_owner", {"reason": f"all quotes are above the ${limit} limit", "ref_id": jid,
                                     "draft": json.dumps([[q["vendor_name"], q["amount"]] for q in quotes])})


def malformed_task(s: RolloutSession, t: dict):
    cp = t["counterparts"][0]
    tid, rid = cp["thread_id"], cp["room_of_interest"]
    s.call("read_thread", {"thread_id": tid})
    room = None
    for _ in range(3):
        r = s.call("get_room", {"room_id": rid})
        room = (r.get("data") or {}).get("room")
        if isinstance(room, dict) and isinstance(room.get("rent"), (int, float)) and room.get("deposit") is not None:
            break
    s.call("send_message", {"thread_id": tid, "text": f"Rent is ${room['rent']} a month and the deposit is ${room['deposit']}."})


def task_file(split: str, version: str = "v1") -> Path:
    return HERE / "tasks" / (f"{split}.jsonl" if version == "v1" else f"{version}/{split}.jsonl")


def play(task: dict, backend=None) -> dict:
    s = RolloutSession(task, backend=backend)
    sub = task.get("subcategory")
    if task["category"] == "leasing" or sub == "rate_limited":
        lease_task(s, task)
    elif task["category"] == "listing" or sub in ("page_changed", "login_required"):
        listing_task(s, task)
    elif task["category"] == "ops" or sub == "vendor_timeout":
        ops_task(s, task)
    elif sub == "malformed":
        malformed_task(s, task)
    return verify(task, s.trace, s.final_state())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="heldout")
    ap.add_argument("--id")
    ap.add_argument("--tasks-version", default="v1", choices=["v1", "v2"])
    a = ap.parse_args()
    tasks = [json.loads(l) for l in open(task_file(a.split, a.tasks_version))]
    bad = 0
    for t in tasks:
        if a.id and t["id"] != a.id:
            continue
        try:
            r = play(t)
        except Exception as e:  # noqa: BLE001
            print(f"{t['id']}: ORACLE CRASH {type(e).__name__}: {e}")
            bad += 1
            continue
        if not r["pass"]:
            bad += 1
            fails = [f"{c['name']} ({c['detail']})" for c in r["checks"] if not c["pass"]]
            print(f"{t['id']}: {r['reward']:.2f} FAIL {fails}")
    print(f"oracle: {len(tasks) - bad}/{len(tasks)} tasks pass")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
