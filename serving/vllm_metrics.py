"""Read vLLM's Prometheus /metrics and turn two snapshots into a per-run summary.

Used by serving/serve_bench.py and serving/agent_load.py. Standard library only.

    snap0 = scrape(base, key); ...run...; snap1 = scrape(base, key)
    d = delta(snap0, snap1)          # counters and histogram buckets, summed over label sets
    hist_quantile(d, "vllm:time_to_first_token_seconds", 0.95)
    sampler = GaugeSampler(base, key).start(); ...; sampler.stop() -> {"kv_cache_usage_perc": {"mean", "max"}, ...}
"""
from __future__ import annotations

import math
import re
import threading
import time
import urllib.request
from collections import defaultdict

_LINE = re.compile(r'^([a-zA-Z_:][a-zA-Z0-9_:]*)(\{([^}]*)\})?\s+([-+0-9.eEInfa]+)$')
_LE = re.compile(r'le="([^"]+)"')


def metrics_url(base_url: str) -> str:
    """http://host:port/v1 -> http://host:port/metrics"""
    b = base_url.rstrip("/")
    return (b[:-3] if b.endswith("/v1") else b) + "/metrics"


def scrape(base_url: str, api_key: str | None = None, timeout: float = 10.0) -> dict:
    """{"scalars": {name: summed value}, "buckets": {hist name: {le: summed count}}, "t": time}"""
    req = urllib.request.Request(metrics_url(base_url),
                                 headers={"Authorization": f"Bearer {api_key}"} if api_key else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        text = r.read().decode()
    scalars: dict[str, float] = defaultdict(float)
    buckets: dict[str, dict[float, float]] = defaultdict(lambda: defaultdict(float))
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        m = _LINE.match(line)
        if not m:
            continue
        name, labels, val = m.group(1), m.group(3) or "", float(m.group(4))
        if name.endswith("_bucket"):
            le = _LE.search(labels)
            if le:
                buckets[name[:-7]][float(le.group(1))] += val
            continue
        if name.endswith("_created"):
            continue
        if name == "vllm:num_requests_waiting_by_reason":
            continue
        scalars[name] += val
    return {"scalars": dict(scalars), "buckets": {k: dict(v) for k, v in buckets.items()}, "t": time.time()}


def delta(a: dict, b: dict) -> dict:
    """b - a for counters/histograms. Gauges are taken from b (use GaugeSampler for gauges over time)."""
    sc = {k: b["scalars"].get(k, 0.0) - a["scalars"].get(k, 0.0) for k in b["scalars"]}
    bk = {h: {le: c - a["buckets"].get(h, {}).get(le, 0.0) for le, c in bs.items()} for h, bs in b["buckets"].items()}
    return {"scalars": sc, "buckets": bk, "seconds": b["t"] - a["t"]}


def hist_quantile(d: dict, name: str, q: float) -> float | None:
    """Quantile from cumulative histogram buckets, linear interpolation inside the bucket (Prometheus style)."""
    bs = d["buckets"].get(name)
    if not bs:
        return None
    les = sorted(bs)
    total = bs[les[-1]]
    if total <= 0:
        return None
    rank = q * total
    prev_le, prev_c = 0.0, 0.0
    for le in les:
        c = bs[le]
        if c >= rank:
            if math.isinf(le):
                return prev_le
            if c == prev_c:
                return le
            return prev_le + (le - prev_le) * (rank - prev_c) / (c - prev_c)
        prev_le, prev_c = le, c
    return prev_le


def hist_mean(d: dict, name: str) -> float | None:
    s, c = d["scalars"].get(name + "_sum"), d["scalars"].get(name + "_count")
    return (s / c) if s is not None and c else None


def summarize(d: dict) -> dict:
    """The server-side numbers every benchmark reports."""
    s = d["scalars"]
    q, h = s.get("vllm:prefix_cache_queries_total", 0.0), s.get("vllm:prefix_cache_hits_total", 0.0)
    out = {
        "requests": int(s.get("vllm:request_success_total", 0)),
        "prompt_tokens": int(s.get("vllm:prompt_tokens_total", 0)),
        "generation_tokens": int(s.get("vllm:generation_tokens_total", 0)),
        "prefix_cache_hit_rate": round(h / q, 4) if q else None,
        "prompt_tokens_cached": int(s.get("vllm:prompt_tokens_cached_total", 0)),
        "preemptions": int(s.get("vllm:num_preemptions_total", 0)),
        "tool_parser_invocations": int(s.get("vllm:tool_call_parser_invocations_total", 0)),
        "seconds": round(d["seconds"], 1),
    }
    for key, name in (("ttft", "vllm:time_to_first_token_seconds"), ("e2e", "vllm:e2e_request_latency_seconds"),
                      ("queue", "vllm:request_queue_time_seconds"), ("itl", "vllm:inter_token_latency_seconds"),
                      ("prefill", "vllm:request_prefill_time_seconds")):
        p50, p95 = hist_quantile(d, name, 0.5), hist_quantile(d, name, 0.95)
        out[f"server_{key}_p50_s"] = round(p50, 4) if p50 is not None else None
        out[f"server_{key}_p95_s"] = round(p95, 4) if p95 is not None else None
    return out


class GaugeSampler:
    """Polls gauges every `every` seconds in a thread: KV cache usage, running and waiting requests."""
    GAUGES = ("vllm:kv_cache_usage_perc", "vllm:num_requests_running", "vllm:num_requests_waiting")

    def __init__(self, base_url: str, api_key: str | None = None, every: float = 1.0):
        self.base_url, self.api_key, self.every = base_url, api_key, every
        self.samples: dict[str, list[float]] = defaultdict(list)
        self.errors = 0
        self._stop = threading.Event()
        self._t: threading.Thread | None = None

    def _run(self):
        while not self._stop.is_set():
            try:
                sc = scrape(self.base_url, self.api_key, timeout=5)["scalars"]
                for g in self.GAUGES:
                    self.samples[g].append(sc.get(g, 0.0))
            except Exception:  # noqa: BLE001 - a missed sample is not a benchmark failure
                self.errors += 1
            self._stop.wait(self.every)

    def start(self) -> "GaugeSampler":
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()
        return self

    def stop(self) -> dict:
        self._stop.set()
        if self._t:
            self._t.join(timeout=10)
        out = {}
        for g in self.GAUGES:
            v = self.samples.get(g) or [0.0]
            out[g.split(":")[1]] = {"mean": round(sum(v) / len(v), 4), "max": round(max(v), 4)}
        out["samples"] = len(self.samples.get(self.GAUGES[0], []))
        return out


def pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    v = sorted(values)
    i = q * (len(v) - 1)
    lo, hi = math.floor(i), math.ceil(i)
    return v[lo] + (v[hi] - v[lo]) * (i - lo)
