# vLLM: how we serve the Rentus Operator and what it bought us

Red Hat vLLM bounty write-up. Every number below was measured on 2026-10-17 between 21:15 and 21:50 ET on the live servers the rest of the team was using, with the scripts in `serving/`. Raw rows: `serving/results/serve_bench.jsonl` and `serving/results/agent_load.jsonl`.

## What vLLM got us

One $2.63/hr RTX Pro 6000 serves both of our models from two vLLM processes: the 30B operator (NVFP4) and the 0.6B reader. It sustains **1,411 output tok/s at 32 concurrent operator requests and 1,822 tok/s at 64**, with 0 errors in 1,650 benchmark requests, and the reader stays under **0.47 s p95** at every operator load level. Prefix caching is the biggest single win: on our real 6k-token system prompt plus 26 tool schemas it **cuts time to first token by 50 to 64% and raises throughput by 76% at N=32 and 97% at N=64**. Turning reasoning off for routine tool turns **doubles turns per second (6.9 to 13.2) and cuts p95 turn latency from 8.1 s to 2.6 s**.

## Architecture

```
laptop (operator loop, Gym, console)                 Brev instance: 1x RTX PRO 6000 Blackwell 96 GB, $2.63/hr
  rentus_operator.run ──── SSH tunnel :8000 ───────▶ vllm-operator  (docker, vllm/vllm-openai:v0.27.1)
        │  read_reply tool                            Nemotron 3.5 Lightning 30B-A3B NVFP4, 0.80 of GPU memory
        └─────────────── SSH tunnel :8011 ─────────▶ vllm-reader    (docker, same image)
                                                      rentus-reader (Qwen3-0.6B fine-tune), 0.12 of GPU memory
  serving/watchdog.sh: polls /v1/models every 30 s, one-token generation probe every ~2 min
```

- Both containers bind to `127.0.0.1` on the instance and are reachable only through the SSH tunnel. Both run with `--restart unless-stopped`, so an engine crash restarts the server without a human.
- GPU memory: operator 78.2 GB, reader 12.1 GB, 90.3 of 97.9 GB used. Operator weights take 17.9 GiB; vLLM gives the remaining 50.5 GiB to the KV cache (about 14 million tokens, from the startup log).
- Parameter budget: 30B + 0.6B, under the 33B cap. Speculative-decoding drafts would count against it, so we use none (see "What did not work").

## Configuration, flag by flag

Operator (`serving/start_vllm.sh`):

| Flag | Why |
|---|---|
| `--model nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4` | 4-bit weights: 17.9 GiB instead of about 60 GB in BF16, which is what leaves room for a 50 GiB KV cache *and* the reader on one card. On this GPU (SM120) vLLM runs NVFP4 through Marlin kernels (4-bit weights, 16-bit math). |
| `--served-model-name nemotron-3.5-lightning` | stable name for every client, independent of the checkpoint path |
| `--max-model-len 65536` | a long operator conversation (system prompt + tools + many tool results) reaches 12–20k tokens; 64k leaves headroom without shrinking the batch |
| `--gpu-memory-utilization 0.80` | the operator's share; the rest is the reader (0.12) plus slack |
| `--max-num-seqs 64` | cap on requests decoded together. At N=128 the extra 64 wait in the queue (measured below) instead of slowing every running request down |
| `--enable-prefix-caching` | every operator turn starts with the same ~6k-token system prompt + tool schemas; caching skips recomputing it. Measured below. |
| `--async-scheduling` | overlaps CPU scheduling with GPU execution, per the model card |
| `--mamba-backend flashinfer`, `--mamba-cache-mode align`, `--mamba-ssm-cache-dtype float16`, `--enable-mamba-cache-stochastic-rounding`, `--mamba-cache-philox-rounds 5` | Lightning is a hybrid Mamba/attention MoE. These are the card's settings for its state-space layers. `align` mode is what lets prefix caching work on a hybrid model: cached state is stored at block boundaries. Side effect: the cache block is **2,128 tokens** (`cache_config_info` in /metrics), so a prefix is reused only in whole 2,128-token blocks. |
| `--reasoning-parser nemotron_v3` | thinking text comes back in `reasoning_content`, never mixed into the reply or tool arguments |
| `--tool-call-parser qwen3_coder`, `--enable-auto-tool-choice` | the model's tool-call format, parsed into OpenAI `tool_calls`; the model chooses between talking and calling |
| `VLLM_API_KEY` (env file, never echoed) | bearer auth even behind the tunnel |

