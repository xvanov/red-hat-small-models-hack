# vLLM bench results — Nemotron 3.5 Lightning NVFP4 on 1x RTX Pro 6000 (Brev)

vLLM 0.27.1 (`vllm/vllm-openai:v0.27.1`), flags in `serving/start_vllm.sh`. Client runs on the laptop through the SSH tunnel, so latency includes the tunnel round trip (~tens of ms). Generated with `uv run serving/bench.py`.

### prefix caching ON, MTP off — 2026-10-17 11:37 EDT

prompt ≈ 3939 tokens shared prefix + short unique turn, output 256 tokens (ignore_eos), thinking off, streamed.

| concurrency | requests | aggregate tok/s | per-request tok/s | p50 latency | p95 latency | p50 TTFT | p95 TTFT |
|---|---|---|---|---|---|---|---|
| 1 | 8 | 254 | 254 | 1.00s | 1.04s | 163 ms | 244 ms |
| 4 | 8 | 614 | 155 | 1.66s | 1.81s | 308 ms | 607 ms |
| 16 | 32 | 1286 | 81 | 3.17s | 3.19s | 768 ms | 1039 ms |
| 32 | 64 | 1764 | 55 | 4.61s | 4.80s | 1134 ms | 1914 ms |

### prefix caching OFF, MTP off — 2026-10-17 11:41 EDT

prompt ≈ 3939 tokens shared prefix + short unique turn, output 256 tokens (ignore_eos), thinking off, streamed.

| concurrency | requests | aggregate tok/s | per-request tok/s | p50 latency | p95 latency | p50 TTFT | p95 TTFT |
|---|---|---|---|---|---|---|---|
| 1 | 8 | 243 | 246 | 1.01s | 1.27s | 208 ms | 301 ms |
| 4 | 8 | 579 | 146 | 1.77s | 1.89s | 482 ms | 710 ms |
| 16 | 32 | 878 | 57 | 4.64s | 5.40s | 1347 ms | 2201 ms |
| 32 | 64 | 1247 | 39 | 6.44s | 6.82s | 2068 ms | 3532 ms |

### prefix caching ON, MTP on (built-in heads, num_speculative_tokens=3) — 11:44 and 11:49 ET

Not measured: the engine crashed with `CUDA error: an illegal memory access` (FlashInfer attention metadata build) at concurrency 4, with async scheduling on and again with it off. Single requests worked and logged a mean acceptance length of about 3.0–3.3 (per-position acceptance ≈ 0.79 / 0.66 / 0.55). MTP is left off.

Caveat: other workstreams started calling this server around 11:45 ET, so the "prefix caching OFF" run above may include some of their traffic. Re-run both on a quiet server before quoting.

### RE-RUN prefix caching ON, MTP off — NOT a quiet server — 2026-10-17 12:13 EDT

prompt ≈ 3939 tokens shared prefix + short unique turn, output 256 tokens (ignore_eos), thinking off, streamed.

| concurrency | requests | aggregate tok/s | per-request tok/s | p50 latency | p95 latency | p50 TTFT | p95 TTFT |
|---|---|---|---|---|---|---|---|
| 1 | 8 | 30 | 30 | 8.52s | 9.41s | 325 ms | 476 ms |
| 4 | 8 | 121 | 30 | 8.45s | 8.52s | 588 ms | 602 ms |
| 16 | 32 | 390 | 25 | 10.46s | 11.26s | 1171 ms | 1939 ms |
| 32 | 64 | 670 | 21 | 12.13s | 12.97s | 2082 ms | 3430 ms |

The 12:11 ET re-run above shared the GPU with about 16 concurrent gym-agent requests (3–5k prompt tok/s) **and** the W6 reader fine-tune running on the same GPU (7 GB, GPU at 98%). Per-request speed dropped about 8x vs the 11:37 run. Use it as a "server under real team load" data point, not a clean config comparison. Soak at the same time: 16 concurrent x 160 requests x 512 tokens, 0 errors, 422 tok/s total for this client, p50 19.6 s, p95 20.7 s, while the engine reported ~530–880 tok/s generation overall and KV cache usage under 3%.

The prefix caching OFF re-run was **not** done: the server never went quiet (gym + reader training), and switching caching needs a ~2.5 min vLLM restart that would break their runs. To do it later on an idle server: `PREFIX_CACHE=off bash ~/serving/start_vllm.sh`, `uv run serving/bench.py --label ... --out serving/bench-results.md`, then `bash ~/serving/start_vllm.sh` again.

---

## 2026-10-17 21:15–21:50 ET: real operator request shape (`serving/serve_bench.py`)

Supersedes the tables above for quoting. The prompt is the operator's real one now: system prompt v3 + 26 real tool schemas = 5,973 tokens, plus one unique synthetic renter turn. Streamed, 3×N requests per level, server-side numbers from `/metrics` (`serving/vllm_metrics.py`), reader probed every 0.5 s on the second vLLM server. Raw rows: `serving/results/serve_bench.jsonl`. Full write-up and config rationale: `docs/vllm.md`.

Decode sweep (256 output tokens, thinking off, prefix caching on):

| N | requests (err) | tok/s | p50 / p95 latency | p50 / p95 TTFT | prefix hit | KV peak | running / waiting peak | reader p50 / p95 |
|---|---|---|---|---|---|---|---|---|
| 1 | 12 (0) | 219 | 1.15 / 1.26 s | 246 / 338 ms | 71.3% | 0.1% | 1 / 0 | 272 / 332 ms |
| 8 | 24 (0) | 849 | 2.43 / 2.44 s | 732 / 763 ms | 71.3% | 0.5% | 8 / 0 | 294 / 472 ms |
| 32 | 96 (0) | 1,412 | 5.81 / 5.84 s | 2,207 / 2,353 ms | 72.2% | 2.4% | 35 / 17 | 327 / 386 ms |
| 64 | 192 (0) | 1,579 | 8.90 / 15.91 s | 2,791 / 10,125 ms | 73.0% | 4.7% | 64 / 47 | 326 / 357 ms |
| 128 | 384 (0) | 1,755 | 16.85 / 21.68 s | 10,692 / 15,396 ms | 73.1% | 4.5% | 64 / 100 | 331 / 402 ms |

Reader idle baseline: 202 / 291 ms. The first N=128 attempt crashed the engine (`CUDA error: misaligned address`, 56 running); Docker restarted it in 40 s and the re-run above finished clean.

Prefix caching ON vs OFF (OFF = unique `cache_salt` per request, no restart; paired runs under the same ~6-request background load):

| N | tok/s ON / OFF | TTFT p50 ON / OFF | latency p50 ON / OFF | hit ON / OFF |
|---|---|---|---|---|
| 1 | 107 / 105 | 258 / 514 ms | 2.35 / 2.44 s | 79.7% / 0.0% |
| 8 | 584 / 459 (+27%) | 649 / 1,780 ms | 3.48 / 4.51 s | 77.3% / 0.0% |
| 32 | 1,411 / 803 (+76%) | 2,134 / 4,770 ms | 5.80 / 10.04 s | 72.5% / 1.8% |
| 64 | 1,822 / 924 (+97%) | 2,603 / 4,297 ms | 7.96 / 17.23 s | 71.0% / 0.0% |

Reasoning on vs off (natural agent turn, N=32): 6.9 vs 13.2 turns/s, 138 vs 35 output tokens per turn, p50 3.23 vs 2.41 s, p95 8.06 vs 2.58 s, 100% tool calls in both.

The hit rate caps near 71% because the hybrid-Mamba cache block is 2,128 tokens: 2 full blocks of the 5,973-token prompt = 71.3%.
