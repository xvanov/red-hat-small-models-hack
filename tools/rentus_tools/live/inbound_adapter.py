"""Lane 3: email and SMS as live channels for the operator's tools. Drafts only, never sends.

    from rentus_tools.live.inbound_adapter import register_inbound
    register_inbound()                 # email + sms adapters, and live-mode thread sync

With world.mode == "live":
  list_threads / read_thread  first merge the inbound store's threads (channels/.inbox/, filled by
                              `python -m channels.inbound email-poll | email-import | sms-add`) into
                              world.threads, then run the normal tool.
  send_message                runs every send_message guard as usual, then the adapter saves the reply in
                              the channel's outbox with a reason and returns status "draft_saved".
  publish_listing             email/sms are not listing channels: POLICY_BLOCKED.

The sync is installed by wrapping the two registry entries (rentus_tools.core.REGISTRY) instead of
editing impl/inbox.py; `uninstall_sync()` restores them. In sandbox mode the wrappers do nothing.
"""
from __future__ import annotations

import sys
from pathlib import Path

from ..errors import ToolError
from . import register

REPO = Path(__file__).resolve().parents[3]
INBOUND_CHANNELS = ("email", "sms")


def _inbound():
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    from channels.inbound import email_channel, sms
    from channels.inbound.store import ChannelStore

    return ChannelStore, email_channel, sms


class InboundAdapter:
    """LiveAdapter for one inbound channel ("email" or "sms")."""

    def __init__(self, channel: str, store=None):
        assert channel in INBOUND_CHANNELS
        self.channel = channel
        ChannelStore, _, _ = _inbound()
        self.store = store or ChannelStore()

    def publish_listing(self, world, listing: dict, channel: str) -> dict:
        raise ToolError("POLICY_BLOCKED", f"{channel} is a conversation channel, not a listing site",
                        hint="publish to marketplace, roomies, craigslist or padsplit")

    def send_message(self, world, thread: dict, text: str, attachments: list[str]) -> dict:
        _, email_channel, sms = _inbound()
        tid = thread.get("external_id") or thread["thread_id"]
        if self.store.get_thread(tid) is None:  # a world-only thread (e.g. a scenario): still never sent
            self.store.add_message(channel=self.channel, thread_id=tid, text=_last_renter_text(thread),
                                   renter_name=thread.get("renter_name"))
        mod = email_channel if self.channel == "email" else sms
        draft = mod.save_reply_draft(self.store, tid, text)
        if attachments:
            draft["attachments"] = list(attachments)
        return {"status": "draft_saved", "draft_id": draft["draft_id"], "reason": draft["reason"],
                "to": draft.get("to"), "screenshot": None,
                "note": "saved as a draft in " + str(self.store.outbox_path(self.channel)) + "; nothing was sent"}


def _last_renter_text(thread: dict) -> str:
    for m in reversed(thread.get("messages", [])):
        if m.get("from") == "renter":
            return m.get("text", "")
    return "(thread started in the world, not from an inbound message)"


# ---------------------------------------------------------------- live-mode sync into world.threads

_STORES: dict[str, object] = {}

THREAD_KEYS = ("source_platform", "reply_via", "subject", "listing_ref", "contact", "lead_facts")


def sync_threads(world, channel: str | None = None) -> dict:
    """Merge inbound-store threads into world.threads (new threads appended, new messages appended).
    Returns counts. Messages are matched by id, so repeated syncs are idempotent."""
    stats = {"threads_new": 0, "messages_new": 0}
    for ch, store in _STORES.items():
        if channel and ch != channel:
            continue
        for st in store.list_threads(ch):
            wt = world.get("threads", st["thread_id"])
            if wt is None:
                wt = {"thread_id": st["thread_id"], "channel": ch, "renter_name": st.get("renter_name") or "",
                      "language": st.get("language", "en"), "messages": [], "external_id": st["thread_id"]}
                world.threads.append(wt)
                world.channels.setdefault(ch, {"posts": [], "threads": []})
                if wt["thread_id"] not in world.channels[ch]["threads"]:
                    world.channels[ch]["threads"].append(wt["thread_id"])
                stats["threads_new"] += 1
            for k in THREAD_KEYS:
                if st.get(k):
                    wt[k] = st[k]
            have = {m.get("id") for m in wt["messages"]}
            for m in st["messages"]:
                if m["id"] not in have:
                    wt["messages"].append({k: m[k] for k in ("id", "from", "text", "attachments", "ts") if k in m})
                    stats["messages_new"] += 1
    return stats


def install_sync() -> None:
    from .. import core

    core_reg = core.REGISTRY
    for name in ("list_threads", "read_thread"):
        fn = core_reg.get(name)
        if fn is None or getattr(fn, "_inbound_sync", False):
            continue

        def wrapped(world, *a, _fn=fn, **kw):
            if getattr(world, "mode", "sandbox") == "live" and _STORES:
                sync_threads(world)
            return _fn(world, *a, **kw)

        wrapped._inbound_sync = True
        wrapped._orig = fn
        wrapped.__name__ = getattr(fn, "__name__", name)
        core_reg[name] = wrapped


def uninstall_sync() -> None:
    from .. import core

    for name in ("list_threads", "read_thread"):
        fn = core.REGISTRY.get(name)
        if getattr(fn, "_inbound_sync", False):
            core.REGISTRY[name] = fn._orig
    _STORES.clear()


def register_inbound(store=None) -> dict[str, InboundAdapter]:
    """Register email + sms adapters (one shared store) and install the live-mode thread sync."""
    from .. import impl  # noqa: F401  (make sure the tool registry is populated before wrapping it)

    out = {}
    for ch in INBOUND_CHANNELS:
        a = InboundAdapter(ch, store)
        store = a.store
        register(ch, a)
        _STORES[ch] = a.store
        out[ch] = a
    install_sync()
    return out
