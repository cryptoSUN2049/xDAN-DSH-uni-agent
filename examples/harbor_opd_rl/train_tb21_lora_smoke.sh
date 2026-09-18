#!/usr/bin/env bash
# Terminal-Bench 2.1 + Harbor (built-in terminus-2, Modal sandbox) + VERL V1
# sync GRPO/LoRA | Qwen3-4B | single GPU | one-or-two-update smoke.
#
# Derived from examples/dsh/train_qwen3_4b_online_rl.sh with the DSH-specific
# trajectory audit and trace/result roots removed: Harbor owns task execution
# and the verifier reward through uni_agent/tasks/harbor. terminus-2 runs on
# this host and reaches the session-scoped Gateway through LLM_BASE_URL-style
# environment variables injected by the adapter; no public ingress is needed.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
VERL_ROOT="${REPO_ROOT}/verl"
cd "${REPO_ROOT}"

MODEL_PATH="${MODEL_PATH:-}"
# litellm provider prefix: terminus-2 strips hosted_vllm/ and sends the rest as the model name.
MODEL_ID="${MODEL_ID:-hosted_vllm/$(basename "${MODEL_PATH:-Qwen3-4B}")}"
TRAIN_FILE="${TRAIN_FILE:?absolute Harbor parquet for training}"
TEST_FILE="${TEST_FILE:?absolute Harbor parquet for validation}"
TASK_CONFIG="${TASK_CONFIG:-${REPO_ROOT}/examples/harbor_opd_rl/tb21_terminus2_smoke.yaml}"
RUN_ROOT="${RUN_ROOT:?absolute private run root}"
PROJECT_NAME="${PROJECT_NAME:-xDAN-Verl-Uni-agent-Harbor-rl-opd}"   # also the wandb project
EXP_NAME="${EXP_NAME:-smoke}"
CKPTS_DIR="${CKPTS_DIR:-${RUN_ROOT}/checkpoints/${PROJECT_NAME}/${EXP_NAME}}"
AGENT_LOG_DIR="${AGENT_LOG_DIR:-${RUN_ROOT}/agent-logs/${PROJECT_NAME}/${EXP_NAME}}"
ROLLOUT_DATA_DIR="${ROLLOUT_DATA_DIR:-${RUN_ROOT}/rollouts/${PROJECT_NAME}/${EXP_NAME}}"
VALIDATION_DATA_DIR="${VALIDATION_DATA_DIR:-${RUN_ROOT}/validation/${PROJECT_NAME}/${EXP_NAME}}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

