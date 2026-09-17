#!/usr/bin/env bash
# pipe-r7 (1-GPU pod): control group for pipe-r4. Identical Qwen3.5-9B Student,
# audited stage1 mix (40 train / 7 held-out), GRPO, 4 prompts x 8 rollouts per
# step, 32 concurrent sandboxes, 6 steps + resume, 8192-token engine steps; the
# only difference is TEACHER=0 (no 27B on-policy distillation).
R=/workspace/verl-uni-agent-harbor-opd-rl; P=$R/runs/pipe-r7
mkdir -p /tmp/models
if [[ ! -f /tmp/models/.qwen35-9b-copy-ok ]]; then
  echo "[chain $(date -u +%H:%M:%S)] copying 9B to /tmp/models"
  cp -r /workspace/models/Qwen3.5-9B /tmp/models/ && touch /tmp/models/.qwen35-9b-copy-ok \
    && echo "[chain $(date -u +%H:%M:%S)] copy ok" || echo "[chain] copy failed; using /workspace/models"
fi
M=/workspace/models; [[ -f /tmp/models/.qwen35-9b-copy-ok ]] && M=/tmp/models
ray stop --force >/dev/null 2>&1 || true; sleep 10
cd $R/src/uni-agent
bash deployment/bootstrap/modal-quota-wait.sh --interval 1800 --max-hours 48 || exit 1
echo "[chain $(date -u +%H:%M:%S)] starting pipe-r7 with models from ${M}"
PIPE_ROOT=$P DATA_DIR=$R/data-r7 DATASET=stage1 STAGE1_SLICE=0 TRAIN_STEPS=6 RESUME_EXTRA_STEPS=1 \
ROLLOUT_N=8 TRAIN_BATCH_SIZE=4 CONCURRENCY=32 TRAIN_MAX_SAMPLES=40 VAL_MAX_SAMPLES=7 VAL_BEFORE_TRAIN=True TEST_FREQ=6 \
MODEL_PATH=$M/Qwen3.5-9B GPU_MEMORY_UTILIZATION=0.45 TEACHER=0 \
HARBOR_REWARD_MODE=pass_ratio DAPO=0 ROLLOUT_MAX_NUM_BATCHED_TOKENS=8192 \
bash examples/harbor_opd_rl/run_tb21_pipeline.sh
