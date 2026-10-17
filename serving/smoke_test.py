# /// script
# requires-python = ">=3.10"
# dependencies = ["openai>=1.50"]
# ///
"""Smoke test for the operator endpoint (vLLM serving Nemotron 3.5 Lightning).

    uv run serving/smoke_test.py            # reads OPERATOR_* from .env
    uv run serving/smoke_test.py --thinking off

Checks: (1) plain chat, (2) tool selection with valid JSON args out of two tools,
(3) multi-turn round trip feeding a tool result back. Prints latency per step and
whether reasoning text leaked into `content` or tool-call arguments.
"""
import argparse
import json
import os
import pathlib
import sys
import time

from openai import OpenAI


def load_env():
    env = pathlib.Path(__file__).resolve().parent.parent / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_market_rent",
            "description": "Median monthly rent for a room in a given zip code.",
            "parameters": {
                "type": "object",
                "properties": {
                    "zip_code": {"type": "string", "description": "5-digit US zip"},
                    "bedrooms": {"type": "integer", "minimum": 0},
                },
                "required": ["zip_code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_listing",
            "description": "Create a room listing draft. Does not publish it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "address": {"type": "string"},
                    "rent": {"type": "number", "description": "USD per month"},
                    "available_from": {"type": "string", "description": "ISO date YYYY-MM-DD"},
                    "private_bath": {"type": "boolean"},
                },
                "required": ["address", "rent", "available_from", "private_bath"],
            },
        },
    },
]

SYSTEM = "You are a leasing operator for a room-rental company. Use tools when they help. Today is 2026-10-17."


DASHES = dict.fromkeys(map(ord, "\u2010\u2011\u2012\u2013\u2014\u2212"), "-")


def norm(text):
    """The model sometimes writes IDs with Unicode hyphens (L\u20111042); callers must normalize."""
    return (text or "").translate(DASHES)


def has_think(text):
    return bool(text) and ("<think>" in text or "</think>" in text)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--thinking", choices=["on", "off"], default="on")
    args = ap.parse_args()
    load_env()
    base = os.environ.get("OPERATOR_BASE_URL", "http://localhost:8000/v1")
    model = os.environ.get("OPERATOR_MODEL", "nemotron-3.5-lightning")
    client = OpenAI(base_url=base, api_key=os.environ["OPERATOR_API_KEY"], timeout=300)
    extra = {"chat_template_kwargs": {"enable_thinking": args.thinking == "on"}}
    samp = dict(temperature=1.0, top_p=0.95, max_tokens=4096, extra_body=extra)
    failures = 0

    print(f"models: {[m.id for m in client.models.list().data]}  thinking={args.thinking}")

    # 1. plain chat
    t = time.perf_counter()
    r = client.chat.completions.create(model=model, messages=[
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": "In one sentence: what should a room listing always state?"}], **samp)
    dt = time.perf_counter() - t
    m = r.choices[0].message
    reasoning = getattr(m, "reasoning_content", None) or getattr(m, "reasoning", None)
    ok = bool(m.content and m.content.strip()) and not has_think(m.content)
    failures += not ok
    print(f"[1 chat] {'PASS' if ok else 'FAIL'} {dt:.2f}s tokens={r.usage.completion_tokens} "
          f"reasoning_chars={len(reasoning or '')} think_tags_in_content={has_think(m.content)}")
    print(f"         content: {m.content!r:.160}")

    # 2. tool selection
    msgs = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": "The Appling Way room is free Nov 1, $750, private bath. Draft the listing."},
    ]
    t = time.perf_counter()
    r = client.chat.completions.create(model=model, messages=msgs, tools=TOOLS, tool_choice="auto", **samp)
    dt = time.perf_counter() - t
    m = r.choices[0].message
    calls = m.tool_calls or []
    ok = False
    parsed = None
    if calls:
        c = calls[0]
        try:
            parsed = json.loads(c.function.arguments)
            ok = (c.function.name == "create_listing" and parsed.get("rent") in (750, 750.0)
                  and parsed.get("available_from") == "2026-11-01" and parsed.get("private_bath") is True)
        except json.JSONDecodeError:
            parsed = None
    failures += not ok
    print(f"[2 tool] {'PASS' if ok else 'FAIL'} {dt:.2f}s finish={r.choices[0].finish_reason} "
          f"calls={[c.function.name for c in calls]} args={parsed} "
          f"content={m.content!r:.80} think_in_args={any(has_think(c.function.arguments) for c in calls)}")

    # 3. round trip with tool result
    if calls:
        msgs.append({"role": "assistant", "content": m.content or "",
                     "tool_calls": [c.model_dump() for c in calls]})
        for c in calls:
            msgs.append({"role": "tool", "tool_call_id": c.id,
                         "content": json.dumps({"ok": True, "listing_id": "L-1042", "status": "draft"})})
        t = time.perf_counter()
        r = client.chat.completions.create(model=model, messages=msgs, tools=TOOLS, **samp)
        dt = time.perf_counter() - t
        m = r.choices[0].message
        ok = bool(m.content) and "L-1042" in norm(m.content) and not has_think(m.content)
        unicode_dash = bool(m.content) and "L-1042" not in m.content and ok
        failures += not ok
        print(f"[3 round trip] {'PASS' if ok else 'FAIL'} {dt:.2f}s finish={r.choices[0].finish_reason} "
              f"more_calls={[c.function.name for c in (m.tool_calls or [])]} unicode_dash_in_id={unicode_dash}")
        print(f"         content: {m.content!r:.200}")
    else:
        failures += 1
        print("[3 round trip] SKIP (no tool call in step 2)")

    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
