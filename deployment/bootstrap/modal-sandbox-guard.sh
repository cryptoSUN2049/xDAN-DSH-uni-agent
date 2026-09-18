#!/usr/bin/env bash
# Resident guard against leaked Harbor sandboxes.
#
# A trial is bounded by trial_timeout_sec (1800 s), but Harbor gives every Modal
# sandbox a 24 h lifetime and no idle timeout, so any sandbox still alive well past
# that bound is leaked and billing. This loop terminates them.
#
#   bash deployment/bootstrap/modal-sandbox-guard.sh                  # every 15 min, kill > 60 min old
#   bash deployment/bootstrap/modal-sandbox-guard.sh --interval 600 --older-than 45
#   bash deployment/bootstrap/modal-sandbox-guard.sh --dry-run        # report only
#
# Run it detached, one per pod:
#   bash examples/harbor_opd_rl/launch-detached.sh <lane>/runs/modal-guard.log \
#     "bash deployment/bootstrap/modal-sandbox-guard.sh"
set -uo pipefail
INTERVAL=900; OLDER_THAN=60; MODE=--apply
while [[ $# -gt 0 ]]; do case "$1" in
  --interval) INTERVAL="$2"; shift;; --older-than) OLDER_THAN="$2"; shift;;
  --dry-run) MODE="";; *) echo "unknown argument: $1" >&2; exit 2;; esac; shift; done
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
while true; do
  out=$(bash "${HERE}/modal-sandbox-cleanup.sh" ${MODE} --older-than "${OLDER_THAN}" 2>&1)
  # Only log when something existed or the call failed: a quiet guard is a readable log.
  if ! grep -qE "^app .* 0 sandbox\(s\) known" <<<"${out}"; then
    printf '[guard %s]\n%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${out}"
  fi
  sleep "${INTERVAL}"
done
