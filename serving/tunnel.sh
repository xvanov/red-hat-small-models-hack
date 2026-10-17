#!/usr/bin/env bash
# (Re)starts the SSH tunnel: localhost:8000 on this machine -> vLLM on the Brev instance.
#   serving/tunnel.sh          start (kills any old tunnel first)
#   serving/tunnel.sh stop     stop it
#   serving/tunnel.sh status   show whether it's up and the endpoint answers
# Runs under autossh-style supervision: a bash loop that reconnects if ssh drops.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$HERE")"
HOST=${BREV_HOST:-rentus-operator}
LPORT=${LPORT:-8000}
RPORT=${RPORT:-8000}
PIDFILE="$HERE/.tunnel.pid"
LOG="$HERE/.tunnel.log"

# brev's ssh_config mints a cert with `brev mint-cert`, which reads BREV_API_KEY from env.
if [ -f "$ROOT/.env" ]; then set -a; . "$ROOT/.env"; set +a; export BREV_API_KEY; fi

stop() {
  if [ -f "$PIDFILE" ]; then
    kill "$(cat "$PIDFILE")" 2>/dev/null || true
    rm -f "$PIDFILE"
  fi
  pkill -f "ssh .*-L ${LPORT}:127.0.0.1:${RPORT} .*${HOST}" 2>/dev/null || true
}

status() {
  if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then echo "tunnel loop running (pid $(cat "$PIDFILE"))"; else echo "tunnel loop not running"; fi
  code=$(curl -s -o /dev/null -w '%{http_code}' -m 5 "http://localhost:${LPORT}/health" || true)
  echo "GET localhost:${LPORT}/health -> ${code:-none}"
}

case "${1:-start}" in
  stop) stop; echo stopped; exit 0 ;;
  status) status; exit 0 ;;
esac

stop
nohup bash -c "
  while true; do
    ssh -N -o BatchMode=yes -o ExitOnForwardFailure=yes \
        -o ServerAliveInterval=15 -o ServerAliveCountMax=3 \
        -L ${LPORT}:127.0.0.1:${RPORT} ${HOST}
    echo \"\$(date -Is) ssh exited (\$?), reconnecting in 5s\"
    sleep 5
  done
" >"$LOG" 2>&1 &
echo $! > "$PIDFILE"
sleep 4
status
