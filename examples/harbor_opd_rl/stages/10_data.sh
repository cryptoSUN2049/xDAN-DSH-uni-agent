#!/usr/bin/env bash
# Stage data: download Terminal-Bench 2.1 from Harbor Hub into parquet with the
# upstream preprocessor, and build the training subset (TASK_FILTER=easy uses the
# four tasks labelled easy; all uses the first MAX_INSTANCES). No GPU.
STAGE_NAME=data
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"; stage_dir

# DATASET=stage1: private HF repo gump2049/xDAN-Harbor-Stage1-Tasks (Harbor task
# dirs under <source>/<rev>/runtime-v1/<task>, index/tasks.jsonl with split +
# difficulty). STAGE1_SLICE=N takes the first N train tasks in index order
# (20 -> 100 -> all as the dataset grows); STAGE1_SOURCES filters sources.
# Validation split becomes the held-out parquet. Needs HF_TOKEN or ~/.cache/huggingface/token.
DATASET="${DATASET:-tb21}"
if [[ "${DATASET}" == stage1 ]]; then
  STAGE1_REPO="${STAGE1_REPO:-gump2049/xDAN-Harbor-Stage1-Tasks}"
  STAGE1_SLICE="${STAGE1_SLICE:-20}"          # 0 = all
  STAGE1_SOURCES="${STAGE1_SOURCES:-terminal-lego-15k swe-rebench-v2-fv}"
  S1="${DATA_DIR}/stage1"; mkdir -p "${S1}"
  "${LANE_PY}" - "${STAGE1_REPO}" "${S1}/repo" "${STAGE1_SLICE}" "${STAGE1_SOURCES}" "${S1}" > "${STAGE_DIR}/stage1-select.log" 2>&1 <<'PY'
import json, os, shutil, sys
from huggingface_hub import snapshot_download
repo, local, slice_n, sources, out = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4].split(), sys.argv[5]
path = snapshot_download(repo, repo_type="dataset", local_dir=local, allow_patterns=["index/*", "*/runtime-v1/*"])
rows = [json.loads(l) for l in open(os.path.join(path, "index", "tasks.jsonl"))]
rows = [r for r in rows if r["source"] in sources and r["status"] == "derived"]
train = [r for r in rows if r["split"] == "train"]
val = [r for r in rows if r["split"] == "validation"]
if slice_n > 0:
    train = train[:slice_n]
for name, subset in (("train", train), ("validation", val)):
    root = os.path.join(out, f"tasks-{name}")
    shutil.rmtree(root, ignore_errors=True); os.makedirs(root)
    for r in subset:
        shutil.copytree(os.path.join(path, r["task_dir"]), os.path.join(root, f"{r['source']}__{r['task']}"))
    print(name, len(subset), root)
json.dump({"repo": repo, "slice": slice_n, "sources": sources, "train": [r["task"] for r in train], "validation": [r["task"] for r in val],
           "difficulty": {d: sum(1 for r in train if r.get("difficulty") == d) for d in ("easy", "medium", "hard")}},
          open(os.path.join(out, "selection.json"), "w"), indent=1)
PY
  cat "${STAGE_DIR}/stage1-select.log"
  (cd "${REPO_ROOT}" && "${LANE_PY}" -m uni_agent.tasks.harbor.preprocess --task-root "${S1}/tasks-train" \
     --local-save-dir "${S1}/train") > "${STAGE_DIR}/preprocess-stage1-train.log" 2>&1
  (cd "${REPO_ROOT}" && "${LANE_PY}" -m uni_agent.tasks.harbor.preprocess --task-root "${S1}/tasks-validation" \
     --local-save-dir "${S1}/validation") > "${STAGE_DIR}/preprocess-stage1-val.log" 2>&1
  TRAIN_PARQUET="${S1}/train/harbor_tasks-train.parquet"
  FULL_PARQUET="${S1}/validation/harbor_tasks-validation.parquet"   # held-out for TEST_FILE
  echo "${TRAIN_PARQUET}" > "${STAGE_DIR}/train-parquet.txt"
  echo "${FULL_PARQUET}" > "${STAGE_DIR}/full-parquet.txt"
  cp "${S1}/selection.json" "${STAGE_DIR}/selection.json"
  ROWS=$("${LANE_PY}" -c "import pandas as pd,sys; print(len(pd.read_parquet(sys.argv[1])))" "${TRAIN_PARQUET}")
  mark_passed; record passed "{\"dataset\":\"stage1\",\"train_parquet\":\"${TRAIN_PARQUET}\",\"rows\":${ROWS},\"slice\":${STAGE1_SLICE}}"
  log "passed: stage1 slice=${STAGE1_SLICE} -> ${TRAIN_PARQUET} (${ROWS} rows); held-out ${FULL_PARQUET}"
  exit 0
fi

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
