"""Compose the experimental recipe against the paired VERL's actual Hydra schema."""

from pathlib import Path

import pytest
from hydra import compose, initialize_config_dir

from examples.harbor_opd_rl.launch import build_overrides

ROOT = Path(__file__).resolve().parents[3]


def prepared_launch():
    return {
        "schema": "dsh.harbor-m2-launch.v1",
        "environment": {
            "TRAIN_FILE": "/private/run/train.parquet",
            "TEST_FILE": "/private/run/heldout.parquet",
            "TASK_CONFIG": "/private/run/task.yaml",
            "RUN_ROOT": "/private/run",
            "MODEL_ID": "operator-student",
        },
        "registration": {"controller_url": "http://127.0.0.1:8888", "token_file": "/private/token"},
        "postprocessor": {"artifact_root": "/private/run/artifacts", "controller_id": "controller"},
    }


def configured(mode, environment=None):
    env = {"STUDENT_MODEL_PATH": "/models/student", "TEACHER_MODEL_PATH": "/models/teacher", "TOOL_PARSER": "hermes"}
    if environment is not None:
        env = environment
    with initialize_config_dir(config_dir=str(ROOT / "verl/verl/trainer/config"), version_base=None):
        return compose(config_name="ppo_trainer", overrides=build_overrides(mode, prepared_launch(), env))


@pytest.mark.parametrize(
    "mode,topology,rollout_nodes,teacher_nodes,task_reward,total_gpus",
    [
        ("rl", "separate_async", 1, 0, True, 2),
        ("opd", "colocate_async", 0, 1, False, 2),
        ("hybrid", "separate_async", 1, 1, True, 3),
    ],
)
def test_native_modes_compose(mode, topology, rollout_nodes, teacher_nodes, task_reward, total_gpus):
    cfg = configured(mode)
    assert cfg.trainer.use_v1 and cfg.transfer_queue.enable
    assert cfg.trainer.v1.trainer_mode == topology
    assert cfg.actor_rollout_ref.rollout.nnodes == rollout_nodes
    assert cfg.distillation.nnodes == teacher_nodes
    assert cfg.distillation.enabled == (mode != "rl")
    assert cfg.distillation.distillation_loss.use_task_rewards == task_reward
    assert cfg.actor_rollout_ref.model.lora_rank > 0
    assert cfg.actor_rollout_ref.actor.strategy == "fsdp"
    assert cfg.actor_rollout_ref.rollout.checkpoint_engine.backend == "nccl"
    assert cfg.trainer.n_gpus_per_node + rollout_nodes + teacher_nodes == total_gpus
    if topology == "separate_async":
        assert cfg.data.train_batch_size == (
            cfg.trainer.v1.separate_async.parameter_sync_step * cfg.actor_rollout_ref.actor.ppo_mini_batch_size
        )
    if mode != "rl":
        assert cfg.distillation.distillation_loss.loss_mode == "k1"
        assert cfg.distillation.distillation_loss.use_policy_gradient
        assert cfg.distillation.teacher_models.teacher_model.model_path == "/models/teacher"
        assert cfg.distillation.teacher_models.teacher_model.inference.tensor_model_parallel_size == 1


def test_rl_does_not_need_or_configure_teacher():
    cfg = configured("rl", {"STUDENT_MODEL_PATH": "/models/student", "TOOL_PARSER": "hermes"})
    assert cfg.distillation.enabled is False
    assert cfg.distillation.nnodes == 0
    assert cfg.distillation.teacher_models.teacher_model.model_path is None


