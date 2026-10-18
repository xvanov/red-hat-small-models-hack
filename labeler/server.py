"""Blind owner labeler for the twin reader test (eval-protocol Amendment 1, A1a).

    labeler/.venv/bin/python labeler/server.py [--source auto|real|fixture] [--port 8090]

Shows one renter message at a time (last 1-2 context lines + the message + "today"), never any
model's label, and saves the owner's label for each item to labeler/out/.

Sample (A1a): all renter rows of a simple random sample of twin threads, seed 0, added thread by thread
until at least 71 rows (Amendment 5; was 150). The draw is `random.Random(0).sample(sorted(set(twin_ids)), k)` (the same
procedure as gym/stats.py `simple_random_sample`) taken over every thread, so the thread order is a
seeded permutation and the sample is its shortest prefix holding >= 71 rows. It is written once to a
manifest and reused on every restart; it is never redrawn unless the manifest is deleted.

Sources and modes (never mixed):
  real     data/published/twins/reader_test.jsonl  -> sample_manifest.json,         out/owner_labels.jsonl
  fixture  data/twins/fixtures/out/published/reader_test.jsonl
                                                   -> sample_manifest.fixture.json, out/owner_labels.fixture.jsonl
  auto     real once it is finished (its sha256 matches data/twins/splits.json `frozen_sha256`, which
           to_tasks.py writes after the file) or once a real manifest exists; fixture until then.
           Checked on every request, so the page switches by itself when the real set lands.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
REAL_SRC = REPO / "data/published/twins/reader_test.jsonl"
FIXTURE_SRC = REPO / "data/twins/fixtures/out/published/reader_test.jsonl"
SPLITS = REPO / "data/twins/splits.json"
OUT = Path(os.environ.get("LABELER_OUT") or HERE / "out").resolve()   # tests point this at a copy
SEED = 0
MIN_ROWS = 71   # eval-protocol Amendment 5 (owner time constraint); the 29-row fixture pilot keeps its own manifest

MODES = {
    "real": {"src": REAL_SRC, "manifest": HERE / "sample_manifest.json", "labels": OUT / "owner_labels.jsonl"},
    "fixture": {"src": FIXTURE_SRC, "manifest": HERE / "sample_manifest.fixture.json",
                "labels": OUT / "owner_labels.fixture.jsonl"},
}

LOCK = threading.Lock()
ARGS = argparse.Namespace(source="auto")


# ---------------------------------------------------------------- sample

def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def read_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


def write_json_atomic(p: Path, obj) -> None:
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")
    os.replace(tmp, p)


def thread_of(row: dict) -> str:
    return (row.get("meta") or {}).get("twin_id") or row["id"]


def draw_sample(rows: list[dict]) -> tuple[list[str], list[str]]:
    by_thread: dict[str, list[dict]] = {}
    for r in rows:
        by_thread.setdefault(thread_of(r), []).append(r)
    pool = sorted(by_thread)
    order = random.Random(SEED).sample(pool, len(pool))
    threads, ids = [], []
    for t in order:
        if len(ids) >= MIN_ROWS:
            break
        threads.append(t)
        turn = lambda r: ((r.get("meta") or {}).get("turn", 0), r["id"])
        ids += [r["id"] for r in sorted(by_thread[t], key=turn)]
    return threads, ids


def ids_sha(ids: list[str]) -> str:
    return hashlib.sha256("\n".join(ids).encode()).hexdigest()


def real_ready() -> tuple[bool, str]:
    if MODES["real"]["manifest"].exists():
        return True, "real sample manifest exists"
    if not REAL_SRC.exists():
        return False, "real twin set not written yet"
    try:
        frozen = json.loads(SPLITS.read_text()).get("heldout", {}).get("frozen_sha256", {})
    except (OSError, ValueError):
        frozen = {}
    want = frozen.get(str(REAL_SRC.relative_to(REPO)))
    if not want:
        # to_tasks may nest it differently; search every frozen_sha256 dict in splits.json
        try:
            txt = SPLITS.read_text()
            want = next((v for k, v in re.findall(r'"([^"]*reader_test\.jsonl)":\s*"([0-9a-f]{64})"', txt)
                         if k == str(REAL_SRC.relative_to(REPO))), None)
        except OSError:
            want = None
    if not want:
        return False, "real twin set exists but is not frozen in data/twins/splits.json yet (still being produced)"
    if want != sha256_file(REAL_SRC):
        return False, "real twin set does not match its frozen sha256 yet (still being written)"
    return True, "real twin set is frozen"


def current_mode() -> tuple[str, str]:
    if ARGS.source in MODES:
        return ARGS.source, f"--source {ARGS.source}"
    ok, why = real_ready()
    return ("real" if ok else "fixture"), why


_cache: dict[str, dict] = {}


def load(mode: str) -> dict:
    cfg = MODES[mode]
    src, man_p = cfg["src"], cfg["manifest"]
    key = f"{mode}:{src.stat().st_mtime_ns if src.exists() else 0}:{man_p.exists()}"
    if mode in _cache and _cache[mode]["key"] == key:
        return _cache[mode]
    if not src.exists():
        raise HTTPException(500, f"source file missing: {src.relative_to(REPO)}")
    rows = read_jsonl(src)
    by_id = {r["id"]: r for r in rows}
    src_sha = sha256_file(src)
    warning = None
    if man_p.exists():
        man = json.loads(man_p.read_text())
        if man.get("source_sha256") != src_sha:
            warning = "source file changed since the sample was drawn; the sample is kept as recorded"
        missing = [i for i in man["row_ids"] if i not in by_id]
        if missing:
            raise HTTPException(500, f"{len(missing)} sampled ids are missing from {src.name}; refusing to mix samples")
    else:
        threads, ids = draw_sample(rows)
        man = {
            "mode": mode,
            "source": str(src.relative_to(REPO)),
            "source_sha256": src_sha,
            "source_rows": len(rows),
            "method": "eval-protocol Amendment 1 A1a: simple random sample of twin threads "
                      "(random.Random(0).sample(sorted twin ids, all)), all renter rows of each thread, "
                      f"threads added in that order until >= {MIN_ROWS} rows",
            "seed": SEED,
            "min_rows": MIN_ROWS,
            "n_threads": len(threads),
            "n_rows": len(ids),
            "twin_ids": threads,
            "row_ids": ids,
            "row_ids_sha256": ids_sha(ids),
            "created_at": now(),
        }
        write_json_atomic(man_p, man)
    assert ids_sha(man["row_ids"]) == man["row_ids_sha256"], "manifest id list does not match its sha256"
    st = {"key": key, "mode": mode, "manifest": man, "by_id": by_id, "warning": warning}
    _cache[mode] = st
    return st


# ---------------------------------------------------------------- labels

def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def log_path(mode: str) -> Path:
    return OUT / f"labels_log.{mode}.jsonl"


def append_log(mode: str, rec: dict) -> None:
    """Append-only: every save, audit change and undo is a new line; nothing is ever rewritten or deleted."""
    OUT.mkdir(exist_ok=True)
    with open(log_path(mode), "a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


def read_log(mode: str) -> list[dict]:
    """The append-only label log. Seeded once from the pre-log snapshot file (labels saved before the log
    existed), so those saves are kept as the first version of each item."""
    lp = log_path(mode)
    if not lp.exists():
        old = read_jsonl(MODES[mode]["labels"])
        for r in sorted(old, key=lambda r: r.get("ts") or ""):
            append_log(mode, {**r, "event": "save", "save_reason": "imported_pre_log"})
    recs = read_jsonl(lp)
    for k, r in enumerate(recs):
        r["seq"] = k
    return recs


def effective(recs: list[dict]) -> tuple[dict[str, dict], dict[str, list[dict]]]:
    """Latest non-undone save per item, plus every save per item (oldest first)."""
    undone = {r["undoes"] for r in recs if r.get("event") == "undo"}
    latest: dict[str, dict] = {}
    versions: dict[str, list[dict]] = {}
    for r in recs:
        if r.get("event") != "save":
            continue
        versions.setdefault(r["id"], []).append(r)
        if r["seq"] not in undone:
            latest[r["id"]] = r
    return latest, versions


def labels_of(mode: str) -> dict[str, dict]:
    return effective(read_log(mode))[0]


SNAPSHOT_KEYS = ("id", "labeler", "ts", "mode", "sample_sha256", "skipped", "output", "ui", "save_reason")


def write_labels(mode: str, labels: dict[str, dict], order: list[str]) -> None:
    """owner_labels*.jsonl = a derived snapshot (latest label per item, sample order) for scripts/owner_gold.py.
    The source of truth is the append-only labels_log.<mode>.jsonl."""
    OUT.mkdir(exist_ok=True)
    p = MODES[mode]["labels"]
    pos = {i: k for k, i in enumerate(order)}
    lines = [json.dumps({k: labels[i][k] for k in SNAPSHOT_KEYS if k in labels[i]}, ensure_ascii=False)
             for i in sorted(labels, key=lambda i: pos.get(i, 1e9))]
    tmp = p.with_suffix(".tmp")
    tmp.write_text("".join(line + "\n" for line in lines))
    os.replace(tmp, p)


def history(mode: str, event: dict) -> None:
    OUT.mkdir(exist_ok=True)
    with open(OUT / f"history.{mode}.jsonl", "a") as f:
        f.write(json.dumps({"ts": now(), **event}, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------- UI value -> reader schema

LEASE = {"yes": ("answered", True), "no": ("no", False), "vague": ("vague", None),
         "exception": ("exception", True), "absent": ("absent", None)}
INTENTS = ["price_negotiation", "scheduling", "small_talk", "not_now", "hard_no", "shorter_lease", "question"]
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class Label(BaseModel):
    id: str
    skip: bool = False
    lease: str = "absent"
    move_in: str = "absent"          # exact | vague | no | absent
    move_in_date: str | None = None
    move_in_cond: bool = False       # exact date with a condition -> exception
    phone: str = "absent"            # given | vague | declined | absent
    phone_value: str | None = None
    phone_cond: bool = False
    occupants: str = "absent"        # "1".."4" | "5+" | vague | absent
    occupants_n: int | None = None   # exact count when "5+"
    occupants_cond: bool = False
    reason: str = "absent"           # given | vague | declined | absent
    intents: list[str] = []
    language: str = "en"             # en | es | other


def to_schema(lb: Label) -> dict:
    def bad(msg):
        raise HTTPException(422, msg)

    if lb.lease not in LEASE:
        bad("lease")
    ls, lv = LEASE[lb.lease]

    if lb.move_in == "exact":
        if not (lb.move_in_date and DATE_RE.match(lb.move_in_date)):
            bad("move-in is 'exact' but no date was picked")
        move_in = {"status": "exception" if lb.move_in_cond else "answered", "date": lb.move_in_date, "raw": None}
    elif lb.move_in in ("vague", "no", "absent"):
        move_in = {"status": lb.move_in, "date": None, "raw": None}
    else:
        bad("move_in")

    if lb.phone == "given":
        digits = re.sub(r"\D", "", lb.phone_value or "")
        if len(digits) == 11 and digits.startswith("1"):
            digits = digits[1:]
        if len(digits) != 10:
            bad("phone is 'given' but the number is not 10 digits")
        phone = {"status": "exception" if lb.phone_cond else "answered", "value": "+1" + digits}
    elif lb.phone in ("vague", "declined", "absent"):
        phone = {"status": {"declined": "no"}.get(lb.phone, lb.phone), "value": None}
    else:
        bad("phone")

    if lb.occupants in ("1", "2", "3", "4", "5+"):
        n = int(lb.occupants) if lb.occupants != "5+" else (lb.occupants_n or 5)
        if n < 5 and lb.occupants == "5+":
            bad("5+ needs a count of 5 or more")
        occupants = {"status": "exception" if lb.occupants_cond else "answered", "value": n}
    elif lb.occupants in ("vague", "absent"):
        occupants = {"status": lb.occupants, "value": None}
    else:
        bad("occupants")

    if lb.reason not in ("given", "vague", "declined", "absent"):
        bad("reason")
    reason = {"status": {"given": "answered", "declined": "no"}.get(lb.reason, lb.reason), "value": None}

    if any(i not in INTENTS for i in lb.intents):
        bad("intents")
    if lb.language not in ("en", "es", "other"):
        bad("language")
    return {"lease": {"status": ls, "value": lv}, "move_in": move_in, "phone": phone, "occupants": occupants,
            "reason": reason, "intents": [i for i in INTENTS if i in lb.intents], "language": lb.language}


UI_KEYS = list(Label.model_fields)


def ui_of(rec: dict | None) -> dict | None:
    """Every UI field of a saved label, complete. Prefers the stored button values; fills any missing key from
    the stored schema output, so a field can never fall back to its default when a saved value exists."""
    if not rec:
        return None
    ui = dict(rec.get("ui") or {})
    out = rec.get("output") or {}
    if out:
        derived = {}
        ls = (out.get("lease") or {}).get("status")
        derived["lease"] = {"answered": "yes", "no": "no", "vague": "vague", "exception": "exception"}.get(ls, "absent")
        mi = out.get("move_in") or {}
        if mi.get("status") in ("answered", "exception"):
            derived.update(move_in="exact", move_in_date=mi.get("date"), move_in_cond=mi.get("status") == "exception")
        else:
            derived["move_in"] = mi.get("status") or "absent"
        ph = out.get("phone") or {}
        if ph.get("status") in ("answered", "exception"):
            derived.update(phone="given", phone_value=ph.get("value"), phone_cond=ph.get("status") == "exception")
        else:
            derived["phone"] = {"no": "declined"}.get(ph.get("status"), ph.get("status") or "absent")
        oc = out.get("occupants") or {}
        if oc.get("status") in ("answered", "exception") and oc.get("value"):
            n = int(oc["value"])
            derived.update(occupants=str(n) if n < 5 else "5+", occupants_n=n if n >= 5 else None,
                           occupants_cond=oc.get("status") == "exception")
        else:
            derived["occupants"] = oc.get("status") or "absent"
        derived["reason"] = {"answered": "given", "no": "declined"}.get((out.get("reason") or {}).get("status"),
                                                                        (out.get("reason") or {}).get("status") or "absent")
        derived["intents"] = list(out.get("intents") or [])
        if out.get("language"):
            derived["language"] = out["language"]
        for k, v in derived.items():
            ui.setdefault(k, v)
    defaults = Label(id="x").model_dump()
    full = {k: ui.get(k, defaults[k]) for k in UI_KEYS if k != "id"}
    full["skip"] = bool(rec.get("skipped"))
    return full


def record_save(mode: str, st: dict, rid: str, lb: Label, reason: str, extra: dict | None = None) -> dict:
    ids = st["manifest"]["row_ids"]
    ui = lb.model_dump(exclude={"id"})
    ui = {k: v for k, v in ui.items() if k in UI_KEYS}
    rec = {"id": rid, "labeler": "owner", "ts": now(), "mode": mode, "sample_sha256": st["manifest"]["row_ids_sha256"],
           "skipped": lb.skip, "output": None if lb.skip else to_schema(lb), "ui": ui, "event": "save",
           "save_reason": reason, **(extra or {})}
    append_log(mode, rec)
    write_labels(mode, labels_of(mode), ids)
    history(mode, {"event": "save", "id": rid, "skipped": lb.skip, "save_reason": reason})
    return rec


app = FastAPI(title="Owner blind labeler")


def item_view(st: dict, idx: int, labels: dict, versions: dict) -> dict:
    ids = st["manifest"]["row_ids"]
    rid = ids[idx]
    row = st["by_id"][rid]
    inp = row["input"]
    saved = labels.get(rid)
    return {"index": idx, "id": rid, "today": inp.get("today"), "context": (inp.get("context") or [])[-2:],
            "message": inp.get("message", ""), "saved_ui": ui_of(saved),
            "saved_ts": (saved or {}).get("ts"), "n_saves": len(versions.get(rid, []))}


def state(idx: int | None = None) -> dict:
    mode, why = current_mode()
    st = load(mode)
    labels, versions = effective(read_log(mode))
    ids = st["manifest"]["row_ids"]
    if idx is None:
        idx = next((k for k, i in enumerate(ids) if i not in labels), len(ids))
    idx = max(0, min(idx, len(ids)))
    return {"mode": mode, "mode_reason": why, "warning": st["warning"], "total": len(ids),
            "done": sum(1 for i in ids if i in labels), "sample_sha256": st["manifest"]["row_ids_sha256"],
            "item": item_view(st, idx, labels, versions) if idx < len(ids) else None, "index": idx}


@app.get("/")
def index():
    return FileResponse(HERE / "static/index.html", headers={"Cache-Control": "no-store"})


@app.get("/api/state")
def get_state(index: int | None = None):
    with LOCK:
        return JSONResponse(state(index), headers={"Cache-Control": "no-store"})


class SaveReq(Label):
    mode: str
    index: int
    base_ts: str | None = None   # ts of the saved label the form was filled from (None = item had no label)
    save_reason: str = "label"   # label | audit (opened from /audit to edit a flagged item)
    audit_rule: str | None = None


@app.post("/api/save")
def save(req: SaveReq):
    with LOCK:
        mode, _ = current_mode()
        if req.mode != mode:
            raise HTTPException(409, "the sample changed (fixture -> real); reload the page")
        st = load(mode)
        ids = st["manifest"]["row_ids"]
        if req.id not in ids:
            raise HTTPException(404, "id not in sample")
        cur = labels_of(mode).get(req.id)
        if (cur or {}).get("ts") != req.base_ts:
            # the form was filled from an older version (stale tab, browser back/forward cache): refuse rather
            # than overwrite the newer label; the page reloads this item with its latest saved values
            raise HTTPException(409, "this item was saved since the form was loaded; showing the latest saved label")
        if req.save_reason not in ("label", "audit"):
            raise HTTPException(422, "save_reason")
        lb = Label(**req.model_dump(exclude={"mode", "index", "base_ts", "save_reason", "audit_rule"}))
        extra = {"audit_rule": req.audit_rule, "supersedes_ts": req.base_ts} if req.save_reason == "audit" else None
        record_save(mode, st, req.id, lb, req.save_reason, extra)
        return state(ids.index(req.id) + 1)


@app.post("/api/undo")
def undo():
    """Undo the most recent save that is not undone yet. Appends an undo record; the save stays in the log and
    the item falls back to its previous save (or to unlabeled)."""
    with LOCK:
        mode, _ = current_mode()
        st = load(mode)
        ids = st["manifest"]["row_ids"]
        recs = read_log(mode)
        undone = {r["undoes"] for r in recs if r.get("event") == "undo"}
        cand = [r for r in recs if r.get("event") == "save" and r["seq"] not in undone
                and r.get("save_reason") != "imported_pre_log"]
        if not cand:
            return state()
        last = cand[-1]
        append_log(mode, {"event": "undo", "id": last["id"], "undoes": last["seq"], "undoes_ts": last["ts"],
                          "ts": now(), "mode": mode})
        write_labels(mode, labels_of(mode), ids)
        history(mode, {"event": "undo", "id": last["id"]})
        return state(ids.index(last["id"]))


# ---------------------------------------------------------------- audit (rule-based, labeler/audit.py)

@app.get("/audit")
def audit_page():
    return FileResponse(HERE / "static/audit.html", headers={"Cache-Control": "no-store"})


def decisions_path(mode: str) -> Path:
    return OUT / f"audit_decisions.{mode}.jsonl"


@app.get("/api/audit")
def get_audit():
    import audit as rules
    with LOCK:
        mode, _ = current_mode()
        st = load(mode)
        recs = read_log(mode)
        labels, versions = effective(recs)
        hist = read_jsonl(OUT / f"history.{mode}.jsonl")
        flags = rules.run(st["manifest"]["row_ids"], st["by_id"], labels, versions, hist, ui_of)
        dkey = lambda d: (d["id"], d["rule"], d.get("why"), json.dumps(d.get("owner_value"), sort_keys=True))
        dec = {dkey(d): d for d in read_jsonl(decisions_path(mode))}
        items = []
        for rid in st["manifest"]["row_ids"]:
            fl = [f for f in flags if f["id"] == rid]
            if not fl:
                continue
            for f in fl:
                d = dec.get(dkey(f))
                f["decision"] = d["action"] if d else None
            row = st["by_id"][rid]["input"]
            items.append({"id": rid, "index": st["manifest"]["row_ids"].index(rid), "today": row.get("today"),
                          "context": (row.get("context") or [])[-2:], "message": row.get("message", ""),
                          "label": ui_of(labels.get(rid)), "label_ts": (labels.get(rid) or {}).get("ts"),
                          "label_reason": (labels.get(rid) or {}).get("save_reason"), "flags": fl})
        decided_ids = {d["id"] for d in dec.values()}
        return JSONResponse({"mode": mode, "items": items, "n_flags": len(flags),
                             "open": sum(1 for it in items for f in it["flags"] if not f["decision"]),
                             "decided_items": len(decided_ids)}, headers={"Cache-Control": "no-store"})


class DecideReq(BaseModel):
    id: str
    rule: str
    label_ts: str
    action: str                  # keep | change
    patch: dict = {}             # UI-field changes the rule suggests (applied only on change)
    why: str | None = None
    owner_value: object = None


@app.post("/api/audit/decide")
def audit_decide(req: DecideReq):
    if req.action not in ("keep", "change"):
        raise HTTPException(422, "action must be keep or change")
    with LOCK:
        mode, _ = current_mode()
        st = load(mode)
        cur = labels_of(mode).get(req.id)
        if not cur:
            raise HTTPException(404, "item has no label")
        if cur["ts"] != req.label_ts:
            raise HTTPException(409, "this label changed since the audit page loaded; reload")
        new_ts = None
        if req.action == "change":
            ui = ui_of(cur)
            bad = [k for k in req.patch if k not in UI_KEYS or k in ("id", "skip")]
            if bad:
                raise HTTPException(422, f"unknown fields {bad}")
            ui.update(req.patch)
            ui["skip"] = False
            rec = record_save(mode, st, req.id, Label(id=req.id, **ui), "audit",
                              {"audit_rule": req.rule, "supersedes_ts": cur["ts"]})
            new_ts = rec["ts"]
        OUT.mkdir(exist_ok=True)
        with open(decisions_path(mode), "a") as f:
            f.write(json.dumps({"ts": now(), "id": req.id, "rule": req.rule, "label_ts": req.label_ts,
                                "why": req.why, "owner_value": req.owner_value,
                                "action": req.action, "patch": req.patch if req.action == "change" else None,
                                "new_label_ts": new_ts}, ensure_ascii=False) + "\n")
        return {"ok": True, "new_label_ts": new_ts}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", choices=["auto", "real", "fixture"], default="auto")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--reset", action="store_true",
                    help="move this mode's labels, log and history aside (*.reset-<time>.jsonl; the manifest is kept), then exit")
    a = ap.parse_args()
    ARGS.source = a.source
    if a.reset:
        mode, _ = current_mode()
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        for p in (MODES[mode]["labels"], OUT / f"history.{mode}.jsonl", log_path(mode), decisions_path(mode)):
            if p.exists():   # moved aside, never deleted
                p.rename(p.with_name(f"{p.stem}.reset-{stamp}{p.suffix}"))
        print(f"reset {mode} labels (old files kept as *.reset-{stamp}.jsonl)")
        return
    import uvicorn
    mode, why = current_mode()
    load(mode)
    print(f"labeler: mode={mode} ({why}) on http://{a.host}:{a.port}", flush=True)
    uvicorn.run(app, host=a.host, port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
