"""The operator gate binds real files, independent rank evidence and learning signals."""

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

pytestmark = [pytest.mark.cpu, pytest.mark.level0]
ROOT = Path(__file__).resolve().parents[3]


def module():
    path = ROOT / "docs/verl-uni-agent-harbor-opd-rl/mimo_world2_acceptance.py"
    spec = importlib.util.spec_from_file_location("world2_acceptance", path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    return path


def file_info(path):
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size}


def fixture(tmp_path, step=2):
    m = module()
    run = tmp_path / "run"
    launch = write(
        tmp_path / "launch.json",
        {
            "schema": "dsh.harbor-m2-launch.v1",
            "postprocessor": {"run_id": "r15", "run_spec_sha256": "sha256:" + "1" * 64},
            "environment": {"RUN_ROOT": str(run)},
        },
    )
    uid = "group-one"
    keys = [f"{uid}_{i}_0" for i in range(4)]
    batch = write(
        tmp_path / "batch.json",
        {
            "schema": "dsh.harbor-training-batch-audit.v1",
            "passed": True,
            "errors": [],
            "launch_sha256": "sha256:" + m.digest(launch),
            "groups": [
                {
                    "partition_id": "train",
                    "global_steps": step,
                    "status": "admitted-and-training-batch-matched",
                    "group_uid": uid,
                    "session_indexes": [0, 1, 2, 3],
                    "transfer_queue_keys": keys,
                    "consumed_transfer_queue_keys": keys,
                    "rewards": [0, 1, 0, 1],
                }
            ],
        },
    )
    metrics = tmp_path / "metrics.log"
    metrics.write_text(
        f"step:{step} - training/global_step:{step} - critic/score/min:0 - critic/score/max:1 - "
        "critic/advantages/min:-1 - critic/advantages/max:1 - actor/grad_norm:0.25 - actor/pg_loss:-0.1\n"
    )
    delta = {
        "schema": "dsh.native-sharded-checkpoint-delta.v1",
        "world_size": 2,
        "passed": True,
        "errors": [],
        "checker_sha256": m.CHECKER_SHA,
        "optimizer_checker_sha256": m.OPTIMIZER_SHA,
        "configs": {},
        "ranks": [],
        "model": {
            "base_count": 2,
            "base_changed": 0,
            "adapter_count": 1,
            "adapter_changed": 1,
            "all_finite": True,
            "passed": True,
        },
    }
    boxes = [{"rank": i, "offsets": [2 * i], "sizes": [2]} for i in range(2)]
    for rank in range(2):
        optimizer = {
            "schema": "dsh.native-optimizer-delta.v1",
            "passed": True,
            "errors": [],
            "active_state_count": 1,
            "empty_state_count": 0,
            "changed_moment_tensors": 2,
            "optimizer_step_advanced": True,
        }
        for label, absolute_step in [("before", step - 1), ("after", step)]:
            optimizer[label] = {
                "steps": [absolute_step],
                "active_state_count": 1,
                "empty_state_count": 0,
                "tensor_count": 3,
                "all_finite": True,
                "nonzero_moment_tensors": 2,
            }
        row = {"rank": rank, "passed": True, "errors": [], "files": {}, "optimizer": optimizer, "model": {}}
        for name, changed in [("base.weight", False), ("lora_A.weight", True)]:
            row["model"][name] = {
                "kind": "sharded",
                "descriptor": {"shape": [4], "dtype": "torch.float32", "boxes": boxes},
                "local": [
                    {"box": boxes[rank], "finite": True, "changed": changed, "max_abs_delta": 1.0 if changed else 0.0}
                ],
            }
        row["model"]["buffer"] = {
            "kind": "replicated",
            "descriptor": {"shape": [], "dtype": "torch.int64"},
            "finite": True,
            "changed": False,
            "max_abs_delta": 0.0,
            "before_sha256": "a" * 64,
            "after_sha256": "a" * 64,
        }
        for label, absolute_step in [("before", step - 1), ("after", step)]:
            folder = run / f"rl-training/checkpoints/global_step_{absolute_step}/actor"
            delta["configs"][label] = file_info(write(folder / "fsdp_config.json", {"world_size": 2}))
            for key, prefix in [("model", "model"), ("optimizer", "optim"), ("extra", "extra_state")]:
                path = folder / f"{prefix}_world_size_2_rank_{rank}.pt"
                path.write_bytes(f"opaque trusted file {prefix} {rank} {absolute_step}".encode())
                row["files"][label + "_" + key] = file_info(path)
        delta["ranks"].append(row)
    path = write(tmp_path / "delta.json", delta)
    return m, {
        "expected_run": "r15",
        "expected_spec": "sha256:" + "1" * 64,
        "step": step,
        "launch": launch,
        "batch_audit": batch,
        "console_metrics": metrics,
        "sharded_delta": path,
        "checkpoint_checker": ROOT / "deployment/checks/sharded_checkpoint_delta.py",
        "optimizer_checker": ROOT / "deployment/checks/optimizer_delta.py",
    }


