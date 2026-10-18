#!/usr/bin/env bash
# Start the blind labeler on 127.0.0.1:8090 and expose it on the tailnet only (100.64.38.18:8090).
# Extra args go to server.py, e.g. ./labeler/start.sh --source real
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$HERE")"
mkdir -p "$HERE/logs"
for f in server forward; do   # stop a previous run (pid files, so nothing else gets killed)
  [ -f "$HERE/logs/$f.pid" ] && kill "$(cat "$HERE/logs/$f.pid")" 2>/dev/null || true
done
sleep 0.5
nohup "$HERE/.venv/bin/python" "$HERE/server.py" "$@" > "$HERE/logs/server.log" 2>&1 &
echo $! > "$HERE/logs/server.pid"
nohup python3 "$REPO/scripts/tailnet_forward.py" --listen 100.64.38.18:8090 --target 127.0.0.1:8090 \
  > "$HERE/logs/forward.log" 2>&1 &
echo $! > "$HERE/logs/forward.pid"
sleep 1.5
cat "$HERE/logs/server.log" "$HERE/logs/forward.log"
echo "open http://100.64.38.18:8090"
