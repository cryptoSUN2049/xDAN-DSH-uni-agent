#!/usr/bin/env bash
# Stage delta: compare the first and last training checkpoints on CPU with the
# existing deployment/checks/checkpoint_delta.py probe. Proves finite LoRA
# adapter updates with unchanged base tensors. No GPU.
STAGE_NAME=delta
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"; stage_dir

CK_LAST="$(cat "${PIPE_ROOT}/train/final-checkpoint.txt")"
CK_FIRST="$(dirname "${CK_LAST}")/global_step_1"
if [[ "${CK_FIRST}" == "${CK_LAST}" ]]; then
  mark_passed; record skipped '"single training step: nothing to diff"'; log "skipped (one step)"; exit 0
fi
(cd "${REPO_ROOT}" && "${LANE_PY}" deployment/checks/checkpoint_delta.py \
   "${CK_FIRST}/model_world_size_1_rank_0.pt" "${CK_LAST}/model_world_size_1_rank_0.pt" \
   --output "${STAGE_DIR}/delta.json") > "${STAGE_DIR}/run.log" 2>&1
DETAIL=$("${LANE_PY}" -c 'import json,sys; d=json.load(open(sys.argv[1])); print(json.dumps({k:d[k] for k in ("passed","adapter_count","adapter_changed","base_count","base_changed") if k in d}))' "${STAGE_DIR}/delta.json")
mark_passed; record passed "${DETAIL}"
log "passed: $(head -c 300 "${STAGE_DIR}/delta.json")"
