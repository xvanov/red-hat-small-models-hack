"""Evaluate a reader backend on the held-out reader set.

Backends:
  fallback  the deterministic read_reply fallback (rentus_tools if it exposes one,
            else the operator's shim), no model at all
  endpoint  any OpenAI-compatible chat endpoint (vLLM, Lightning, the fine-tuned
            reader) with the fixed prompt in reader/prompt.py
  anthropic REFERENCE ONLY: a frontier model (default claude-opus-5-5) over the Anthropic
            Messages API via OpenCode Zen, same prompt. Never part of the running system.
            Needs the `anthropic` SDK (gym/.venv has it) and OPENCODE_API_KEY.
  claude_cli REFERENCE ONLY: a frontier model (claude-opus-5-5 or claude-fable-5-1) through the owner's
            local Claude Code CLI (`claude -p`, subscription login, no tools, no settings), same system
            prompt and user message, JSON-only answer parsed and validated by prompt.parse_output.
            Concurrency is capped at 3; rate limits back off, then stop (operator/rentus_operator/claude_code.py).

Examples:
  python reader/eval.py --backend fallback
  python reader/eval.py --backend endpoint --base-url http://localhost:8001/v1 \
      --model rentus-reader --label finetuned
  python reader/eval.py --backend endpoint --base-url $OPERATOR_BASE_URL \
      --model $OPERATOR_MODEL --label lightning --no-thinking

  python reader/eval.py --backend anthropic --label frontier-opus-5-5 --sample 400 --concurrency 8
  python reader/eval.py --backend claude_cli --model claude-opus-5-5 --label frontier-cc-opus-5-5 --sample 400 --concurrency 3

--sample N scores a seeded sample stratified by source x language x gold move-in status, and
rescores every existing <label>.<split>.preds.jsonl on the same rows (same_sample_baselines).

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
    """Find the deterministic read_reply fallback: W3's rentus_tools reader if present, else the operator shim.
    Returns (name, fn(input_dict) -> reader JSON)."""
    for p in (REPO / "tools", REPO / "operator"):
        sys.path.insert(0, str(p))
    try:
        from rentus_tools.impl.reader import read_reply_fallback
        return "rentus_tools.impl.reader.read_reply_fallback", lambda inp: read_reply_fallback(
            inp["message"], context=inp.get("context") or [], today=inp["today"])
    except ImportError:
        pass
    from rentus_operator import shim
    world = shim.new_world()

    def via_shim(inp):
        pending = pending_item(inp)
        return _unwrap(shim.call(world, "read_reply", {"text": inp["message"], **({"pending_item": pending} if pending else {})}))
    return "rentus_operator.shim.read_reply", via_shim


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
        out = fn(r["input"])
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
            except (OSError, KeyError, IndexError, json.JSONDecodeError) as e:
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


def run_anthropic(rows: list[dict], a) -> list[dict]:
    """Frontier reference: same system prompt + user message, Messages API through the anthropic SDK."""
    sys.path.insert(0, str(REPO / "operator"))
    from rentus_operator.anthropic_client import METER, make_sdk_client, messages_create
    sdk = make_sdk_client(timeout=a.timeout)

    def one(r):
        msgs = build_messages(r["input"])
        system = "\n\n".join(m["content"] for m in msgs if m["role"] == "system")
        body = {"model": a.model, "max_tokens": a.max_tokens, "system": system,
                "messages": [{"role": m["role"], "content": m["content"]} for m in msgs if m["role"] != "system"]}
        if a.effort:
            body["output_config"] = {"effort": a.effort}
        t0 = time.time()
        text, err, cost, usage = None, None, None, None
        try:
            data = messages_create(sdk, METER, **body)
            text = "".join(b.get("text", "") for b in data.get("content") or [] if b.get("type") == "text")
            cost, usage = data.get("_cost_usd"), data.get("usage")
        except Exception as e:  # noqa: BLE001 - budget cap, API errors: scored as an empty answer
            err = f"{type(e).__name__}: {str(e)[:200]}"
        return {"id": r["id"], "raw_text": text, "pred": parse_output(text) if text is not None else None,
                "error": err, "latency_s": time.time() - t0, "cost_usd": cost, "usage": usage}

    preds = []
    with ThreadPoolExecutor(max_workers=a.concurrency) as ex:
        for i, p in enumerate(ex.map(one, rows), 1):
            preds.append(p)
            if i % 50 == 0:
                print(f"  {i}/{len(rows)} spent ${METER.snapshot()['spent_usd']:.2f}", file=sys.stderr)
    return preds


def run_claude_cli(rows: list[dict], a) -> list[dict]:
    """Frontier reference via the local Claude Code CLI: same system prompt + user message, no tools."""
    sys.path.insert(0, str(REPO / "operator"))
    from rentus_operator.claude_code import BREAKER, print_json

    def one(r):
        msgs = build_messages(r["input"])
        system = "\n\n".join(m["content"] for m in msgs if m["role"] == "system")
        user = "\n\n".join(m["content"] for m in msgs if m["role"] != "system")
        t0 = time.time()
        text, err, cost, usage, models = None, None, None, None, None
        try:
            data = print_json(system, user, a.model, a.effort, timeout=a.timeout)
            text, cost, usage = data.get("result") or "", data.get("total_cost_usd"), data.get("usage")
            models = sorted((data.get("modelUsage") or {}).keys())
        except Exception as e:  # noqa: BLE001 - rate limit / CLI error: scored as an empty answer, never looped
            err = f"{type(e).__name__}: {str(e)[:200]}"
        return {"id": r["id"], "raw_text": text, "pred": parse_output(text) if text is not None else None,
                "error": err, "latency_s": time.time() - t0, "notional_cost_usd": cost, "usage": usage,
                "models": models}

    preds = []
    with ThreadPoolExecutor(max_workers=min(a.concurrency, 3)) as ex:
        for i, p in enumerate(ex.map(one, rows), 1):
            preds.append(p)
            if i % 50 == 0:
                print(f"  {i}/{len(rows)} errors {sum(1 for x in preds if x['error'])}"
                      f"{' BREAKER OPEN' if BREAKER.tripped else ''}", file=sys.stderr)
    return preds


def stratified_sample(rows: list[dict], n: int, seed: int = 0) -> list[dict]:
    """Seeded sample of n rows, proportional per stratum (source x language x gold move-in status)."""
    import random
    strata: dict[tuple, list[dict]] = {}
    for r in rows:
        g = canonical(r["output"])
        strata.setdefault((r.get("source"), g["language"], g["move_in"]["status"]), []).append(r)
    rng = random.Random(seed)
    keys = sorted(strata, key=str)
    quota = {k: len(strata[k]) * n / len(rows) for k in keys}
    take = {k: int(quota[k]) for k in keys}
    for k in sorted(keys, key=lambda k: quota[k] - take[k], reverse=True)[: n - sum(take.values())]:
        take[k] += 1   # largest remainders
    out = []
    for k in keys:
        out += rng.sample(strata[k], take[k])
    order = {r["id"]: i for i, r in enumerate(rows)}
    return sorted(out, key=lambda r: order[r["id"]])


def same_sample_baselines(rows: list[dict], split: str, skip: str) -> dict:
    """Rescore every existing full-split preds file on exactly these rows."""
    out = {}
    for f in sorted(RESULTS.glob(f"*.{split}.preds.jsonl")):
        label = f.name[: -len(f".{split}.preds.jsonl")]
        if label == skip:
            continue
        preds = [json.loads(l) for l in f.read_text().splitlines() if l.strip()]
        ids = {r["id"] for r in rows}
        sub = [p for p in preds if p["id"] in ids]
        if len(sub) == len(rows):
            m = score(rows, sub)
            out[label] = {k: m[k] for k in ("exact_match", "json_valid", "intent_f1_micro", "language_acc")}
            out[label]["vague_date_trap"] = m["vague_date_trap"]["rate"]
            out[label].update({f_: m["fields"][f_]["status_and_value_acc"] for f_ in FIELDS})
    return out


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
    exact_primary = 0
    per_row: dict[str, dict] = {}
    for r in rows:
        p = by_id.get(r["id"], {})
        pred = p.get("pred")
        if isinstance(pred, dict):
            valid_json += 1
        if schema_valid(pred):
            schema_ok += 1
        gold = canonical(r["output"])
        all_fields = True
        primary_fields = True   # Amendment 1: reason scored on STATUS only (its value is free text)
        unscorable = set(((r.get("meta") or {}).get("unscorable")) or [])
        for f in FIELDS:
            gs, gv = field_parts(f, gold)
            ps, pv = field_parts(f, pred)
            s_ok, v_ok = ps == gs, pv == gv
            if f not in unscorable:
                primary_fields &= s_ok and (v_ok or f == "reason")
            fstat[f] += s_ok
            fval[f] += v_ok
            fboth[f] += s_ok and v_ok
            all_fields &= s_ok and v_ok
        g_int = set(gold["intents"])
        raw_int = (pred or {}).get("intents")
        p_int = {i for i in raw_int if isinstance(i, str)} if isinstance(raw_int, list) else set()
        for lab in INTENTS:
            tp[lab] += lab in g_int and lab in p_int
            fp[lab] += lab not in g_int and lab in p_int
            fn_[lab] += lab in g_int and lab not in p_int
        l_ok = (pred or {}).get("language") == gold["language"]
        lang_ok += l_ok
        em = all_fields and g_int == p_int and l_ok
        em_p = primary_fields and g_int == p_int and l_ok
        exact += em
        exact_primary += em_p
        meta = r.get("meta") or {}
        per_row[r["id"]] = {"em": bool(em), "em_primary": bool(em_p),
                            "cluster": meta.get("twin_id") or meta.get("thread_id") or meta.get("dialogue_id") or r["id"]}
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
        "exact_match_primary": round(exact_primary / n, 4),
        "exact_match_primary_def": "all field statuses + lease/move-in date/phone/occupants values + intents + language; "
                                   "reason on status only; fields marked unscorable in meta skipped (Amendment 1)",
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
        "_per_row": per_row,
    }


def _sha256(path) -> str | None:
    import hashlib
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def provenance(data_path) -> dict:
    """Leakage review #8: tie every metrics file to its commit, data file and reader checkpoint."""
    import subprocess

    def git(*a):
        try:
            return subprocess.check_output(["git", *a], cwd=REPO, text=True, stderr=subprocess.DEVNULL).strip()
        except Exception:  # noqa: BLE001
            return None
    ckpt = os.environ.get("READER_CHECKPOINT")   # path to model.safetensors of the served reader, if local
    return {"commit": git("rev-parse", "HEAD"), "describe": git("describe", "--always", "--dirty"),
            "data_path": str(data_path), "data_sha256": _sha256(data_path),
            "prompt_sha256": _sha256(REPO / "reader" / "prompt.py"),
            "checkpoint_sha256": _sha256(ckpt) if ckpt else None,
            "checkpoint_note": None if ckpt else "set READER_CHECKPOINT to hash the served weights; release reader-v1 "
                                                 "model.safetensors = 877c8843... (protocol 6.1)"}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backend", choices=["fallback", "endpoint", "anthropic", "claude_cli"], required=True)
    ap.add_argument("--split", default="test", choices=["train", "dev", "test"])
    ap.add_argument("--rows-file", default=None, help="score this JSONL of reader rows instead of --split "
                    "(e.g. the twin reader test); results are named after the file stem")
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
    ap.add_argument("--effort", default="medium", help="anthropic backend: output_config.effort (model default medium)")
    ap.add_argument("--sample", type=int, default=0, help="seeded stratified sample of N rows (0 = all)")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    load_env()

    if a.rows_file:
        rows = [json.loads(l) for l in Path(a.rows_file).read_text().splitlines() if l.strip()]
        a.split = Path(a.rows_file).stem
        data_path = Path(a.rows_file)
    else:
        rows = load_rows(a.split)
        data_path = DATA / f"{a.split}.jsonl" if (DATA / f"{a.split}.jsonl").exists() else PUBLISHED / f"{a.split}.jsonl"
    if a.limit:
        rows = rows[:a.limit]
    if a.sample:
        rows = stratified_sample(rows, a.sample, a.seed)
    t0 = time.time()
    if a.backend == "fallback":
        name, preds = run_fallback(rows)
        label = a.label or "fallback"
        info = {"backend": "fallback", "impl": name}
    elif a.backend == "anthropic":
        a.model = a.model or "claude-opus-5-5"
        if a.max_tokens == 400:
            a.max_tokens = 8000   # thinking is always on for Opus 5.5 and counts against max_tokens
        preds = run_anthropic(rows, a)
        label = a.label or "frontier-" + re.sub(r"[^\w.-]", "_", a.model)
        from rentus_operator.anthropic_client import METER
        costs = [p["cost_usd"] for p in preds if p.get("cost_usd") is not None]
        info = {"backend": "anthropic", "reference_only": True, "provider": "OpenCode Zen (Anthropic Messages API)",
                "model": a.model, "effort": a.effort, "cost_usd": round(sum(costs), 4),
                "cost_per_row_usd": round(sum(costs) / len(costs), 5) if costs else None,
                "concurrency": a.concurrency, "spend": METER.snapshot()}
    elif a.backend == "claude_cli":
        sys.path.insert(0, str(REPO / "operator"))
        from rentus_operator.claude_code import BREAKER, DEFAULT_MODEL, check_model, cli_version
        a.model = check_model(a.model or DEFAULT_MODEL)
        preds = run_claude_cli(rows, a)
        label = a.label or "frontier-cc-" + re.sub(r"[^\w.-]", "_", a.model)
        costs = [p["notional_cost_usd"] for p in preds if p.get("notional_cost_usd") is not None]
        info = {"backend": "claude_cli", "reference_only": True,
                "provider": "local Claude Code CLI, owner's subscription login (claude -p, no tools, no settings)",
                "model": a.model, "cli_version": cli_version(), "effort": a.effort,
                "response_models": sorted({m for p in preds for m in (p.get("models") or [])}),
                "notional_cost_usd": round(sum(costs), 4),
                "notional_cost_note": "Claude Code's list-price estimate; billed to the subscription, not per call",
                "concurrency": min(a.concurrency, 3), "rate_limit_breaker": {"tripped": BREAKER.tripped,
                                                                             "reason": BREAKER.reason}}
    else:
        a.base_url = a.base_url or os.environ.get("READER_BASE_URL")
        a.model = a.model or os.environ.get("READER_MODEL")
        if not a.base_url or not a.model:
            ap.error("--base-url and --model (or READER_BASE_URL / READER_MODEL) are required")
        preds = run_endpoint(rows, a)
        label = a.label or re.sub(r"[^\w.-]", "_", a.model)
        info = {"backend": "endpoint", "model": a.model, "no_thinking": a.no_thinking, "json_mode": a.json_mode}
    m = {"label": label, "split": a.split, **info, "wall_s": round(time.time() - t0, 1), **score(rows, preds)}
    per_row = m.pop("_per_row")
    m["provenance"] = provenance(data_path)
    if a.sample:
        m["sample"] = {"n": len(rows), "seed": a.seed, "strata": "source x language x gold move_in status",
                       "ids": [r["id"] for r in rows]}
        m["same_sample_baselines"] = same_sample_baselines(rows, a.split, label)

    RESULTS.mkdir(exist_ok=True)
    stem = RESULTS / f"{label}.{a.split}{'.limit' + str(a.limit) if a.limit else ''}{'.sample' + str(a.sample) if a.sample else ''}"
    Path(f"{stem}.metrics.json").write_text(json.dumps(m, indent=1, ensure_ascii=False) + "\n")
    with open(f"{stem}.preds.jsonl", "w") as fh:
        for p in preds:
            fh.write(json.dumps({**p, **per_row.get(p.get("id"), {})}, ensure_ascii=False) + "\n")
    short = {k: m[k] for k in ("exact_match", "json_valid", "intent_f1_micro", "language_acc")}
    short["vague_date_trap"] = m["vague_date_trap"]["rate"]
    short.update({f: m["fields"][f]["status_and_value_acc"] for f in FIELDS})
    print(json.dumps(short))
    print(f"wrote {stem}.metrics.json")


if __name__ == "__main__":
    main()
