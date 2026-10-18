"""Step 0 (owner's anonymized export only): choose the threads to mirror and split them per the evaluation
protocol (docs/eval-protocol.md section 2.2).

Relevance (which conversations are leasing / tenant ops / contractor repairs at a rental house):
  * a private relevance file (--relevance, conv id -> category) written from the owner-side exploration
    (work/explore-tenants-sample.json and the contractor exploration's rental-repair list);
  * every candidate in the held-out window is also classified by Lightning (reasoning on), which decides the
    held-out categories and where a leasing thread turns into a tenancy. Agreement with the exploration lists is
    reported.
Only threads with ONE counterpart person qualify (1:1 chats, or lead hand-off groups whose other members are the
owner's partners, mapped to the owner). Russian threads are excluded (the reader covers en/es).

Split (protocol 2.2):
  HELD-OUT = conversations whose first message is on/after --split-date (2026-05-01) and none of whose
             counterpart person ids (people.csv; owner and partners excluded) appear in any earlier conversation
             of the export (tenants, contractors and landlords datasets all count);
  DEV      = relevant conversations that start before the split date;
  dropped  = window conversations that share a person with earlier ones (dropped from BOTH splits).

Writes (private) work/twins/selection.json: conv -> split, category, dataset, tenancy_start; and (public, in
the repo) data/twins/splits.json: sha256 of the held-out conversation-id list and counts only.

Usage: data/twins/.venv/bin/python data/twins/split.py --raw ~/rentus-private-data/raw/anonymized-2026-10-18
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

from common import HERE, LocalLLM, Paths, common_args, pmap, scrub, setup, write_json
from ingest import CYRILLIC, anon_messages, anon_people, anon_role, anon_turn_text

SPLITS_JSON = HERE / "splits.json"
CATS = ("leasing", "leasing_then_tenancy", "tenancy_ops", "contractor", "other")

CLASSIFY_SYSTEM = """You sort anonymized phone-message threads of a small landlord who rents rooms in shared houses.
Lines are numbered; "landlord" is the owner or his team, "other" is the one counterpart.
Categories:
- leasing: the other person asks about renting a room/home from the landlord (availability, price, showing,
  application, lease, deposit, move-in), whatever the outcome, and the thread never turns into living there
- leasing_then_tenancy: it starts as leasing and later the person is a tenant talking about house matters
- tenancy_ops: an existing tenant's matters (repairs, rent or utility payments, house rules, move-out, renewal)
- contractor: a contractor, handyman or service company about repair or maintenance work AT A RENTAL HOUSE the
  landlord rents out (not his own home, not a renovation for a client, not a job applicant or day-labor hiring)
