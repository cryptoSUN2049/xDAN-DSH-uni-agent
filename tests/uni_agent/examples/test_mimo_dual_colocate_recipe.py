"""Compose the fresh two-rank colocate recipe through prepared launch binding."""

import pytest

from examples.harbor_opd_rl import launch
from tests.uni_agent.examples.test_mimo_budget_recipe import ENV, LIMITS, ROOT, prepared_budget_launch

RECIPE = ROOT / "examples/mimo_dsh_rl/mimo-9b-dual-colocate-observed.yaml"


def configured(prepared=None):
    return launch.compose_config(
        launch.build_overrides("rl", prepared or prepared_budget_launch(), ENV, recipe_config=RECIPE)
    )


def test_dual_colocate_uses_shared_pool_and_divisible_per_rank_minibatches():
    cfg = configured()
    rollout = cfg.actor_rollout_ref.rollout
    actor_world_size = cfg.trainer.nnodes * cfg.trainer.n_gpus_per_node
    replica_world_size = (
        rollout.tensor_model_parallel_size * rollout.data_parallel_size * rollout.pipeline_model_parallel_size
    )
    assert cfg.trainer.use_v1 and cfg.transfer_queue.enable
    assert cfg.trainer.v1.trainer_mode == "colocate_async"
    assert actor_world_size == 2 and cfg.trainer.nnodes == 1
    assert rollout.nnodes == 0 and rollout.n_gpus_per_node == 2
    assert replica_world_size == 1 and actor_world_size // replica_world_size == 2
    assert rollout.checkpoint_engine.backend == "naive"
    assert cfg.trainer.v1.colocate_async.num_warmup_batches == 1
    minibatch = cfg.actor_rollout_ref.actor.ppo_mini_batch_size * rollout.n
    assert minibatch == 4 and minibatch % actor_world_size == 0
    assert minibatch // actor_world_size == 2
    assert not cfg.distillation.enabled and cfg.distillation.nnodes == 0


def test_dual_colocate_is_fresh_and_preserves_native_observation_and_concurrency():
    cfg = configured()
    rollout = cfg.actor_rollout_ref.rollout
    # Rank-1 C3/C4 cannot be resumed as rank-2 checkpoints; runtime admission also guards this.
    assert cfg.trainer.resume_mode == "disable" and cfg.trainer.resume_from_path is None
    assert cfg.trainer.total_training_steps == 2 and cfg.trainer.save_freq == 1
    assert cfg.trainer.experiment_name == "mimo9b-001661-r14"
    assert cfg.trainer.project_name == "xDAN-Verl-Uni-agent-Harbor-rl-opd"
    assert list(cfg.trainer.logger) == ["console", "wandb", "rl_insight"]
    assert cfg.transfer_queue.metrics.enabled and cfg.transfer_queue.metrics.port == 0
    assert rollout.disable_log_stats is False
    assert rollout.max_num_seqs == 2 and rollout.agent.num_workers == 1
    assert rollout.custom.agent_framework.agent_runners.task.max_concurrent_sessions == 2
    assert rollout.multi_turn.max_parallel_calls == 1


def test_dual_colocate_keeps_operator_budget_and_proven_model_settings():
    prepared = prepared_budget_launch()
    cfg = configured(prepared)
    model = cfg.actor_rollout_ref.model
    actor = cfg.actor_rollout_ref.actor
    rollout = cfg.actor_rollout_ref.rollout
    framework = rollout.custom.agent_framework
    assert cfg.algorithm.adv_estimator == "grpo" and rollout.n == 4
    assert cfg.data.max_prompt_length + cfg.data.max_response_length == rollout.max_model_len == 32768
    assert actor.ppo_max_token_len_per_gpu == rollout.log_prob_max_token_len_per_gpu == 32768
    assert framework.max_generated_tokens_per_episode == LIMITS["max_generated_tokens"] == 20480
    assert framework.termination_policy == "budget-terminal-v1" and not framework.mask_unfinished_episode
    assert framework.require_finished_episode and framework.fail_on_rollout_error
    assert framework.require_verifier_reward and framework.require_version_evidence
    assert framework.require_trajectory_dump and framework.trajectory_postprocessor_kwargs == prepared["postprocessor"]
    assert model.lora_rank == 16 and model.lora_alpha == 32 and model.lora.merge
    assert model.override_config.attn_implementation == "sdpa" and not model.use_remove_padding
    assert actor.fsdp_config.entropy_from_logits_with_chunking
    assert actor.fsdp_config.entropy_from_logits_chunk_size == 256
    assert actor.fsdp_config.param_offload and actor.fsdp_config.optimizer_offload


@pytest.mark.parametrize("field,value", [("max_generated_tokens", 14336), ("trajectory_capacity", 65536)])
def test_dual_colocate_rejects_mismatched_operator_budget(field, value):
    prepared = prepared_budget_launch()
    prepared["postprocessor"]["budget_limits"][field] = value
    prepared["postprocessor"]["policy_template"]["budget_limits"][field] = value
    with pytest.raises(ValueError, match="budget|capacity"):
        configured(prepared)