@pytest.mark.parametrize("step", [2, 3])
def test_exact_world2_evidence_passes_for_adjacent_steps(tmp_path, step):
    m, args = fixture(tmp_path, step)
    result = m.audit(**args)
    assert result["passed"], result["errors"]
    assert result["identity"]["step"] == step
    assert result["world_size"] == 2 and result["effective_update_verified"]
    assert not result["resume_verified"] and not result["capability_improvement_verified"]


@pytest.mark.parametrize(
    "attack",
    [
        "fake-file-sha",
        "fake-checker-sha",
        "missing-rank",
        "constant-reward",
        "zero-grad",
        "base-changed",
        "zero-optimizer",
        "wrong-step",
        "wrong-run",
        "wrong-key",
        "summary",
        "incomplete-shard",
        "overlap",
        "replica",
        "duplicate-metrics",
        "wrong-path",
        "changed-source",
        "batch-launch",
        "nan-metric",
        "nonfinite-shard",
        "no-moment-change",
        "model-summary-only",
        "rank-failed",
        "old-schema",
    ],
)
def test_rejects_inconsistent_or_ineffective_evidence(tmp_path, attack):
    m, args = fixture(tmp_path)
    delta = json.loads(args["sharded_delta"].read_text())
    batch = json.loads(args["batch_audit"].read_text())
    if attack == "fake-file-sha":
        delta["ranks"][0]["files"]["after_model"]["sha256"] = "0" * 64
    elif attack == "fake-checker-sha":
        delta["checker_sha256"] = "0" * 64
    elif attack == "missing-rank":
        delta["ranks"].pop()
    elif attack == "constant-reward":
        batch["groups"][0]["rewards"] = [1] * 4
    elif attack == "zero-grad":
        args["console_metrics"].write_text(args["console_metrics"].read_text().replace("grad_norm:0.25", "grad_norm:0"))
    elif attack == "base-changed":
        row = delta["ranks"][0]["model"]["base.weight"]["local"][0]
        row.update(changed=True, max_abs_delta=1.0)
    elif attack == "zero-optimizer":
        delta["ranks"][0]["optimizer"]["before"]["nonzero_moment_tensors"] = 0
    elif attack == "wrong-step":
        delta["ranks"][1]["optimizer"]["after"]["steps"] = [3]
    elif attack == "wrong-run":
        args["expected_run"] = "other"
    elif attack == "wrong-key":
        batch["groups"][0]["consumed_transfer_queue_keys"].pop()
    elif attack == "summary":
        delta["model"]["adapter_changed"] = 100
    elif attack == "incomplete-shard":
        delta["ranks"][1]["model"]["lora_A.weight"]["local"] = []
    elif attack == "overlap":
        for rank in delta["ranks"]:
            rank["model"]["lora_A.weight"]["descriptor"]["boxes"][1]["offsets"] = [1]
    elif attack == "replica":
        delta["ranks"][1]["model"]["buffer"]["before_sha256"] = "b" * 64
    elif attack == "duplicate-metrics":
        args["console_metrics"].write_text(args["console_metrics"].read_text() * 2)
    elif attack == "wrong-path":
        delta["ranks"][0]["files"]["after_model"]["path"] = delta["ranks"][0]["files"]["before_model"]["path"]
    elif attack == "changed-source":
        path = tmp_path / "modified-checker.py"
        path.write_text("# modified")
        args["checkpoint_checker"] = path
    elif attack == "batch-launch":
        batch["launch_sha256"] = "sha256:" + "0" * 64
    elif attack == "nan-metric":
        args["console_metrics"].write_text(
            args["console_metrics"].read_text().replace("grad_norm:0.25", "grad_norm:nan")
        )
    elif attack == "nonfinite-shard":
        delta["ranks"][1]["model"]["lora_A.weight"]["local"][0]["finite"] = False
    elif attack == "no-moment-change":
        delta["ranks"][1]["optimizer"]["changed_moment_tensors"] = 0
    elif attack == "model-summary-only":
        delta["ranks"][1].pop("model")
    elif attack == "rank-failed":
        delta["ranks"][1]["passed"] = False
    elif attack == "old-schema":
        delta["schema"] = "dsh.single-rank-lora-delta.v1"
    write(args["sharded_delta"], delta)
    write(args["batch_audit"], batch)
    result = m.audit(**args)
    assert not result["passed"] and not result["effective_update_verified"] and result["errors"]


