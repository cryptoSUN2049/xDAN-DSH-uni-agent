import ast
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
    monkeypatch.setattr(
        recipe, "verl_source_identity", lambda: {"state": "patched", "overlay_id": "cpu-test"}, raising=False
    )
    return dict(
        output_dir=tmp_path / "data",
        run_root=tmp_path / "run",
        run_id="memory-cpu-recipe",
        runtime_executable=runtime,
        runner_python=Path(sys.executable),
        model_path=model,
        model_revision=lock["student"]["revision"],
    )


def mother_checkpoint(inputs, tmp_path, family="constraints"):
    mother = tmp_path / "mother"
    mother.mkdir()
    checkpoint = tmp_path / "mother-checkpoint" / "global_step_1"
    (checkpoint / "actor").mkdir(parents=True)
    for name in ("model", "optim", "extra_state"):
        (checkpoint / "actor" / f"{name}_world_size_1_rank_0.pt").write_bytes(name.encode())
    (checkpoint / "data.pt").write_bytes(b"data")
    plan = dict(
        mode="train",
        integration_head=recipe.revision(recipe.ROOT),
        verl_head=recipe.revision(recipe.ROOT / "verl"),
        verl_effective_source=recipe.verl_source_identity(),
        model_revision_declared=inputs["model_revision"],
        runtime=dict(sha256=recipe.digest(inputs["runtime_executable"])),
        environment=dict(RUN_ROOT=str(mother), CKPTS_DIR=str(checkpoint.parent)),
        command=[f'++{recipe.AF}memory_operator.family="{family}"'],
    )
    dataset = mother / "dataset-manifest.json"
    dataset.write_text(json.dumps(plan))
    (mother / "memory-launch-plan.json").write_text(json.dumps(plan))
    (mother / "run-manifest.json").write_text(
        json.dumps(
            dict(
                status="completed",
                exit_code=0,
                run_root=str(mother),
                uni_agent_sha=plan["integration_head"],
                verl_sha=plan["verl_head"],
                verl_effective_source=plan["verl_effective_source"],
                paths=dict(dataset_manifest=str(dataset)),
                sha256=dict(dataset_manifest=recipe.digest(dataset)),
            )
        )
    )
    return dict(resume_from=checkpoint, mother_run=mother)


@pytest.mark.parametrize("mode", ["val", "train", "reload"])
@pytest.mark.parametrize("family", ["constraints", "work-state-v1"])
def test_actual_shell_hydra_and_native_from_config(inputs, tmp_path, mode, family):
    extra = mother_checkpoint(inputs, tmp_path, family) if mode == "reload" else {}
    manifest = recipe.prepare(**inputs, mode=mode, family=family, **extra)
    work_state = family == "work-state-v1"
    assert manifest["dataset_kind"] == (
        "public-structural-development" if work_state else "fixed-diagnostic-not-heldout"
    )
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
    framework_class = NativeMemoryFramework
    if work_state:
        from uni_agent.framework.work_state import NativeWorkStateFramework

        framework_class = NativeWorkStateFramework
        assert (
            config.actor_rollout_ref.rollout.agent.agent_loop_manager_class
            == "uni_agent.framework.entry.StrictSyncValidationRolloutAdapter"
        )
    assert af.framework_class_fqn == framework_class.__module__ + "." + framework_class.__name__
    assert af.trajectory_postprocessor_fqn is None and af.trajectory_postprocessor_kwargs is None
    assert af.trajectory_postprocessor_pass_context is False
    assert config.trainer.val_only == (mode != "train")
    framework = framework_class.from_config(config=config, gateway_manager=Manager([]))
    assert framework._memory_operator.root == inputs["run_root"] / "chains"
    assert framework._memory_operator.family == family
    if work_state:
        from examples.dsh.capabilities.memory_training_stage import GroupContext
        from examples.dsh.capabilities.work_state.stage import _task

        assert manifest["counts"] == {"train": 8, "validation": 4}
        for split, partition in [("train", "train"), ("validation", "val")]:
            for row in pq.read_table(inputs["output_dir"] / f"{split}.parquet").to_pylist():
                task = _task(
                    framework._memory_operator, GroupContext("run", partition, "group", 0, 1), row["extra_info"]
                )
                assert task["task_id"] == row["extra_info"]["tools_kwargs"]["task"]["metadata"]["work_state_task_id"]
    if mode == "reload":
        assert config.trainer.resume_mode == "resume_path"
        assert config.trainer.resume_from_path == str(extra["resume_from"])
        assert config.trainer.del_local_ckpt_after_load is False
        assert config.trainer.val_before_train is True
        assert list(config.actor_rollout_ref.actor.checkpoint.load_contents) == ["model", "optimizer", "extra"]
        assert framework._memory_operator.checkpoint_identity == manifest["checkpoint_origin"]["identity"]
        assert framework._memory_operator.checkpoint_identity != inputs["model_revision"]


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


@pytest.mark.parametrize(
    "mode,extra", [("reload", {}), ("val", {"resume_from": "/tmp/x"}), ("train", {"mother_run": "/tmp/x"})]
)
def test_reload_mode_conflicts(inputs, mode, extra):
    with pytest.raises(ValueError, match="Reload requires"):
        recipe.prepare(**inputs, mode=mode, **extra)


