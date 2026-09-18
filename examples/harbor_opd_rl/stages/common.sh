#!/usr/bin/env bash
# Shared environment for the Terminal-Bench + Harbor + VERL stage scripts.
# Every stage script sources this file, then does exactly one reproducible step
# and writes its evidence under "$PIPE_ROOT/<stage>/". Stages are independent:
# each can be run by hand with the same env vars the driver uses.
#
# Required: PIPE_ROOT   absolute run root shared by all stages
# Optional: LANE_ROOT, LANE_PY, MODEL_PATH, SERVED_MODEL_NAME, TASK_CONFIG,
#           ORACLE_CONFIG, DATA_DIR, TASK_FILTER (easy|all), MAX_INSTANCES,
#           TRAIN_STEPS, RESUME_EXTRA_STEPS, ROLLOUT_N, CONCURRENCY, TRAIN_BATCH_SIZE,
#           DAPO, WANDB_ENABLED, WANDB_PROJECT, WANDB_ENTITY
set -euo pipefail

STAGES_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${STAGES_DIR}/../../.." && pwd)"
LANE_ROOT="${LANE_ROOT:-/workspace/verl-uni-agent-harbor-opd-rl}"
LANE_PY="${LANE_PY:-${LANE_ROOT}/envs/ua-verl-py312-vllm023-ws1/bin/python}"
export PATH="$(dirname "${LANE_PY}"):${PATH}"
export PYTHONPATH="${REPO_ROOT}:${REPO_ROOT}/verl${PYTHONPATH:+:${PYTHONPATH}}"
PIPE_ROOT="${PIPE_ROOT:?absolute pipeline run root}"
MODEL_PATH="${MODEL_PATH:-/workspace/models/Qwen3-4B-1cfa9a7}"
SERVED_MODEL_NAME="${SERVED_MODEL_NAME:-hosted_vllm/$(basename "${MODEL_PATH}")}"
TASK_CONFIG="${TASK_CONFIG:-${REPO_ROOT}/examples/harbor_opd_rl/tb21_terminus2_smoke.yaml}"
ORACLE_CONFIG="${ORACLE_CONFIG:-${REPO_ROOT}/examples/harbor_opd_rl/tb21_oracle.yaml}"
DATA_DIR="${DATA_DIR:-${LANE_ROOT}/data}"
TB_DATASET_REF="${TB_DATASET_REF:-terminal-bench/terminal-bench-2-1}"
TASK_FILTER="${TASK_FILTER:-easy}"
MAX_INSTANCES="${MAX_INSTANCES:-5}"
EASY_TASKS="${EASY_TASKS:-fix-git cobol-modernization prove-plus-comm overfull-hbox}"
TRAIN_STEPS="${TRAIN_STEPS:-3}"
RESUME_EXTRA_STEPS="${RESUME_EXTRA_STEPS:-1}"
ROLLOUT_N="${ROLLOUT_N:-4}"
CONCURRENCY="${CONCURRENCY:-4}"
TRAIN_BATCH_SIZE="${TRAIN_BATCH_SIZE:-2}"
# binary = Harbor's primary verifier reward; pass_ratio = passed/total tests from the
# verifier CTRF report when the binary reward is 0 (dense signal for weak policies).
# Inherited by the Ray workers because the trainer starts a local Ray instance.
export HARBOR_REWARD_MODE="${HARBOR_REWARD_MODE:-pass_ratio}"
SUMMARY="${PIPE_ROOT}/pipeline-summary.jsonl"
mkdir -p "${PIPE_ROOT}"

log() { printf '[%s %s] %s\n' "${STAGE_NAME:-stage}" "$(date -u +%H:%M:%S)" "$*"; }
record() { # status detail-json
  printf '{"stage":"%s","status":"%s","utc":"%s","detail":%s}\n' "${STAGE_NAME}" "$1" \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${2:-null}" >> "${SUMMARY}"
}
stage_dir() { STAGE_DIR="${PIPE_ROOT}/${STAGE_NAME}"; mkdir -p "${STAGE_DIR}"; }
mark_passed() { date -u +%Y-%m-%dT%H:%M:%SZ > "${STAGE_DIR}/PASSED"; }
gpu_free() {
  local used; used=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | head -1)
  [[ "${used}" -lt 2000 ]] || { log "GPU busy (${used} MiB); refusing to start"; exit 3; }
}
# grep exits 1 when nothing matches; with pipefail + set -e that would abort the
# caller, so an empty match must still return 0.
trainer_pids() { ps -eo pid,cmd | { grep -E "^ *[0-9]+ [^ ]*python -m verl\.trainer\.main_ppo" || true; } | awk '{print $1}'; }
stop_lingering_trainer() {
  local pids; pids="$(trainer_pids)"
  if [[ -n "${pids}" ]]; then
    log "terminating lingering trainer: ${pids}"
    echo "${pids}" | xargs -r kill -TERM; sleep 8
    trainer_pids | xargs -r kill -KILL; sleep 3
  fi
  ray stop --force >/dev/null 2>&1 || true; sleep 3
}
train_parquet() { cat "${PIPE_ROOT}/data/train-parquet.txt"; }
full_parquet() { cat "${PIPE_ROOT}/data/full-parquet.txt"; }
metrics_json() { # step-metrics.txt -> JSON list of key metrics per step
  "${LANE_PY}" - "$1" <<'PY'
import sys,json,re
keys=("training/global_step","critic/score/mean","critic/score/max","critic/score/min","actor/grad_norm","actor/pg_loss","response_length/mean","timing_s/gen","timing_s/update_actor")
out=[]
for line in open(sys.argv[1]):
    m=dict(re.findall(r"([\w/\-]+):(-?[0-9.]+(?:e-?\d+)?)",line))
    if "training/global_step" not in m: continue  # non-metric console line
    out.append({k:float(m[k]) for k in keys if k in m})
print(json.dumps(out))
PY
}
