"""Compose the bounded MiMo engineering smoke through the existing launcher."""

import json
from pathlib import Path

import pytest
from omegaconf import OmegaConf

from examples.harbor_opd_rl import launch
from tests.uni_agent.examples.test_harbor_launch_preflight import cli_setup
from tests.uni_agent.examples.test_harbor_opd_rl_recipe import prepared_launch

RECIPE = Path(__file__).resolve().parents[3] / "examples/mimo_dsh_rl/mimo-9b-smoke.yaml"
ENVIRONMENT = {"STUDENT_MODEL_PATH": "/models/mimo-9b", "TOOL_PARSER": "qwen3"}


def test_optional_overlay_precedes_prepared_routes_and_explicit_environment(tmp_path):
    overlay = tmp_path / "overlay.yaml"
    OmegaConf.save(
        {
            "trainer": {"total_training_steps": 2, "default_local_dir": "/wrong"},
            "data": {"train_files": "/wrong", "val_files": "/wrong"},
            "actor_rollout_ref": {
                "model": {"path": "/wrong"},
                "rollout": {
                    "multi_turn": {"format": "wrong"},
                    "custom": {
                        "agent_framework": {
                            "trajectory_postprocessor_kwargs": {"artifact_root": "/wrong"},
                            "agent_runners": {
                                "task": {
                                    "max_concurrent_sessions": 4,
                                    "runner_kwargs": {
                                        "task_config_path": "/wrong",
                                        "model_name": "wrong",
                                        "harbor_route_registration": {"controller_url": "http://wrong"},
                                    },
                                }
                            },
                        }
                    },
                },
            },
        },
        overlay,
    )
    prepared = prepared_launch()
    prepared["environment"]["MAX_CONCURRENT_SESSIONS"] = "1"
    cfg = launch.compose_config(launch.build_overrides("rl", prepared, ENVIRONMENT, recipe_config=overlay))
    framework = cfg.actor_rollout_ref.rollout.custom.agent_framework
    runner = framework.agent_runners.task
    assert cfg.trainer.total_training_steps == 2
    assert cfg.trainer.default_local_dir == "/private/run/rl-training/checkpoints"
    assert cfg.actor_rollout_ref.model.path == ENVIRONMENT["STUDENT_MODEL_PATH"]
    assert cfg.actor_rollout_ref.rollout.multi_turn.format == "qwen3"
    assert cfg.data.train_files == prepared["environment"]["TRAIN_FILE"]
    assert cfg.data.val_files == prepared["environment"]["TEST_FILE"]
    assert framework.trajectory_postprocessor_kwargs == prepared["postprocessor"]
    assert runner.max_concurrent_sessions == 1
    assert runner.runner_kwargs.harbor_route_registration == prepared["registration"]
    assert runner.runner_kwargs.task_config_path == prepared["environment"]["TASK_CONFIG"]
    assert runner.runner_kwargs.model_name == prepared["environment"]["MODEL_ID"]
    assert runner.runner_kwargs.require_result is True


def test_mimo_smoke_composes_native_single_gpu_and_complete_context_budget():
    cfg = launch.compose_config(launch.build_overrides("rl", prepared_launch(), ENVIRONMENT, recipe_config=RECIPE))
    assert cfg.trainer.v1.trainer_mode == "colocate_async"
    assert cfg.trainer.nnodes == cfg.trainer.n_gpus_per_node == 1
    assert cfg.actor_rollout_ref.rollout.nnodes == cfg.distillation.nnodes == 0
    assert cfg.distillation.enabled is False
    assert cfg.trainer.total_training_steps == 2 and cfg.trainer.save_freq == 1
    assert cfg.trainer.test_freq == -1 and cfg.trainer.val_before_train is False
    assert cfg.data.train_batch_size == 1
    assert cfg.data.seed == cfg.actor_rollout_ref.rollout.seed == cfg.actor_rollout_ref.actor.fsdp_config.seed == 42
    assert cfg.data.max_prompt_length == 2048 and cfg.data.max_response_length == 14336
    model, actor, rollout = cfg.actor_rollout_ref.model, cfg.actor_rollout_ref.actor, cfg.actor_rollout_ref.rollout
    assert model.lora_rank == 16 and model.lora.merge and model.enable_gradient_checkpointing
    assert actor.use_dynamic_bsz and actor.ppo_max_token_len_per_gpu == 16384
    assert actor.use_torch_compile is False and actor.fsdp_config.use_torch_compile is False
    assert actor.fsdp_config.param_offload and actor.fsdp_config.optimizer_offload
    assert rollout.n == 4 and rollout.max_model_len == 16384
    assert rollout.prompt_length + rollout.response_length == rollout.max_model_len
    assert rollout.enforce_eager and rollout.free_cache_engine and not rollout.layered_summon
    assert rollout.engine_kwargs.vllm.reasoning_parser == "deepseek_r1"
    assert rollout.engine_kwargs.vllm.cpu_offload_gb == 0
    assert rollout.log_prob_use_dynamic_bsz and rollout.log_prob_max_token_len_per_gpu == 16384
    framework = rollout.custom.agent_framework
    assert framework.max_generated_tokens_per_episode == 14336
    assert framework.agent_runners.task.max_concurrent_sessions == 1
    assert framework.fail_on_rollout_error and framework.require_verifier_reward and framework.require_version_evidence
    assert framework.require_finished_episode and framework.require_trajectory_dump


def test_overlay_cli_print_never_loads_model_or_starts_trainer(tmp_path, monkeypatch, capsys):
    cli_setup(tmp_path, monkeypatch, "--recipe-config", str(RECIPE), "--print-config")
    monkeypatch.setattr(launch, "preflight_training", lambda *a: pytest.fail("print must not load model"))
    monkeypatch.setattr(launch.subprocess, "run", lambda *a, **k: pytest.fail("print must not launch"))
    launch.main()
    cfg = OmegaConf.create(capsys.readouterr().out)
    assert cfg.trainer.v1.trainer_mode == "colocate_async"
    assert cfg.actor_rollout_ref.rollout.engine_kwargs.vllm.reasoning_parser == "deepseek_r1"
    assert not (tmp_path / "run").exists()


def test_overlay_preflight_preserves_epoch_and_explicit_resume_budget(tmp_path, monkeypatch, capsys):
    checkpoint = tmp_path / "global_step_1"
    (checkpoint / "actor").mkdir(parents=True)
    (checkpoint / "data.pt").write_bytes(b"presence only; never loaded")
    cli_setup(
        tmp_path,
        monkeypatch,
        "--recipe-config",
        str(RECIPE),
        "--preflight-only",
        "--resume-from-path",
        str(checkpoint),
        "--total-training-steps",
        "3",
    )
    monkeypatch.setattr(
        launch, "preflight_training", lambda cfg: launch.finalize_training_plan(cfg, train_rows=1, validation_rows=1)
    )
    monkeypatch.setattr(launch.subprocess, "run", lambda *a, **k: pytest.fail("preflight must not launch"))
    launch.main()
    report = json.loads(capsys.readouterr().out)
    assert report["total_training_steps"] == report["total_epochs"] == 3
    assert report["save_freq"] == 1 and report["resume_mode"] == "resume_path"
    assert report["resume_from_path"] == str(checkpoint)
    assert not (tmp_path / "run").exists()
