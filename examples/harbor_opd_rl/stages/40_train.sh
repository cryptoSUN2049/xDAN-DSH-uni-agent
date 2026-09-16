#!/usr/bin/env bash
# Stage train: TRAIN_STEPS steps of VERL V1 GRPO/LoRA over the Harbor task
# adapter, through train_tb21_lora_smoke.sh (same env-var override style as the
# official examples/quickstart/training scripts). Completion is judged by the
# global_step_N checkpoint plus the step metrics line, never by the exit code.
#
# Reused by 60_resume.sh with RESUME_MODE/RESUME_FROM_PATH.
STAGE_NAME="${STAGE_NAME:-train}"
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"; stage_dir; gpu_free

EXP_NAME="${EXP_NAME:-pipe-${STAGE_NAME}}"
TOTAL_STEPS="${TOTAL_STEPS:-${TRAIN_STEPS}}"
(cd "${REPO_ROOT}" && env MODEL_PATH="${MODEL_PATH}" MODEL_ID="${SERVED_MODEL_NAME}" TRAIN_FILE="$(train_parquet)" \
   TEST_FILE="$(full_parquet)" TASK_CONFIG="${TASK_CONFIG}" RUN_ROOT="${STAGE_DIR}" PYTHON_BIN="${LANE_PY}" \
   EXP_NAME="${EXP_NAME}" TOTAL_TRAINING_STEPS="${TOTAL_STEPS}" TRAIN_MAX_SAMPLES="${TRAIN_MAX_SAMPLES:-4}" \
   VAL_MAX_SAMPLES="${VAL_MAX_SAMPLES:-1}" TRAIN_BATCH_SIZE="${TRAIN_BATCH_SIZE}" PPO_MINI_BATCH_SIZE="${TRAIN_BATCH_SIZE}" \
   ROLLOUT_N="${ROLLOUT_N}" CONCURRENCY="${CONCURRENCY}" ROLLOUT_MAX_NUM_SEQS="${CONCURRENCY}" SAVE_FREQ=1 \
   RESUME_MODE="${RESUME_MODE:-disable}" RESUME_FROM_PATH="${RESUME_FROM_PATH:-}" DAPO="${DAPO:-0}" \
   bash examples/harbor_opd_rl/train_tb21_lora_smoke.sh) > "${STAGE_DIR}/train.log" 2>&1 || true

CK=$(find "${STAGE_DIR}/checkpoints" -maxdepth 4 -type d -name "global_step_${TOTAL_STEPS}" | head -1)
[[ -n "${CK}" && -f "${CK}/model_world_size_1_rank_0.pt" ]] || { log "global_step_${TOTAL_STEPS} checkpoint missing"; record failed '"checkpoint missing"'; exit 1; }
grep -qE "step:${TOTAL_STEPS} - " "${STAGE_DIR}/train.log" || { log "step ${TOTAL_STEPS} metrics missing"; record failed '"metrics missing"'; exit 1; }
stop_lingering_trainer
echo "${CK}" > "${STAGE_DIR}/final-checkpoint.txt"
grep -oE "step:[0-9]+ - .*" "${STAGE_DIR}/train.log" > "${STAGE_DIR}/step-metrics.txt"
grep -oE "wandb: .*View run at .*" "${STAGE_DIR}/train.log" | head -1 | sed 's/.*View run at //' > "${STAGE_DIR}/wandb-url.txt" || true
metrics_json "${STAGE_DIR}/step-metrics.txt" > "${STAGE_DIR}/metrics.json"
mark_passed; record passed "$(cat "${STAGE_DIR}/metrics.json")"
log "passed: checkpoint=${CK} wandb=$(cat "${STAGE_DIR}/wandb-url.txt")"
