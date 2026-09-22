"""Immutable MOPD inputs and explicit, non-replaying resume admission."""

import json
from pathlib import Path

import pytest

from examples.harbor_mopd.launch import (
    checkpoint_receipt,
    file_sha256,
    model_identity,
    validate_registry,
    verify_resume,
)


def model(path):
    path.mkdir()
    (path / "config.json").write_text('{"model_type":"qwen3"}')
    (path / "tokenizer.json").write_text('{"model":{"vocab":{"x":0}}}')
    (path / "model.safetensors").write_bytes(b"fixture-weights")
    return {"model_path": str(path), "sha256": model_identity(path)["sha256"]}


def registry(tmp_path):
    return {
        "schema": "harbor-mopd-registry-v1",
        "student": model(tmp_path / "student"),
        "teachers": {domain: model(tmp_path / domain) for domain in ("swe", "terminal")},
    }


def test_model_identity_binds_weights_and_tokenizer(tmp_path):
    spec = model(tmp_path / "model")
    (Path(spec["model_path"]) / "model.safetensors").write_bytes(b"changed")
    assert model_identity(Path(spec["model_path"]))["sha256"] != spec["sha256"]


def test_raw_training_checkpoint_is_not_a_servable_teacher(tmp_path):
    (tmp_path / "model_world_size_1_rank_0.pt").write_bytes(b"weights")
    with pytest.raises(ValueError, match="HF"):
        model_identity(tmp_path)


def test_registry_verifies_actual_local_bytes(tmp_path):
    spec = registry(tmp_path)
    assert set(validate_registry(spec)["teachers"]) == {"swe", "terminal"}
    (tmp_path / "swe" / "model.safetensors").write_bytes(b"changed")
    with pytest.raises(ValueError, match="digest"):
        validate_registry(spec)


def test_tokenizer_mismatch_rejected_even_with_updated_model_digest(tmp_path):
    spec = registry(tmp_path)
    (tmp_path / "swe" / "tokenizer.json").write_text('{"model":{"vocab":{"other":0}}}')
    spec["teachers"]["swe"]["sha256"] = model_identity(tmp_path / "swe")["sha256"]
    with pytest.raises(ValueError, match="tokenizer"):
        validate_registry(spec)


def test_two_teacher_domains_required(tmp_path):
    spec = registry(tmp_path)
    del spec["teachers"]["terminal"]
    with pytest.raises(ValueError, match="swe.*terminal"):
        validate_registry(spec)


def checkpoint(root, step=1):
    path = root / "checkpoints" / f"global_step_{step}"
    (path / "actor").mkdir(parents=True)
    (path / "data.pt").write_bytes(b"cursor")
    for kind in ("model", "optim", "extra_state"):
        (path / "actor" / f"{kind}_world_size_1_rank_0.pt").write_bytes(kind.encode())
    return path


def test_checkpoint_requires_optimizer_and_cursor(tmp_path):
    path = checkpoint(tmp_path)
    assert checkpoint_receipt(path, world_size=1)["step"] == 1
    (path / "actor" / "optim_world_size_1_rank_0.pt").unlink()
    with pytest.raises(ValueError, match="optim"):
        checkpoint_receipt(path, world_size=1)


def successful_state(tmp_path):
    path = checkpoint(tmp_path)
    return path, {
        "status": "process_succeeded",
        "contract_sha256": "contract",
        "target_step": 1,
        "checkpoint": checkpoint_receipt(path, world_size=1),
    }


def test_resume_requires_identical_contract_and_saved_checkpoint(tmp_path):
    path, state = successful_state(tmp_path)
    verify_resume(state, "contract", path, target_step=2, max_steps=2, world_size=1)
    with pytest.raises(ValueError, match="contract"):
        verify_resume(state, "changed", path, target_step=2, max_steps=2, world_size=1)
    (path / "data.pt").write_bytes(b"different cursor")
    with pytest.raises(ValueError, match="checkpoint"):
        verify_resume(state, "contract", path, target_step=2, max_steps=2, world_size=1)


