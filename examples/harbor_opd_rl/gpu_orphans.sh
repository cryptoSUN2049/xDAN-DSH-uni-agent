#!/usr/bin/env bash
# Print the GPU compute PIDs that run_opd_round.sh may treat as orphans of an earlier run
# (it only asks when no VERL trainer is alive): every process holding a GPU except those
# started with KEEP_GPU_PROCESS=1 in their environment, e.g. another session's standalone
# `vllm serve` on the GPU a one-GPU training run leaves free (docs/.../gpu-schedule.md).
# Children inherit the variable, so a vLLM EngineCore is kept with its server.
#
#   bash examples/harbor_opd_rl/gpu_orphans.sh        # one PID per line; kept PIDs go to stderr
#
# PIDS (space separated) and PROC_ROOT replace nvidia-smi and /proc in tests. A PID whose
# environment cannot be read counts as an orphan, as before this filter existed.
set -uo pipefail
PROC_ROOT="${PROC_ROOT:-/proc}"
pids="${PIDS-$(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null | tr -d ' ')}"
for pid in ${pids}; do
  if tr '\0' '\n' < "${PROC_ROOT}/${pid}/environ" 2>/dev/null | grep -qx 'KEEP_GPU_PROCESS=1'; then
    echo "keep ${pid} (KEEP_GPU_PROCESS=1)" >&2
    continue
  fi
  echo "${pid}"
done
