#!/usr/bin/env bash
# pipe-r4 (2-GPU pod): Qwen3.5-9B Student + Qwen3.8-27B Teacher (route 2, real Teacher)
# on the audited stage1 mix (40 train / 7 held-out, shared with pipe-r6), GRPO,
# 4 prompts x 8 rollouts per step, 32 concurrent sandboxes. Models are staged on
# local NVMe first; an optional PID argument waits for a previous run to exit.
# All three OOMs (13:41, 14:41, 15:4x UTC) were the Qwen3.8-27B Teacher vLLM on GPU1
# (it sees its card as cuda:0), not the 9B student: at gpu_memory_utilization 0.85
# weights + KV fill ~81 GiB and the prompt-logprob buffer (batched tokens x 248k
# vocab x 4 bytes, 7.25 GiB at 8192) does not fit.
# Settings v2 (user decision, 16:05 UTC): Teacher 0.70 / 4096-token steps / 4 sequences;
# student restored to prefix caching on, 8192-token steps, gpu_memory_utilization 0.45,
# identical in the pipe-r7 control.
R=/workspace/verl-uni-agent-harbor-opd-rl; P=$R/runs/pipe-r4; WAIT_PID="${1:-}"
mkdir -p /tmp/models
if [[ ! -f /tmp/models/.qwen35-copy-ok ]]; then
  echo "[chain $(date -u +%H:%M:%S)] copying 9B + 27B to /tmp/models"
  cp -r /workspace/models/Qwen3.5-9B /tmp/models/ && cp -r /workspace/models/Qwen3.8-27B /tmp/models/ \
    && touch /tmp/models/.qwen35-copy-ok && echo "[chain $(date -u +%H:%M:%S)] copy ok" || echo "[chain] copy failed; using /workspace/models"
fi
M=/workspace/models; [[ -f /tmp/models/.qwen35-copy-ok ]] && M=/tmp/models
if [[ -n "${WAIT_PID}" ]]; then
  echo "[chain $(date -u +%H:%M:%S)] waiting for runner ${WAIT_PID}"
  while kill -0 "${WAIT_PID}" 2>/dev/null; do sleep 60; done
fi
ray stop --force >/dev/null 2>&1 || true; sleep 20
cd $R/src/uni-agent
bash deployment/bootstrap/modal-quota-wait.sh --interval 1800 --max-hours 48 || exit 1
echo "[chain $(date -u +%H:%M:%S)] starting pipe-r4 with models from ${M}"
PIPE_ROOT=$P DATA_DIR=$R/data-r4 DATASET=stage1 STAGE1_SLICE=0 TRAIN_STEPS=6 RESUME_EXTRA_STEPS=1 \
ROLLOUT_N=8 TRAIN_BATCH_SIZE=4 CONCURRENCY=32 TRAIN_MAX_SAMPLES=40 VAL_MAX_SAMPLES=7 VAL_BEFORE_TRAIN=True TEST_FREQ=6 \
MODEL_PATH=$M/Qwen3.5-9B GPU_MEMORY_UTILIZATION=0.45 TEACHER=1 TEACHER_MODEL_PATH=$M/Qwen3.8-27B TEACHER_GPU_MEM=0.70 \
HARBOR_REWARD_MODE=pass_ratio DAPO=0 ROLLOUT_MAX_NUM_BATCHED_TOKENS=8192 ROLLOUT_ENABLE_PREFIX_CACHING=True TEACHER_MAX_NUM_BATCHED_TOKENS=4096 TEACHER_MAX_NUM_SEQS=4 \
bash examples/harbor_opd_rl/run_tb21_pipeline.sh
