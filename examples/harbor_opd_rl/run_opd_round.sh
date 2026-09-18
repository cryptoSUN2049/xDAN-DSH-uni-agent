#!/usr/bin/env bash
# One entry point for a training round of the Harbor + VERL line, replacing the
# per-run chain scripts. It stages models on local NVMe, waits for Modal quota,
# optionally waits for another run to finish, then runs the full pipeline
# (env -> data -> oracle -> rollout -> train -> delta -> resume -> summary ->
# acceptance) with the settings validated by pipe-r4 on 2026-09-17.
#
#   ROUND=pipe-r8 bash examples/harbor_opd_rl/run_opd_round.sh --smoke
#   ROUND=pipe-r8 TEACHER=1 TRAIN_STEPS=20 bash examples/harbor_opd_rl/run_opd_round.sh
#   ROUND=pipe-r9 TEACHER=0 WAIT_PID=12345 bash examples/harbor_opd_rl/run_opd_round.sh
#
# --smoke (<= 10 min, no GPU) checks env, task selection, one oracle sandbox and the
# fully resolved training config: run it before every round.
# --smoke-gpu (~30 min) loads the models once and runs one tiny step: run it after
# changing the model, the engine settings or the Teacher. pipe-r4 burned five failed
# 6-step attempts (~500 sandboxes) on a Teacher OOM that one GPU smoke would catch.
#
# Launch it detached so a laptop going offline cannot kill it:
#   bash examples/harbor_opd_rl/launch-detached.sh <run>/driver.log \
#     "ROUND=<run> TEACHER=1 bash examples/harbor_opd_rl/run_opd_round.sh"
set -euo pipefail
SMOKE=0
for arg in "$@"; do case "${arg}" in --smoke) SMOKE=1;; --smoke-gpu) SMOKE=2;; *) echo "unknown argument: ${arg}" >&2; exit 2;; esac; done

LANE_ROOT="${LANE_ROOT:-/workspace/verl-uni-agent-harbor-opd-rl}"
REPO_ROOT="${REPO_ROOT:-${LANE_ROOT}/src/uni-agent}"
ROUND="${ROUND:?ROUND (run name, e.g. pipe-r8) is required}"
PIPE_ROOT="${PIPE_ROOT:-${LANE_ROOT}/runs/${ROUND}}"
DATA_DIR="${DATA_DIR:-${LANE_ROOT}/data-${ROUND}}"   # one data dir per run: the two pods share /workspace
export PATH="${LANE_ROOT}/envs/ua-verl-py312-vllm023-ws1/bin:${PATH}"

# Models: Qwen3.5-9B Student, Qwen3.8-27B Teacher (a 4B student cannot distil from
# the 27B Teacher: vocab 151936 vs 248320). Local NVMe copies load much faster.
STUDENT_MODEL="${STUDENT_MODEL:-Qwen3.5-9B}"
TEACHER_MODEL="${TEACHER_MODEL:-Qwen3.8-27B}"
TEACHER="${TEACHER:-1}"
MODEL_STORE="${MODEL_STORE:-/workspace/models}"
STAGE_MODELS="${STAGE_MODELS:-1}"

# Engine settings (pipe-r4, 2026-09-17). The Teacher needs headroom beyond its
# weights + KV for the prompt-logprob buffer (batched tokens x 248k vocab x 4 B);
# 0.85 with 8192 tokens OOMed three times, 0.70 with 4096 is stable.
GPU_MEMORY_UTILIZATION="${GPU_MEMORY_UTILIZATION:-0.45}"
ROLLOUT_MAX_NUM_BATCHED_TOKENS="${ROLLOUT_MAX_NUM_BATCHED_TOKENS:-8192}"
ROLLOUT_ENABLE_PREFIX_CACHING="${ROLLOUT_ENABLE_PREFIX_CACHING:-True}"
TEACHER_GPU_MEM="${TEACHER_GPU_MEM:-0.70}"
TEACHER_MAX_NUM_BATCHED_TOKENS="${TEACHER_MAX_NUM_BATCHED_TOKENS:-4096}"
TEACHER_MAX_NUM_SEQS="${TEACHER_MAX_NUM_SEQS:-4}"

# Sandboxes: 16 concurrent is the share agreed with the Tinker line, which uses the
# same Modal workspace (64 combined exhausted the workspace spend limit overnight).
CONCURRENCY="${CONCURRENCY:-16}"
TRAIN_BATCH_SIZE="${TRAIN_BATCH_SIZE:-4}"
ROLLOUT_N="${ROLLOUT_N:-8}"
TRAIN_STEPS="${TRAIN_STEPS:-20}"
RESUME_EXTRA_STEPS="${RESUME_EXTRA_STEPS:-1}"
TEST_FREQ="${TEST_FREQ:-10}"

