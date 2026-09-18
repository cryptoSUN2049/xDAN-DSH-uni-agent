#!/usr/bin/env bash
# Stage cost: prove the sandbox discipline held during this run. Three numbers, each
# with a threshold, written to cost.json and recorded in pipeline-summary.jsonl:
#
#   leaked_sandboxes      sandboxes still alive after the run          target 0
#   billed_to_used_ratio  Modal sandbox-hours today / trial hours today target <= 1.5
#   usd_per_trial         today's __harbor__ spend / today's trials     target <= 0.05
#
# The 2026-09-17 run scored 14x and 0.50 USD per trial (see modal-cost-postmortem.md),
# which is what these thresholds exist to catch. A breach records "failed" but never
# stops the pipeline: training results stay valid, the bill is a separate concern.
STAGE_NAME=cost
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"; stage_dir

TRIAL_HOURS=$("${LANE_PY}" - "${PIPE_ROOT}" <<'PY'
import re, sys
from pathlib import Path
root = Path(sys.argv[1])
seconds, trials = 0.0, 0
for log in root.rglob("task.log"):
    for m in re.finditer(r"Harbor trial done: .*? elapsed=([0-9.]+)s", log.read_text(errors="replace")):
        seconds += float(m.group(1)); trials += 1
print(f"{seconds / 3600:.3f} {trials}")
PY
)
USED_HOURS=${TRIAL_HOURS%% *}; TRIALS=${TRIAL_HOURS##* }

"${LANE_PY}" - "${STAGE_DIR}/cost.json" "${USED_HOURS}" "${TRIALS}" <<'PY'
import json, subprocess, sys, time
out_path, used_hours, trials = sys.argv[1], float(sys.argv[2]), int(sys.argv[3])
# Modal's per-resource report is daily; CPU dollars / CPU price gives core-hours, and
# Harbor sandboxes take one core each now, so core-hours are sandbox-hours.
CPU_USD_PER_CORE_HOUR = 0.047
app = "__harbor__"
billed_usd = None
try:
    report = subprocess.run(["modal", "billing", "report", "--for", "today", "--show-resources"],
                            capture_output=True, text=True, timeout=180).stdout
    rows = [l for l in report.splitlines() if app[:9] in l or app in l]
    billed_usd = sum(float(tok) for l in rows for tok in l.replace("│", " ").split()
                     if tok.replace(".", "", 1).isdigit() and "." in tok and float(tok) < 1e6)
except Exception as exc:
    print(f"billing report unavailable: {type(exc).__name__}: {exc}")

leaked = None
try:
    import modal
    a = modal.App.lookup(app, create_if_missing=False)
    leaked = sum(1 for _ in modal.Sandbox.list(app_id=a.app_id))
except Exception as exc:
    print(f"sandbox list unavailable: {type(exc).__name__}: {exc}")

billed_hours = billed_usd / CPU_USD_PER_CORE_HOUR if billed_usd else None
ratio = (billed_hours / used_hours) if billed_hours and used_hours else None
usd_per_trial = (billed_usd / trials) if billed_usd and trials else None
checks = {
    "trials": trials, "trial_hours": round(used_hours, 2),
    "billed_usd_today": round(billed_usd, 2) if billed_usd else None,
    "billed_sandbox_hours_today": round(billed_hours, 1) if billed_hours else None,
    "billed_to_used_ratio": round(ratio, 2) if ratio else None,
    "usd_per_trial": round(usd_per_trial, 4) if usd_per_trial else None,
    "leaked_sandboxes": leaked,
    "thresholds": {"billed_to_used_ratio": 1.5, "usd_per_trial": 0.05, "leaked_sandboxes": 0},
    "measured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
}
breaches = []
if leaked not in (None, 0): breaches.append(f"leaked_sandboxes={leaked}")
if ratio and ratio > 1.5: breaches.append(f"billed_to_used_ratio={ratio:.2f}")
if usd_per_trial and usd_per_trial > 0.05: breaches.append(f"usd_per_trial={usd_per_trial:.3f}")
checks["breaches"] = breaches
checks["passed"] = not breaches
json.dump(checks, open(out_path, "w"), indent=1)
print(json.dumps({k: checks[k] for k in ("trials", "trial_hours", "billed_usd_today", "billed_to_used_ratio", "usd_per_trial", "leaked_sandboxes", "passed", "breaches")}))
PY
DETAIL=$(tr -d '\n' < "${STAGE_DIR}/cost.json" | cut -c1-2000)
PASSED=$("${LANE_PY}" -c 'import json,sys; print("passed" if json.load(open(sys.argv[1]))["passed"] else "failed")' "${STAGE_DIR}/cost.json")
mark_passed; record "${PASSED}" "${DETAIL}"
log "${PASSED}: $(head -c 300 "${STAGE_DIR}/cost.json" | tr -d '\n')"
