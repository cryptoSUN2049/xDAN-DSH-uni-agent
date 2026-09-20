#!/usr/bin/env bash
# Evaluate a policy on a Harbor task parquet through the training stack's validation
# pass (trainer.val_only=True), so the evaluated policy is exactly what training ran:
# base weights + LoRA applied at inference by vLLM. Do not merge LoRA into bf16 weights
# for eval: after 20 steps the update is ~1e-4 of |W|, below bf16 resolution, and a
# merged copy is mostly the base (pipe-r11, 2026-09-18).
#
#   EVAL_ROOT=/workspace/.../runs/eval-v1-base  CUDA_VISIBLE_DEVICES=0 \
#     bash examples/harbor_opd_rl/eval_val_only.sh
#   EVAL_ROOT=/workspace/.../runs/eval-v1-pipe-r11  CUDA_VISIBLE_DEVICES=1 EVAL_RUN=<run dir> \
#     RESUME_FROM=<run>/train/pinned/global_step_20 bash examples/harbor_opd_rl/eval_val_only.sh
#
# Without RESUME_FROM the LoRA is freshly initialised (B = 0), i.e. the base model on
# the identical code path, which makes base and trained runs a clean pair.
# Sampling matches training rollouts (temperature 1.0, top_p 1.0) so EVAL_N samples
# per task differ; VERL's validation default is greedy.
# MIN_VALID_SESSIONS=0: a task that lost a sample to a sandbox fault keeps its other
# samples (no weight update happens here, so the short-group padding path never runs).
# Writes ${EVAL_ROOT}/summary.json ({per_task: {task: [0/1 ...]}}) for eval_pair_report.py.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
LANE_ROOT="${LANE_ROOT:-/workspace/verl-uni-agent-harbor-opd-rl}"
LANE_PY="${LANE_PY:-${LANE_ROOT}/envs/ua-verl-py312-vllm023-ws1/bin/python}"
export PATH="$(dirname "${LANE_PY}"):${PATH}"
EVAL_ROOT="${EVAL_ROOT:?new absolute output dir}"
MODEL_PATH="${MODEL_PATH:-/workspace/models/Qwen3.5-9B}"
EVAL_DATA="${EVAL_DATA:-${LANE_ROOT}/data-eval-set-v1/eval/harbor_tasks-eval.parquet}"
# The resumed checkpoint restores its dataloader, so the train-side knobs must match
# the run that wrote it; nothing is trained. EVAL_RUN=<run dir> reads them from that
# run's frozen train/stage-env.sh and data/train-parquet.txt (defaults: pipe-r11).
# Only the knobs that shape the checkpoint are taken (in a subshell), never the run's
# TASK_CONFIG or validation settings: eval keeps its own task-declared limits.
EVAL_RUN="${EVAL_RUN:-}"
RUN_STEPS=20 RUN_MAX_SAMPLES=100 RUN_BATCH=4 RUN_ROLLOUT_N=8 RUN_LR=1e-5 RUN_LORA_RANK=32
if [[ -n "${EVAL_RUN}" ]]; then
  IFS='|' read -r RUN_STEPS RUN_MAX_SAMPLES RUN_BATCH RUN_ROLLOUT_N RUN_LR RUN_LORA_RANK < <(
    set +u; source "${EVAL_RUN}/train/stage-env.sh"
    echo "${TRAIN_STEPS:-20}|${TRAIN_MAX_SAMPLES:-100}|${TRAIN_BATCH_SIZE:-4}|${ROLLOUT_N:-8}|${LR:-1e-5}|${LORA_RANK:-32}")
  TRAIN_DATA="${TRAIN_DATA:-$(cat "${EVAL_RUN}/data/train-parquet.txt")}"
fi
TRAIN_DATA="${TRAIN_DATA:-${LANE_ROOT}/data-pipe-r11/stage1/train/harbor_tasks-train.parquet}"
TASK_CONFIG="${TASK_CONFIG:-${REPO_ROOT}/examples/harbor_opd_rl/eval_taskdeclared.yaml}"
RESUME_FROM="${RESUME_FROM:-}"
EVAL_N="${EVAL_N:-4}"
EVAL_LIMIT="${EVAL_LIMIT:-0}"
CONCURRENCY="${CONCURRENCY:-16}"
[[ -e "${EVAL_ROOT}" ]] && { echo "EVAL_ROOT exists; use a new dir to keep evidence" >&2; exit 2; }
for f in "${EVAL_DATA}" "${TRAIN_DATA}" "${TASK_CONFIG}" "${MODEL_PATH}/config.json"; do
  [[ -f "${f}" ]] || { echo "missing ${f}" >&2; exit 2; }
