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
