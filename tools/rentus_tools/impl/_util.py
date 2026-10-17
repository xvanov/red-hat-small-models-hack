"""Shared helpers for tool implementations."""
from __future__ import annotations

import re
from datetime import date, datetime

from ..errors import ToolError


def need(world, collection: str, id_value: str, label: str | None = None, list_tool: str | None = None) -> dict:
    rec = world.get(collection, id_value)
    if rec is None:
        label = label or collection.rstrip("s")
        hint = f"use {list_tool} to see valid ids" if list_tool else None
        raise ToolError("NOT_FOUND", f"no {label} with id {id_value!r}", hint=hint)
    return rec


def parse_date(s: str, arg: str) -> date:
    try:
        return date.fromisoformat(s)
    except (TypeError, ValueError):
        raise ToolError("INVALID_ARGS", f"{arg}: {s!r} is not a date (expected YYYY-MM-DD)")


def parse_dt(s: str, arg: str) -> datetime:
    try:
        return datetime.fromisoformat(s)
    except (TypeError, ValueError):
        raise ToolError("INVALID_ARGS", f"{arg}: {s!r} is not a datetime (expected YYYY-MM-DDTHH:MM)")


PHONE_RE = re.compile(r"(?<!\d)(?:\+?1[\s.\-]*)?\(?(\d{3})\)?[\s.\-]*(\d{3})[\s.\-]*(\d{4})(?!\d)")


def normalize_phone(s: str) -> str | None:
    m = PHONE_RE.search(s or "")
    return f"+1{m.group(1)}{m.group(2)}{m.group(3)}" if m else None


DOLLAR_RE = re.compile(
    r"\$\s?(\d[\d,]*(?:\.\d{1,2})?)\s*([kK])?(?![\d,])"
    r"|(?<![\w$])(\d[\d,]*(?:\.\d{1,2})?)\s*(?:dollars|dólares|dolares|usd|USD)\b")


def dollar_figures(text: str) -> list[float]:
    out = []
    for m in DOLLAR_RE.finditer(text or ""):
        raw = m.group(1) or m.group(3)
        v = float(raw.replace(",", ""))
        if m.group(2):
            v *= 1000
        out.append(v)
    return out


def num(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