@pytest.mark.parametrize("mode", ["rl", "opd", "hybrid"])
def test_preserves_uni_agent_harbor_admission(mode):
    cfg = configured(mode)
    framework = cfg.actor_rollout_ref.rollout.custom.agent_framework
    assert cfg.actor_rollout_ref.rollout.agent.agent_loop_manager_class == (
        "uni_agent.framework.entry.AgentFrameworkRolloutAdapter"
    )
    assert framework.fail_on_rollout_error and framework.require_finished_episode
    assert framework.require_verifier_reward and framework.require_trajectory_dump
    assert framework.trajectory_postprocessor_pass_context
    assert framework.trajectory_postprocessor_fqn == (
        "uni_agent.tasks.harbor_dsh.registration.validate_registered_trajectories"
    )
    runner = framework.agent_runners.task
    assert runner.trajectory_selection == "all"
    assert runner.runner_fqn == "uni_agent.framework.task_runner.run_task"
    assert runner.runner_kwargs.harbor_route_registration == prepared_launch()["registration"]
    assert runner.runner_kwargs.task_config_path == "/private/run/task.yaml"
    assert cfg.data.train_files == "/private/run/train.parquet"
    assert cfg.data.val_files == "/private/run/heldout.parquet"


@pytest.mark.parametrize("mode", ["opd", "hybrid"])
def test_teacher_model_must_be_explicit(mode):
    with pytest.raises(ValueError, match="TEACHER_MODEL_PATH"):
        build_overrides(mode, prepared_launch(), {"STUDENT_MODEL_PATH": "/models/student", "TOOL_PARSER": "hermes"})


def test_student_model_and_prepared_schema_required():
    with pytest.raises(ValueError, match="STUDENT_MODEL_PATH"):
        build_overrides("rl", prepared_launch(), {})
    with pytest.raises(ValueError, match="schema"):
        build_overrides("rl", {}, {"STUDENT_MODEL_PATH": "/models/student", "TOOL_PARSER": "hermes"})
    with pytest.raises(ValueError, match="mode"):
        build_overrides("sync", prepared_launch(), {"STUDENT_MODEL_PATH": "/models/student", "TOOL_PARSER": "hermes"})


def test_print_config_does_not_start_training(tmp_path, monkeypatch, capsys):
    import json

    from examples.harbor_opd_rl import launch

    prepared = tmp_path / "launch.json"
    prepared.write_text(json.dumps(prepared_launch()))
    monkeypatch.setenv("STUDENT_MODEL_PATH", "/models/student")
    monkeypatch.setenv("TOOL_PARSER", "hermes")
    monkeypatch.setattr("sys.argv", ["launch", "--mode", "rl", "--launch", str(prepared), "--print-config"])

    def no_launch(*args, **kwargs):
        pytest.fail("print-config must not execute the trainer")

    monkeypatch.setattr(launch.subprocess, "run", no_launch)
    launch.main()
    assert "trainer_mode: separate_async" in capsys.readouterr().out


def test_model_tool_parser_is_explicit():
    with pytest.raises(ValueError, match="TOOL_PARSER"):
        build_overrides("rl", prepared_launch(), {"STUDENT_MODEL_PATH": "/models/student"})


@pytest.mark.parametrize("mode", ["rl", "opd", "hybrid"])
def test_native_teacher_dataclass_accepts_topology_and_context(mode):
    from verl.utils.config import omega_conf_to_dataclass

    cfg = configured(mode)
    distillation = omega_conf_to_dataclass(cfg.distillation)
    assert distillation.enabled == (mode != "rl")
    if mode != "rl":
        teacher = next(iter(distillation.teacher_models.values()))
        assert teacher.inference.max_model_len >= cfg.data.max_prompt_length + cfg.data.max_response_length + 1
        assert distillation.distillation_loss.loss_settings.use_estimator
        assert not distillation.distillation_loss.loss_settings.use_topk


@pytest.mark.parametrize("mode", ["rl", "opd", "hybrid"])
def test_async_lora_exports_merged_weights_for_native_checkpoint_engine(mode):
    cfg = configured(mode)
    # NCCL named-tensor transport does not carry adapter metadata. The native
    # merged export is required even when actor and rollout are colocated.
    assert cfg.actor_rollout_ref.rollout.checkpoint_engine.backend == "nccl"
    assert cfg.actor_rollout_ref.model.lora.merge is True
    assert cfg.actor_rollout_ref.model.lora_rank == 16
    assert cfg.actor_rollout_ref.model.lora_alpha == 32
