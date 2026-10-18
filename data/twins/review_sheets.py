"""Owner review sheets (eval-protocol 7.1 and 7.2). Both hold REAL text, so they are written only to the private
work dir (default ~/rentus-private-data/work/), never to the repo.

  label-spotcheck.md   N random items from both splits, seeded: renter/tenant/vendor messages with the reader's
                       labels and the rule cross-check, plus thread-outcome items (Lightning outcome vs rules),
                       each with blank verdict lines.
  realism-review.md    M blind pairs: one real episode excerpt and one twin of the SAME category, in random order.
  realism-key.json     which side of each pair is real (kept separate so the sheet stays blind).

Twins for the realism sheet come from the DEV split (protocol 7.1: from train); held-out twins are used only if no
dev twins exist, and the sheet says so.

Usage: data/twins/.venv/bin/python data/twins/review_sheets.py [--items 30] [--pairs 20] [--seed 7]
"""
from __future__ import annotations

import argparse
import json
import os
import random
from pathlib import Path

from common import FIELDS, Paths, is_cp, read_jsonl
from label import RULE_FIELDS, RULE_INTENTS, reader_presence


def fmt_labels(lab: dict) -> str:
    parts = []
    for f in FIELDS:
        v = lab[f]
        if v["status"] == "absent":
            continue
        val = v.get("date") if f == "move_in" else v.get("value")
        parts.append(f"{f}={v['status']}" + (f" ({val})" if val not in (None, "") else ""))
    parts.append("intents=" + (",".join(lab["intents"]) or "none"))
    parts.append(f"language={lab['language']}")
    return "; ".join(parts)


