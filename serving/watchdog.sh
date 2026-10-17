#!/usr/bin/env bash
# Tiny watchdog: every 30 s ask GET /v1/models through the tunnel. After 2 misses in a row,
# restart the tunnel; if it still fails, log the container state from the instance.
#   serving/watchdog.sh          start in background (log: serving/.watchdog.log)
#   serving/watchdog.sh stop
#   serving/watchdog.sh once     single check, exit 0 if healthy
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$HERE")"
PIDFILE="$HERE/.watchdog.pid"
LOG="$HERE/.watchdog.log"
HOST=${BREV_HOST:-rentus-operator}
if [ -f "$ROOT/.env" ]; then set -a; . "$ROOT/.env"; set +a; export BREV_API_KEY; fi
URL="${OPERATOR_BASE_URL:-http://localhost:8000/v1}/models"

MODEL=${OPERATOR_MODEL:-nemotron-3.5-lightning}
# A hung engine still answers /v1/models, so every 4th poll (~2 min) also asks for one token.
gen_check() {
  curl -s -o /dev/null -w '%{http_code}' -m 90 -H "Authorization: Bearer ${OPERATOR_API_KEY:-}" \
    -H 'Content-Type: application/json' "${OPERATOR_BASE_URL:-http://localhost:8000/v1}/chat/completions" \
    -d "{\"model\":\"$MODEL\",\"max_tokens\":1,\"messages\":[{\"role\":\"user\",\"content\":\"ping\"}]}" | grep -q 200
}
check() { [ "$(curl -s -o /dev/null -w '%{http_code}' -m 10 -H "Authorization: Bearer ${OPERATOR_API_KEY:-}" "$URL")" = 200 ]; }
log() { echo "$(date '+%F %T %Z') $*" | tee -a "$LOG"; }

loop() {
  misses=0; tick=0; gen_misses=0
  log "watchdog up, polling $URL"
  while true; do
    tick=$((tick + 1))
    if check && [ $((tick % 4)) -eq 0 ]; then
      if gen_check; then gen_misses=0
      else
        gen_misses=$((gen_misses + 1)); log "generation probe failed ($gen_misses) while /v1/models answers"
        if [ "$gen_misses" -ge 2 ]; then
          log "engine looks hung: restarting vllm-operator on the instance"
          timeout 120 ssh -o BatchMode=yes "$HOST" 'sudo docker restart vllm-operator' >>"$LOG" 2>&1 || log "restart over ssh failed"
          gen_misses=0
        fi
      fi
    fi
    if check; then
      [ "$misses" -gt 0 ] && log "recovered after $misses miss(es)"
      misses=0
    else
      misses=$((misses + 1))
      log "miss $misses: /v1/models not answering"
      if [ "$misses" -eq 2 ]; then
        log "restarting tunnel"; "$HERE/tunnel.sh" >>"$LOG" 2>&1
        sleep 10
        if ! check; then
          log "still down after tunnel restart; container state on instance:"
          timeout 60 ssh -o BatchMode=yes "$HOST" \
            'sudo docker ps -a --filter name=vllm-operator --format "{{.Status}}"; sudo docker logs --tail 5 vllm-operator 2>&1 | cut -c1-200' \
            >>"$LOG" 2>&1 || log "ssh to instance failed"
        fi
      fi
      # keep retrying the tunnel every ~5 min while down (vLLM restart takes ~2.5 min)
      [ "$misses" -gt 2 ] && [ $((misses % 10)) -eq 0 ] && "$HERE/tunnel.sh" >>"$LOG" 2>&1
    fi
    sleep 30
  done
}

case "${1:-start}" in
  once) check && echo healthy || { echo "NOT answering: $URL"; exit 1; } ;;
  stop) [ -f "$PIDFILE" ] && kill "$(cat "$PIDFILE")" 2>/dev/null; rm -f "$PIDFILE"; echo stopped ;;
  run) loop ;;
  start)
    [ -f "$PIDFILE" ] && kill "$(cat "$PIDFILE")" 2>/dev/null
    nohup "$0" run >/dev/null 2>&1 &
    echo $! > "$PIDFILE"; echo "watchdog started (pid $!), log $LOG" ;;
esac
