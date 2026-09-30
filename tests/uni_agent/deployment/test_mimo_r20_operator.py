"""Cloud CPU regression for sequential stage admission and native parent integrity."""

import importlib.util
import json
import os
from pathlib import Path

import pytest

pytestmark = [pytest.mark.cpu, pytest.mark.level0]


@pytest.fixture
def module():
    path = Path(
        os.environ.get(
            "MIMO_R20_OPERATOR_PATH",
            str(Path(__file__).resolve().parents[3] / "docs/verl-uni-agent-harbor-opd-rl/mimo_r20_operator.py"),
        )
    )
    spec = importlib.util.spec_from_file_location("r20_operator_test", path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    if value.SOURCE_MANIFEST_SHA is None:
        value.SOURCE_MANIFEST_SHA = "f" * 64  # Synthetic unit admission only; production remains fail-closed.
    return value


def accepted_evidence(module, tmp_path, run_id="mimo9b-001661-r20a", step=4):
    update = tmp_path / "effective-update.json"
    update.write_text(
        json.dumps(
            {
                "schema": "mimo.world2-effective-update.v1",
                "passed": True,
                "identity": {"run_id": run_id, "step": step, "run_spec_sha256": "sha256:" + "1" * 64},
            }
        )
    )
    wandb = tmp_path / "native-wandb.json"
    wandb.write_text(
        json.dumps(
            {
                "schema": "mimo.r20-native-wandb-final.v1",
                "passed": True,
                "source_commit": module.SOURCE_COMMIT,
                "run_name": run_id,
                "run_state": "finished",
                "read_only": True,
                "history_mutated": False,
                "backfilled": False,
                "native_history_rows": [{"training/global_step": step, "actor/grad_norm": 0.125}],
            }
        )
    )
    return {str(path): module.file_identity(path)["sha256"] for path in (update, wandb)}


@pytest.fixture
def plan(module):
    return {
        "schema": "mimo.r20-stage-plan.v1",
        "stage": "r20a",
        "task_id": "001661",
        "run_id": "mimo9b-001661-r20a",
        "deadline_unix": module.DEADLINE,
        "source_commit": module.SOURCE_COMMIT,
        "source_manifest_sha256": module.SOURCE_MANIFEST_SHA,
        "model_revision": module.MODEL_REVISION,
        "data_revision": module.DATA_REVISION,
        "spec_path": "/root/mimo-private/run-spec-r20a.json",
        "parent_manifest_path": "/tmp/parent.json",
        "parent_manifest_sha256": "1" * 64,
        "http_proof_path": "/tmp/http.json",
        "http_proof_sha256": "2" * 64,
        "calibration_path": "/tmp/cal.json",
        "calibration_sha256": "3" * 64,
        "task_manifest_path": "/tmp/task-manifest.json",
        "task_manifest_sha256": "4" * 64,
    }


def test_fixed_deadline_and_independent_paths(module, plan):
    result = module.validate_plan(plan, now=module.DEADLINE - 3600)
    assert result["wall_clock_seconds"] == 3420
    assert result["journal"] == "/root/mimo-private/launch-r20a/token-journal"
    assert result["run_root"].endswith("/runs/r20a")


@pytest.mark.parametrize(
    "key,value",
    [
        ("stage", "r19"),
        ("stage", "../r20a"),
        ("task_id", "fake"),
        ("run_id", "mimo9b-001661-r19"),
        ("deadline_unix", 1790760000),
        ("deadline_unix", True),
        ("model_revision", "main"),
        ("data_revision", "main"),
        ("source_commit", "head"),
        ("source_manifest_sha256", "0" * 64),
        ("spec_path", "/root/mimo-private/run-spec-r19.json"),
        ("parent_manifest_sha256", ""),
        ("http_proof_path", ""),
        ("calibration_sha256", ""),
    ],
)
def test_reject_wrong_identity_authorization_or_unbound_inputs(module, plan, key, value):
    plan[key] = value
    with pytest.raises(ValueError):
        module.validate_plan(plan, now=module.DEADLINE - 3600)


@pytest.mark.parametrize("now", [float("nan"), float("inf"), True, 1790759992, 1790759992 - 2579, 1790759992 - 15000])
def test_no_restart_of_authorization_window(module, now):
    with pytest.raises(ValueError):
        module.validate_window(module.DEADLINE, now)


@pytest.fixture
def checkpoint(module, tmp_path):
    checkpoint = tmp_path / "checkpoints/global_step_4"
    for name in module.CHECKPOINT_FILES:
        path = checkpoint / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"native component")
    (checkpoint / "actor/fsdp_config.json").write_text(json.dumps({"world_size": 2, "FSDP_version": 1}))
    (checkpoint.parent / "latest_checkpointed_iteration.txt").write_text("4\n")
    return checkpoint


