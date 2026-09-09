import json
import os
import subprocess
import sys
from pathlib import Path

import pyarrow.parquet as pq
import pytest
from hydra import compose, initialize_config_dir

from examples.dsh.capabilities import prepare_memory_training as recipe
from tests.uni_agent.framework.test_gateway_stage_execution import Manager
from uni_agent.framework.memory_chain import NativeMemoryFramework


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    runtime.write_bytes(b"fixed runtime")
    runtime.chmod(0o700)
    model = tmp_path / "model"
    model.mkdir()
    for name in ("config.json", "tokenizer_config.json"):
        (model / name).write_text("{}")
    lock = recipe.deployment_lock()
    lock["dsh"]["runtime_binary_sha256"] = recipe.digest(runtime)
    monkeypatch.setattr(recipe, "deployment_lock", lambda: lock)
    monkeypatch.setattr(recipe, "runtime_probe", lambda *a: {"sdk": "0.1.3a2", "runtime": "0.1.3a2"})
    return dict(
        output_dir=tmp_path / "data",
        run_root=tmp_path / "run",
        run_id="memory-cpu-recipe",
        runtime_executable=runtime,
        runner_python=Path(sys.executable),
        model_path=model,
        model_revision=lock["student"]["revision"],
    )


@pytest.mark.parametrize("mode", ["val", "train"])
def test_actual_shell_hydra_and_native_from_config(inputs, tmp_path, mode):
    manifest = recipe.prepare(**inputs, mode=mode)
    assert manifest["dataset_kind"] == "fixed-diagnostic-not-heldout"
    assert manifest["environment"]["ROLLOUT_N"] == "4"
    assert manifest["environment"]["VAL_ROLLOUT_N"] == "1"
    rows = [
        pq.read_table(inputs["output_dir"] / f"{split}.parquet").to_pylist()[0] for split in ("train", "validation")
    ]
    assert rows[0]["uid"] != rows[1]["uid"] and rows[0]["prompt"] == rows[1]["prompt"]
    # Execute the actual shell branch; only the Python process is a recording stub.
    fake = tmp_path / "record-python"
    captured = tmp_path / "argv.json"
    fake.write_text(
        f"#!{sys.executable}\nimport json,sys\n"
        f"if sys.argv[1:3]==['-m','verl.trainer.main_ppo']:"
        f"open({str(captured)!r},'w').write(json.dumps(sys.argv[3:]))\n"
    )
    fake.chmod(0o700)
    env = {
        **os.environ,
        **manifest["environment"],
        "PYTHON_BIN": str(fake),
        "CKPTS_DIR": str(tmp_path / "checkpoint"),
        "CUDA_VISIBLE_DEVICES": "",
    }
    subprocess.run(
        ["bash", str(recipe.ROOT / "examples/dsh/train_qwen3_4b_online_rl.sh"), *manifest["command"][3:]],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    with initialize_config_dir(config_dir=str(recipe.ROOT / "verl/verl/trainer/config"), version_base=None):
        config = compose(config_name="ppo_trainer", overrides=json.loads(captured.read_text()))
    af = config.actor_rollout_ref.rollout.custom.agent_framework
    assert af.framework_class_fqn == "uni_agent.framework.memory_chain.NativeMemoryFramework"
    assert af.trajectory_postprocessor_fqn is None and af.trajectory_postprocessor_kwargs is None
    assert af.trajectory_postprocessor_pass_context is False
    assert config.trainer.val_only == (mode == "val")
    framework = NativeMemoryFramework.from_config(config=config, gateway_manager=Manager([]))
    assert framework._memory_operator.root == inputs["run_root"] / "chains"
    assert framework._memory_operator.family == "constraints"


def test_reuse_bad_runtime_and_source_mutation_rejected(inputs):
    manifest = recipe.prepare(**inputs)
    path = inputs["output_dir"] / "manifest.json"
    assert recipe.check(path)["integration_head"] == manifest["integration_head"]
    with pytest.raises(ValueError, match="new private"):
        recipe.prepare(**inputs)
    (inputs["output_dir"] / "task.yaml").write_text("changed")
    with pytest.raises(ValueError, match="changed"):
        recipe.check(path)


def test_unsupported_modes_and_runtime_pin(inputs):
    with pytest.raises(ValueError, match="Only"):
        recipe.prepare(**inputs, mode="colocate_async")
    inputs["runtime_executable"].write_bytes(b"different runtime")
    with pytest.raises(ValueError, match="Runtime pin"):
        recipe.prepare(**inputs)


def test_memory_recipe_module_exists():
    from examples.dsh.capabilities.prepare_memory_training import prepare

    assert callable(prepare)


def test_launch_creates_actual_private_writer_parent(inputs, monkeypatch, tmp_path):
    from deployment.services import harbor_training_supervisor
    from examples.dsh.capabilities.memory_training_stage import GroupContext, OperatorSpec, prepare_writer_stage

    manifest = recipe.prepare(**inputs)
    # Keep CPU preflight real; only nvidia-smi and the supervisor child process are replaced.
    actual = recipe.subprocess.check_output
    monkeypatch.setattr(
        recipe.subprocess, "check_output", lambda cmd, **kw: "" if cmd[0] == "nvidia-smi" else actual(cmd, **kw)
    )

    def supervise(command, cwd, env, root, health, **budget):
        assert command == manifest["command"] and budget["wall_seconds"] == 3600
        assert env["CUDA_VISIBLE_DEVICES"] == "0" and "RAY_ADDRESS" not in env
        operator = OperatorSpec(
            inputs["run_root"] / "chains",
            inputs["runner_python"],
            inputs["runtime_executable"],
            recipe.digest(inputs["runtime_executable"]),
            inputs["model_revision"],
            "constraints",
        )
        stage = prepare_writer_stage(
            operator,
            GroupContext(inputs["run_id"], "val", "group", 0, 0),
            chain_id="chain",
            gateway_session_id="stage-a",
        )
        assert stage.task_config_path.is_file()
        assert operator.root.stat().st_mode & 0o777 == 0o700
        return {"exit_code": 0}

    # Use short private test Ray path, without leaking a /tmp artifact after this CPU test.
    manifest["environment"]["RAY_TMPDIR"] = str(tmp_path / "ray")
    path = inputs["output_dir"] / "manifest.json"
    path.write_text(json.dumps(manifest))
    monkeypatch.setattr(harbor_training_supervisor, "supervise", supervise)
    assert recipe.launch(path)["exit_code"] == 0
