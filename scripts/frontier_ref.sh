#!/usr/bin/env bash
# Frontier REFERENCE run (comparison only, never part of the running system): the operator tasks through
# the owner's local Claude Code CLI (subscription login) with native tool use over our sandbox tools.
#
#   scripts/frontier_ref.sh <taskfile> <seeds> [variant]
#   scripts/frontier_ref.sh gym/tasks/v3/heldout.jsonl 1
#   scripts/frontier_ref.sh gym/tasks/v2/heldout.jsonl 1,2,3
#
# <seeds>: comma list of repeat tags. The frontier's sampling seed is NOT controllable; each tag is one
#          independent repeat, named <prefix><variant>-s<tag>.
# [variant]: default guard+prompt3+style+rhist+readermodel (the final config). readermodel needs the
#          fine-tuned reader at READER_BASE_URL (.env); the script refuses to run if it is unreachable,
#          unless ALLOW_READER_FALLBACK=1, which drops +readermodel (rule-based read_reply) and says so.
# Env: FRONTIER_MODEL (claude-opus-5-5 | claude-fable-5-1, default claude-opus-5-5), FRONTIER_EFFORT
#      (default high), FRONTIER_WORKERS (default 3, max 3), FREEZE_COMMIT (if set, refuse when anything
#      under gym/frozen_paths.txt differs from it), PREFIX (default <taskset>-<split>-frontier-cc-),
#      OPERATOR_CONFIG (JSON RunConfig overrides passed as --operator-config, e.g. the Amendment 6 final config
#      '{"prompt_version":"v4","tool_descriptions":"concierge","guard_stand_down":true}'),
#      PRINT_RUN_NAMES=1 (print the run names this call would write, one per line, and exit: no setup, no calls).
# Run names for the confirmatory plan: `scripts/frontier_ref.sh gym/tasks/v3/heldout.jsonl 1,2,3,4,5` writes
# v3-heldout-frontier-cc-guard+prompt3+style+rhist+readermodel-s1..s5, the names gym/confirmatory_v3.json lists
# (checked by gym/tests/test_stats_confirmatory.py). ALLOW_READER_FALLBACK=1 changes the names, so such runs are
# missing from the plan, and `gym/stats.py plan --check` fails on them.
set -euo pipefail
cd "$(dirname "$0")/.."
[ $# -ge 2 ] || { sed -n 2,26p "$0"; exit 2; }
TASKS=$1; SEEDS=$2; VARIANT=${3:-guard+prompt3+style+rhist+readermodel}
SET=$(basename "$(dirname "$TASKS")"); SPLIT=$(basename "$TASKS" .jsonl)
[ "$SET" = tasks ] && SET=v1
PREFIX=${PREFIX:-$SET-$SPLIT-frontier-cc-}
if [ "${PRINT_RUN_NAMES:-0}" = 1 ]; then
  for s in ${SEEDS//,/ }; do echo "$PREFIX$VARIANT-s$s"; done
  exit 0
fi
MODEL=${FRONTIER_MODEL:-claude-opus-5-5}; EFFORT=${FRONTIER_EFFORT:-high}; WORKERS=${FRONTIER_WORKERS:-3}
PY=gym/.venv-frontier/bin/python
[ -f "$TASKS" ] || { echo "no task file $TASKS"; exit 2; }
[ "$WORKERS" -le 3 ] || { echo "FRONTIER_WORKERS must be <= 3 (subscription limits)"; exit 2; }
case "$MODEL" in claude-opus-5-5|claude-fable-5-1) ;; *) echo "frontier model must be claude-opus-5-5 or claude-fable-5-1"; exit 2;; esac

if [ ! -x "$PY" ] || ! "$PY" -c "import claude_agent_sdk" 2>/dev/null; then
  echo "setting up gym/.venv-frontier (claude-agent-sdk 0.2.163, deps pinned to releases before 2026-10-03)"
  uv venv -q --allow-existing --python 3.12 gym/.venv-frontier
  uv pip install -q --exclude-newer 2026-10-03T00:00:00Z --python "$PY" -r gym/requirements.txt 'claude-agent-sdk==0.2.163'
fi

mapfile -t FROZEN < <(grep -v '^[[:space:]]*#' gym/frozen_paths.txt | sed '/^[[:space:]]*$/d')
if [ -n "${FREEZE_COMMIT:-}" ]; then
  git diff --quiet "$FREEZE_COMMIT" -- "${FROZEN[@]}" \
    || { echo "frozen paths differ from $FREEZE_COMMIT; refusing to run"; exit 3; }
fi
if [ "$TASKS" = gym/tasks/v3/heldout.jsonl ] && [ -n "$(git status --porcelain -- "${FROZEN[@]}")" ]; then
  echo "frozen paths are dirty (gym/frozen_paths.txt); a confirmatory run would be void. Refusing."; exit 3
fi

if [[ "+$VARIANT+" == *"+readermodel+"* ]]; then
  if ! "$PY" - <<'EOF'
import os, sys, urllib.request
sys.path.insert(0, "gym"); import run_eval; run_eval.load_env_file()
u, k = os.environ.get("READER_BASE_URL"), os.environ.get("READER_API_KEY", "EMPTY")
try:
    urllib.request.urlopen(urllib.request.Request(u.rstrip("/") + "/models", headers={"Authorization": f"Bearer {k}"}), timeout=10)
except Exception as e:
    print(f"fine-tuned reader unreachable ({type(e).__name__})"); sys.exit(1)
EOF
  then
    if [ "${ALLOW_READER_FALLBACK:-0}" = 1 ]; then
      VARIANT=${VARIANT//+readermodel/}; echo "ALLOW_READER_FALLBACK=1: running $VARIANT (rule-based read_reply)"
    else
      echo "refusing: start the reader (serving/rebuild.sh) or set ALLOW_READER_FALLBACK=1"; exit 4
    fi
  fi
fi

echo "frontier reference: $MODEL effort=$EFFORT operator_config=${OPERATOR_CONFIG:-none} via $(claude --version 2>/dev/null) | tasks $TASKS | variant $VARIANT | repeats $SEEDS | workers $WORKERS"
for s in ${SEEDS//,/ }; do
  "$PY" gym/ablate.py --run-name _ --tasks-file "$TASKS" --variants "$VARIANT" --api claude_code \
    --model "$MODEL" --effort "$EFFORT" --prefix "$PREFIX" --seed-tag="-s$s" --workers "$WORKERS" --retry-errors 3 \
    ${OPERATOR_CONFIG:+--operator-config "$OPERATOR_CONFIG"}
done
