#!/usr/bin/env bash
# Rebuild the whole serving setup from scratch on a (new) Brev instance, in one command.
# Use it if `rentus-operator` was deleted (spend cap) and must come back before the freeze.
#
#   serving/rebuild.sh              do it for real (creates the instance if it does not exist)
#   serving/rebuild.sh --dry-run    print every step and command, touch nothing
#
# Idempotent: every step checks first and skips what is already done (instance exists and is
# RUNNING, docker present, container up, checkpoint already on the instance, tunnel answering...).
# Re-running after a failure picks up where it stopped.
#
# Env overrides:
#   BREV_HOST=rentus-operator   instance name
#   BREV_TYPE=massedcompute_RTXPro6000
#   CREATE_TRIES=5              brev create attempts (30 s apart, then 60, 90...)
#   READER_SOURCE=auto|hf|rsync auto = pull from Hugging Face if the repo is public, else rsync
#   SKIP_SMOKE=1                skip serving/smoke_test.py at the end
#
# Secrets: OPERATOR_API_KEY / READER_API_KEY / BREV_API_KEY come from .env. If OPERATOR_API_KEY
# is empty, a new one is generated and written to .env. No secret is ever echoed; the key goes
# to the instance over ssh stdin, never on a command line.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$HERE")"
HOST=${BREV_HOST:-rentus-operator}
TYPE=${BREV_TYPE:-massedcompute_RTXPro6000}
CREATE_TRIES=${CREATE_TRIES:-5}
READER_SOURCE=${READER_SOURCE:-auto}
HF_READER=${HF_READER:-xvanov/rentus-reader-qwen3-0.6b}
LOCAL_CKPT="$ROOT/reader/release/rentus-reader"
READER_LPORT=8011
DRY=0
[ "${1:-}" = "--dry-run" ] && DRY=1
case "${1:-}" in ""|--dry-run) ;; *) echo "usage: $0 [--dry-run]" >&2; exit 2 ;; esac

T0=$(date +%s)
STEP_T=$T0
STEP_NAME=""
say() { echo "[$(date +%H:%M:%S)] $*"; }
step() {
  local now; now=$(date +%s)
  [ -n "$STEP_NAME" ] && say "   done: $STEP_NAME ($((now - STEP_T)) s)"
  STEP_NAME="$1"; STEP_T=$now
  echo; say "== $1"
}
finish() {
  local now; now=$(date +%s)
  [ -n "$STEP_NAME" ] && say "   done: $STEP_NAME ($((now - STEP_T)) s)"
  say "total elapsed: $(( (now - T0) / 60 )) min $(( (now - T0) % 60 )) s"
}
# run: execute, or in dry-run print. Arguments must never contain a secret.
run() { if [ "$DRY" = 1 ]; then echo "   + $*"; else "$@"; fi; }
die() { say "FAILED: $*"; finish; exit 1; }
# Brev's ssh_config already disables host-key checking, so a rebuilt host under the same name just works.
rssh() { ssh -o BatchMode=yes -o ConnectTimeout=15 "$HOST" "$@"; }

# ---------------------------------------------------------------- 0. local prerequisites
step "0. local prerequisites and secrets"
for bin in brev ssh rsync curl uv openssl; do
  command -v "$bin" >/dev/null || die "missing local command: $bin"
done
if [ ! -f "$ROOT/.env" ]; then
  if [ "$DRY" = 1 ]; then say "   (no .env yet)"; else die "no .env at $ROOT/.env (copy .env.example and set BREV_API_KEY)"; fi
fi
# shellcheck disable=SC1091
if [ -f "$ROOT/.env" ]; then set -a; . "$ROOT/.env"; set +a; fi
export BREV_API_KEY="${BREV_API_KEY:-}"
[ -n "$BREV_API_KEY" ] || [ "$DRY" = 1 ] || die "BREV_API_KEY is empty in .env"