NNODES="${NNODES:-1}"
NGPUS_PER_NODE="${NGPUS_PER_NODE:-1}"
ROLLOUT_TP="${ROLLOUT_TP:-1}"
ROLLOUT_N="${ROLLOUT_N:-2}"
VAL_ROLLOUT_N="${VAL_ROLLOUT_N:-1}"
# Validation sampling. VERL defaults to greedy (temperature 0), which makes
# VAL_ROLLOUT_N > 1 near-identical; VAL_TEMPERATURE=1.0 samples like training rollouts.
VAL_TEMPERATURE="${VAL_TEMPERATURE:-}"
# LoRA learning rate. 1e-5 moved pipe-r11 by only ~1e-4 of |W| in 20 steps (Adam moves
# each weight ~lr per step); LoRA wants ~10x a full fine-tune LR. LR_WARMUP_STEPS
# linearly warms up the first steps, when Adam's normalised update is largest.
LR="${LR:-1e-5}"
LR_WARMUP_STEPS="${LR_WARMUP_STEPS:--1}"
GATEWAY_COUNT="${GATEWAY_COUNT:-1}"
CONCURRENCY="${CONCURRENCY:-2}"
GPU_MEMORY_UTILIZATION="${GPU_MEMORY_UTILIZATION:-0.40}"
# Must match agent.model.max_total_tokens in TASK_CONFIG (episode budget).
MAX_PROMPT_LENGTH="${MAX_PROMPT_LENGTH:-4096}"
MAX_RESPONSE_LENGTH="${MAX_RESPONSE_LENGTH:-32768}"
# Tokens per vLLM engine step (chunked prefill). The default is a whole context in
# one step, which is fine for Qwen3-4B but OOMs Qwen3.5-9B (hybrid linear
# attention, 248k vocab): pipe-r4 tried a 26.84 GiB allocation at 36864 tokens.
# The Teacher computes prompt logprobs over the batched tokens, so its
# vocab-sized buffer scales the same way. Use 8192 for Qwen3.5 / 27B Teachers.
ROLLOUT_MAX_NUM_BATCHED_TOKENS="${ROLLOUT_MAX_NUM_BATCHED_TOKENS:-$((MAX_PROMPT_LENGTH + MAX_RESPONSE_LENGTH))}"
TEACHER_MAX_NUM_BATCHED_TOKENS="${TEACHER_MAX_NUM_BATCHED_TOKENS:-$((MAX_PROMPT_LENGTH + MAX_RESPONSE_LENGTH))}"
PPO_MAX_TOKEN_LEN_PER_GPU="${PPO_MAX_TOKEN_LEN_PER_GPU:-$((MAX_PROMPT_LENGTH + MAX_RESPONSE_LENGTH))}"
LORA_RANK="${LORA_RANK:-32}"
LORA_ALPHA="${LORA_ALPHA:-32}"
ACTOR_PARAM_OFFLOAD="${ACTOR_PARAM_OFFLOAD:-True}"
ACTOR_OPTIMIZER_OFFLOAD="${ACTOR_OPTIMIZER_OFFLOAD:-True}"
ROLLOUT_ENFORCE_EAGER="${ROLLOUT_ENFORCE_EAGER:-False}"   # CUDA graphs on: faster decode
ROLLOUT_FREE_CACHE_ENGINE="${ROLLOUT_FREE_CACHE_ENGINE:-True}"
ROLLOUT_LAYERED_SUMMON="${ROLLOUT_LAYERED_SUMMON:-False}"
ROLLOUT_MAX_NUM_SEQS="${ROLLOUT_MAX_NUM_SEQS:-4}"
ROLLOUT_ENABLE_PREFIX_CACHING="${ROLLOUT_ENABLE_PREFIX_CACHING:-True}"   # multi-turn prompts share prefixes
SAVE_LORA_ONLY="${SAVE_LORA_ONLY:-False}"
TRAIN_BATCH_SIZE="${TRAIN_BATCH_SIZE:-2}"
PPO_MINI_BATCH_SIZE="${PPO_MINI_BATCH_SIZE:-2}"
TOTAL_TRAINING_STEPS="${TOTAL_TRAINING_STEPS:-1}"
SAVE_FREQ="${SAVE_FREQ:-1}"
# VERL keeps only the newest N actor checkpoints (8.7 GB each for 4B LoRA with
# optimizer state). Newest 10 by default (user decision); a checkpoint corrupted mid-save
# still leaves good predecessors. Post-run retention: deployment/bootstrap/retain-checkpoints.sh
MAX_CKPT_TO_KEEP="${MAX_CKPT_TO_KEEP:-10}"   # user 2026-09-17: keep the newest 10
TEST_FREQ="${TEST_FREQ:--1}"
VAL_BEFORE_TRAIN="${VAL_BEFORE_TRAIN:-False}"
TRAIN_MAX_SAMPLES="${TRAIN_MAX_SAMPLES:-2}"
VAL_MAX_SAMPLES="${VAL_MAX_SAMPLES:-1}"
DATA_SHUFFLE="${DATA_SHUFFLE:-False}"
TOOL_PARSER="${TOOL_PARSER:-hermes}"
ATTN_IMPLEMENTATION="${ATTN_IMPLEMENTATION:-sdpa}"
TRAINER_MODE="${TRAINER_MODE:-colocate_async}"   # user 2026-09-16: default async on one GPU; sync only for A/B
NUM_WARMUP_BATCHES="${NUM_WARMUP_BATCHES:-1}"
# VERL stops at min(total_epochs, total_training_steps). With a tiny dataset one
# epoch is only TRAIN_MAX_SAMPLES/TRAIN_BATCH_SIZE steps, so derive the epoch
# budget from the requested step target (same rule as launch.py finalize_training_plan).
STEPS_PER_EPOCH=$(( TRAIN_MAX_SAMPLES / TRAIN_BATCH_SIZE ))
[[ ${STEPS_PER_EPOCH} -ge 1 ]] || { echo "TRAIN_MAX_SAMPLES must be >= TRAIN_BATCH_SIZE" >&2; exit 2; }
TOTAL_EPOCHS="${TOTAL_EPOCHS:-$(( (TOTAL_TRAINING_STEPS + STEPS_PER_EPOCH - 1) / STEPS_PER_EPOCH ))}"
RESUME_MODE="${RESUME_MODE:-disable}"
RESUME_FROM_PATH="${RESUME_FROM_PATH:-}"   # global_step_N dir; sets trainer.resume_from_path when non-empty
MASK_UNFINISHED_EPISODE="${MASK_UNFINISHED_EPISODE:-True}"
# FAIL_ON_ROLLOUT_ERROR=1 aborts the whole step when any session fails (strict
# smoke). 0 (default) keeps the run going and keeps as much finished work as possible:
#   - a group that lost sessions is trained on its valid ones while at least
#     MIN_VALID_SESSIONS remain (default half of ROLLOUT_N: 8 -> 4; GRPO's group
#     mean/std use only the samples present, nothing is imputed);
#   - below that the whole group is marked failed and the replay buffer refills it.
# Worker-side errors never reach the trainer (generate_sequences is fire-and-forget),
# so an outage shows as repeated "rollout group dropped" lines, not as a crash.
# A short group makes VERL pad the batch with a synthetic sample; patches/verl/0001
# (applied by sync-source.sh) gives that sample teacher rows of its own length, which
# upstream forgot and which crashed pipe-r11 at step 5 on 2026-09-18.
# require_trajectory_dump is only valid in strict mode (framework validation).
FAIL_ON_ROLLOUT_ERROR="${FAIL_ON_ROLLOUT_ERROR:-0}"
MIN_VALID_SESSIONS="${MIN_VALID_SESSIONS:-$(( ROLLOUT_N / 2 > 2 ? ROLLOUT_N / 2 : 2 ))}"
if [[ "${FAIL_ON_ROLLOUT_ERROR}" == "1" ]]; then
  STRICT_OVERRIDES=(
    ++actor_rollout_ref.rollout.custom.agent_framework.fail_on_rollout_error=True
    ++actor_rollout_ref.rollout.custom.agent_framework.require_trajectory_dump=True
  )
