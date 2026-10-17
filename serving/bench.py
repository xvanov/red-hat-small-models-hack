# /// script
# requires-python = ">=3.10"
# dependencies = ["openai>=1.50"]
# ///
"""Concurrency benchmark for the operator endpoint.

    uv run serving/bench.py --label "prefix-cache on" --out serving/bench-results.md
    uv run serving/bench.py --levels 1,4,16,32 --requests-per-level 32

Each request = a ~2.5k-token shared system prompt (operator persona + tool list, the
shape our agent loop sends every turn) + a short unique user turn, streamed, with
thinking off and a fixed max_tokens so runs are comparable. Reports per level:
aggregate output tok/s, p50/p95 end-to-end latency, p50/p95 time-to-first-token.
Run it once with prefix caching on and once off (serving/start_vllm.sh PREFIX_CACHE=off)
to see the cache effect on TTFT.
"""
import argparse
import asyncio
import datetime
import os
import pathlib
import statistics
import time

from openai import AsyncOpenAI


def load_env():
    env = pathlib.Path(__file__).resolve().parent.parent / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def shared_prefix():
    rules = []
    for i in range(60):
        rules.append(
            f"Rule {i+1}: when a renter asks about room {i%12+1}, quote rent, deposit, utilities, "
            f"lease length and move-in date exactly as stored in the register; never guess a value; "
            f"if a value is missing call the matching tool, and escalate to the owner if the tool fails twice."
        )
    tools = ", ".join(f"tool_{n}(args)" for n in [
        "create_listing", "post_listing", "read_reply", "record_applicant", "match_rooms",
        "propose_showing", "market_rent", "search_vendors", "request_quote", "book_vendor", "escalate"])
    return ("You are the Rentus leasing operator. Available tools: " + tools + ".\n" + "\n".join(rules))


def pct(xs, p):
    xs = sorted(xs)
    if not xs:
        return float("nan")
    k = (len(xs) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


async def one(client, model, system, i, max_tokens):
    t0 = time.perf_counter()
    ttft = None
    ntok = 0
    stream = await client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": f"Inquiry #{i}: is room {i%12+1} still free for Nov 1, and what's the deposit? Answer in detail."}],
        max_tokens=max_tokens, temperature=1.0, top_p=0.95, stream=True,
        stream_options={"include_usage": True},
        extra_body={"chat_template_kwargs": {"enable_thinking": False}, "ignore_eos": True},
    )
    async for ch in stream:
        if ch.choices and (ch.choices[0].delta.content or getattr(ch.choices[0].delta, "reasoning_content", None)):
            if ttft is None:
                ttft = time.perf_counter() - t0
        if ch.usage:
            ntok = ch.usage.completion_tokens
    return time.perf_counter() - t0, ttft or float("nan"), ntok


async def level(client, model, system, conc, n, max_tokens):
    sem = asyncio.Semaphore(conc)
    async def run(i):
        async with sem:
            return await one(client, model, system, i, max_tokens)
    t0 = time.perf_counter()
    res = await asyncio.gather(*(run(i) for i in range(n)))
    wall = time.perf_counter() - t0
    lat = [r[0] for r in res]; ttft = [r[1] for r in res]; toks = sum(r[2] for r in res)
    return dict(conc=conc, n=n, wall=wall, tok_s=toks / wall, per_req_tok_s=statistics.mean(r[2] / r[0] for r in res),
                p50=pct(lat, .5), p95=pct(lat, .95), ttft50=pct(ttft, .5), ttft95=pct(ttft, .95))


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--levels", default="1,4,16,32")
    ap.add_argument("--requests-per-level", type=int, default=0, help="default: max(8, 2*conc)")
    ap.add_argument("--max-tokens", type=int, default=256)
    ap.add_argument("--label", default="")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    load_env()
    client = AsyncOpenAI(base_url=os.environ.get("OPERATOR_BASE_URL", "http://localhost:8000/v1"),
                         api_key=os.environ["OPERATOR_API_KEY"], timeout=600)
    model = os.environ.get("OPERATOR_MODEL", "nemotron-3.5-lightning")
    system = shared_prefix()
    await one(client, model, system, 0, 16)  # warm-up (also primes the prefix cache)
    rows = []
    for c in [int(x) for x in a.levels.split(",")]:
        n = a.requests_per_level or max(8, 2 * c)
        r = await level(client, model, system, c, n, a.max_tokens)
        rows.append(r)
        print(f"conc={c:>3} n={n:>3} agg={r['tok_s']:7.1f} tok/s per-req={r['per_req_tok_s']:6.1f} tok/s "
              f"p50={r['p50']:.2f}s p95={r['p95']:.2f}s ttft50={r['ttft50']*1000:.0f}ms ttft95={r['ttft95']*1000:.0f}ms")
    if a.out:
        p = pathlib.Path(a.out)
        lines = [f"\n### {a.label or 'run'} — {datetime.datetime.now().astimezone():%Y-%m-%d %H:%M %Z}\n",
                 f"prompt ≈ {len(system)//4} tokens shared prefix + short unique turn, output {a.max_tokens} tokens (ignore_eos), thinking off, streamed.\n",
                 "| concurrency | requests | aggregate tok/s | per-request tok/s | p50 latency | p95 latency | p50 TTFT | p95 TTFT |",
                 "|---|---|---|---|---|---|---|---|"]
        for r in rows:
            lines.append(f"| {r['conc']} | {r['n']} | {r['tok_s']:.0f} | {r['per_req_tok_s']:.0f} | {r['p50']:.2f}s | {r['p95']:.2f}s | "
                         f"{r['ttft50']*1000:.0f} ms | {r['ttft95']*1000:.0f} ms |")
        with p.open("a") as f:
            f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    asyncio.run(main())
