#!/usr/bin/env bash
# Build the isolated two-GPU SFT lane for the RunPod cu128 / torch280 image.
# All mutable state must stay on the network volume.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CONSTRAINTS="$SCRIPT_DIR/../versions/uv-lanes/performance-9b-sft-py312-cu128.constraints.txt"
BUILD_CONSTRAINTS="$SCRIPT_DIR/../versions/uv-lanes/performance-9b-sft-py312-cu128.build-constraints.txt"
export MIN_GPU_COUNT="${MIN_GPU_COUNT:-2}"
[[ "$MIN_GPU_COUNT" =~ ^[0-9]+$ ]] || { echo "MIN_GPU_COUNT must be a nonnegative integer" >&2; exit 2; }

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

sha256sum "$CONSTRAINTS" "$BUILD_CONSTRAINTS"
/usr/bin/uv --version
"$CUDA_HOME/bin/nvcc" --version
/usr/bin/uv venv "$VENV" --python "$PYTHON"

# Every resolution has both runtime and build constraints. Install build tools
# first; all later source/editable builds use this exact environment.
install() {
  /usr/bin/uv pip install --python "$VENV/bin/python" \
    --constraints "$CONSTRAINTS" --build-constraints "$BUILD_CONSTRAINTS" "$@"
}
install -r "$BUILD_CONSTRAINTS"

# The image's CUDA 12.8 / Torch 2.8 tuple is intentional. Do not let the
# cu130 project lane or a transitive dependency replace these three packages.
install --index-url https://download.pytorch.org/whl/cu128 \
  torch==2.8.0+cu128 torchvision==0.23.0+cu128 torchaudio==2.8.0+cu128

# Install the entire audited runtime, not just its top-level requirements.
# Delay CUDA extensions until Torch is installed. Preserve direct VCS pins.
RUNTIME_REQUIREMENTS="$RUNS/uv-lane-$LANE-$STAMP.requirements.txt"
awk '!/^(causal-conv1d|flash-attn)==/' "$CONSTRAINTS" > "$RUNTIME_REQUIREMENTS"
install --no-build-isolation -r "$RUNTIME_REQUIREMENTS"

# Install the local trainers without re-solving their cu130 extras. Runtime
# dependencies above are intentionally explicit for this cu128 lane.
install --no-build-isolation --no-deps \
  -e "$ROOT/src/uni-agent/verl" -e "$ROOT/src/uni-agent"

# Both extensions are source-built against this venv's Torch and CUDA 12.8.
install --no-build-isolation \
  --no-binary causal-conv1d causal-conv1d==1.7.0
install --no-build-isolation \
  --no-binary flash-attn flash-attn==2.8.3.post1

/usr/bin/uv pip check --python "$VENV/bin/python"
"$VENV/bin/python" - "$CONSTRAINTS" <<'PY'
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys

import torch
from packaging.requirements import Requirement

verified = 0
for line in Path(sys.argv[1]).read_text().splitlines():
    if not line.strip() or line.startswith("#"):
        continue
    requirement = Requirement(line)
    distribution = importlib.metadata.distribution(requirement.name)
    if requirement.url:
        provenance = json.loads(distribution.read_text("direct_url.json") or "{}")
        expected_url, expected_commit = requirement.url.removeprefix("git+").rsplit("@", 1)
        assert provenance.get("url") == expected_url, requirement.name
        assert provenance.get("vcs_info", {}).get("commit_id") == expected_commit, requirement.name
    else:
        assert distribution.version in requirement.specifier, (requirement.name, distribution.version)
    verified += 1
print("audited runtime distributions verified:", verified)

assert torch.__version__.startswith("2.8.0"), torch.__version__
assert torch.version.cuda == "12.8", torch.version.cuda
minimum = int(os.environ["MIN_GPU_COUNT"])
if minimum:
    assert torch.cuda.device_count() >= minimum, torch.cuda.device_count()
    torch.cuda.synchronize()
else:
    print("CPU-only rebuild/import acceptance: CUDA availability and forward NOT tested")
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