def test_streamed_seal_binds_all_native_components_no_tq(module, checkpoint, tmp_path, monkeypatch):
    monkeypatch.setattr(module, "validate_source", lambda: module.SOURCE_MANIFEST_SHA)
    provenance = {
        "run_id": "mimo9b-001661-r20a",
        "task_id": "001661",
        "source_commit": module.SOURCE_COMMIT,
        "run_spec_sha256": "1" * 64,
        "evidence_sha256": accepted_evidence(module, tmp_path),
    }
    output = tmp_path / "sealed.json"
    sealed = module.seal_parent(checkpoint, output, provenance)
    assert sealed["step"] == 4 and len(sealed["files"]) == 15
    assert sealed["inflight_tq_replay_available"] is False
    assert sealed["training_started"] is False
    assert output.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        module.seal_parent(checkpoint, output, provenance)


@pytest.mark.parametrize("fault", ["missing", "extra-tq", "symlink", "marker", "world", "bool-world", "fsdp"])
def test_native_parent_rejects_incomplete_or_wrong_layout(module, checkpoint, fault):
    if fault == "missing":
        (checkpoint / "actor/optim_world_size_2_rank_1.pt").unlink()
    elif fault == "extra-tq":
        (checkpoint / "tq_state.pt").write_bytes(b"unsupported")
    elif fault == "symlink":
        path = checkpoint / "actor/extra_state_world_size_2_rank_0.pt"
        path.unlink()
        path.symlink_to(checkpoint / "data.pt")
    elif fault == "marker":
        (checkpoint.parent / "latest_checkpointed_iteration.txt").write_text("3")
    else:
        values = {"world_size": 2, "FSDP_version": 1}
        values["world_size" if "world" in fault else "FSDP_version"] = (
            True if fault == "bool-world" else 1 if fault == "world" else 2
        )
        (checkpoint / "actor/fsdp_config.json").write_text(json.dumps(values))
    with pytest.raises(ValueError):
        module.checkpoint_files(checkpoint)


def test_sealed_parent_rejects_tampering(module, checkpoint, tmp_path, plan):
    step, files = module.checkpoint_files(checkpoint)
    parent = {
        "schema": "mimo.native-checkpoint-manifest.v1",
        "world_size": 2,
        "source_commit": module.SOURCE_COMMIT,
        "source_manifest_sha256": module.SOURCE_MANIFEST_SHA,
        "run_id": "mimo9b-001661-r20a",
        "run_spec_sha256": "1" * 64,
        "evidence_sha256": accepted_evidence(module, tmp_path),
        "checkpoint": str(checkpoint),
        "step": step,
        "files": files,
        "task_id": "001661",
        "inflight_tq_replay_available": False,
    }
    path = tmp_path / "parent.json"
    path.write_text(json.dumps(parent))
    plan.update(parent_manifest_path=str(path), parent_manifest_sha256=module.file_identity(path)["sha256"])
    assert module.validate_parent(plan)["step"] == 4
    (checkpoint / "actor/optim_world_size_2_rank_1.pt").write_bytes(b"modified")
    with pytest.raises(ValueError, match="changed after sealing"):
        module.validate_parent(plan)


@pytest.mark.parametrize("fault", ["data-sha", "old-parent-step", "old-checkpoint", "old-target"])
def test_new_task_requires_mechanism_proof_before_preparation(module, checkpoint, tmp_path, plan, fault):
    step, files = module.checkpoint_files(checkpoint)
    path = tmp_path / "parent.json"
    path.write_text(
        json.dumps(
            {
                "schema": "mimo.native-checkpoint-manifest.v1",
                "world_size": 2,
                "source_commit": module.SOURCE_COMMIT,
                "source_manifest_sha256": module.SOURCE_MANIFEST_SHA,
                "run_id": "mimo9b-001661-r20a",
                "run_spec_sha256": "1" * 64,
                "evidence_sha256": accepted_evidence(module, tmp_path),
                "checkpoint": str(checkpoint),
                "step": step,
                "files": files,
                "task_id": "001661",
                "inflight_tq_replay_available": False,
            }
        )
    )
    plan.update(
        task_id="002857", parent_manifest_path=str(path), parent_manifest_sha256=module.file_identity(path)["sha256"]
    )
    with pytest.raises(KeyError):
        module.validate_parent(plan)
    proof = tmp_path / "data-resume.json"
    payload = {
        "schema": "mimo.curriculum-data-resume-probe.v1",
        "passed": True,
        "data_sha256": files["data.pt"]["sha256"],
        "checkpoint": str(checkpoint),
        "parent_step": 4,
        "plan": {"first_training_step": 5},
        "native": {"cuda_initialized": False},
        "model_loaded": False,
        "original_parent_unchanged": True,
        "transfer_queue_exists": False,
        "full_bitwise_data_replay_claimed": False,
        "scope": "Synthetic distinct-task mechanism probe using real parent data.pt; "
        "not training consumption or full model resume",
    }
    proof.write_text(json.dumps(payload))
    plan.update(
        dataset_mechanism_proof_path=str(proof), dataset_mechanism_proof_sha256=module.file_identity(proof)["sha256"]
    )
    assert module.validate_parent(plan)["step"] == 4
    if fault == "data-sha":
        payload["data_sha256"] = "0" * 64
    elif fault == "old-parent-step":
        payload["parent_step"] = 3
    elif fault == "old-checkpoint":
        payload["checkpoint"] = "/old/global_step_3"
    else:
        payload["plan"]["first_training_step"] = 4
    proof.write_text(json.dumps(payload))
    plan["dataset_mechanism_proof_sha256"] = module.file_identity(proof)["sha256"]
    with pytest.raises(ValueError, match="mechanism proof"):
        module.validate_parent(plan)


