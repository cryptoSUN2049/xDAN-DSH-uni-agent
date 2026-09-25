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
  engine.model_dtype=bfloat16 engine.dtype=bfloat16 engine.use_torch_compile=False
  "optim.lr=${SFT_LR:-1e-5}"
  checkpoint.save_contents='[model,optimizer,extra]'
  "trainer.default_local_dir=$RUN_ROOT/checkpoints"
  "trainer.project_name=$WANDB_PROJECT" "trainer.experiment_name=$RUN_ID"
  trainer.resume_mode=disable 'trainer.logger=[console,file,wandb]'
  "trainer.save_freq=${SFT_SAVE_FREQ:-1}" "trainer.test_freq=${SFT_TEST_FREQ:-1}"
  "trainer.total_training_steps=$TRAIN_STEPS"
  "trainer.n_gpus_per_node=$NPROC_PER_NODE"
)

printf '%q ' "${COMMAND[@]}" > "$RUN_ROOT/command.sh"
printf '\n' >> "$RUN_ROOT/command.sh"
date -u +%Y-%m-%dT%H:%M:%SZ > "$RUN_ROOT/start.utc"
set +e
"${COMMAND[@]}" 2>&1 | tee "$RUN_ROOT/train.log"
code=${PIPESTATUS[0]}
printf '%s\n' "$code" > "$RUN_ROOT/exit-code"
exit "$code"
