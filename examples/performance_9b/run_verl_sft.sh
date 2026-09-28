#!/usr/bin/env bash
set -euo pipefail

# Native VERL SFT entrypoint. Run this script with nohup on a GPU pod after
# the workspace uv lane has passed the activation proof in uv-runbook.md.
ROOT=${WORKSPACE_ROOT:-/workspace/verl-uni-agent-harbor-opd-rl}
PYTHON_BIN=${PYTHON_BIN:-$ROOT/envs/ua-verl-py312-vllm023-ws1/bin/python}
MODEL_PATH=${MODEL_PATH:-/workspace/models/Qwen3.5-9B}
DATA_ROOT=${DATA_ROOT:-/workspace/apus-data-cleaning/reports/verl-sft-v1}
RUN_ID=${RUN_ID:-sft-$(date -u +%Y%m%dT%H%M%SZ)}
RUN_ROOT=${RUN_ROOT:-$ROOT/runs/performance-9b-sft/$RUN_ID}
TRAIN_STEPS=${TRAIN_STEPS:-1}
TRAIN_MAX_SAMPLES=${TRAIN_MAX_SAMPLES:--1}
VAL_MAX_SAMPLES=${VAL_MAX_SAMPLES:--1}
MAX_LENGTH=${MAX_LENGTH:-16384}
NPROC_PER_NODE=${NPROC_PER_NODE:-2}
TRAIN_BATCH_SIZE=${TRAIN_BATCH_SIZE:-$NPROC_PER_NODE}
LOGGER_BACKENDS=${LOGGER_BACKENDS:-console,file,wandb}
ATTN_IMPLEMENTATION=${ATTN_IMPLEMENTATION:-sdpa}
[[ "$NPROC_PER_NODE" =~ ^[1-9][0-9]*$ && "$TRAIN_BATCH_SIZE" =~ ^[1-9][0-9]*$ ]] || {
  echo "GPU count and global batch size must be positive integers" >&2; exit 2
}
(( TRAIN_BATCH_SIZE % NPROC_PER_NODE == 0 )) || {
  echo "global batch size must be divisible by the data-parallel GPU count" >&2; exit 2
}

[[ -x "$PYTHON_BIN" ]] || { echo "missing VERL python: $PYTHON_BIN" >&2; exit 2; }
[[ -d "$MODEL_PATH" ]] || { echo "missing model: $MODEL_PATH" >&2; exit 2; }
[[ -f "$DATA_ROOT/train.parquet" && -f "$DATA_ROOT/validation.parquet" ]] || {
  echo "split Parquet files are missing under $DATA_ROOT" >&2; exit 2
}
[[ "$RUN_ROOT" = "$ROOT/runs/"* ]] || { echo "RUN_ROOT must be under workspace runs" >&2; exit 2; }
[[ ! -e "$RUN_ROOT" ]] || { echo "RUN_ROOT already exists: $RUN_ROOT" >&2; exit 2; }

mkdir -p "$RUN_ROOT"
export WANDB_DIR="$RUN_ROOT/wandb"
export VERL_FILE_LOGGER_PATH="$RUN_ROOT/metrics.jsonl"
mkdir -p "$WANDB_DIR"
export PYTHONPATH="$ROOT/src/uni-agent:$ROOT/src/uni-agent/verl:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONNOUSERSITE=1
export RAY_ENABLE_UV_RUN_RUNTIME_ENV=0
export WANDB_PROJECT=${WANDB_PROJECT:-xDAN-performance-9b}
export WANDB_RUN_GROUP=${WANDB_RUN_GROUP:-verl-sft}
SFT_INSIGHT_ENABLE=${SFT_INSIGHT_ENABLE:-${VERL_RL_INSIGHT_ENABLE:-0}}
# Native rl_insight assumes Ray in the training process. The CPU sidecar owns
# its own Ray runtime instead; never attach the torchrun ranks to that runtime.
if [[ "$SFT_INSIGHT_ENABLE" == "1" ]]; then
  : "${RL_INSIGHT_SERVER_URL:?set RL_INSIGHT_SERVER_URL for the SFT sidecar}"
  [[ ",$LOGGER_BACKENDS," != *,rl_insight,* ]] || {
    echo "use the SFT sidecar, not the native Ray logger, with torchrun" >&2; exit 2
  }
  export VERL_RL_INSIGHT_ENABLE=0
fi
LOGGER_SPEC="[${LOGGER_BACKENDS}]"

