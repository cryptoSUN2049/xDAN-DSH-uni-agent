#!/usr/bin/env bash
# Evaluate a policy on a Harbor task parquet through the training stack's validation
# pass (trainer.val_only=True), so the evaluated policy is exactly what training ran:
# base weights + LoRA applied at inference by vLLM. Do not merge LoRA into bf16 weights
# for eval: after 20 steps the update is ~1e-4 of |W|, below bf16 resolution, and a
# merged copy is mostly the base (pipe-r11, 2026-09-18).
#
#   EVAL_ROOT=/workspace/.../runs/eval-v1-base  CUDA_VISIBLE_DEVICES=0 \
#     bash examples/harbor_opd_rl/eval_val_only.sh
#   EVAL_ROOT=/workspace/.../runs/eval-v1-pipe-r11  CUDA_VISIBLE_DEVICES=1 \
#     RESUME_FROM=<run>/train/checkpoints/.../global_step_20 bash examples/harbor_opd_rl/eval_val_only.sh
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
# the run that wrote it (pipe-r11 defaults); nothing is trained.
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

(cd "${REPO_ROOT}" && env MODEL_PATH="${MODEL_PATH}" MODEL_ID="hosted_vllm/$(basename "${MODEL_PATH}")" \
   TRAIN_FILE="${TRAIN_DATA}" TEST_FILE="${EVAL_DATA}" TASK_CONFIG="${TASK_CONFIG}" RUN_ROOT="${EVAL_ROOT}" \
   PYTHON_BIN="${LANE_PY}" EXP_NAME="eval-$(basename "${EVAL_ROOT}")" TOTAL_TRAINING_STEPS=20 \
   TRAIN_MAX_SAMPLES=100 VAL_MAX_SAMPLES="${VAL_MAX}" TRAIN_BATCH_SIZE=4 PPO_MINI_BATCH_SIZE=4 ROLLOUT_N=8 \
   CONCURRENCY="${CONCURRENCY}" ROLLOUT_MAX_NUM_SEQS="${CONCURRENCY}" SAVE_FREQ=-1 DAPO=0 TEACHER=0 \
   VAL_ROLLOUT_N="${EVAL_N}" VAL_TEMPERATURE=1.0 VAL_BEFORE_TRAIN=True TEST_FREQ=-1 WANDB_ENABLED=0 MIN_VALID_SESSIONS=0 \
   GPU_MEMORY_UTILIZATION="${GPU_MEMORY_UTILIZATION:-0.6}" \
   RESUME_MODE="$([[ -n "${RESUME_FROM}" ]] && echo resume_path || echo disable)" RESUME_FROM_PATH="${RESUME_FROM}" \
   bash examples/harbor_opd_rl/train_tb21_lora_smoke.sh trainer.val_only=True) > "${EVAL_ROOT}/eval.log" 2>&1 || true

"${LANE_PY}" - "${EVAL_ROOT}" <<'PY'
import glob, json, os, re, sys
root = sys.argv[1]
per_task, infra = {}, {}
done = re.compile(r"Harbor trial done: instance_id=(\S+) reward=[0-9.]+ resolved=(\w+)")
bad = re.compile(r"Harbor trial incomplete for (\S+) \(infra\)")
for f in glob.glob(os.path.join(root, "agent-logs", "**", "task.log"), recursive=True):
    text = open(f, errors="replace").read()
    for m in done.finditer(text):
        per_task.setdefault(m.group(1).split("/")[-1], []).append(1.0 if m.group(2) == "True" else 0.0)
    for m in bad.finditer(text):
        name = m.group(1).split("/")[-1]
        infra[name] = infra.get(name, 0) + 1
means = [sum(v) / len(v) for v in per_task.values()]
summary = {"tasks": len(per_task), "samples": sum(len(v) for v in per_task.values()),
           "pass_rate": sum(means) / len(means) if means else None,
           "infra_incomplete": infra, "per_task": dict(sorted(per_task.items()))}
json.dump(summary, open(os.path.join(root, "summary.json"), "w"), indent=1)
print(json.dumps({k: summary[k] for k in ("tasks", "samples", "pass_rate")} | {"infra_incomplete": sum(infra.values())}))
PY
echo "eval done: ${EVAL_ROOT}/summary.json"
