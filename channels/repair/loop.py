"""The self-repair loop.

When the Runner can't find an element (PAGE_CHANGED), it calls Repairer.repair():
  1. capture the page (interactive elements + repeated data elements + ARIA snapshot)
  2. ask the proposer (the operator model) for the element that plays the same role
  3. validate every proposal against the live page (unique, visible, right kind, id pattern)
  4. write the winner back into the selector file with a changelog entry, plus a global log line
  5. the Runner retries the step with the new selector
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from ..adapters.engine import save_spec, try_selector
from . import snapshot as snap_mod

FIELD_ACTIONS = {"fill", "select", "choose", "check", "upload"}
CHANGELOG = Path(__file__).resolve().parent / "changelog.jsonl"


class Repairer:
    def __init__(self, proposer, changelog_path: Path | None = None, timeout_ms: int = 1500, log=None):
        self.proposer = proposer
        self.changelog_path = Path(changelog_path or CHANGELOG)
        self.timeout_ms = timeout_ms
        self.log = log or (lambda msg: None)

    def _validate_rows_from(self, page, prop: dict) -> bool:
        """For message rows, every element's author marker must map to renter/operator."""
        if "from_attr" not in prop:
            return True
        attr, fmap = prop["from_attr"], prop.get("from_map") or {}
        if attr == "class":
            vals = page.locator(prop["selector"]).evaluate_all("els => els.map(e => e.className)")
            return all(any(c in fmap for c in v.split()) for v in vals)
        vals = page.locator(prop["selector"]).evaluate_all(
            f"els => els.map(e => e.getAttribute({json.dumps(attr)}))")
        return bool(vals) and all(v in fmap and fmap[v] in ("renter", "operator") for v in vals)

    def repair(self, page, spec: dict, spec_path: Path, key: str, *, platform: str, target: str,
               exclude: list[str] | None = None) -> dict | None:
        el = spec["elements"][key]
        t0 = time.time()
        snap = snap_mod.capture(page)
        # a form field's selector may not already belong to a different form field
        taken = [o["selector"] for k, o in spec["elements"].items()
                 if k != key and o.get("action") in FIELD_ACTIONS and el.get("action") in FIELD_ACTIONS]
        excluded = list(dict.fromkeys((exclude or []) + taken))
        task = {"key": key, "element": el, "snapshot": snap, "platform": platform, "target": target,
                "exclude": excluded, "rejected": list(exclude or [])}
        try:
            proposals = self.proposer.propose(task)
        except Exception as e:  # model down or bad response: report, don't crash the adapter
            self._log_line({"ts": _now(), "platform": platform, "target": target, "element": key,
                            "result": "proposer_error", "error": str(e)[:300]})
            return None
        tried = []
        for prop in proposals:
            sel = prop.get("selector")
            if not sel or sel == el.get("selector") or sel in excluded:
                tried.append({"selector": sel, "valid": False, "why": "old, rejected or taken"})
                continue
            trial = dict(el, selector=sel)
            for k in ("attr", "from_attr", "from_map"):
                if k in prop:
                    trial[k] = prop[k]
            loc = try_selector(page, sel, trial, self.timeout_ms)
            ok = loc is not None
            if ok and el.get("action") in FIELD_ACTIONS and _same_as_any(page, loc, taken):
                ok = False
            if ok and el.get("action") == "rows":
                ok = self._validate_rows_from(page, prop)
            tried.append({"selector": sel, "valid": ok})
            if not ok:
                continue
            entry = {"ts": _now(), "element": key, "old": el.get("selector"), "new": sel,
                     "proposed_by": prop.get("by", getattr(self.proposer, "name", "?")),
                     "reason": prop.get("reason", ""), "url": snap["url"],
                     "seconds": round(time.time() - t0, 2)}
            for k in ("attr", "from_attr", "from_map"):
                if k in prop and prop[k] != el.get(k):
                    entry[f"new_{k}"] = prop[k]
            el.update({k: v for k, v in trial.items() if k in ("selector", "attr", "from_attr", "from_map")})
            spec.setdefault("changelog", []).append(entry)
            save_spec(spec_path, spec)
            self._log_line(dict(entry, platform=platform, target=target, result="repaired", tried=tried))
            self.log(f"repaired {platform}.{key}: {entry['old']} -> {sel} ({entry['proposed_by']})")
            return entry
        self._log_line({"ts": _now(), "platform": platform, "target": target, "element": key,
                        "result": "no_valid_proposal", "excluded": excluded, "tried": tried,
                        "proposed_by": getattr(self.proposer, "name", "?")})
        return None

    def _log_line(self, obj: dict) -> None:
        self.changelog_path.parent.mkdir(parents=True, exist_ok=True)
        with self.changelog_path.open("a") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")




def revert(spec: dict, spec_path: Path, entry: dict, why: str) -> None:
    """Undo an accepted repair that turned out wrong (e.g. clicking it did not advance the form)."""
    el = spec["elements"][entry["element"]]
    el["selector"] = entry["old"]
    spec.setdefault("changelog", []).append({"ts": _now(), "element": entry["element"], "old": entry["new"],
                                             "new": entry["old"], "proposed_by": "verifier", "reason": why})
    save_spec(spec_path, spec)


def _same_as_any(page, loc, selectors: list[str]) -> bool:
    """True if the element `loc` points at is the element some other field's selector points at."""
    handles = []
    for s in selectors:
        try:
            handles += page.locator(s).element_handles()
        except Exception:
            continue
    if not handles:
        return False
    try:
        return bool(loc.evaluate("(el, others) => others.some(o => o === el)", handles))
    except Exception:
        return False