@pytest.mark.parametrize("change", ["missing", "mother_incomplete", "source_mismatch", "checkpoint_path"])
def test_reload_requires_actual_mother_evidence(inputs, tmp_path, change):
    extra = mother_checkpoint(inputs, tmp_path)
    if change == "missing":
        (extra["resume_from"] / "actor/optim_world_size_1_rank_0.pt").unlink()
    elif change == "checkpoint_path":
        extra["resume_from"] = extra["resume_from"].parent / "not-a-step"
    else:
        path = extra["mother_run"] / "run-manifest.json"
        record = json.loads(path.read_text())
        record["status" if change == "mother_incomplete" else "uni_agent_sha"] = "wrong"
        path.write_text(json.dumps(record))
    with pytest.raises(ValueError):
        recipe.prepare(**inputs, mode="reload", **extra)
    assert not inputs["output_dir"].exists()


def test_reload_identity_excludes_new_run_and_detects_weight_change(inputs, tmp_path):
    extra = mother_checkpoint(inputs, tmp_path)
    first = recipe.prepare(**inputs, mode="reload", **extra)
    other = {**inputs, "output_dir": tmp_path / "data2", "run_root": tmp_path / "run2", "run_id": "reload-2"}
    second = recipe.prepare(**other, mode="reload", **extra)
    assert first["checkpoint_origin"] == second["checkpoint_origin"]
    assert first["checkpoint_origin"]["step"] == 1
    path = inputs["output_dir"] / "manifest.json"
    assert recipe.check(path)["mode"] == "reload"
    weight = extra["resume_from"] / "actor/model_world_size_1_rank_0.pt"
    weight.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="Checkpoint or mother evidence changed"):
        recipe.check(path)


@pytest.mark.parametrize("override", ["trainer.val_only=False", "trainer.del_local_ckpt_after_load=True"])
def test_reload_rejects_training_or_delete_override(inputs, tmp_path, override):
    extra = mother_checkpoint(inputs, tmp_path)
    manifest = recipe.prepare(**inputs, mode="reload", **extra)
    manifest["command"].append(override)
    path = inputs["output_dir"] / "manifest.json"
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="protected overrides"):
        recipe.check(path)


def test_reload_output_cannot_overlap_mother(inputs, tmp_path):
    extra = mother_checkpoint(inputs, tmp_path)
    inputs["output_dir"] = extra["resume_from"] / "reload-data"
    with pytest.raises(ValueError, match="overlap"):
        recipe.prepare(**inputs, mode="reload", **extra)


def test_fixed_verl_val_only_returns_before_training_increment():
    path = recipe.ROOT / "verl/verl/trainer/ppo/v1/trainer_base.py"
    tree = ast.parse(path.read_text())
    fit = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "fit")
    val_only = next(n for n in ast.walk(fit) if isinstance(n, ast.If) and "val_only" in ast.unparse(n.test))
    assert any(isinstance(n, ast.Return) for n in val_only.body)
    increment = min(
        n.lineno for n in ast.walk(fit) if isinstance(n, ast.AugAssign) and ast.unparse(n.target) == "self.global_steps"
    )
    assert val_only.end_lineno < increment


def test_work_state_preparation_check_rejects_task_manifest_tampering(inputs):
    manifest = recipe.prepare(**inputs, family="work-state-v1")
    path = inputs["output_dir"] / "manifest.json"
    assert recipe.check(path)["coverage"]["structures"] == {"train": 4, "validation": 4}
    task_path = inputs["output_dir"] / "work-state-tasks.json"
    dataset = json.loads(task_path.read_text())
    assert set(dataset) == {"schema", "tasks"}
    assert len(dataset["tasks"]) == 12
    assert {row["variant"] for row in dataset["tasks"].values() if row["split"] == "train"} == {0}
    key = next(iter(dataset["tasks"]))
    dataset["tasks"][key]["seed"] += 1
    task_path.write_text(json.dumps(dataset))
    with pytest.raises(ValueError, match="changed"):
        recipe.check(path)
    # Even changing the ordinary file digest cannot bypass the operator's pinned task contract.
    manifest["files"][str(task_path)] = recipe.digest(task_path)
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="task manifest identity"):
        recipe.check(path)


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


def test_preparation_binds_effective_verl_and_checks_drift(inputs, monkeypatch):
    manifest = recipe.prepare(**inputs, mode="train", family="work-state-v1")
    assert manifest["verl_effective_source"] == recipe.verl_source_identity()
    monkeypatch.setattr(recipe, "verl_source_identity", lambda: {"state": "patched", "overlay_id": "unexpected"})
    with pytest.raises(ValueError, match="VERL effective source changed"):
        recipe.check(inputs["output_dir"] / "manifest.json")


def test_reload_rejects_different_mother_effective_verl(inputs, tmp_path):
    extra = mother_checkpoint(inputs, tmp_path, "work-state-v1")
    p = extra["mother_run"] / "memory-launch-plan.json"
    plan = json.loads(p.read_text())
    plan["verl_effective_source"] = {"state": "patched", "overlay_id": "other-patch"}
    p.write_text(json.dumps(plan))
    dataset = extra["mother_run"] / "dataset-manifest.json"
    dataset.write_text(json.dumps(plan))
    run_file = extra["mother_run"] / "run-manifest.json"
    run = json.loads(run_file.read_text())
    run["sha256"]["dataset_manifest"] = recipe.digest(dataset)
    run["verl_effective_source"] = plan["verl_effective_source"]
    run_file.write_text(json.dumps(run))
    with pytest.raises(ValueError, match="Mother evidence/config"):
        recipe.prepare(**inputs, mode="reload", family="work-state-v1", **extra)
