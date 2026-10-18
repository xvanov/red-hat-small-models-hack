"""Step 5: turn filtered twins into published data.

  <published>/twins.jsonl        the twin conversations (synthetic text, gold labels, persona), no link to
                                 any real thread
  <published>/reader_test.jsonl  one reader-schema row per twin renter message (data/reader_schema.md format,
                                 source "twin"): a test set for the reader that mirrors real traffic
  Gym held-out tasks, format v3  (contracts/tools.md §10) = v2 + per counterpart a `persona` and a
                                 `twin_script` for a model-played renter. The v2 `script` (when_asked lines
                                 derived from the twin) is kept, so the current scripted counterparts run
                                 them unchanged. Real mode writes gym/tasks/v3/heldout.jsonl; --fixture
                                 writes fixtures/out/published/gym_tasks_v3.jsonl.

Checks come from the twin's gold labels: the final value of each gate item the renter gave, items the
renter volunteered are not re-asked, and the behaviour the thread calls for (price push escalated with
the rent unchanged, a shorter lease met with the 6-month floor, not-now parked, hard-no closed, a silent
renter not spammed, the gate before a showing).

Usage: data/twins/.venv/bin/python data/twins/to_tasks.py [--fixture] [--limit N]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections import Counter
from datetime import date

from common import FIELDS, REPO, Paths, common_args, hid, read_jsonl, to_context, write_json, write_jsonl

_spec = importlib.util.spec_from_file_location("gym_build_tasks", REPO / "gym" / "build_tasks.py")
_bt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_bt)
PRICE_PROMISES, GENERIC = _bt.PRICE_PROMISES, _bt.GENERIC

INVENTORY = REPO / "data" / "published" / "inventory.json"
CHANNELS = {"messenger": "marketplace", "facebook": "marketplace", "marketplace": "marketplace", "sms": "sms",
            "imessage": "sms", "craigslist": "craigslist", "roomies": "roomies", "padsplit": "padsplit", "email": "email"}
DEVIATION = ("Play this renter. Follow twin_script in order: say each renter turn when the operator's message calls for "
             "it, in the persona's voice. If the operator asks something the script does not cover, answer briefly and "
             "consistently with the persona and with every gold fact (dates, phone, head count, lease answer); never "
             "invent a different value for a gold fact. Stay silent where the script ends if ghosts_after_turn is set.")


def final_gate(twin: dict) -> dict:
    """The last non-absent status/value the renter gave for each gate item."""
    out = {}
    for t in twin["turns"]:
        if t["role"] != "renter":
            continue
        for f in FIELDS:
            if t["gold"][f]["status"] != "absent":
                out[f] = t["gold"][f]
    return out


ACT_ITEM = {"ask_lease": "lease", "ask_move_in": "move_in", "ask_phone": "phone", "ask_occupants": "occupants",
            "ask_reason": "reason", "propose_showing": "showing"}


def items_of(gold: dict) -> list[str]:
    items = [f for f in FIELDS if gold[f]["status"] != "absent"]
    if "scheduling" in gold["intents"]:
        items.append("showing")
    return items


def script_of(twin: dict) -> list[dict]:
    """v2 counterpart lines from the twin. Consecutive renter messages merge into one line, since the
    scripted counterpart answers one operator message with one line."""
    blocks, cur, seen_owner, asked = [], None, False, []
    for t in twin["turns"]:
        if t["role"] == "owner":
            seen_owner = True
            cur = None
            # what the owner just asked: the renter's next line answers it, whatever its labels say
            asked = [ACT_ITEM[x] for x in t.get("acts", []) if x in ACT_ITEM]
            continue
        if cur is None:
            cur = {"start": not seen_owner, "texts": [], "items": list(asked)}
            blocks.append(cur)
        cur["texts"].append(t["text"])
        cur["items"] += [x for x in items_of(t["gold"]) if x not in cur["items"]]
    lines = []
    for b in blocks:
        say = " ".join(b["texts"])
        if b["start"]:
            lines.append({"after": "start", "say": say})
        else:
            w = b["items"] or ["any"]
            lines.append({"when_asked": w[0] if len(w) == 1 else w, "say": say})
    return lines


def subcategory(twin: dict) -> str:
    intents = {i for t in twin["turns"] if t["role"] == "renter" for i in t["gold"]["intents"]}
    last = [t for t in twin["turns"] if t["role"] == "renter"][-1]["gold"]["intents"]
    oc = twin.get("outcome") or {}
    vague = any(t["gold"]["move_in"]["status"] == "vague" for t in twin["turns"] if t["role"] == "renter")
    for name, cond in (("hard_no", "hard_no" in intents), ("not_now", "not_now" in last),
                       ("price_push", "price_negotiation" in intents), ("shorter_lease", "shorter_lease" in intents),
                       ("ghosted", bool(oc.get("ghosted"))), ("language_switch", twin["language_switch"]),
                       ("vague_date", vague), ("spanish", twin["language"] == "es")):
        if cond:
            return name
    return "full"


def pick_room(rooms: list[dict], twin: dict, gate: dict) -> tuple[dict, dict | None]:
    held = [r for k, r in enumerate(rooms) if k % 2 == 1]  # held-out rooms: odd inventory index, as in gym/build_tasks.py
    room = dict(held[int(hid(twin["twin_id"], "room"), 16) % len(held)])
    orig = dict(room)
    move = gate.get("move_in", {}).get("date")
    if move and room["available_from"] > move:
        start = twin["start"][:10]
        first = move[:8] + "01"
        room["available_from"] = max(first, start) if max(first, start) <= move else move
    occ = gate.get("occupants", {}).get("value")
    if occ and occ > (room.get("max_occupants") or 99):
        room["max_occupants"] = occ
    patch = {k: room[k] for k in ("available_from", "max_occupants") if room.get(k) != orig.get(k)}
    return room, ({"room_id": room["room_id"], **patch} if patch else None)


def live_listing(room, ch):
    lid = f"L_{room['room_id']}"
    title = f"{room['type'].title()} in {room['area']}, {'private bath' if room['private_bath'] else 'shared bath'}"
    return {"listing_id": lid, "room_id": room["room_id"], "status": "live", "title": title,
            "body": f"${room['rent']}/month, available {room['available_from']}, 1 year minimum.",
            "price": room["rent"], "channels": {ch: {"post_id": f"P_{room['room_id']}", "status": "live",
                                                     "url": f"sandbox://{ch}/{lid}"}}}


def checks_of(twin: dict, tid: str, room: dict, gate: dict, sub: str) -> list[dict]:
    c = []
    for f, g in gate.items():
        base = f"register[{tid}].gate.{f}"
        st = g["status"]
        if f == "move_in" and st in ("answered", "exception") and g.get("date"):
            c.append({"type": "state", "path": base + ".date", "equals": g["date"], "normalize": "date"})
        elif f == "phone" and st in ("answered", "exception") and g.get("value"):
            c.append({"type": "state", "path": base + ".value", "equals": g["value"], "normalize": "phone"})
        elif f == "reason" and st == "answered":
            c.append({"type": "state", "path": base + ".status", "equals": "answered", "name": "reason recorded as answered"})
        elif f in ("lease", "occupants") and st in ("answered", "exception", "no") and g.get("value") is not None:
            c.append({"type": "state", "path": base + ".value", "equals": g["value"]})
    # items volunteered before the operator spoke must not be asked again
    for t in twin["turns"]:
        if t["role"] == "owner":
            break
        for f in FIELDS:
            if t["gold"][f]["status"] == "answered":
                c.append({"type": "never", "asked": f, "thread": tid, "name": f"does not re-ask {f}"})
    intents = {i for t in twin["turns"] if t["role"] == "renter" for i in t["gold"]["intents"]}
    oc = twin.get("outcome") or {}
    gate_complete = all(gate.get(f, {}).get("status") in ("answered", "exception") for f in FIELDS)
    if "price_negotiation" in intents:
        c += [{"type": "escalated", "expect": True, "name": "price ask escalated"},
              {"type": "state", "path": f"rooms[{room['room_id']}].rent", "equals": room["rent"], "name": "rent unchanged"},
              {"type": "message", "thread": tid, "not_contains": PRICE_PROMISES, "name": "no discount promised"}]
    if "shorter_lease" in intents:
        c.append({"type": "message", "thread": tid, "name": "offers the 6-month floor only",
                  "contains_any": ["6 month", "six month", "6-month", "6 mes", "seis mes"],
                  "not_contains": ["month-to-month is fine", "3 months is fine", "mes a mes está bien"]})
    if sub == "hard_no":
        c += [{"type": "never", "tool": "propose_showing", "name": "no showing proposed"},
              {"type": "state", "path": f"register[{tid}].status", "equals": "lost", "name": "closed as not interested"}]
    elif sub == "not_now":
        c += [{"type": "never", "tool": "propose_showing", "name": "no showing proposed"},
              {"type": "state", "path": f"register[{tid}].status", "equals": "not_now", "name": "kept on file as not now"}]
    else:
        c.append({"type": "never", "tool": "propose_showing", "before": "gate_complete", "thread": tid,
                  "name": "gate before showing"})
        if gate_complete and oc.get("showing"):
            c.append({"type": "tool_called", "tool": "propose_showing", "ok": True, "name": "showing proposed"})
    if oc.get("ghosted"):
        n_owner = sum(t["role"] == "owner" for t in twin["turns"])
        c.append({"type": "tool_called", "tool": "send_message", "ok": True, "args": {"thread_id": tid}, "min": 0,
                  "max": n_owner + 2, "name": "does not spam a silent renter"})
    if not twin["language_switch"]:
        c.append({"type": "style", "rule": "language", "language": twin["language"], "thread": tid, "scope": "sent"})
    c += [{"type": "style", "rule": "first_person", "thread": tid, "scope": "sent"},
          {"type": "tool_called", "tool": "send_message", "ok": False, "args": {"thread_id": tid}, "min": 0, "max": 2,
           "name": "at most 2 refused drafts"},
          {"type": "budget", "max_repeat_failures": 2}]
    return c


def to_task(twin: dict, n: int, rooms: list[dict]) -> dict:
    gate = final_gate(twin)
    sub = subcategory(twin)
    room, patch = pick_room(rooms, twin, gate)
    ch = CHANNELS.get(twin["channel"], "sms")
    slug = "".join(ch_ for ch_ in twin["persona"]["name"].lower() if ch_.isalnum()) or "renter"
    tid = f"t_{slug}_{twin['twin_id'][3:9]}"
    script = script_of(twin)
    lang = twin["turns"][-1].get("gold", {}).get("language") or twin["language"]
    ends_silent = bool((twin.get("outcome") or {}).get("ghosted")) or sub in ("hard_no", "not_now")
    if not ends_silent:
        script.append({"when_asked": "any", "say": GENERIC[lang][1], "reuse": True})
    last_renter = max(t["i"] for t in twin["turns"] if t["role"] == "renter")
    init = {"clock": {"now": twin["start"] + ":00"}, "listings": [live_listing(room, ch)]}
    if patch:
        init["rooms"] = [patch]
    card = dict(twin["persona"])
    persona = (f"{card['name']}, {card.get('age')}, {card.get('occupation') or 'working'} from {card.get('city')}, "
               f"{card.get('state')}. {card.get('summary') or ''}").strip()
    return {
        "id": f"twin-{sub}-heldout-{n:03d}", "split": "heldout", "version": "v3", "category": "leasing",
        "subcategory": f"twin_{sub}", "source": {"kind": "twin", "twin_id": twin["twin_id"]},
        "initial_state": init,
        "counterparts": [{
            "id": f"renter:{slug}", "name": card["name"], "thread_id": tid, "channel": ch, "language": twin["language"],
            "classifier": "v2", "room_of_interest": room["room_id"], "listing_id": f"L_{room['room_id']}",
            "script": script,
            "persona": persona, "persona_card": card,
            **llm_renter_fields(twin, gate, sub, ends_silent),
            "twin_script": {
                "turns": [{"i": t["i"], "role": "renter" if t["role"] == "renter" else "operator", "text": t["text"],
                           "ts": t["ts"], **({"gold": t["gold"]} if t["role"] == "renter" else {"acts": t["acts"]})}
                          for t in twin["turns"]],
                "gold_facts": gate, "phone": twin["phone"],
                "ghosts_after_turn": last_renter if ends_silent else None,
                "ends_with": twin.get("final_stage"), "deviation_policy": DEVIATION}}],
        "faults": [], "max_turns": 30, "checks": checks_of(twin, tid, room, gate, sub),
    }


def llm_renter_fields(twin: dict, gate: dict, sub: str, ends_silent: bool) -> dict:
    """The same twin as fields of gym/rentus_env/llm_renter.py, so setting "mode": "llm_renter" on the
    counterpart runs it with the existing model-played renter (truth sheet + behaviours)."""
    rt = [t for t in twin["turns"] if t["role"] == "renter"]
    first_owner = next((t["i"] for t in twin["turns"] if t["role"] == "owner"), 10 ** 9)
    opening = [t["text"] for t in rt if t["i"] < first_owner]
    truth, beh = {"pets": "none"}, {"max_facts_per_reply": 2}
    if gate.get("move_in", {}).get("date"):
        truth["move_in"] = gate["move_in"]["date"]
        vague = [t for t in rt if t["gold"]["move_in"]["status"] == "vague"]
        if vague and vague[0]["i"] < max(t["i"] for t in rt if t["gold"]["move_in"]["date"]):
            truth["move_in_vague"] = vague[0]["gold"]["move_in"]["raw"] or vague[0]["text"]
            beh["vague_first"] = True
    if gate.get("phone", {}).get("value"):
        truth["phone"] = gate["phone"]["value"]
    if gate.get("occupants", {}).get("value") is not None:
        truth["occupants"] = gate["occupants"]["value"]
        truth["occupants_desc"] = next(t["text"] for t in rt if t["gold"]["occupants"]["status"] != "absent")
    if gate.get("reason", {}).get("status") == "answered":
        truth["reason"] = next(t["text"] for t in reversed(rt) if t["gold"]["reason"]["status"] == "answered")
    short = [t for t in rt if "shorter_lease" in t["gold"]["intents"]]
    lease = gate.get("lease", {})
    if short and lease.get("value") is True:
        truth["lease"], truth["lease_ask"] = "shorter_then_yes", short[0]["text"]
    elif lease.get("value") is False:
        truth["lease"] = "no"
    elif lease.get("value") is True:
        truth["lease"] = "yes"
    price = [t for t in rt if "price_negotiation" in t["gold"]["intents"]]
    if price:
        beh["price_push"] = price[0]["text"]
    beh["ghost_after"] = (len(rt) - len(opening)) if ends_silent else None
    beh["volunteered"] = sorted({f for t in rt if t["i"] < first_owner for f in FIELDS
                                 if t["gold"][f]["status"] == "answered"})
    return {"opening": opening, "truth": truth, "behaviors": beh,
            "simulator": {"temperature": 0.0, "seed": 7, "max_tokens": 300}}


def reader_rows(twin: dict, task_id: str) -> list[dict]:
    rows = []
    for k, t in enumerate(twin["turns"]):
        if t["role"] != "renter":
            continue
        rows.append({"id": f"twin-{twin['twin_id'][3:]}-{t['i']:02d}", "source": "twin",
                     "input": {"today": t["ts"][:10], "context": to_context(twin["turns"][:k])[-8:], "message": t["text"]},
                     "output": t["gold"],
                     "meta": {"twin_id": twin["twin_id"], "turn": t["i"], "difficulty": t.get("difficulty"),
                              "task_id": task_id}})
    return rows


def main():
    ap = common_args(argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter))
    a = ap.parse_args()
    P = Paths.make(a.fixture)
    twins = sorted(read_jsonl(P.work / "twins_filtered.jsonl"), key=lambda t: t["twin_id"])[: a.limit]
    if not twins:
        sys.exit("no filtered twins: run filter.py first")
    rooms = json.loads(INVENTORY.read_text())["rooms"]
    tasks, rrows, pub = [], [], []
    for n, tw in enumerate(twins, 1):
        task = to_task(tw, n, rooms)
        tasks.append(task)
        rrows += reader_rows(tw, task["id"])
        pub.append({k: v for k, v in tw.items() if k not in ("source_thread", "problems", "attempts")})
    write_jsonl(P.published / "twins.jsonl", pub)
    write_jsonl(P.published / "reader_test.jsonl", rrows)
    write_jsonl(P.tasks_out, tasks)
    stats = {"twins": len(pub), "reader_rows": len(rrows), "tasks": len(tasks),
             "by_subcategory": dict(Counter(t["subcategory"] for t in tasks)),
             "checks": sum(len(t["checks"]) for t in tasks),
             "check_types": dict(Counter(c["type"] for t in tasks for c in t["checks"])),
             "languages": dict(Counter(t["counterparts"][0]["language"] for t in tasks)),
             "reader_difficulty": dict(Counter(r["meta"]["difficulty"] for r in rrows)),
             "tasks_file": str(P.tasks_out.relative_to(REPO))}
    write_json(P.published / "tasks_stats.json", stats)
    print(json.dumps(stats, indent=1))


if __name__ == "__main__":
    main()
