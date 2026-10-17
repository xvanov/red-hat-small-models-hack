#!/usr/bin/env bash
# One project environment at <repo>/.venv (Python 3.12, uv-managed) with the tools, operator,
# console and channels packages installed editable, plus Playwright's Chromium.
#   scripts/setup.sh            build or update .venv
#   scripts/setup.sh --gym      also build gym/.venv-nemo + gym/.venv (NeMo Gym, Python 3.13)
# Always uses explicit .venv paths: a bare `python3.12` on PATH may belong to another project.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
command -v uv >/dev/null || { echo "uv not found: curl -LsSf https://astral.sh/uv/install.sh | sh"; exit 1; }

PY="$ROOT/.venv/bin/python"
if [ ! -x "$PY" ]; then uv venv "$ROOT/.venv" --python 3.12 --managed-python 2>/dev/null || uv venv "$ROOT/.venv" --python 3.12; fi
"$PY" -c 'import sys; assert sys.version_info[:2] == (3, 12), sys.version' 
# --exclude-newer: every third-party release must be public 2+ weeks before the event (Oct 17 2026).
uv pip install --exclude-newer 2026-10-03 --python "$PY" -e "$ROOT/tools[test]" -e "$ROOT/operator[dev]" -e "$ROOT"
"$ROOT/.venv/bin/playwright" install chromium >/dev/null
[ -f "$ROOT/.env" ] || { cp "$ROOT/.env.example" "$ROOT/.env"; echo "created .env from .env.example: fill in the keys"; }

if [ "${1:-}" = "--gym" ]; then bash "$ROOT/gym/setup_nemo_gym.sh"; fi

"$PY" - <<'PY'
import importlib
for m in ("rentus_tools", "rentus_operator", "console.app", "channels.adapters.engine"):
    importlib.import_module(m)
print("ok: rentus_tools, rentus_operator, console, channels import from .venv")
PY
echo "next: scripts/doctor.sh"