def test_cli_preserves_raw_failure_and_refuses_overwrite(tmp_path, monkeypatch, capsys):
    m, args = fixture(tmp_path)
    output = tmp_path / "result.json"
    argv = ["audit"]
    for key, value in args.items():
        argv += ["--" + key.replace("_", "-"), str(value)]
    monkeypatch.setattr("sys.argv", argv + ["--output", str(output)])
    assert m.main() == 0
    assert json.loads(capsys.readouterr().out)["passed"]
    with pytest.raises(FileExistsError):
        m.main()


def test_strict_json_rejects_duplicate_and_nonfinite(tmp_path):
    m = module()
    for raw in ('{"x":1,"x":2}', '{"x":NaN}'):
        path = tmp_path / "invalid.json"
        path.write_text(raw)
        with pytest.raises(ValueError):
            m.read_json(path)


def async_batch(args):
    batch = json.loads(args["batch_audit"].read_text())
    batch["schema"] = "dsh.harbor-training-batch-audit.v2"
    group = batch["groups"][0]
    group.update(global_steps=1, generation_global_steps=1, training_global_steps=2)
    group["consumed_rows"] = [
        dict(transfer_queue_key=key, training_global_steps=2, reward=reward)
        for key, reward in zip(group["transfer_queue_keys"], group["rewards"], strict=True)
    ]
    group["version_evidence"] = [
        dict(
            transfer_queue_key=key,
            min_global_steps=0,
            max_global_steps=1,
            generation_count=3,
            versioned_generation_count=3,
            version_evidence_complete=True,
        )
        for key in group["transfer_queue_keys"]
    ]
    return batch


def test_async_batch_joins_actual_consumer_step(tmp_path):
    m, args = fixture(tmp_path)
    write(args["batch_audit"], async_batch(args))
    report = m.audit(**args)
    assert report["passed"], report
    assert report["consumed_group"]["generation_global_steps"] == 1
    assert report["identity"]["step"] == 2


@pytest.mark.parametrize(
    "fault",
    [
        "missing-row",
        "wrong-key",
        "duplicate-key",
        "wrong-reward",
        "split-step",
        "future-generation",
        "missing-version",
        "wrong-generation-type",
        "future-policy",
        "distant-policy",
    ],
)
def test_async_effective_gate_rejects_false_crosswalk(tmp_path, fault):
    m, args = fixture(tmp_path)
    batch = async_batch(args)
    group = batch["groups"][0]
    if fault == "missing-row":
        group["consumed_rows"].pop()
    elif fault == "wrong-key":
        group["consumed_rows"][0]["transfer_queue_key"] = "fake"
    elif fault == "duplicate-key":
        group["consumed_rows"][0]["transfer_queue_key"] = group["consumed_rows"][1]["transfer_queue_key"]
    elif fault == "wrong-reward":
        group["consumed_rows"][0]["reward"] = 1
    elif fault == "split-step":
        group["consumed_rows"][0]["training_global_steps"] = 3
    elif fault == "future-generation":
        group["generation_global_steps"] = group["global_steps"] = 3
    elif fault == "missing-version":
        group["version_evidence"].pop()
    elif fault in {"future-policy", "distant-policy"}:
        group["version_evidence"][0]["max_global_steps"] = 2 if fault == "future-policy" else 99
    else:
        group["generation_global_steps"] = True
    write(args["batch_audit"], batch)
    assert not m.audit(**args)["passed"]


def dtensor_ranks(args):
    ranks = json.loads(args["sharded_delta"].read_text())["ranks"]
    for rank in ranks:
        rank["cuda_initialized"] = False
        for tensor in rank["model"].values():
            if tensor["kind"] == "sharded":
                tensor.update(kind="dtensor", local_tensor_type="torch.Tensor", local_device_type="cpu")
                tensor["descriptor"].update(
                    representation="DTensor",
                    stride=[1],
                    mesh={"ranks": [0, 1], "names": ["fsdp"], "device_type": "cuda"},
                    placements=["Shard(0)"],
                )
    return ranks


