#!/usr/bin/env bash
# Stage rollout: launch vLLM behind the Uni-Agent Gateway with the upstream
# inference runner and let terminus-2 (on this host) solve two tasks in Modal.
# Requires every session to be scored and to leave a token-level trajectory.npz.
STAGE_NAME=rollout
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"; stage_dir; gpu_free

(cd "${REPO_ROOT}" && UNI_AGENT_LOG_DIR="${STAGE_DIR}/logs" "${LANE_PY}" examples/inference/parallel_infer_verl.py \
   --data-path "$(train_parquet)" --model-path "${MODEL_PATH}" --served-model-name "${SERVED_MODEL_NAME}" \
   --task-config "${TASK_CONFIG}" --engine vllm --tool-parser "${TOOL_PARSER:-hermes}" --nnodes 1 --n-gpus-per-node 1 \
   --tensor-parallel-size 1 --gpu-memory-utilization "${ROLLOUT_GPU_MEM:-0.6}" --max-model-len "${MAX_MODEL_LEN:-36864}" \
   --limit "${ROLLOUT_LIMIT:-2}" --concurrency 2 --log-dir "${STAGE_DIR}/logs" --result-path "${STAGE_DIR}/result.json") \
   > "${STAGE_DIR}/run.log" 2>&1
DETAIL=$("${LANE_PY}" - "${STAGE_DIR}/result.json" "${STAGE_DIR}/logs" <<'PY'
import json,sys,glob,os
d=json.load(open(sys.argv[1])); assert d["num_scored_sessions"]==d["num_prompts"]*d["n"]>0, d
traj=glob.glob(os.path.join(sys.argv[2],"session-*","trajectory.npz")); assert len(traj)==d["num_scored_sessions"], traj
print(json.dumps({"scored_sessions":d["num_scored_sessions"],"mean_rm_score":d["mean_rm_score"],"trajectories":len(traj)}))
PY
)
ray stop --force >/dev/null 2>&1 || true
mark_passed; record passed "${DETAIL}"
log "passed: ${DETAIL}"
