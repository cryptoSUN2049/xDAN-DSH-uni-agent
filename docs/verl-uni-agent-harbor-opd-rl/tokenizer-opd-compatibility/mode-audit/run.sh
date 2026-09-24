#!/usr/bin/env bash
set -euo pipefail
ROOT=/workspace/verl-uni-agent-harbor-opd-rl
OUT="$ROOT/runs/opd-mode-acceptance-20260924"
source "$ROOT/envs/ua-verl-py312-vllm023-ws1/bin/activate"
export VIRTUAL_ENV="$ROOT/envs/ua-verl-py312-vllm023-ws1"
export UV_PROJECT_ENVIRONMENT="$VIRTUAL_ENV"
export PYTHONNOUSERSITE=1 VLLM_USE_FLASHINFER_SAMPLER=0 CUDA_VISIBLE_DEVICES=0
export PYTHONPATH="$ROOT/src/uni-agent/verl"
trap 'printf "exit=%s\n" "$?"' EXIT
python -c 'import os,sys,subprocess; assert sys.prefix == os.environ["VIRTUAL_ENV"]; assert int(subprocess.check_output(["nvidia-smi","-i","0","--query-gpu=memory.used","--format=csv,noheader,nounits"])) < 2000'
# Each stage closes its process before the next allocates GPU memory.
timeout --signal=TERM --kill-after=30s 5400 python -u "$OUT/prepare.py" generate --out "$OUT" --max-new-tokens 1024
python "$OUT/finalize.py" preflight --out "$OUT"
if [[ -n "${CAPTURE_SAMPLES:-}" ]]; then
    python "$OUT/finalize.py" merge --out "$OUT" --capture-samples "$CAPTURE_SAMPLES"
fi
timeout --signal=TERM --kill-after=30s 5400 python -u "$OUT/deep_replay.py" hf --out "$OUT"
timeout --signal=TERM --kill-after=30s 5400 python -u "$OUT/deep_replay.py" vllm --out "$OUT"
python "$OUT/deep_replay.py" compare --out "$OUT"
python "$OUT/finalize.py" verdict --out "$OUT"
