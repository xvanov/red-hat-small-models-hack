#!/usr/bin/env bash
# Runs ON the Brev instance. Starts (or restarts) the operator model in a
# detached docker container that restarts itself after crashes/reboots.
#
#   scp serving/start_vllm.sh rentus-operator:~/serving/ && ssh rentus-operator 'bash ~/serving/start_vllm.sh'
#
# Env overrides: MODEL, NAME, PREFIX_CACHE=on|off, ASYNC=on|off, PORT, MAX_LEN, GPU_UTIL, MTP=on|off,
#                GRAPHS=full|piecewise|eager, KERNELS=flashinfer|triton, EXTRA_ARGS="..."
# MTP=on crashed under concurrency on vLLM 0.27.1 + RTX Pro 6000 (see README); default off.
# The API key comes from ~/serving/vllm.env (VLLM_API_KEY=...), written by the
# operator machine from .env OPERATOR_API_KEY. It is never echoed.
set -euo pipefail

IMAGE=${IMAGE:-vllm/vllm-openai:v0.27.1}
# BF16, not NVFP4: on vLLM 0.27.1 + RTX Pro 6000 (SM120) the NVFP4 path (Marlin W4A16 linear/MoE, FP8 linear,
# FP8 KV cache) crashed the engine every ~10 min under 48 concurrent requests (CUDA misaligned address /
# illegal memory access / illegal instruction), with CUDA graphs FULL or PIECEWISE and with FlashInfer or
# Triton attention+mamba. BF16 ran 15 min / 2,567 requests with 0 errors. See docs/vllm.md "Stability".
# MODEL=nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4 GPU_UTIL=0.80 restores the old (faster, crashing) config.
MODEL=${MODEL:-nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-BF16}
SERVED=${SERVED:-nemotron-3.5-lightning}
NAME=${NAME:-vllm-operator}
PORT=${PORT:-8000}
MAX_LEN=${MAX_LEN:-65536}
GPU_UTIL=${GPU_UTIL:-0.85}     # BF16 weights 59 GiB + 15 GiB KV (2.3M tokens); reader 0.12 still fits
PREFIX_CACHE=${PREFIX_CACHE:-on}
MTP=${MTP:-off}
ASYNC=${ASYNC:-on}
GRAPHS=${GRAPHS:-full}          # full (vLLM default FULL_AND_PIECEWISE) | piecewise | eager
KERNELS=${KERNELS:-flashinfer}  # flashinfer (card recipe) | triton (no FlashInfer attention/mamba kernels)
EXTRA_ARGS=${EXTRA_ARGS:-}      # appended verbatim, e.g. "--moe-backend triton"

ARGS=(
  --model "$MODEL"
  --served-model-name "$SERVED"
  --host 0.0.0.0 --port 8000
  --max-model-len "$MAX_LEN"
  --gpu-memory-utilization "$GPU_UTIL"
  --max-num-seqs 64
  --mamba-cache-mode align
  --mamba-ssm-cache-dtype float16
  --reasoning-parser nemotron_v3
  --tool-call-parser qwen3_coder
  --enable-auto-tool-choice
)
if [ "$ASYNC" = on ]; then ARGS+=(--async-scheduling); fi
if [ "$PREFIX_CACHE" = on ]; then ARGS+=(--enable-prefix-caching); else ARGS+=(--no-enable-prefix-caching); fi
# MTP heads live inside the checkpoint (no extra model, nothing added to the 33B budget).
if [ "$KERNELS" = flashinfer ]; then
  ARGS+=(--mamba-backend flashinfer --enable-mamba-cache-stochastic-rounding --mamba-cache-philox-rounds 5)
else
  ARGS+=(--mamba-backend triton --attention-backend TRITON_ATTN)
fi
case "$GRAPHS" in
  piecewise) ARGS+=(--compilation-config '{"cudagraph_mode":"PIECEWISE"}') ;;
  eager) ARGS+=(--enforce-eager) ;;
esac
# shellcheck disable=SC2206
if [ -n "$EXTRA_ARGS" ]; then ARGS+=($EXTRA_ARGS); fi
if [ "$MTP" = on ]; then ARGS+=(--speculative-config '{"method":"mtp","num_speculative_tokens":3}'); fi

mkdir -p ~/hf-cache
sudo docker rm -f "$NAME" >/dev/null 2>&1 || true
# Bound to 127.0.0.1 on the instance: only reachable through the SSH tunnel.
sudo docker run -d --name "$NAME" --restart unless-stopped \
  --gpus all --ipc=host \
  -p 127.0.0.1:"$PORT":8000 \
  -v ~/hf-cache:/root/.cache/huggingface \
  --env-file ~/serving/vllm.env \
  "$IMAGE" "${ARGS[@]}"
echo "started $NAME ($MODEL, prefix_cache=$PREFIX_CACHE, mtp=$MTP, graphs=$GRAPHS, kernels=$KERNELS, extra=$EXTRA_ARGS) on 127.0.0.1:$PORT"
