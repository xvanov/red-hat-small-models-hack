"""W8: LiveAdapter implementation backed by channels/ (browser adapters + self-repair).

    from rentus_tools.live.channels_adapter import register_all
    register_all(target="mock")   # world.mode == "live" now drives the local mock sites (demo, Gym)
    register_all(target="live")   # real platforms on the owner's logged-in profiles; still stops before submit

publish_listing fills the platform's form, screenshots, and returns status "ready_to_submit".
send_message never sends on a real platform: for target="live" it returns a draft (ready_to_submit)
without opening a browser. For target="mock" it sends into the mock inbox when the thread carries an
`external_id` like "marketplace:t1001" (from channels.adapters.api.list_threads).

Needs channels/requirements.txt (playwright etc.) in the running environment.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from ..errors import ToolError
from . import register

REPO = Path(__file__).resolve().parents[3]
PLATFORMS = ("marketplace", "roomies", "craigslist", "padsplit")


def _api():
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    try:
        from channels.adapters import api
    except ImportError as e:
        raise ToolError("UPSTREAM_ERROR", f"channel adapters unavailable: {e}",
                        hint="pip install -r channels/requirements.txt && playwright install chromium") from None
    return api


def _raise(env: dict) -> None:
    err = env["error"]
    code = err.get("code", "UPSTREAM_ERROR")
    try:
        raise ToolError(code, err.get("message", ""), hint=err.get("hint"), retryable=err.get("retryable"),
                        details=err.get("details"))
    except AssertionError:  # code outside the contract list
        raise ToolError("UPSTREAM_ERROR", err.get("message", ""), details=err.get("details")) from None


class ChannelsAdapter:
    def __init__(self, target: str = "mock", base_url: str | None = None, photo_dir: str | None = None):
        assert target in ("mock", "live")
        self.target = target
        self.base_url = base_url
        self.photo_dir = photo_dir or os.environ.get("CHANNELS_PHOTO_DIR")

    def _photos(self, room: dict) -> list[str]:
        if not self.photo_dir:
            return []
        out = []
        for name in room.get("photos", []):
            for cand in (Path(self.photo_dir) / room.get("room_id", "") / name, Path(self.photo_dir) / name):
                if cand.exists():
                    out.append(str(cand))
                    break
        return out

    def publish_listing(self, world, listing: dict, channel: str) -> dict:
        room = next((r for r in world.rooms if r.get("room_id") == listing.get("room_id")), {})
        payload = {"listing_id": listing.get("listing_id"), "title": listing.get("title"),
                   "body": listing.get("body"), "price": listing.get("price"), "room": room,
                   "photos": self._photos(room)}
        env = _api().publish_listing(payload, channel, self.target, base_url=self.base_url)
        if not env["ok"]:
            _raise(env)
        d = env["data"]
        return {"status": d["status"], "screenshot": d.get("screenshot"), "post_id": d.get("post_id"),
                "url": d.get("url"), "repairs": d.get("repairs", [])}

    def send_message(self, world, thread: dict, text: str, attachments: list[str]) -> dict:
        ext = thread.get("external_id") or (thread["thread_id"] if ":" in thread.get("thread_id", "") else None)
        if self.target == "live" or not ext:
            return {"status": "ready_to_submit", "screenshot": None,
                    "note": "draft only; messages on real platforms are sent by the owner"}
        env = _api().send_message(ext, text, attachments, "mock", base_url=self.base_url)
        if not env["ok"]:
            _raise(env)
        return {"status": "sent", "screenshot": None, "external_message_id": env["data"]["message_id"]}


def register_all(target: str = "mock", base_url: str | None = None, photo_dir: str | None = None) -> ChannelsAdapter:
    adapter = ChannelsAdapter(target, base_url, photo_dir)
    for ch in PLATFORMS:
        register(ch, adapter)
    return adapter
