#!/usr/bin/env bash
# Stage cost: prove the sandbox discipline held during this run. cost_report.py measures
# the run's Modal bill (hourly rows of the run's app inside the run window, priced at the
# Sandbox rate) against the trial hours the run actually used, and counts sandboxes still
# alive. Thresholds: billed/used core-hours <= 1.5, <= 0.05 USD per trial, 0 leaked.
#
# The 2026-09-17 runs billed about 950 sandbox-hours for about 200 trial-hours (4.8x,
# see modal-cost-postmortem.md), which is what these thresholds exist to catch. A number
# that cannot be measured counts as a breach. A breach records "failed" but never stops
# the pipeline: training results stay valid, the bill is a separate concern.
STAGE_NAME=cost
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"; stage_dir

# Let the last sandboxes finish teardown and their seconds reach the bill before measuring.
sleep "${COST_SETTLE_SECS:-300}"
# The app comes from the same task config the trials were created with.
"${LANE_PY}" "${STAGES_DIR}/cost_report.py" --pipe-root "${PIPE_ROOT}" \
  --out "${STAGE_DIR}/cost.json" --task-config "${TASK_CONFIG}"
# Compact subset for pipeline-summary.jsonl (a truncated full report would not parse).
DETAIL=$("${LANE_PY}" -c 'import json,sys; c=json.load(open(sys.argv[1])); print(json.dumps({k: c.get(k) for k in ("app","trials","trial_hours","billed_usd","billed_core_hours","billed_to_used_ratio","usd_per_trial","leaked_sandboxes","breaches","passed")}, separators=(",",":")))' "${STAGE_DIR}/cost.json")
PASSED=$("${LANE_PY}" -c 'import json,sys; print("passed" if json.load(open(sys.argv[1]))["passed"] else "failed")' "${STAGE_DIR}/cost.json")
mark_passed; record "${PASSED}" "${DETAIL}"
log "${PASSED}: $(head -c 300 "${STAGE_DIR}/cost.json" | tr -d '\n')"
