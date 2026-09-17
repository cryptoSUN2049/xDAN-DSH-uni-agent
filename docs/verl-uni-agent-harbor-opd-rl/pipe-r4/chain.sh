#!/usr/bin/env bash
# pipe-r4 chain (2-GPU pod): stage Qwen3.5-9B + Qwen3.8-27B on local NVMe while
# pipe-r3 finishes, then run the full pipeline with the 27B Teacher (route 2).
# Terminal-Lego only: swe-rebench-v2-fv oracle trials write no reward file in
# Modal (pipe-r5 oracle, 2026-09-17 11:13), so that source is gated out for now.
R=/workspace/verl-uni-agent-harbor-opd-rl; P=$R/runs/pipe-r4; WAIT_PID="${1:-}"
mkdir -p /tmp/models
if [[ ! -f /tmp/models/.qwen35-copy-ok ]]; then
  echo "[chain $(date -u +%H:%M:%S)] copying 9B + 27B to /tmp/models"
  cp -r /workspace/models/Qwen3.5-9B /tmp/models/ && cp -r /workspace/models/Qwen3.8-27B /tmp/models/ \
    && touch /tmp/models/.qwen35-copy-ok && echo "[chain $(date -u +%H:%M:%S)] copy ok" || echo "[chain] copy failed; using /workspace/models"
fi
M=/workspace/models; [[ -f /tmp/models/.qwen35-copy-ok ]] && M=/tmp/models
if [[ -n "${WAIT_PID}" ]]; then
  echo "[chain $(date -u +%H:%M:%S)] waiting for pipe-r3 runner ${WAIT_PID}"
  while kill -0 "${WAIT_PID}" 2>/dev/null; do sleep 60; done
fi
ray stop --force >/dev/null 2>&1 || true; sleep 20
echo "[chain $(date -u +%H:%M:%S)] starting pipe-r4 with models from ${M}"
cd $R/src/uni-agent
PIPE_ROOT=$P DATA_DIR=$R/data-r4 DATASET=stage1 STAGE1_SLICE=0 STAGE1_SOURCES=terminal-lego-15k TRAIN_STEPS=6 RESUME_EXTRA_STEPS=1 \
ROLLOUT_N=8 CONCURRENCY=16 TRAIN_MAX_SAMPLES=20 VAL_MAX_SAMPLES=5 VAL_BEFORE_TRAIN=True TEST_FREQ=6 \
MODEL_PATH=$M/Qwen3.5-9B GPU_MEMORY_UTILIZATION=0.45 TEACHER=1 TEACHER_MODEL_PATH=$M/Qwen3.8-27B TEACHER_GPU_MEM=0.85 \
HARBOR_REWARD_MODE=pass_ratio DAPO=0 bash examples/harbor_opd_rl/run_tb21_pipeline.sh