def test_actual_launcher_command_absolute_step_and_private_metadata(module, plan):
    command = module.command(plan, {"step": 4, "checkpoint": "/actual/global_step_4"})
    assert command[command.index("--total-training-steps") + 1] == "5"
    assert command[command.index("--resume-from-path") + 1] == "/actual/global_step_4"
    assert command[command.index("--token-journal-dir") + 1] == "/root/mimo-private/launch-r20a/token-journal"
    assert "--observability-wrapper" in command
    assert command[command.index("--observability-deadline-unix") + 1] == str(module.DEADLINE)


def test_bound_json_and_atomic_outputs_reject_unsealed_or_existing_file(module, tmp_path):
    path = tmp_path / "input.json"
    module.write_new(path, {"stage": "r20a"})
    sha = module.file_identity(path)["sha256"]
    assert module.read_bound(path, sha) == {"stage": "r20a"}
    with pytest.raises(ValueError):
        module.read_bound(path, "0" * 64)
    with pytest.raises(FileExistsError):
        module.write_new(path, {"stage": "overwrite"})


@pytest.fixture
def composed(module, plan):
    from omegaconf import OmegaConf

    from examples.harbor_opd_rl.launch import ROOT, build_overrides, compose_config

    limits = {"max_generated_tokens": 20480, "trajectory_capacity": 32768}
    launch = {
        "schema": "dsh.harbor-m2-launch.v1",
        "environment": {
            "TRAIN_FILE": "/private/run/train.parquet",
            "TEST_FILE": "/private/run/heldout.parquet",
            "TASK_CONFIG": "/private/run/task.yaml",
            "RUN_ROOT": "/private/run",
            "MODEL_ID": "mimo-student",
        },
        "registration": {"controller_url": "http://127.0.0.1:38780", "token_file": "/private/token"},
        "postprocessor": {
            "artifact_root": "/private/run/artifacts",
            "controller_id": "controller",
            "termination_policy": "budget-terminal-v1",
            "budget_limits": limits,
            "policy_template": {"termination_policy": "budget-terminal-v1", "budget_limits": limits},
            "mimo_binding": {"path": "/private/task/mimo-binding.json", "sha256": "sha256:" + "a" * 64},
        },
    }
    launch["environment"]["RUN_ROOT"] = str(module.ROOT / "runs/r20a")
    launch["postprocessor"].update(run_id=plan["run_id"], run_spec_sha256="sha256:" + "a" * 64)
    config = compose_config(
        build_overrides(
            "rl",
            launch,
            {"STUDENT_MODEL_PATH": module.MODEL, "TOOL_PARSER": "qwen3_coder"},
            recipe_config=ROOT / "examples/mimo_dsh_rl/mimo-9b-dual-colocate-observed.yaml",
            experiment_name=plan["run_id"],
        )
    )
    parent = {"step": 4, "checkpoint": "/actual/global_step_4"}
    for name, value in {
        "trainer.resume_mode": "resume_path",
        "trainer.resume_from_path": parent["checkpoint"],
        "trainer.total_training_steps": 5,
        "trainer.observability_deadline_unix": module.DEADLINE,
        "ray_kwargs.ray_init.runtime_env.env_vars.UNI_AGENT_TOKEN_JOURNAL_DIR": (
            "/root/mimo-private/launch-r20a/token-journal"
        ),
    }.items():
        OmegaConf.update(config, name, value, force_add=True)
    return config, launch, parent


def test_actual_hydra_composition_native_resume_stage_admission(module, plan, composed):
    import torch

    config, launch, parent = composed
    assert not torch.cuda.is_initialized()
    module.validate_training_config(config, plan, launch, parent)
    assert not torch.cuda.is_initialized()


