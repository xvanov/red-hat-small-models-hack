"""Convert scripted leasing tasks to model-played renters (counterpart mode `llm_renter`).

    python gym/llm_renter_tasks.py                 # writes gym/tasks/llm_renter/demo_train.jsonl (6 v2 train tasks)
    python gym/llm_renter_tasks.py --ids a,b --out path.jsonl --seed 7

The source tasks are NOT modified. Each converted task keeps its id (suffixed `-llm`), world, faults and
checks byte for byte; only the counterpart changes. The truth sheet is read from the same expected
values the checks use (move-in date, phone, occupants, lease = yes), so the unchanged scorer checks
the World against the truth sheet. Opening lines are kept verbatim so the first turn is identical to
the scripted task. Persona details are drawn deterministically from the task id.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "tasks" / "v2" / "train.jsonl"
OUT = HERE / "tasks" / "llm_renter" / "demo_train.jsonl"

DEMO_IDS = ["lease-full-train-001", "lease-vague_date-train-001", "lease-spanish-train-001",
            "lease-price_push-train-001", "lease-shorter_lease-train-001", "lease-early_date-train-001"]

JOBS_EN = ["a line cook", "a nursing student", "a warehouse supervisor", "a junior accountant", "a barista",
           "an HVAC apprentice", "a grad student", "a bank teller"]
JOBS_ES = ["cocinero", "estudiante de enfermería", "trabajador de construcción", "asistente dental", "mecánico"]
STYLES_EN = ["texts in short lowercase bursts, sometimes an emoji", "writes complete but brief sentences, polite",
             "terse, skips punctuation, says 'lmk' a lot", "friendly and a little chatty, still brief"]
STYLES_ES = ["escribe mensajes cortos y casuales, a veces con emoji", "educado y breve, sin muchos signos"]
# per-task behaviors on top of what the subcategory implies (ghost_after = patience in replies)
GHOST_AFTER = {"lease-full-train-001": 9}


def pick(pool, key: str, salt: str):
    h = int(hashlib.sha256(f"{key}:{salt}".encode()).hexdigest(), 16)
    return pool[h % len(pool)]


def check_value(task: dict, suffix: str):
    for c in task["checks"]:
        if c.get("type") == "state" and str(c.get("path", "")).endswith(suffix) and "equals" in c:
            return c["equals"]
    return None


def lines(cp: dict, item: str, reuse: bool = False) -> list[str]:
    out = []
    for l in cp["script"]:
        w = l.get("when_asked")
        if (item in w if isinstance(w, list) else w == item) and bool(l.get("reuse")) == reuse:
            out.append(l["say"])
    return out


def convert(task: dict, seed: int = 7) -> dict:
    if task["category"] != "leasing" or len(task.get("counterparts") or []) != 1:
        raise ValueError(f"{task['id']}: only single-renter leasing tasks convert")
    t = json.loads(json.dumps(task))
    cp = t["counterparts"][0]
    sub = t.get("subcategory")
    es = cp.get("language") == "es"
    move_in = check_value(t, ".gate.move_in.date")
    phone = check_value(t, ".gate.phone.value")
    occ = check_value(t, ".gate.occupants.value")
    occ_line = (lines(cp, "occupants") or [""])[0]
    truth = {"move_in": move_in, "phone": phone, "occupants": occ, "occupants_desc": occ_line,
             "reason": (lines(cp, "reason") or ["(you'd rather not say much; something ordinary)"])[0],
             "lease": "yes", "pets": "none"}
    behaviors = {"max_facts_per_reply": 2, "ghost_after": GHOST_AFTER.get(task["id"])}
    openers = [l["say"] for l in cp["script"] if l.get("after") == "start"]
    if sub == "vague_date":
        truth["move_in_vague"] = lines(cp, "move_in")[0]
        behaviors["vague_first"] = True
    if sub == "early_date":
        first = lines(cp, "move_in")[0]
        truth["move_in_first"] = {"date": _early_date(t, cp, move_in), "accept": move_in, "said_as": first}
    if sub == "shorter_lease":
        truth["lease"] = "shorter_then_yes"
        truth["lease_ask"] = lines(cp, "lease")[0]
    if sub == "price_push":
        behaviors["price_push"] = openers[-1]
    job = pick(JOBS_ES if es else JOBS_EN, task["id"], "job")
    style = pick(STYLES_ES if es else STYLES_EN, task["id"], "style")
    persona = (f"{cp['name']}, {job}. " + (f"Escribe en español; {style}." if es else f"Texting style: {style}.") +
               f" Saw the listing on {cp.get('channel')}.")
    new_cp = {k: cp[k] for k in ("id", "name", "thread_id", "channel", "language", "classifier", "room_of_interest",
                                 "listing_id") if k in cp}
    new_cp.update({"mode": "llm_renter", "opening": openers, "persona": persona, "truth": truth, "behaviors": behaviors,
                   "simulator": {"temperature": 0.0, "seed": seed, "max_tokens": 300},
                   "converted_from": {"task": task["id"], "script_lines": len(cp["script"])}})
    t["counterparts"] = [new_cp]
    t["id"] = task["id"] + "-llm"
    t["counterpart_mode"] = "llm_renter"
    return t


def _early_date(task: dict, cp: dict, accept: str) -> str:
    """The renter's first (too early) date. The v2 generator stores it only as the utterance's label, so it is
    recovered from the reader row via the published reader set; if unavailable, 30 days before `accept`."""
    src = next((l.get("src") for l in cp["script"] if l.get("when_asked") == "move_in" and l.get("src")), None)
    if src:
        split = "train" if "-train-" in src else "test"
        f = HERE.parent / "data" / "published" / "reader" / f"{split}.jsonl"
        if f.exists():
            for line in open(f):
                if src in line:
                    row = json.loads(line)
                    if row.get("id") == src:
                        lab = row.get("label") or row.get("output") or {}
                        if isinstance(lab, str):
                            lab = json.loads(lab)
                        d = (lab.get("move_in") or {}).get("date") if isinstance(lab.get("move_in"), dict) else lab.get("move_in_date")
                        if d:
                            return d
    from datetime import date, timedelta
    return (date.fromisoformat(accept) - timedelta(days=30)).isoformat()


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--src", default=str(SRC))
    ap.add_argument("--ids", default=",".join(DEMO_IDS))
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--seed", type=int, default=7, help="simulator seed written into each task")
    a = ap.parse_args()
    by = {json.loads(l)["id"]: json.loads(l) for l in open(a.src)}
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        for i in a.ids.split(","):
            f.write(json.dumps(convert(by[i], a.seed), ensure_ascii=False) + "\n")
    print(f"wrote {out} ({len(a.ids.split(','))} tasks)")


if __name__ == "__main__":
    main()
