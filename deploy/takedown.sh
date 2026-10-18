#!/usr/bin/env bash
# Take the public read-only console offline: drop console.rentus.homes from the
# rentus-demo tunnel, restart the tunnel, stop the :8092 read-only console and
# restart the public page without the console button. demo.rentus.homes stays up.
# Pass --all to also stop demo.rentus.homes (tunnel + page app).
set -u
cd "$(dirname "$0")/.."
CFG="$HOME/.cloudflared/rentus-demo.yml"
pid_on() { ss -ltnp 2>/dev/null | grep "127.0.0.1:$1 " | grep -o 'pid=[0-9]*' | cut -d= -f2 | sort -u; }
tunnel_pids() { pgrep -f "cloudflared .*--config $CFG" || true; }

if [ "${1:-}" = "--all" ]; then
  for p in $(tunnel_pids); do kill "$p"; done
  for p in $(pid_on 8091); do kill "$p"; done
else
  # remove the console ingress rule (hostname line + its service line), restart the tunnel
  python3 - "$CFG" <<'PY'
import sys, re
p = sys.argv[1]; s = open(p).read()
s = re.sub(r"  - hostname: console\.rentus\.homes\n    service: [^\n]*\n", "", s)
open(p, "w").write(s)
PY
  for p in $(tunnel_pids); do kill "$p"; done
  sleep 2
  nohup cloudflared tunnel --no-autoupdate --config "$CFG" run rentus-demo >> runs/public_site_tunnel.log 2>&1 &
  # page without the console button
  for p in $(pid_on 8091); do kill "$p"; done
  sleep 1
  PUBLIC_DEMO_EMAIL=info@rentus.homes nohup .venv/bin/python -m uvicorn deploy.public_site.app:app \
    --host 127.0.0.1 --port 8091 >> runs/public_site.log 2>&1 &
fi
for p in $(pid_on 8092); do kill "$p"; done
sleep 4
echo "console.rentus.homes: $(curl -s -o /dev/null -m 10 -w '%{http_code}' https://console.rentus.homes/) (404 or 530 = offline)"
echo "demo.rentus.homes:    $(curl -s -o /dev/null -m 10 -w '%{http_code}' https://demo.rentus.homes/)"
echo ":8092 listening:      $(pid_on 8092 | wc -l) process(es)"
