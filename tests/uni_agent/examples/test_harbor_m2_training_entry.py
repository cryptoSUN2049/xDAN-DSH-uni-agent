import json
import os
import subprocess
import sys
from pathlib import Path

import pyarrow.parquet as pq
import pytest
import yaml
from hydra.core.override_parser.overrides_parser import OverridesParser

from deployment.services.harbor_run_controller import digest
from examples.harbor.prepare_m2_training import prepare_training, task_digest
from examples.harbor.train_m2_online_rl import build_overrides
from tests.uni_agent.deployment.test_harbor_run_controller import make_spec

pytestmark = [pytest.mark.cpu, pytest.mark.level0]
REPO = Path(__file__).resolve().parents[3]


@pytest.fixture
def inputs(tmp_path):
    task = tmp_path / "task"
    task.mkdir()
    image = "sha256:" + "e" * 64
    (task / "task.toml").write_text('[environment]\ndocker_image = "' + image + '"\n')
    (task / "instruction.md").write_text("Write the fixed answer.\n")
    spec = make_spec(tmp_path)
    value = spec.model_dump(mode="json")
    value["policy_template"]["dsh_release"]["image_digest"] = image
    value["policy_template"]["task_refs"][0]["sha256"] = task_digest(task)
    spec_path = tmp_path / "run-spec.json"
    spec_path.write_text(json.dumps(value))
    spec_path.chmod(0o600)
    output = tmp_path / "prepared"
    return {
        "run_spec_path": spec_path,
        "task_dir": task,
        "output_dir": output,
        "task_config_path": output / "task.yaml",
        "registration_token_file": tmp_path / "registration-token",
        "worker_token_file": tmp_path / "worker-token",
        "train_count": 2,
        "heldout_count": 1,
    }


def test_preparation_binds_current_manifest_and_records_same_task_evaluation(inputs):
    launch_path = prepare_training(**inputs)
    launch = json.loads(launch_path.read_text())
    task = yaml.safe_load(inputs["task_config_path"].read_text())
    assert "gateway_port" not in task["policy"]
    assert task["policy"]["dsh_release"]["image_digest"] == "sha256:" + "e" * 64
    assert task["instruction"] == "Write the fixed answer.\n"
    assert launch["registration"]["run_spec_sha256"] == digest(json.loads(inputs["run_spec_path"].read_text()))
    train = pq.read_table(inputs["output_dir"] / "train.parquet").to_pylist()
    val = pq.read_table(inputs["output_dir"] / "heldout.parquet").to_pylist()
    assert len(train) == 2 and len(val) == 1
    assert {row["uid"] for row in train}.isdisjoint(row["uid"] for row in val)
    assert train[0]["prompt"] == val[0]["prompt"]
    assert train[0]["extra_info"]["tools_kwargs"]["task"]["name"] == "harbor_dsh"
    assert launch["evaluation_scope"] == "same-task-engineering-evaluation-not-generalization"
    secret = inputs["worker_token_file"].read_text()
    assert task["worker_token"] == secret
    assert secret not in launch_path.read_text()
    assert inputs["task_config_path"].stat().st_mode & 0o777 == 0o600
    assert inputs["output_dir"].stat().st_mode & 0o777 == 0o700


@pytest.mark.parametrize("change", ["instruction", "image"])
def test_changed_task_or_image_requires_new_frozen_spec(inputs, change):
    name = "instruction.md" if change == "instruction" else "task.toml"
    (inputs["task_dir"] / name).write_text("changed")
    with pytest.raises(ValueError):
        prepare_training(**inputs)
    assert not inputs["output_dir"].exists()


def test_outputs_cannot_be_overwritten(inputs):
    prepare_training(**inputs)
    with pytest.raises(FileExistsError):
        prepare_training(**inputs)


def test_real_hydra_parser_receives_replacement_kwargs(inputs):
    launch = json.loads(prepare_training(**inputs).read_text())
    overrides = build_overrides(launch)
    parsed = OverridesParser.create().parse_overrides(overrides)
    prefix = "actor_rollout_ref.rollout.custom.agent_framework"
    values = {item.key_or_group: item.value() for item in parsed if not item.is_delete()}
    post = values[prefix + ".trajectory_postprocessor_kwargs"]
    assert "trace_root" not in post and "result_root" not in post
    assert "gateway_port" not in post["policy_template"]
    assert post["instruction"] == "Write the fixed answer.\n"
    assert any(item.is_delete() and item.key_or_group == prefix + ".trajectory_postprocessor_kwargs" for item in parsed)
    assert values[prefix + ".agent_runners.task.runner_kwargs.harbor_route_registration"] == launch["registration"]


