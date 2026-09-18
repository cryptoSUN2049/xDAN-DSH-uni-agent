#!/usr/bin/env bash
# Terminal-Bench 2.1 evaluation with the SAME harness as training (Harbor +
# terminus-2 in Modal, model served through the Uni-Agent Gateway). Produces a
# per-task pass matrix and a summary JSON so base vs trained models can be
# compared with confidence intervals.
#
#   MODEL_PATH=/workspace/models/Qwen3-4B-1cfa9a7 EVAL_ROOT=/workspace/.../runs/eval-tb21-4b-base \
#   bash examples/harbor_opd_rl/eval_tb21.sh
#
# Other task sets: DATA_PARQUET=<harbor parquet> (e.g. from prepare_eval_set.py) replaces
# Terminal-Bench 2.1. Two evals can share a pod: pin each to a GPU with
# CUDA_VISIBLE_DEVICES; each starts its own local Ray (RAY_ADDRESS=local, own temp dir)
# and never stops another's.
#
# Knobs: EVAL_N (samples per task, default 3), EVAL_LIMIT (tasks, default 0 = all 89),
#        CONCURRENCY (default 16), TASK_CONFIG (default tb21_terminus2_smoke.yaml),
#        HARBOR_REWARD_MODE (default binary: official pass/fail; pass_ratio also recorded in logs)
# Trained LoRA checkpoints must first be merged into HF weights (see README: model merge).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
LANE_ROOT="${LANE_ROOT:-/workspace/verl-uni-agent-harbor-opd-rl}"
LANE_PY="${LANE_PY:-${LANE_ROOT}/envs/ua-verl-py312-vllm023-ws1/bin/python}"
export PATH="$(dirname "${LANE_PY}"):${PATH}"
export PYTHONPATH="${REPO_ROOT}:${REPO_ROOT}/verl${PYTHONPATH:+:${PYTHONPATH}}"
MODEL_PATH="${MODEL_PATH:?HF model dir (base or merged)}"
EVAL_ROOT="${EVAL_ROOT:?new absolute output dir}"
SERVED_MODEL_NAME="${SERVED_MODEL_NAME:-hosted_vllm/$(basename "${MODEL_PATH}")}"
TASK_CONFIG="${TASK_CONFIG:-${REPO_ROOT}/examples/harbor_opd_rl/tb21_terminus2_smoke.yaml}"
DATA_DIR="${DATA_DIR:-${LANE_ROOT}/data}"
EVAL_N="${EVAL_N:-3}"
EVAL_LIMIT="${EVAL_LIMIT:-0}"
CONCURRENCY="${CONCURRENCY:-16}"
export HARBOR_REWARD_MODE="${HARBOR_REWARD_MODE:-binary}"
export UNI_AGENT_LOG_DIR="${EVAL_ROOT}/logs"
[[ -e "${EVAL_ROOT}" ]] && { echo "EVAL_ROOT exists; use a new dir to keep evidence" >&2; exit 2; }
mkdir -p "${EVAL_ROOT}"

# Full TB 2.1 parquet (89 tasks); the training data stage only keeps MAX_INSTANCES.
FULL="${DATA_PARQUET:-${DATA_DIR}/tb21-full/harbor_terminal-bench_terminal-bench-2-1.parquet}"
if [[ -z "${DATA_PARQUET:-}" && ! -f "${FULL}" ]]; then
  (cd "${REPO_ROOT}" && "${LANE_PY}" -m uni_agent.tasks.harbor.preprocess --dataset-ref terminal-bench/terminal-bench-2-1 \
     --local-save-dir "${DATA_DIR}/tb21-full") > "${EVAL_ROOT}/preprocess.log" 2>&1
