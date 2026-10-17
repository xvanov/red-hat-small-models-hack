# Serving the reader next to Lightning

One GPU (Brev RTX Pro 6000, 96 GB). Lightning runs in the `vllm-operator` container on
port 8000 with `--gpu-memory-utilization 0.80` (see `serving/start_vllm.sh`). The reader runs
in a **second** vLLM container, `vllm-reader`, from the same image, on port 8001 with
`--gpu-memory-utilization 0.12` (~11.5 GB: 1.2 GB of bf16 weights, the rest KV cache).
Both are bound to 127.0.0.1 on the instance and reached through SSH tunnels.

Start Lightning first: vLLM checks free memory at startup, so the reader must come up after the
operator has taken its 80%. Never restart `vllm-operator` to make room for the reader.

## On the instance

The checkpoint lives in `~/rentus/reader/checkpoints/rentus-reader` (written by `train.py`)
and is mounted read-only at `/ckpt`.

```bash
# fine-tuned reader
MODEL=/ckpt/rentus-reader SERVED=rentus-reader bash ~/rentus/reader/serve_reader.sh
# base model, for the baseline eval
MODEL=Qwen/Qwen3-0.6B SERVED=qwen3-0.6b-base bash ~/rentus/reader/serve_reader.sh
# stop
bash ~/rentus/reader/serve_reader.sh stop
```

What the script runs:

```bash
sudo docker run -d --name vllm-reader --restart unless-stopped --gpus all --ipc=host \
  -p 127.0.0.1:8001:8000 \
  -v ~/hf-cache:/root/.cache/huggingface -v ~/rentus/reader/checkpoints:/ckpt:ro \
  --env-file ~/serving/vllm.env \
  vllm/vllm-openai:v0.27.1 \
  --model /ckpt/rentus-reader --served-model-name rentus-reader \
  --host 0.0.0.0 --port 8000 \
  --gpu-memory-utilization 0.12 --max-model-len 4096 --max-num-seqs 64 \
  --enable-prefix-caching --generation-config vllm
```

Prefix caching pays off here: every call shares the same ~650-token system prompt.
The saved chat template defaults to thinking off, so callers send plain chat requests.
`--env-file ~/serving/vllm.env` makes the reader require the same API key as the operator.

## From the operator machine

```bash
ssh -N -L 8001:127.0.0.1:8001 rentus-operator &      # tunnel, like serving/tunnel.sh for 8000
```

Then in `.env` (names in `reader/.env.example`):

```
READER_BASE_URL=http://localhost:8001/v1
READER_MODEL=rentus-reader
READER_API_KEY=<same value as OPERATOR_API_KEY>
```

Check it:

```bash
python reader/eval.py --backend endpoint --api-key-env READER_API_KEY --label finetuned
```

## Training on the same GPU

`train.py` needs ~15 GB with batch 8; with Lightning at 80% that fits only while `vllm-reader`
is stopped. Order used: serve base reader → base eval → stop it → train → serve fine-tuned.