else
  STRICT_OVERRIDES=(
    ++actor_rollout_ref.rollout.custom.agent_framework.fail_on_rollout_error=False
    ++actor_rollout_ref.rollout.custom.agent_framework.min_valid_sessions_per_group="${MIN_VALID_SESSIONS}"
  )
fi
# wandb: credentials come from ~/.netrc (wandb login) or WANDB_API_KEY, never from this repo.
WANDB_ENABLED="${WANDB_ENABLED:-1}"
export WANDB_PROJECT="${WANDB_PROJECT:-${PROJECT_NAME}}"
export WANDB_ENTITY="${WANDB_ENTITY:-xdan-ai}"
# Keep local wandb files with the run, not inside the rsync'd source tree.
export WANDB_DIR="${WANDB_DIR:-${RUN_ROOT}/wandb}"
[[ "${PRINT_COMMAND:-0}" == "1" ]] || mkdir -p "${WANDB_DIR}"
if [[ "${WANDB_ENABLED}" == "1" ]]; then
  TRAINER_LOGGER="['console','file','wandb']"
else
  TRAINER_LOGGER="['console','file']"
fi

if [[ "${TRAINER_MODE}" != sync && "${TRAINER_MODE}" != colocate_async ]]; then
  echo "TRAINER_MODE must be sync or colocate_async" >&2; exit 2
