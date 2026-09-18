#!/usr/bin/env bash
# Put this checkout's HEAD onto the GPU host at $LANE_ROOT/src/uni-agent and
# record a source manifest. Run from the developer machine.
#
#   bash deployment/bootstrap/sync-source.sh <ssh-port> [--git|--rsync] [--delete]
#
# --git (default): git fetch/checkout of the exact HEAD SHA on the host. First
#   time it clones into src/uni-agent.git-checkout via deployment/bootstrap/checkout.sh
#   (token only passed through the environment of that one command; never stored),
#   inits the verl submodule, and swaps it into place when no pipeline is running.
# --rsync: copy the working tree (also carries uncommitted changes). --delete
#   removes remote files missing locally; never use it while another pod sharing
#   the same /workspace volume runs a pipeline.
set -euo pipefail
PORT="${1:?ssh port}"; shift || true
MODE=git; DELETE=""
for a in "$@"; do case "$a" in --git) MODE=git;; --rsync) MODE=rsync;; --delete) DELETE="--delete";; esac; done
HOST="${GPU_HOST:-root@157.157.221.177}"
KEY="${GPU_SSH_KEY:-$HOME/.ssh/id_ed25519}"
LANE_ROOT="${LANE_ROOT:-/workspace/verl-uni-agent-harbor-opd-rl}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SHA="$(git -C "${REPO_ROOT}" rev-parse HEAD)"
BRANCH="$(git -C "${REPO_ROOT}" rev-parse --abbrev-ref HEAD)"
DIRTY=$([[ -n "$(git -C "${REPO_ROOT}" status --porcelain)" ]] && echo true || echo false)
SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=30 -o StrictHostKeyChecking=accept-new -p "${PORT}" -i "${KEY}")
SRC="${LANE_ROOT}/src/uni-agent"

# Upstream VERL fixes (patches/verl/*.patch) must be re-applied after every sync.
apply_patches() {
  ssh "${SSH_OPTS[@]}" "${HOST}" "bash ${SRC}/deployment/bootstrap/apply-verl-patches.sh ${SRC}"
}

manifest() {
  ssh "${SSH_OPTS[@]}" "${HOST}" "printf '{\"sha\":\"%s\",\"branch\":\"%s\",\"mode\":\"%s\",\"dirty\":%s,\"utc\":\"%s\"}\n' '${SHA}' '${BRANCH}' '$1' ${DIRTY} '$(date -u +%Y%m%dT%H%M%SZ)' > ${LANE_ROOT}/runs/source-manifest-${SHA:0:7}.json; cat ${LANE_ROOT}/runs/source-manifest-${SHA:0:7}.json"
}

if [[ "${MODE}" == rsync ]]; then
  echo "[sync] rsync ${SHA:0:7} (dirty=${DIRTY}) -> ${HOST}:${SRC} ${DELETE}"
  rsync -rltz ${DELETE} --exclude .git --exclude '__pycache__' --exclude .Codex --exclude '*.egg-info' \
    --exclude .pytest_cache --exclude .ruff_cache --exclude wandb -e "ssh ${SSH_OPTS[*]}" "${REPO_ROOT}/" "${HOST}:${SRC}/"
  apply_patches; manifest rsync; exit 0
fi

# --git
[[ "${DIRTY}" == false ]] || { echo "[sync] working tree is dirty; commit and push first (or use --rsync)" >&2; exit 2; }
git -C "${REPO_ROOT}" fetch -q origin "${BRANCH}"
[[ "$(git -C "${REPO_ROOT}" rev-parse "origin/${BRANCH}")" == "${SHA}" ]] || { echo "[sync] HEAD is not pushed to origin/${BRANCH}; push first" >&2; exit 2; }
TOKEN="${GH_TOKEN:-${GITHUB_TOKEN:-}}"
[[ -n "${TOKEN}" ]] || { echo "[sync] export GH_TOKEN (private repo) or set up a deploy key on the host" >&2; exit 2; }

if ssh "${SSH_OPTS[@]}" "${HOST}" "[ -d ${SRC}/.git ]"; then
  echo "[sync] git checkout ${SHA:0:7} in existing clone"
  ssh "${SSH_OPTS[@]}" "${HOST}" "cd ${SRC} && GIT_ASKPASS=\$(mktemp) && printf '#!/bin/sh\ncase \"\$1\" in *Username*) echo x;; *) echo ${TOKEN};; esac\n' > \$GIT_ASKPASS && chmod 700 \$GIT_ASKPASS && GIT_ASKPASS=\$GIT_ASKPASS GIT_TERMINAL_PROMPT=0 git fetch -q origin ${BRANCH} && rm -f \$GIT_ASKPASS && git checkout -q --detach ${SHA} && git submodule update -q --init verl && git rev-parse HEAD && git -C verl rev-parse HEAD"
else
  echo "[sync] first clone into ${SRC}.git-checkout (existing rsync copy kept until swap)"
  ssh "${SSH_OPTS[@]}" "${HOST}" "D=${SRC}.git-checkout; rm -rf \$D; mkdir -p ${LANE_ROOT}/src; cd ${SRC} 2>/dev/null || cd /; GH_TOKEN='${TOKEN}' GIT_TERMINAL_PROMPT=0 bash ${SRC}/deployment/bootstrap/checkout.sh ${SHA} \$D >/dev/null && cd \$D && git submodule update -q --init verl && git rev-parse HEAD && git -C verl rev-parse HEAD"
  if ssh "${SSH_OPTS[@]}" "${HOST}" "ps -eo cmd | grep -qE '^[^ ]*python -m verl\.trainer\.main_ppo|^bash examples/harbor_opd_rl/run_tb21_pipeline.sh'"; then
    echo "[sync] a pipeline is running; NOT swapping. Later: mv ${SRC} ${SRC}.rsync-bak && mv ${SRC}.git-checkout ${SRC}"
  else
    ssh "${SSH_OPTS[@]}" "${HOST}" "mv ${SRC} ${SRC}.rsync-bak-\$(date -u +%Y%m%dT%H%M) && mv ${SRC}.git-checkout ${SRC} && echo '[sync] swapped git checkout into place'"
  fi
fi
apply_patches
manifest git
