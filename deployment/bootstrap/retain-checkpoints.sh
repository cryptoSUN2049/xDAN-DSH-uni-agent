#!/usr/bin/env bash
# Post-run checkpoint retention for the shared volume. For every run root under
# RUNS_ROOT (or the single PIPE_ROOT given), keep at most KEEP (default 10) newest
# global_step_* directories per checkpoint set, verify each survivor's model
# file is a readable zip (a checkpoint killed mid-save fails this and is
# removed rather than kept as a silent landmine), and optionally drop optimizer
# state from all but the newest survivor (STRIP_OPTIM=1, saves ~2/3 of the size).
#
#   bash deployment/bootstrap/retain-checkpoints.sh [--apply] [--keep 10] [--strip-optim] [<runs-root-or-pipe-root>]
#
# Default is a dry run that prints the plan. Never touches directories named
# *keep* or the model store. Run it at the end of every pipeline (70_summary.sh
# does) and from cron on the host when the volume is shared.
set -euo pipefail
APPLY=0; KEEP=10; STRIP=0; TARGET="${RUNS_ROOT:-/workspace/verl-uni-agent-harbor-opd-rl/runs}"
while [[ $# -gt 0 ]]; do case "$1" in
  --apply) APPLY=1;; --keep) KEEP="$2"; shift;; --strip-optim) STRIP=1;; *) TARGET="$1";; esac; shift; done
PY="${LANE_PY:-/workspace/verl-uni-agent-harbor-opd-rl/envs/ua-verl-py312-vllm023-ws1/bin/python}"
command -v "${PY}" >/dev/null || PY=python3

zip_ok() { "${PY}" - "$1" <<'PY'
import sys, zipfile
try:
    with zipfile.ZipFile(sys.argv[1]) as z: bad = z.testzip()
    sys.exit(0 if bad is None else 1)
except Exception:
    sys.exit(1)
PY
}
size_of() { du -sh "$1" 2>/dev/null | cut -f1; }

echo "[retain] target=${TARGET} keep=${KEEP} strip_optim=${STRIP} apply=${APPLY}"
# checkpoint sets = parents that contain global_step_* dirs
find "${TARGET}" -maxdepth 8 -type d -name 'global_step_*' 2>/dev/null | xargs -r -n1 dirname | sort -u | while read -r set; do
  [[ "${set}" == *keep* ]] && continue
  mapfile -t steps < <(ls -d "${set}"/global_step_* 2>/dev/null | sort -t_ -k3 -n)
  [[ ${#steps[@]} -gt 0 ]] || continue
  echo "== ${set#${TARGET}/} (${#steps[@]} checkpoints)"
  # 1) integrity: a truncated model file means the step is unusable
  good=()
  for d in "${steps[@]}"; do
    f="${d}/actor/model_world_size_1_rank_0.pt"; [[ -f "${f}" ]] || f="${d}/model_world_size_1_rank_0.pt"
    if [[ -f "${f}" ]] && zip_ok "${f}"; then good+=("${d}"); else
      echo "   corrupt/incomplete: $(basename "${d}") -> remove"
      [[ ${APPLY} -eq 1 ]] && rm -rf "${d}"
    fi
  done
  # 2) keep newest KEEP good ones
  n=${#good[@]}; drop=$(( n > KEEP ? n - KEEP : 0 ))
  for ((i=0; i<drop; i++)); do
    echo "   remove $(basename "${good[$i]}") ($(size_of "${good[$i]}"))"
    [[ ${APPLY} -eq 1 ]] && rm -rf "${good[$i]}"
  done
  # 3) strip optimizer state from all survivors except the newest
  if [[ ${STRIP} -eq 1 && $n -gt 1 ]]; then
    for ((i=drop; i<n-1; i++)); do
      for o in "${good[$i]}"/actor/optim_*.pt "${good[$i]}"/optim_*.pt; do
        [[ -f "${o}" ]] || continue
        echo "   strip optimizer: $(basename "${good[$i]}")/$(basename "${o}") ($(size_of "${o}"))"
        [[ ${APPLY} -eq 1 ]] && rm -f "${o}" && touch "${good[$i]}/OPTIMIZER_STRIPPED"
      done
    done
  fi
  echo "   keep: $(for ((i=drop; i<n; i++)); do basename "${good[$i]}"; done | tr '\n' ' ')"
done
[[ ${APPLY} -eq 1 ]] || echo "[retain] dry run; add --apply to execute"
