#!/usr/bin/env bash
# One fixed-base LoRA SFT run using native VERL. Input data must pass provenance/mask checks.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "${REPO_ROOT}"
: "${MODEL_PATH:?fixed Qwen3-4B snapshot required}"
: "${SFT_TRAIN:?validated decision train parquet required}"
: "${SFT_DEV:?validated public dev parquet required}"
: "${SFT_RUN:?new run directory required}"
: "${SFT_MAX_LENGTH:?measured token capacity required}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
SFT_STEPS="${SFT_STEPS:-1}"
SFT_TIMEOUT="${SFT_TIMEOUT:-1800}"
SFT_SAVE_FREQ="${SFT_SAVE_FREQ:-1}"
SFT_TEST_FREQ="${SFT_TEST_FREQ:-1}"
for frequency in "${SFT_SAVE_FREQ}" "${SFT_TEST_FREQ}"; do
  [[ "${frequency}" =~ ^-?[1-9][0-9]*$ ]] || { echo 'SFT frequencies must be nonzero integers' >&2; exit 2; }
done
for value in "${SFT_STEPS}" "${SFT_MAX_LENGTH}" "${SFT_TIMEOUT}"; do
  [[ "${value}" =~ ^[1-9][0-9]*$ ]] || { echo 'SFT bounds must be positive integers' >&2; exit 2; }
done
(( SFT_STEPS <= 64 && SFT_MAX_LENGTH <= 32768 && SFT_TIMEOUT <= 3600 )) || exit 2
COMMAND=(
  "${PYTHON_BIN}" -m torch.distributed.run --standalone --nnodes=1 --nproc_per_node=1
  -m verl.trainer.sft_trainer
  "data.train_files=${SFT_TRAIN}" "data.val_files=${SFT_DEV}"
  data.custom_cls.path=pkg://examples.dsh.capability_tasks.log_tool.sft_dataset
  data.custom_cls.name=DshDecisionSFTDataset data.pad_mode=no_padding data.truncation=error
  "data.max_length=${SFT_MAX_LENGTH}" "data.max_token_len_per_gpu=${SFT_MAX_LENGTH}"
  data.train_batch_size=1 data.micro_batch_size_per_gpu=1 data.use_dynamic_bsz=True data.num_workers=0
  ++data.apply_chat_template_kwargs.enable_thinking=False
  "model.path=${MODEL_PATH}" "model.tokenizer_path=${MODEL_PATH}"
  model.lora_rank=16 model.lora_alpha=16 model.target_modules=all-linear
  model.enable_gradient_checkpointing=True model.use_remove_padding=True
  ++model.override_config.attn_implementation=sdpa
  engine=fsdp engine.strategy=fsdp engine.ulysses_sequence_parallel_size=1
  engine.model_dtype=bfloat16 engine.dtype=bfloat16 engine.use_torch_compile=False
  "optim.lr=${SFT_LR:-1e-4}" checkpoint.save_contents='[model,optimizer,extra]'
  ++checkpoint.save_lora_only=False
  "trainer.default_local_dir=${SFT_RUN}" trainer.resume_mode=disable trainer.logger='[console]'
  "trainer.save_freq=${SFT_SAVE_FREQ:-1}" "trainer.test_freq=${SFT_TEST_FREQ:-1}"
  "trainer.total_training_steps=${SFT_STEPS}"
)
if [[ "${PRINT_COMMAND:-0}" == 1 ]]; then
  printf '%q ' "${COMMAND[@]}" "$@"
  printf '\n'
  exit 0
fi
[[ "$(git -C verl rev-parse HEAD)" == fefb080262e1c015a0ea05f958822a6a512dc795 ]] || {
  echo 'VERL differs from the tested SFT pin' >&2; exit 2;
}
[[ -f "${SFT_TRAIN}" && -f "${SFT_DEV}" && -d "${MODEL_PATH}" ]] || exit 2
[[ ! -e "${SFT_RUN}" ]] || { echo 'SFT_RUN must be new' >&2; exit 2; }
umask 077
mkdir -p "${SFT_RUN}"
"${PYTHON_BIN}" - "${SFT_RUN}/command.json" "${COMMAND[@]}" "$@" <<'PY'
import json,sys
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps(sys.argv[2:], indent=2)+"\n")
PY
export PYTHONPATH="${REPO_ROOT}:${REPO_ROOT}/verl${PYTHONPATH:+:${PYTHONPATH}}"
set +e
timeout --signal=TERM --kill-after=30s "${SFT_TIMEOUT}s" "${COMMAND[@]}" "$@" 2>&1 | tee "${SFT_RUN}/train.log"
code=${PIPESTATUS[0]}
printf '%s\n' "${code}" > "${SFT_RUN}/exit-code"
exit "${code}"
