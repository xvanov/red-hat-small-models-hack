"""Small registry for extra live channels (beyond the built-in sms / email / messenger).

    from channels.live import registry
    registry.register_channel("messenger_personal", provider, world_channel="marketplace",
                              drafts_env="LIVE_PERSONAL_DRAFTS")

or, without code in this folder, via env:
    LIVE_EXTRA_CHANNELS="messenger_personal=channels.messenger_web.adapter:make_live_provider"
(each factory is called with no arguments and must return a provider).

Provider protocol (same as the built-ins):
    display: str                                    line/account label for status()
    connected() -> (bool, str)
    poll(allow: config.Allowlist, since: datetime, seen: set[str]) -> list[item]
        item = {"channel": <name>, "contact": <stable id of the other person>, "text", "ext_id" (unique message id),
                "ts" (ISO or None), "line" (optional), "renter_name" (optional), "meta": {}}
    send(contact: str, text: str) -> {"ok": bool, "provider_id", "status", "error_code", "error"}   never raises

Allowlist for an extra channel: env LIVE_ALLOW_<NAME>_IDS (comma separated contact ids), e.g.
LIVE_ALLOW_MESSENGER_PERSONAL_IDS. Messages from contacts NOT on it are ignored entirely, unless the channel's
`drafts_env` is set to 1: then the thread is stored and the operator runs, but every reply is an approval
draft (status awaiting_approval) that only the owner's Approve in the console sends.
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass

from . import config


@dataclass
class ChannelSpec:
    name: str
    provider: object
    world_channel: str = "marketplace"
    drafts_env: str | None = None

    def drafts_for_unlisted(self) -> bool:
        return bool(self.drafts_env) and (config.env(self.drafts_env, "0") or "0").strip() == "1"


EXTRA: dict[str, ChannelSpec] = {}
DEFAULT_SPECS = {"messenger_personal": {"world_channel": "marketplace", "drafts_env": "LIVE_PERSONAL_DRAFTS"}}
_LOADED = {"env": False}


def register_channel(name: str, provider, *, world_channel: str | None = None, drafts_env: str | None = None) -> None:
    d = DEFAULT_SPECS.get(name, {})
    EXTRA[name] = ChannelSpec(name, provider, world_channel or d.get("world_channel", "marketplace"),
                              drafts_env if drafts_env is not None else d.get("drafts_env"))


def unregister(name: str) -> None:
    EXTRA.pop(name, None)


def load_from_env() -> list[str]:
    """Load LIVE_EXTRA_CHANNELS once. Errors are reported, never raised."""
    if _LOADED["env"]:
        return []
    _LOADED["env"] = True
    errs = []
    for part in (config.env("LIVE_EXTRA_CHANNELS") or "").split(","):
        if "=" not in part:
            continue
        name, target = (x.strip() for x in part.split("=", 1))
        try:
            mod, fn = target.split(":", 1)
            register_channel(name, getattr(importlib.import_module(mod), fn)())
        except Exception as e:
            errs.append(f"{name}: {type(e).__name__}: {str(e)[:120]}")
    return errs


def world_channel(name: str) -> str:
    from .store import CHANNEL_WORLD
    if name in CHANNEL_WORLD:
        return CHANNEL_WORLD[name]
    return EXTRA[name].world_channel if name in EXTRA else "marketplace"