fi
[[ -f "${FULL}" ]] || { echo "no parquet at ${FULL}" >&2; exit 2; }
ROWS=$("${LANE_PY}" -c "import pandas as pd,sys; print(len(pd.read_parquet(sys.argv[1])))" "${FULL}")
GPU_ID="${CUDA_VISIBLE_DEVICES:-0}"; GPU_ID="${GPU_ID%%,*}"
used=$(nvidia-smi -i "${GPU_ID}" --query-gpu=memory.used --format=csv,noheader,nounits)
[[ "${used}" -lt 2000 ]] || { echo "GPU ${GPU_ID} busy (${used} MiB)" >&2; exit 3; }
# Own local Ray cluster per eval; a short temp dir keeps Ray's socket paths under the
# 107-byte Unix limit.
export RAY_ADDRESS=local
export RAY_TMPDIR="/tmp/ray-eval-$(basename "${EVAL_ROOT}" | cut -c1-24)"
mkdir -p "${RAY_TMPDIR}"

cat > "${EVAL_ROOT}/eval-config.json" <<JSON
{"model_path":"${MODEL_PATH}","served_model_name":"${SERVED_MODEL_NAME}","task_config":"${TASK_CONFIG}","data":"${FULL}","rows":${ROWS},"n":${EVAL_N},"limit":${EVAL_LIMIT},"concurrency":${CONCURRENCY},"reward_mode":"${HARBOR_REWARD_MODE}","started_utc":"$(date -u +%Y-%m-%dT%H:%M:%SZ)"}
JSON
LIMIT_ARGS=(); [[ "${EVAL_LIMIT}" -gt 0 ]] && LIMIT_ARGS=(--limit "${EVAL_LIMIT}")
(cd "${REPO_ROOT}" && "${LANE_PY}" examples/inference/parallel_infer_verl.py \
   --data-path "${FULL}" --model-path "${MODEL_PATH}" --served-model-name "${SERVED_MODEL_NAME}" \
   --task-config "${TASK_CONFIG}" --engine vllm --tool-parser "${TOOL_PARSER:-hermes}" --nnodes 1 --n-gpus-per-node 1 \
   --tensor-parallel-size 1 --gpu-memory-utilization "${ROLLOUT_GPU_MEM:-0.6}" --max-model-len "${MAX_MODEL_LEN:-36864}" \
   --n "${EVAL_N}" --concurrency "${CONCURRENCY}" "${LIMIT_ARGS[@]}" \
   --log-dir "${EVAL_ROOT}/logs" --result-path "${EVAL_ROOT}/result.json") > "${EVAL_ROOT}/run.log" 2>&1 || true
# No `ray stop`: it would stop every Ray cluster on the pod, including a training run
# or the other eval. The in-process cluster ends with parallel_infer_verl.py; launch
# through launch-detached.sh and `pkill -s <sid>` if anything is left behind.

"${LANE_PY}" - "${EVAL_ROOT}" <<'PY'
import json, sys, glob, os, re, math, random
root = sys.argv[1]
res = json.load(open(os.path.join(root, "result.json")))
# per-task pass matrix from Harbor task logs (binary reward), grouped by instance
per_task = {}
for f in glob.glob(os.path.join(root, "logs", "session-*", "task.log")):
    t = open(f, errors="replace").read()
    m = re.search(r"Harbor trial done: instance_id=(\S+) reward=([0-9.]+) resolved=(\w+)", t)
    if m:
        per_task.setdefault(m.group(1).split("/")[-1], []).append(1.0 if m.group(3) == "True" else 0.0)
tasks = sorted(per_task)
means = [sum(v) / len(v) for v in per_task.values()]
acc = sum(means) / len(means) if means else None
# bootstrap CI over tasks
random.seed(0); bs = []
for _ in range(2000):
    s = [means[random.randrange(len(means))] for _ in means]; bs.append(sum(s) / len(s))
bs.sort()
summary = {"tasks": len(tasks), "samples_per_task": res.get("n"), "pass_rate": acc,
           "ci95": [bs[int(0.025 * len(bs))], bs[int(0.975 * len(bs))]] if bs else None,
           "mean_rm_score": res.get("mean_rm_score"), "scored_sessions": res.get("num_scored_sessions"),
           "per_task": {k: per_task[k] for k in tasks}}
json.dump(summary, open(os.path.join(root, "summary.json"), "w"), indent=1)
print(json.dumps({k: summary[k] for k in ("tasks", "samples_per_task", "pass_rate", "ci95", "scored_sessions")}))
PY
echo "eval done: ${EVAL_ROOT}/summary.json"