# set_env KEY VALUE: replace or append KEY=VALUE in .env without printing VALUE
set_env() {
  local k=$1 v=$2 tmp
  tmp=$(mktemp)
  grep -v "^${k}=" "$ROOT/.env" > "$tmp" || true
  printf '%s=%s\n' "$k" "$v" >> "$tmp"
  cat "$tmp" > "$ROOT/.env"; rm -f "$tmp"
}
# strip inline comments/whitespace a loader may have kept
OPERATOR_API_KEY=$(printf '%s' "${OPERATOR_API_KEY:-}" | sed 's/[[:space:]]*#.*$//; s/[[:space:]]//g')
if [ -z "$OPERATOR_API_KEY" ]; then
  if [ "$DRY" = 1 ]; then say "   would generate OPERATOR_API_KEY (openssl rand -hex 32) and write it to .env"
  else
    OPERATOR_API_KEY=$(openssl rand -hex 32)
    set_env OPERATOR_API_KEY "$OPERATOR_API_KEY"
    say "   generated a new OPERATOR_API_KEY and wrote it to .env (not shown)"
  fi
else say "   OPERATOR_API_KEY present in .env (not shown)"; fi
if [ "$DRY" = 0 ] && [ "${READER_API_KEY:-}" != "$OPERATOR_API_KEY" ]; then
  set_env READER_API_KEY "$OPERATOR_API_KEY"; say "   READER_API_KEY set to the operator key in .env"
fi
export OPERATOR_API_KEY READER_API_KEY="$OPERATOR_API_KEY"

# ---------------------------------------------------------------- 1. instance
step "1. Brev instance $HOST ($TYPE)"
inst_status() {  # prints RUNNING / STOPPED / ... or nothing if the instance does not exist
  timeout 60 brev ls --json 2>/dev/null | python3 -c '
import json, sys
name = sys.argv[1]
try: d = json.load(sys.stdin)
except Exception: sys.exit(0)
for w in d.get("workspaces") or []:
    if w.get("name") == name: print(w.get("status", "")); break
' "$HOST"
}
if [ "$DRY" = 1 ]; then
  echo "   + brev ls --json  -> if $HOST missing: brev create $HOST --type $TYPE --timeout 900 (up to $CREATE_TRIES tries)"
  echo "   +                 -> if STOPPED: brev start $HOST"
else
  st=$(inst_status)
  if [ -z "$st" ]; then
    n=1
    until brev create "$HOST" --type "$TYPE" --timeout 900; do
      [ "$n" -ge "$CREATE_TRIES" ] && die "brev create failed $n times"
      # a half-created instance may exist now; don't create a second one
      [ -n "$(inst_status)" ] && { say "   instance appeared despite the error, continuing"; break; }
      say "   brev create failed (try $n/$CREATE_TRIES), retrying in $((30 * n)) s"
      sleep $((30 * n)); n=$((n + 1))
    done
    say "   billing started $(date '+%a %F %H:%M %Z') at about \$2.63/hr: update the table in serving/README.md"
  elif [ "$st" = STOPPED ] || [ "$st" = STOPPING ]; then
    say "   instance is $st, starting it"; brev start "$HOST"
  else say "   instance exists ($st)"; fi
fi

# ---------------------------------------------------------------- 2. wait until ready
step "2. wait until the instance is RUNNING and ssh answers"
if [ "$DRY" = 1 ]; then echo "   + poll brev ls --json until RUNNING; brev refresh; ssh $HOST true (timeout 20 min)"
else
  deadline=$(( $(date +%s) + 1200 ))
  until [ "$(inst_status)" = RUNNING ]; do
    [ "$(date +%s)" -gt "$deadline" ] && die "instance not RUNNING after 20 min"
    sleep 15
  done
  brev refresh >/dev/null 2>&1 || true
  until rssh true 2>/dev/null; do
    [ "$(date +%s)" -gt "$deadline" ] && die "ssh to $HOST not answering after 20 min"
    sleep 10; brev refresh >/dev/null 2>&1 || true
  done
  say "   ssh ok"
fi