Defaults that matter: `max_num_batched_tokens=8192` (chunked prefill). One uncached 6k-token prompt uses most of a step's budget, so at high concurrency new requests wait for prefill. That is why caching helps time to first token so much.

Reader (`reader/serve_reader.sh`): `--gpu-memory-utilization 0.12 --max-model-len 4096 --max-num-seqs 64 --enable-prefix-caching --generation-config vllm`. The reader prompt is a fixed ~1k-token instruction block, so prefix caching applies here too.

Client side: the operator loop sends `chat_template_kwargs.enable_thinking` per turn, so a call can turn reasoning off without a server restart.

## How it was measured

`serving/serve_bench.py` sends the operator's **real** request: the system prompt rendered by `rentus_operator.config.load_prompt` (prompt v3, 5,973 tokens with tools) and the real 26 tool schemas. Only the final user turn differs, a synthetic renter message written for the benchmark. So the shared prefix vLLM can cache is exactly the one production sees. Requests are streamed. Requests per level = 3 × N. Server-side numbers come from snapshots of vLLM's Prometheus `/metrics` before and after each level (`serving/vllm_metrics.py`). KV usage and running/waiting counts are sampled every second. A background loop sends one reader request every 0.5 s and records its latency. `foreign_requests` in the raw rows counts other clients' requests that landed during a level, so contamination is visible.

Decode mode fixes output at 256 tokens (`ignore_eos`, thinking off) for clean comparisons. Turn mode lets the model answer naturally (tool choice auto, up to 2,048 tokens).

## Results

### Throughput and latency vs concurrency (decode, prefix caching on)

| N | requests (errors) | output tok/s | per-request tok/s | latency p50 / p95 | TTFT p50 / p95 | prefix hit | KV peak | running / waiting peak | reader p50 / p95 |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 12 (0) | 219 | 280 | 1.15 / 1.26 s | 246 / 338 ms | 71.3% | 0.1% | 1 / 0 | 272 / 332 ms |
| 8 | 24 (0) | 849 | 152 | 2.43 / 2.44 s | 732 / 763 ms | 71.3% | 0.5% | 8 / 0 | 294 / 472 ms |
| 32 | 96 (0) | 1,412 | 72 | 5.81 / 5.84 s | 2,207 / 2,353 ms | 72.2% | 2.4% | 35 / 17 | 327 / 386 ms |
| 64 | 192 (0) | 1,579 | 43 | 8.90 / 15.91 s | 2,791 / 10,125 ms | 73.0% | 4.7% | 64 / 47 | 326 / 357 ms |
| 128 | 384 (0) | 1,755 | 42 | 16.85 / 21.68 s | 10,692 / 15,396 ms | 73.1% | 4.5% | 64 / 100 | 331 / 402 ms |

- Throughput climbs 8x from N=1 to N=128. Past N=64 it flattens because `--max-num-seqs 64` caps the batch, and the extra requests queue (waiting peak 100 at N=128, TTFT p50 10.7 s).
- **KV cache never exceeded 5.4%.** Memory is not the limit at this prompt size; the prefill token budget and decode compute are. There is room to raise `--max-num-seqs` or `--max-num-batched-tokens` (not tested, see below).
- The hit rate sits at 71% because of the 2,128-token block: 5,973 prompt tokens hold 2 full blocks = 4,256 cacheable tokens = **71.3%, matching the measured 71.25% exactly**. Later turns of a real conversation reuse more, because each turn's history is the next turn's prefix (the 2-conversation agent smoke run below sent 12.6k-token turns).
- The N=32 row is a clean re-run. The first N=32 run overlapped 40 requests from another client and gave 1,062 tok/s.