@pytest.mark.parametrize(
    "key,value",
    [
        ("trainer.n_gpus_per_node", 1),
        ("trainer.v1.trainer_mode", "separate_async"),
        ("actor_rollout_ref.rollout.tensor_model_parallel_size", 2),
        ("actor_rollout_ref.rollout.checkpoint_engine.backend", "nccl"),
        ("actor_rollout_ref.rollout.custom.agent_framework.agent_runners.task.max_concurrent_sessions", 1),
        ("data.train_files", "/old/run/train.parquet"),
        ("data.val_files", "/old/run/heldout.parquet"),
        (
            "actor_rollout_ref.rollout.custom.agent_framework.agent_runners.task.runner_kwargs.task_config_path",
            "/old/task.yaml",
        ),
        ("trainer.default_local_dir", "/old/checkpoints"),
        ("trainer.resume_mode", "disable"),
        ("trainer.resume_from_path", "/old/global_step_3"),
        ("trainer.total_training_steps", 4),
        ("trainer.save_freq", 2),
        ("trainer.observability_deadline_unix", 1790752269),
        ("trainer.experiment_name", "mimo9b-001661-r19"),
        ("trainer.logger", ["console"]),
        ("ray_kwargs.ray_init.runtime_env.env_vars.UNI_AGENT_TOKEN_JOURNAL_DIR", "/old/journal"),
        (
            "actor_rollout_ref.rollout.custom.agent_framework.trajectory_postprocessor_kwargs.run_spec_sha256",
            "sha256:" + "b" * 64,
        ),
    ],
)
def test_reject_native_config_wrong_task_and_old_run_contamination(module, plan, composed, key, value):
    from omegaconf import OmegaConf

    config, launch, parent = composed
    OmegaConf.update(config, key, value)
    with pytest.raises(ValueError):
        module.validate_training_config(config, plan, launch, parent)


def test_environment_removes_previous_task_override_and_keeps_private_identity(module, plan, monkeypatch):
    monkeypatch.setattr(
        module.runpy,
        "run_path",
        lambda path: {
            "training_environment": lambda root: {
                "PYTHONPATH": ":".join(
                    str(root / name) for name in ("env-overlays/r10-cupy/packages", "run-src-r19", "run-src-r19/verl")
                ),
                "LD_LIBRARY_PATH": "/fixed/nccl",
            }
        },
    )
    monkeypatch.setenv("TRAIN_FILE", "/old/train.parquet")
    monkeypatch.setenv("TASK_CONFIG", "/old/credentials.yaml")
    monkeypatch.setenv("WANDB_DISABLED", "true")
    env = module.environment(plan, cpu=True)
    assert env["CUDA_VISIBLE_DEVICES"] == ""
    assert env["WANDB_NAME"] == plan["run_id"] and env["WANDB_RESUME"] == "never"
    assert env["RAY_TMPDIR"].endswith("ray-r20a")
    assert str(module.source_directory()) in env["PYTHONPATH"] and "run-src-r19" not in env["PYTHONPATH"]
    assert not {"TRAIN_FILE", "TASK_CONFIG", "WANDB_DISABLED"} & env.keys()