COMMAND=(
  "$PYTHON_BIN" -m torch.distributed.run --standalone --nnodes=1
  --nproc_per_node="$NPROC_PER_NODE" -m verl.trainer.sft_trainer
  "data.train_files=$DATA_ROOT/train.parquet"
  "data.val_files=$DATA_ROOT/validation.parquet"
  "data.custom_cls.path=pkg://examples.performance_9b.verl_sft_dataset"
  "data.custom_cls.name=ApusMultiTurnSFTDataset"
  data.messages_key=messages data.tools_key=tools
  data.enable_thinking_key=enable_thinking data.pad_mode=no_padding
  data.truncation=left "data.max_length=$MAX_LENGTH"
  "data.max_token_len_per_gpu=$MAX_LENGTH"
  "data.train_max_samples=$TRAIN_MAX_SAMPLES"
  "data.val_max_samples=$VAL_MAX_SAMPLES"
  "data.train_batch_size=$TRAIN_BATCH_SIZE" data.micro_batch_size_per_gpu=1
  data.use_dynamic_bsz=True data.num_workers=0
  "model.path=$MODEL_PATH" "model.tokenizer_path=$MODEL_PATH"
  model.use_remove_padding=True model.enable_gradient_checkpointing=True
  model.lora_rank=16 model.lora_alpha=16 model.target_modules=all-linear
  engine=fsdp engine.strategy=fsdp engine.ulysses_sequence_parallel_size=1
  "+model.override_config.attn_implementation=$ATTN_IMPLEMENTATION"
  engine.model_dtype=bfloat16 engine.dtype=bfloat16 engine.use_torch_compile=False
  "optim.lr=${SFT_LR:-1e-5}"
  checkpoint.save_contents='[model,optimizer,extra]'
  "trainer.default_local_dir=$RUN_ROOT/checkpoints"
  "trainer.project_name=$WANDB_PROJECT" "trainer.experiment_name=$RUN_ID"
  trainer.resume_mode=disable "trainer.logger=$LOGGER_SPEC"
  "trainer.save_freq=${SFT_SAVE_FREQ:-1}" "trainer.test_freq=${SFT_TEST_FREQ:-1}"
  "trainer.total_training_steps=$TRAIN_STEPS"
  "trainer.n_gpus_per_node=$NPROC_PER_NODE"
)

printf '%q ' "${COMMAND[@]}" > "$RUN_ROOT/command.sh"
printf '\n' >> "$RUN_ROOT/command.sh"
date -u +%Y-%m-%dT%H:%M:%SZ > "$RUN_ROOT/start.utc"
SIDECAR_PID=""
cleanup_sidecar() {
  if [[ -n "$SIDECAR_PID" ]] && kill -0 "$SIDECAR_PID" 2>/dev/null; then
    kill "$SIDECAR_PID"
    wait "$SIDECAR_PID" || true
  fi
}
trap cleanup_sidecar EXIT
if [[ "$SFT_INSIGHT_ENABLE" == "1" ]]; then
  touch "$VERL_FILE_LOGGER_PATH"
  RAY_SUFFIX=$("$PYTHON_BIN" -c 'import hashlib,sys; print(hashlib.sha256(sys.argv[1].encode()).hexdigest()[:12])' "$RUN_ROOT")
  INSIGHT_COMMAND=("$PYTHON_BIN" "$(dirname -- "${BASH_SOURCE[0]}")/sft_insight_sidecar.py"
    --metrics "$VERL_FILE_LOGGER_PATH" --state "$RUN_ROOT/insight-cursor.json"
    --status "$RUN_ROOT/insight-status.json" --exit-code "$RUN_ROOT/exit-code"
    --project "$WANDB_PROJECT" --experiment "$RUN_ID"
    --server-url "$RL_INSIGHT_SERVER_URL"
    --metrics-port "${SFT_INSIGHT_METRICS_PORT:-19092}"
    --ray-temp-dir "/workspace/ri-$RAY_SUFFIX")
  printf '%q ' "${INSIGHT_COMMAND[@]}" > "$RUN_ROOT/insight-command.sh"
  printf '\n' >> "$RUN_ROOT/insight-command.sh"
  "${INSIGHT_COMMAND[@]}" > "$RUN_ROOT/insight.log" 2>&1 &
  SIDECAR_PID=$!
  printf '%s\n' "$SIDECAR_PID" > "$RUN_ROOT/insight.pid"
  READY=0
  for ((attempt=0; attempt<180; attempt++)); do
    kill -0 "$SIDECAR_PID" 2>/dev/null || break
    if "$PYTHON_BIN" -c 'import json,sys,pathlib; p=pathlib.Path(sys.argv[1]); sys.exit(0 if p.exists() and json.loads(p.read_text()).get("status")=="running" else 1)' "$RUN_ROOT/insight-status.json"; then
      READY=1
      break
    fi
    sleep 1
  done
  if [[ "$READY" != "1" ]]; then
    kill "$SIDECAR_PID" 2>/dev/null || true
    insight_code=0
    wait "$SIDECAR_PID" || insight_code=$?
    printf '%s\n' "$insight_code" > "$RUN_ROOT/insight-exit-code"
    SIDECAR_PID=""
    echo "SFT insight startup failed; see $RUN_ROOT/insight.log" >&2
    exit 3
  fi
fi
set +e
"${COMMAND[@]}" 2>&1 | tee "$RUN_ROOT/train.log"
code=${PIPESTATUS[0]}
printf '%s\n' "$code" > "$RUN_ROOT/exit-code"
if [[ -n "$SIDECAR_PID" ]]; then
  wait "$SIDECAR_PID"
  insight_code=$?
  printf '%s\n' "$insight_code" > "$RUN_ROOT/insight-exit-code"
  SIDECAR_PID=""
  if [[ "$code" == "0" && "$insight_code" != "0" ]]; then
    echo "training completed, but requested insight forwarding failed" >&2
    exit 3
  fi
fi
exit "$code"
