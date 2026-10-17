"""Evaluate a reader backend on the held-out reader set.

Backends:
  fallback  the deterministic read_reply fallback (rentus_tools if it exposes one,
            else the operator's shim), no model at all
  endpoint  any OpenAI-compatible chat endpoint (vLLM, Lightning, the fine-tuned
            reader) with the fixed prompt in reader/prompt.py

Examples:
  python reader/eval.py --backend fallback
  python reader/eval.py --backend endpoint --base-url http://localhost:8001/v1 \
      --model rentus-reader --label finetuned
  python reader/eval.py --backend endpoint --base-url $OPERATOR_BASE_URL \
      --model $OPERATOR_MODEL --label lightning --no-thinking

Writes reader/results/<label>.<split>.metrics.json and .preds.jsonl.
Metrics: exact match, per-field status / value accuracy, JSON validity, intent
F1 (micro + macro), language accuracy, and the vague-date trap rate.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
from prompt import FIELDS, INTENTS, build_messages, canonical, parse_output, schema_valid  # noqa: E402

DATA = REPO / "data" / "processed" / "reader"
PUBLISHED = REPO / "data" / "published" / "reader"
RESULTS = HERE / "results"


def load_env(path: Path = REPO / ".env") -> None:
    """Load KEY=VALUE lines into os.environ without overriding or printing anything."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def load_rows(split: str) -> list[dict]:
    path = DATA / f"{split}.jsonl"
    if not path.exists():
        path = PUBLISHED / f"{split}.jsonl"
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


# ---------------------------------------------------------------- backends

def _fallback_fn():
    """Find the deterministic read_reply fallback. Prefer rentus_tools (W3), else the operator shim."""
    for p in (REPO / "tools", REPO / "operator"):
        sys.path.insert(0, str(p))
    try:  # W3's package, if it exposes a plain function
        import importlib
        for mod in ("rentus_tools.impl.reader", "rentus_tools.reader", "rentus_tools.impl"):
            try:
                m = importlib.import_module(mod)
            except ImportError:
                continue
            for name in ("read_reply_fallback", "read_reply"):
                fn = getattr(m, name, None)
                if callable(fn):
                    return f"{mod}.{name}", lambda text, pending: _unwrap(fn(text=text, pending_item=pending))
    except Exception:  # noqa: BLE001
        pass
    from rentus_operator import shim
    world = shim.new_world()
    return "rentus_operator.shim.read_reply", lambda text, pending: _unwrap(
        shim.call(world, "read_reply", {"text": text, **({"pending_item": pending} if pending else {})}))


def _unwrap(res):
    if isinstance(res, dict) and "ok" in res and "data" in res:
        return res["data"] if res.get("ok") else None
    return res


LEASE_Q = re.compile(r"lease|12[- ]month|year|contrato|un año", re.I)


def pending_item(inp: dict) -> str | None:
    """What the operator just asked, the only context the fallback can use."""
    ctx = inp.get("context") or []
    if ctx and ctx[-1]["role"] == "operator" and LEASE_Q.search(ctx[-1]["text"]):
        return "lease"
    return None


def run_fallback(rows: list[dict]) -> tuple[str, list[dict]]:
    name, fn = _fallback_fn()
    preds = []
    for r in rows:
        t0 = time.time()
        out = fn(r["input"]["message"], pending_item(r["input"]))
        preds.append({"id": r["id"], "raw_text": json.dumps(out, ensure_ascii=False), "pred": out,
                      "latency_s": time.time() - t0})
    return name, preds


