#!/usr/bin/env bash
set -euo pipefail
R=/workspace/apus-mimo-identity
ENV=/workspace/verl-uni-agent-harbor-opd-rl/envs/ua-verl-py312-vllm023-ws1
export VIRTUAL_ENV="$ENV"
export PATH="$ENV/bin:$PATH"
export PYTHONNOUSERSITE=1
export CUDA_VISIBLE_DEVICES=1
export KEEP_GPU_PROCESS=1
export VLLM_USE_FLASHINFER_SAMPLER=0
unset PYTHONPATH
exec "$ENV/bin/vllm" serve /workspace/models/MiMo-V2.6-Distill-Qwen-9B \
 --host 127.0.0.1 --port 8019 --served-model-name apus-9b-probe \
 --max-model-len 16384 --gpu-memory-utilization 0.65 --max-num-seqs 4 \
 --enforce-eager --enable-auto-tool-choice --tool-call-parser qwen3_coder \
 --reasoning-parser deepseek_r1
