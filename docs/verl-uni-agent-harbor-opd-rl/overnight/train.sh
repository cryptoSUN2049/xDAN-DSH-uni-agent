#!/usr/bin/env bash
# Native single-turn VERL OPD: one frozen teacher, multiple prompt domains.
set -euo pipefail
ROOT=${ROOT:-/workspace/verl-uni-agent-harbor-opd-rl}
SOURCE="$ROOT/src/uni-agent"
DATA=${DATA:-$ROOT/data-overnight-opd-20260924-v2}
RUN=${RUN:-$ROOT/runs/overnight-opd-20260924}
REWARD_FILE=${REWARD_FILE:-$DATA/reward.py}
STUDENT=${STUDENT:-/workspace/models/Qwen3.5-9B}
TEACHER=${TEACHER:-/workspace/models/Qwen3.8-27B}
STEPS=${STEPS:-16}
RESPONSE=${RESPONSE:-2048}
PROMPT=${PROMPT:-2048}
source "$ROOT/envs/ua-verl-py312-vllm023-ws1/bin/activate"
export VIRTUAL_ENV="$ROOT/envs/ua-verl-py312-vllm023-ws1"
export UV_PROJECT_ENVIRONMENT="$VIRTUAL_ENV"
export PYTHONNOUSERSITE=1
export PATH="$VIRTUAL_ENV/bin:$PATH"
export PYTHONPATH="$SOURCE:$SOURCE/verl${PYTHONPATH:+:$PYTHONPATH}"
export CUDA_VISIBLE_DEVICES=0,1
export TOKENIZERS_PARALLELISM=false
export VLLM_USE_FLASHINFER_SAMPLER=0
export WANDB_MODE=${WANDB_MODE:-offline}
export WANDB_DIR="$RUN"
cd "$SOURCE/verl"
python -c 'import os, sys; assert sys.prefix == os.environ["VIRTUAL_ENV"], (sys.prefix, os.environ["VIRTUAL_ENV"]); print("VERL environment verified:", sys.executable, sys.prefix, flush=True)'
ARGS=(
  algorithm.adv_estimator=grpo algorithm.use_kl_in_reward=False
  data.train_files="$DATA/train.parquet" data.val_files="$DATA/val.parquet"
  data.train_batch_size=8 data.val_batch_size=8 data.shuffle=True data.seed=20260924
  data.prompt_key=prompt data.return_raw_chat=True data.dataloader_num_workers=0
  data.max_prompt_length="$PROMPT" data.max_response_length="$RESPONSE"
  data.filter_overlong_prompts=True data.truncation=error
  ++data.apply_chat_template_kwargs.enable_thinking=False
  actor_rollout_ref.model.path="$STUDENT"
  actor_rollout_ref.model.use_remove_padding=False
  ++actor_rollout_ref.model.override_config.attn_implementation=sdpa
  actor_rollout_ref.model.enable_gradient_checkpointing=True
  actor_rollout_ref.model.lora_rank=16 actor_rollout_ref.model.lora_alpha=32
  actor_rollout_ref.model.target_modules=all-linear
  actor_rollout_ref.actor.strategy=fsdp2
  actor_rollout_ref.actor.fsdp_config.model_dtype=bfloat16
  actor_rollout_ref.actor.fsdp_config.param_offload=True
  actor_rollout_ref.actor.fsdp_config.optimizer_offload=True
  actor_rollout_ref.actor.fsdp_config.offload_policy=False
  actor_rollout_ref.actor.fsdp_config.reshard_after_forward=True
  actor_rollout_ref.actor.use_torch_compile=False
  actor_rollout_ref.actor.optim.lr=1e-6 actor_rollout_ref.actor.optim.lr_warmup_steps=${WARMUP:-2}
  actor_rollout_ref.actor.optim.lr_warmup_steps_ratio=0
  actor_rollout_ref.actor.ppo_mini_batch_size=8 actor_rollout_ref.actor.ppo_epochs=1
  actor_rollout_ref.actor.use_dynamic_bsz=True
  actor_rollout_ref.actor.ppo_max_token_len_per_gpu=4096
  actor_rollout_ref.actor.use_kl_loss=False actor_rollout_ref.actor.entropy_coeff=0
  actor_rollout_ref.actor.loss_agg_mode=token-mean
  "actor_rollout_ref.actor.checkpoint.save_contents=['model','optimizer','extra']"
  ++actor_rollout_ref.actor.checkpoint.save_lora_only=True
  actor_rollout_ref.rollout.name=vllm actor_rollout_ref.rollout.mode=async
  actor_rollout_ref.rollout.tensor_model_parallel_size=1
  actor_rollout_ref.rollout.gpu_memory_utilization=0.40
  actor_rollout_ref.rollout.n=1 actor_rollout_ref.rollout.temperature=0.8
  actor_rollout_ref.rollout.val_kwargs.n=1
  actor_rollout_ref.rollout.val_kwargs.do_sample=False
  actor_rollout_ref.rollout.val_kwargs.temperature=0
  actor_rollout_ref.rollout.enforce_eager=True
  actor_rollout_ref.rollout.free_cache_engine=True
  actor_rollout_ref.rollout.max_num_seqs=8
  actor_rollout_ref.rollout.max_num_batched_tokens=4096
  actor_rollout_ref.rollout.max_model_len=$((PROMPT + RESPONSE))
  actor_rollout_ref.rollout.prompt_length="$PROMPT"
  actor_rollout_ref.rollout.response_length="$RESPONSE"
  actor_rollout_ref.rollout.log_prob_use_dynamic_bsz=True
  actor_rollout_ref.rollout.log_prob_max_token_len_per_gpu=4096
  actor_rollout_ref.rollout.calculate_log_probs=True
  actor_rollout_ref.rollout.agent.num_workers=2
  actor_rollout_ref.rollout.multi_turn.enable=False
  reward.num_workers=2
  reward.custom_reward_function.path="$REWARD_FILE"
  reward.custom_reward_function.name=compute_score
  distillation.enabled=True distillation.n_gpus_per_node=1 distillation.nnodes=1
  distillation.teacher_models.teacher_model.model_path="$TEACHER"
  distillation.teacher_models.teacher_model.inference.name=vllm
  distillation.teacher_models.teacher_model.inference.tensor_model_parallel_size=1
  distillation.teacher_models.teacher_model.inference.gpu_memory_utilization=0.72
  distillation.teacher_models.teacher_model.inference.enforce_eager=True
  distillation.teacher_models.teacher_model.inference.max_model_len=$((PROMPT + RESPONSE + 1))
  distillation.teacher_models.teacher_model.inference.max_num_batched_tokens=2048
  distillation.teacher_models.teacher_model.inference.max_num_seqs=4
  distillation.distillation_loss.loss_mode=k1
  distillation.distillation_loss.use_policy_gradient=True
  distillation.distillation_loss.use_task_rewards=False
  distillation.distillation_loss.loss_max_clamp=10.0
  distillation.distillation_loss.log_prob_min_clamp=-10.0
  trainer.nnodes=1 trainer.n_gpus_per_node=1
  trainer.project_name=xDAN-performance-9b
  trainer.experiment_name=overnight-multidomain-opd-20260924
  'trainer.logger=[console,wandb]'
  trainer.val_before_train=True trainer.test_freq=4 trainer.save_freq=4
  trainer.total_epochs=16 trainer.total_training_steps="$STEPS"
  trainer.max_actor_ckpt_to_keep=5 trainer.resume_mode=auto
  trainer.default_local_dir="$RUN/checkpoints"
  trainer.rollout_data_dir="$RUN/rollouts"
  trainer.validation_data_dir="$RUN/validation"
  ray_kwargs.ray_init.runtime_env.py_executable="$VIRTUAL_ENV/bin/python"
  ++ray_kwargs.ray_init.runtime_env.env_vars.VLLM_USE_FLASHINFER_SAMPLER='"0"'
  ++ray_kwargs.ray_init.runtime_env.env_vars.PYTHONNOUSERSITE='"1"'
  ++ray_kwargs.ray_init.runtime_env.env_vars.VIRTUAL_ENV="$VIRTUAL_ENV"
)
# --cfg job validates Hydra keys without initializing Ray or touching the GPUs.
if [[ "${1:-}" == --check-config ]]; then
  exec python -m verl.trainer.main_ppo "${ARGS[@]}" --cfg job
fi
for path in "$DATA/train.parquet" "$DATA/val.parquet" "$REWARD_FILE" "$STUDENT/config.json" "$TEACHER/config.json"; do
  [[ -f "$path" ]] || { echo "Missing required input: $path" >&2; exit 2; }
done
mkdir -p "$RUN"
printf '%q ' python -m verl.trainer.main_ppo "${ARGS[@]}" "$@" > "$RUN/command.txt"
printf '\n' >> "$RUN/command.txt"
exec python -m verl.trainer.main_ppo "${ARGS[@]}" "$@"
