#!/usr/bin/env bash
set -euo pipefail

# Run on a Linux Runpod node.  The CPU node prepares the reproducible
# environment and runs data/dataloader smoke tests; GPU nodes reuse the same
# environment path on the shared volume for SFT.
ROOT=${VERL_SOURCE_ROOT:-/workspace/verl-uni-agent-harbor-opd-rl/src/uni-agent/verl}
ENV=${VERL_SFT_ENV:-/workspace/envs/performance-9b-verl-sft}

command -v uv >/dev/null || { echo "uv is required" >&2; exit 1; }
test -f "$ROOT/pyproject.toml" || { echo "missing VERL pyproject: $ROOT" >&2; exit 1; }
mkdir -p "$(dirname "$ENV")"

# Keep the lockfile from the checked-out VERL source.  The fsdp extra is the
# SFT training backend; no vLLM is needed for SFT itself.
UV_PROJECT_ENVIRONMENT="$ENV" uv sync --project "$ROOT" --extra fsdp --python 3.12
"$ENV/bin/python" - <<'PY'
import torch
import transformers
import verl
print({"torch": torch.__version__, "transformers": transformers.__version__, "verl": verl.__file__})
PY
