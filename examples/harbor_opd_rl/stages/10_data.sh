#!/usr/bin/env bash
# Stage data: download Terminal-Bench 2.1 from Harbor Hub into parquet with the
# upstream preprocessor, and build the training subset (TASK_FILTER=easy uses the
# four tasks labelled easy; all uses the first MAX_INSTANCES). No GPU.
STAGE_NAME=data
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"; stage_dir

FULL_PARQUET="${DATA_DIR}/harbor_terminal-bench_terminal-bench-2-1.parquet"
if [[ ! -f "${FULL_PARQUET}" ]]; then
  (cd "${REPO_ROOT}" && "${LANE_PY}" -m uni_agent.tasks.harbor.preprocess --dataset-ref "${TB_DATASET_REF}" \
     --local-save-dir "${DATA_DIR}" --max-instances "${MAX_INSTANCES}") > "${STAGE_DIR}/preprocess-full.log" 2>&1
fi
TASK_ROOT="${DATA_DIR}/harbor/terminal-bench_terminal-bench-2-1/terminal-bench-2-1"
if [[ "${TASK_FILTER}" == easy ]]; then
  E="${DATA_DIR}/tb21-easy-tasks"; rm -rf "${E}"; mkdir -p "${E}"
  for t in ${EASY_TASKS}; do cp -r "${TASK_ROOT}/${t}" "${E}/${t}"; done   # preprocess ignores symlinks
  (cd "${REPO_ROOT}" && "${LANE_PY}" -m uni_agent.tasks.harbor.preprocess --task-root "${E}" \
     --local-save-dir "${DATA_DIR}/easy") > "${STAGE_DIR}/preprocess-easy.log" 2>&1
  TRAIN_PARQUET="${DATA_DIR}/easy/harbor_tb21-easy-tasks.parquet"
else
  TRAIN_PARQUET="${FULL_PARQUET}"
fi
echo "${TRAIN_PARQUET}" > "${STAGE_DIR}/train-parquet.txt"
echo "${FULL_PARQUET}" > "${STAGE_DIR}/full-parquet.txt"
ROWS=$("${LANE_PY}" -c "import pandas as pd,sys; print(len(pd.read_parquet(sys.argv[1])))" "${TRAIN_PARQUET}")
grep -h -E "^difficulty" "${TASK_ROOT}"/*/task.toml | sort | uniq -c > "${STAGE_DIR}/difficulty-histogram.txt" || true
mark_passed; record passed "{\"train_parquet\":\"${TRAIN_PARQUET}\",\"rows\":${ROWS},\"filter\":\"${TASK_FILTER}\"}"
log "passed: ${TRAIN_PARQUET} (${ROWS} rows)"
