"""Who proposes a replacement selector.

OperatorProposer  asks the operator model (Nemotron Lightning on vLLM, OpenAI-compatible API,
                  env OPERATOR_BASE_URL / OPERATOR_MODEL / OPERATOR_API_KEY). Same model as the
                  operator, so no extra parameters against the 33B budget.
HeuristicProposer deterministic word-overlap fallback for offline tests. Not a model. Every
                  changelog entry records which proposer produced the fix.

A proposer returns a list of proposals, best first:
  {"selector": str, "attr"?: str, "from_attr"?: str, "from_map"?: dict, "reason": str, "by": str}
The repair loop validates each against the live page before accepting it.
"""
from __future__ import annotations

import json
import os
import re

from .snapshot import render_for_prompt

RENTER_WORDS = {"renter", "them", "in", "incoming", "inbound", "received", "other", "guest", "buyer", "msg-in"}
OPERATOR_WORDS = {"operator", "me", "out", "outgoing", "outbound", "sent", "self", "mine", "host", "msg-out"}

SYSTEM = (
    "You repair browser automation for a rental listing tool. A CSS selector stopped matching "
    "after the website changed. Pick the element on the current page that plays the same role. "
    "Reply with one JSON object only, no prose."
)


def _words(s: str) -> set[str]:
    return {w for w in re.split(r"[^a-z0-9]+", (s or "").lower()) if len(w) > 1}


def _from_from_attrs(attrs: dict) -> tuple[str, dict] | None:
    """Find an attribute whose values split into renter-side and operator-side words."""
    for name, vals in attrs.items():
        m = {}
        for v in vals:
            toks = _words(v) | {(v or '').lower()}
            if toks & RENTER_WORDS:
                m[v] = "renter"
            elif toks & OPERATOR_WORDS:
                m[v] = "operator"
        if m and len(m) == len(vals):
            return name, m
    return None


SYNONYMS = {
    "neighborhood": {"location", "area"}, "city": {"location"}, "address": {"location", "located", "where"},
    "price": {"rent", "cost"}, "rent": {"price"}, "month": {"monthly"}, "monthly": {"month"},
    "description": {"describe", "body", "about", "tell"}, "describe": {"description", "tell"},
    "title": {"headline"}, "headline": {"title"}, "zip": {"postal"}, "postal": {"zip"},
    "available": {"move", "ready", "from"}, "bathroom": {"bath", "ensuite"}, "bath": {"bathroom", "ensuite"},
    "photos": {"pictures", "images", "photo"}, "images": {"photos", "pictures"}, "email": {"contact"},
    "laundry": {"washer", "dryer"}, "cat": {"cats"}, "dog": {"dogs"}, "friendly": {"allowed"},
    "bedrooms": {"bedroom"}, "bathrooms": {"bathroom"}, "minimum": {"shortest"}, "stay": {"lease"},
    "furnished": {"furniture"}, "size": {"size"}, "name": {"label"}, "home": {"rental", "type"},
    "next": {"continue", "advance", "save"}, "publish": {"post", "live", "submit", "send"},
    "category": {"posting"},
}
STOP = {"the", "on", "step", "field", "to", "of", "a", "an", "and", "that", "it", "from", "number", "button",
        "text", "select", "checkbox", "date", "textarea", "upload", "file", "input", "your", "this", "in",
        "is", "for", "or", "makes", "listing", "public", "never", "clicked", "live", "sites", "advances"}


def _label_words(desc: str) -> set[str]:
    """The quoted or leading label in an element description: "'Next' button ..." or "Price per month (...)"."""
    m = re.match(r"\s*'([^']+)'", desc)
    lab = m.group(1) if m else desc.split("(")[0]
    return _words(lab) - STOP


class HeuristicProposer:
    """Offline fallback, not a model: label words + synonyms, weighted by how rare a word is on the page."""
    name = "heuristic"

    def propose(self, task: dict) -> list[dict]:
        el, snap = task["element"], task["snapshot"]
        if el.get("action") == "rows":
            return self._rows(task, el, snap)
        action = el.get("action")
        label = _label_words(el.get("description", ""))
        expanded = set(label)
        for w in label:
            expanded |= SYNONYMS.get(w, set())
        context = (_words(el.get("description", "")) | _words(task["key"])) - STOP
        cands = []
        for e in snap["elements"]:
            hay = " ".join(e[k] for k in ("id", "name", "aria", "testid", "placeholder", "label", "text", "value"))
            cands.append((e, _words(hay) | _words(e["id"].replace("V2", " ")) ))
        df: dict[str, int] = {}
        for _, ws in cands:
            for w in ws:
                df[w] = df.get(w, 0) + 1
        excluded = set(task.get("exclude") or [])
        scored = []
        for e, have in cands:
            if e["selector"] in excluded:
                continue
            score = sum(3.0 / df[w] for w in expanded & have) + sum(0.5 / df[w] for w in (context - expanded) & have)
            if action == "upload":
                score += 10 if e["type"] == "file" else -10
            if action in ("click", "submit"):
                if e["tag"] == "button" or e["role"] == "button":
                    score += 0.5
                else:
                    score -= 5
            if score > 0:
                scored.append((score, e))
        scored.sort(key=lambda t: -t[0])
        return [{"selector": e["selector"], "reason": f"label/synonym overlap score {s:.2f}", "by": self.name}
                for s, e in scored[:4]]

    def _rows(self, task: dict, el: dict, snap: dict) -> list[dict]:
        pat = re.compile(el.get("attr_pattern", ".+"))
        out = []
        for r in snap["repeated"]:
            for name, vals in r["attrs"].items():
                if vals and all(v is not None and pat.search(v) for v in vals):
                    prop = {"selector": r["selector"].rsplit("[", 1)[0] + f"[{name}]", "attr": name,
                            "reason": f"{name} values match {pat.pattern}", "by": self.name}
                    if el.get("from_attr"):
                        fm = _from_from_attrs(r["attrs"]) or _from_from_attrs(
                            {"class": [c for c in r["classes"].split() if c]})
                        if not fm:
                            continue
                        prop["from_attr"], prop["from_map"] = fm
                    out.append(prop)
        return out


