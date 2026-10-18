"""scripts/owner_gold.py: blind owner labels -> H2 gold (Amendment 2 items 7/8). No model calls."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("owner_gold", REPO / "scripts/owner_gold.py")
og = importlib.util.module_from_spec(spec)
spec.loader.exec_module(og)

ABSENT = {"lease": {"status": "absent", "value": None}, "move_in": {"status": "absent", "date": None, "raw": None},
          "phone": {"status": "absent", "value": None}, "occupants": {"status": "absent", "value": None},
          "reason": {"status": "absent", "value": None}, "intents": [], "language": "en"}


def _src():
    rows = []
    for t in range(3):
        for k in range(2):
            out = json.loads(json.dumps(ABSENT))
            out["intents"] = ["question"]
            rows.append({"id": f"twin-{t}-{k}", "source": "twin", "input": {"today": "2026-11-01", "context": [],
                         "message": f"msg {t}{k}"}, "output": out,
                         "meta": {"twin_id": f"tw_{t}", "turn": k, "unscorable": ["move_in"], "flagged": True}})
    return rows


def _manifest(rows, ids, mode="real"):
    blob = "".join(json.dumps(r) + "\n" for r in rows).encode()
    return {"mode": mode, "source_sha256": hashlib.sha256(blob).hexdigest(), "twin_ids": sorted({i.rsplit("-", 1)[0] for i in ids}),
            "row_ids": ids, "row_ids_sha256": hashlib.sha256("\n".join(ids).encode()).hexdigest()}, hashlib.sha256(blob).hexdigest()


def _label(rid, man, out=None, **kw):
    rec = {"id": rid, "labeler": "owner", "ts": "2026-10-18T09:00:00+00:00", "mode": "real",
           "sample_sha256": man["row_ids_sha256"], "skipped": False, "output": out or json.loads(json.dumps(ABSENT))}
    rec.update(kw)
    return rec


def test_complete_labels_make_gold_and_audit():
    rows = _src()
    ids = [r["id"] for r in rows[:4]]
    man, sha = _manifest(rows, ids)
    phone = json.loads(json.dumps(ABSENT))
    phone["phone"] = {"status": "answered", "value": "+19195550100"}
    phone["intents"] = ["question"]
    labels = [_label(ids[0], man, phone), _label(ids[1], man), _label(ids[2], man, skipped=True, output=None),
              _label(ids[3], man)]
    gold, audit = og.build(labels, man, rows, sha)
    assert [g["id"] for g in gold] == [ids[0], ids[1], ids[3]]
    assert gold[0]["output"]["phone"]["value"] == "+19195550100"
    assert all(g["meta"]["gold"] == "owner" and g["meta"]["unscorable"] == [] and "flagged" not in g["meta"] for g in gold)
    assert gold[0]["meta"]["twin_id"] == "tw_0"          # cluster id for the thread bootstrap survives
    assert audit["skipped_by_owner"] == 1 and audit["gold_rows"] == 3 and audit["gold_threads"] == 2
    tv = audit["twin_gold_vs_owner"]
    assert tv["phone"] == {"agree": 2, "n": 3, "rate": round(2 / 3, 4)}
    assert tv["intents"]["agree"] == 1                 # twin gold says question; owner said none on two rows
    assert audit["twin_gold_exact_row_match"]["agree"] == 0


@pytest.mark.parametrize("break_it,needle", [
    (lambda L, m: L.pop(), "not labeled yet"),
    (lambda L, m: L.append(dict(L[0])), "duplicate"),
    (lambda L, m: L[0].update(mode="fixture"), "not 'real'"),
    (lambda L, m: L[0].update(labeler="reader"), "not 'owner'"),
    (lambda L, m: L[0].update(sample_sha256="x"), "different sample"),
    (lambda L, m: L.append(_label("twin-2-1", m)), "not in the sample"),
])
def test_refuses_incomplete_or_inconsistent_labels(break_it, needle):
    rows = _src()
    ids = [r["id"] for r in rows[:4]]
    man, sha = _manifest(rows, ids)
    labels = [_label(i, man) for i in ids]
    break_it(labels, man)
    with pytest.raises(og.NotReady, match=needle):
        og.build(labels, man, rows, sha)


def test_refuses_manifest_from_another_source_file():
    rows = _src()
    ids = [r["id"] for r in rows[:2]]
    man, _ = _manifest(rows, ids)
    with pytest.raises(og.NotReady, match="source_sha256"):
        og.build([_label(i, man) for i in ids], man, rows, "0" * 64)


def test_cli_writes_once(tmp_path):
    rows = _src()
    ids = [r["id"] for r in rows]
    man, _ = _manifest(rows, ids)
    src, mp, lp = tmp_path / "reader_test.jsonl", tmp_path / "m.json", tmp_path / "l.jsonl"
    src.write_text("".join(json.dumps(r) + "\n" for r in rows))
    mp.write_text(json.dumps(man))
    lp.write_text("".join(json.dumps(_label(i, man)) + "\n" for i in ids[:-1]))
    args = ["--labels", str(lp), "--manifest", str(mp), "--source", str(src),
            "--out", str(tmp_path / "g.jsonl"), "--audit", str(tmp_path / "a.json")]
    assert og.main(args + ["--check"]) == 1 and og.main(args) == 1 and not (tmp_path / "g.jsonl").exists()
    lp.write_text("".join(json.dumps(_label(i, man)) + "\n" for i in ids))
    assert og.main(args + ["--check"]) == 0 and not (tmp_path / "g.jsonl").exists()
    assert og.main(args) == 0
    audit = json.loads((tmp_path / "a.json").read_text())
    assert audit["gold_rows"] == 6
    assert audit["owner_gold_sha256"] == hashlib.sha256((tmp_path / "g.jsonl").read_bytes()).hexdigest()
    assert og.main(args) == 1                          # never overwritten