fi

# DAPO=1: dynamic sampling (drop groups whose rewards are all equal and refill),
# clip-higher, optional overlong shaping. VERL V1's ReplayBuffer ignores
# filter_groups.max_num_gen_batches: it fetches prompts one at a time and keeps
# refilling (the dataloader cycles) until train_batch_size groups with variance
# exist, with at most DAPO_MAX_INFLIGHT x train_batch_size prompts in flight. With
# ~45% zero-variance groups that is ~2x wall time and sandboxes per step at the
# default of 1; raise DAPO_MAX_INFLIGHT to trade sandboxes for wall time.
DAPO="${DAPO:-0}"
DAPO_MAX_INFLIGHT="${DAPO_MAX_INFLIGHT:-1}"
DAPO_METRIC="${DAPO_METRIC:-reward}"
CLIP_RATIO_LOW="${CLIP_RATIO_LOW:-0.2}"
CLIP_RATIO_HIGH="${CLIP_RATIO_HIGH:-0.2}"
DAPO_OVERRIDES=()
if [[ "${DAPO}" == "1" ]]; then
  CLIP_RATIO_HIGH="${CLIP_RATIO_HIGH_DAPO:-0.28}"
  DAPO_OVERRIDES+=(
    algorithm.filter_groups.enable=True
    algorithm.filter_groups.metric="${DAPO_METRIC}"
    algorithm.filter_groups.max_inflight_gen_batches="${DAPO_MAX_INFLIGHT}"
  )
  # Overlong reward shaping is not wired here: this VERL config has no
  # reward.reward_kwargs path; the episode budget (max_total_tokens) bounds length instead.
fi

# TEACHER=1: route 2 (OPD). VERL's native Teacher is a frozen vLLM replica that
# scores the student's own tokens with prompt_logprobs; the Agent Framework
# receives teacher_client automatically when distillation.enabled=True. It needs
# its OWN Ray resource pool of whole GPUs. On a single physical GPU,
# TEACHER_SHARE_GPU=1 advertises two logical GPUs to Ray and stops Ray from
# rewriting CUDA_VISIBLE_DEVICES, so actor/rollout and teacher share device 0
# (memory budget: student vLLM GPU_MEMORY_UTILIZATION + TEACHER_GPU_MEM < ~0.8).
TEACHER="${TEACHER:-0}"
TEACHER_MODEL_PATH="${TEACHER_MODEL_PATH:-${MODEL_PATH}}"   # 4B self-teacher is enough for wiring
TEACHER_SHARE_GPU="${TEACHER_SHARE_GPU:-0}"   # 0 = teacher on its own physical GPU (recommended); 1 = single-GPU smoke hack
TEACHER_GPU_MEM="${TEACHER_GPU_MEM:-0.25}"
TEACHER_MAX_NUM_SEQS="${TEACHER_MAX_NUM_SEQS:-8}"
DISTILL_LOSS_MODE="${DISTILL_LOSS_MODE:-k1}"          # k1 = on-policy distillation (TML blog); k3 = topk/forward-KL variants
DISTILL_LOSS_COEF="${DISTILL_LOSS_COEF:-1.0}"
DISTILL_USE_TASK_REWARDS="${DISTILL_USE_TASK_REWARDS:-True}"   # hybrid: RL reward + OPD
TEACHER_OVERRIDES=()
if [[ "${TEACHER}" == "1" ]]; then
  [[ -n "${TEACHER_MODEL_PATH}" ]] || { echo "TEACHER=1 requires TEACHER_MODEL_PATH (or MODEL_PATH)" >&2; exit 2; }
  TEACHER_OVERRIDES+=(
    distillation.enabled=True
    distillation.nnodes=1
    distillation.n_gpus_per_node=1
    distillation.distillation_loss.loss_mode="${DISTILL_LOSS_MODE}"
    distillation.distillation_loss.use_policy_gradient=True
    distillation.distillation_loss.use_task_rewards="${DISTILL_USE_TASK_REWARDS}"
    distillation.distillation_loss.distillation_loss_coef="${DISTILL_LOSS_COEF}"
    distillation.teacher_models.teacher_model.model_path="${TEACHER_MODEL_PATH}"
    distillation.teacher_models.teacher_model.num_replicas=1
    distillation.teacher_models.teacher_model.inference.tensor_model_parallel_size=1
    distillation.teacher_models.teacher_model.inference.gpu_memory_utilization="${TEACHER_GPU_MEM}"
    distillation.teacher_models.teacher_model.inference.max_model_len=$((MAX_PROMPT_LENGTH + MAX_RESPONSE_LENGTH + 1))
    distillation.teacher_models.teacher_model.inference.max_num_batched_tokens="${TEACHER_MAX_NUM_BATCHED_TOKENS}"
    distillation.teacher_models.teacher_model.inference.max_num_seqs="${TEACHER_MAX_NUM_SEQS}"
  )
  if [[ "${TEACHER_SHARE_GPU}" == "1" ]]; then
    export RAY_EXPERIMENTAL_NOSET_CUDA_VISIBLE_DEVICES=1
    TEACHER_OVERRIDES+=(++ray_kwargs.ray_init.num_gpus=2)
  fi
