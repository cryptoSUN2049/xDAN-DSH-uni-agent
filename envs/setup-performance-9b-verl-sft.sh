#!/usr/bin/env bash
set -euo pipefail

# Run on a Linux Runpod node.  The CPU node prepares the reproducible
# environment and runs data/dataloader smoke tests; GPU nodes reuse the same
# environment path on the shared volume for SFT.
ROOT=${VERL_SOURCE_ROOT:-/workspace/verl-uni-agent-harbor-opd-rl/src/uni-agent/verl}
WORKSPACE_ROOT=${WORKSPACE_ROOT:-/workspace/verl-uni-agent-harbor-opd-rl}
ENV=${VERL_SFT_ENV:-$WORKSPACE_ROOT/envs/performance-9b-verl-sft}
BASE_ENV=${VERL_BASE_ENV:-}

command -v uv >/dev/null || { echo "uv is required" >&2; exit 1; }
test -f "$ROOT/pyproject.toml" || { echo "missing VERL pyproject: $ROOT" >&2; exit 1; }
mkdir -p "$(dirname "$ENV")"

if [[ -n "$BASE_ENV" && -x "$BASE_ENV/bin/python" ]]; then
  # CPU nodes can reuse an already uv-created VERL environment instead of
  # downloading CUDA wheels.  GPU nodes omit BASE_ENV and resolve the lock.
  ln -sfn "$BASE_ENV" "$ENV"
else

# Keep the lockfile from the checked-out VERL source.  The fsdp extra is the
# SFT training backend; no vLLM is needed for SFT itself.
# flash-attn is an optional kernel for GPU throughput.  The current VERL
# wheelhouse has no matching CPython 3.12 wheel on this CPU preparation node;
# omit it here and install a CUDA-matched wheel on the GPU node if available.
UV_CACHE_DIR=${UV_CACHE_DIR:-$WORKSPACE_ROOT/cache/uv} \
  UV_PROJECT_ENVIRONMENT="$ENV" uv sync --project "$ROOT" --extra fsdp --python 3.12 --no-install-package flash-attn
fi
"$ENV/bin/python" - <<'PY'
import torch
import transformers
import verl
print({"torch": torch.__version__, "transformers": transformers.__version__, "verl": verl.__file__})
PY