def test_native_dtensor_mesh_and_local_coverage_are_explicit(tmp_path):
    m, args = fixture(tmp_path)
    report = m.model_summary(dtensor_ranks(args))
    assert report["passed"] and report["adapter_changed"] == 1


@pytest.mark.parametrize(
    "fault",
    [
        "mesh-ranks",
        "mesh-names",
        "mesh-device",
        "placement",
        "stride",
        "box-placement",
        "unknown-representation",
        "local-type",
        "local-device",
        "cuda-init",
        "hidden-dtensor",
    ],
)
def test_dtensor_contract_rejects_forged_metadata(tmp_path, fault):
    m, args = fixture(tmp_path)
    ranks = dtensor_ranks(args)
    for rank in ranks:
        value = rank["model"]["lora_A.weight"]
        descriptor = value["descriptor"]
        if fault == "mesh-ranks":
            descriptor["mesh"]["ranks"] = [1, 0]
        elif fault == "mesh-names":
            descriptor["mesh"]["names"] = ["other"]
        elif fault == "mesh-device":
            descriptor["mesh"]["device_type"] = "meta"
        elif fault == "placement":
            descriptor["placements"] = ["Replicate()"]
        elif fault == "stride":
            descriptor["stride"] = [-1]
        elif fault == "unknown-representation":
            descriptor["representation"] = "OtherTensor"
        elif fault == "local-type":
            value["local_tensor_type"] = "DTensor"
        elif fault == "local-device":
            value["local_device_type"] = "cuda"
        elif fault == "cuda-init":
            rank["cuda_initialized"] = True
        elif fault == "hidden-dtensor":
            value["kind"] = "sharded"
        else:
            # Still a complete nonoverlapping partition, but not Shard(0)'s rank placement.
            for box in descriptor["boxes"]:
                box["offsets"][0] = 2 - box["offsets"][0]
            value["local"][0]["box"]["offsets"][0] = 2 - value["local"][0]["box"]["offsets"][0]
    with pytest.raises(ValueError):
        m.model_summary(ranks)


def cross_run_fixture(tmp_path):
    m, args = fixture(tmp_path, step=4)
    launch = json.loads(args["launch"].read_text())
    launch["postprocessor"]["run_id"] = args["expected_run"] = "r18"
    write(args["launch"], launch)
    batch = json.loads(args["batch_audit"].read_text())
    batch["launch_sha256"] = "sha256:" + m.digest(args["launch"])
    write(args["batch_audit"], batch)
    root = Path(launch["environment"]["RUN_ROOT"])
    old = root / "rl-training/checkpoints/global_step_3"
    parent = tmp_path / "parent-run/rl-training/checkpoints/global_step_3"
    parent.parent.mkdir(parents=True)
    old.rename(parent)  # Temporary fixture files only; production checkpoints stay in place.
    (parent / "data.pt").write_bytes(b"trusted native dataloader state")
    delta = json.loads(args["sharded_delta"].read_text())
    for label, folder in (("before", parent), ("after", root / "rl-training/checkpoints/global_step_4")):
        path = write(folder / "actor/fsdp_config.json", {"FSDP_version": 1, "world_size": 2})
        delta["configs"][label] = file_info(path)
    for rank in delta["ranks"]:
        for key, prefix in (("model", "model"), ("optimizer", "optim"), ("extra", "extra_state")):
            rank["files"]["before_" + key] = file_info(parent / f"actor/{prefix}_world_size_2_rank_{rank['rank']}.pt")
    write(args["sharded_delta"], delta)
    files = {
        str(p.relative_to(parent)): {k: v for k, v in file_info(p).items() if k != "path"}
        for p in parent.rglob("*")
        if p.is_file()
    }
    manifest = write(
        tmp_path / "resume-manifest.json",
        {
            "schema": "mimo.native-checkpoint-manifest.v1",
            "run_id": "r17",
            "source_commit": "b" * 40,
            "run_spec_sha256": "sha256:" + "2" * 64,
            "step": 3,
            "world_size": 2,
            "checkpoint": str(parent),
            "files": files,
        },
    )
    args.update(resume_manifest=manifest, resume_manifest_sha256=m.digest(manifest))
    return m, args, parent


def test_cross_run_parent_bound_update_does_not_claim_restore(tmp_path):
    m, args, parent = cross_run_fixture(tmp_path)
    result = m.audit(**args)
    assert result["passed"], result["errors"]
    assert result["parent_checkpoint"]["checkpoint"] == str(parent)
    assert result["parent_checkpoint"]["manifest"]["sha256"] == args["resume_manifest_sha256"]
    assert result["parent_checkpoint"]["run_id"] == "r17"
    assert result["effective_update_verified"] and not result["resume_verified"]