- other: anything else (friends, family, the landlord renting from someone else, house sale, marketing, spam)
tenancy_start: for leasing_then_tenancy, the number of the first line that is about living there; else null.
Return JSON only: {"category": "...", "tenancy_start": <line number or null>}"""


def split_rule(start: dict[str, str], people: dict[str, set[str]], partners: set[str], split_date: str) -> dict[str, str]:
    """Pure protocol-2.2 rule over EVERY conversation: 'heldout' (starts on/after split_date and no counterpart
    person appears in any earlier-starting conversation), 'dev' (starts before), 'dropped' (window conversation
    sharing a person with an earlier one)."""
    early = set()
    for c, s0 in start.items():
        if s0 < split_date:
            early |= people.get(c, set()) - partners
    out = {}
    for c, s0 in start.items():
        if s0 < split_date:
            out[c] = "dev"
        else:
            out[c] = "dropped" if (people.get(c, set()) - partners) & early else "heldout"
    return out


def verify_split(selected: dict[str, str], start, people, partners, split_date) -> dict:
    """Independent re-check of the selected split on the data: every held-out conversation starts in the window and
    shares no counterpart with any conversation that starts earlier; every dev conversation starts earlier."""
    early = {c for c, s0 in start.items() if s0 < split_date}
    v = 0
    for c, sp in selected.items():
        cp = people.get(c, set()) - partners
        if sp == "heldout":
            v += start[c] < split_date or any(cp & (people.get(e, set()) - partners) for e in early)
        elif sp == "dev":
            v += start[c] >= split_date
    return {"heldout_checked": sum(x == "heldout" for x in selected.values()),
            "dev_checked": sum(x == "dev" for x in selected.values()), "violations": int(v)}


def sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def thread_lines(msgs, partners, dataset, limit=90) -> tuple[list[str], int]:
    turns = []
    for m in msgs:
        t = anon_turn_text(m)
        if t is None:
            continue
        role = anon_role(m, partners, dataset)
        turns.append(f"{'landlord' if role == 'owner' else 'other'}: {scrub(t)[0][:240]}")
    n = len(turns)
    idx = list(range(n)) if n <= limit else list(range(60)) + list(range(n - 30, n))
    return [f"[{k}] {turns[k]}" for k in idx], n


def main():
    ap = common_args(argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter))
    ap.add_argument("--raw", required=True, help="the anonymized export dir (raw/anonymized-YYYY-MM-DD)")
    ap.add_argument("--relevance", default=None,
                    help="private JSON {conv: category} from the exploration (default work/twins/relevance.json)")
    ap.add_argument("--split-date", default="2026-05-01")
    a = ap.parse_args()
    setup(a)
    P = Paths.make(False)
    raw = Path(a.raw).expanduser().resolve()
    rel_path = Path(a.relevance) if a.relevance else P.root / "relevance.json"
    relevance = json.loads(rel_path.read_text())
    partners, conv_people = anon_people(raw)
    msgs = anon_messages(raw)
    every = anon_messages(raw, ("tenants", "contractors", "landlords"))
    start = {c: m[0]["ts"][:10] for c, m in every.items() if m}
    for c, ms in every.items():
        conv_people[c] |= {m["sender"] for m in ms if m["sender"] != "me"}
    rule = split_rule(start, conv_people, partners, a.split_date)

    def counterparts(c):
        return conv_people[c] - partners

    def speakers(c):
        return {m["sender"] for m in msgs[c] if m["sender"] != "me" and m["sender"] not in partners}

    def russian(c):
        cp = [m.get("text") or "" for m in msgs[c] if m["sender"] != "me"]
        return sum(bool(CYRILLIC.search(t)) for t in cp) > 0.3 * max(1, len(cp))

    dataset = {c: m[0]["dataset"] for c, m in msgs.items()}
    reasons = Counter()
    candidates = {}
    for c in msgs:
        late = start[c] >= a.split_date
        if not late and c not in relevance:
            continue
        if len(speakers(c)) != 1:
            reasons["not one counterpart"] += 1
            continue
        if russian(c):
            reasons["russian"] += 1
            continue
        if late and rule[c] == "dropped":
            reasons["window thread shares a person with an earlier thread (dropped from both)"] += 1
            continue
        candidates[c] = "heldout" if late else "dev"

    # Lightning classifies every held-out candidate (and gives tenancy_start for leasing threads that become tenancy)
    llm = LocalLLM("operator", P.cache)
    held = sorted(c for c, s in candidates.items() if s == "heldout")

    def classify(c):
        lines, n = thread_lines(msgs[c], partners, dataset[c])
        out = llm.chat_json([{"role": "system", "content": CLASSIFY_SYSTEM}, {"role": "user", "content": "\n".join(lines)}],
                            temperature=0.0, max_tokens=8000, cache_key="split-classify")
        cat = (out or {}).get("category")
        ts = (out or {}).get("tenancy_start")
        return (cat if cat in CATS else None), (ts if isinstance(ts, int) and 0 < ts < n else None)

    got = dict(zip(held, pmap(classify, held, a.workers)))
    llm.require_healthy("split")
    threads, agree = {}, Counter()
    for c, split in sorted(candidates.items()):
        ex = relevance.get(c)
        if split == "heldout":
            cat, ts = got[c]
            if ex:
                agree["same" if (ex == cat or (ex == "leasing" and cat == "leasing_then_tenancy")) else "differ"] += 1
            if dataset[c] == "contractors":
                # contractor threads: the exploration's manual read of every thread decides rental vs not
                cat = "contractor" if ex == "contractor" else "other"
            if cat in (None, "other") or (dataset[c] == "tenants" and cat == "contractor"):
                reasons[f"held-out window, classified {cat}"] += 1
                continue
        else:
            cat, ts = ex, None
        threads[c] = {"split": split, "category": cat, "dataset": dataset[c], "start": start[c], "tenancy_start": ts,
                      "rules_period": start[c] >= "2026-10-04"}
    write_json(P.root / "selection.json", {"split_date": a.split_date, "threads": threads,
                                           "excluded": dict(reasons)})
    held_ids = sorted(c for c, t in threads.items() if t["split"] == "heldout")
    counts = {s: dict(Counter(t["category"] for t in threads.values() if t["split"] == s)) for s in ("heldout", "dev")}
    pub = json.loads(SPLITS_JSON.read_text()) if SPLITS_JSON.exists() else {}
    pub.update({
        "what": "Held-out split of the owner's anonymized threads (eval-protocol 2.2). Hashes and counts only; the "
                "id list stays private. Ids are the export's pseudonymous conversation ids.",
        "split_date": a.split_date,
        "rule": "held-out = conversation starts on/after split_date AND none of its counterpart person ids appears in an "
                "earlier conversation of the export; window conversations sharing a person are dropped from both splits",
        "heldout_conversations": len(held_ids),
        "heldout_conv_ids_sha256": sha("\n".join(held_ids)),
        "heldout_conv_id_sha256_each": sorted(sha(c) for c in held_ids),
        "conversations_by_split_and_category": counts,
        "excluded": dict(reasons),
        "heldout_classifier_vs_exploration": dict(agree),
        "split_rule_check_real_data": verify_split({c: t["split"] for c, t in threads.items()}, start, conv_people,
                                                   partners, a.split_date),
        "split_rule_unit_test": "test_twins.py::test_split_rule (invented person on two channels across the date)",
        "heldout_conversations_starting_on_or_after_2026_10_04": sum(t["rules_period"] for t in threads.values()
                                                                     if t["split"] == "heldout"),
    })
    write_json(SPLITS_JSON, pub)
    print(json.dumps({k: pub[k] for k in ("heldout_conversations", "conversations_by_split_and_category", "excluded",
                                         "heldout_classifier_vs_exploration", "split_rule_check_real_data")}, indent=1))


if __name__ == "__main__":
    sys.exit(main())