def _post(url: str, body: dict, api_key: str, timeout: float) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def run_endpoint(rows: list[dict], a) -> list[dict]:
    url = a.base_url.rstrip("/") + "/chat/completions"
    api_key = os.environ.get(a.api_key_env, "EMPTY") if a.api_key_env else "EMPTY"
    extra = json.loads(a.extra_body) if a.extra_body else {}
    if a.no_thinking:
        extra.setdefault("chat_template_kwargs", {}).update({"enable_thinking": False})
    if a.json_mode:
        extra["response_format"] = {"type": "json_object"}

    def one(r):
        body = {"model": a.model, "messages": build_messages(r["input"]), "temperature": 0.0,
                "max_tokens": a.max_tokens, **extra}
        t0 = time.time()
        text, err = None, None
        for attempt in range(3):
            try:
                resp = _post(url, body, api_key, a.timeout)
                msg = resp["choices"][0]["message"]
                text = msg.get("content") or ""
                break
            except (urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError) as e:
                err = f"{type(e).__name__}: {str(e)[:200]}"
                time.sleep(1 + attempt)
        return {"id": r["id"], "raw_text": text, "pred": parse_output(text), "error": None if text is not None else err,
                "latency_s": time.time() - t0}

    preds = []
    with ThreadPoolExecutor(max_workers=a.concurrency) as ex:
        for i, p in enumerate(ex.map(one, rows), 1):
            preds.append(p)
            if i % 100 == 0:
                print(f"  {i}/{len(rows)}", file=sys.stderr)
    return preds


# ---------------------------------------------------------------- scoring

def _norm_val(field: str, v):
    if v is None:
        return None
    if field == "occupants":
        try:
            return int(v)
        except (TypeError, ValueError):
            return str(v)
    if field == "reason":
        return re.sub(r"\s+", " ", str(v).strip().lower().rstrip("."))
    if field == "phone":
        return re.sub(r"[^\d+]", "", str(v))
    return v


def field_parts(field: str, obj: dict | None):
    """(status, value) for one field, value = date for move_in."""
    d = (obj or {}).get(field)
    if not isinstance(d, dict):
        return None, None
    key = "date" if field == "move_in" else "value"
    return d.get("status"), _norm_val(field, d.get(key))


