"""Serving benchmark with the operator's real request shape, at increasing concurrency.

    gym/.venv/bin/python serving/serve_bench.py --label baseline                       # decode sweep 1..128
    gym/.venv/bin/python serving/serve_bench.py --mode turn --reasoning on  --levels 32 --label think-on
    gym/.venv/bin/python serving/serve_bench.py --mode turn --reasoning off --levels 32 --label think-off

Every request carries what the operator loop sends on every turn: the real system prompt
(operator/prompts/system_v3.md + reader rules, rendered by rentus_operator.config.load_prompt) and the
real tool schemas (rentus_operator.toolbox.tool_schemas, verbose, reader on). Only the last user turn
differs per request: a synthetic renter message written for this benchmark (no real data). So the
shared prefix vLLM can cache is exactly the one production sees.

Modes
  decode  output fixed at --max-tokens (ignore_eos, thinking off): clean throughput/latency vs concurrency.
  --no-prefix-reuse  gives each request a unique cache_salt, so no request reuses another's cached prefix:
          the prefix-caching-OFF ablation without restarting the server other clients are using.
  turn    a natural agent turn: tool_choice auto, max_tokens 2048, thinking per --reasoning. Reports
          completion tokens per turn and the share of turns that came back as tool calls.

Per level it reports client-side latency/TTFT (streamed), aggregate tok/s, errors, and from vLLM's
/metrics: prefix-cache hit rate, KV-cache usage (sampled every second), running/waiting requests,
preemptions, and server-side TTFT/queue time. With --reader-probe a background loop sends one request
every 0.5 s to the second vLLM server (the reader) and records its latency under the operator load.
Results append to serving/results/serve_bench.jsonl; a markdown table goes to stdout.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import os
import random
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
for p in (HERE, REPO / "operator", REPO / "tools", REPO / "reader"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import vllm_metrics as vm  # noqa: E402
from openai import AsyncOpenAI  # noqa: E402

RESULTS = HERE / "results"

# Synthetic renter messages, written for this benchmark. Combined with a name, room and thread id so every
# request's last turn is unique and only the system prompt + tools form the shared prefix.
OPENERS = [
    "hi is the room still available?", "hello, I saw your post. is it furnished?",
    "hey, how much is the deposit for this room?", "Hola, sigue disponible el cuarto?",
    "I'm interested in the room, when can I see it?", "is the private bath room open for December?",
    "can I move in on the 1st? I have a job starting at the hospital", "is parking included?",
    "would you take 650 instead of 750?", "do you allow a small cat?", "I need something for 4 months only",
    "Me interesa el cuarto, me puedo mudar el 15 de noviembre?", "what utilities are included in the rent?",
    "my number is 919 555 0142, call me about the room", "it's me and my partner, is that ok?",
    "I'm a grad student at Duke, looking for a quiet place", "is the room near a bus line?",
    "can I see it this Saturday morning?", "is there a washer and dryer in the house?",
    "how many people live in the house right now?",
]
NAMES = ["Avery", "Jordan", "Sam", "Riley", "Casey", "Morgan", "Taylor", "Jamie", "Lucía", "Mateo", "Priya",
         "Dev", "Noah", "Emma", "Kai", "Zoe"]
ROOMS = ["R002", "R004", "R006", "R008", "R010", "R012"]
READER_MESSAGES = ["I can move in Nov 1st, it's just me", "next month probably", "sí, un año está bien",
                   "my cell is (919) 555-0187", "me and my brother, we got jobs at RTP", "around the 15th"]


def load_env():
    f = REPO / ".env"
    if f.exists():
        for line in f.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def operator_prefix():
    """(system prompt, tools) exactly as the operator loop builds them, final config (prompt v3)."""
    from rentus_operator import toolbox
    from rentus_operator.config import RunConfig, load_prompt
    cfg = RunConfig(prompt_version="v3", format_facts=True)
    facts = {"today": "2026-10-21", "spend_limit_usd": 300, "showing_hours": {"start": "10:00", "end": "18:00"}}
    return load_prompt(cfg, facts), toolbox.tool_schemas(toolbox.backend(), "verbose", True)


def user_turn(i: int) -> str:
    rnd = random.Random(i)
    name, room, text = rnd.choice(NAMES), rnd.choice(ROOMS), OPENERS[i % len(OPENERS)]
    return (f"New message on thread t_{name.lower()}_{i:05d} (marketplace) from {name}, "
            f"about listing L_{room}: {text}")


async def one_request(client, model, system, tools, i, mode, reasoning, max_tokens, salt=False):
    kw = dict(model=model, messages=[{"role": "system", "content": system}, {"role": "user", "content": user_turn(i)}],
              tools=tools, tool_choice="auto", stream=True, stream_options={"include_usage": True})
    extra = {}
    if mode == "decode":
        kw.update(max_tokens=max_tokens, temperature=1.0, top_p=0.95)
        extra = {"chat_template_kwargs": {"enable_thinking": False}, "ignore_eos": True}
    else:
        kw.update(max_tokens=2048, temperature=0.2)
        if reasoning is not None:
            extra = {"chat_template_kwargs": {"enable_thinking": reasoning}}
    if salt:   # unique cache_salt per request: no request can reuse another's cached prefix (= caching off)
        extra = {**extra, "cache_salt": f"nocache-{i}-{time.time_ns()}"}
    kw["extra_body"] = extra
    t0 = time.perf_counter()
    ttft, usage, tool_call, chunks = None, None, False, 0
    stream = await client.chat.completions.create(**kw)
    async for ch in stream:
        if ch.usage:
            usage = ch.usage
        if not ch.choices:
            continue
        d = ch.choices[0].delta
        has = bool(getattr(d, "content", None) or getattr(d, "tool_calls", None)
                   or getattr(d, "reasoning_content", None) or getattr(d, "reasoning", None))
        if has and ttft is None:
            ttft = time.perf_counter() - t0
        if getattr(d, "tool_calls", None):
            tool_call = True
        chunks += 1
    lat = time.perf_counter() - t0
    return {"lat": lat, "ttft": ttft if ttft is not None else lat,
            "out": usage.completion_tokens if usage else 0, "in": usage.prompt_tokens if usage else 0,
            "tool_call": tool_call}


async def reader_probe(stop: asyncio.Event, out: list, errors: list):
    from prompt import build_messages
    client = AsyncOpenAI(base_url=os.environ["READER_BASE_URL"], api_key=os.environ.get("READER_API_KEY") or "EMPTY",
                         max_retries=0, timeout=60)
    model = os.environ.get("READER_MODEL", "rentus-reader")
    i = 0
    while not stop.is_set():
        msg = build_messages({"today": "2026-10-21", "message": READER_MESSAGES[i % len(READER_MESSAGES)]})
        t0 = time.perf_counter()
        try:
            await client.chat.completions.create(model=model, messages=msg, max_tokens=256, temperature=0)
            out.append(time.perf_counter() - t0)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{type(e).__name__}: {e}"[:200])
        i += 1
        try:
            await asyncio.wait_for(stop.wait(), timeout=0.5)
        except asyncio.TimeoutError:
            pass
    await client.close()


def operator_busy(base, key) -> float:
    try:
        sc = vm.scrape(base, key, timeout=5)["scalars"]
        return sc.get("vllm:num_requests_running", 0.0) + sc.get("vllm:num_requests_waiting", 0.0)
    except Exception:  # noqa: BLE001
        return -1


async def run_level(a, client, system, tools, n, base, key):
    total = max(a.min_requests, a.requests_per_slot * n)
    queue = list(range(a.seed, a.seed + total))
    a.seed += total
    results, errors = [], []
    sem_q: asyncio.Queue = asyncio.Queue()
    for i in queue:
        sem_q.put_nowait(i)

    async def worker():
        while True:
            try:
                i = sem_q.get_nowait()
            except asyncio.QueueEmpty:
                return
            try:
                results.append(await one_request(client, a.model, system, tools, i, a.mode, a.reasoning_flag,
                                                 a.max_tokens, a.no_prefix_reuse))
            except Exception as e:  # noqa: BLE001
                errors.append(f"{type(e).__name__}: {e}"[:300])

    stop = asyncio.Event()
    probe_lat, probe_err = [], []
    probe = asyncio.create_task(reader_probe(stop, probe_lat, probe_err)) if a.reader_probe else None
    snap0 = vm.scrape(base, key)
    sampler = vm.GaugeSampler(base, key).start()
    t0 = time.perf_counter()
    await asyncio.gather(*(worker() for _ in range(n)))
    wall = time.perf_counter() - t0
    gauges = await asyncio.to_thread(sampler.stop)
    snap1 = vm.scrape(base, key)
    stop.set()
    if probe:
        await probe
    srv = vm.summarize(vm.delta(snap0, snap1))
    lat = [r["lat"] for r in results]
    ttft = [r["ttft"] for r in results]
    out_tok = sum(r["out"] for r in results)
    row = {
        "label": a.label, "mode": a.mode, "reasoning": a.reasoning, "concurrency": n, "requests": total,
        "ok": len(results), "errors": len(errors), "error_samples": errors[:3], "wall_s": round(wall, 2),
        "agg_out_tok_s": round(out_tok / wall, 1), "req_per_s": round(len(results) / wall, 2),
        "per_req_tok_s": round(sum(r["out"] / max(r["lat"] - r["ttft"], 1e-6) for r in results) / max(len(results), 1), 1),
        "lat_p50_s": round(vm.pct(lat, .5), 3) if lat else None, "lat_p95_s": round(vm.pct(lat, .95), 3) if lat else None,
        "ttft_p50_ms": round(1000 * vm.pct(ttft, .5)) if ttft else None,
        "ttft_p95_ms": round(1000 * vm.pct(ttft, .95)) if ttft else None,
        "prompt_tok_mean": round(sum(r["in"] for r in results) / max(len(results), 1)),
        "out_tok_mean": round(out_tok / max(len(results), 1)),
        "tool_call_share": round(sum(r["tool_call"] for r in results) / max(len(results), 1), 3),
        "server": srv, "gauges": gauges,
        "foreign_requests": max(0, srv["requests"] - len(results)),   # other clients during the run (contamination)
    }
    if a.reader_probe:
        row["reader"] = {"n": len(probe_lat), "errors": len(probe_err),
                         "p50_ms": round(1000 * vm.pct(probe_lat, .5)) if probe_lat else None,
                         "p95_ms": round(1000 * vm.pct(probe_lat, .95)) if probe_lat else None}
    return row


async def reader_idle(seconds: float) -> dict:
    stop, lat, err = asyncio.Event(), [], []
    t = asyncio.create_task(reader_probe(stop, lat, err))
    await asyncio.sleep(seconds)
    stop.set()
    await t
    return {"n": len(lat), "errors": len(err), "p50_ms": round(1000 * vm.pct(lat, .5)) if lat else None,
            "p95_ms": round(1000 * vm.pct(lat, .95)) if lat else None}


def md_table(rows: list[dict]) -> str:
    hdr = ("| N | requests (err) | agg out tok/s | per-req tok/s | p50 / p95 latency | p50 / p95 TTFT | "
           "prefix hit | KV max | running max / waiting max | reader p50 / p95 |")
    lines = [hdr, "|" + "|".join(["---"] * 10) + "|"]
    for r in rows:
        g, s = r["gauges"], r["server"]
        rd = r.get("reader") or {}
        lines.append(
            f"| {r['concurrency']} | {r['ok']} ({r['errors']}) | {r['agg_out_tok_s']:.0f} | {r['per_req_tok_s']:.0f} | "
            f"{r['lat_p50_s']:.2f} / {r['lat_p95_s']:.2f} s | {r['ttft_p50_ms']} / {r['ttft_p95_ms']} ms | "
            f"{(s['prefix_cache_hit_rate'] or 0) * 100:.1f}% | {g['kv_cache_usage_perc']['max'] * 100:.1f}% | "
            f"{g['num_requests_running']['max']:.0f} / {g['num_requests_waiting']['max']:.0f} | "
            f"{rd.get('p50_ms', '-')} / {rd.get('p95_ms', '-')} ms |")
    return "\n".join(lines)


async def main_async(a):
    load_env()
    base = os.environ.get("OPERATOR_BASE_URL") or "http://localhost:8000/v1"
    key = os.environ.get("OPERATOR_API_KEY") or "EMPTY"
    a.model = a.model or os.environ.get("OPERATOR_MODEL") or "nemotron-3.5-lightning"
    a.reasoning_flag = {"on": True, "off": False}.get(a.reasoning)
    system, tools = operator_prefix()
    client = AsyncOpenAI(base_url=base, api_key=key, max_retries=0, timeout=600)
    RESULTS.mkdir(exist_ok=True)
    rows = []
    meta = {"started": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
            "system_prompt_chars": len(system), "tools": len(tools)}
    if a.reader_probe and a.reader_idle_s > 0:
        busy = operator_busy(base, key)
        meta["reader_idle"] = await reader_idle(a.reader_idle_s)
        meta["reader_idle"]["operator_busy_at_start"] = busy
        print("reader idle:", meta["reader_idle"], flush=True)
    for n in [int(x) for x in a.levels.split(",")]:
        busy = operator_busy(base, key)
        if busy > a.max_foreign_load:
            print(f"operator busy ({busy:.0f} requests from others) before N={n}; waiting up to 120 s", flush=True)
            for _ in range(24):
                await asyncio.sleep(5)
                busy = operator_busy(base, key)
                if busy <= a.max_foreign_load:
                    break
        row = await run_level(a, client, system, tools, n, base, key)
        row.update(meta, busy_before=busy)
        rows.append(row)
        with open(RESULTS / "serve_bench.jsonl", "a") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"N={n}: {row['agg_out_tok_s']} tok/s, p50 {row['lat_p50_s']} s, TTFT p50 {row['ttft_p50_ms']} ms, "
              f"hit {row['server']['prefix_cache_hit_rate']}, err {row['errors']}, foreign {row['foreign_requests']}",
              flush=True)
    await client.close()
    print(f"\n### {a.label} ({a.mode}, reasoning {a.reasoning}) {meta['started']}\n")
    print(md_table(rows))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--mode", choices=["decode", "turn"], default="decode")
    ap.add_argument("--reasoning", choices=["on", "off", "default"], default="default", help="turn mode only")
    ap.add_argument("--levels", default="1,8,32,64,128")
    ap.add_argument("--requests-per-slot", type=int, default=3, help="requests per level = this x N")
    ap.add_argument("--min-requests", type=int, default=12)
    ap.add_argument("--max-tokens", type=int, default=256, help="decode mode output length")
    ap.add_argument("--model")
    ap.add_argument("--reader-probe", action="store_true")
    ap.add_argument("--reader-idle-s", type=float, default=20)
    ap.add_argument("--max-foreign-load", type=float, default=2, help="wait if others have more requests in flight")
    ap.add_argument("--no-prefix-reuse", action="store_true",
                    help="unique cache_salt per request: measures prefix caching OFF without restarting vLLM")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    asyncio.run(main_async(a))


if __name__ == "__main__":
    main()