@pytest.mark.parametrize(
    "attack",
    [
        "no-manifest",
        "no-sha",
        "orphan-sha",
        "fake-sha",
        "parent-is-current",
        "source",
        "spec",
        "schema",
        "wrong-path",
        "traversal",
        "same-root",
        "wrong-step",
        "wrong-world",
        "wrong-fsdp",
        "missing-rank",
        "manifest-rank",
        "corrupt-data",
        "missing-data",
        "bytes",
        "file-sha",
        "file-traversal",
        "symlink",
        "after-parent",
    ],
)
def test_cross_run_rejects_unbound_or_incomplete_parent(tmp_path, attack):
    m, args, parent = cross_run_fixture(tmp_path)
    manifest = json.loads(args["resume_manifest"].read_text())
    if attack == "no-manifest":
        args.pop("resume_manifest")
        args.pop("resume_manifest_sha256")
    elif attack == "no-sha":
        args.pop("resume_manifest_sha256")
    elif attack == "orphan-sha":
        args.pop("resume_manifest")
    elif attack == "fake-sha":
        args["resume_manifest_sha256"] = "0" * 64
    elif attack == "parent-is-current":
        manifest["run_id"] = "r18"
    elif attack == "source":
        manifest["source_commit"] = "unbound"
    elif attack == "spec":
        manifest["run_spec_sha256"] = "unbound"
    elif attack == "schema":
        manifest["schema"] = "other"
    elif attack == "wrong-path":
        manifest["checkpoint"] = str(parent.with_name("global_step_2"))
    elif attack == "traversal":
        manifest["checkpoint"] = str(parent / "../global_step_3")
    elif attack == "same-root":
        manifest["checkpoint"] = str(tmp_path / "run/rl-training/checkpoints/global_step_3")
    elif attack == "wrong-step":
        manifest["step"] = 2
    elif attack == "wrong-world":
        manifest["world_size"] = 1
    elif attack == "wrong-fsdp":
        path = write(parent / "actor/fsdp_config.json", {"FSDP_version": 2, "world_size": 2})
        manifest["files"]["actor/fsdp_config.json"] = {k: v for k, v in file_info(path).items() if k != "path"}
    elif attack == "missing-rank":
        (parent / "actor/model_world_size_2_rank_1.pt").unlink()
    elif attack == "manifest-rank":
        manifest["files"].pop("actor/extra_state_world_size_2_rank_1.pt")
    elif attack == "corrupt-data":
        (parent / "data.pt").write_bytes(b"changed")
    elif attack == "missing-data":
        manifest["files"].pop("data.pt")
    elif attack == "bytes":
        manifest["files"]["data.pt"]["bytes"] += 1
    elif attack == "file-sha":
        manifest["files"]["data.pt"]["sha256"] = "0" * 64
    elif attack == "file-traversal":
        manifest["files"]["../outside"] = manifest["files"]["data.pt"]
    elif attack == "symlink":
        path = parent / "data.pt"
        outside = tmp_path / "outside.pt"
        path.rename(outside)
        path.symlink_to(outside)
    elif attack == "after-parent":
        delta = json.loads(args["sharded_delta"].read_text())
        delta["ranks"][0]["files"]["after_model"] = delta["ranks"][0]["files"]["before_model"]
        write(args["sharded_delta"], delta)
    if "resume_manifest" in args:
        write(args["resume_manifest"], manifest)
        if attack not in {"fake-sha", "no-sha"}:
            args["resume_manifest_sha256"] = m.digest(args["resume_manifest"])
    result = m.audit(**args)
    assert not result["passed"], attack
    assert result["errors"], attack


def test_cross_run_cli_preserves_explicit_manifest_binding(tmp_path, monkeypatch, capsys):
    m, args, parent = cross_run_fixture(tmp_path)
    output = tmp_path / "cross-run-report.json"
    argv = ["audit", "--output", str(output)]
    for key, value in args.items():
        argv += ["--" + key.replace("_", "-"), str(value)]
    monkeypatch.setattr("sys.argv", argv)
    assert m.main() == 0
    assert json.loads(capsys.readouterr().out)["passed"] is True
    result = json.loads(output.read_text())
    assert result["parent_checkpoint"]["checkpoint"] == str(parent)
    assert result["parent_checkpoint"]["manifest"]["sha256"] == args["resume_manifest_sha256"]
    assert result["resume_verified"] is False
