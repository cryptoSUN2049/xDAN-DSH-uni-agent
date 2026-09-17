#!/usr/bin/env bash
# Stage train: TRAIN_STEPS steps of VERL V1 GRPO/LoRA over the Harbor task
# adapter, through train_tb21_lora_smoke.sh (same env-var override style as the
# official examples/quickstart/training scripts). Completion is judged by the
# global_step_N checkpoint plus the step metrics line, never by the exit code.
#
# Reused by 60_resume.sh with RESUME_MODE/RESUME_FROM_PATH.
STAGE_NAME="${STAGE_NAME:-train}"
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"; stage_dir

EXP_NAME="${EXP_NAME:-pipe-${STAGE_NAME}}"
TOTAL_STEPS="${TOTAL_STEPS:-${TRAIN_STEPS}}"
# VERL v1 writes global_step_N/actor/model_world_size_1_rank_0.pt (+ data.pt);
# the legacy sync layout keeps the .pt files directly under global_step_N.
model_file() { local ck="$1"; for f in "${ck}/actor/model_world_size_1_rank_0.pt" "${ck}/model_world_size_1_rank_0.pt"; do [[ -f "${f}" ]] && { echo "${f}"; return 0; }; done; return 1; }
# Must succeed with empty output when the checkpoints dir does not exist yet
# (fresh stage dir): find's non-zero exit would otherwise abort under pipefail.
find_final_ckpt() { [[ -d "${STAGE_DIR}/checkpoints" ]] || return 0; { find "${STAGE_DIR}/checkpoints" -maxdepth 4 -type d -name "global_step_${TOTAL_STEPS}" 2>/dev/null || true; } | head -1; }

# TRAIN_REUSE=1 (default): a completed run in this stage dir (final checkpoint +
# step metrics already present) is post-processed instead of retrained, so a
# failed post-check never costs another GPU hour.
if [[ "${TRAIN_REUSE:-1}" == "1" ]]; then
  CK=$(find_final_ckpt)
  if [[ -n "${CK}" ]] && model_file "${CK}" >/dev/null; then
    log "reusing completed run in ${STAGE_DIR} (global_step_${TOTAL_STEPS} present)"
    stop_lingering_trainer
    echo "${CK}" > "${STAGE_DIR}/final-checkpoint.txt"
    grep -oE "wandb: .*View run at .*" "${STAGE_DIR}/train.log" | head -1 | sed 's/.*View run at //' > "${STAGE_DIR}/wandb-url.txt" || true
    { grep -oE "step:[0-9]+ - .*" "${STAGE_DIR}/train.log" || true; } > "${STAGE_DIR}/step-metrics.txt"
    # Console step lines are Ray-actor buffered and are lost when the process is
    # killed; wandb holds the same metrics. Rebuild step-metrics.txt from wandb
    # when the final step's console line is missing.
    if ! grep -qE "step:${TOTAL_STEPS} - " "${STAGE_DIR}/step-metrics.txt" && [[ -s "${STAGE_DIR}/wandb-url.txt" ]]; then
      log "console metrics incomplete; rebuilding from wandb $(cat "${STAGE_DIR}/wandb-url.txt")"
      "${LANE_PY}" - "$(cat "${STAGE_DIR}/wandb-url.txt")" "${STAGE_DIR}/step-metrics.txt" <<'PY'
import sys, wandb
url, out = sys.argv[1], sys.argv[2]
ent, proj, _, rid = url.split("wandb.ai/")[1].split("/")[:4]
rows = [h for h in wandb.Api().run(f"{ent}/{proj}/{rid}").scan_history() if h.get("training/global_step") is not None]
with open(out, "w") as f:
    for h in rows:
        items = [f"{k}:{v}" for k, v in h.items() if not k.startswith("_") and isinstance(v, (int, float))]
        f.write(f"step:{int(h['training/global_step'])} - " + " - ".join(items) + "\n")
print("rebuilt", len(rows), "steps from wandb")
PY
    fi
    grep -qE "step:${TOTAL_STEPS} - " "${STAGE_DIR}/step-metrics.txt" || { log "step ${TOTAL_STEPS} metrics missing (console and wandb)"; record failed '"metrics missing"'; exit 1; }
    metrics_json "${STAGE_DIR}/step-metrics.txt" > "${STAGE_DIR}/metrics.json"
    mark_passed; record passed "$(cat "${STAGE_DIR}/metrics.json")"
    log "passed (reused): checkpoint=${CK} wandb=$(cat "${STAGE_DIR}/wandb-url.txt")"
    exit 0
  fi
fi
gpu_free
(cd "${REPO_ROOT}" && env MODEL_PATH="${MODEL_PATH}" MODEL_ID="${SERVED_MODEL_NAME}" TRAIN_FILE="$(train_parquet)" \
   TEST_FILE="$(full_parquet)" TASK_CONFIG="${TASK_CONFIG}" RUN_ROOT="${STAGE_DIR}" PYTHON_BIN="${LANE_PY}" \
   EXP_NAME="${EXP_NAME}" TOTAL_TRAINING_STEPS="${TOTAL_STEPS}" TRAIN_MAX_SAMPLES="${TRAIN_MAX_SAMPLES:-4}" \
   VAL_MAX_SAMPLES="${VAL_MAX_SAMPLES:-1}" TRAIN_BATCH_SIZE="${TRAIN_BATCH_SIZE}" PPO_MINI_BATCH_SIZE="${TRAIN_BATCH_SIZE}" \
   ROLLOUT_N="${ROLLOUT_N}" CONCURRENCY="${CONCURRENCY}" ROLLOUT_MAX_NUM_SEQS="${CONCURRENCY}" SAVE_FREQ=1 \
   RESUME_MODE="${RESUME_MODE:-disable}" RESUME_FROM_PATH="${RESUME_FROM_PATH:-}" DAPO="${DAPO:-0}" \
   bash examples/harbor_opd_rl/train_tb21_lora_smoke.sh) > "${STAGE_DIR}/train.log" 2>&1 || true

CK=$(find_final_ckpt)
[[ -n "${CK}" ]] && model_file "${CK}" >/dev/null || { log "global_step_${TOTAL_STEPS} checkpoint missing"; record failed '"checkpoint missing"'; exit 1; }
grep -qE "step:${TOTAL_STEPS} - " "${STAGE_DIR}/train.log" || { log "step ${TOTAL_STEPS} metrics missing"; record failed '"metrics missing"'; exit 1; }
stop_lingering_trainer
echo "${CK}" > "${STAGE_DIR}/final-checkpoint.txt"
grep -oE "step:[0-9]+ - .*" "${STAGE_DIR}/train.log" > "${STAGE_DIR}/step-metrics.txt"
grep -oE "wandb: .*View run at .*" "${STAGE_DIR}/train.log" | head -1 | sed 's/.*View run at //' > "${STAGE_DIR}/wandb-url.txt" || true
metrics_json "${STAGE_DIR}/step-metrics.txt" > "${STAGE_DIR}/metrics.json"
mark_passed; record passed "$(cat "${STAGE_DIR}/metrics.json")"
log "passed: checkpoint=${CK} wandb=$(cat "${STAGE_DIR}/wandb-url.txt")"
