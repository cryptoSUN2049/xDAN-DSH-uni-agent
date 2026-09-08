#!/usr/bin/env bash
# Materialize the paired upstream lock in a dedicated Linux Python environment.
set -euo pipefail
: "${DSH_TRAIN_VENV:?Set DSH_TRAIN_VENV to an absolute dedicated environment path}"
: "${DSH_UV_CACHE:?Set DSH_UV_CACHE to an absolute persistent cache path}"
[[ "$DSH_TRAIN_VENV" = /* && "$DSH_UV_CACHE" = /* ]] || exit 2
[[ "$(uname -s)" == Linux && "$(uname -m)" == x86_64 ]] || exit 2
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
expected_verl=fefb080262e1c015a0ea05f958822a6a512dc795
[[ "$(git -C "$repo_root/verl" rev-parse HEAD)" == "$expected_verl" ]] || exit 2
if [[ -n "$(git -C "$repo_root/verl" status --porcelain --untracked-files=no)" ]]; then
  echo 'VERL has modified tracked files; refusing to install a changed lock/source.' >&2
  exit 2
fi
cd "$repo_root/verl"
UV_PROJECT_ENVIRONMENT="$DSH_TRAIN_VENV" UV_CACHE_DIR="$DSH_UV_CACHE" \
  uv sync --frozen --extra fsdp --extra vllm
# Add only this checkout; never re-resolve the locked GPU dependencies.
UV_CACHE_DIR="$DSH_UV_CACHE" uv pip install --python "$DSH_TRAIN_VENV/bin/python" --no-deps -e "$repo_root"
