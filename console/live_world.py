"""Live mode for Assistant runs: real channel adapters, the real Appling Way room, honest posting status.

Nothing here submits a listing or sends a message by itself:
  - marketplace / roomies / craigslist / padsplit: rentus_tools.live.register_live("live") browser adapters fill the
    form on the owner's logged-in profile and stop before submit (ready_to_submit) or say LOGIN_REQUIRED.
  - Facebook Page: `fb_prepare` creates an UNPUBLISHED post (not visible); `fb_publish` publishes only when the
    owner clicks Publish in the console (channels/pilot_post.py publish path), then deletes the unpublished draft.
`CONSOLE_FB_MODULE` swaps the Facebook calls for a fake (tests never touch the real Page).
"""
from __future__ import annotations

import importlib
import json
import os
import re
import subprocess
import tempfile
import threading
from pathlib import Path

from . import integration as integ

REPO = integ.REPO
CH_PY = REPO / "channels" / ".venv" / "bin" / "python"
_REG: dict = {"done": False, "info": None, "error": None}
_LOCK = threading.Lock()
PLATFORMS = ("marketplace", "roomies", "craigslist", "padsplit")


def listing_channels() -> list[str]:
    """Where the Assistant may post (CONSOLE_LISTING_CHANNELS). Platforms left out are refused at the tool and hidden on the card."""
    raw = os.environ.get("CONSOLE_LISTING_CHANNELS") or "facebook_page,craigslist,roomies,padsplit"
    return [c.strip() for c in raw.split(",") if c.strip()]


class DisabledChannel:
    """Live adapter for a platform the owner switched off: publish is refused before any browser opens."""

    def __init__(self, channel: str):
        self.channel = channel

    def publish_listing(self, world, listing, channel):
        from rentus_tools.errors import ToolError
        raise ToolError("POLICY_BLOCKED", f"the owner turned off posting to {channel}",
                        hint="skip this channel; post only to the others")

    def send_message(self, world, thread, text, attachments):
        return {"status": "ready_to_submit", "screenshot": None, "note": "draft only"}


def register() -> dict:
    """Register the live adapters once per process. Returns {"ok", "info"|"error"}."""
    with _LOCK:
        if not _REG["done"]:
            _REG["done"] = True
            if not os.environ.get("DISPLAY"):
                os.environ.setdefault("CHANNELS_HEADLESS", "1")  # the console runs without a screen
            try:
                from rentus_tools import live
                _REG["info"] = {k: str(v) for k, v in (live.register_live("live", photo_dir=photo_dir()) or {}).items()}
                on = set(listing_channels())
                for ch in PLATFORMS:
                    if ch not in on:
                        live.register(ch, DisabledChannel(ch))
                _REG["info"]["listing_channels"] = ",".join(sorted(on))
            except Exception as e:
                _REG["error"] = f"{type(e).__name__}: {e}"
        return {"ok": _REG["error"] is None, "info": _REG["info"], "error": _REG["error"]}


IMG_EXT = {".jpg", ".jpeg", ".png", ".webp"}


def photo_dir() -> str | None:
    """The owner's photo folder for the real room (CONSOLE_ROOM_PHOTO_DIR, else CHANNELS_PHOTO_DIR). Never in the repo."""
    d = os.environ.get("CONSOLE_ROOM_PHOTO_DIR") or os.environ.get("CHANNELS_PHOTO_DIR")
    return d if d and Path(d).is_dir() else None


def room_photos() -> list[Path]:
    d = photo_dir()
    return sorted(p for p in Path(d).iterdir() if p.suffix.lower() in IMG_EXT) if d else []


def real_room() -> dict:
    """The Appling Way room with only the owner-confirmed facts (the same record the D20 pilot post used),
    plus the owner's photos when a photo folder is configured."""
    from channels.pilot_post import ROOM
    room = dict(ROOM)
    photos = room_photos()
    if photos:
        room["photos"] = [p.name for p in photos]
    return room


def prepare_world(world, toolbox) -> dict:
    reg = register()
    world.mode = "live"
    try:
        world.rooms[:] = []  # live inventory only: the sandbox rooms are fictional
    except Exception:
        pass
    toolbox.add_room(world, real_room())
    return reg


# ------------------------------------------------------------------ honest posting status
def _rel(p: Path) -> str:
    try:
        return str(p.resolve().relative_to(REPO))
    except ValueError:
        return str(p)


def _exists(p: str | None) -> bool:
    return bool(p) and ((REPO / p).is_file() or Path(p).is_file())


LOGIN_RE = re.compile(r"(channels/\.venv/bin/python -m channels\.login \w+)")


