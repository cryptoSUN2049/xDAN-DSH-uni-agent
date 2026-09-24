#!/usr/bin/env bash
# Sequential OPD then RL (docs/performance-9b/opd-then-rl-design.md §2), instead
# of S1's joint loss L = L_GRPO + 1.0*L_OPD at every step. Two run_opd_round.sh rounds:
#   phase A  runs/<NAME>-opd  TEACHER=1 DISTILL_USE_TASK_REWARDS=False, OPD_STEPS steps: pure
#            OPD (VERL zeroes the policy loss and fixes the distillation coefficient at 1.0).
#   phase B  runs/<NAME>-rl   TEACHER=0 GRPO from A's final checkpoint up to OPD_STEPS+RL_STEPS,
#            on A's train parquet. VERL restores the dataloader from global_step_N/data.pt, so B
#            continues with the tasks after the ones A trained on (same order as one 60-step run).
#
# Launch detached (S1's launch command, 训练方案.md §12, with the phase lengths):
#   bash examples/harbor_opd_rl/launch-detached.sh /workspace/verl-uni-agent-harbor-opd-rl/runs/pipe-s2-driver.log \
#     "NAME=pipe-s2 OPD_STEPS=12 RL_STEPS=48 TRAIN_BATCH_SIZE=8 ROLLOUT_N=4 \
#      LR=1e-4 LR_WARMUP_STEPS=3 VAL_ROLLOUT_N=4 VAL_TEMPERATURE=1.0 TEST_FREQ=20 PIN_CKPT_EVERY=20 \
#      STAGE1_SLICE_NAME=stage1-ladderA-v1 STAGE1_TRAIN_PER_SOURCE=0 STAGE1_ORDER=stratified \
#      TRAIN_MAX_SAMPLES=500 VAL_MAX_SAMPLES=8 HARBOR_REWARD_MODE=binary \
#      bash examples/harbor_opd_rl/run_opd_then_rl.sh"
# Every other knob is inherited unchanged by both phases, so both train on the same data stream
# and schedule: never give the phases different TRAIN_MAX_SAMPLES or TRAIN_BATCH_SIZE, or data.pt
# no longer points at the next task. Smoke first as before every round, under its own run name
# (a smoke's config-dry-run train/PASSED in runs/<NAME>-opd would make phase A skip training):
#   ROUND=<NAME>-smoke TEACHER=1 <same knobs> bash examples/harbor_opd_rl/run_opd_round.sh --smoke
#
# Knobs:
#   NAME, OPD_STEPS, RL_STEPS  required; no defaults, a wrong phase length costs a whole run
#   CKPT_LOAD_CONTENTS  what B restores from A's checkpoint. Default model: B is a fresh GRPO run
#                       (new Adam moments, LR_WARMUP_STEPS warmup again) that only starts from A's
#                       weights, so it differs from an RL-only run from the base in the init alone.
#                       A's Adam moments were accumulated under the OPD loss, and keeping A's lr
#                       scheduler without them (model,extra) would start fresh Adam, whose first
#                       normalised steps are its largest, at full LR with no warmup.
#   PHASE               all (default) | a | b (B only, after A finished; refuses unless A passed)
#   A_SKIP_STAGES, B_SKIP_STAGES, B_VAL_BEFORE_TRAIN   see below
#
# Relaunching after a failure is safe: finished stages are skipped, A continues from its newest
# checkpoint (RESUME_MODE=auto), and B continues from its own newest checkpoint with everything
# restored once it has one, otherwise it starts again from A's final checkpoint.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NAME="${NAME:?NAME (run pair name, e.g. pipe-s2) is required}"
OPD_STEPS="${OPD_STEPS:?OPD_STEPS (phase A steps) is required}"
RL_STEPS="${RL_STEPS:?RL_STEPS (phase B steps) is required}"
[[ "${OPD_STEPS}" =~ ^[1-9][0-9]*$ && "${RL_STEPS}" =~ ^[1-9][0-9]*$ ]] || { echo "OPD_STEPS and RL_STEPS must be positive integers" >&2; exit 2; }
PHASE="${PHASE:-all}"
[[ "${PHASE}" =~ ^(all|a|b)$ ]] || { echo "PHASE must be all, a or b" >&2; exit 2; }
B_LOAD_CONTENTS="${CKPT_LOAD_CONTENTS:-model}"
LANE_ROOT="${LANE_ROOT:-/workspace/verl-uni-agent-harbor-opd-rl}"
A_ROOT="${LANE_ROOT}/runs/${NAME}-opd"
B_ROOT="${LANE_ROOT}/runs/${NAME}-rl"
DATA_DIR="${DATA_DIR:-${LANE_ROOT}/data-${NAME}-opd}"   # A downloads the tasks; B trains on the same copy
ROUND_SCRIPT="${ROUND_SCRIPT:-${SCRIPT_DIR}/run_opd_round.sh}"   # tests substitute a stub
# Stages after train that each phase skips:
#   resume      A: would train one more OPD step that B never uses; B's train stage itself resumes
#               from A's checkpoint in a fresh process. B: 60_resume.sh re-sources B's stage-env.sh
#               with CKPT_LOAD_CONTENTS=model, so it would not test the optimizer restore
#               and would only cost one more RL step and a model load.
#   acceptance  its hard checks need the resume stage (and, for B, the env/data/oracle/rollout
#               records that live in A's pipeline-summary.jsonl), so it would fail and stop the
#               driver before cost. A is judged by a quick check of its final checkpoint, B by the
#               full 78x4 evaluation paired against RL only.
# Kept: delta (CPU; adapter changed, base unchanged), summary (verdict + checkpoint retention,
# newest 10 kept) and cost (each phase's sandbox bill: A's Teacher phase costs differ from B's).
A_SKIP_STAGES="${A_SKIP_STAGES-resume acceptance}"
B_SKIP_STAGES="${B_SKIP_STAGES-resume acceptance}"
# A's last step already ran validation (TEST_FREQ > 0 always validates the last step); repeating
# it on the same weights at B's start would only cost VAL_MAX_SAMPLES x VAL_ROLLOUT_N trials.
B_VAL_BEFORE_TRAIN="${B_VAL_BEFORE_TRAIN:-False}"

