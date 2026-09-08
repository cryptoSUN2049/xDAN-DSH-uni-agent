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


def t2_inputs(inputs):
    import hashlib

    from uni_agent.agents.dsh.harbor_release import T2_PATCH_SHA256

    fixture = inputs["task_dir"] / "tests" / "fixture.json"
    fixture.parent.mkdir()
    fixture.write_bytes((REPO / "examples/dsh/capability_tasks/log_tool/fixtures/dev-01.json").read_bytes())
    spec = json.loads(inputs["run_spec_path"].read_text())
    spec["policy_template"]["dsh_release"]["patch_sha256s"] = [T2_PATCH_SHA256]
    ref = spec["policy_template"]["task_refs"][0]
    ref.update(id="t2-log-tool-dev-01", sha256=task_digest(inputs["task_dir"]))
    inputs["run_spec_path"].write_text(json.dumps(spec))
    binding = dict(
        task_ref=ref,
        fixture_path=str(fixture),
        fixture_sha256="sha256:" + hashlib.sha256(fixture.read_bytes()).hexdigest(),
    )
    binding_path = inputs["run_spec_path"].parent / "t2-binding.json"
    binding_path.write_text(json.dumps(binding))
    return {**inputs, "t2_fixture_binding": binding_path}, binding


def test_t2_binding_enters_task_and_postprocessor_without_sample_override(inputs):
    values, binding = t2_inputs(inputs)
    launch = json.loads(prepare_training(**values).read_text())
    task = yaml.safe_load(inputs["task_config_path"].read_text())
    assert task["t2_fixture"] == launch["postprocessor"]["t2_fixture"] == binding
    for name in ("train", "heldout"):
        rows = pq.read_table(inputs["output_dir"] / f"{name}.parquet").to_pylist()
        assert all(row["data_source"] == f"harbor/t2-log-tool-dev-01/{name}" for row in rows)
        assert all(
            row["extra_info"]["evaluation_scope"] == "same-task-engineering-evaluation-not-generalization"
            for row in rows
        )
        assert all(row["extra_info"]["public_fixture_split"] == "dev" for row in rows)
        assert all("t2_fixture" not in row["extra_info"]["tools_kwargs"]["task"] for row in rows)


@pytest.mark.parametrize("bad", ["missing", "task_ref", "hash", "external_path"])
def test_t2_binding_failures_reject_before_private_output(inputs, bad):
    values, binding = t2_inputs(inputs)
    if bad == "missing":
        del values["t2_fixture_binding"]
    if bad == "task_ref":
        binding["task_ref"]["version"] = "other"
    if bad == "hash":
        binding["fixture_sha256"] = "sha256:" + "0" * 64
    if bad == "external_path":
        copy = inputs["run_spec_path"].parent / "other-fixture.json"
        copy.write_bytes(Path(binding["fixture_path"]).read_bytes())
        binding["fixture_path"] = str(copy)
    if "t2_fixture_binding" in values:
        values["t2_fixture_binding"].write_text(json.dumps(binding))
    with pytest.raises(ValueError):
        prepare_training(**values)
    assert not inputs["output_dir"].exists()


def test_empty_release_cannot_accept_t2_binding(inputs):
    path = inputs["run_spec_path"].parent / "binding.json"
    path.write_text("{}")
    with pytest.raises(ValueError, match="empty release"):
        prepare_training(**inputs, t2_fixture_binding=path)
    assert not inputs["output_dir"].exists()


def test_t2_fixture_survives_real_hydra_postprocessor_override(inputs):
    values, binding = t2_inputs(inputs)
    launch = json.loads(prepare_training(**values).read_text())
    parsed = OverridesParser.create().parse_overrides(build_overrides(launch))
    overrides = {item.key_or_group: item.value() for item in parsed if not item.is_delete()}
    post = overrides["actor_rollout_ref.rollout.custom.agent_framework.trajectory_postprocessor_kwargs"]
    assert post["t2_fixture"] == binding


