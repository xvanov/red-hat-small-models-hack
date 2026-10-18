"""World: the sandbox state from contracts/tools.md section 3.

One JSON document. `load()` builds it from data/published/inventory.json plus a scenario's
`initial_state` patch; `snapshot()` / `diff()` support scorers; `save()` writes it back out.

Patch semantics (scenario `initial_state`):
- dicts merge recursively;
- a list of records that carry an id key (room_id, listing_id, thread_id, renter_id, ...) is
  UPSERTED by id: matching records are deep-merged, new ones are appended;
- any other list replaces the old value;
- `{"$replace": value}` replaces the value wholesale (use it to empty or swap a record list).
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field, fields
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

PKG_DIR = Path(__file__).resolve().parent
FIXTURES = PKG_DIR / "fixtures"

POST_CHANNELS = ("marketplace", "roomies", "craigslist", "padsplit")
MSG_CHANNELS = ("sms", "email")
CHANNELS = POST_CHANNELS + MSG_CHANNELS

# id key for each record list, used by patch upserts and diff()
ID_KEYS = {
    "rooms": "room_id", "listings": "listing_id", "threads": "thread_id", "register": "renter_id",
    "calendar": "event_id", "vendors": "vendor_id", "quotes": "quote_id", "jobs": "job_id",
    "escalations": "esc_id", "messages": "id", "owner_reports": "report_id",
    "tenants": "tenant_id", "approvals": "approval_id",
}

DEFAULT_POLICY = {
    # Owner decisions D29 (docs/playbooks/owner-decisions.md): every expenditure needs the owner's
    # approval (escalate with quotes side by side); showings any free slot 8 AM to 8 PM every day,
    # never two at once; 7-day sourcing window; 2 money follow-ups, then the owner; 5-day grace.
    "spend_limit_usd": 0,
    "showing_hours": {"days": [0, 1, 2, 3, 4, 5, 6], "start": "08:00", "end": "20:00", "slot_minutes": 30},
    "lease_min_months_public": 12,
    "lease_floor_months": 6,
    "source_of_income_protected": False,
    "sourcing_window_days": 7,
    "money_followups_before_owner": 2,
    "grace_days": 5,
    "languages": {"handled": ["en", "es"], "draft_for_owner": ["ru"]},
    "payment_plan_bounds": {"split_max_payments": 2, "arrears_max_months": 3},
    "promise_bounds": {},
}


def find_repo_root(start: Path = PKG_DIR) -> Path | None:
    for p in [start, *start.parents]:
        if (p / "contracts" / "tools.md").exists():
            return p
    return None


def default_inventory_path() -> Path:
    root = find_repo_root()
    if root is None:
        raise FileNotFoundError("cannot find repo root (contracts/tools.md); pass inventory= explicitly")
    return root / "data" / "published" / "inventory.json"


def _empty_channels() -> dict:
    return {c: {"posts": [], "threads": []} for c in CHANNELS}


@dataclass
class World:
    rooms: list = field(default_factory=list)
    listings: list = field(default_factory=list)
    channels: dict = field(default_factory=_empty_channels)
    threads: list = field(default_factory=list)
    register: list = field(default_factory=list)
    calendar: list = field(default_factory=list)
    vendors: list = field(default_factory=list)
    quotes: list = field(default_factory=list)
    jobs: list = field(default_factory=list)
    escalations: list = field(default_factory=list)
    owner_reports: list = field(default_factory=list)
    tenants: list = field(default_factory=list)      # tenancy: lease, ledger, late-rent ladder, plan
    approvals: list = field(default_factory=list)    # owner pre-approvals and owner-set bounds
    policy: dict = field(default_factory=lambda: copy.deepcopy(DEFAULT_POLICY))
    clock: dict = field(default_factory=lambda: {"now": "2026-10-17T09:00:00"})
    faults: list = field(default_factory=list)
    mode: str = "sandbox"          # "sandbox" | "live" (live routes publish/send through rentus_tools.live)
    counters: dict = field(default_factory=dict)
    meta: dict = field(default_factory=dict)

    # ---- serialization -------------------------------------------------
    def to_dict(self) -> dict:
        return {f.name: copy.deepcopy(getattr(self, f.name)) for f in fields(self)}

    @classmethod
    def from_dict(cls, d: dict) -> "World":
        names = {f.name for f in fields(cls)}
        w = cls(**{k: copy.deepcopy(v) for k, v in d.items() if k in names})
        w.channels = {**_empty_channels(), **(w.channels or {})}
        for ch in w.channels.values():
            ch.setdefault("posts", [])
            ch.setdefault("threads", [])
        w.policy = {**copy.deepcopy(DEFAULT_POLICY), **(w.policy or {})}
        w._normalize()
        return w

    def snapshot(self) -> dict:
        return self.to_dict()

    def save(self, path: str | Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False))

    # ---- helpers used by tools ----------------------------------------
    def now(self) -> datetime:
        return datetime.fromisoformat(self.clock["now"])

    def today(self) -> str:
        return self.now().date().isoformat()

    def advance(self, minutes: int = 0, **kw) -> None:
        """Move the sandbox clock forward (scenarios and the gym drive time; tools never read the wall clock)."""
        self.clock["now"] = (self.now() + timedelta(minutes=minutes, **kw)).isoformat(timespec="seconds")

    def next_id(self, prefix: str, width: int = 3) -> str:
        n = self.counters.get(prefix, 0) + 1
        self.counters[prefix] = n
        return f"{prefix}{n:0{width}d}"

    def get(self, collection: str, id_value: str) -> dict | None:
        key = ID_KEYS[collection]
        for rec in getattr(self, collection):
            if rec.get(key) == id_value:
                return rec
        return None

    def _normalize(self) -> None:
        for r in self.rooms:
            # inventory.json uses `address`; the contract calls it `address_public`. Keep both.
            if "address_public" not in r and "address" in r:
                r["address_public"] = r["address"]
            r.setdefault("photos", [])
        for t in self.threads:
            t.setdefault("messages", [])
            t.setdefault("language", "en")
            ch = t.get("channel")
            if ch in self.channels and t["thread_id"] not in self.channels[ch]["threads"]:
                self.channels[ch]["threads"].append(t["thread_id"])
            for i, m in enumerate(t["messages"]):
                m.setdefault("id", f"{t['thread_id']}-m{i + 1}")
                m.setdefault("attachments", [])
                m.setdefault("ts", self.clock["now"])
        # keep counters ahead of any ids that came in through a patch
        prefixes = {"listings": ("L", "listing_id"), "calendar": ("E", "event_id"), "quotes": ("Q", "quote_id"),
                    "jobs": ("J", "job_id"), "escalations": ("ESC", "esc_id"), "threads": ("T", "thread_id")}
        for coll, (prefix, key) in prefixes.items():
            for rec in getattr(self, coll):
                v = str(rec.get(key, ""))
                if v.startswith(prefix) and v[len(prefix):].isdigit():
                    self.counters[prefix] = max(self.counters.get(prefix, 0), int(v[len(prefix):]))


# ---- patch / merge ---------------------------------------------------------

def _id_key_for(items: list, name: str | None = None) -> str | None:
    if not items or not all(isinstance(x, dict) for x in items):
        return None
    if name in ID_KEYS:
        return ID_KEYS[name] if all(ID_KEYS[name] in x for x in items) else None
    for k in ID_KEYS.values():
        if all(k in x for x in items):
            return k
    return None


def merge(base: Any, patch: Any, name: str | None = None) -> Any:
    if isinstance(patch, dict) and set(patch) == {"$replace"}:
        return copy.deepcopy(patch["$replace"])
    if isinstance(base, dict) and isinstance(patch, dict):
        out = dict(base)
        for k, v in patch.items():
            out[k] = merge(base.get(k), v, k) if k in base else merge(None, v, k)
        return out
    if isinstance(base, list) and isinstance(patch, list):
        key = _id_key_for(patch, name)
        if key and _id_key_for(base, name) in (key, None):
            out = [copy.deepcopy(x) for x in base]
            index = {x.get(key): i for i, x in enumerate(out)}
            for item in patch:
                if item[key] in index:
                    out[index[item[key]]] = merge(out[index[item[key]]], item)
                else:
                    index[item[key]] = len(out)
                    out.append(merge(None, item))
            return out
    if isinstance(patch, dict):
        return {k: merge(None, v) for k, v in patch.items()}
    return copy.deepcopy(patch)


def load(inventory: str | Path | dict | None = None, patch: dict | None = None, *,
         vendors: str | Path | list | None = None) -> World:
    """Build a World from the inventory (path or dict; default data/published/inventory.json),
    the vendor fixtures (default rentus_tools/fixtures/vendors.json) and an optional scenario patch."""
    if inventory is None:
        inventory = default_inventory_path()
    inv = json.loads(Path(inventory).read_text()) if isinstance(inventory, (str, Path)) else copy.deepcopy(inventory)
    if vendors is None:
        vendors = FIXTURES / "vendors.json"
    vend = json.loads(Path(vendors).read_text()) if isinstance(vendors, (str, Path)) else copy.deepcopy(vendors)
    if isinstance(vend, dict):
        vend = vend.get("vendors", [])

    base: dict = {"rooms": inv.get("rooms", []), "vendors": vend}
    if inv.get("generated"):
        base["clock"] = {"now": f"{inv['generated']}T09:00:00"}
    # an inventory that already is a saved World passes straight through
    for k in ("listings", "channels", "threads", "register", "calendar", "quotes", "jobs", "escalations",
              "owner_reports", "tenants", "approvals", "policy", "clock", "faults", "mode", "counters", "meta"):
        if k in inv:
            base[k] = inv[k]
    state = merge(base, patch or {})
    return World.from_dict(state)


def load_file(path: str | Path) -> World:
    """Load a World previously written by World.save()."""
    return World.from_dict(json.loads(Path(path).read_text()))


# ---- diff --------------------------------------------------------------------

def diff(before: dict | World, after: dict | World, path: str = "", name: str | None = None) -> list[dict]:
    """Structural diff. Record lists are compared by id, so a path looks like
    `register[renter:maria].gate.move_in.date` (the same syntax scenario checks use)."""
    if isinstance(before, World):
        before = before.to_dict()
    if isinstance(after, World):
        after = after.to_dict()
    out: list[dict] = []
    if isinstance(before, dict) and isinstance(after, dict):
        for k in sorted(set(before) | set(after), key=str):
            p = f"{path}.{k}" if path else str(k)
            if k not in before:
                out.append({"path": p, "op": "add", "after": after[k]})
            elif k not in after:
                out.append({"path": p, "op": "remove", "before": before[k]})
            else:
                out.extend(diff(before[k], after[k], p, str(k)))
        return out
    if isinstance(before, list) and isinstance(after, list):
        key = _id_key_for(before + after, name) if (before or after) else None
        if key:
            b = {x[key]: x for x in before}
            a = {x[key]: x for x in after}
            for i in list(b) + [i for i in a if i not in b]:
                p = f"{path}[{i}]"
                if i not in a:
                    out.append({"path": p, "op": "remove", "before": b[i]})
                elif i not in b:
                    out.append({"path": p, "op": "add", "after": a[i]})
                else:
                    out.extend(diff(b[i], a[i], p))
            return out
    if before != after:
        out.append({"path": path, "op": "change", "before": before, "after": after})
    return out


def get_path(state: dict | World, path: str) -> Any:
    """Resolve a check path such as `register[renter:maria].gate.move_in.date`. Returns None if absent."""
    import re
    if isinstance(state, World):
        state = state.to_dict()
    cur: Any = state
    name = None
    for part in re.findall(r"[^.\[\]]+|\[[^\]]*\]", path):
        if cur is None:
            return None
        if part.startswith("["):
            ident = part[1:-1]
            if isinstance(cur, list):
                if ident.lstrip("-").isdigit():
                    i = int(ident)
                    cur = cur[i] if -len(cur) <= i < len(cur) else None
                else:
                    key = _id_key_for(cur, name)
                    cur = next((x for x in cur if key and x.get(key) == ident), None)
            else:
                cur = cur.get(ident) if isinstance(cur, dict) else None
        else:
            cur = cur.get(part) if isinstance(cur, dict) else None
            name = part
    return cur
