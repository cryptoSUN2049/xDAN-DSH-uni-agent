"""Native monitoring config and run identity survive prepared launcher binding."""

import json

import pytest
from omegaconf import OmegaConf

from examples.harbor_opd_rl import launch
from tests.uni_agent.examples.test_harbor_opd_rl_recipe import prepared_launch
from tests.uni_agent.examples.test_mimo_budget_recipe import ENV, ROOT, prepared_budget_launch

RECIPE = ROOT / "examples/mimo_dsh_rl/mimo-9b-observed.yaml"


def test_observed_recipe_preserves_native_monitoring_identity_and_training_contract():
    cfg = launch.compose_config(launch.build_overrides("rl", prepared_budget_launch(), ENV, recipe_config=RECIPE))
    assert list(cfg.trainer.logger) == ["console", "wandb", "rl_insight"]
    assert cfg.trainer.project_name == "xDAN-Verl-Uni-agent-Harbor-rl-opd"
    assert cfg.trainer.experiment_name == "mimo9b-001661-r11"
    assert cfg.transfer_queue.metrics.enabled is True and cfg.transfer_queue.metrics.port == 0
    assert cfg.actor_rollout_ref.rollout.disable_log_stats is False
    assert cfg.trainer.v1.trainer_mode == "separate_async"
    assert cfg.trainer.n_gpus_per_node == cfg.actor_rollout_ref.rollout.n_gpus_per_node == 1
    assert cfg.actor_rollout_ref.rollout.nnodes == 1
    assert cfg.actor_rollout_ref.rollout.checkpoint_engine.backend == "nccl"
    assert cfg.trainer.v1.separate_async.parameter_sync_step == cfg.data.train_batch_size == 1
    assert cfg.actor_rollout_ref.rollout.n == 4
    assert cfg.actor_rollout_ref.rollout.max_model_len == 32768
    framework = cfg.actor_rollout_ref.rollout.custom.agent_framework
    assert framework.termination_policy == "budget-terminal-v1"
    assert framework.max_generated_tokens_per_episode == 20480
    assert cfg.actor_rollout_ref.model.lora_rank == 16
    assert cfg.actor_rollout_ref.actor.fsdp_config.entropy_from_logits_with_chunking


@pytest.mark.parametrize("mode", ["rl", "opd", "hybrid"])
def test_experiment_name_default_preserves_legacy_mode_identity(mode):
    cfg = launch.compose_config(launch.build_overrides(mode, prepared_launch(), ENV))
    assert cfg.trainer.experiment_name == f"harbor-{mode}"


def test_explicit_experiment_name_overrides_recipe_name():
    cfg = launch.compose_config(
        launch.build_overrides(
            "rl", prepared_budget_launch(), ENV, recipe_config=RECIPE, experiment_name="mimo9b-001661-r12"
        )
    )
    assert cfg.trainer.experiment_name == "mimo9b-001661-r12"


@pytest.mark.parametrize("name", ["", "  ", True, 42])
def test_invalid_explicit_experiment_name_is_rejected(name):
    with pytest.raises(ValueError, match="experiment_name"):
        launch.build_overrides("rl", prepared_launch(), ENV, experiment_name=name)


def test_cli_experiment_name_reaches_actual_composed_config(tmp_path, monkeypatch, capsys):
    prepared = tmp_path / "launch.json"
    prepared.write_text(json.dumps(prepared_budget_launch()))
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(
        "sys.argv",
        [
            "launch",
            "--mode",
            "rl",
            "--launch",
            str(prepared),
            "--recipe-config",
            str(RECIPE),
            "--experiment-name",
            "mimo9b-001661-cli",
            "--print-config",
        ],
    )
    monkeypatch.setattr(launch.subprocess, "run", lambda *a, **k: pytest.fail("print-config must not train"))
    launch.main()
    cfg = OmegaConf.create(capsys.readouterr().out)
    assert cfg.trainer.experiment_name == "mimo9b-001661-cli"
    assert list(cfg.trainer.logger) == ["console", "wandb", "rl_insight"]


def test_native_entrypoint_remains_default():
    cfg = OmegaConf.create({"trainer": {"logger": ["console"]}})
    assert launch._training_entrypoint(cfg, observability_wrapper=False) == ["-m", "verl.trainer.main_ppo"]


def test_observability_entrypoint_is_fixed_and_explicit(tmp_path, monkeypatch):
    monkeypatch.setattr(launch, "ROOT", tmp_path)
    wrapper = tmp_path / "docs/verl-uni-agent-harbor-opd-rl/mimo_observability.py"
    wrapper.parent.mkdir(parents=True)
    wrapper.write_text("# prepared source placeholder\n")
    cfg = OmegaConf.create({"trainer": {"logger": ["console", "wandb", "rl_insight"]}})
    assert launch._training_entrypoint(cfg, observability_wrapper=True) == [str(wrapper)]


@pytest.mark.parametrize("logger,match", [(["console"], "rl_insight"), (["rl_insight"], "missing")])
def test_observability_entrypoint_rejects_unprepared_inputs(tmp_path, monkeypatch, logger, match):
    monkeypatch.setattr(launch, "ROOT", tmp_path)
    cfg = OmegaConf.create({"trainer": {"logger": logger}})
    with pytest.raises(ValueError, match=match):
        launch._training_entrypoint(cfg, observability_wrapper=True)


def test_cli_observability_flag_selects_child_without_changing_overrides(tmp_path, monkeypatch):
    from hydra.core.override_parser.overrides_parser import OverridesParser

    prepared = prepared_budget_launch()
    prepared["environment"]["RUN_ROOT"] = str(tmp_path)
    launch_path = tmp_path / "launch.json"
    launch_path.write_text(json.dumps(prepared))
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(
        "sys.argv",
        [
            "launch",
            "--mode",
            "rl",
            "--launch",
            str(launch_path),
            "--recipe-config",
            str(RECIPE),
            "--observability-wrapper",
        ],
    )
    selections = []

    def select(config, *, observability_wrapper):
        selections.append(observability_wrapper)
        return ["/verified/mimo_observability.py"]

    commands = []
    monkeypatch.setattr(launch, "_training_entrypoint", select)
    monkeypatch.setattr(launch, "preflight_training", lambda config: {})
    monkeypatch.setattr(launch.subprocess, "run", lambda cmd, **kwargs: commands.append(cmd))
    launch.main()
    assert selections == [True]
    assert commands[0][1:3] == ["/verified/mimo_observability.py", "--config-name=ppo_trainer"]
    hydra_dirs = [
        item.value()
        for item in OverridesParser.create().parse_overrides(commands[0][3:])
        if item.key_or_group == "hydra.run.dir"
    ]
    assert hydra_dirs == [str(tmp_path.resolve() / "hydra")]
    cfg = launch.compose_config(commands[0][3:])
    assert cfg.trainer.experiment_name == "mimo9b-001661-r11"
    assert list(cfg.trainer.logger) == ["console", "wandb", "rl_insight"]
