"""Offline tests for the twins pipeline (no model calls). Run: data/twins/.venv/bin/python data/twins/test_twins.py"""
from __future__ import annotations

import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common  # noqa: E402
import ingest  # noqa: E402
from filter import grams  # noqa: E402

FX = Path(__file__).resolve().parent / "fixtures" / "input"


def test_mojibake():
    assert ingest.fix_mojibake("Listo, ya la llenÃ©. Â¡Gracias!") == "Listo, ya la llené. ¡Gracias!"
    assert ingest.fix_mojibake("ya la llené") == "ya la llené"  # correct text is left alone


def test_scrub():
    t, c = common.scrub("text 919-555-0142 or (336) 555 0119, mail a.b@example.com, 12 Example Ct apt 4, www.x.com/y")
    for leak in ("555", "example.com", "12 Example", "www."):
        assert leak not in t, (leak, t)
    assert c["[PHONE]"] == 2 and c["[EMAIL]"] == 1 and c["[ADDRESS]"] == 1


def test_pii_hits_allows_assigned_phone():
    assert common.pii_hits("call 919-555-0142", ("+19195550142",)) == []
    assert common.pii_hits("call 919-555-0199", ("+19195550142",)) == ["phone"]


def test_loaders_read_all_formats():
    raws = (list(ingest.load_imazing(FX / "imazing")) + list(ingest.load_facebook(FX / "facebook"))
            + list(ingest.load_generic(FX / "generic")))
    assert Counter(r["source"] for r in raws) == {"imazing": 3, "facebook": 4, "generic": 3}
    sc = Counter()
    threads = [ingest.normalize(r, {"fixture owner"}, "salt", sc) for r in raws]
    assert all(t and any(x["role"] == "owner" for x in t["turns"]) for t in threads)
    fb = [t for t in threads if t["source"] == "facebook"]
    assert any("llené" in x["text"] for t in fb for x in t["turns"])  # mojibake repaired
    assert sum(t["language_switch"] for t in threads) == 1
    assert not any("555-01" in x["text"] for t in threads for x in t["turns"])  # phones scrubbed


def test_local_only_guard():
    assert common._is_local_host("localhost") and common._is_local_host("127.0.0.1")
    assert not common._is_local_host("api.anthropic.com") and not common._is_local_host("opencode.ai")


def test_private_dir_outside_repo():
    os.environ["RENTUS_PRIVATE_DIR"] = str(common.REPO / "data")
    try:
        common.Paths.make(False)
    except SystemExit as e:
        assert "inside the repo" in str(e)
    else:
        raise AssertionError("a private dir inside the repo must be refused")
    finally:
        del os.environ["RENTUS_PRIVATE_DIR"]


def test_grams():
    assert len(grams("hello there")) == len("hello there") - 7


def test_anon_export_rules():
    """Owner-export loader: tap-backs dropped, photo-only kept as [photo], partners map to the owner side,
    contractors are vendors, anonymizer-damaged dates flagged, episodes capped."""
    assert ingest.anon_turn_text({"text": "Liked \u201cok see you then\u201d", "attachments": []}) is None
    assert ingest.anon_turn_text({"text": "Le gust\u00f3 \u201cgracias\u201d", "attachments": []}) is None
    assert ingest.anon_turn_text({"text": "", "attachments": ["image .heic"]}) == "[photo]"
    assert ingest.anon_turn_text({"text": "", "attachments": ["file .pluginpayloadattachment"]}) is None
    assert ingest.anon_turn_text({"text": "I liked the room", "attachments": []}) == "I liked the room"
    assert ingest.anon_role({"sender": "me"}, {"P9"}, "tenants") == "owner"
    assert ingest.anon_role({"sender": "P9"}, {"P9"}, "tenants") == "owner"
    assert ingest.anon_role({"sender": "P1"}, {"P9"}, "contractors") == "vendor"
    assert ingest.anon_role({"sender": "P1"}, {"P9"}, "tenants") == "renter"
    ingest.STREET_WORDS.clear()
    ingest.STREET_WORDS.update({"thornbury"})
    assert ingest.date_damaged("moving in November Thornbury if ok")
    assert not ingest.date_damaged("moving in November 12")
    assert ingest.date_damaged("the 15th [state] 16th works")
    turns = [{"role": "renter" if k % 2 else "owner", "text": "hi"} for k in range(100)]
    eps = ingest.episode_bounds(turns, "leasing", None)
    assert eps == [("leasing", 0, ingest.EPISODE_TURNS)]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
