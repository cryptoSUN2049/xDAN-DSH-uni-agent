#!/usr/bin/env bash
# Supplement only the two fixed attempt2 infra gaps. Preserve every existing outcome.
set -uo pipefail
lane=/workspace/verl-uni-agent-harbor-opd-rl
root=$lane/runs/full-matrix-20260920
py=$lane/envs/ua-verl-py312-vllm023-ws1/bin/python
cd "$lane/src/uni-agent" || exit 2
export KEEP_GPU_PROCESS=1 CKPT_LOAD_CONTENTS=model CONCURRENCY=16 GPU_MEMORY_UTILIZATION=0.6
rc=0
for label in pipe-s2-opd-step12 pipe-s2-rl-step20; do
  run=pipe-s2-opd
  [[ "$label" == pipe-s2-rl-step20 ]] && run=pipe-s2-rl
  out=$root/$label-supplemented-20260921
  echo "[$(date -u +%FT%TZ)] supplement $label"
  if "$py" examples/harbor_opd_rl/eval_supplement.py \
      --source "$root/$label-attempt2" --output "$out" --gpu 1 \
      --run "$lane/runs/$run" --python "$py"; then
    "$py" examples/harbor_opd_rl/eval_pair_report.py \
      "$lane/runs/eval-v1-base-9b-n4/summary.json" "$out/summary.json" \
      --labels base "$label" --out "$out/pair.json" || rc=1
    "$py" examples/harbor_opd_rl/eval_behavior_report.py \
      "base=$lane/runs/eval-v1-base-9b-n4" "$label=$out" --out "$out/behavior.json" || rc=1
  else
    echo "[$(date -u +%FT%TZ)] supplement failed: $label; preserving evidence"
    rc=1
  fi
  # No global Ray cleanup: GPU0 is evaluating other checkpoints.
done
exit "$rc"