@pytest.mark.parametrize("status", ["started", "failed", "interrupted"])
def test_uncertain_update_is_never_automatically_replayed(tmp_path, status):
    path, state = successful_state(tmp_path)
    state["status"] = status
    with pytest.raises(ValueError, match="uncertain"):
        verify_resume(state, "contract", path, target_step=2, max_steps=2, world_size=1)


@pytest.mark.parametrize("target", [1, 3])
def test_resume_cannot_repeat_or_exceed_authorized_steps(tmp_path, target):
    path, state = successful_state(tmp_path)
    with pytest.raises(ValueError, match="step"):
        verify_resume(state, "contract", path, target_step=target, max_steps=2, world_size=1)


def test_sharded_index_must_reference_existing_weight_files(tmp_path):
    model(tmp_path / "model")
    (tmp_path / "model" / "model.safetensors.index.json").write_text(
        json.dumps({"weight_map": {"weight": "missing.safetensors"}})
    )
    with pytest.raises(ValueError, match="shard"):
        model_identity(tmp_path / "model")


def test_launcher_composes_native_two_teacher_recipe(tmp_path):
    from examples.harbor_mopd.launch import build_overrides
    from examples.harbor_opd_rl.launch import compose_config
    from tests.uni_agent.examples.test_harbor_opd_rl_recipe import prepared_launch
    from verl.utils.config import omega_conf_to_dataclass

    spec = registry(tmp_path)
    allocation = {
        "schema": "harbor-mopd-allocation-v1",
        "owner": "test",
        "schedule_reference": "test-only",
        "gpu_uuids": ["GPU-a", "GPU-b", "GPU-c"],
        "max_steps": 2,
        "budget_usd": 10,
    }
    files = {part: {"path": f"/{part}.parquet"} for part in ("train", "validation")}
    overrides = build_overrides(
        prepared_launch(),
        spec,
        {"files": files},
        allocation,
        run_root=tmp_path / "run",
        tool_parser="hermes",
        target_step=1,
    )
    cfg = compose_config(overrides)
    assert cfg.data.train_files == "/train.parquet"
    assert cfg.trainer.total_training_steps == 1
    assert cfg.trainer.v1.trainer_mode == "sync"
    assert cfg.actor_rollout_ref.rollout.custom.agent_framework.require_verifier_reward
    native = omega_conf_to_dataclass(cfg.distillation)
    assert set(native.teacher_models) == {"swe", "terminal"}
    assert native.teacher_models["swe"].model_path == str(tmp_path / "swe")


@pytest.mark.parametrize("devices", [["GPU-a", "GPU-b"], ["GPU-a", "GPU-b", "GPU-b"]])
def test_allocation_requires_three_distinct_real_gpu_roles(devices):
    from examples.harbor_mopd.launch import validate_allocation

    with pytest.raises(ValueError, match="three distinct"):
        validate_allocation(
            {
                "schema": "harbor-mopd-allocation-v1",
                "owner": "test",
                "schedule_reference": "test-only",
                "gpu_uuids": devices,
                "max_steps": 2,
                "budget_usd": 10,
            },
            target_step=1,
        )