@pytest.fixture
def admitted(module, plan, tmp_path, monkeypatch):
    from deployment.services.harbor_run_controller import RunSpec
    from examples.harbor.prepare_m2_training import task_digest

    actual_verifier = (module.source_directory() / "examples/mimo_dsh_rl/verifier.py").read_bytes()
    private = tmp_path / "private"
    private.mkdir()
    monkeypatch.setattr(module, "PRIVATE", private)
    monkeypatch.setattr(module, "ROOT", tmp_path / "cloud")
    monkeypatch.setattr(module, "MODEL", str(tmp_path / "model"))
    monkeypatch.setattr(module, "validate_source", lambda: module.SOURCE_MANIFEST_SHA)
    monkeypatch.setattr(module, "validate_parent", lambda value: {"step": 4, "checkpoint": "/actual/global_step_4"})
    monkeypatch.setattr(module.time, "time", lambda: module.DEADLINE - 3600)
    task = private / "task"
    task.mkdir()
    (task / "verifier.py").write_bytes(actual_verifier)
    images = {
        "original_image": "registry.example/task@sha256:" + "a" * 64,
        "dsh_image": "registry.example/dsh@sha256:" + "b" * 64,
    }
    binding = {
        "schema": "dsh.mimo-code-binding.v1",
        "task_id": "format-code-task-001661",
        "cwd": "/testbed",
        "runner_python": "/opt/dsh/bin/python",
        "image_binding": images,
        "artifact_contract": "mimo-code-workspace-v1",
        "base_ref_capture": "before_agent",
    }
    (task / "mimo-binding.json").write_text(json.dumps(binding))
    (task / "instruction.md").write_text("Repair the frozen real task.\n")
    (task / "task.toml").write_text(
        '[environment]\ndocker_image="' + images["dsh_image"] + '"\n'
        'network_mode="allowlist"\nallowed_hosts=["mimo9b-rl.xdan.work"]\n'
        '[verifier]\nenvironment_mode="separate"\n[verifier.environment]\n'
        'network_mode="no-network"\ndocker_image="' + images["original_image"] + '"\n'
    )
    release = {
        "source_sha": module.DSH_SOURCE,
        "sdk_sha256": module.SDK_SHA,
        "runtime_sha256": module.RUNTIME_SHA,
        "image_digest": "sha256:" + "b" * 64,
        "patch_sha256s": [],
        "profile": "sdk-minimal",
        "platform": "linux/amd64",
    }
    ref = {"id": "mimo-code-format-code-task-001661", "version": "v1", "sha256": task_digest(task)}
    template = {
        "task_refs": [ref],
        "dsh_release": release,
        "gateway_host": "172.24.0.2",
        "model_name": "mimo-student",
        "tunnel_alias": "mimo-cloud-r20a",
        "max_wall_time_seconds": 1800.0,
        "max_cpus": 2.0,
        "max_memory_mb": 4096,
        "max_tokens": 4096,
        "max_artifact_bytes": 16777216,
        "termination_policy": "budget-terminal-v1",
        "budget_limits": {"max_generated_tokens": 20480, "trajectory_capacity": 32768},
    }
    for name, content in (("registration-token", "r" * 32), ("worker-token", "w" * 32)):
        (private / name).write_text(content)
        (private / name).chmod(0o600)
    spec = RunSpec(
        run_id=plan["run_id"],
        controller_id="controller-r20a",
        worker_id="worker-r20a",
        deadline_unix=module.DEADLINE,
        root=private / "controller",
        task_dir=task,
        registration_token_file=private / "registration-token",
        worker_token_file=private / "worker-token",
        ssh_host="127.0.0.1",
        ssh_port=22,
        ssh_user="root",
        ssh_key=private / "cohost-r20/loopback-key",
        known_hosts=private / "cohost-r20/known_hosts",
        control_port=38880,
        worker_port=38881,
        model_port=38882,
        remote_control_port=38780,
        remote_worker_port=38781,
        max_concurrent_jobs=2,
        policy_template=template,
        modal_ingress={
            "origin": "https://mimo9b-rl.xdan.work",
            "tunnel_id": "12345678-1234-1234-1234-123456789abc",
            "credentials_file": str(private / "cf.json"),
            "listen_port": 38883,
        },
    )
    spec_path = private / "run-spec-r20a.json"
    spec_path.write_text(spec.model_dump_json())
    plan["spec_path"] = str(spec_path)
    plan["spec_raw_sha256"] = module.file_identity(spec_path)["sha256"]
    package = {
        "schema": "dsh.mimo-code-task-package.v1",
        "task_ref": ref,
        "source_repo": "XiaomiMiMo/MiMo-V2.6-RL-oss",
        "source_revision": module.DATA_REVISION,
        "task_id": "format-code-task-001661",
        "task_dir": str(task),
        "dsh_derived_image_digest": release["image_digest"],
        "files": {"task/" + path.name: "sha256:" + module.file_identity(path)["sha256"] for path in task.iterdir()},
    }
    proof = {
        "status": "passed",
        "cleaned_up": True,
        "training_started": False,
        "jobs_submitted": 0,
        "gateway_host": "172.24.0.2",
        "ssh_host": "127.0.0.1",
        "ports": dict(
            control=38880, worker=38881, model=38882, ingress=38883, remote_control=38780, remote_worker=38781
        ),
        "checks": {
            name: True
            for name in (
                "public_model_forward",
                "reverse_control_auth",
                "reverse_worker_auth",
                "bad_token_rejected",
                "unknown_session_rejected",
                "disabled_path_rejected",
            )
        },
    }
    calibration = {
        "status": "passed",
        "task_ref": ref,
        "dsh_release": release,
        "rewards": [0.0, 1.0],
        "model_requests": 0,
        "cleanup_confirmed": True,
    }
    for name, payload in (("task_manifest", package), ("http_proof", proof), ("calibration", calibration)):
        if name == "calibration":
            bindings = {
                "current_runtime_commit": module.SOURCE_COMMIT,
                "source_manifest_sha256": module.SOURCE_MANIFEST_SHA,
                "workspace_helper_sha256": module.PRODUCTION_BLOBS["uni_agent/tasks/harbor_dsh/mimo_workspace.py"],
                "packaged_verifier_sha256": module.PRODUCTION_BLOBS["examples/mimo_dsh_rl/verifier.py"],
                "no_shim": True,
                "private_compatibility_injection": False,
                "task_ref": ref,
                "immutable_package_manifest_sha256": plan["task_manifest_sha256"],
            }
            names = ["baseline-direct", "baseline-restored", "candidate-restored"]
            raw = {
                **bindings,
                "source_hashes": {
                    str(module.source_directory() / name): "sha256:" + sha
                    for name, sha in module.PRODUCTION_BLOBS.items()
                },
                "results": {
                    label: {"status": "graded", "reward": reward, "resolved": bool(reward)}
                    for label, reward in zip(names, [0.0, 0.0, 1.0], strict=True)
                },
            }
            raw_path = private / "actual-calibration.json"
            raw_path.write_text(json.dumps(raw))
            payload.update(
                runtime_bindings=bindings,
                historical_evidence_reused=False,
                production_verifier_compatibility_verified_by_this_adapter=True,
                raw_receipts_verified=names,
                raw_execution_report={"path": str(raw_path), "sha256": module.file_identity(raw_path)["sha256"]},
            )
        path = private / f"{name}.json"
        path.write_text(json.dumps(payload))
        plan[name + "_path"] = str(path)
        plan[name + "_sha256"] = module.file_identity(path)["sha256"]
    for name in ("config.json", "chat_template.jinja", "model.safetensors.index.json"):
        path = Path(module.MODEL) / ".cache/huggingface/download" / (name + ".metadata")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(module.MODEL_REVISION + "\netag\ntimestamp")
    return plan, spec


