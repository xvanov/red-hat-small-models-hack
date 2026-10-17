# W1 — Serving

Nemotron 3.5 Lightning (the operator) served by vLLM on one Brev GPU, reached from the laptop at `http://localhost:8000/v1` (OpenAI-compatible) through an SSH tunnel.

## Instance and spend

| | |
|---|---|
| Brev instance | `rentus-operator` (one instance only, decision D11) |
| Type | `massedcompute_RTXPro6000`: 1x RTX PRO 6000 Blackwell Server Edition 96 GB, 16 vCPU, 141 GB RAM, 713 GB disk |
| Price | **$2.63/hr** |
| Billing started | **Sat 2026-10-17 11:26 ET** (`brev create`; ready 11:30) |
| Endpoint live | 11:36 ET |
| Spend cap | $40 total (owner, Oct 17), which is about 15 h at $2.63/hr, i.e. **until about 02:30 ET Sun** unless the cap is raised. Code freeze is 11:00 Sun (~23.5 h, ~$62). |

Spend so far = (now − 11:26 ET) × $2.63.

## Model and vLLM config

- Checkpoint: `nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4` (30B total / 3B active, card count). Served name: **`nemotron-3.5-lightning`**.
- Image: `vllm/vllm-openai:v0.27.1` (pinned by the model card; released 2026-08-11, inside the 2-week rule).
- Flags (see `start_vllm.sh`): `--max-model-len 65536 --gpu-memory-utilization 0.80 --max-num-seqs 64 --enable-prefix-caching --async-scheduling --mamba-backend flashinfer --mamba-cache-mode align --mamba-ssm-cache-dtype float16 --enable-mamba-cache-stochastic-rounding --mamba-cache-philox-rounds 5 --reasoning-parser nemotron_v3 --tool-call-parser qwen3_coder --enable-auto-tool-choice`, API key via `VLLM_API_KEY`.
- Memory: weights + overhead about 19.4 GB, KV cache 50.6 GB (≈14M tokens; 213 concurrent 64k-token requests). At 0.80 utilization about 19 GB of the 96 GB stays free for the ≤1.5B reader.
- On this GPU (SM120) vLLM picks the **Marlin** NVFP4 kernels for linear and MoE layers (4-bit weights, 16-bit math), not native FP4 tensor cores. The card publishes no RTX Pro 6000 recipe.
- **No speculative decoding.** DSpark/DFlash are separate draft models and would count toward the 33B budget. Built-in **MTP** (`--speculative-config '{"method":"mtp","num_speculative_tokens":3}'`) loads and accepts about 3 tokens per step, but it **crashed the engine** (CUDA illegal memory access in the FlashInfer attention metadata build) as soon as 4 requests ran together, with async scheduling on or off. It stays off (`MTP=on` in `start_vllm.sh` to retry).
- The container runs with `--restart unless-stopped` and binds to `127.0.0.1:8000` on the instance, so it's reachable only through the tunnel.

## Start, stop, reconnect