# ---------------------------------------------------------------- 3. docker + nvidia runtime
step "3. docker + NVIDIA container runtime"
REMOTE_DOCKER=$(cat <<'EOS'
set -euo pipefail
if ! command -v docker >/dev/null; then
  echo "installing docker"
  curl -fsSL https://get.docker.com | sudo sh
fi
if ! sudo docker info 2>/dev/null | grep -qi 'nvidia'; then
  if ! command -v nvidia-ctk >/dev/null; then
    echo "installing nvidia-container-toolkit"
    curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor --yes -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
    curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
      | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
      | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list >/dev/null
    sudo apt-get update -qq && sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq nvidia-container-toolkit
  fi
  sudo nvidia-ctk runtime configure --runtime=docker
  sudo systemctl restart docker
fi
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
sudo docker info --format 'docker {{.ServerVersion}}, runtimes: {{range $k, $v := .Runtimes}}{{$k}} {{end}}'
EOS
)
if [ "$DRY" = 1 ]; then echo "   + ssh $HOST: install docker (get.docker.com) if missing; install nvidia-container-toolkit + nvidia-ctk runtime configure if docker has no nvidia runtime"
else rssh 'bash -s' <<<"$REMOTE_DOCKER" || die "docker/nvidia setup failed"; fi

# ---------------------------------------------------------------- 4. key file + scripts
step "4. API key file and serving scripts on the instance"
if [ "$DRY" = 1 ]; then
  echo "   + ssh $HOST: write ~/serving/vllm.env (VLLM_API_KEY=<from .env>, mode 600) via stdin"
  echo "   + scp serving/start_vllm.sh -> $HOST:~/serving/ ; reader/serve_reader.sh -> $HOST:~/rentus/reader/"
else
  printf 'VLLM_API_KEY=%s\n' "$OPERATOR_API_KEY" \
    | rssh 'umask 077; mkdir -p ~/serving ~/rentus/reader/checkpoints ~/hf-cache; cat > ~/serving/vllm.env.new && mv ~/serving/vllm.env.new ~/serving/vllm.env'
  scp -q -o BatchMode=yes "$HERE/start_vllm.sh" "$HOST:serving/start_vllm.sh"
  scp -q -o BatchMode=yes "$ROOT/reader/serve_reader.sh" "$HOST:rentus/reader/serve_reader.sh"
  say "   key file written (not shown), scripts copied"
fi

# container_up NAME: true if the container is running on the instance
container_up() { [ "$(rssh "sudo docker inspect -f '{{.State.Running}}' $1 2>/dev/null" || true)" = true ]; }
# remote_models PORT: HTTP code of /v1/models on the instance (key read there, never sent here)
remote_models() {
  rssh "set -a; . ~/serving/vllm.env; set +a; curl -s -o /dev/null -w '%{http_code}' -m 10 -H \"Authorization: Bearer \$VLLM_API_KEY\" http://127.0.0.1:$1/v1/models" 2>/dev/null || true
}
wait_models() {  # PORT NAME TIMEOUT_S
  local port=$1 name=$2 deadline=$(( $(date +%s) + $3 )) code
  until [ "$(remote_models "$port")" = 200 ]; do
    if [ "$(date +%s)" -gt "$deadline" ]; then
      rssh "sudo docker logs --tail 20 $name 2>&1 | cut -c1-200" || true
      die "$name /v1/models not 200 after $3 s"
    fi
    code=$(rssh "sudo docker inspect -f '{{.State.Status}} restarts={{.RestartCount}}' $name 2>/dev/null" || true)
    say "   waiting for $name on :$port ($code) ..."
    sleep 20
  done
  say "   $name /v1/models -> 200"
}

# ---------------------------------------------------------------- 5. Lightning
step "5. start Lightning (vllm-operator, :8000) with start_vllm.sh defaults"
if [ "$DRY" = 1 ]; then echo "   + ssh $HOST 'bash ~/serving/start_vllm.sh'   (skipped if vllm-operator already running)"
elif container_up vllm-operator; then say "   vllm-operator already running, left alone"
else rssh 'bash ~/serving/start_vllm.sh'; fi

