from copy import deepcopy
from pathlib import Path

import pytest
from omegaconf import OmegaConf

from examples.harbor_opd_rl import launch
from tests.uni_agent.examples.test_harbor_opd_rl_recipe import prepared_launch

ROOT = Path(__file__).resolve().parents[3]
SMOKE = ROOT / "examples/mimo_dsh_rl/mimo-9b-smoke.yaml"
RECIPE = ROOT / "examples/mimo_dsh_rl/mimo-9b-budget-terminal.yaml"
ENV = {"STUDENT_MODEL_PATH": "/models/mimo", "TOOL_PARSER": "qwen3_coder", "TEACHER_MODEL_PATH": "/models/teacher"}
LIMITS = {"max_generated_tokens": 20480, "trajectory_capacity": 32768}
POLICY = "budget-terminal-v1"


def prepared_budget_launch():
    prepared = prepared_launch()
    prepared["postprocessor"].update(
        termination_policy=POLICY,
        budget_limits=dict(LIMITS),
        policy_template={"termination_policy": POLICY, "budget_limits": dict(LIMITS)},
        mimo_binding={"path": "/private/task/mimo-binding.json", "sha256": "sha256:" + "a" * 64},
    )
    return prepared


def overlay(tmp_path, changes=None):
    cfg = OmegaConf.load(SMOKE)
    cfg.actor_rollout_ref.rollout.custom.agent_framework.termination_policy = POLICY
    cfg.actor_rollout_ref.rollout.custom.agent_framework.mask_unfinished_episode = False
    if changes:
        cfg = OmegaConf.merge(cfg, changes)
    path = tmp_path / "budget.yaml"
    OmegaConf.save(cfg, path)
    return path


def test_new_recipe_is_explicit_and_original_remains_completed_only():
    old = OmegaConf.load(SMOKE)
    assert OmegaConf.select(old, launch.FRAMEWORK + ".termination_policy", default="completed-only") == "completed-only"
    prepared = prepared_budget_launch()
    cfg = launch.compose_config(launch.build_overrides("rl", prepared, ENV, recipe_config=RECIPE))
    framework = cfg.actor_rollout_ref.rollout.custom.agent_framework
    assert framework.termination_policy == POLICY
    assert framework.mask_unfinished_episode is False
    assert framework.require_finished_episode and framework.fail_on_rollout_error
    assert (
        framework.require_verifier_reward and framework.require_trajectory_dump and framework.require_version_evidence
    )
    assert framework.max_generated_tokens_per_episode == LIMITS["max_generated_tokens"]
    assert cfg.data.max_prompt_length + cfg.data.max_response_length == LIMITS["trajectory_capacity"]
    assert cfg.actor_rollout_ref.rollout.max_model_len == LIMITS["trajectory_capacity"]
    assert cfg.trainer.n_gpus_per_node == cfg.actor_rollout_ref.rollout.tensor_model_parallel_size == 1
    assert cfg.actor_rollout_ref.rollout.checkpoint_engine.backend == "naive"
    assert cfg.algorithm.adv_estimator == "grpo" and cfg.actor_rollout_ref.rollout.n == 4
    assert framework.trajectory_postprocessor_kwargs == prepared["postprocessor"]


@pytest.mark.parametrize(
    "fault", ["unprepared", "different-policy", "limits", "template", "bool-limit", "missing-mimo"]
)
def test_budget_recipe_rejects_unbound_or_inconsistent_prepared_policy(tmp_path, fault):
    prepared = prepared_budget_launch()
    post = prepared["postprocessor"]
    if fault == "unprepared":
        prepared = prepared_launch()
    elif fault == "different-policy":
        post["termination_policy"] = "completed-only"
    elif fault == "limits":
        post["budget_limits"]["max_generated_tokens"] = 14336
    elif fault == "template":
        post["policy_template"]["budget_limits"]["trajectory_capacity"] = 65536
    elif fault == "bool-limit":
        post["budget_limits"]["max_generated_tokens"] = True
        post["policy_template"]["budget_limits"]["max_generated_tokens"] = True
    elif fault == "missing-mimo":
        post.pop("mimo_binding")
    with pytest.raises(ValueError, match="budget|termination|MiMo"):
        launch.build_overrides("rl", prepared, ENV, recipe_config=overlay(tmp_path))


@pytest.mark.parametrize("mode", ["opd", "hybrid"])
def test_budget_mode_cannot_silently_enable_distillation(tmp_path, mode):
    with pytest.raises(ValueError, match="GRPO|RL"):
        launch.build_overrides(mode, prepared_budget_launch(), ENV, recipe_config=overlay(tmp_path))


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_generated_tokens_per_episode", 14336),
        ("mask_unfinished_episode", True),
        ("require_finished_episode", False),
        ("fail_on_rollout_error", False),
        ("require_verifier_reward", False),
        ("require_version_evidence", False),
        ("require_trajectory_dump", False),
    ],
)
def test_budget_mode_preserves_admission_and_loss_contract(tmp_path, field, value):
    change = {"actor_rollout_ref": {"rollout": {"custom": {"agent_framework": {field: value}}}}}
    with pytest.raises(ValueError, match="budget|requires|mask"):
        launch.build_overrides("rl", prepared_budget_launch(), ENV, recipe_config=overlay(tmp_path, change))


@pytest.mark.parametrize(
    "change",
    [
        {"algorithm": {"adv_estimator": "gae"}},
        {"data": {"max_response_length": 61440}},
        {"actor_rollout_ref": {"rollout": {"max_model_len": 65536}}},
        {"actor_rollout_ref": {"actor": {"ppo_max_token_len_per_gpu": 16384}}},
        {"actor_rollout_ref": {"rollout": {"log_prob_max_token_len_per_gpu": 16384}}},
    ],
)
def test_budget_mode_rejects_runtime_capacity_or_algorithm_drift(tmp_path, change):
    with pytest.raises(ValueError, match="budget|GRPO|capacity"):
        launch.build_overrides("rl", prepared_budget_launch(), ENV, recipe_config=overlay(tmp_path, change))


def test_prepared_budget_policy_cannot_downgrade_to_old_recipe():
    prepared = prepared_budget_launch()
    snapshot = deepcopy(prepared)
    with pytest.raises(ValueError, match="termination"):
        launch.build_overrides("rl", prepared, ENV, recipe_config=SMOKE)
    assert prepared == snapshot
