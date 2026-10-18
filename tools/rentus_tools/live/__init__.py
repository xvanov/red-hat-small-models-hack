"""Live channel adapters (W8 fills these). Same signatures as the sandbox side effects.

A live adapter NEVER submits: it fills the real form, takes a screenshot and stops, returning
`{"status": "ready_to_submit", "screenshot": "<path>", "post_id"?, "url"?}`. The owner clicks submit.

Register an adapter per channel:

    from rentus_tools import live
    live.register("marketplace", MyMarketplaceAdapter())

Tools route through here when `world.mode == "live"`. Unregistered channels use StubAdapter,
which returns ready_to_submit with a placeholder screenshot path and touches nothing.
"""
from __future__ import annotations

from typing import Protocol


class LiveAdapter(Protocol):
    def publish_listing(self, world, listing: dict, channel: str) -> dict: ...

    def send_message(self, world, thread: dict, text: str, attachments: list[str]) -> dict: ...


class StubAdapter:
    def __init__(self, runs_dir: str = "runs"):
        self.runs_dir = runs_dir

    def _shot(self, world, kind: str, ref: str) -> str:
        run = (world.meta or {}).get("run_id", "r_local")
        return f"{self.runs_dir}/{run}/screens/{kind}-{ref}.png"

    def publish_listing(self, world, listing: dict, channel: str) -> dict:
        return {"status": "ready_to_submit", "screenshot": self._shot(world, f"publish-{channel}", listing["listing_id"]),
                "post_id": None, "url": None, "stub": True}

    def send_message(self, world, thread: dict, text: str, attachments: list[str]) -> dict:
        return {"status": "ready_to_submit", "screenshot": self._shot(world, f"send-{thread['channel']}", thread["thread_id"]),
                "stub": True}


ADAPTERS: dict[str, LiveAdapter] = {}
_STUB = StubAdapter()


def register(channel: str, adapter: LiveAdapter) -> None:
    ADAPTERS[channel] = adapter


def adapter_for(channel: str) -> LiveAdapter:
    return ADAPTERS.get(channel, _STUB)


def register_live(target: str = "live", base_url: str | None = None, photo_dir: str | None = None, store=None) -> dict:
    """Lane 3 one-call setup: browser listing adapters (marketplace, roomies, craigslist, padsplit) on
    `target` plus the email and SMS draft channels with live-mode thread sync, and the Google Calendar
    showing adapter (writes only to CHANNELS_SHOWINGS_CALENDAR_ID, never invites anyone). Nothing it
    registers submits a listing or sends a message."""
    from .channels_adapter import register_all
    from .calendar_adapter import register_calendar
    from .inbound_adapter import register_inbound

    browser = register_all(target, base_url=base_url, photo_dir=photo_dir)
    inbound = register_inbound(store)
    register_calendar()
    return {"browser": browser, **inbound, "calendar": "google"}
