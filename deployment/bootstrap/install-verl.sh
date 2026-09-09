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
# Apply is explicit and belongs to a new inactive checkout. Installation only
# verifies the exact authorized overlay; every additional dirty change is rejected.
python3 "$repo_root/deployment/checks/verl_source_overlay.py" --repo "$repo_root/verl"
cd "$repo_root/verl"
UV_PROJECT_ENVIRONMENT="$DSH_TRAIN_VENV" UV_CACHE_DIR="$DSH_UV_CACHE" \
  uv sync --frozen --extra fsdp --extra vllm
# Apply the one reviewed metadata correction without modifying upstream uv.lock
# or re-resolving the GPU stack. The deployment lock must authorize this exact
# overlay against this exact paired VERL source and lock bytes.
env -u PYTHONPATH "$DSH_TRAIN_VENV/bin/python" -I - "$repo_root" "$expected_verl" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
if sys.implementation.name != "cpython" or sys.version_info[:2] != (3, 12):
    raise SystemExit("the pinned numpy overlay requires CPython 3.12 on Linux x86_64")
lock = json.loads((root / "deployment/versions/g1-deployment-lock.json").read_text())
gpu = lock["gpu_python"]
if lock["integration"]["verl_revision"] != sys.argv[2]:
    raise SystemExit("deployment lock does not match paired VERL revision")
digest = "sha256:" + hashlib.sha256((root / "verl/uv.lock").read_bytes()).hexdigest()
if gpu["verl_uv_lock_sha256"] != digest:
    raise SystemExit("upstream uv.lock does not match deployment lock")
if gpu["validated_resolution_adjustment"]["numpy"] != "2.3.5":
    raise SystemExit("deployment lock does not authorize the reviewed numpy==2.3.5 overlay")
PY
# Project override-dependencies can replace even the exact numpy requirement.
# Only frozen sync above should read upstream uv configuration; post-lock
# operations must honor our explicit requirement/hash and checkout arguments.
UV_CACHE_DIR="$DSH_UV_CACHE" uv pip install --no-config --python "$DSH_TRAIN_VENV/bin/python" \
  --no-deps --only-binary=:all: --require-hashes -r "$repo_root/deployment/versions/native-numpy-overlay.txt"
# Add only this checkout; never re-resolve the locked GPU dependencies.
UV_CACHE_DIR="$DSH_UV_CACHE" uv pip install --no-config --python "$DSH_TRAIN_VENV/bin/python" --no-deps -e "$repo_root"
UV_CACHE_DIR="$DSH_UV_CACHE" uv pip check --no-config --python "$DSH_TRAIN_VENV/bin/python"
# An old PYTHONPATH or the checkout working directory must not conceal missing
# editable installs in the fresh environment. No GPU process is started here.
env -u PYTHONPATH "$DSH_TRAIN_VENV/bin/python" -I -c '
import importlib.metadata
from pathlib import Path
import sys
import numpy
import torch
import verl
import uni_agent

root = Path(sys.argv[1]).resolve()
if Path(sys.prefix).resolve() != Path(sys.argv[2]).resolve():
    raise SystemExit("import probe did not use the dedicated environment")
if importlib.metadata.version("numpy") != "2.3.5":
    raise SystemExit("numpy overlay version mismatch")
for module, expected in ((uni_agent, root / "uni_agent"), (verl, root / "verl/verl")):
    if not Path(module.__file__).resolve().is_relative_to(expected):
        raise SystemExit(f"{module.__name__} imported from an unexpected checkout")
print("Isolated imports passed: numpy, torch, verl, uni_agent")
' "$repo_root" "$DSH_TRAIN_VENV"
