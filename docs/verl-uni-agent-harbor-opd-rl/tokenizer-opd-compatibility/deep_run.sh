#!/usr/bin/env bash
set -euo pipefail
ROOT=/workspace/verl-uni-agent-harbor-opd-rl
OUT="$ROOT/runs/opd-deep-audit-20260924"
source "$ROOT/envs/ua-verl-py312-vllm023-ws1/bin/activate"
export VIRTUAL_ENV="$ROOT/envs/ua-verl-py312-vllm023-ws1"
export PYTHONNOUSERSITE=1 VLLM_USE_FLASHINFER_SAMPLER=0 CUDA_VISIBLE_DEVICES=0
export PYTHONPATH="$ROOT/src/uni-agent/verl"
trap 'printf "exit=%s\n" "$?"' EXIT
python -c 'import subprocess; assert int(subprocess.check_output(["nvidia-smi","-i","0","--query-gpu=memory.used","--format=csv,noheader,nounits"])) < 2000'
python "$OUT/deep_numeric.py" "$OUT/numeric.json"
python "$OUT/deep_replay.py" prepare --out "$OUT"
python "$OUT/deep_replay.py" hf --out "$OUT"
python "$OUT/deep_replay.py" vllm --out "$OUT"
python "$OUT/deep_replay.py" compare --out "$OUT"
