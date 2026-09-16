#!/usr/bin/env bash
# Stage oracle: run Harbor's oracle agent (reference solution) on two tasks in
# Modal sandboxes and require the verifier to score every trial 1.0. Proves the
# task images, sandbox provider and verifier path without any model. No GPU.
STAGE_NAME=oracle
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"; stage_dir

(cd "${REPO_ROOT}" && NUM_WORKERS=2 GLOBAL_CONCURRENCY=2 "${LANE_PY}" examples/inference/parallel_infer_api.py \
   --data-path "$(train_parquet)" --task-config "${ORACLE_CONFIG}" --base-url http://unused.invalid/v1 \
   --limit "${ORACLE_LIMIT:-2}" --concurrency 2 --log-dir "${STAGE_DIR}/logs" --result-path "${STAGE_DIR}/result.json") \
   > "${STAGE_DIR}/run.log" 2>&1
DETAIL=$("${LANE_PY}" - "${STAGE_DIR}/result.json" <<'PY'
import json,sys; s=json.load(open(sys.argv[1]))["summary"]
assert s["resolved"]==s["total_rollouts"]>0, s
print(json.dumps({"resolved":s["resolved"],"total":s["total_rollouts"],"mean_reward":s["mean_reward"],"avg_eval_s":round(s["average_eval_execution_time"],1)}))
PY
)
mark_passed; record passed "${DETAIL}"
log "passed: ${DETAIL}"