### Ablation 1: prefix caching on vs off

Restarting vLLM with caching off would have broken other team members' running jobs (the server never went idle for 5 minutes). Instead each request got a unique `cache_salt`, a vLLM request field that isolates its cache entries, so no request can reuse another's prefix. The measured hit rate drops to 0–1.8%, which confirms it is equivalent to caching off for this workload. The ON and OFF runs were back to back under the same background traffic (about 6 requests from other clients), so the comparison is paired.

| N | tok/s ON | tok/s OFF | change | TTFT p50 ON / OFF | latency p50 ON / OFF | latency p95 ON / OFF | hit rate ON / OFF |
|---|---|---|---|---|---|---|---|
| 1 | 107 | 105 | +2% | 258 / 514 ms | 2.35 / 2.44 s | 2.54 / 2.50 s | 79.7% / 0.0% |
| 8 | 584 | 459 | **+27%** | 649 / 1,780 ms | 3.48 / 4.51 s | 3.60 / 4.60 s | 77.3% / 0.0% |
| 32 | 1,411 | 803 | **+76%** | 2,134 / 4,770 ms | 5.80 / 10.04 s | 5.88 / 12.30 s | 72.5% / 1.8% |
| 64 | 1,822 | 924 | **+97%** | 2,603 / 4,297 ms | 7.96 / 17.23 s | 12.02 / 24.33 s | 71.0% / 0.0% |

The gain grows with load because without caching every request pays a full ~6k-token prefill out of the 8,192-token step budget, so prefill crowds out decode. With caching only the ~1.7k uncached tail is computed.

### Ablation 2: reasoning on vs off (natural agent turn, N=32, caching on)

| | turns/s | output tokens per turn | latency p50 / p95 | server TTFT p50 / p95 | turns that called a tool |
|---|---|---|---|---|---|
| reasoning on | 6.9 | 138 | 3.23 / 8.06 s | 0.38 / 2.12 s | 100% |
| reasoning off | **13.2** | 35 | **2.41 / 2.58 s** | 1.06 / 2.36 s | 100% |

Reasoning off answers 1.9x more turns per second and removes the long tail (p95 8.1 to 2.6 s), with every turn still a tool call. Its quality cost is measured by the Gym, not here (`docs/results.md`: the `think_off` variant). TTFT with reasoning on counts the first thinking token. With it off the first token is the tool call, which the `qwen3_coder` parser emits once the call is complete, so the two TTFT columns are not comparable. Use latency.

### Ablation 3: max-num-seqs (not run as a restart)

