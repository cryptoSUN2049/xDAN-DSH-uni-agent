#!/usr/bin/env bash
# One bounded acceptance run after environment rebuild and an idle GPU.
set -euo pipefail
ROOT=${WORKSPACE_ROOT:-/workspace/verl-uni-agent-harbor-opd-rl}
CODE=${SFT_CODE_ROOT:?set SFT_CODE_ROOT to the deployed immutable snapshot}
export PYTHON_BIN=${PYTHON_BIN:-$ROOT/envs/performance-9b-sft-cu128-rebuild-20260928/bin/python}
export RUN_ID=${RUN_ID:-verl-sft-insight-smoke-20260928}
export RUN_ROOT="$ROOT/runs/performance-9b-sft/$RUN_ID"
QUEUE="$ROOT/runs/sft-observability-queue"
mkdir -p "$QUEUE"
exec 9>"$QUEUE/lock"
flock -n 9 || { echo "another acceptance queue holds the lock" >&2; exit 2; }
[[ ! -e "$RUN_ROOT" ]] || { echo "refusing to reuse existing run: $RUN_ROOT" >&2; exit 2; }
printf '%s\n' "$$" > "$QUEUE/pid"
trap 'code=$?; printf "%s\n" "$code" > "$QUEUE/exit-code"' EXIT

idle_gpu() {
  nvidia-smi --query-gpu=index,memory.used,utilization.gpu --format=csv,noheader,nounits |
    awk -F, '$2 < 512 && $3 < 5 {gsub(/ /,"",$1); print $1; exit}'
}

deadline=$((SECONDS + 86400))
selected=""
while (( SECONDS < deadline )); do
  env_exit="$ROOT/runs/sft-environment-rebuild/exit-code"
  if [[ -f "$env_exit" ]]; then
    [[ "$(cat "$env_exit")" == "0" ]] || { echo "environment rebuild failed; no GPU job launched" >&2; exit 3; }
    candidate=$(idle_gpu)
    if [[ -n "$candidate" ]]; then
      sleep 15
      if [[ "$(idle_gpu)" == "$candidate" ]]; then
        sleep 15
        if [[ "$(idle_gpu)" == "$candidate" ]]; then
          selected="$candidate"
          break
        fi
      fi
    fi
  fi
  date -u '+%Y-%m-%dT%H:%M:%SZ waiting for rebuilt environment and idle GPU'
  sleep 120
done
[[ -n "$selected" ]] || { echo "acceptance queue timed out without launching training" >&2; exit 4; }
export CUDA_VISIBLE_DEVICES="$selected"
export NPROC_PER_NODE=1 TRAIN_STEPS=1 TRAIN_MAX_SAMPLES=2 VAL_MAX_SAMPLES=2
export TRAIN_BATCH_SIZE=2 MAX_LENGTH=4096 SFT_SAVE_FREQ=1 SFT_TEST_FREQ=1
export ATTN_IMPLEMENTATION=flash_attention_2 SFT_INSIGHT_ENABLE=1
export RL_INSIGHT_SERVER_URL=http://127.0.0.1:18080
export SFT_INSIGHT_METRICS_PORT=19093
printf '%s\n' "$selected" > "$QUEUE/gpu-index"
date -u '+%Y-%m-%dT%H:%M:%SZ starting bounded acceptance run'
bash "$CODE/examples/performance_9b/run_verl_sft.sh"