# ---------------------------------------------------------------- 6. wait for Lightning
# The reader must start AFTER Lightning has taken its 80% of GPU memory (reader/serve.md).
step "6. wait for Lightning /v1/models (first boot downloads ~20 GB of weights + 9 GB image)"
if [ "$DRY" = 1 ]; then echo "   + poll 127.0.0.1:8000/v1/models on the instance every 20 s (timeout 30 min)"
else wait_models 8000 vllm-operator 1800; fi

# ---------------------------------------------------------------- 7. reader checkpoint
step "7. reader checkpoint (READER_SOURCE=$READER_SOURCE)"
src=$READER_SOURCE
if [ "$src" = auto ]; then
  if [ "$(curl -s -o /dev/null -w '%{http_code}' -m 10 "https://huggingface.co/api/models/$HF_READER")" = 200 ]; then src=hf; else src=rsync; fi
  say "   auto -> $src"
fi
if [ "$src" = hf ]; then
  READER_MODEL_ARG="$HF_READER"
  say "   vLLM will pull $HF_READER from Hugging Face into ~/hf-cache"
else
  READER_MODEL_ARG=/ckpt/rentus-reader
  [ -f "$LOCAL_CKPT/model.safetensors" ] || die "no local checkpoint at $LOCAL_CKPT"
  run rsync -a --partial --info=progress2 -e "ssh -o BatchMode=yes" \
    "$LOCAL_CKPT/" "$HOST:rentus/reader/checkpoints/rentus-reader/"
fi

# ---------------------------------------------------------------- 8. reader container
step "8. start the reader (vllm-reader, :8001, gpu util 0.12)"
if [ "$DRY" = 1 ]; then echo "   + ssh $HOST 'MODEL=$READER_MODEL_ARG SERVED=rentus-reader bash ~/rentus/reader/serve_reader.sh'   (skipped if running)"
elif container_up vllm-reader; then say "   vllm-reader already running, left alone"
else rssh "MODEL=$READER_MODEL_ARG SERVED=rentus-reader bash ~/rentus/reader/serve_reader.sh"; fi

step "9. wait for reader /v1/models"
if [ "$DRY" = 1 ]; then echo "   + poll 127.0.0.1:8001/v1/models on the instance every 20 s (timeout 10 min)"
else wait_models 8001 vllm-reader 600; fi

# ---------------------------------------------------------------- 10. tunnels
step "10. tunnels: localhost:8000 -> :8000, localhost:$READER_LPORT -> :8001"
local_code() { curl -s -o /dev/null -w '%{http_code}' -m 5 -H "Authorization: Bearer $OPERATOR_API_KEY" "http://localhost:$1/v1/models" || true; }
if [ "$DRY" = 1 ]; then
  echo "   + serving/tunnel.sh                          (skipped if localhost:8000/v1/models already 200)"
  echo "   + LPORT=$READER_LPORT RPORT=8001 serving/tunnel.sh   (skipped if localhost:$READER_LPORT/v1/models already 200)"
else
  if [ "$(local_code 8000)" = 200 ]; then say "   operator tunnel already up"; else "$HERE/tunnel.sh"; fi
  if [ "$(local_code $READER_LPORT)" = 200 ]; then say "   reader tunnel already up"; else LPORT=$READER_LPORT RPORT=8001 "$HERE/tunnel.sh"; fi
  sleep 3
  [ "$(local_code 8000)" = 200 ] || die "localhost:8000/v1/models not 200 through the tunnel"
  [ "$(local_code $READER_LPORT)" = 200 ] || die "localhost:$READER_LPORT/v1/models not 200 through the tunnel"
  say "   both endpoints answer locally"
fi

# ---------------------------------------------------------------- 11. watchdog
step "11. watchdog"
run "$HERE/watchdog.sh" start

# ---------------------------------------------------------------- 12. smoke test
step "12. smoke test (serving/smoke_test.py --thinking off)"
if [ "${SKIP_SMOKE:-0}" = 1 ]; then say "   skipped (SKIP_SMOKE=1)"
else run uv run "$HERE/smoke_test.py" --thinking off || die "smoke test failed"; fi

finish
[ "$DRY" = 1 ] && say "dry run: nothing was created, started or changed"
exit 0
