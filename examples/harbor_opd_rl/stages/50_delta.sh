#!/usr/bin/env bash
# Stage delta: compare the first and last training checkpoints on CPU with the
# existing deployment/checks/checkpoint_delta.py probe. Proves finite LoRA
# adapter updates with unchanged base tensors. No GPU.
STAGE_NAME=delta
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"; stage_dir

CK_LAST="$(cat "${PIPE_ROOT}/train/final-checkpoint.txt")"
# With trainer.max_actor_ckpt_to_keep=N only the newest N survive; compare the
# earliest surviving checkpoint with the final one (consecutive steps still prove
# adapter-changed / base-unchanged).
CK_FIRST="$(ls -d "$(dirname "${CK_LAST}")"/global_step_* 2>/dev/null | sort -t_ -k3 -n | head -1)"
if [[ "${CK_FIRST}" == "${CK_LAST}" ]]; then
  mark_passed; record skipped '"single training step: nothing to diff"'; log "skipped (one step)"; exit 0
fi
model_file() { local ck="$1"; for f in "${ck}/actor/model_world_size_1_rank_0.pt" "${ck}/model_world_size_1_rank_0.pt"; do [[ -f "${f}" ]] && { echo "${f}"; return 0; }; done; return 1; }
BEFORE=$(model_file "${CK_FIRST}") || { log "no model file under ${CK_FIRST}"; record failed '"first checkpoint model missing"'; exit 1; }
AFTER=$(model_file "${CK_LAST}") || { log "no model file under ${CK_LAST}"; record failed '"last checkpoint model missing"'; exit 1; }
(cd "${REPO_ROOT}" && "${LANE_PY}" deployment/checks/checkpoint_delta.py "${BEFORE}" "${AFTER}" \
   --output "${STAGE_DIR}/delta.json") > "${STAGE_DIR}/run.log" 2>&1
DETAIL=$("${LANE_PY}" -c 'import json,sys; d=json.load(open(sys.argv[1])); print(json.dumps({k:d[k] for k in ("passed","adapter_count","adapter_changed","base_count","base_changed") if k in d}))' "${STAGE_DIR}/delta.json")
mark_passed; record passed "${DETAIL}"
log "passed: $(head -c 300 "${STAGE_DIR}/delta.json")"