def excerpt(turns, n=14, cp_name="them"):
    out = []
    for t in turns[:n]:
        who = "Owner" if t["role"] == "owner" else cp_name
        out.append(f"> **{who}:** {t['text']}")
    if len(turns) > n:
        out.append(f"> *(... {len(turns) - n} more messages)*")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--items", type=int, default=30)
    ap.add_argument("--pairs", type=int, default=20)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default=None, help="private output dir (default $RENTUS_PRIVATE_DIR/work)")
    a = ap.parse_args()
    P = Paths.make(False)
    out = Path(a.out) if a.out else P.root.parent
    rng = random.Random(a.seed)
    labeled = {s: read_jsonl(P.root / s / "labeled.jsonl") for s in ("heldout", "dev")}

    # ---------------------------------------------------------------- 7.2 label spot-check
    msgs, threads = [], []
    for s, ths in labeled.items():
        for th in ths:
            if th.get("category", "leasing") == "leasing" and th.get("rule_outcome"):
                threads.append((s, th))
            for k, t in enumerate(th["turns"]):
                if is_cp(t) and t.get("labels") and not t.get("media"):
                    msgs.append((s, th, k))
    n_thr = min(len(threads), max(1, a.items // 4))
    pick_m = rng.sample(msgs, min(len(msgs), a.items - n_thr))
    pick_t = rng.sample(threads, n_thr)
    L = ["# Label spot-check (PRIVATE: real anonymized text, never commit)", "",
         f"{len(pick_m)} message items and {len(pick_t)} thread-outcome items, seeded ({a.seed}), drawn from both splits.",
         "For each label write **ok**, **wrong** (and the right value) or **can't tell**. Labels come from the "
         "fine-tuned reader (messages) and Lightning with reasoning on (thread outcomes); the rule line is a cheap "
         "regex cross-check. `reason` is scored on status only.", ""]
    for n, (s, th, k) in enumerate(pick_m, 1):
        t = th["turns"][k]
        prev = [x for x in th["turns"][max(0, k - 3):k]]
        rp = reader_presence(t["labels"])
        dis = [x for x in RULE_FIELDS + RULE_INTENTS if rp[x] != t["rule"][x]]
        L += [f"## M{n:02d} ({th.get('category', 'leasing')}, sent {t['ts'][:10]})", ""]
        if prev:
            L += ["Before it:", excerpt(prev, 3, th.get("counterpart", "renter").title()), ""]
        L += [f"**Message:** {t['text']}", "", f"- Reader labels: {fmt_labels(t['labels'])}",
              f"- Rule check disagrees on: {', '.join(dis) or 'nothing'}"
              + ("  (date damaged by the anonymizer: move-in unscorable)" if t.get("unscorable") else ""), "",
              "Verdict per label:", "- lease: ____  - move_in: ____  - phone: ____  - occupants: ____  - reason (status): ____",
              "- intents: ____  - language: ____", ""]
    for n, (s, th) in enumerate(pick_t, 1):
        oc = {k: v for k, v in th["outcome"].items()}
        L += [f"## T{n:02d} (leasing thread, {len(th['turns'])} messages, starts {th['start'][:10]})", "",
              excerpt(th["turns"], 40, "Renter"), "",
              f"- Lightning outcome: {', '.join(k for k, v in oc.items() if v) or 'none'}; final stage: {th['final_stage']}",
              f"- Rule outcome: {', '.join(k for k, v in th['rule_outcome'].items() if v) or 'none'}", "",
              "Verdict: qualified ____  showing ____  applied ____  ghosted ____  no ____  final stage ____", ""]
    (out / "label-spotcheck.md").write_text("\n".join(L), encoding="utf-8")
    os.chmod(out / "label-spotcheck.md", 0o600)

    # ---------------------------------------------------------------- 7.1 realism review
    src = "dev"
    twins = read_jsonl(P.root / "dev" / "twins_filtered.jsonl")
    if not twins:
        src, twins = "heldout", read_jsonl(P.root / "heldout" / "twins_filtered.jsonl")
    by_id = {th["thread_id"]: th for ths in labeled.values() for th in ths}
    real_pool = {}
    for th in labeled[src]:
        real_pool.setdefault(th.get("category", "leasing"), []).append(th)
    twins = [tw for tw in twins if tw["source_thread"] in by_id]
    rng.shuffle(twins)
    pairs, key, used = [], {}, set()
    for tw in twins:
        if len(pairs) >= a.pairs:
            break
        cat = tw.get("category", "leasing")
        # the real side is a DIFFERENT real episode of the same category (not the twin's own source)
        cands = [th for th in real_pool.get(cat, []) if th["thread_id"] not in used and th["thread_id"] != tw["source_thread"]]
        if not cands:
            continue
        real = rng.choice(cands)
        used.add(real["thread_id"])
        pairs.append((cat, real, tw))
    R = ["# Realism review (PRIVATE: contains real anonymized text, never commit)", "",
         f"{len(pairs)} pairs. In each pair one conversation is real (anonymized) and one is a synthetic twin. "
         + ("Twins are from the development split." if src == "dev" else
            "NOTE: no dev twins were available, so these twins come from the HELD-OUT split.") +
         " The answer key is in realism-key.json; don't open it until you're done.", "",
         "For each pair: which one is real (A or B), how sure (1 = guess, 3 = sure), and does the twin sound like your "
         "renters / tenants / contractors (1 = not at all, 5 = exactly).", ""]
    for n, (cat, real, tw) in enumerate(pairs, 1):
        cp = {"leasing": "Renter", "ops": "Tenant", "contractor": "Contractor"}[cat]
        sides = [("real", real["turns"]), ("twin", tw["turns"])]
        rng.shuffle(sides)
        key[f"P{n:02d}"] = {"A": sides[0][0], "B": sides[1][0], "category": cat, "twin_id": tw["twin_id"]}
        R += [f"## P{n:02d} ({cat})", "", "**A**", "", excerpt(sides[0][1], 12, cp), "", "**B**", "",
              excerpt(sides[1][1], 12, cp), "",
              "- Which is real (A/B): ____   - How sure (1-3): ____   - Twin sounds like my people (1-5): ____",
              "- Comment: ____", ""]
    (out / "realism-review.md").write_text("\n".join(R), encoding="utf-8")
    (out / "realism-key.json").write_text(json.dumps({"twin_source_split": src, "pairs": key}, indent=1))
    for f in ("realism-review.md", "realism-key.json"):
        os.chmod(out / f, 0o600)
    print(json.dumps({"spotcheck_messages": len(pick_m), "spotcheck_threads": len(pick_t), "realism_pairs": len(pairs),
                      "realism_twin_split": src, "out": str(out)}))


if __name__ == "__main__":
    main()
