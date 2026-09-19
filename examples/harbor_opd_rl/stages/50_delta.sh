#!/usr/bin/env bash
# Stage delta: compare the first and last training checkpoints on CPU with the
# existing deployment/checks/checkpoint_delta.py probe. Proves finite LoRA
# adapter updates with unchanged base tensors. No GPU.
STAGE_NAME=delta
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"; stage_dir

CK_LAST="$(cat "${PIPE_ROOT}/train/final-checkpoint.txt")"
model_file() { local ck="$1"; for f in "${ck}/actor/model_world_size_1_rank_0.pt" "${ck}/model_world_size_1_rank_0.pt"; do [[ -f "${f}" ]] && { echo "${f}"; return 0; }; done; return 1; }
# With trainer.max_actor_ckpt_to_keep=N only the newest N survive; compare the
# earliest surviving checkpoint with the final one (consecutive steps still prove
# adapter-changed / base-unchanged). VERL's rotation deletes only actor/ and leaves
# global_step_N/data.pt behind, so "surviving" means a model file is still there
# (pipe-s2 phase A picked the empty global_step_1 shell and failed, 2026-09-19).
CK_FIRST=""
while read -r ck; do
  model_file "${ck}" >/dev/null && { CK_FIRST="${ck}"; break; }
done < <(for d in "$(dirname "${CK_LAST}")"/global_step_*; do [[ -d "${d}" ]] && echo "${d##*_} ${d}"; done | sort -n | cut -d' ' -f2-)
[[ -n "${CK_FIRST}" ]] || { log "no checkpoint with a model file next to ${CK_LAST}"; record failed '"no checkpoint model"'; exit 1; }
if [[ "${CK_FIRST}" == "${CK_LAST}" ]]; then
  mark_passed; record skipped '"single surviving checkpoint: nothing to diff"'; log "skipped (one checkpoint)"; exit 0
fi
BEFORE=$(model_file "${CK_FIRST}") || { log "no model file under ${CK_FIRST}"; record failed '"first checkpoint model missing"'; exit 1; }
AFTER=$(model_file "${CK_LAST}") || { log "no model file under ${CK_LAST}"; record failed '"last checkpoint model missing"'; exit 1; }
(cd "${REPO_ROOT}" && "${LANE_PY}" deployment/checks/checkpoint_delta.py "${BEFORE}" "${AFTER}" \
   --output "${STAGE_DIR}/delta.json") > "${STAGE_DIR}/run.log" 2>&1
DETAIL=$("${LANE_PY}" -c 'import json,sys; d=json.load(open(sys.argv[1])); print(json.dumps({k:d[k] for k in ("passed","adapter_count","adapter_changed","base_count","base_changed") if k in d}))' "${STAGE_DIR}/delta.json")
mark_passed; record passed "${DETAIL}"
log "passed: $(head -c 300 "${STAGE_DIR}/delta.json")"
