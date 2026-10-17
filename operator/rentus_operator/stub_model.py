"""A scripted fake OpenAI-compatible client, so the loop runs with no GPU.

    client = StubClient([
        turn(call("list_rooms", area="Durham")),
        turn(call("get_room", room_id="R001"), content="Looking at it."),
        turn(content="All done."),
    ])
    client.chat.completions.create(model=..., messages=..., tools=...)

A turn may also be a function (messages) -> turn, for scripts that need ids from
earlier tool results (see tool_data). Responses are real openai ChatCompletion
objects, so the loop exercises the same parsing path as against vLLM.
"""
from __future__ import annotations

import copy
import json
import uuid
from types import SimpleNamespace

try:
    from openai.types.chat import ChatCompletion
except Exception:  # pragma: no cover - openai missing
    ChatCompletion = None


def call(name: str, **args) -> dict:
    return {"name": name, "arguments": json.dumps(args)}


def raw_call(name: str, raw: str) -> dict:
    """A tool call with literal (possibly broken) argument text."""
    return {"name": name, "arguments": raw}


def turn(*calls: dict, content: str | None = None, reasoning: str | None = None) -> dict:
    return {"content": content, "tool_calls": list(calls), "reasoning": reasoning}


def _completion(t: dict, model: str):
    tcs = [{"id": f"call_{uuid.uuid4().hex[:8]}", "type": "function",
            "function": {"name": c["name"], "arguments": c["arguments"]}} for c in t.get("tool_calls") or []]
    msg = {"role": "assistant", "content": t.get("content"), "tool_calls": tcs or None}
    if t.get("reasoning"):
        msg["reasoning_content"] = t["reasoning"]
    raw = {"id": f"chatcmpl-{uuid.uuid4().hex[:8]}", "object": "chat.completion", "created": 0, "model": model,
           "choices": [{"index": 0, "message": msg, "finish_reason": "tool_calls" if tcs else "stop"}]}
    if ChatCompletion is not None:
        return ChatCompletion.model_validate(raw)
    return raw


class _Completions:
    def __init__(self, owner):
        self.owner = owner

    def create(self, **kw):
        o = self.owner
        o.requests.append(copy.deepcopy(kw))
        if o.fail_first:
            o.fail_first -= 1
            raise ConnectionError("stub: endpoint unavailable")
        if o.script:
            t = o.script.pop(0)
            if callable(t):
                t = t(kw["messages"])
        else:
            t = turn(content=o.default_final)
        return _completion(t, kw.get("model", "stub"))


class StubClient:
    def __init__(self, script: list, default_final: str = "Done.", fail_first: int = 0):
        self.script = list(script)
        self.default_final = default_final
        self.fail_first = fail_first
        self.requests: list[dict] = []
        self.chat = SimpleNamespace(completions=_Completions(self))


# --------------------------------------------------------------------------- script helpers

def tool_data(messages: list[dict], name: str, nth: int = -1):
    """`data` of the nth result of tool `name` in the history (default: latest)."""
    names = {}
    for m in messages:
        for tc in m.get("tool_calls") or []:
            names[tc["id"]] = tc["function"]["name"]
    hits = []
    for m in messages:
        if m.get("role") == "tool" and names.get(m.get("tool_call_id")) == name:
            env = json.loads(m["content"])
            if env.get("ok"):
                hits.append(env.get("data"))
    return hits[nth] if hits else None


def listing_demo(area_hint: str = "Appling", channels=("marketplace", "roomies")) -> list:
    """Scripted run of the listing flow, used by `cli --stub`."""
    def pick(msgs):
        rooms = (tool_data(msgs, "list_rooms") or {}).get("rooms", [])
        rid = rooms[0]["room_id"] if rooms else "R001"
        return turn(call("get_room", room_id=rid), call("get_listing_media", room_id=rid),
                    reasoning="Two independent reads, call them in parallel.")

    def draft(msgs):
        r = tool_data(msgs, "get_room")["room"]
        title = f"Private room with {'private bath' if r.get('private_bath') else 'shared bath'}, ${r['rent']}/month"
        body = (f"{r.get('type', 'Room').capitalize()} in {r.get('area', '')}, available {r.get('available_from')}. "
                f"Rent ${r['rent']}, deposit ${r.get('deposit')}, utilities {r.get('utilities')}. 1 year minimum.")
        return turn(call("check_listing_compliance", text=f"{title}\n{body}"),
                    content=None, reasoning=json.dumps({"title": title, "body": body}))

    def create(msgs):
        r = tool_data(msgs, "get_room")["room"]
        title = f"Private room with {'private bath' if r.get('private_bath') else 'shared bath'}, ${r['rent']}/month"
        body = (f"{r.get('type', 'Room').capitalize()} in {r.get('area', '')}, available {r.get('available_from')}. "
                f"Rent ${r['rent']}, deposit ${r.get('deposit')}, utilities {r.get('utilities')}. 1 year minimum.")
        return turn(call("create_listing", room_id=r["room_id"], title=title, body=body, price=r["rent"]))

    def publish(msgs):
        lid = tool_data(msgs, "create_listing")["listing"]["listing_id"]
        return turn(*[call("publish_listing", listing_id=lid, channel=c) for c in channels])

    def report(msgs):
        lid = tool_data(msgs, "create_listing")["listing"]["listing_id"]
        return turn(call("report_to_owner", summary=f"Listing {lid} is live on {', '.join(channels)}."))

    return [turn(call("list_rooms", area=area_hint)), pick, draft, create, publish, report,
            turn(content=f"I published the listing on {' and '.join(channels)} and reported to the owner.")]
