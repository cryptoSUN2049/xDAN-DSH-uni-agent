"""CPU composition and native dataclass/loss contracts for the MOPD recipe."""

from pathlib import Path

import pytest
from hydra import compose, initialize_config_dir
from omegaconf import OmegaConf, open_dict

ROOT = Path(__file__).resolve().parents[3]


def configured():
    """Compose production YAML without creating models, Ray actors or controllers."""
    with initialize_config_dir(config_dir=str(ROOT / "verl/verl/trainer/config"), version_base=None):
        native = compose(config_name="ppo_trainer")
    with open_dict(native):
        cfg = OmegaConf.merge(
            native,
            OmegaConf.load(ROOT / "examples/harbor_opd_rl/base.yaml"),
            OmegaConf.load(ROOT / "examples/harbor_mopd/mopd.yaml"),
        )
    required = {
        "trainer.nnodes": 1,
        "trainer.n_gpus_per_node": 1,
        "trainer.experiment_name": "cpu-compose-only",
        "trainer.total_training_steps": 2,
        "trainer.default_local_dir": "/not-created/checkpoints",
        "trainer.rollout_data_dir": "/not-created/rollout",
        "trainer.validation_data_dir": "/not-created/validation",
        "data.train_files": "/not-read/train.parquet",
        "data.val_files": "/not-read/validation.parquet",
        "actor_rollout_ref.model.path": "/not-loaded/student",
        "actor_rollout_ref.rollout.multi_turn.format": "hermes",
        "actor_rollout_ref.rollout.custom.agent_framework.log_dir": "/not-created/agent",
        "distillation.nnodes": 1,
        "distillation.n_gpus_per_node": 2,
        "distillation.teacher_models.teacher_swe.model_path": "/not-loaded/swe",
        "distillation.teacher_models.teacher_terminal.model_path": "/not-loaded/terminal",
    }
    for key, value in required.items():
        OmegaConf.update(cfg, key, value)
    return cfg


def test_native_teacher_dataclass_removes_only_placeholder_and_preserves_routes():
    from verl.utils.config import omega_conf_to_dataclass

    cfg = configured()
    assert set(cfg.distillation.teacher_models) == {"teacher_model", "teacher_swe", "teacher_terminal"}
    native = omega_conf_to_dataclass(cfg.distillation)
    assert set(native.teacher_models) == {"swe", "terminal"}
    assert native.teacher_key == "teacher_domain"
    assert native.teacher_models["swe"].model_path == "/not-loaded/swe"
    assert native.teacher_models["terminal"].model_path == "/not-loaded/terminal"
    assert sum(teacher.world_size for teacher in native.teacher_models.values()) == 2
    for teacher in native.teacher_models.values():
        assert teacher.inference.max_model_len >= cfg.actor_rollout_ref.rollout.max_model_len + 1
        assert teacher.inference.prompt_length == cfg.data.max_prompt_length + cfg.data.max_response_length
        assert teacher.inference.response_length == 1


def test_teacher_pool_cannot_silently_share_one_gpu():
    from hydra.errors import InstantiationException

    from verl.utils.config import omega_conf_to_dataclass

    cfg = configured()
    cfg.distillation.n_gpus_per_node = 1
    with pytest.raises(InstantiationException, match="must match.*resource pool"):
        omega_conf_to_dataclass(cfg.distillation)


def test_duplicate_domain_is_rejected_by_native_config():
    from hydra.errors import InstantiationException

    from verl.utils.config import omega_conf_to_dataclass

    cfg = configured()
    cfg.distillation.teacher_models.teacher_terminal.key = "swe"
    with pytest.raises(InstantiationException, match="Duplicate teacher key"):
        omega_conf_to_dataclass(cfg.distillation)


