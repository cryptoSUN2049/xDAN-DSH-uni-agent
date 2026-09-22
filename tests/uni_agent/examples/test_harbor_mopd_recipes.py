"""Recipe contracts isolate MiMo objectives and preserve the native baseline."""

import pytest
from omegaconf import OmegaConf

from examples.harbor_mopd.launch import recipe_overlay, validate_recipe
from tests.uni_agent.examples.test_harbor_mopd_config import configured


def recipe_config(name, **parameters):
    return OmegaConf.merge(configured(), recipe_overlay(name, **parameters))


def test_baseline_overlay_is_empty():
    assert OmegaConf.to_container(recipe_overlay("native-pg")) == {}


@pytest.mark.parametrize("name", ["pg-sequence", "top64-reverse", "flash-orm"])
def test_new_recipes_use_trajectory_average_without_native_ppo(name):
    parameters = {"orm_alpha": 0.3, "is_lower": 0.5, "is_upper": 2.0} if name == "flash-orm" else {}
    cfg = recipe_config(name, **parameters)
    validate_recipe(cfg, name)
    assert cfg.actor_rollout_ref.actor.loss_agg_mode == "seq-mean-token-mean"
    assert not cfg.distillation.distillation_loss.use_policy_gradient
    assert cfg.distillation.distillation_loss.loss_max_clamp is None
    assert cfg.distillation.distillation_loss.log_prob_min_clamp is None
    assert not cfg.actor_rollout_ref.model.use_fused_kernels
    assert cfg.actor_rollout_ref.rollout.custom.agent_framework.require_single_policy_version
    assert cfg.actor_rollout_ref.rollout.n == (4 if name == "flash-orm" else 1)


def test_top64_is_explicit_reverse_and_not_renamed_forward():
    cfg = recipe_config("top64-reverse")
    assert cfg.distillation.distillation_loss.loss_mode == "mopd_top64_reverse"
    assert cfg.distillation.distillation_loss.topk == 64
    assert not cfg.distillation.distillation_loss.use_task_rewards


def test_flash_has_no_invented_paper_hyperparameters():
    with pytest.raises(ValueError, match="explicit"):
        recipe_overlay("flash-orm")
    with pytest.raises(ValueError, match="only"):
        recipe_overlay("pg-sequence", orm_alpha=0.3)


@pytest.mark.parametrize(
    "params",
    [
        {"orm_alpha": -1, "is_lower": 0.5, "is_upper": 2},
        {"orm_alpha": float("nan"), "is_lower": 0.5, "is_upper": 2},
        {"orm_alpha": 1, "is_lower": 0, "is_upper": 2},
        {"orm_alpha": 1, "is_lower": 1.1, "is_upper": 2},
        {"orm_alpha": 1, "is_lower": 0.5, "is_upper": float("inf")},
    ],
)
def test_flash_invalid_parameters_rejected(params):
    with pytest.raises(ValueError):
        recipe_overlay("flash-orm", **params)


@pytest.mark.parametrize(
    "key,value",
    [
        ("actor_rollout_ref.actor.loss_agg_mode", "token-mean"),
        ("actor_rollout_ref.model.use_fused_kernels", True),
        ("actor_rollout_ref.actor.ulysses_sequence_parallel_size", 2),
        ("actor_rollout_ref.actor.fsdp_config.ulysses_sequence_parallel_size", 2),
        ("actor_rollout_ref.actor.fsdp_config.pad_to_length", True),
        ("actor_rollout_ref.actor.ppo_epochs", 2),
        ("algorithm.rollout_correction.rollout_is", "token"),
        ("actor_rollout_ref.rollout.temperature", 0.7),
        ("actor_rollout_ref.rollout.n", 1),
    ],
)
def test_flash_contract_rejects_silent_algorithm_changes(key, value):
    cfg = recipe_config("flash-orm", orm_alpha=0.3, is_lower=0.5, is_upper=2)
    OmegaConf.update(cfg, key, value, force_add=True)
    with pytest.raises(ValueError):
        validate_recipe(cfg, "flash-orm")


def test_unknown_recipe_is_rejected():
    with pytest.raises(ValueError, match="Unknown"):
        recipe_overlay("invented")


@pytest.mark.parametrize("name", ["pg-sequence", "top64-reverse", "flash-orm"])
def test_launcher_overrides_reach_native_dataclass(tmp_path, name):
    from examples.harbor_mopd.launch import build_overrides
    from examples.harbor_opd_rl.launch import compose_config
    from tests.uni_agent.examples.test_harbor_opd_rl_recipe import prepared_launch
    from verl.utils.config import omega_conf_to_dataclass

    parameters = {"orm_alpha": 0.3, "is_lower": 0.5, "is_upper": 2} if name == "flash-orm" else {}
    registry = {
        "student": {"model_path": "/student"},
        "teachers": {domain: {"model_path": f"/{domain}"} for domain in ("swe", "terminal")},
    }
    allocation = {
        "schema": "harbor-mopd-allocation-v1",
        "owner": "test",
        "schedule_reference": "test",
        "gpu_uuids": ["GPU-a", "GPU-b", "GPU-c"],
        "max_steps": 2,
        "budget_usd": 10,
    }
    receipt = {"files": {split: {"path": f"/{split}.parquet"} for split in ("train", "validation")}}
    cfg = compose_config(
        build_overrides(
            prepared_launch(),
            registry,
            receipt,
            allocation,
            run_root=tmp_path / "run",
            tool_parser="hermes",
            target_step=1,
            recipe=name,
            **parameters,
        )
    )
    validate_recipe(cfg, name)
    loss = omega_conf_to_dataclass(cfg.distillation).distillation_loss
    assert loss.loss_mode.startswith("mopd_")
    assert loss.loss_settings.use_topk == (name == "top64-reverse")