fi

COMMAND=(
  "${PYTHON_BIN}" -m verl.trainer.main_ppo
  trainer.use_v1=True
  trainer.v1.trainer_mode="${TRAINER_MODE}"
  trainer.v1.colocate_async.num_warmup_batches="${NUM_WARMUP_BATCHES}"
  trainer.v1.sampler.sync_refill_failed_groups=True
  transfer_queue.enable=True
  algorithm.adv_estimator=grpo
  algorithm.use_kl_in_reward=False
  data.train_files="${TRAIN_FILE}"
  data.val_files="${TEST_FILE}"
  data.prompt_key=prompt
  data.return_raw_chat=True
  data.filter_overlong_prompts=True
  data.truncation=error
  data.dataloader_num_workers=0
  data.shuffle="${DATA_SHUFFLE}"
  data.train_max_samples="${TRAIN_MAX_SAMPLES}"
  data.val_max_samples="${VAL_MAX_SAMPLES}"
  data.train_batch_size="${TRAIN_BATCH_SIZE}"
  data.max_prompt_length="${MAX_PROMPT_LENGTH}"
  data.max_response_length="${MAX_RESPONSE_LENGTH}"
  ++data.apply_chat_template_kwargs.enable_thinking=False
  actor_rollout_ref.model.path="${MODEL_PATH}"
  ++actor_rollout_ref.model.override_config.attn_implementation="${ATTN_IMPLEMENTATION}"
  actor_rollout_ref.actor.fsdp_config.model_dtype=bfloat16
  actor_rollout_ref.model.use_remove_padding=True
  actor_rollout_ref.model.enable_gradient_checkpointing=True
  actor_rollout_ref.model.lora_rank="${LORA_RANK}"
  actor_rollout_ref.model.lora_alpha="${LORA_ALPHA}"
  actor_rollout_ref.model.target_modules=all-linear
  actor_rollout_ref.actor.strategy=fsdp
  actor_rollout_ref.actor.optim.lr="${LR}"
  actor_rollout_ref.actor.optim.lr_warmup_steps="${LR_WARMUP_STEPS}"
  actor_rollout_ref.actor.ppo_mini_batch_size="${PPO_MINI_BATCH_SIZE}"
  actor_rollout_ref.actor.ppo_epochs=1
  actor_rollout_ref.actor.use_dynamic_bsz=True
  actor_rollout_ref.actor.use_torch_compile=False
  actor_rollout_ref.actor.ppo_max_token_len_per_gpu="${PPO_MAX_TOKEN_LEN_PER_GPU}"
  actor_rollout_ref.actor.use_kl_loss=False
  actor_rollout_ref.actor.entropy_coeff=0
  actor_rollout_ref.actor.clip_ratio_low="${CLIP_RATIO_LOW}"
  actor_rollout_ref.actor.clip_ratio_high="${CLIP_RATIO_HIGH}"
  actor_rollout_ref.actor.loss_agg_mode=token-mean
  actor_rollout_ref.actor.fsdp_config.param_offload="${ACTOR_PARAM_OFFLOAD}"
  actor_rollout_ref.actor.fsdp_config.optimizer_offload="${ACTOR_OPTIMIZER_OFFLOAD}"
  "actor_rollout_ref.actor.checkpoint.save_contents=['model','optimizer','extra']"
  "actor_rollout_ref.actor.checkpoint.load_contents=['model','optimizer','extra']"
  ++actor_rollout_ref.actor.checkpoint.save_lora_only="${SAVE_LORA_ONLY}"
  actor_rollout_ref.rollout.name=vllm
  actor_rollout_ref.rollout.mode=async
  actor_rollout_ref.rollout.tensor_model_parallel_size="${ROLLOUT_TP}"
  actor_rollout_ref.rollout.gpu_memory_utilization="${GPU_MEMORY_UTILIZATION}"
  actor_rollout_ref.rollout.n="${ROLLOUT_N}"
  actor_rollout_ref.rollout.val_kwargs.n="${VAL_ROLLOUT_N}"
  ${VAL_TEMPERATURE:+actor_rollout_ref.rollout.val_kwargs.temperature="${VAL_TEMPERATURE}"}
  ${VAL_TEMPERATURE:+actor_rollout_ref.rollout.val_kwargs.top_p=1.0}
  ${VAL_TEMPERATURE:+actor_rollout_ref.rollout.val_kwargs.do_sample=True}
  actor_rollout_ref.rollout.load_format=safetensors
  actor_rollout_ref.rollout.layered_summon="${ROLLOUT_LAYERED_SUMMON}"
  actor_rollout_ref.rollout.free_cache_engine="${ROLLOUT_FREE_CACHE_ENGINE}"
  actor_rollout_ref.rollout.enforce_eager="${ROLLOUT_ENFORCE_EAGER}"
  actor_rollout_ref.rollout.max_num_seqs="${ROLLOUT_MAX_NUM_SEQS}"
  actor_rollout_ref.rollout.enable_prefix_caching="${ROLLOUT_ENABLE_PREFIX_CACHING}"
  actor_rollout_ref.rollout.log_prob_use_dynamic_bsz=True
  actor_rollout_ref.rollout.log_prob_max_token_len_per_gpu="${PPO_MAX_TOKEN_LEN_PER_GPU}"
  actor_rollout_ref.rollout.prompt_length="${MAX_PROMPT_LENGTH}"
  actor_rollout_ref.rollout.response_length="${MAX_RESPONSE_LENGTH}"
  actor_rollout_ref.rollout.max_model_len=$((MAX_PROMPT_LENGTH + MAX_RESPONSE_LENGTH))
  actor_rollout_ref.rollout.max_num_batched_tokens="${ROLLOUT_MAX_NUM_BATCHED_TOKENS}"
  actor_rollout_ref.rollout.multi_turn.enable=True
  actor_rollout_ref.rollout.multi_turn.max_parallel_calls=1
  actor_rollout_ref.rollout.multi_turn.format="${TOOL_PARSER}"
  actor_rollout_ref.rollout.agent.num_workers=1
  ++actor_rollout_ref.rollout.agent.agent_loop_manager_class=uni_agent.framework.entry.AgentFrameworkRolloutAdapter
  ++actor_rollout_ref.rollout.custom.agent_framework.gateway_count="${GATEWAY_COUNT}"
  ++actor_rollout_ref.rollout.custom.agent_framework.log_dir="${AGENT_LOG_DIR}"
  ++actor_rollout_ref.rollout.custom.agent_framework.agent_runners.task.runner_fqn=uni_agent.framework.task_runner.run_task
  ++actor_rollout_ref.rollout.custom.agent_framework.agent_runners.task.dispatch_mode=ray_task
  ++actor_rollout_ref.rollout.custom.agent_framework.agent_runners.task.max_concurrent_sessions="${CONCURRENCY}"
  ++actor_rollout_ref.rollout.custom.agent_framework.agent_runners.task.trajectory_selection=longest
  ++actor_rollout_ref.rollout.custom.agent_framework.agent_runners.task.runner_kwargs.task_config_path="${TASK_CONFIG}"
  ++actor_rollout_ref.rollout.custom.agent_framework.agent_runners.task.runner_kwargs.model_name="${MODEL_ID}"
  ++actor_rollout_ref.rollout.custom.agent_framework.agent_runners.task.runner_kwargs.require_result=True
  ++actor_rollout_ref.rollout.custom.agent_framework.use_reward_loop_worker=False
  ++actor_rollout_ref.rollout.custom.agent_framework.mask_unfinished_episode="${MASK_UNFINISHED_EPISODE}"
  # require_verifier_reward is DSH-only (TaskResult.verifier_reward). require_result
  # only rejects a missing reward; nothing downstream reads eval_completed. Incomplete
  # Harbor trials are handled in the adapter: agent failures score 0, infrastructure
  # failures raise and drop that session (HARBOR_INFRA_FAILURE=exclude|zero).
  "${STRICT_OVERRIDES[@]}"
  trainer.logger="${TRAINER_LOGGER}"
  trainer.project_name="${PROJECT_NAME}"
  trainer.experiment_name="${EXP_NAME}"
  trainer.val_before_train="${VAL_BEFORE_TRAIN}"
  trainer.save_freq="${SAVE_FREQ}"
  trainer.max_actor_ckpt_to_keep="${MAX_CKPT_TO_KEEP}"
  trainer.test_freq="${TEST_FREQ}"
  trainer.total_epochs="${TOTAL_EPOCHS}"
  trainer.total_training_steps="${TOTAL_TRAINING_STEPS}"
  trainer.resume_mode="${RESUME_MODE}"
  ${RESUME_FROM_PATH:+trainer.resume_from_path="${RESUME_FROM_PATH}"}
  trainer.default_local_dir="${CKPTS_DIR}"
  trainer.rollout_data_dir="${ROLLOUT_DATA_DIR}"
  trainer.validation_data_dir="${VALIDATION_DATA_DIR}"
  trainer.nnodes="${NNODES}"
  trainer.n_gpus_per_node="${NGPUS_PER_NODE}"
  ${DAPO_OVERRIDES[@]+"${DAPO_OVERRIDES[@]}"}
  ${TEACHER_OVERRIDES[@]+"${TEACHER_OVERRIDES[@]}"}
)

