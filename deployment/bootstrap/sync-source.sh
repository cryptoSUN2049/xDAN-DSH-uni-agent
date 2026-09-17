#!/usr/bin/env bash
# Sync this checkout (HEAD working tree) to the GPU host's /workspace source copy
# and record a source manifest. Run from the developer machine.
#
#   bash deployment/bootstrap/sync-source.sh <ssh-port> [--delete]
#
# --delete removes remote files that no longer exist locally. Do NOT use it
# while another pod sharing the same /workspace volume is running a pipeline.
set -euo pipefail
PORT="${1:?ssh port}"; shift || true
DELETE=""; [[ "${1:-}" == "--delete" ]] && DELETE="--delete"
HOST="${GPU_HOST:-root@157.157.221.177}"
KEY="${GPU_SSH_KEY:-$HOME/.ssh/id_ed25519}"
LANE_ROOT="${LANE_ROOT:-/workspace/verl-uni-agent-harbor-opd-rl}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SHA="$(git -C "${REPO_ROOT}" rev-parse HEAD)"
SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=30 -o StrictHostKeyChecking=accept-new -p "${PORT}" -i "${KEY}")

echo "[sync] ${SHA:0:7} -> ${HOST}:${LANE_ROOT}/src/uni-agent ${DELETE}"
rsync -rltz ${DELETE} --exclude .git --exclude '__pycache__' --exclude .Codex --exclude '*.egg-info' \
  --exclude .pytest_cache --exclude .ruff_cache --exclude wandb \
  -e "ssh ${SSH_OPTS[*]}" "${REPO_ROOT}/" "${HOST}:${LANE_ROOT}/src/uni-agent/"
ssh "${SSH_OPTS[@]}" "${HOST}" "printf '{\"sha\":\"%s\",\"utc\":\"%s\",\"dirty\":%s}\n' '${SHA}' '$(date -u +%Y%m%dT%H%M%SZ)' $([[ -n "$(git -C "${REPO_ROOT}" status --porcelain)" ]] && echo true || echo false) > ${LANE_ROOT}/runs/source-manifest-${SHA:0:7}.json; cat ${LANE_ROOT}/runs/source-manifest-${SHA:0:7}.json"
