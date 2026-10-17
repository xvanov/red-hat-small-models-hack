#!/usr/bin/env bash
# Install NeMo Gym 0.6.0 (Python 3.13.14) into gym/.venv-nemo and the gym runner deps into gym/.venv.
set -euo pipefail
cd "$(dirname "$0")"
UV_NEW=(uvx --from 'uv>=0.11' uv)   # older uv releases cannot download CPython 3.13.14
"${UV_NEW[@]}" python install 3.13.14
"${UV_NEW[@]}" venv --allow-existing --python 3.13.14 .venv-nemo
"${UV_NEW[@]}" pip install --python .venv-nemo/bin/python 'nemo-gym==0.6.0'
uv venv --allow-existing --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
echo "ok: .venv-nemo/bin/gym $(.venv-nemo/bin/python -c 'import nemo_gym; print(nemo_gym.__version__)')"
