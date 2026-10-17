#!/usr/bin/env bash
# Health check for the whole system. Prints one PASS/FAIL/WARN line per check, exits 1 on any FAIL.
#   scripts/doctor.sh           everything (channel tests drive Chromium, ~2 min)
#   scripts/doctor.sh --quick   skip the channels browser tests
# Endpoints: operator  localhost:8000  (serving/tunnel.sh)
#            reader    localhost:8011  (LPORT=8011 RPORT=8001 serving/tunnel.sh)
# Secrets are sourced from .env into this process only and never printed.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
QUICK=0; [ "${1:-}" = "--quick" ] && QUICK=1
PY="$ROOT/.venv/bin/python"
FAILS=0
pass() { printf '  PASS  %s\n' "$1"; }
fail() { printf '  FAIL  %s\n' "$1"; FAILS=$((FAILS + 1)); }
warn() { printf '  WARN  %s\n' "$1"; }

if [ -f "$ROOT/.env" ]; then set -a; . "$ROOT/.env"; set +a; else warn ".env missing (cp .env.example .env)"; fi
OP_URL="${OPERATOR_BASE_URL:-http://localhost:8000/v1}"; OP_URL="${OP_URL%/}"
RD_URL="${READER_BASE_URL:-http://localhost:8011/v1}"; RD_URL="${RD_URL%/}"

echo "environment"
if [ -x "$PY" ] && "$PY" -c 'import sys; assert sys.version_info[:2] == (3, 12)' 2>/dev/null; then
  if "$PY" -c 'import rentus_tools, rentus_operator, console.app, channels.adapters.engine' 2>/dev/null; then
    pass ".venv (Python 3.12): rentus_tools, rentus_operator, console, channels import"
  else fail ".venv imports (run scripts/setup.sh)"; fi
else fail ".venv missing or not Python 3.12 (run scripts/setup.sh)"; fi
[ -x "$ROOT/gym/.venv/bin/python" ] && pass "gym/.venv present" || warn "gym/.venv missing (scripts/setup.sh --gym)"

echo "tunnels"
for spec in "8000 operator" "8011 reader"; do
  set -- $spec
  out=$(LPORT=$1 bash "$ROOT/serving/tunnel.sh" status 2>&1)
  if grep -q "loop running" <<<"$out" && grep -q -- "-> 200" <<<"$out"; then pass "$2 tunnel localhost:$1 up, /health 200"
  else fail "$2 tunnel localhost:$1: $(tr '\n' ' ' <<<"$out")"; fi
done

models() {  # $1 url, $2 key -> comma-separated model ids, empty on failure
  curl -s -m 6 -H "Authorization: Bearer ${2:-none}" "$1/models" 2>/dev/null |
    "$PY" -c 'import json,sys; print(",".join(m["id"] for m in json.load(sys.stdin)["data"]))' 2>/dev/null
}
echo "endpoints"
ids=$(models "$OP_URL" "${OPERATOR_API_KEY:-}")
[ -n "$ids" ] && pass "operator $OP_URL/models -> $ids" || fail "operator $OP_URL/models not answering"
ids=$(models "$RD_URL" "${READER_API_KEY:-${OPERATOR_API_KEY:-}}")
[ -n "$ids" ] && pass "reader $RD_URL/models -> $ids" || warn "reader $RD_URL/models not answering (read_reply uses the rules fallback)"

echo "tests"
run_tests() {  # $1 label, rest: command
  local label=$1; shift
  local out; out=$("$@" 2>&1); local rc=$?
  local last; last=$(grep -E 'passed|failed|error' <<<"$out" | tail -1)
  [ $rc -eq 0 ] && pass "$label: $last" || fail "$label: ${last:-exit $rc}"
}
run_tests "tools" "$PY" -m pytest -q "$ROOT/tools"
run_tests "operator" bash -c "cd '$ROOT/operator' && '$PY' -m pytest -q"
run_tests "console" "$PY" -m pytest -q "$ROOT/console/tests"
if [ -x "$ROOT/gym/.venv/bin/python" ]; then run_tests "gym" "$ROOT/gym/.venv/bin/python" -m pytest -q "$ROOT/gym/tests"; fi
if [ $QUICK = 0 ]; then run_tests "channels (Chromium)" "$PY" -m pytest -q "$ROOT/channels/tests"
else warn "channels tests skipped (--quick)"; fi

echo
if [ $FAILS = 0 ]; then echo "doctor: all checks passed"; else echo "doctor: $FAILS check(s) failed"; exit 1; fi