def test_actual_prepare_binds_mimo_spec_and_single_task_parquet(module, admitted):
    import pyarrow.parquet as pq

    plan, spec = admitted
    report = module.prepare(plan)
    path = module.PRIVATE / "launch-r20a/launch.json"
    launch = json.loads(path.read_bytes())
    assert launch["postprocessor"]["run_id"] == spec.run_id
    assert launch["environment"]["RUN_ROOT"] == str(module.ROOT / "runs/r20a")
    rows = pq.read_table(path.parent / "train.parquet").to_pylist()
    assert len(rows) == 1 and rows[0]["data_source"] == "harbor/mimo-code-format-code-task-001661/train"
    assert report["total_training_steps"] == 5 and report["training_started"] is False
    assert report["validation_is_independent_holdout"] is False
    with pytest.raises(FileExistsError):
        module.prepare(plan)


@pytest.mark.parametrize(
    "artifact,key,value",
    [
        ("http_proof", "cleaned_up", False),
        ("http_proof", "jobs_submitted", 1),
        ("http_proof", "gateway_host", "127.0.0.1"),
        ("calibration", "rewards", [1, 1]),
        ("calibration", "cleanup_confirmed", False),
        ("calibration", "model_requests", 1),
        ("task_manifest", "source_revision", "main"),
        ("task_manifest", "dsh_derived_image_digest", "sha256:" + "e" * 64),
    ],
)
def test_preparation_rejects_wrong_independent_evidence_before_write(module, admitted, artifact, key, value):
    plan, _ = admitted
    path = Path(plan[artifact + "_path"])
    payload = json.loads(path.read_bytes())
    payload[key] = value
    path.write_text(json.dumps(payload))
    plan[artifact + "_sha256"] = module.file_identity(path)["sha256"]
    with pytest.raises(ValueError):
        module.prepare(plan)
    assert not (module.PRIVATE / "launch-r20a").exists()


@pytest.mark.parametrize("fault", [None, "old-run", "old-prompt", "old-source"])
def test_real_prepared_dataset_native_fetch_after_small_parent_state_restore(
    module, admitted, tmp_path, monkeypatch, fault
):
    from types import SimpleNamespace

    import pyarrow as pa
    import pyarrow.parquet as pq
    import torch
    from omegaconf import OmegaConf
    from transformers import AutoTokenizer

    plan, spec = admitted
    module.prepare(plan)
    launch = json.loads((module.PRIVATE / "launch-r20a/launch.json").read_bytes())
    helper_path = Path(
        os.environ.get(
            "MIMO_CURRICULUM_PROBE_PATH",
            str(
                Path(__file__).resolve().parents[3] / "docs/verl-uni-agent-harbor-opd-rl/mimo_curriculum_data_probe.py"
            ),
        )
    )
    plan["dataset_probe_path"] = str(helper_path)
    checkpoint = tmp_path / "parent/global_step_4"
    checkpoint.mkdir(parents=True)
    state = {
        "_index_sampler_state": None,
        "_sampler_iter_state": {"samples_yielded": 1},
        "_sampler_iter_yielded": 1,
        "_num_yielded": 1,
        "_IterableDataset_len_called": None,
        "_shared_seed": None,
        "fetcher_state": None,
        "dataset_state": None,
        "_iterator_finished": False,
    }
    torch.save(state, checkpoint / "data.pt")
    parent = {
        "checkpoint": str(checkpoint),
        "step": 4,
        "files": {"data.pt": module.file_identity(checkpoint / "data.pt")},
    }
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "")
    monkeypatch.setattr(module, "validate_native_dataset_sources", lambda origins: None)
    monkeypatch.setattr(AutoTokenizer, "from_pretrained", lambda *args, **kwargs: None)
    config = SimpleNamespace(
        data=OmegaConf.create(
            {"shuffle": False, "seed": 42, "filter_overlong_prompts": False, "dataloader_num_workers": 0}
        )
    )
    if fault:
        path = Path(launch["environment"]["TRAIN_FILE"])
        rows = pq.read_table(path).to_pylist()
        if fault == "old-run":
            rows[0]["uid"] = "mimo9b-001661-r19-train-0"
        elif fault == "old-prompt":
            rows[0]["prompt"] = [{"role": "user", "content": "OLD TASK"}]
        else:
            rows[0]["data_source"] = "harbor/old-task/train"
        pq.write_table(pa.Table.from_pylist(rows), path)
        with pytest.raises(ValueError, match="task/run identity"):
            module.validate_actual_dataset(plan, parent, spec, launch, config)
    else:
        report = module.validate_actual_dataset(plan, parent, spec, launch, config)
        assert report["status"] == "passed" and report["task_id"] == "001661" and report["parent_unchanged"]
        assert report["epoch_plan"]["first_training_step"] == 5
        assert report["actual_training_consumption_verified"] is False and report["cuda_initialized"] is False
        assert report["parquet_sha256"] == module.file_identity(launch["environment"]["TRAIN_FILE"])["sha256"]