# Data: a published slice by default; with the full index instead, audit-passed
# tasks only, shared eval sets excluded, medium/hard (pipe-r4 showed an unfiltered
# index slice leaves 9B at 0.92 with no within-group spread for GRPO).
# Default source: the data line's slice stage1-swe50e-tl50m-v1 (audited, eval-set excluded,
# decontaminated against Terminal-Bench 2.0/2.1 and 21 other benchmarks). Set
# STAGE1_SLICE_NAME= (empty) with STAGE1_REPO=...-Full to fall back to the index.
STAGE1_REPO="${STAGE1_REPO:-gump2049/xDAN-Harbor-Stage1-Tasks}"
STAGE1_SLICE_NAME="${STAGE1_SLICE_NAME-stage1-swe50e-tl50m-v1}"
STAGE1_TRAIN_PER_SOURCE="${STAGE1_TRAIN_PER_SOURCE:-50}"
STAGE1_VAL_PER_SOURCE="${STAGE1_VAL_PER_SOURCE:-4}"
# Slices are already chosen by difficulty by the data line: base 9B passes SWE easy
# 33% but SWE medium only 7% (about 90% of groups all-wrong, no GRPO signal), while
# Terminal-Lego medium passes 52%. Their 8 shared validation tasks must stay intact
# so every slice's validation is comparable, so no extra filter on a slice.
if [[ -n "${STAGE1_SLICE_NAME}" ]]; then STAGE1_DIFFICULTY="${STAGE1_DIFFICULTY-}"
else STAGE1_DIFFICULTY="${STAGE1_DIFFICULTY-medium hard}"; fi
HARBOR_REWARD_MODE="${HARBOR_REWARD_MODE:-pass_ratio}"
DAPO="${DAPO:-0}"

VAL_BEFORE_TRAIN="${VAL_BEFORE_TRAIN:-True}"
SKIP_STAGES="${SKIP_STAGES:-}"
ORACLE_LIMIT="${ORACLE_LIMIT:-2}"
CONFIG_DRY_RUN="${CONFIG_DRY_RUN:-0}"
if [[ ${SMOKE} -eq 1 ]]; then
  # Fast smoke, target <= 10 min, no GPU: env, task selection, one oracle sandbox
  # with this round's sandbox settings, and a full resolve of the training config.
  TRAIN_STEPS=1; STAGE1_TRAIN_PER_SOURCE=1; STAGE1_VAL_PER_SOURCE=1; ORACLE_LIMIT=1
  TRAIN_BATCH_SIZE=2; ROLLOUT_N=2; CONCURRENCY=4
  CONFIG_DRY_RUN=1; STAGE_MODELS=0; SKIP_STAGES="rollout delta resume summary acceptance cost"
elif [[ ${SMOKE} -eq 2 ]]; then
  # GPU smoke, ~30 min: one model load and one tiny step to prove memory settings.
  # Only needed after changing the model, the engine settings or the Teacher.
  TRAIN_STEPS=1; STAGE1_TRAIN_PER_SOURCE=1; STAGE1_VAL_PER_SOURCE=1
  TRAIN_BATCH_SIZE=2; ROLLOUT_N=2; CONCURRENCY=4; VAL_BEFORE_TRAIN=False; TEST_FREQ=-1
  SKIP_STAGES="rollout delta resume summary acceptance"
fi
TRAIN_MAX_SAMPLES="${TRAIN_MAX_SAMPLES:-$(( STAGE1_TRAIN_PER_SOURCE * 2 ))}"
VAL_MAX_SAMPLES="${VAL_MAX_SAMPLES:-$(( STAGE1_VAL_PER_SOURCE * 2 ))}"

mkdir -p "${PIPE_ROOT}"
log() { printf '[round %s] %s\n' "$(date -u +%H:%M:%S)" "$*"; }

if [[ "${STAGE_MODELS}" == "1" ]]; then
  mkdir -p /tmp/models
  for model in "${STUDENT_MODEL}" $([[ "${TEACHER}" == "1" ]] && echo "${TEACHER_MODEL}"); do
    if [[ ! -f "/tmp/models/.${model}.ok" ]]; then
      log "staging ${model} on local NVMe"
      cp -r "${MODEL_STORE}/${model}" /tmp/models/ && touch "/tmp/models/.${model}.ok" || log "copy failed; using ${MODEL_STORE}"
    fi
  done
fi
MODEL_DIR="${MODEL_STORE}"
[[ -f "/tmp/models/.${STUDENT_MODEL}.ok" ]] && MODEL_DIR=/tmp/models

