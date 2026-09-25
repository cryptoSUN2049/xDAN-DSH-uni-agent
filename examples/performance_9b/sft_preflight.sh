#!/usr/bin/env bash
set -euo pipefail

# Fast, non-training gate for the workspace VERL SFT lane.
ROOT=${WORKSPACE_ROOT:-/workspace/verl-uni-agent-harbor-opd-rl}
PYTHON_BIN=${PYTHON_BIN:-$ROOT/envs/ua-verl-py312-vllm023-ws1/bin/python}
MODEL_PATH=${MODEL_PATH:-/workspace/models/Qwen3.5-9B}
DATA_ROOT=${DATA_ROOT:-/workspace/apus-data-cleaning/reports/verl-sft-v1}
NPROC_PER_NODE=${NPROC_PER_NODE:-2}
REPORT_PATH=${PREFLIGHT_REPORT_PATH:-$DATA_ROOT/preflight.json}

fail() { echo "PREFLIGHT_FAIL: $*" >&2; exit 2; }
[[ -x "$PYTHON_BIN" ]] || fail "missing VERL python: $PYTHON_BIN"
[[ -d "$MODEL_PATH" ]] || fail "missing model: $MODEL_PATH"
[[ -f "$DATA_ROOT/train.parquet" && -f "$DATA_ROOT/validation.parquet" ]] || fail "missing split parquet"
command -v nvidia-smi >/dev/null || fail "nvidia-smi is unavailable"
gpu_count=$(nvidia-smi --query-gpu=name --format=csv,noheader | wc -l | tr -d ' ')
[[ "$gpu_count" -ge "$NPROC_PER_NODE" ]] || fail "requested $NPROC_PER_NODE GPUs, found $gpu_count"

mkdir -p "$(dirname "$REPORT_PATH")"
export PYTHONPATH="$ROOT/src/uni-agent:$ROOT/src/uni-agent/verl:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONNOUSERSITE=1
"$PYTHON_BIN" - "$DATA_ROOT" "$REPORT_PATH" "$MODEL_PATH" "$gpu_count" <<'PY'
import json
import os
import sys
from pathlib import Path

data_root, report_path, model_path, gpu_count = sys.argv[1:]
import pyarrow.parquet as pq

rows = {}
for name in ("train.parquet", "validation.parquet"):
    path = Path(data_root, name)
    table = pq.ParquetFile(path)
    rows[name] = {"rows": table.metadata.num_rows, "columns": table.schema.names}

import verl
from examples.performance_9b.verl_sft_dataset import ApusMultiTurnSFTDataset

report = {
    "status": "passed",
    "python": sys.executable,
    "verl_version": getattr(verl, "__version__", "unknown"),
    "adapter": ApusMultiTurnSFTDataset.__name__,
    "model_path": model_path,
    "gpu_count": int(gpu_count),
    "parquet": rows,
    "wandb_credential": bool(os.environ.get("WANDB_API_KEY")) or Path.home().joinpath(".netrc").exists(),
    "rl_insight_requested": os.environ.get("VERL_RL_INSIGHT_ENABLE") == "1",
}
if report["rl_insight_requested"]:
    import rl_insight
    report["rl_insight_version"] = getattr(rl_insight, "__version__", "unknown")
Path(report_path).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
print(json.dumps(report, ensure_ascii=False))
PY
echo "PREFLIGHT_PASS: $REPORT_PATH"