def test_supervisor_input_rejects_changed_raw_spec_with_identical_canonical_data(module, admitted):
    plan, _ = admitted
    path = Path(plan["spec_path"])
    original = json.loads(path.read_text())
    path.write_text(json.dumps(original, indent=4))
    assert json.loads(path.read_text()) == original
    with pytest.raises(ValueError, match="authorized RunSpec bytes"):
        module.validate_inputs(plan)


@pytest.mark.parametrize("fault", ["shim", "old-runtime", "raw-zero-candidate", "historical", "wrong-source-path"])
def test_prepare_and_supervisor_both_require_current_no_shim_raw_receipts(module, admitted, fault):
    plan, _ = admitted
    path = Path(plan["calibration_path"])
    value = json.loads(path.read_text())
    raw_path = Path(value["raw_execution_report"]["path"])
    raw = json.loads(raw_path.read_text())
    if fault == "shim":
        value["runtime_bindings"]["private_compatibility_injection"] = True
    elif fault == "old-runtime":
        value["runtime_bindings"]["current_runtime_commit"] = module.BASE_COMMIT
    elif fault == "historical":
        value["historical_evidence_reused"] = True
    elif fault == "wrong-source-path":
        raw["source_hashes"] = {"old/source.py": "sha256:" + "1" * 64}
    else:
        raw["results"]["candidate-restored"]["reward"] = 0.0
        raw["results"]["candidate-restored"]["resolved"] = False
    raw_path.write_text(json.dumps(raw))
    value["raw_execution_report"]["sha256"] = module.file_identity(raw_path)["sha256"]
    path.write_text(json.dumps(value))
    plan["calibration_sha256"] = module.file_identity(path)["sha256"]
    with pytest.raises(ValueError):
        module.validate_inputs(plan)


@pytest.mark.parametrize("fault", ["unpassed-update", "wrong-step", "backfilled", "unfinished", "zero-gradient"])
def test_new_parent_requires_native_and_remote_acceptance(module, tmp_path, fault):
    parent = {
        "run_id": "mimo9b-001661-r20a",
        "step": 4,
        "run_spec_sha256": "1" * 64,
        "evidence_sha256": accepted_evidence(module, tmp_path),
    }
    update = tmp_path / "effective-update.json"
    remote = tmp_path / "native-wandb.json"
    path = update if fault in ("unpassed-update", "wrong-step") else remote
    value = json.loads(path.read_text())
    if fault == "unpassed-update":
        value["passed"] = False
    elif fault == "wrong-step":
        value["identity"]["step"] = 3
    elif fault == "backfilled":
        value["backfilled"] = True
    elif fault == "unfinished":
        value["run_state"] = "running"
    else:
        value["native_history_rows"][0]["actor/grad_norm"] = 0
    path.write_text(json.dumps(value))
    parent["evidence_sha256"][str(path)] = module.file_identity(path)["sha256"]
    with pytest.raises(ValueError):
        module.validate_parent_evidence(parent)


@pytest.mark.parametrize("fault", ["another-old-run", "wrong-manifest", "wrong-task", "wrong-checkpoint"])
def test_old_source_is_not_a_general_parent_allowlist(module, plan, fault):
    import copy

    parent = json.loads((module.ROOT / "integration-check/r19-c4-resume-manifest-r20.json").read_text())
    parent = copy.deepcopy(parent)
    plan.update(
        parent_manifest_path=str(module.ROOT / "integration-check/r19-c4-resume-manifest-r20.json"),
        parent_manifest_sha256=module.OLD_C4_MANIFEST_SHA,
    )
    if fault == "another-old-run":
        parent["run_id"] = "mimo9b-001661-r17"
    elif fault == "wrong-manifest":
        plan["parent_manifest_sha256"] = "a" * 64
    elif fault == "wrong-task":
        parent["task_id"] = "002549"
    else:
        parent["checkpoint"] = str(module.ROOT / "runs/r17/rl-training/checkpoints/global_step_3")
    module.read_bound = lambda path, sha: parent
    with pytest.raises(ValueError, match="exact accepted R19 C4"):
        module.validate_parent(plan)


@pytest.mark.parametrize("fault", [None, "assembly", "parent", "third-blob", "changed-native"])
def test_actual_runtime_assembly_provenance_and_native_bytes(module, monkeypatch, fault):
    manifest = json.loads((module.ROOT / "integration-check/source-r20-manifest.json").read_text())
    base = json.loads((module.ROOT / "integration-check/source-r19-manifest.json").read_text())
    if fault == "assembly":
        manifest["assembly_mode"] = "unverified-full-git-checkout"
    elif fault == "parent":
        manifest["parent_manifest_sha256"] = "0" * 64
    elif fault == "third-blob":
        manifest["compatibility_git_blob_sha256"]["unreviewed.py"] = "0" * 64
    elif fault == "changed-native":
        manifest["files"]["verl/verl/trainer/ppo/v1/trainer_base.py"]["sha256"] = "0" * 64
    monkeypatch.setattr(
        module, "read_bound", lambda path, sha: manifest if Path(path).name == "source-r20-manifest.json" else base
    )
    if fault:
        with pytest.raises(ValueError):
            module.validate_source()
    else:
        assert module.validate_source() == module.SOURCE_MANIFEST_SHA