def score(rows: list[dict], preds: list[dict]) -> dict:
    by_id = {p["id"]: p for p in preds}
    n = len(rows)
    valid_json = schema_ok = exact = exact_raw = lang_ok = 0
    fstat = Counter()
    fval = Counter()
    fboth = Counter()
    tp, fp, fn_ = Counter(), Counter(), Counter()
    vague_total = vague_trapped = 0
    groups: dict[str, list[int]] = {}
    for r in rows:
        p = by_id.get(r["id"], {})
        pred = p.get("pred")
        if isinstance(pred, dict):
            valid_json += 1
        if schema_valid(pred):
            schema_ok += 1
        gold = canonical(r["output"])
        all_fields = True
        for f in FIELDS:
            gs, gv = field_parts(f, gold)
            ps, pv = field_parts(f, pred)
            s_ok, v_ok = ps == gs, pv == gv
            fstat[f] += s_ok
            fval[f] += v_ok
            fboth[f] += s_ok and v_ok
            all_fields &= s_ok and v_ok
        g_int = set(gold["intents"])
        p_int = set((pred or {}).get("intents") or []) if isinstance((pred or {}).get("intents"), list) else set()
        for lab in INTENTS:
            tp[lab] += lab in g_int and lab in p_int
            fp[lab] += lab not in g_int and lab in p_int
            fn_[lab] += lab in g_int and lab not in p_int
        l_ok = (pred or {}).get("language") == gold["language"]
        lang_ok += l_ok
        em = all_fields and g_int == p_int and l_ok
        exact += em
        if em and (((pred or {}).get("move_in") or {}).get("raw") or None) == gold["move_in"]["raw"]:
            exact_raw += 1
        if gold["move_in"]["status"] == "vague":
            vague_total += 1
            ps, _ = field_parts("move_in", pred)
            vague_trapped += ps in ("answered", "exception")
        for g in (f"source={r['source']}", f"language={gold['language']}"):
            groups.setdefault(g, []).append(int(em))

    def f1(t, fp_, fn__):
        p_ = t / (t + fp_) if t + fp_ else 0.0
        r_ = t / (t + fn__) if t + fn__ else 0.0
        return 2 * p_ * r_ / (p_ + r_) if p_ + r_ else 0.0

    T, FP, FN = sum(tp.values()), sum(fp.values()), sum(fn_.values())
    per_label = {lab: round(f1(tp[lab], fp[lab], fn_[lab]), 4) for lab in INTENTS}
    lat = sorted(p.get("latency_s", 0) for p in preds)
    return {
        "n": n,
        "exact_match": round(exact / n, 4),
        "exact_match_with_raw_span": round(exact_raw / n, 4),
        "json_valid": round(valid_json / n, 4),
        "schema_valid": round(schema_ok / n, 4),
        "fields": {f: {"status_acc": round(fstat[f] / n, 4), "value_acc": round(fval[f] / n, 4),
                       "status_and_value_acc": round(fboth[f] / n, 4)} for f in FIELDS},
        "intent_f1_micro": round(f1(T, FP, FN), 4),
        "intent_f1_macro": round(sum(per_label.values()) / len(per_label), 4),
        "intent_f1_per_label": per_label,
        "language_acc": round(lang_ok / n, 4),
        "vague_date_trap": {"rate": round(vague_trapped / vague_total, 4) if vague_total else None,
                            "trapped": vague_trapped, "vague_rows": vague_total},
        "exact_match_by_group": {g: round(sum(v) / len(v), 4) for g, v in sorted(groups.items())},
        "errors": sum(1 for p in preds if p.get("error")),
        "latency_s": {"p50": round(lat[len(lat) // 2], 3) if lat else None,
                      "p95": round(lat[int(len(lat) * 0.95)], 3) if lat else None},
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backend", choices=["fallback", "endpoint"], required=True)
    ap.add_argument("--split", default="test", choices=["train", "dev", "test"])
    ap.add_argument("--limit", type=int, default=0, help="first N rows only (0 = all)")
    ap.add_argument("--base-url", default=None)
    ap.add_argument("--model", default=None)
    ap.add_argument("--api-key-env", default=None, help="name of the env var holding the API key")
    ap.add_argument("--label", default=None, help="results file name (default: backend or model)")
    ap.add_argument("--concurrency", type=int, default=32)
    ap.add_argument("--max-tokens", type=int, default=400)
    ap.add_argument("--timeout", type=float, default=120)
    ap.add_argument("--no-thinking", action="store_true", help="send chat_template_kwargs.enable_thinking=false")
    ap.add_argument("--json-mode", action="store_true", help="send response_format json_object")
    ap.add_argument("--extra-body", default=None, help="JSON merged into the request body")
    a = ap.parse_args()
    load_env()

    rows = load_rows(a.split)
    if a.limit:
        rows = rows[:a.limit]
    t0 = time.time()
    if a.backend == "fallback":
        name, preds = run_fallback(rows)
        label = a.label or "fallback"
        info = {"backend": "fallback", "impl": name}
    else:
        a.base_url = a.base_url or os.environ.get("READER_BASE_URL")
        a.model = a.model or os.environ.get("READER_MODEL")
        if not a.base_url or not a.model:
            ap.error("--base-url and --model (or READER_BASE_URL / READER_MODEL) are required")
        preds = run_endpoint(rows, a)
        label = a.label or re.sub(r"[^\w.-]", "_", a.model)
        info = {"backend": "endpoint", "model": a.model, "no_thinking": a.no_thinking, "json_mode": a.json_mode}
    m = {"label": label, "split": a.split, **info, "wall_s": round(time.time() - t0, 1), **score(rows, preds)}

    RESULTS.mkdir(exist_ok=True)
    stem = RESULTS / f"{label}.{a.split}{'.limit' + str(a.limit) if a.limit else ''}"
    Path(f"{stem}.metrics.json").write_text(json.dumps(m, indent=1, ensure_ascii=False) + "\n")
    with open(f"{stem}.preds.jsonl", "w") as fh:
        for p in preds:
            fh.write(json.dumps(p, ensure_ascii=False) + "\n")
    short = {k: m[k] for k in ("exact_match", "json_valid", "intent_f1_micro", "language_acc")}
    short["vague_date_trap"] = m["vague_date_trap"]["rate"]
    short.update({f: m["fields"][f]["status_and_value_acc"] for f in FIELDS})
    print(json.dumps(short))
    print(f"wrote {stem}.metrics.json")


if __name__ == "__main__":
    main()
