"""Compose the dual-GPU MiMo recipe through the actual prepared-launch contract."""

import pytest

from examples.harbor_opd_rl import launch
from tests.uni_agent.examples.test_mimo_budget_recipe import ENV, LIMITS, ROOT, prepared_budget_launch

RECIPE = ROOT / "examples/mimo_dsh_rl/mimo-9b-separate-async.yaml"


def configured(prepared=None):
    return launch.compose_config(
        launch.build_overrides("rl", prepared or prepared_budget_launch(), ENV, recipe_config=RECIPE)
    )


def test_separate_recipe_satisfies_native_trainer_topology_and_batch_invariants():
    cfg = configured()
    actor = cfg.actor_rollout_ref.actor
    rollout = cfg.actor_rollout_ref.rollout
    separate = cfg.trainer.v1.separate_async
    assert cfg.trainer.use_v1 and cfg.transfer_queue.enable
    assert cfg.trainer.v1.trainer_mode == "separate_async"
    assert cfg.trainer.nnodes == cfg.trainer.n_gpus_per_node == 1
    assert rollout.nnodes == rollout.n_gpus_per_node == rollout.tensor_model_parallel_size == 1
    assert not cfg.distillation.enabled and cfg.distillation.nnodes == 0
    assert rollout.checkpoint_engine.backend == "nccl"
    assert separate.parameter_sync_step == 1
    assert cfg.data.train_batch_size == separate.parameter_sync_step * actor.ppo_mini_batch_size
    assert separate.hybrid_rollout.enable_switch is False


def test_separate_recipe_preserves_budget_admission_and_training_contract():
    prepared = prepared_budget_launch()
    cfg = configured(prepared)
    model = cfg.actor_rollout_ref.model
    actor = cfg.actor_rollout_ref.actor
    rollout = cfg.actor_rollout_ref.rollout
    framework = rollout.custom.agent_framework
    assert cfg.algorithm.adv_estimator == "grpo" and rollout.n == 4
    assert framework.termination_policy == "budget-terminal-v1"
    assert framework.mask_unfinished_episode is False
    assert framework.require_finished_episode and framework.fail_on_rollout_error
    assert (
        framework.require_verifier_reward and framework.require_trajectory_dump and framework.require_version_evidence
    )
    assert framework.trajectory_postprocessor_kwargs == prepared["postprocessor"]
    assert framework.max_generated_tokens_per_episode == LIMITS["max_generated_tokens"]
    assert cfg.data.max_prompt_length + cfg.data.max_response_length == rollout.max_model_len == 32768
    assert actor.ppo_max_token_len_per_gpu == rollout.log_prob_max_token_len_per_gpu == 32768
    assert model.lora_rank == 16 and model.lora_alpha == 32 and model.lora.merge
    assert model.override_config.attn_implementation == "sdpa" and not model.use_remove_padding
    assert actor.fsdp_config.entropy_from_logits_with_chunking
    assert actor.fsdp_config.entropy_from_logits_chunk_size == 256
    assert cfg.trainer.total_training_steps == 2 and cfg.trainer.save_freq == 1


@pytest.mark.parametrize("field,value", [("max_generated_tokens", 14336), ("trajectory_capacity", 65536)])
def test_separate_recipe_rejects_mismatched_operator_budget(field, value):
    prepared = prepared_budget_launch()
    prepared["postprocessor"]["budget_limits"][field] = value
    prepared["postprocessor"]["policy_template"]["budget_limits"][field] = value
    with pytest.raises(ValueError, match="budget|capacity"):
        configured(prepared)
