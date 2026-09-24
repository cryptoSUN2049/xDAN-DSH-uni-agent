#!/usr/bin/env bash
set -euo pipefail
ROOT=/workspace/verl-uni-agent-harbor-opd-rl
RUN="$ROOT/runs/opd-live-acceptance-20260924"
CODE="$ROOT/runs/overnight-opd-20260924-control-attempt2"
source "$ROOT/envs/ua-verl-py312-vllm023-ws1/bin/activate"
export VIRTUAL_ENV="$ROOT/envs/ua-verl-py312-vllm023-ws1"
export PYTHONNOUSERSITE=1 VLLM_USE_FLASHINFER_SAMPLER=0
export PYTHONPATH="$ROOT/src/uni-agent/verl:$CODE"
unset OPD_LIVE_AUDIT_DIR
trap 'printf "exit=%s\n" "$?"' EXIT
[[ "$(cat "$RUN/exit-code.txt")" == 0 ]]
python -c 'import subprocess; assert all(int(x)<2000 for x in subprocess.check_output(["nvidia-smi","--query-gpu=memory.used","--format=csv,noheader,nounits"],text=True).split())'
python "$CODE/export_checkpoints.py" --checkpoints "$RUN/checkpoints" --out "$RUN/adapters" --base-model /workspace/models/Qwen3.5-9B
export CUDA_VISIBLE_DEVICES=0
python "$CODE/evaluate.py" --model /workspace/models/Qwen3.5-9B --model-id live-audit-step1 --data "$ROOT/data-overnight-opd-20260924-v2/val.parquet" --out "$RUN/reload" --adapter "$RUN/adapters/global_step_1/lora_adapter" --max-tokens 4096
