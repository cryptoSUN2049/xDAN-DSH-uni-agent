#!/usr/bin/env bash
# Terminate leaked Harbor sandboxes on Modal.
#
# Harbor creates every sandbox with modal's sandbox_timeout_secs=86400 (24 h) and no
# idle timeout, and the Harbor CLI does not clean up when its process is killed. So
# every trainer we stop mid-run leaves its sandboxes billing CPU and memory for up to
# a day: on 2026-09-17 the __harbor__ app cost 358 USD, with roughly fourteen times
# more billed sandbox hours than the trials actually ran.
#
#   bash deployment/bootstrap/modal-sandbox-cleanup.sh                 # list only
#   bash deployment/bootstrap/modal-sandbox-cleanup.sh --apply         # terminate
#   bash deployment/bootstrap/modal-sandbox-cleanup.sh --apply --older-than 30
#
# --older-than MIN (default 60) protects sandboxes of a run that is still going: only
# sandboxes started more than MIN minutes ago are terminated. Always run this after
# killing a training run, and before starting a new one on an idle pod.
set -uo pipefail
APPLY=0; OLDER_THAN=60; APP_NAME="${HARBOR_MODAL_APP:-__harbor__}"
while [[ $# -gt 0 ]]; do case "$1" in
  --apply) APPLY=1;; --older-than) OLDER_THAN="$2"; shift;; --app) APP_NAME="$2"; shift;;
  *) echo "unknown argument: $1" >&2; exit 2;; esac; shift; done
PY="${LANE_PY:-/workspace/verl-uni-agent-harbor-opd-rl/envs/ua-verl-py312-vllm023-ws1/bin/python}"
command -v "${PY}" >/dev/null || PY=python3

"${PY}" - "${APP_NAME}" "${OLDER_THAN}" "${APPLY}" <<'PY'
import sys, time
import modal

app_name, older_than_min, apply_now = sys.argv[1], float(sys.argv[2]), sys.argv[3] == "1"
cutoff = time.time() - older_than_min * 60
try:
    app = modal.App.lookup(app_name, create_if_missing=False)
except Exception as exc:
    print(f"app {app_name!r} not found ({type(exc).__name__}); nothing to clean")
    raise SystemExit(0)

sandboxes = list(modal.Sandbox.list(app_id=app.app_id))
print(f"app {app_name} ({app.app_id}): {len(sandboxes)} sandbox(es) known to Modal")
terminated = kept = 0
for sb in sandboxes:
    created = getattr(sb, "created_at", None)
    created_s = created.timestamp() if hasattr(created, "timestamp") else created
    age_min = (time.time() - created_s) / 60 if isinstance(created_s, (int, float)) else None
    old_enough = age_min is None or age_min >= older_than_min
    label = f"{sb.object_id} age={age_min:.0f}min" if age_min is not None else f"{sb.object_id} age=unknown"
    if not old_enough:
        kept += 1
        print(f"  keep    {label} (younger than {older_than_min:.0f} min)")
        continue
    if apply_now:
        try:
            sb.terminate()
            terminated += 1
            print(f"  stopped {label}")
        except Exception as exc:
            print(f"  failed  {label}: {type(exc).__name__}: {exc}")
    else:
        terminated += 1
        print(f"  would stop {label}")
print(f"{'terminated' if apply_now else 'would terminate'} {terminated}, kept {kept}")
if not apply_now:
    print("dry run; add --apply to terminate")
PY
