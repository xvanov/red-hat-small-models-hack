#!/usr/bin/env bash
# Starts the demo: tunnels to the Brev instance (operator 8000, reader 8011) if they're down,
# then the console, and prints the URL.
#   scripts/demo.sh            start (console in the background, log in runs/console.log)
#   scripts/demo.sh stop       stop the console (tunnels stay up)
#   CONSOLE_PORT=8090 scripts/demo.sh
#   CONSOLE_FORCE_STUB=1 scripts/demo.sh    rehearse with no GPU (badge says stub)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PORT=${CONSOLE_PORT:-8080}
PY="$ROOT/.venv/bin/python"
PIDFILE="$ROOT/runs/.console-$PORT.pid"
LOG="$ROOT/runs/console.log"
mkdir -p "$ROOT/runs"

if [ "${1:-}" = stop ]; then
  [ -f "$PIDFILE" ] && kill "$(cat "$PIDFILE")" 2>/dev/null || true
  rm -f "$PIDFILE"; echo "console stopped"; exit 0
fi
[ -x "$PY" ] || { echo "no .venv: run scripts/setup.sh first"; exit 1; }

health() { curl -s -o /dev/null -w '%{http_code}' -m 4 "http://localhost:$1/health" 2>/dev/null || true; }
if [ "${CONSOLE_FORCE_STUB:-}" != 1 ]; then
  for spec in "8000 8000 operator" "8011 8001 reader"; do
    set -- $spec
    if [ "$(health "$1")" = 200 ]; then echo "$3 endpoint up on localhost:$1"
    else
      echo "$3 tunnel down, starting it (localhost:$1 -> instance:$2)"
      LPORT=$1 RPORT=$2 bash "$ROOT/serving/tunnel.sh" >/dev/null 2>&1 || true
      [ "$(health "$1")" = 200 ] && echo "  $3 up" || echo "  $3 still down (the console will say so in its badge)"
    fi
  done
fi

if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  echo "console already running (pid $(cat "$PIDFILE"))"
else
  nohup "$PY" -m uvicorn console.app:app --host 127.0.0.1 --port "$PORT" --log-level warning >"$LOG" 2>&1 &
  echo $! > "$PIDFILE"
  for _ in $(seq 1 40); do
    curl -s -m 1 "http://127.0.0.1:$PORT/api/status" >/dev/null 2>&1 && break; sleep 0.5
  done
fi
status=$(curl -s -m 5 "http://127.0.0.1:$PORT/api/status" || true)
if [ -z "$status" ]; then echo "console did not start; see $LOG"; exit 1; fi
"$PY" -c 'import json,sys; s=json.loads(sys.argv[1]); print("badge:", s["badge"]["label"], "|", s.get("reader", {}).get("label", ""))' "$status"

# Tailnet-only relay so the owner's phone can open /approve (scripts/tailnet_forward.py); never the LAN.
if [ "$PORT" = 8080 ] && command -v tailscale >/dev/null 2>&1; then
  if ! pgrep -f "scripts/tailnet_forward.py" >/dev/null; then
    nohup /usr/bin/python3 "$ROOT/scripts/tailnet_forward.py" >"$ROOT/scripts/.tailnet_forward.log" 2>&1 &
    sleep 1
  fi
  TS_IP=$(tailscale ip -4 2>/dev/null | head -1)
  [ -n "$TS_IP" ] && echo "  phone:   http://$TS_IP:8080/approve   (tailnet only)"
fi
echo
echo "  console: http://localhost:$PORT"
echo "  try:     Appling Way room free Nov 1, \$750, private bath"
echo "  stop:    scripts/demo.sh stop"
