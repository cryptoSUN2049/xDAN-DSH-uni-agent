#!/usr/bin/env bash
# Fixed-version reader diagnostic entry. Does not install packages or run VERL training.
set -euo pipefail

usage() { echo "usage: CANARY=1 $0 prepare | $0 check | $0 run"; }
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then usage; exit 0; fi

: "${PY:?Set PY to the pinned Uni-Agent Python interpreter}"
: "${MODEL:?Set MODEL to the local pinned model directory}"
: "${RUNTIME:?Set RUNTIME to the pinned DSH runtime executable}"
: "${DEVICE:?Set DEVICE to one GPU index or MIG UUID}"
: "${RUN_ROOT:?Set RUN_ROOT to a new persistent /workspace run directory}"
REPO=${REPO:-$(pwd -P)}
REVISION=${MODEL_REVISION:-1cfa9a7208912126459214e8b04321603b3df60c}
export PYTHONPATH="$REPO:$REPO/verl"
export DSH_RUNTIME_MODE=exe

case "${1:-}" in
  prepare)
    canary_args=()
    [[ "${CANARY:-0}" == 1 ]] && canary_args+=(--canary)
    exec "$PY" -m examples.dsh.capabilities.diagnose_core_reader prepare \
      --root "$RUN_ROOT" --model-path "$MODEL" --model-revision "$REVISION" \
      --runtime-executable "$RUNTIME" --runner-python "$PY" \
      --cuda-visible-devices "$DEVICE" "${canary_args[@]}"
    ;;
  check)
    exec "$PY" -m examples.dsh.capabilities.diagnose_core_reader check --manifest "$RUN_ROOT/manifest.json"
    ;;
  run)
    exec "$PY" -m examples.dsh.capabilities.diagnose_core_reader run --manifest "$RUN_ROOT/manifest.json"
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