Dropped from scope with the owner (a restart would have broken others' jobs). The sweep shows what the cap does. At N=64 and N=128 the running count is pinned at 64, and the requests above it wait (47 and 100 at peak). Throughput only rises 11% from N=64 to N=128 while TTFT p50 nearly quadruples. Since KV usage peaks at 5%, raising the cap is the next thing to test on an idle server.

### Ablation 4: precision (NVFP4 vs another) — skipped on Oct 17, done on Oct 18 (see "Stability")

The BF16 checkpoint is about 60 GB. Next to the 12 GB reader it would leave about 10 GB for the KV cache. It would also need a download and a restart, which other people's jobs could not absorb. Not feasible in the window, so it was not run.

### Two models on one GPU: reader latency under operator load

| operator load | reader p50 | reader p95 | reader errors |
|---|---|---|---|
| idle (30 s baseline) | 202 ms | 291 ms | 0 |
| N=8 | 294 ms | 472 ms | 0 |
| N=32 | 327 ms | 386 ms | 0 |
| N=64 | 326 ms | 357 ms | 0 |
| N=128 | 331 ms | 402 ms | 0 |
| N=64, caching off (worst case) | 333 ms | 358 ms | 0 |

The reader slows by about 60% at p50 when the operator is saturated, but it stays under half a second at every level, in 465 probe requests under load (plus 42 idle) with no errors. Splitting the card by memory fraction (0.80 / 0.12) keeps the small model responsive with no scheduler coupling between the two.

## Reliability

| Signal | Result |
|---|---|
| Benchmark requests | 1,650 sent, **0 errors** (all levels, all ablations) |
| Engine crash under load | **1**, at N=128 (21:24 ET): `CUDA error: misaligned address` with 56 requests running, KV 3.7%. Docker's restart policy brought the server back in **40 s** (crash 01:24:07 UTC, serving 01:24:47 UTC; warm engine init 9.5–11 s thanks to the compile cache). An identical N=128 re-run 2 minutes later finished 384/384 with 0 errors, so the crash is intermittent. The same class of kernel fault took down MTP earlier (README). |
| Watchdog (`serving/watchdog.sh`, 12:10–21:50 ET) | 16 missed polls, 6 tunnel restarts, every outage recovered without a human (one needed a second tunnel restart). The generation probe (a 1-token request every ~2 min, 90 s timeout) caught 2 cases where `/v1/models` answered but generation did not (12:51 and 13:51 ET, while a fine-tune shared the GPU), and restarted the engine both times. We could not tell afterwards whether those were real hangs or just very slow generation under the training load. |
| Container restarts (whole day) | 4: two deliberate MTP experiments and their rollback, plus the crash above. The watchdog's 2 engine restarts are separate `docker restart` calls. |
| Retries in the operator loop | the loop retries a failed model call up to 2 times with backoff, and the client SDK retries are off (`max_retries=0` in `agent_load.py`) so every failure is counted. The smoke run: 57 model calls, 0 errors, 0 retries. |

## Stability (Oct 18, 03:10–04:05 ET): NVFP4 crashes under load, BF16 does not

**Symptom.** The NVFP4 engine died intermittently with `CUDA error: misaligned address` in EngineCore (reported at `async_copy_ready_event.synchronize()`, native stack inside `cudaGraphLaunch`): 21:24 ET at N=128, 13:02 ET, then 02:48 and 03:05 ET under ~16 concurrent agent requests. Docker restarted it in ~40 s each time, but every in-flight request failed (52 of 99 eval rollouts had to be rerun) and the watchdog logged hangs.

**Test.** `stress.py`-style load (kept out of the repo): 48 workers looping for 12–15 min, each request the real 6k-token system prompt + 26 tools plus 0–24 turns of synthetic history (average prompt 10.4–10.6k tokens), `tool_choice=auto`, thinking on for 40%, `max_tokens` 256–2048. Other team traffic was running at the same time. One change per run; crash signatures tailed from `docker logs`.

| # | config (everything else as `start_vllm.sh`) | result | output tok/s (this load) |
|---|---|---|---|
| 1 | NVFP4, CUDA graphs `PIECEWISE` only (`GRAPHS=piecewise`) | **crashed at 11.5 min**: illegal memory access, 48 running, pure decode step, KV 6.5% | ~685 before the crash |
| 2 | NVFP4, full graphs, Triton attention + Triton mamba, no FlashInfer kernels in the hot path (`KERNELS=triton`) | **crashed at 8.7 min**: illegal instruction | ~515 (incl. the outage) |
| 3 | **BF16 checkpoint** (`nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-BF16`), `--gpu-memory-utilization 0.85`, card's FlashInfer settings, full graphs | **0 errors, 0 restarts**: 2,567 requests in 15.5 min | 568 |

Runs 1 and 2 rule out CUDA graph capture and the FlashInfer attention/mamba kernels. What is left in common is the NVFP4 path on SM120: Marlin W4A16 linear and MoE kernels, the FP8 linear layers (FlashInfer FP8 scaled-mm) and the FP8 KV cache the checkpoint asks for. BF16 removes all three, and it ran clean. `--enforce-eager` was not run separately, since PIECEWISE already put attention and mamba outside the graphs and still crashed; we did not isolate which NVFP4 kernel is at fault.

**Chosen config:** BF16 checkpoint, `GPU_UTIL=0.85`, every other flag unchanged (served name `nemotron-3.5-lightning`, port 8000). Memory: weights 58.9 GiB, KV cache 15.2 GiB = 2.3M tokens (peak usage 33% under the 48-way stress), GPU 94.6 of 97.9 GB used with the reader. Engine init is ~2.3 min on a warm cache.

**Throughput cost** (`serve_bench.py` decode, 256 tokens, same request shape as the Results table; a few foreign requests were running):

| N | NVFP4 tok/s (Oct 17) | BF16 tok/s (Oct 18) | change | per-request tok/s | TTFT p50 |
|---|---|---|---|---|---|
| 32 | 1,412 | 880 | −38% | 72 → 31 | 2.2 → 1.0 s |
| 64 | 1,579–1,822 | 1,286 | −19 to −29% | 43 → 29 | 2.8 → 1.4 s |

Decode is slower (BF16 reads 4x the weight bytes per token), time to first token is faster (no dequantization in prefill), and nothing crashes. For overnight eval runs that is the right trade: one NVFP4 crash costs every in-flight rollout. `MODEL=nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4 GPU_UTIL=0.80` restores the old config.

## Realistic workload: leads per hour and cost per qualified lead (PENDING)

`serving/agent_load.py` runs N concurrent full operator conversations end to end: the real loop (final config: prompt v3, renter guard, style pre-check, reasoning kept in history, verifier on), sandbox tools, scripted renters, and `read_reply` on the reader server. It reports conversations per hour, tool calls/s, turn latency p50/p95, server TTFT, tokens/s, KV usage, errors and retries, scorer pass rate under load, and the lead economics (leads/hr, qualified leads/hr = leasing conversations whose renter finished the 5-item gate, cost per qualified lead = $2.63 ÷ qualified leads/hr).

**Pending by the owner's decision:** these numbers will be measured on the realistic task set built from the owner's data, not on the Gym train tasks. Only a plumbing smoke test was run (2 Gym train conversations at N=2): 57 model turns, 0 errors, turn latency p50 1.19 s / p95 5.25 s, 12.6k prompt tokens per turn on average, 59 s per conversation. Two conversations say nothing about throughput, so no per-hour or per-lead figure is quoted.

To run it: `gym/.venv/bin/python serving/agent_load.py --levels 1,8,32,64,128 --tasks <task file> --label <name>`.

## What did not work, and what's next

- **MTP speculative decoding** (built-in heads, free under the 33B budget) accepted about 3 tokens per step on single requests but crashed the engine at 4 concurrent requests (CUDA illegal memory access). It is off.
- **Untested next steps**, each needing an idle-server restart: `--max-num-seqs 128` (KV peaks at 5%, so memory allows it), `--max-num-batched-tokens 16384` (should cut TTFT at N≥32, since prefill is the queue), and `ASYNC=off` on NVFP4 (the misaligned-address crash is fixed by moving to BF16, see "Stability"; async scheduling was not isolated).
- **Prompt layout**: a static prefix that ends exactly on a 2,128-token block boundary would raise the first-turn hit rate from 71% toward 100%.

## Reproduce

```bash
gym/.venv/bin/python serving/serve_bench.py --label baseline --reader-probe                  # sweep 1..128
gym/.venv/bin/python serving/serve_bench.py --label off --no-prefix-reuse --levels 1,8,32,64 --reader-probe
gym/.venv/bin/python serving/serve_bench.py --label on  --levels 1,8,32,64 --reader-probe   # pair it
gym/.venv/bin/python serving/serve_bench.py --label think-on  --mode turn --reasoning on  --levels 32
gym/.venv/bin/python serving/serve_bench.py --label think-off --mode turn --reasoning off --levels 32
```