if [[ "${PRINT_COMMAND:-0}" == "1" ]]; then
  printf '%q ' "${COMMAND[@]}" "$@"; printf '\n'; exit 0
fi

[[ -n "${MODEL_PATH}" && -f "${MODEL_PATH}/config.json" ]] || { echo "MODEL_PATH must be a local snapshot with config.json" >&2; exit 2; }
for required_path in "${TRAIN_FILE}" "${TEST_FILE}" "${TASK_CONFIG}"; do
  [[ -f "${required_path}" ]] || { echo "required file is missing: ${required_path}" >&2; exit 2; }
done
export PYTHONPATH="${REPO_ROOT}:${VERL_ROOT}${PYTHONPATH:+:${PYTHONPATH}}"
"${PYTHON_BIN}" -c 'import harbor, modal, transfer_queue, verl, uni_agent' || { echo "runtime dependency missing" >&2; exit 2; }
command -v harbor >/dev/null || { echo "harbor CLI not on PATH" >&2; exit 2; }
mkdir -p "${CKPTS_DIR}" "${AGENT_LOG_DIR}" "${ROLLOUT_DATA_DIR}" "${VALIDATION_DATA_DIR}"
printf '%q ' "${COMMAND[@]}" "$@" > "${RUN_ROOT}/train-command.txt"; printf '\n' >> "${RUN_ROOT}/train-command.txt"
exec "${COMMAND[@]}" "$@"