def adapter_dir(tmp_path):
    path = tmp_path / "adapter with space"
    path.mkdir()
    (path / "adapter_model.safetensors").write_bytes(b"test-weights")
    (path / "adapter_config.json").write_text('{"r":16,"lora_alpha":16}')
    return path


def test_adapter_override_is_hash_bound_and_hydra_preserves_path(tmp_path):
    from examples.harbor.train_m2_online_rl import adapter_digest, adapter_overrides

    path = adapter_dir(tmp_path)
    values = adapter_overrides(path, adapter_digest(path), {"RESUME_MODE": "disable"})
    parsed = OverridesParser.create().parse_overrides(values)
    assert parsed[0].key_or_group == "actor_rollout_ref.model.lora_adapter_path"
    assert parsed[0].value() == str(path)
    old = adapter_digest(path)
    (path / "adapter_config.json").write_text('{"lora_alpha":0}')
    with pytest.raises(ValueError, match="hash"):
        adapter_overrides(path, old, {"RESUME_MODE": "disable"})


@pytest.mark.parametrize("mode", [None, "auto", "resume_path"])
def test_adapter_warmstart_requires_explicit_disable(tmp_path, mode):
    from examples.harbor.train_m2_online_rl import adapter_digest, adapter_overrides

    path = adapter_dir(tmp_path)
    with pytest.raises(ValueError, match="RESUME_MODE"):
        adapter_overrides(path, adapter_digest(path), {} if mode is None else {"RESUME_MODE": mode})