All `brev`/`ssh` commands need `BREV_API_KEY` exported (Brev's ssh_config mints a cert with it): `set -a; . ./.env; set +a; export BREV_API_KEY`.

```bash
serving/tunnel.sh            # (re)start tunnel localhost:8000 -> instance:8000, auto-reconnects
serving/tunnel.sh status     # loop alive? /health code?
serving/tunnel.sh stop

# (re)start vLLM on the instance (key file ~/serving/vllm.env already there)
scp serving/start_vllm.sh rentus-operator:serving/ && ssh rentus-operator 'bash ~/serving/start_vllm.sh'
ssh rentus-operator 'sudo docker logs -f --tail 50 vllm-operator'
# variants: PREFIX_CACHE=off, MTP=on, ASYNC=off, MAX_LEN=..., GPU_UTIL=...

brev ls                      # instance status
brev stop rentus-operator    # stop billing GPU (if the type supports stop); brev start to resume
brev delete rentus-operator  # Sun 10:50 after submission, owner's call
```

If the key file is missing on a fresh instance: `printf 'VLLM_API_KEY=%s\n' "$OPERATOR_API_KEY" | ssh rentus-operator 'umask 077; mkdir -p ~/serving; cat > ~/serving/vllm.env'`.

Client settings (`.env`): `OPERATOR_BASE_URL=http://localhost:8000/v1`, `OPERATOR_MODEL=nemotron-3.5-lightning`, `OPERATOR_API_KEY` (already in `.env`).

## Smoke test (`uv run serving/smoke_test.py [--thinking on|off]`)

All three checks pass in both modes (11:37 ET, idle server):

| check | thinking on | thinking off |
|---|---|---|
| plain chat | PASS, 2.3–3.2 s (~700–880 tokens, mostly reasoning) | PASS, 0.15 s |
| 2 tools, must call `create_listing` with exact JSON (750, 2026-11-01, true) | PASS, 0.8–1.1 s, `finish_reason=tool_calls` | PASS, 0.34 s |
| round trip: tool result fed back, model reports listing id | PASS, 0.55 s | PASS, 0.3–0.5 s |

Notes for the operator loop (W2):
- **Reasoning is split out cleanly** by `--reasoning-parser nemotron_v3`: it arrives in `message.reasoning_content`, never in `content` or in tool-call arguments. Nothing to strip. Tool calls with thinking on still came back with `content=None`.
- Thinking adds 2–20 s per turn depending on load. Use `extra_body={"chat_template_kwargs": {"enable_thinking": False}}` for routine tool turns, and keep thinking for hard decisions.
- **The model sometimes writes IDs with Unicode hyphens** (`L‑1042` with U+2011). Normalize dashes before matching IDs or amounts in its text (`smoke_test.py` has `norm()`). Tool-call JSON arguments were plain ASCII in every run.
- Sampling per the card: temperature 1.0, top_p 0.95.

## Stability (checked 12:10 ET)

- The one crash other workstreams saw (about 11:49 ET) was my second MTP test (CUDA illegal memory access), followed by my restart to the default config. The current container (created 11:49 ET) has `speculative_config=None`, 0 restarts, no OOM, no errors.
- It held 16 concurrent agent requests from me plus ~16 from the gym with 0 errors. KV cache usage stays under 3% and the queue stays empty, so `--max-num-seqs 64` and `--gpu-memory-utilization 0.80` stay as they are.
- The GPU is shared with the W6 reader fine-tune (7 GB, GPU at 98%). vLLM's 77.5 GB plus the training job's 7 GB leaves about 13 GB free. While training runs, operator speed drops a lot (about 30 tok/s per request vs 254 tok/s when idle).
- `serving/watchdog.sh` (start | stop | once) polls `/v1/models` every 30 s. After 2 misses it restarts the tunnel, then logs the container state from the instance to `serving/.watchdog.log`.

## Benchmarks

See `bench-results.md`. In short (shared ~2.5k-token system prompt, 256 output tokens, thinking off):

| concurrency | prefix cache ON tok/s (p50 / p95) | OFF tok/s (p50 / p95) |
|---|---|---|
| 1 | 254 (1.00 / 1.04 s) | 243 (1.01 / 1.27 s) |
| 4 | 614 (1.66 / 1.81 s) | 579 (1.77 / 1.89 s) |
| 16 | 1286 (3.17 / 3.19 s) | 879 (4.64 / 5.40 s) |
| 32 | 1764 (4.61 / 4.80 s) | 1247 (6.44 / 6.82 s) |

Prefix caching: +41–46% throughput at 16–32 concurrent requests and about half the time to first token (1.1 s vs 2.1 s p50 at 32). Caveat: other workstreams began calling the server around 11:45 ET, so the OFF run may include some of their load. Re-run both on a quiet server before quoting them in the final README.