def test_print_command_calls_existing_base_without_gpu_and_keeps_harbor_overrides(inputs):
    launch_path = prepare_training(**inputs)
    command = subprocess.run(
        [sys.executable, "-m", "examples.harbor.train_m2_online_rl", "--launch", str(launch_path)],
        cwd=REPO,
        env={**os.environ, "PRINT_COMMAND": "1"},
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert command.returncode == 0, command.stderr
    assert "verl.trainer.main_ppo" in command.stdout
    assert "uni_agent.tasks.harbor_dsh.registration.validate_registered_trajectories" in command.stdout
    assert "harbor_route_registration" in command.stdout
    assert inputs["worker_token_file"].read_text() not in command.stdout
    assert not (inputs["output_dir"] / "checkpoints").exists()


@pytest.mark.parametrize(
    "text", ["line one\nline two", 'a"quoted"value', "path\\with\\slashes", "trailing\\", 'slash\\"quote']
)
def test_hydra_values_preserve_original_instruction_bytes(text):
    from examples.harbor.train_m2_online_rl import _hydra

    result = OverridesParser.create().parse_override("instruction=" + _hydra(text)).value()
    assert result == text


def test_hydra_application_removes_old_dsh_postprocessor_kwargs(inputs):
    from hydra._internal.config_loader_impl import ConfigLoaderImpl
    from omegaconf import OmegaConf

    launch = json.loads(prepare_training(**inputs).read_text())
    cfg = OmegaConf.create(
        {
            "actor_rollout_ref": {
                "rollout": {
                    "custom": {
                        "agent_framework": {
                            "trajectory_postprocessor_kwargs": {"trace_root": "old", "result_root": "old"}
                        }
                    }
                }
            }
        }
    )
    parsed = OverridesParser.create().parse_overrides(build_overrides(launch))
    ConfigLoaderImpl._apply_overrides_to_config(parsed, cfg)
    applied = OmegaConf.to_container(
        cfg.actor_rollout_ref.rollout.custom.agent_framework.trajectory_postprocessor_kwargs
    )
    assert applied == launch["postprocessor"]


def test_single_gpu_print_defaults_disable_layered_offload_fallback(inputs):
    launch_path = prepare_training(**inputs)
    environment = dict(os.environ)
    for key in (
        "LOW_VRAM",
        "ROLLOUT_LAYERED_SUMMON",
        "ROLLOUT_ENFORCE_EAGER",
        "ROLLOUT_FREE_CACHE_ENGINE",
        "ROLLOUT_CPU_OFFLOAD_GB",
        "LORA_RANK",
        "LORA_ALPHA",
        "SAVE_LORA_ONLY",
        "ACTOR_PARAM_OFFLOAD",
    ):
        environment.pop(key, None)
    command = subprocess.run(
        [sys.executable, "-m", "examples.harbor.train_m2_online_rl", "--launch", str(launch_path), "--print-command"],
        cwd=REPO,
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert command.returncode == 0, command.stderr
    assert "actor_rollout_ref.rollout.layered_summon=False" in command.stdout
    assert "actor_rollout_ref.rollout.enforce_eager=True" in command.stdout
    assert "actor_rollout_ref.rollout.free_cache_engine=True" in command.stdout
    assert "actor_rollout_ref.actor.fsdp_config.param_offload=True" in command.stdout
    assert "actor_rollout_ref.rollout.engine_kwargs.vllm.cpu_offload_gb=0" in command.stdout
    assert "actor_rollout_ref.model.lora_rank=16" in command.stdout
    assert "actor_rollout_ref.model.lora_alpha=16" in command.stdout
    assert "actor_rollout_ref.actor.checkpoint.save_lora_only=False" in command.stdout


def test_ignored_directory_permissions_fail_before_writing_token_yaml(inputs, monkeypatch):
    original_mkdir = Path.mkdir

    def mkdir_ignoring_mode(path, *args, **kwargs):
        original_mkdir(path, *args, **kwargs)
        if path == inputs["output_dir"]:
            path.chmod(0o777)

    monkeypatch.setattr(Path, "mkdir", mkdir_ignoring_mode)
    with pytest.raises(ValueError, match="permissions.*local path"):
        prepare_training(**inputs)
    assert not inputs["task_config_path"].exists()
    assert list(inputs["output_dir"].iterdir()) == []


def test_harbor_runner_does_not_inherit_dsh_artifact_roots(inputs):
    from hydra._internal.config_loader_impl import ConfigLoaderImpl
    from omegaconf import OmegaConf

    from uni_agent.framework.task_runner import _inject_dsh_artifact_roots

    launch = json.loads(prepare_training(**inputs).read_text())
    cfg = OmegaConf.create(
        {
            "actor_rollout_ref": {
                "rollout": {
                    "custom": {
                        "agent_framework": {
                            "trajectory_postprocessor_kwargs": {},
                            "agent_runners": {
                                "task": {
                                    "runner_kwargs": {
                                        "dsh_trace_root": "/old/traces",
                                        "dsh_result_root": "/old/results",
                                    }
                                }
                            },
                        }
                    }
                }
            }
        }
    )
    ConfigLoaderImpl._apply_overrides_to_config(OverridesParser.create().parse_overrides(build_overrides(launch)), cfg)
    kwargs = cfg.actor_rollout_ref.rollout.custom.agent_framework.agent_runners.task.runner_kwargs
    task = {"name": "harbor_dsh"}
    assert (
        _inject_dsh_artifact_roots(task, trace_root=kwargs.dsh_trace_root, result_root=kwargs.dsh_result_root) == task
    )
    assert kwargs.dsh_trace_root is None and kwargs.dsh_result_root is None
