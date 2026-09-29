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