def test_data_receipt_checks_bytes_domains_and_task_contents(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq

    from examples.harbor_mopd.launch import validate_data
    from examples.harbor_mopd.prepare import fingerprint_task, prepare_rows
    from tests.uni_agent.examples.test_harbor_mopd_prepare import fixture_data

    rows, manifest, _ = fixture_data()
    fingerprints = {}
    for i, entry in enumerate(manifest["tasks"]):
        task = tmp_path / f"task-{i}"
        task.mkdir()
        (task / "task.toml").write_text(f"# task {i}")
        fingerprints[entry["instance_id"]] = entry["fingerprint"] = fingerprint_task(task)
        for row in rows[entry["split"]]:
            metadata = row["extra_info"]["tools_kwargs"]["task"]["metadata"]
            if metadata["instance_id"] == entry["instance_id"]:
                metadata["task_path"] = str(task)
    prepared, receipt = prepare_rows(
        rows, manifest, allowed_domains={"swe", "terminal"}, task_fingerprints=fingerprints
    )
    receipt["files"] = {}
    for split, values in prepared.items():
        file = tmp_path / f"{split}.parquet"
        pq.write_table(pa.Table.from_pylist(values), file)
        receipt["files"][split] = {"path": str(file), "sha256": file_sha256(file)}
    assert validate_data(receipt)["train_rows"] == 2
    (tmp_path / "task-0" / "task.toml").write_text("# changed")
    with pytest.raises(ValueError, match="fingerprint"):
        validate_data(receipt)


def test_contract_ignores_only_execution_target_and_resume_pointer():
    from examples.harbor_mopd.launch import semantic_config
    from tests.uni_agent.examples.test_harbor_mopd_config import configured

    cfg = configured()
    before = semantic_config(cfg)
    cfg.trainer.total_training_steps = 9
    cfg.trainer.total_epochs = 9
    cfg.trainer.resume_mode = "resume_path"
    cfg.trainer.resume_from_path = "/saved/global_step_1"
    assert semantic_config(cfg) == before
    cfg.distillation.distillation_loss.loss_max_clamp = 2
    assert semantic_config(cfg) != before


def test_gpu_preflight_rejects_busy_or_missing_devices(monkeypatch):
    from examples.harbor_mopd.launch import check_gpu_allocation

    monkeypatch.setattr("subprocess.check_output", lambda *a, **k: "GPU-a, 80000\nGPU-b, 0\n")
    with pytest.raises(ValueError, match="occupied"):
        check_gpu_allocation({"gpu_uuids": ["GPU-a", "GPU-b", "GPU-c"]})


def test_gpu_preflight_checks_processes_even_with_low_memory(monkeypatch):
    from examples.harbor_mopd.launch import check_gpu_allocation

    values = iter(["GPU-a, 0\nGPU-b, 0\nGPU-c, 0\n", "GPU-b, 1234\n"])
    monkeypatch.setattr("subprocess.check_output", lambda *a, **k: next(values))
    with pytest.raises(ValueError, match="compute process"):
        check_gpu_allocation({"gpu_uuids": ["GPU-a", "GPU-b", "GPU-c"]})


def allocation():
    return {
        "schema": "harbor-mopd-allocation-v1",
        "owner": "test",
        "schedule_reference": "test-only",
        "gpu_uuids": ["GPU-a", "GPU-b", "GPU-c"],
        "max_steps": 2,
        "budget_usd": 10,
    }


def checkpoint_command(run_root, step):
    import sys

    script = (
        "from pathlib import Path; "
        f"p=Path({str(run_root)!r})/'checkpoints'/'global_step_{step}'; "
        "(p/'actor').mkdir(parents=True); (p/'data.pt').write_bytes(b'cursor'); "
        "[(p/'actor'/f'{kind}_world_size_1_rank_0.pt').write_bytes(kind.encode()) "
        "for kind in ['model','optim','extra_state']]"
    )
    return [sys.executable, "-c", script]


def test_subprocess_receipt_and_explicit_continuation(tmp_path, monkeypatch):
    import os

    from examples.harbor_mopd.launch import execute_run

    monkeypatch.setattr("examples.harbor_mopd.launch.check_gpu_allocation", lambda _: None)
    root = tmp_path / "run"
    common = dict(run_root=root, contract={"algorithm": "fixed"}, allocation=allocation(), environment=dict(os.environ))
    first = execute_run(checkpoint_command(root, 1), **common, target_step=1, resume=None)
    assert first["status"] == "process_succeeded" and first["capability_accepted"] is False
    with pytest.raises(FileExistsError):
        execute_run(checkpoint_command(root, 1), **common, target_step=1, resume=None)
    second = execute_run(
        checkpoint_command(root, 2), **common, target_step=2, resume=root / "checkpoints" / "global_step_1"
    )
    assert second["checkpoint"]["step"] == 2
    assert (root / "attempt-to-step-1" / "result.json").exists()
    assert (root / "attempt-to-step-2" / "result.json").exists()


@pytest.mark.parametrize("code", [0, 7])
def test_exit_zero_without_checkpoint_is_not_success(tmp_path, monkeypatch, code):
    import os
    import sys

    from examples.harbor_mopd.launch import execute_run

    monkeypatch.setattr("examples.harbor_mopd.launch.check_gpu_allocation", lambda _: None)
    root = tmp_path / "run"
    with pytest.raises((RuntimeError, ValueError)):
        execute_run(
            [sys.executable, "-c", f"raise SystemExit({code})"],
            run_root=root,
            contract={},
            allocation=allocation(),
            environment=dict(os.environ),
            target_step=1,
            resume=None,
        )
    assert json.loads((root / "state.json").read_text())["status"] == "failed"


def test_checkpoint_world_size_requires_every_rank(tmp_path):
    path = checkpoint(tmp_path)
    with pytest.raises(ValueError, match="world_size_2"):
        checkpoint_receipt(path, world_size=2)


def test_model_identity_binds_added_special_tokens(tmp_path):
    model(tmp_path / "model")
    before = model_identity(tmp_path / "model")
    (tmp_path / "model" / "tokenizer.json").write_text('{"model":{"vocab":{"x":0}},"added_tokens":[{"id":1}]}')
    assert model_identity(tmp_path / "model")["tokenizer_sha256"] != before["tokenizer_sha256"]


def test_inspect_model_cli_never_starts_training(tmp_path, capsys):
    from examples.harbor_mopd.launch import main

    spec = model(tmp_path / "model")
    main(["--inspect-model", spec["model_path"]])
    assert json.loads(capsys.readouterr().out)["sha256"] == spec["sha256"]


def test_native_resume_uses_constant_lr_without_warmup():
    from tests.uni_agent.examples.test_harbor_mopd_config import configured

    optim = configured().actor_rollout_ref.actor.optim
    assert optim.lr_scheduler_type == "constant"
    assert optim.lr_warmup_steps == 0 and optim.lr_warmup_steps_ratio == 0


def prepared_cli_inputs(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq
    from transformers import GPT2Config, GPT2LMHeadModel

    from examples.harbor_mopd.prepare import fingerprint_task
    from examples.harbor_mopd.prepare import main as prepare_main
    from tests.uni_agent.examples.test_harbor_launch_preflight import local_model
    from tests.uni_agent.examples.test_harbor_opd_rl_recipe import prepared_launch

    model_path = local_model(tmp_path)
    GPT2LMHeadModel(GPT2Config(vocab_size=3, n_embd=8, n_layer=1, n_head=1, n_positions=32)).save_pretrained(model_path)
    identity = {"model_path": str(model_path), "sha256": model_identity(model_path)["sha256"]}
    rows = {"train": [], "validation": []}
    tasks = []
    for i in range(6):
        split, domain = ("train" if i < 4 else "validation"), ("swe" if i % 2 == 0 else "terminal")
        task = tmp_path / f"task-{i}"
        task.mkdir()
        (task / "task.toml").write_text(f"# task {i}")
        instance = f"tasks-{split}/task-{i}"
        rows[split].append(
            {
                "data_source": f"tasks-{split}",
                "prompt": [{"role": "user", "content": "short"}],
                "extra_info": {
                    "tools_kwargs": {
                        "task": {"name": "harbor", "metadata": {"instance_id": instance, "task_path": str(task)}}
                    }
                },
            }
        )
        tasks.append(
            {
                "instance_id": instance,
                "task_id": f"task-{i}",
                "source": "fixture",
                "family": "fixture",
                "revision": "fixture-v1",
                "split": split,
                "fingerprint": fingerprint_task(task),
                "teacher_domain": domain,
            }
        )
    for split in rows:
        pq.write_table(pa.Table.from_pylist(rows[split]), tmp_path / f"{split}.parquet")
    (tmp_path / "manifest.json").write_text(json.dumps({"schema_version": 1, "tasks": tasks}))
    prepare_main(
        [
            "--train-parquet",
            str(tmp_path / "train.parquet"),
            "--validation-parquet",
            str(tmp_path / "validation.parquet"),
            "--manifest",
            str(tmp_path / "manifest.json"),
            "--domains",
            "swe",
            "terminal",
            "--output-dir",
            str(tmp_path / "prepared"),
        ]
    )
    (tmp_path / "task.yaml").write_text("fixture: true\n")
    launch = prepared_launch()
    launch["environment"]["TASK_CONFIG"] = str(tmp_path / "task.yaml")
    objects = {
        "launch": launch,
        "registry": {
            "schema": "harbor-mopd-registry-v1",
            "student": identity,
            "teachers": {"swe": identity, "terminal": identity},
        },
        "allocation": allocation(),
    }
    args = []
    for name, obj in objects.items():
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(obj))
        args.extend([f"--{name}", str(path)])
    return [
        *args,
        "--data-receipt",
        str(tmp_path / "prepared" / "receipt.json"),
        "--run-root",
        str(tmp_path / "run"),
        "--tool-parser",
        "hermes",
    ]


def test_full_local_preflight_uses_native_tokenizer_dataset_and_config(tmp_path, monkeypatch, capsys):
    from examples.harbor_mopd.launch import main

    args = prepared_cli_inputs(tmp_path)
    monkeypatch.setattr("examples.harbor_mopd.launch.execute_run", lambda *a, **k: pytest.fail("no GPU run permitted"))
    main(args)
    output = capsys.readouterr().out
    assert '"training_started": false' in output
    assert '"train_rows": 4' in output and '"validation_rows": 2' in output
    assert not (tmp_path / "run").exists()


def test_model_identity_binds_external_chat_template(tmp_path):
    model(tmp_path / "model")
    before = model_identity(tmp_path / "model")["sha256"]
    (tmp_path / "model" / "chat_template.jinja").write_text("{{ messages[0]['content'] }}")
    assert model_identity(tmp_path / "model")["sha256"] != before


def test_gpu_uuid_cannot_escape_lock_directory():
    from examples.harbor_mopd.launch import validate_allocation

    spec = allocation()
    spec["gpu_uuids"][0] = "GPU-../../outside"
    with pytest.raises(ValueError, match="three distinct"):
        validate_allocation(spec, target_step=1)


def test_public_cli_preserves_exact_native_command_and_resume_contract(tmp_path, monkeypatch, capsys):
    """Real preflight/state/subprocess IO; replace only the unavailable GPU trainer."""
    import importlib.metadata

    from examples.harbor_mopd import launch
    from examples.harbor_opd_rl.launch import compose_config

    args = prepared_cli_inputs(tmp_path)
    original_version = importlib.metadata.version
    monkeypatch.setattr(
        importlib.metadata, "version", lambda name: "cpu-boundary-fixture" if name == "vllm" else original_version(name)
    )
    monkeypatch.setattr(launch, "check_gpu_allocation", lambda _: None)
    actual_execute = launch.execute_run
    seen = []

    def execute_boundary(command, **kwargs):
        cfg = compose_config(command[4:])
        assert cfg.trainer.total_training_steps == kwargs["target_step"]
        assert cfg.trainer.total_epochs == 1
        assert cfg.actor_rollout_ref.actor.ppo_mini_batch_size == 2
        assert kwargs["environment"]["RAY_ADDRESS"] == "local"
        assert kwargs["environment"]["CUDA_VISIBLE_DEVICES"] == "GPU-a,GPU-b,GPU-c"
        seen.append(cfg.trainer.resume_mode)
        return actual_execute(checkpoint_command(kwargs["run_root"], kwargs["target_step"]), **kwargs)

    monkeypatch.setattr(launch, "execute_run", execute_boundary)
    launch.main([*args, "--execute"])
    launch.main(
        [
            *args,
            "--target-step",
            "2",
            "--resume-from-path",
            str(tmp_path / "run" / "checkpoints" / "global_step_1"),
            "--execute",
        ]
    )
    assert seen == ["disable", "resume_path"]
    state = json.loads((tmp_path / "run" / "state.json").read_text())
    assert state["target_step"] == 2 and state["capability_accepted"] is False
    assert '"process_succeeded"' in capsys.readouterr().out
