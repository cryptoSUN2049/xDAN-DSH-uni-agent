#!/usr/bin/env bash
# Stage resume: reload the last training checkpoint (model + optimizer + extra)
# in a fresh trainer process and train RESUME_EXTRA_STEPS more steps. Proves the
# native checkpoint is restorable and training continues from the absolute step.
STAGE_NAME=resume
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

CK_LAST="$(cat "${PIPE_ROOT}/train/final-checkpoint.txt")"
TOTAL=$(( TRAIN_STEPS + RESUME_EXTRA_STEPS ))
STAGE_NAME=resume EXP_NAME=pipe-resume TOTAL_STEPS="${TOTAL}" RESUME_MODE=resume_path RESUME_FROM_PATH="${CK_LAST}" \
  bash "${STAGES_DIR}/40_train.sh"
grep -qE "step:$(( TRAIN_STEPS + 1 )) - " "${PIPE_ROOT}/resume/train.log" || { echo "resume did not continue from step ${TRAIN_STEPS}" >&2; exit 1; }
