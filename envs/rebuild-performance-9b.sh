#!/usr/bin/env bash
set -euo pipefail

# Run on a Linux Runpod checkout only. This script intentionally does not start
# training; it creates the named environments and records the resolved package
# set after the data gates have passed.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_ENV="${DATA_ENV:-/workspace/envs/performance-9b-data}"
RL_ENV="${RL_ENV:-/workspace/envs/performance-9b-harbor-rl}"

uv venv "$DATA_ENV" --python 3.12
uv sync --project "$ROOT/envs/performance-9b-data" --no-install-project

if [[ "${INSTALL_GPU:-0}" == "1" ]]; then
  uv venv "$RL_ENV" --python 3.12
  uv sync --project "$ROOT/envs/performance-9b-harbor-rl" --no-install-project
  uv pip freeze --python "$RL_ENV/bin/python" > "$ROOT/docs/performance-9b/environment-freeze-runpod.txt"
else
  echo "GPU environment not installed; set INSTALL_GPU=1 after data gates pass."
fi