log() { printf '[opd-then-rl %s] %s\n' "$(date -u +%H:%M:%S)" "$*"; }

if [[ "${PHASE}" != b ]]; then
  log "phase A: ${OPD_STEPS} pure-OPD steps in ${A_ROOT}"
  # CKPT_LOAD_CONTENTS is cleared so a relaunch of A restores its own optimizer state.
  rc=0
  env ROUND="${NAME}-opd" PIPE_ROOT="${A_ROOT}" DATA_DIR="${DATA_DIR}" TEACHER=1 DISTILL_USE_TASK_REWARDS=False \
    TRAIN_STEPS="${OPD_STEPS}" SKIP_STAGES="${A_SKIP_STAGES}" FROM_STAGE= RESUME_MODE=auto RESUME_FROM_PATH= \
    CKPT_LOAD_CONTENTS= bash "${ROUND_SCRIPT}" || rc=$?
  # B only needs A's trained checkpoint; a later stage failing (e.g. cost) does not invalidate it.
  [[ ${rc} -eq 0 ]] || log "phase A exited ${rc}; phase B still runs if A's train stage passed"
  [[ "${PHASE}" == a ]] && exit "${rc}"
fi

# Phase B gate: A's train stage passed and its final checkpoint is the step B continues from.
if [[ ! -f "${A_ROOT}/train/PASSED" || ! -s "${A_ROOT}/train/final-checkpoint.txt" ]]; then
  log "phase A has not passed (${A_ROOT}/train/PASSED or final-checkpoint.txt missing); refusing phase B"; exit 1
fi
A_CKPT="$(cat "${A_ROOT}/train/final-checkpoint.txt")"
if [[ "${A_CKPT}" != */global_step_"${OPD_STEPS}" || ! -d "${A_CKPT}" ]]; then
  log "phase A's final checkpoint ${A_CKPT} is not an existing global_step_${OPD_STEPS}; refusing phase B"; exit 1
fi
for f in train-parquet.txt full-parquet.txt; do
  [[ -s "${A_ROOT}/data/${f}" ]] || { log "phase A has no data/${f}; refusing phase B"; exit 1; }
done
# B skips the stages before train (FROM_STAGE=train); the train stage reads only the parquet paths
# from data/. The whole data stage dir is copied so B's run root shows which tasks it trained on.
mkdir -p "${B_ROOT}/data"
cp -a "${A_ROOT}/data/." "${B_ROOT}/data/"
if [[ -d "${B_ROOT}/train/checkpoints" ]] && [[ -n "$(find "${B_ROOT}/train/checkpoints" -name latest_checkpointed_iteration.txt 2>/dev/null | head -1)" ]]; then
  # A relaunch after B stopped: continue B from its own newest checkpoint with its optimizer.
  B_RESUME=(RESUME_MODE=auto RESUME_FROM_PATH= CKPT_LOAD_CONTENTS=)
  resume_note="own newest checkpoint (all contents)"
else
  B_RESUME=(RESUME_MODE=resume_path RESUME_FROM_PATH="${A_CKPT}" CKPT_LOAD_CONTENTS="${B_LOAD_CONTENTS}")
  resume_note="${A_CKPT} (${B_LOAD_CONTENTS})"
fi
printf '%s phase B resumes from %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${resume_note}" >> "${B_ROOT}/handover.log"
# In the default async trainer mode A's checkpoint also holds the TransferQueue state: B's first
# step may train on trajectories that finished under A's weights, one step stale like every async
# step. They carry Teacher fields that B's trainer never selects.
log "phase B: ${RL_STEPS} RL steps in ${B_ROOT} (steps $((OPD_STEPS + 1))-$((OPD_STEPS + RL_STEPS))), from ${resume_note}"
env ROUND="${NAME}-rl" PIPE_ROOT="${B_ROOT}" DATA_DIR="${DATA_DIR}" TEACHER=0 FROM_STAGE=train \
  TRAIN_STEPS="$((OPD_STEPS + RL_STEPS))" SKIP_STAGES="${B_SKIP_STAGES}" VAL_BEFORE_TRAIN="${B_VAL_BEFORE_TRAIN}" \
  "${B_RESUME[@]}" bash "${ROUND_SCRIPT}"
log "done: A ${A_CKPT}; B $(cat "${B_ROOT}/train/final-checkpoint.txt" 2>/dev/null || echo 'final checkpoint missing')"
