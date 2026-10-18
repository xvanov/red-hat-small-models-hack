#!/usr/bin/env bash
# Run the whole twins pipeline. Usage: data/twins/run.sh [--fixture] [--limit N] [extra args for every step]
# Real mode: set TWINS_OWNER_NAMES (owner display names, comma-separated) first.
set -euo pipefail
cd "$(dirname "$0")"
PY=.venv/bin/python
for step in ingest label twin filter to_tasks; do
  echo "== $step"
  $PY "$step.py" "$@"
done
