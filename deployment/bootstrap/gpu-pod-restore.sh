#!/usr/bin/env bash
# Run from the developer machine after a RunPod pod rebuild. One command restores
# everything that lives outside /workspace and is therefore lost on rebuild:
#   - host key for the new port, Modal / wandb / HF credentials under /root
#   - optional local-NVMe cache of the model and uv lane for fast engine start
# then re-proves the lane with the pipeline env stage.
#
#   bash deployment/bootstrap/gpu-pod-restore.sh <ssh-port> [--cache-local]
set -euo pipefail

PORT="${1:?ssh port of the rebuilt pod}"; shift || true
CACHE_LOCAL=0; [[ "${1:-}" == "--cache-local" ]] && CACHE_LOCAL=1
HOST="${GPU_HOST:-root@157.157.221.177}"
KEY="${GPU_SSH_KEY:-$HOME/.ssh/id_ed25519}"
LANE_ROOT="${LANE_ROOT:-/workspace/verl-uni-agent-harbor-opd-rl}"
SSH=(ssh -o ConnectTimeout=30 -o BatchMode=yes -o StrictHostKeyChecking=accept-new -p "${PORT}" -i "${KEY}" "${HOST}")
SCP=(scp -q -o ConnectTimeout=30 -o BatchMode=yes -o StrictHostKeyChecking=accept-new -P "${PORT}" -i "${KEY}")

echo "[restore] probing ${HOST}:${PORT}"
"${SSH[@]}" 'echo "host=$(hostname)"; findmnt -T /workspace -o SOURCE | tail -1; nvidia-smi --query-gpu=name,memory.used --format=csv,noheader'

echo "[restore] credentials"
[[ -f "$HOME/.modal.toml" ]] && "${SCP[@]}" "$HOME/.modal.toml" "${HOST}:/root/.modal.toml"
[[ -f "$HOME/.cache/huggingface/token" ]] && "${SSH[@]}" 'mkdir -p /root/.cache/huggingface' && "${SCP[@]}" "$HOME/.cache/huggingface/token" "${HOST}:/root/.cache/huggingface/token"
: "${WANDB_API_KEY:?export WANDB_API_KEY before running (never stored in the repo)}"
"${SSH[@]}" "umask 077; chmod 600 /root/.modal.toml /root/.cache/huggingface/token 2>/dev/null; export PATH=${LANE_ROOT}/envs/ua-verl-py312-vllm023-ws1/bin:\$PATH; wandb login --relogin '${WANDB_API_KEY}' >/dev/null 2>&1 && echo 'wandb: ok'; modal profile current"

if [[ ${CACHE_LOCAL} -eq 1 ]]; then
  echo "[restore] caching model to local NVMe (/tmp is pod-local, wiped on rebuild)"
  "${SSH[@]}" "mkdir -p /tmp/models && rsync -a /workspace/models/Qwen3-4B-1cfa9a7 /tmp/models/ && du -sh /tmp/models/*"
  echo "[restore] set MODEL_PATH=/tmp/models/Qwen3-4B-1cfa9a7 for this pod's runs"
fi

echo "[restore] source sync (no --delete: the volume may be shared with a running pod)"
bash "$(dirname "${BASH_SOURCE[0]}")/sync-source.sh" "${PORT}"

if [[ -n "${MODELS_TO_FETCH:-}" ]]; then
  echo "[restore] background model downloads: ${MODELS_TO_FETCH}"
  "${SSH[@]}" "export PATH=${LANE_ROOT}/envs/ua-verl-py312-vllm023-ws1/bin:\$PATH; mkdir -p /workspace/models ${LANE_ROOT}/runs/downloads; for m in ${MODELS_TO_FETCH}; do d=/workspace/models/\$(basename \$m); [ -f \$d/config.json ] && { echo \"\$m already present\"; continue; }; nohup python -c \"from huggingface_hub import snapshot_download; print(snapshot_download('\$m', local_dir='\$d', allow_patterns=['*.json','*.safetensors','*.txt','*.py','*.jinja','*.model']))\" > ${LANE_ROOT}/runs/downloads/\$(basename \$m).log 2>&1 < /dev/null & done; sleep 2; ls /workspace/models"
fi

echo "[restore] lane proof (pipeline env stage)"
"${SSH[@]}" "cd ${LANE_ROOT}/src/uni-agent && PIPE_ROOT=${LANE_ROOT}/runs/pod-restore-\$(date -u +%Y%m%dT%H%M) bash examples/harbor_opd_rl/stages/00_env.sh"
echo "[restore] done. New port ${PORT}: update docs/performance-9b/tasks/handoff.md"
