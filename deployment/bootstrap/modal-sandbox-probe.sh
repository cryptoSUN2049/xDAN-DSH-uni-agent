#!/usr/bin/env bash
# Measure what a Harbor sandbox on Modal actually does: does a finished trial release
# it, does a killed client leak it, and does the cleanup script collect the leak.
#
#   bash deployment/bootstrap/modal-sandbox-probe.sh [--task <dir>] [--out <dir>]
#
# Everything runs in its own Modal app (__harbor_probe__) so the phase-3 cleanup
# cannot touch a training run's sandboxes. Sandboxes are watched by polling, because
# an oracle trial finishes in about 20 seconds: a fixed sleep measures nothing.
set -uo pipefail
LANE_ROOT="${LANE_ROOT:-/workspace/verl-uni-agent-harbor-opd-rl}"
REPO_ROOT="${REPO_ROOT:-${LANE_ROOT}/src/uni-agent}"
TASK_DIR="${TASK_DIR:-}"; OUT="${OUT:-${LANE_ROOT}/runs/modal-lifecycle-probe}"
PROBE_APP="${PROBE_APP:-__harbor_probe__}"
SANDBOX_TIMEOUT_SECS="${SANDBOX_TIMEOUT_SECS:-2700}"
while [[ $# -gt 0 ]]; do case "$1" in
  --task) TASK_DIR="$2"; shift;; --out) OUT="$2"; shift;; *) echo "unknown argument: $1" >&2; exit 2;; esac; shift; done
export PATH="${LANE_ROOT}/envs/ua-verl-py312-vllm023-ws1/bin:${PATH}"
PY="${LANE_PY:-${LANE_ROOT}/envs/ua-verl-py312-vllm023-ws1/bin/python}"
[[ -n "${TASK_DIR}" ]] || TASK_DIR=$(ls -d "${LANE_ROOT}"/data-r4/stage1/tasks-train/*terminal-lego* 2>/dev/null | head -1)
[[ -d "${TASK_DIR}" ]] || { echo "no task dir; pass --task" >&2; exit 2; }
mkdir -p "${OUT}"; cd "${REPO_ROOT}"
bash deployment/bootstrap/modal-quota-wait.sh --interval "${QUOTA_INTERVAL:-900}" --max-hours "${QUOTA_MAX_HOURS:-48}" || exit 1

count_sandboxes() { "${PY}" - "${PROBE_APP}" <<'PY'
import sys, modal
try:
    app = modal.App.lookup(sys.argv[1], create_if_missing=False)
    print(sum(1 for _ in modal.Sandbox.list(app_id=app.app_id)))
except Exception:
    print(0)
PY
}
wait_for_sandbox() { # seconds -> echoes the count once non-zero (or after the deadline)
  local deadline=$(( $(date +%s) + $1 )) n=0
  while [[ $(date +%s) -lt ${deadline} ]]; do
    n=$(count_sandboxes); [[ "${n}" != "0" ]] && break; sleep 5
  done
  echo "${n}"
}
start_trial() { # name -> runs in the background of THIS shell so $! is its pid
  harbor trial start --path "${TASK_DIR}" --trial-name "$1" --trials-dir "${OUT}/trials" \
    --agent oracle --env modal --timeout-multiplier 1 \
    --environment-kwarg "app_name=\"${PROBE_APP}\"" \
    --environment-kwarg "sandbox_timeout_secs=${SANDBOX_TIMEOUT_SECS}" > "${OUT}/$1.log" 2>&1 &
}

{
  echo "# Modal sandbox lifecycle probe"
  echo
  echo "- task: $(basename "${TASK_DIR}")   app: ${PROBE_APP}   sandbox_timeout_secs: ${SANDBOX_TIMEOUT_SECS}"
  echo "- started: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo
  echo "## 1. Finished trial should release its sandbox"
  echo "before: $(count_sandboxes) sandbox(es)"
  start_trial probe-normal; pid=$!
  echo "during: $(wait_for_sandbox 180) sandbox(es) (polled until one appeared)"
  wait "${pid}"; echo "trial exit=$?"
  sleep 20; echo "20 s after the trial finished: $(count_sandboxes) sandbox(es)"
  echo
  echo "## 2. Killed client: the leak we paid 358 USD for on 2026-09-17"
  start_trial probe-killed; pid=$!
  n=$(wait_for_sandbox 180); echo "during: ${n} sandbox(es)"
  if [[ "${n}" != "0" ]]; then
    kill -TERM "${pid}" 2>/dev/null; echo "killed the Harbor CLI (pid ${pid})"
    sleep 30; echo "30 s after the kill: $(count_sandboxes) sandbox(es)"
    sleep 60; echo "90 s after the kill: $(count_sandboxes) sandbox(es)"
  else
    kill -TERM "${pid}" 2>/dev/null
    echo "no sandbox observed before the trial ended; leak behaviour not measured"
  fi
  echo
  echo "## 3. Cleanup collects whatever is left (probe app only)"
  HARBOR_MODAL_APP="${PROBE_APP}" bash deployment/bootstrap/modal-sandbox-cleanup.sh --apply --older-than 0
  sleep 20; echo "after cleanup: $(count_sandboxes) sandbox(es)"
  echo
  echo "Finished: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
} 2>&1 | tee "${OUT}/report.md"