def posts(listings: list[dict], events: list[dict], fb: dict) -> list[dict]:
    """Per listing, per channel: what really happened. Merges listing.channels with failed publish_listing calls."""
    calls, failed = {}, {}
    for e in events:
        d = e.get("data") or {}
        if e.get("type") == "tool_call" and d.get("tool") == "publish_listing":
            calls[d.get("call_id")] = d.get("args") or {}
        elif e.get("type") == "tool_result" and d.get("tool") == "publish_listing":
            r = d.get("result") or {}
            a = calls.get(d.get("call_id")) or {}
            if r.get("ok") is False and a.get("channel"):
                failed[(a.get("listing_id"), a["channel"])] = r.get("error") or {}
    out = []
    for l in listings:
        lid = l.get("listing_id")
        rows = []
        chans = list(dict.fromkeys(list((l.get("channels") or {}).keys()) + [c for (x, c) in failed if x == lid]))
        on = set(listing_channels())
        for ch in chans:
            if ch not in on:  # switched off by the owner: not shown
                continue
            entry = (l.get("channels") or {}).get(ch)
            if entry:
                entry = entry if isinstance(entry, dict) else {"status": str(entry)}
                st = entry.get("status")
                shot = entry.get("screenshot") or ""
                stub = "/screens/" in shot and not _exists(shot)  # rentus_tools.live.StubAdapter placeholder
                if entry.get("stub") or stub:
                    rows.append({"channel": ch, "state": "not_connected", "label": "Not connected",
                                 "detail": "no live adapter for this channel"})
                    continue
                url = entry.get("url") or ""
                if "sandbox" in url or ".local/" in url:
                    rows.append({"channel": ch, "state": "not_connected", "label": "Not connected",
                                 "detail": "this run was not in live mode"})
                    continue
                state = {"ready_to_submit": "ready", "live": "posted", "posted": "posted"}.get(st, st or "unknown")
                label = {"ready": "Ready, needs your click", "posted": "Posted"}.get(state, st)
                rows.append({"channel": ch, "state": state, "label": label, "screenshot": shot if _exists(shot) else None,
                             "url": url or None, "detail": ("Details form filled and stopped there. Photos go on the next page, which needs "
                                                            f"you logged in: channels/.venv/bin/python -m channels.login {ch}")
                             if state == "ready" and "-partial" in (shot or "") else
                             "Form filled on your logged-in profile, photos attached, stopped before submit." if state == "ready" else None})
            else:
                err = failed.get((lid, ch)) or {}
                code = err.get("code") or "UPSTREAM_ERROR"
                msg = " ".join(str(err.get(k) or "") for k in ("message", "hint"))
                if code == "LOGIN_REQUIRED":
                    m = LOGIN_RE.search(msg)
                    rows.append({"channel": ch, "state": "login", "label": "Needs login",
                                 "command": m.group(1) if m else f"channels/.venv/bin/python -m channels.login {ch}",
                                 "detail": err.get("message")})
                elif "adapters unavailable" in msg:
                    rows.append({"channel": ch, "state": "not_connected", "label": "Not connected", "detail": err.get("message")})
                else:
                    rows.append({"channel": ch, "state": "failed", "label": "Failed", "detail": err.get("message") or code})
        f = fb.get(lid) or {}
        if "facebook_page" in on:
            rows.insert(0, {"channel": "facebook_page", "state": f.get("state") or "not_prepared",
                            "label": {"draft": "Draft on Page, not visible yet", "published": "Published",
                                      "failed": "Not published"}.get(f.get("state"), "Ready to publish"),
                            "detail": f.get("error"), "url": f.get("permalink"), "post_id": f.get("post_id"),
                            "preview": post_text(l), "photos": [_rel(p) for p in room_photos()[:4]]})
        out.append({"listing_id": lid, "title": l.get("title"), "body": l.get("body"), "price": l.get("price"),
                    "status": l.get("status"), "channels": rows})
    return out


# ------------------------------------------------------------------ Facebook Page (owner's click only)
def _fb_fake():
    name = os.environ.get("CONSOLE_FB_MODULE")
    return importlib.import_module(name) if name else None


def post_text(listing: dict) -> str:
    text = f"{listing.get('title', '')}\n\n{listing.get('body', '')}".strip()
    if listing.get("price") and f"${listing['price']}" not in text:
        text += f"\n\n${listing['price']}/month"
    return text


def fb_prepare(listing: dict) -> dict:
    """An UNPUBLISHED Page post: not visible on the Page until the owner publishes."""
    fake = _fb_fake()
    if fake:
        return fake.create_unpublished_post(post_text(listing))
    from channels.facebook_page import create_unpublished_post
    return create_unpublished_post(post_text(listing))


def fb_publish(listing: dict, draft_post_id: str | None) -> dict:
    """The published-post path of channels/pilot_post.py (the owner's room photos, EXIF stripped there),
    then the unpublished draft is deleted. Called only from the owner's Publish click."""
    fake = _fb_fake()
    if fake:
        res = fake.publish(post_text(listing))
        if draft_post_id:
            fake.delete(draft_post_id)
        return res
    photos = [str(p) for p in room_photos()][:4]
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as fh:
        fh.write(post_text(listing))
    py = str(CH_PY if CH_PY.exists() else "python3")
    r = subprocess.run([py, "-m", "channels.pilot_post", "publish", fh.name, *photos], cwd=REPO, capture_output=True,
                       text=True, timeout=120)
    os.unlink(fh.name)
    try:
        res = json.loads(r.stdout[r.stdout.index("{"):])
    except ValueError:
        raise RuntimeError((r.stderr or r.stdout or "publish failed").strip().splitlines()[-1][:300])
    if draft_post_id and res.get("is_published"):
        subprocess.run([py, "-m", "channels.pilot_post", "delete", draft_post_id], cwd=REPO, capture_output=True,
                       text=True, timeout=60)
    return res