if [[ -n "${WAIT_PID:-}" ]]; then
  log "waiting for run ${WAIT_PID} to finish"
  while kill -0 "${WAIT_PID}" 2>/dev/null; do sleep 60; done
fi
# Only clear Ray when no trainer is alive: an unconditional stop killed the running
# pipe-r8-smoke resume stage on 2026-09-18 when a fast smoke was started beside it.
if ps -eo args= | grep -qE "^[^ ]*python[0-9.]* -m verl\.trainer\.main_ppo"; then
  if [[ ${SMOKE} -eq 1 ]]; then log "a trainer is running; fast smoke leaves Ray alone"
  else log "a trainer is already running on this pod; refusing to start ${ROUND}"; exit 3; fi
else
  ray stop --force >/dev/null 2>&1 || true; sleep 10
fi
# Collect sandboxes leaked by an earlier killed run before paying for a new one.
# Opt-in until the age filter is fixed: modal 1.5.5's Sandbox.list() has no created_at,
# so the current script treats unknown age as old and would terminate live trials.
if [[ "${CLEANUP_BEFORE_ROUND:-0}" == "1" ]]; then
  HARBOR_MODAL_APP="${HARBOR_MODAL_APP:-verl-harbor}"     bash deployment/bootstrap/modal-sandbox-cleanup.sh --apply --older-than "${CLEANUP_OLDER_THAN:-60}" 2>&1 | tail -2 || true
fi

cd "${REPO_ROOT}"
bash deployment/bootstrap/modal-quota-wait.sh --interval "${QUOTA_INTERVAL:-1800}" --max-hours "${QUOTA_MAX_HOURS:-48}" || exit 1
log "starting ${ROUND}: student=${STUDENT_MODEL} teacher=${TEACHER} steps=${TRAIN_STEPS} tasks=${TRAIN_MAX_SAMPLES} slice=${STAGE1_SLICE_NAME:-none} concurrency=${CONCURRENCY} smoke=${SMOKE}"

env PIPE_ROOT="${PIPE_ROOT}" DATA_DIR="${DATA_DIR}" DATASET=stage1 STAGE1_SLICE=0 \
  STAGE1_REPO="${STAGE1_REPO}" STAGE1_SLICE_NAME="${STAGE1_SLICE_NAME}" STAGE1_TRAIN_PER_SOURCE="${STAGE1_TRAIN_PER_SOURCE}" \
  STAGE1_VAL_PER_SOURCE="${STAGE1_VAL_PER_SOURCE}" STAGE1_DIFFICULTY="${STAGE1_DIFFICULTY}" \
  TRAIN_STEPS="${TRAIN_STEPS}" RESUME_EXTRA_STEPS="${RESUME_EXTRA_STEPS}" TEST_FREQ="${TEST_FREQ}" \
  TRAIN_MAX_SAMPLES="${TRAIN_MAX_SAMPLES}" VAL_MAX_SAMPLES="${VAL_MAX_SAMPLES}" VAL_BEFORE_TRAIN="${VAL_BEFORE_TRAIN}" \
  SKIP_STAGES="${SKIP_STAGES}" ORACLE_LIMIT="${ORACLE_LIMIT}" CONFIG_DRY_RUN="${CONFIG_DRY_RUN}" \
  TRAIN_BATCH_SIZE="${TRAIN_BATCH_SIZE}" ROLLOUT_N="${ROLLOUT_N}" CONCURRENCY="${CONCURRENCY}" \
  MODEL_PATH="${MODEL_DIR}/${STUDENT_MODEL}" GPU_MEMORY_UTILIZATION="${GPU_MEMORY_UTILIZATION}" \
  ROLLOUT_MAX_NUM_BATCHED_TOKENS="${ROLLOUT_MAX_NUM_BATCHED_TOKENS}" \
  ROLLOUT_ENABLE_PREFIX_CACHING="${ROLLOUT_ENABLE_PREFIX_CACHING}" \
  TEACHER="${TEACHER}" TEACHER_MODEL_PATH="${MODEL_DIR}/${TEACHER_MODEL}" \
  TEACHER_GPU_MEM="${TEACHER_GPU_MEM}" TEACHER_MAX_NUM_BATCHED_TOKENS="${TEACHER_MAX_NUM_BATCHED_TOKENS}" \
  TEACHER_MAX_NUM_SEQS="${TEACHER_MAX_NUM_SEQS}" HARBOR_REWARD_MODE="${HARBOR_REWARD_MODE}" DAPO="${DAPO}" \
  bash examples/harbor_opd_rl/run_tb21_pipeline.sh
