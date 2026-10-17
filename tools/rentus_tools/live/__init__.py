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