def test_adapter_is_visible_in_actual_print_command(inputs):
    from examples.harbor.train_m2_online_rl import adapter_digest

    path = adapter_dir(inputs["run_spec_path"].parent)
    launch_path = prepare_training(**inputs)
    command = subprocess.run(
        [
            sys.executable,
            "-m",
            "examples.harbor.train_m2_online_rl",
            "--launch",
            str(launch_path),
            "--print-command",
            "--lora-adapter-path",
            str(path),
            "--lora-adapter-bundle-sha256",
            adapter_digest(path),
        ],
        cwd=REPO,
        env={**os.environ, "RESUME_MODE": "disable", "RESUME_FROM_PATH": ""},
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert command.returncode == 0, command.stderr
    assert "actor_rollout_ref.model.lora_adapter_path=" in command.stdout
    assert str(path) in command.stdout
    assert "trainer.resume_mode=disable" in command.stdout
    provenance = json.loads(command.stderr.splitlines()[0])
    assert set(provenance["files"]) == {"adapter_model.safetensors", "adapter_config.json"}
    assert provenance["bundle_sha256"] == adapter_digest(path)


@pytest.mark.parametrize("bad", ["missing_file", "relative", "path_only", "hash_only", "resume_path"])
def test_adapter_input_failures(tmp_path, bad):
    from examples.harbor.train_m2_online_rl import adapter_digest, adapter_overrides

    path = adapter_dir(tmp_path)
    expected = adapter_digest(path)
    env = {"RESUME_MODE": "disable"}
    if bad == "missing_file":
        (path / "adapter_model.safetensors").unlink()
    if bad == "relative":
        path = Path("relative")
    if bad == "path_only":
        expected = None
    if bad == "hash_only":
        path = None
    if bad == "resume_path":
        env["RESUME_FROM_PATH"] = "/old/ppo"
    with pytest.raises(ValueError):
        adapter_overrides(path, expected, env)


@pytest.mark.parametrize("variant", ["valid", "mutual", "descriptor", "metadata_path"])
@pytest.mark.parametrize("binding_key", ["evolution_binding", "evolution_v2_binding"])
def test_evolution_preparation_preserves_operator_binding(inputs, tmp_path, variant, binding_key):
    from tests.uni_agent.tasks.test_harbor_evolution_admission import configured
    from tests.uni_agent.tasks.test_harbor_evolution_admission_v2 import v2_config

    cfg, _ = (v2_config if binding_key == "evolution_v2_binding" else configured)(tmp_path)
    task = inputs["task_dir"]
    (task / "tests").mkdir()
    binding = getattr(cfg, binding_key).model_dump(mode="json")
    for key, filename in [("fixture_path", "fixture.json"), ("metadata_path", "metadata.json")]:
        target = task / "tests" / filename
        target.write_bytes(Path(binding[key]).read_bytes())
        binding[key] = str(target)
    descriptor = {key: binding[key] for key in ["kind", "fixture_sha256", "metadata_sha256", "source_sha256s"]}
    if binding_key == "evolution_v2_binding":
        descriptor["verifier_bundle_sha256"] = binding["verifier_bundle_sha256"]
    (task / "evolution.json").write_text(json.dumps(descriptor))
    spec = json.loads(inputs["run_spec_path"].read_text())
    spec["policy_template"]["dsh_release"] = cfg.policy.dsh_release.model_dump(mode="json")
    (task / "task.toml").write_text('[environment]\ndocker_image = "' + cfg.policy.dsh_release.image_digest + '"\n')
    if variant == "descriptor":
        descriptor["kind"] = "other"
        (task / "evolution.json").write_text(json.dumps(descriptor))
    spec["policy_template"]["task_refs"][0]["version"] = cfg.task_ref.version
    spec["policy_template"]["task_refs"][0]["sha256"] = task_digest(task)
    binding["task_ref"] = spec["policy_template"]["task_refs"][0]
    inputs["run_spec_path"].write_text(json.dumps(spec))
    if variant == "metadata_path":
        binding["metadata_path"] = getattr(cfg, binding_key).metadata_path
    path = tmp_path / "evolution-binding.json"
    path.write_text(json.dumps(binding))
    if variant != "valid":
        extra = {"t2_fixture_binding": path} if variant == "mutual" else {}
        with pytest.raises(ValueError):
            prepare_training(**inputs, **{binding_key: path}, **extra)
        assert not inputs["output_dir"].exists()
        return
    launch = json.loads(prepare_training(**inputs, **{binding_key: path}).read_text())
    config_value = yaml.safe_load(inputs["task_config_path"].read_text())
    assert config_value[binding_key] == binding
    assert launch["postprocessor"][binding_key] == binding
    assert "t2_fixture" not in launch["postprocessor"]
    assert launch["environment"]["PROJECT_NAME"] == "harbor-evolution-engineering"
    rows = pq.read_table(inputs["output_dir"] / "train.parquet").to_pylist()
    assert (
        rows[0]["extra_info"]["public_fixture_case_id"]
        == json.loads(Path(binding["metadata_path"]).read_text())["scenario_id"]
    )
    assert rows[0]["extra_info"]["evaluation_scope"] == "same-task-engineering-evaluation-not-generalization"


@pytest.mark.parametrize("binding_key", ["evolution_binding", "evolution_v2_binding"])
def test_registered_wrapper_forwards_evolution_binding(monkeypatch, binding_key):
    from uni_agent.tasks.harbor_dsh import registration

    binding = {"marker": "operator-binding"}
    captured = {}
    monkeypatch.setattr(registration, "load_registered_policy", lambda **kwargs: "registered-policy")

    def check(trajectories, **kwargs):
        captured.update(kwargs)
        return trajectories

    monkeypatch.setattr(registration, "validate_trajectories", check)
    result = registration.validate_registered_trajectories(
        (),
        context={},
        artifact_root="/tmp/artifacts",
        run_id="r",
        worker_id="w",
        task_ref={},
        policy_template={},
        instruction="task",
        registration_root="/tmp/registrations",
        controller_id="c",
        run_spec_sha256="sha",
        **{binding_key: binding},
    )
    assert result == ()
    assert captured[binding_key] is binding
    assert captured["policy"] == "registered-policy"
