"""Real-world pilot (D20): the operator writes the Appling Way post, the owner-approved text goes on the Page.

  python -m channels.pilot_post draft                       # live operator -> runs/pilot/operator_listing.json
  python -m channels.pilot_post publish TEXT_FILE PHOTO...  # PUBLISHED Page post with up to 4 photos
  python -m channels.pilot_post delete POST_ID              # remove a post (owner allows post/remove cycles)

`draft` builds a sandbox world whose Appling Way room holds ONLY the owner-confirmed facts (no deposit,
utilities, lease length or house rules), runs rentus_operator (create_listing + check_listing_compliance,
no publish_listing) and saves the model's title/body. Editing to the allowed facts is done by hand.
`publish` strips photo metadata (EXIF/GPS) before upload. Credentials come from channels.facebook_page._creds
(never printed). runs/ is gitignored.
"""
from __future__ import annotations

import io
import json
import sys
import time
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "runs" / "pilot"

ROOM = {
    "room_id": "R_APPLING",
    "area": "Durham",
    "zip": "27703",
    "address": "Appling Way, Durham, NC 27703",
    "address_public": "Appling Way, Durham, NC 27703",
    "type": "bedroom in house",
    "private_bath": True,
    "own_entrance": True,
    "rent": 750,
    "available_from": "2026-11-01",
    "amenities": ["Private bathroom", "Separate entrance"],
    "notes": "Owner-confirmed facts only. Deposit, utilities, lease length, furnishing, shared spaces and house "
             "rules are NOT confirmed: never state them; say 'message us for details'.",
}

INSTRUCTION = (
    "The Appling Way room (R_APPLING) is available Nov 1, $750/month, private bathroom, its own separate "
    "entrance. Write a short listing title and body for our Facebook Page from the room record only. Do not "
    "state a deposit, utilities, lease length or house rules (they are not confirmed); end with 'Message us for "
    "details.' Use the street name only. Run check_listing_compliance and create_listing. Do NOT call "
    "publish_listing: the owner posts it himself. Then report_to_owner."
)


def draft() -> int:
    sys.path.insert(0, str(REPO / "operator"))
    from rentus_operator import cli, toolbox
    from rentus_operator.config import RunConfig
    from rentus_operator.loop import run

    cli.load_env()
    cfg = RunConfig()
    models = cli.probe(cfg.base_url, cfg.api_key)
    if not models:
        print("operator endpoint not reachable", file=sys.stderr)
        return 2
    cfg = cfg.with_(model=models[0])
    be = toolbox.backend("auto")
    world = toolbox.new_world(be, None)
    toolbox.add_room(world, ROOM)
    run_id = f"pilot_{uuid.uuid4().hex[:6]}"
    OUT.mkdir(parents=True, exist_ok=True)
    sink = toolbox.make_sink(be, run_id, path=OUT / f"{run_id}.events.jsonl")
    res = run(world, INSTRUCTION, config=cfg, sink=sink, backend=be, run_id=run_id)
    st = toolbox.state(world)
    listing = next((l for l in st.get("listings", []) if l.get("room_id") == "R_APPLING"), None)
    compliance = [e for e in res.events if e.get("type") == "tool_result"
                  and (e.get("data") or {}).get("tool") == "check_listing_compliance"]
    out = {"run_id": run_id, "model": cfg.model, "status": res.status, "listing": listing,
           "compliance_results": [(e.get("data") or {}).get("result") for e in compliance],
           "final_text": res.final_text, "at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    (OUT / "operator_listing.json").write_text(json.dumps(out, indent=2, ensure_ascii=False, default=str))
    print(json.dumps({"status": res.status, "listing": listing, "compliance": out["compliance_results"]},
                     indent=2, ensure_ascii=False, default=str))
    return 0 if listing else 1


def _clean_jpeg(path: Path) -> bytes:
    from PIL import Image, ImageOps

    im = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    im.thumbnail((2048, 2048))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=88)  # no exif= argument: metadata (incl. GPS) is dropped
    return buf.getvalue()


def publish(text: str, photos: list[Path]) -> dict:
    from channels.facebook_page import _call, _creds

    page_id, token = _creds()
    media = []
    for i, p in enumerate(photos[:4]):
        up = _call("POST", f"{page_id}/photos", token, data={"published": "false"},
                   files={"source": (f"appling-{i + 1}.jpg", _clean_jpeg(p), "image/jpeg")})
        media.append(up["id"])
    data = {"message": text, "published": "true"}
    for i, mid in enumerate(media):
        data[f"attached_media[{i}]"] = json.dumps({"media_fbid": mid})
    post = _call("POST", f"{page_id}/feed", token, data=data)
    info = _call("GET", post["id"], token, params={"fields": "id,is_published,permalink_url,created_time"})
    return {"post_id": post["id"], "photo_ids": media, **info}


def delete(post_id: str) -> dict:
    from channels.facebook_page import FacebookError, _call, _creds

    _, token = _creds()
    try:
        return {"post_id": post_id, **_call("DELETE", post_id, token)}
    except FacebookError as e:
        return {"post_id": post_id, "error": str(e)}


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else ""
    if cmd == "draft":
        return draft()
    if cmd == "publish" and len(argv) >= 2:
        res = publish(Path(argv[1]).read_text().strip(), [Path(p) for p in argv[2:]])
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "published.json").write_text(json.dumps(res, indent=2))
        print(json.dumps(res, indent=2))
        return 0 if res.get("is_published") else 1
    if cmd == "delete" and len(argv) == 2:
        print(json.dumps(delete(argv[1])))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