class OperatorProposer:
    name = "operator"

    def __init__(self, base_url: str | None = None, model: str | None = None, api_key: str | None = None,
                 timeout: float = 60.0):
        self.base_url = (base_url or os.environ.get("OPERATOR_BASE_URL") or "http://localhost:8000/v1").rstrip("/")
        self.model = model or os.environ.get("OPERATOR_MODEL") or ""
        self.api_key = api_key or os.environ.get("OPERATOR_API_KEY") or "EMPTY"
        self.timeout = timeout
        self.last_raw: str | None = None

    def available(self) -> bool:
        import httpx

        try:
            r = httpx.get(f"{self.base_url}/models", headers={"Authorization": f"Bearer {self.api_key}"}, timeout=3)
            if r.status_code != 200:
                return False
            if not self.model:
                self.model = r.json()["data"][0]["id"]
            return True
        except Exception:
            return False

    def _prompt(self, task: dict) -> str:
        el = task["element"]
        rows = el.get("action") == "rows"
        listing = render_for_prompt(task["snapshot"], rows=rows)
        want = {"index": "number of the element in the list", "selector": "optional better selector",
                "reason": "short"}
        if rows:
            want = {"index": "number of the repeated-element group", "attr": "attribute that holds the id",
                    "from_attr": "attribute (or 'class') that says who wrote a message, if asked",
                    "from_map": "map from that attribute's values to 'renter' or 'operator', if asked",
                    "reason": "short"}
        return (
            f"Page: {task['snapshot']['title']} ({task['snapshot']['url']})\n"
            f"Broken element key: {task['key']}\n"
            f"What it is: {el.get('description', '')}\n"
            f"Action we perform on it: {el.get('action')}\n"
            f"Old selector (no longer matches): {el.get('selector')}\n"
            + (f"The id attribute values must match the regex {el.get('attr_pattern')}\n" if rows else "")
            + (f"We also need who wrote each message (old: {el.get('from_attr')} {el.get('from_map')})\n"
               if el.get("from_attr") else "")
            + (f"Do NOT pick these selectors (wrong or used by other fields): {task.get('exclude')}\n"
               if task.get("exclude") else "")
            + f"\nCandidates on the current page:\n{listing}\n\n"
            f"Accessibility tree (truncated):\n{task['snapshot'].get('aria', '')[:1500]}\n\n"
            f"Return JSON with keys {json.dumps(want)}."
        )

    def propose(self, task: dict) -> list[dict]:
        import httpx

        body = {
            "model": self.model, "temperature": 0, "max_tokens": 600,
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": self._prompt(task)}],
            "chat_template_kwargs": {"enable_thinking": False},
        }
        r = httpx.post(f"{self.base_url}/chat/completions", json=body, timeout=self.timeout,
                       headers={"Authorization": f"Bearer {self.api_key}"})
        r.raise_for_status()
        text = r.json()["choices"][0]["message"].get("content") or ""
        self.last_raw = text
        obj = parse_json_object(text)
        if not obj:
            return []
        snap, el = task["snapshot"], task["element"]
        by = f"operator:{self.model}"
        reason = str(obj.get("reason", ""))[:200]
        props: list[dict] = []
        idx = obj.get("index")
        if el.get("action") == "rows":
            grp = next((g for g in snap["repeated"] if g["i"] == idx), None)
            if grp and obj.get("attr"):
                sel = grp["selector"].rsplit("[", 1)[0] + f"[{obj['attr']}]"
                p = {"selector": sel, "attr": obj["attr"], "reason": reason, "by": by}
                if el.get("from_attr"):
                    if obj.get("from_attr") and isinstance(obj.get("from_map"), dict):
                        p["from_attr"], p["from_map"] = obj["from_attr"], obj["from_map"]
                    else:
                        fm = _from_from_attrs(grp["attrs"])
                        if fm:
                            p["from_attr"], p["from_map"] = fm
                props.append(p)
            return props
        cand = next((e for e in snap["elements"] if e["i"] == idx), None)
        if cand:
            props.append({"selector": cand["selector"], "reason": reason, "by": by})
        if isinstance(obj.get("selector"), str) and obj["selector"].strip():
            props.append({"selector": obj["selector"].strip(), "reason": reason, "by": by})
        return props


def parse_json_object(text: str) -> dict | None:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    text = re.sub(r"```(?:json)?", "", text)
    start = text.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(text[start:i + 1])
                        if isinstance(obj, dict):
                            return obj
                    except json.JSONDecodeError:
                        break
                    break
        start = text.find("{", start + 1)
    return None


def default_proposer():
    """The operator model when reachable; the heuristic only if CHANNELS_REPAIR_FALLBACK=heuristic."""
    op = OperatorProposer()
    if op.available():
        return op
    if os.environ.get("CHANNELS_REPAIR_FALLBACK", "") == "heuristic":
        return HeuristicProposer()
    return None