done
[[ -z "${RESUME_FROM}" || -d "${RESUME_FROM}/actor" ]] || { echo "RESUME_FROM has no actor/: ${RESUME_FROM}" >&2; exit 2; }
GPU_ID="${CUDA_VISIBLE_DEVICES:?pin one GPU per eval}"; GPU_ID="${GPU_ID%%,*}"
used=$(nvidia-smi -i "${GPU_ID}" --query-gpu=memory.used --format=csv,noheader,nounits)
[[ "${used}" -lt 2000 ]] || { echo "GPU ${GPU_ID} busy (${used} MiB)" >&2; exit 3; }
mkdir -p "${EVAL_ROOT}"
ROWS=$("${LANE_PY}" -c "import pandas as pd,sys; print(len(pd.read_parquet(sys.argv[1])))" "${EVAL_DATA}")
VAL_MAX=$([[ "${EVAL_LIMIT}" -gt 0 ]] && echo "${EVAL_LIMIT}" || echo "${ROWS}")
# Own local Ray per eval (short temp dir: Unix socket paths are capped at 107 bytes).
export RAY_ADDRESS=local
export RAY_TMPDIR="/tmp/ray-val-$(basename "${EVAL_ROOT}" | cut -c1-24)"
mkdir -p "${RAY_TMPDIR}"
export HARBOR_REWARD_MODE=binary
printf '{"model_path":"%s","resume_from":"%s","data":"%s","tasks":%s,"n":%s,"task_config":"%s","gpu":"%s","started_utc":"%s"}\n' \
  "${MODEL_PATH}" "${RESUME_FROM}" "${EVAL_DATA}" "${VAL_MAX}" "${EVAL_N}" "${TASK_CONFIG}" "${GPU_ID}" \
  "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "${EVAL_ROOT}/eval-config.json"

trainer_exit=0
(cd "${REPO_ROOT}" && env MODEL_PATH="${MODEL_PATH}" MODEL_ID="hosted_vllm/$(basename "${MODEL_PATH}")" \
   TRAIN_FILE="${TRAIN_DATA}" TEST_FILE="${EVAL_DATA}" TASK_CONFIG="${TASK_CONFIG}" RUN_ROOT="${EVAL_ROOT}" \
   PYTHON_BIN="${LANE_PY}" EXP_NAME="eval-$(basename "${EVAL_ROOT}")" TOTAL_TRAINING_STEPS="${RUN_STEPS}" \
   TRAIN_MAX_SAMPLES="${RUN_MAX_SAMPLES}" VAL_MAX_SAMPLES="${VAL_MAX}" TRAIN_BATCH_SIZE="${RUN_BATCH}" \
   PPO_MINI_BATCH_SIZE="${RUN_BATCH}" ROLLOUT_N="${RUN_ROLLOUT_N}" LR="${RUN_LR}" LORA_RANK="${RUN_LORA_RANK}" \
   CONCURRENCY="${CONCURRENCY}" ROLLOUT_MAX_NUM_SEQS="${CONCURRENCY}" SAVE_FREQ=-1 DAPO=0 TEACHER=0 \
   VAL_ROLLOUT_N="${EVAL_N}" VAL_TEMPERATURE=1.0 VAL_BEFORE_TRAIN=True TEST_FREQ=-1 WANDB_ENABLED=0 MIN_VALID_SESSIONS=0 \
   GPU_MEMORY_UTILIZATION="${GPU_MEMORY_UTILIZATION:-0.6}" \
   RESUME_MODE="$([[ -n "${RESUME_FROM}" ]] && echo resume_path || echo disable)" RESUME_FROM_PATH="${RESUME_FROM}" \
   bash examples/harbor_opd_rl/train_tb21_lora_smoke.sh trainer.val_only=True) > "${EVAL_ROOT}/eval.log" 2>&1 || trainer_exit=$?

check_exit=0
"${LANE_PY}" "${SCRIPT_DIR}/eval_result_check.py" \
  --root "${EVAL_ROOT}" --data "${EVAL_DATA}" --n "${EVAL_N}" --limit "${EVAL_LIMIT}" \
  --process-exit "${trainer_exit}" --resume-from "${RESUME_FROM}" || check_exit=$?
if [[ "${trainer_exit}" -ne 0 ]]; then
  echo "eval failed: trainer exit ${trainer_exit}; evidence in ${EVAL_ROOT}" >&2
  exit "${trainer_exit}"
fi
if [[ "${check_exit}" -ne 0 ]]; then
  echo "eval incomplete or invalid: evidence in ${EVAL_ROOT}" >&2
  exit "${check_exit}"
fi
echo "eval complete: ${EVAL_ROOT}/summary.json"
