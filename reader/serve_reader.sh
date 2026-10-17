#!/usr/bin/env bash
# Runs ON the Brev instance. Serves a reader model in a second vLLM container next to
# Lightning (serving/start_vllm.sh, port 8000), on 127.0.0.1:8001, with ~12% of GPU memory.
# Never touches the vllm-operator container.
#
#   MODEL=/ckpt/rentus-reader bash ~/rentus/reader/serve_reader.sh      # fine-tuned checkpoint
#   MODEL=Qwen/Qwen3-0.6B SERVED=qwen3-0.6b-base bash ~/rentus/reader/serve_reader.sh   # base model
#   bash ~/rentus/reader/serve_reader.sh stop
#
# Same API key as the operator endpoint (~/serving/vllm.env), never echoed.
set -euo pipefail
IMAGE=${IMAGE:-vllm/vllm-openai:v0.27.1}
MODEL=${MODEL:-/ckpt/rentus-reader}
SERVED=${SERVED:-rentus-reader}
NAME=${NAME:-vllm-reader}
PORT=${PORT:-8001}
GPU_UTIL=${GPU_UTIL:-0.12}
CKPT_DIR=${CKPT_DIR:-$HOME/rentus/reader/checkpoints}

if [ "${1:-}" = stop ]; then sudo docker rm -f "$NAME" >/dev/null 2>&1 || true; echo "stopped $NAME"; exit 0; fi

ENVFILE=()
[ -f ~/serving/vllm.env ] && ENVFILE=(--env-file ~/serving/vllm.env)
mkdir -p "$CKPT_DIR" ~/hf-cache
sudo docker rm -f "$NAME" >/dev/null 2>&1 || true
sudo docker run -d --name "$NAME" --restart unless-stopped \
  --gpus all --ipc=host \
  -p 127.0.0.1:"$PORT":8000 \
  -v ~/hf-cache:/root/.cache/huggingface \
  -v "$CKPT_DIR":/ckpt:ro \
  "${ENVFILE[@]}" \
  "$IMAGE" \
  --model "$MODEL" --served-model-name "$SERVED" \
  --host 0.0.0.0 --port 8000 \
  --gpu-memory-utilization "$GPU_UTIL" \
  --max-model-len 4096 --max-num-seqs 64 \
  --enable-prefix-caching \
  --generation-config vllm
echo "started $NAME ($MODEL as $SERVED) on 127.0.0.1:$PORT, gpu_util=$GPU_UTIL"
