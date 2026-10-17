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

check() { [ "$(curl -s -o /dev/null -w '%{http_code}' -m 10 -H "Authorization: Bearer ${OPERATOR_API_KEY:-}" "$URL")" = 200 ]; }
log() { echo "$(date '+%F %T %Z') $*" | tee -a "$LOG"; }

loop() {
  misses=0
  log "watchdog up, polling $URL"
  while true; do
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
