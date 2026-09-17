#!/usr/bin/env bash
# Run a command on the GPU host fully detached from the SSH session that starts
# it: new session (setsid), no controlling terminal, stdin from /dev/null, all
# output to a log. Closing the laptop / losing the network cannot signal it.
# Chain several steps server-side with && so scheduling never depends on the
# developer machine staying online.
#
#   bash examples/harbor_opd_rl/launch-detached.sh <log-file> '<shell command line>'
#   e.g. launch-detached.sh runs/pipe-r4/driver.log \
#        'PIPE_ROOT=... bash examples/harbor_opd_rl/run_tb21_pipeline.sh && MODEL_PATH=... bash examples/harbor_opd_rl/eval_tb21.sh'
#
# Prints the detached PID and session id. Verify later: ps -o pid,sid,etime,cmd -p <pid>
set -euo pipefail
LOG="${1:?log file}"; CMD="${2:?shell command line}"
mkdir -p "$(dirname "${LOG}")"
RUNNER="$(mktemp "${TMPDIR:-/tmp}/detached-XXXXXX.sh")"
LOGQ=$(printf "%q" "${LOG}"); CMDQ=$(printf "%q" "${CMD}")
cat > "${RUNNER}" <<EOF
#!/usr/bin/env bash
LOG=${LOGQ}
for sig in TERM HUP INT; do trap "echo \"[detached] received SIG\$sig at \$(date -u +%FT%TZ)\" >> \$LOG" \$sig; done
echo "[detached] start \$(date -u +%FT%TZ) pid=\$\$ sid=\$(ps -o sid= -p \$\$ | tr -d ' ') cwd=\$(pwd)" >> "\$LOG"
echo "[detached] cmd: ${CMDQ}" >> "\$LOG"
bash -c ${CMDQ} >> "\$LOG" 2>&1 < /dev/null
rc=\$?
echo "[detached] exit=\$rc \$(date -u +%FT%TZ)" >> "\$LOG"
exit \$rc
EOF
chmod 700 "${RUNNER}"
setsid nohup bash "${RUNNER}" > /dev/null 2>&1 < /dev/null &
PID=$!
disown "${PID}" 2>/dev/null || true
sleep 1
echo "detached pid=${PID} sid=$(ps -o sid= -p "${PID}" 2>/dev/null | tr -d ' ') runner=${RUNNER} log=${LOG}"
