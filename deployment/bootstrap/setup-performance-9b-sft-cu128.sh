#!/usr/bin/env bash
# Build the isolated two-GPU SFT lane for the RunPod cu128 / torch280 image.
# All mutable state must stay on the network volume.
set -euo pipefail

ROOT="${WORKSPACE_ROOT:-/workspace/verl-uni-agent-harbor-opd-rl}"
LANE="${LANE:-performance-9b-sft-py312-cu128}"
VENV="${UV_VENV:-$ROOT/envs/$LANE}"
PYTHON="${UV_PYTHON:-/usr/bin/python3.12}"
export UV_CACHE_DIR="${UV_CACHE_DIR:-$ROOT/cache/uv/$LANE}"
export CUDA_HOME="${CUDA_HOME:-/usr/local/cuda-12.8}"
export PATH="$CUDA_HOME/bin:$PATH"
export TORCH_CUDA_ARCH_LIST="${TORCH_CUDA_ARCH_LIST:-12.0}"
export FLASH_ATTN_CUDA_ARCHS="${FLASH_ATTN_CUDA_ARCHS:-120}"
RUNS="${RUNS_DIR:-$ROOT/runs}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG="$RUNS/uv-lane-$LANE-$STAMP.log"

[[ "$VENV" = /workspace/* ]] || { echo "venv must be under /workspace: $VENV" >&2; exit 2; }
[[ "$UV_CACHE_DIR" = /workspace/* ]] || { echo "uv cache must be under /workspace: $UV_CACHE_DIR" >&2; exit 2; }
[[ -x "$PYTHON" ]] || { echo "python not found: $PYTHON" >&2; exit 2; }
[[ -x "$CUDA_HOME/bin/nvcc" ]] || { echo "nvcc not found: $CUDA_HOME/bin/nvcc" >&2; exit 2; }
if [[ -d "$VENV/lib" ]] && [[ "$(find "$VENV/lib" -maxdepth 3 -name site-packages -exec sh -c 'ls "$1" | wc -l' _ {} \; | head -1)" -gt 10 ]]; then
  echo "refusing to overwrite populated venv: $VENV" >&2
  exit 2
fi

mkdir -p "$RUNS" "$UV_CACHE_DIR" "$(dirname "$VENV")"
exec > >(tee -a "$LOG") 2>&1
echo "lane=$LANE venv=$VENV python=$PYTHON cuda=$CUDA_HOME arch=$FLASH_ATTN_CUDA_ARCHS"

/usr/bin/uv venv "$VENV" --python "$PYTHON"

# The image's CUDA 12.8 / Torch 2.8 tuple is intentional. Do not let the
# cu130 project lane or a transitive dependency replace these three packages.
/usr/bin/uv pip install --python "$VENV/bin/python" \
  --index-url https://download.pytorch.org/whl/cu128 \
  torch==2.8.0 torchvision==0.23.0 torchaudio==2.8.0

/usr/bin/uv pip install --python "$VENV/bin/python" \
  accelerate codetiming datasets dill hydra-core 'numpy>=2.0' pandas peft \
  'pyarrow>=19' pybind11 pylatexenc 'transformers==5.8.0' 'ray[default]>=2.41.0' \
  torchdata 'tensordict>=0.8,<=0.10,!=0.9' wandb 'packaging>=20' tensorboard \
  fastapi uvicorn mathruler qwen-vl-utils torchcodec cachetools nvtx pytest \
  pytest-asyncio pytest-rerunfailures 'TransferQueue @ git+https://github.com/Ascend/TransferQueue.git@434f8c476b4be24bc087e6e95070e64efcc739f9' \
  'rl-insight==0.3.0' 'fla-core==0.5.2' 'flash-linear-attention==0.5.2'

# Install the local trainers without re-solving their cu130 extras. Runtime
# dependencies above are intentionally explicit for this cu128 lane.
/usr/bin/uv pip install --python "$VENV/bin/python" --no-deps \
  -e "$ROOT/src/uni-agent/verl" -e "$ROOT/src/uni-agent"

# Both extensions are source-built against this venv's Torch and CUDA 12.8.
/usr/bin/uv pip install --python "$VENV/bin/python" --no-build-isolation \
  --no-binary causal-conv1d causal-conv1d==1.7.0
/usr/bin/uv pip install --python "$VENV/bin/python" --no-build-isolation \
  --no-binary flash-attn flash-attn==2.8.3.post1

/usr/bin/uv pip check --python "$VENV/bin/python"
"$VENV/bin/python" - <<'PY'
import importlib
import torch

assert torch.__version__.startswith("2.8.0"), torch.__version__
assert torch.version.cuda == "12.8", torch.version.cuda
assert torch.cuda.device_count() >= 2, torch.cuda.device_count()
torch.cuda.synchronize()
importlib.import_module("flash_attn")
importlib.import_module("causal_conv1d")
importlib.import_module("verl")
importlib.import_module("uni_agent")
print("activation and imports passed", torch.__version__, torch.version.cuda)
PY

FREEZE="$RUNS/uv-lane-$LANE-$STAMP.freeze.txt"
/usr/bin/uv pip freeze --python "$VENV/bin/python" > "$FREEZE"
sha256sum "$FREEZE"
echo "freeze=$FREEZE"