def test_recipe_has_one_untruncated_sample_and_one_update_per_batch():
    cfg = configured()
    actor = cfg.actor_rollout_ref.actor
    rollout = cfg.actor_rollout_ref.rollout
    assert cfg.trainer.v1.trainer_mode == "sync"
    assert actor.ppo_epochs == 1
    assert actor.ppo_mini_batch_size == cfg.data.train_batch_size
    assert rollout.n == 1
    assert rollout.temperature == 1.0 and rollout.top_p == 1.0 and rollout.top_k == -1
    assert rollout.do_sample and rollout.calculate_log_probs
    assert not cfg.data.filter_overlong_prompts
    assert cfg.data.truncation == "error"
    assert not cfg.data.shuffle and not actor.shuffle
    assert actor.loss_agg_mode == "token-mean"
    assert not cfg.algorithm.rollout_correction.bypass_mode
    assert cfg.algorithm.rollout_correction.rollout_is is None
    assert cfg.algorithm.rollout_correction.rollout_rs is None
    # A changed batch size must keep one full optimizer minibatch.
    cfg.data.train_batch_size = 6
    assert actor.ppo_mini_batch_size == 6


def test_pure_pg_native_loss_and_dual_clip_fallback():
    import torch

    from verl.trainer.ppo.core_algos import get_policy_loss_fn
    from verl.utils.config import omega_conf_to_dataclass

    cfg = configured()
    loss = omega_conf_to_dataclass(cfg.distillation).distillation_loss
    assert loss.loss_mode == "k1" and loss.use_policy_gradient
    assert not loss.use_task_rewards
    assert loss.loss_max_clamp == 5.0
    assert loss.log_prob_min_clamp is None
    assert loss.loss_settings.use_estimator and not loss.loss_settings.use_topk
    # DistillationLossConfig exposes no dual-clip field. Verify the actual native
    # fallback numerically instead of claiming actor.clip_ratio_c controls it.
    assert "clip_ratio_c" not in dict(loss)
    objective, _ = get_policy_loss_fn(loss.policy_loss_mode)(
        old_log_prob=torch.tensor([[-5.0]]),
        log_prob=torch.tensor([[-1.0]], requires_grad=True),
        advantages=torch.tensor([[-1.0]]),
        response_mask=torch.ones(1, 1),
        loss_agg_mode=cfg.actor_rollout_ref.actor.loss_agg_mode,
        config=loss,
    )
    assert objective.item() == pytest.approx(3.0)


def test_harbor_registration_and_verifier_evidence_are_preserved():
    cfg = configured()
    assert cfg.actor_rollout_ref.rollout.agent.agent_loop_manager_class == (
        "uni_agent.framework.entry.AgentFrameworkRolloutAdapter"
    )
    framework = cfg.actor_rollout_ref.rollout.custom.agent_framework
    assert framework.fail_on_rollout_error and framework.require_finished_episode
    assert framework.require_verifier_reward and framework.require_trajectory_dump
    assert framework.require_version_evidence
    assert framework.trajectory_postprocessor_fqn == (
        "uni_agent.tasks.harbor_dsh.registration.validate_registered_trajectories"
    )
    assert framework.agent_runners.task.runner_fqn == "uni_agent.framework.task_runner.run_task"
    assert cfg.actor_rollout_ref.actor.checkpoint.save_contents == ["model", "optimizer", "extra"]
    assert cfg.actor_rollout_ref.actor.checkpoint.load_contents == ["model", "optimizer", "extra"]


@pytest.mark.parametrize(
    "field",
    [
        "actor_rollout_ref.model.path",
        "data.train_files",
        "data.val_files",
        "trainer.n_gpus_per_node",
        "distillation.n_gpus_per_node",
        "distillation.teacher_models.teacher_swe.model_path",
        "distillation.teacher_models.teacher_terminal.model_path",
    ],
)
def test_paths_and_allocations_have_no_live_defaults(field):
    overlay = OmegaConf.load(ROOT / "examples/harbor_mopd/mopd.yaml")
    value = OmegaConf.to_container(overlay, resolve=False)
    for key in field.split("."):
        value = value[key]
    assert value == "???"
