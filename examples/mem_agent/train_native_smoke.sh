#!/usr/bin/env bash
# Single-GPU native diagnosis. No DSH qualification and no cloud sandbox.
set -euo pipefail
: "${MODEL_PATH:?Pinned local model required}"
: "${DATA_ROOT:?Prepared native diagnostic data required}"
: "${RUN_ROOT:?New run directory required}"
: "${PYTHON_BIN:?Isolated environment Python required}"
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root"
[[ ! -e "$RUN_ROOT" ]] || { echo 'Refusing to overwrite run' >&2; exit 2; }
mkdir -p "$RUN_ROOT"
export PYTHONPATH="$repo_root:$repo_root/verl:${PYTHONPATH:-}"
export HYDRA_FULL_ERROR=1 TOKENIZERS_PARALLELISM=false
export NCCL_P2P_DISABLE=1 NCCL_IB_DISABLE=1
command=("$PYTHON_BIN" -m verl.trainer.main_ppo
 trainer.use_v1=True trainer.v1.trainer_mode=sync transfer_queue.enable=True
 data.train_files="$DATA_ROOT/train.parquet" data.val_files="$DATA_ROOT/val.parquet"
 data.prompt_key=prompt data.return_raw_chat=True data.train_batch_size=1
 data.max_prompt_length=6144 data.max_response_length=1024 data.filter_overlong_prompts=False
 data.custom_cls.path=pkg://examples.mem_agent.dataset data.custom_cls.name=HotpotQAMemAgentDataset
 ++data.context_chunk_size=4096 ++data.apply_chat_template_kwargs.enable_thinking=False
 algorithm.adv_estimator=grpo algorithm.use_kl_in_reward=False
 actor_rollout_ref.model.path="$MODEL_PATH" actor_rollout_ref.model.lora_rank=16
 actor_rollout_ref.model.lora_alpha=16 actor_rollout_ref.model.target_modules=all-linear
 actor_rollout_ref.model.use_remove_padding=True actor_rollout_ref.model.enable_gradient_checkpointing=True
 ++actor_rollout_ref.model.override_config.attn_implementation=sdpa
 actor_rollout_ref.actor.strategy=fsdp actor_rollout_ref.actor.fsdp_config.model_dtype=bfloat16
 actor_rollout_ref.actor.fsdp_config.optimizer_offload=True actor_rollout_ref.actor.optim.lr=1e-5
 actor_rollout_ref.actor.ppo_mini_batch_size=1 actor_rollout_ref.actor.ppo_epochs=1
 actor_rollout_ref.actor.use_dynamic_bsz=True actor_rollout_ref.actor.ppo_max_token_len_per_gpu=8192
 actor_rollout_ref.actor.use_kl_loss=False actor_rollout_ref.actor.entropy_coeff=0
 actor_rollout_ref.rollout.name=vllm actor_rollout_ref.rollout.mode=async
 actor_rollout_ref.rollout.tensor_model_parallel_size=1 actor_rollout_ref.rollout.n=4
 actor_rollout_ref.rollout.val_kwargs.n=1 actor_rollout_ref.rollout.gpu_memory_utilization=0.3
 actor_rollout_ref.rollout.enforce_eager=True actor_rollout_ref.rollout.free_cache_engine=True
 actor_rollout_ref.rollout.layered_summon=False actor_rollout_ref.rollout.max_num_seqs=2
 actor_rollout_ref.rollout.prompt_length=6144 actor_rollout_ref.rollout.response_length=1024
 actor_rollout_ref.rollout.max_model_len=7168 actor_rollout_ref.rollout.max_num_batched_tokens=7168
 actor_rollout_ref.rollout.log_prob_use_dynamic_bsz=True
 actor_rollout_ref.rollout.log_prob_max_token_len_per_gpu=8192
 actor_rollout_ref.rollout.calculate_log_probs=True
 actor_rollout_ref.rollout.multi_turn.enable=True actor_rollout_ref.rollout.agent.num_workers=1
 ++actor_rollout_ref.rollout.agent.agent_loop_manager_class=uni_agent.framework.entry.AgentFrameworkRolloutAdapter
 ++actor_rollout_ref.rollout.custom.agent_framework.gateway_count=1
 ++actor_rollout_ref.rollout.custom.agent_framework.log_dir="$RUN_ROOT/trajectories"
 ++actor_rollout_ref.rollout.custom.agent_framework.agent_runners.task.runner_fqn=uni_agent.framework.task_runner.run_task
 ++actor_rollout_ref.rollout.custom.agent_framework.agent_runners.task.dispatch_mode=ray_task
 ++actor_rollout_ref.rollout.custom.agent_framework.agent_runners.task.max_concurrent_sessions=2
 ++actor_rollout_ref.rollout.custom.agent_framework.agent_runners.task.trajectory_selection=all
 ++actor_rollout_ref.rollout.custom.agent_framework.agent_runners.task.runner_kwargs.task_config_path=examples/mem_agent/task_config_native_smoke.yaml
 ++actor_rollout_ref.rollout.custom.agent_framework.agent_runners.task.runner_kwargs.model_name=Qwen3-4B
 ++actor_rollout_ref.rollout.custom.agent_framework.mask_unfinished_episode=False
 ++actor_rollout_ref.rollout.custom.agent_framework.fail_on_rollout_error=True
 ++actor_rollout_ref.rollout.custom.agent_framework.require_trajectory_dump=True
 reward.custom_reward_function.path=pkg://uni_agent.framework.task_runner
 reward.custom_reward_function.name=score_from_runner_result
 trainer.logger="['console','file']" trainer.project_name=native-smoke trainer.experiment_name=memagent-single-gpu
 trainer.nnodes=1 trainer.n_gpus_per_node=1 trainer.val_before_train=True
 trainer.total_epochs=1 trainer.total_training_steps=2 trainer.save_freq=1 trainer.test_freq=1
 trainer.resume_mode=disable trainer.default_local_dir="$RUN_ROOT/checkpoints"
 trainer.rollout_data_dir="$RUN_ROOT/rollouts" trainer.validation_data_dir="$RUN_ROOT/validation"
 "$@")
printf '%q ' "${command[@]}" > "$RUN_ROOT/command.txt"
printf '\n' >> "$RUN_ROOT/command.txt"
git rev-parse HEAD > "$RUN_ROOT/code-revision.txt"
git -C verl rev-parse HEAD > "$RUN_ROOT/verl-revision.txt"
cp "$DATA_ROOT/manifest.json" "$RUN_ROOT/data-manifest.json"
# A new local Ray runtime belongs to this driver. No existing shared cluster.
export RAY_ADDRESS=local
exec timeout --signal=INT --kill-after=30s 1800s "${command[@]}"
