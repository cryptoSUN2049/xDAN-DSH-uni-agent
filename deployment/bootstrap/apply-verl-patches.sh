#!/usr/bin/env bash
# Apply this repo's fixes for upstream VERL bugs to the verl/ tree.
#
#   bash deployment/bootstrap/apply-verl-patches.sh [REPO_ROOT]
#
# verl/ is the upstream verl-project/verl submodule, which we cannot push to, so each
# fix lives as a patch under patches/verl/ and is applied after every code sync (the
# rsync copy and the git checkout both arrive unpatched). Idempotent: a patch that is
# already applied is skipped; a patch that no longer applies fails loudly, because a
# silently missing fix is how a run crashes hours later.
set -euo pipefail
ROOT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
VERL="${ROOT}/verl"
[[ -d "${VERL}/verl" ]] || { echo "[verl-patches] no verl tree at ${VERL}" >&2; exit 2; }
shopt -s nullglob
applied=0; present=0
for patch in "${ROOT}"/patches/verl/*.patch; do
  name="$(basename "${patch}")"
  if (cd "${VERL}" && git apply --reverse --check "${patch}" 2>/dev/null); then
    echo "[verl-patches] already applied: ${name}"; present=$((present + 1)); continue
  fi
  if ! (cd "${VERL}" && git apply --check "${patch}"); then
    echo "[verl-patches] ${name} does not apply to ${VERL}; refusing to continue" >&2; exit 1
  fi
  (cd "${VERL}" && git apply "${patch}")
  echo "[verl-patches] applied: ${name}"; applied=$((applied + 1))
done
echo "[verl-patches] done: applied=${applied} already=${present}"
