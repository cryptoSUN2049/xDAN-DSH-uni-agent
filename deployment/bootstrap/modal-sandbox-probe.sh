#!/usr/bin/env bash
# Measure what a Harbor sandbox on Modal actually costs us: applied spec, whether a
# finished trial releases its sandbox, and whether a killed trial leaks one that the
# cleanup script can collect. Two sandboxes, a few minutes, no GPU.
#
#   bash deployment/bootstrap/modal-sandbox-probe.sh [--task <task-dir>] [--out <dir>]
#
# Writes <out>/report.md. Run it before a training round whenever the sandbox
# settings change; the numbers feed docs/verl-uni-agent-harbor-opd-rl/modal-cost-postmortem.md.
set -uo pipefail
LANE_ROOT="${LANE_ROOT:-/workspace/verl-uni-agent-harbor-opd-rl}"
REPO_ROOT="${REPO_ROOT:-${LANE_ROOT}/src/uni-agent}"
TASK_DIR="${TASK_DIR:-}"; OUT="${OUT:-${LANE_ROOT}/runs/modal-lifecycle-probe}"
while [[ $# -gt 0 ]]; do case "$1" in
  --task) TASK_DIR="$2"; shift;; --out) OUT="$2"; shift;; *) echo "unknown argument: $1" >&2; exit 2;; esac; shift; done
export PATH="${LANE_ROOT}/envs/ua-verl-py312-vllm023-ws1/bin:${PATH}"
PY="${LANE_PY:-${LANE_ROOT}/envs/ua-verl-py312-vllm023-ws1/bin/python}"
[[ -n "${TASK_DIR}" ]] || TASK_DIR=$(ls -d "${LANE_ROOT}"/data-r4/stage1/tasks-train/*terminal-lego* 2>/dev/null | head -1)
[[ -d "${TASK_DIR}" ]] || { echo "no task dir; pass --task" >&2; exit 2; }
mkdir -p "${OUT}"; cd "${REPO_ROOT}"

bash deployment/bootstrap/modal-quota-wait.sh --interval "${QUOTA_INTERVAL:-900}" --max-hours "${QUOTA_MAX_HOURS:-48}" || exit 1

snapshot() { "${PY}" - "$1" <<'PY'
import sys, time, modal
label = sys.argv[1]
try:
    app = modal.App.lookup("__harbor__", create_if_missing=False)
    rows = []
    for sb in modal.Sandbox.list(app_id=app.app_id):
        created = getattr(sb, "created_at", None)
        created_s = created.timestamp() if hasattr(created, "timestamp") else created
        age = f"{(time.time() - created_s) / 60:.1f}min" if isinstance(created_s, (int, float)) else "unknown"
        rows.append(f"{sb.object_id} age={age}")
    print(f"{label}: {len(rows)} sandbox(es)" + ("" if not rows else " -> " + ", ".join(rows)))
except Exception as exc:
    print(f"{label}: lookup failed {type(exc).__name__}: {exc}")
PY
}

run_trial() { # name -> starts a detached oracle trial, echoes its pid
  local name="$1"
  harbor trial start --path "${TASK_DIR}" --trial-name "${name}" --trials-dir "${OUT}/trials" \
    --agent oracle --env modal --timeout-multiplier 1 > "${OUT}/${name}.log" 2>&1 &
  echo $!
}

{
  echo "# Modal sandbox lifecycle probe"
  echo
  echo "- task: $(basename "${TASK_DIR}")"
  echo "- started: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "- config: $(grep -E 'override_cpus|override_memory_mb|trial_timeout_sec' "${REPO_ROOT}/examples/harbor_opd_rl/tb21_terminus2_smoke.yaml" | tr -d ' ' | tr '\n' ' ')"
  echo
  echo "## 1. Normal completion"
  snapshot "before"
  pid=$(run_trial probe-normal)
  sleep 90; snapshot "during (t+90s)"
  wait "${pid}"; echo "trial exit=$?"
  sleep 30; snapshot "after completion (t+30s)"
  echo
  echo "## 2. Killed client (the leak we pay for)"
  snapshot "before"
  pid=$(run_trial probe-killed)
  sleep 90; snapshot "during (t+90s)"
  kill -TERM "${pid}" 2>/dev/null; sleep 30
  snapshot "30 s after killing the Harbor CLI"
  echo
  echo "## 3. Cleanup script"
  bash deployment/bootstrap/modal-sandbox-cleanup.sh --apply --older-than 0
  sleep 20; snapshot "after cleanup"
  echo
  echo "Finished: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
} 2>&1 | tee "${OUT}/report.md"
