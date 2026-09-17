#!/usr/bin/env bash
# Block until the Modal workspace can start a sandbox again. Each probe creates
# the smallest possible sandbox (runs `true`, terminates itself) so it costs a
# fraction of a cent; a spend-limit / ResourceExhausted answer means "wait".
#
#   bash deployment/bootstrap/modal-quota-wait.sh [--interval 1800] [--max-hours 48] [--once]
#   ... && <command to run once quota is back>
#
# Exit 0 when a sandbox starts, 1 on --once when it cannot, 2 when max-hours elapse.
set -uo pipefail
INTERVAL=1800; MAX_HOURS=48; ONCE=0
while [[ $# -gt 0 ]]; do case "$1" in
  --interval) INTERVAL="$2"; shift;; --max-hours) MAX_HOURS="$2"; shift;; --once) ONCE=1;; esac; shift; done
PY="${LANE_PY:-/workspace/verl-uni-agent-harbor-opd-rl/envs/ua-verl-py312-vllm023-ws1/bin/python}"
command -v "${PY}" >/dev/null || PY=python3
deadline=$(( $(date +%s) + MAX_HOURS * 3600 ))
while true; do
  out=$("${PY}" - 2>&1 <<'PYEOF'
import modal
app = modal.App.lookup("quota-probe", create_if_missing=True)
try:
    sb = modal.Sandbox.create("true", app=app, timeout=60)
    sb.wait(); sb.terminate()
    print("QUOTA_OK")
except Exception as exc:  # ResourceExhaustedError carries the spend-limit text
    print(f"QUOTA_BLOCKED {type(exc).__name__}: {str(exc)[:160]}")
PYEOF
)
  echo "[modal-quota-wait $(date -u +%Y-%m-%dT%H:%M:%SZ)] ${out##*$'\n'}"
  [[ "${out}" == *QUOTA_OK* ]] && exit 0
  [[ ${ONCE} -eq 1 ]] && exit 1
  [[ $(date +%s) -ge ${deadline} ]] && { echo "[modal-quota-wait] gave up after ${MAX_HOURS}h"; exit 2; }
  sleep "${INTERVAL}"
done