@pytest.mark.parametrize("fault", [None, "old-source-path", "recorded-wrong-sha", "changed-source-bytes"])
def test_native_dataset_import_origin_is_admission_not_a_log(module, tmp_path, monkeypatch, fault):
    monkeypatch.setattr(module, "ROOT", tmp_path)
    names = (
        "verl/verl/trainer/ppo/v1/trainer_base.py",
        "verl/verl/trainer/ppo/utils.py",
        "verl/verl/utils/dataset/rl_dataset.py",
    )
    files = {}
    origins = {}
    for name in names:
        path = module.source_directory() / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"Synthetic reviewed native source for origin test")
        files[name] = module.file_identity(path)
        origins[str(path)] = files[name]["sha256"]
    torchdata = (
        Path(module.PYTHON).parents[1]
        / "lib/python3.12/site-packages/torchdata/stateful_dataloader/stateful_dataloader.py"
    )
    origins[str(torchdata)] = module.file_identity(torchdata)["sha256"]
    monkeypatch.setattr(module, "read_bound", lambda path, sha: {"files": files})
    first = module.source_directory() / names[0]
    if fault == "old-source-path":
        origins[str(tmp_path / "run-src-r19" / names[0])] = origins.pop(str(first))
    elif fault == "recorded-wrong-sha":
        origins[str(first)] = "0" * 64
    elif fault == "changed-source-bytes":
        first.write_bytes(b"Unreviewed bytes")
    if fault:
        with pytest.raises(ValueError):
            module.validate_native_dataset_sources(origins)
    else:
        module.validate_native_dataset_sources(origins)


@pytest.mark.parametrize("fault", [None, "stale-run", "old-operator", "old-launch", "old-parent", "bad-health"])
def test_supervise_binds_preflight_before_delegate_and_authenticates_controller(
    module, admitted, tmp_path, monkeypatch, fault
):
    import io
    from types import SimpleNamespace

    from deployment.services import harbor_training_supervisor as supervisor

    plan, spec = admitted
    module.prepare(plan)
    info, _, parent, spec_sha = module.validate_inputs(plan)
    launch_path = Path(info["launch_root"]) / "launch.json"
    proof = {
        "status": "passed",
        "run_id": plan["run_id"],
        "operator_sha256": module.file_identity(module.__file__)["sha256"],
        "launch_sha256": module.file_identity(launch_path)["sha256"],
        "run_spec_sha256": spec_sha,
        "command": module.command(plan, parent),
        "parent_manifest_sha256": plan["parent_manifest_sha256"],
    }
    if fault in ("stale-run", "old-operator", "old-launch", "old-parent"):
        proof[
            {
                "stale-run": "run_id",
                "old-operator": "operator_sha256",
                "old-launch": "launch_sha256",
                "old-parent": "parent_manifest_sha256",
            }[fault]
        ] = "obsolete"
    path = tmp_path / "preflight.json"
    path.write_text(json.dumps(proof))
    plan.update(preflight_path=str(path), preflight_sha256=module.file_identity(path)["sha256"])
    monkeypatch.setattr(module, "environment", lambda value, cpu: {"WANDB_DIR": str(tmp_path / "wandb-stage")})
    requested, invoked = [], []

    def open_request(request, timeout):
        requested.append(request)
        assert request.full_url.endswith("/v1/runs/" + spec.run_id + "/status")
        assert request.get_header("Authorization") == "Bearer " + spec.registration_token_file.read_text()
        value = {
            "healthy": True,
            "state": "unregistered",
            "run_id": spec.run_id,
            "controller_id": "another-controller" if fault == "bad-health" else spec.controller_id,
            "run_spec_sha256": spec_sha,
        }
        return io.BytesIO(json.dumps(value).encode())

    monkeypatch.setattr(module.urllib.request, "build_opener", lambda *args: SimpleNamespace(open=open_request))

    def delegate(command, cwd, environment, root, health, **kwargs):
        health()  # Mirrors the real supervisor's admission ordering; no Popen or GPU in this test.
        invoked.append((command, cwd, environment, root, kwargs))
        return {"exit_code": 0, "reason": "training-exited"}

    monkeypatch.setattr(supervisor, "supervise", delegate)
    if fault is None:
        result = module.supervise(plan)
        assert result["exit_code"] == 0 and result["target_step"] == 5 and result["deadline_unix"] == module.DEADLINE
        assert len(requested) == len(invoked) == 1 and invoked[0][-1]["wall_seconds"] == 3420
    else:
        with pytest.raises(ValueError):
            module.supervise(plan)
        assert invoked == []
        assert len(requested) == (1 if fault == "bad-health" else 0)
