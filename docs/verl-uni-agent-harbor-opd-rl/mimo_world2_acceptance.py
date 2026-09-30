"""Read-only operator gate for an effective update in native world-size-two checkpoints.

This combines independently produced evidence; it does not execute training,
restore checkpoints, assess capability uplift, or replace GPU/monitoring audits.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path

from deployment.checks.effective_update_audit import parse_console_metrics

CHECKER_SHA = "ea9055884d8474bb511f0e8593dcee3fd9769714244deacd4d9c1c3017ff05a6"
OPTIMIZER_SHA = "037d220fdd280d5ca07989554031db99c82ca6b450aef6327b47a6910cc0ccee"
RESUME_FILES = {
    "data.pt",
    "actor/fsdp_config.json",
    *(
        f"actor/{prefix}_world_size_2_rank_{rank}.pt"
        for rank in range(2)
        for prefix in ("model", "optim", "extra_state")
    ),
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def integer(value, minimum=0):
    return type(value) is int and value >= minimum


def digest(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), "Expected regular evidence file")
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def absolute(value):
    path = Path(value)
    require(path.is_absolute() and ".." not in path.parts, "Expected absolute path without traversal")
    require(not path.is_symlink(), "Symlink evidence forbidden")
    return path.resolve()


def identity(path):
    path = absolute(path)
    return {"path": str(path), "sha256": digest(path), "bytes": path.stat().st_size}


def read_json(path):
    path = Path(path)
    require(path.stat().st_size <= 64 * 1024 * 1024, "Evidence report exceeds bound")

    def pairs(items):
        value = {}
        for key, item in items:
            require(key not in value, "Duplicate JSON key")
            value[key] = item
        return value

    def invalid(value):
        raise ValueError("Nonfinite JSON constant")

    require(path.is_file() and not path.is_symlink(), "Expected regular JSON report")
    return json.loads(path.read_bytes(), object_pairs_hook=pairs, parse_constant=invalid)


def bind_file(item, expected):
    expected = absolute(expected)
    require(absolute(item["path"]) == expected, "Checkpoint evidence path mismatch")
    require(re.fullmatch(r"[0-9a-f]{64}", item["sha256"]) is not None, "Invalid checkpoint SHA")
    require(digest(expected) == item["sha256"], "Checkpoint SHA mismatch")
    if "bytes" in item:
        require(type(item["bytes"]) is int and item["bytes"] == expected.stat().st_size, "File size mismatch")


def bind_parent_checkpoint(path, expected_sha, *, current_root, current_run, step):
    """Bind an independent parent checkpoint without treating comparison as restore."""
    require(
        isinstance(expected_sha, str) and re.fullmatch(r"[0-9a-f]{64}", expected_sha), "Expected parent manifest SHA"
    )
    manifest_identity = identity(path)
    require(manifest_identity["sha256"] == expected_sha, "Parent manifest SHA mismatch")
    manifest = read_json(path)
    require(manifest["schema"] == "mimo.native-checkpoint-manifest.v1", "Parent manifest schema differs")
    require(
        isinstance(manifest["run_id"], str) and manifest["run_id"] and manifest["run_id"] != current_run,
        "Parent and current run identities must differ",
    )
    require(
        isinstance(manifest["source_commit"], str)
        and re.fullmatch(r"[0-9a-f]{40}", manifest["source_commit"])
        and isinstance(manifest["run_spec_sha256"], str)
        and re.fullmatch(r"sha256:[0-9a-f]{64}", manifest["run_spec_sha256"]),
        "Parent source/spec identity malformed",
    )
    require(integer(manifest["step"], 1) and manifest["step"] == step - 1, "Parent checkpoint step differs")
    require(type(manifest["world_size"]) is int and manifest["world_size"] == 2, "Parent checkpoint world size differs")
    checkpoint = absolute(manifest["checkpoint"])
    require(
        checkpoint.name == f"global_step_{step - 1}"
        and checkpoint.parent.name == "checkpoints"
        and checkpoint.parent.parent.name == "rl-training"
        and checkpoint.parents[2] != current_root
        and checkpoint.is_dir(),
        "Parent checkpoint path must identify an independent native run",
    )
    files = manifest["files"]
    require(isinstance(files, dict) and RESUME_FILES <= files.keys(), "Incomplete parent checkpoint manifest")
    for name, item in files.items():
        relative = Path(name)
        require(not relative.is_absolute() and ".." not in relative.parts, "Invalid parent checkpoint file path")
        target = checkpoint / relative
        require(target.resolve().is_relative_to(checkpoint), "Parent checkpoint file escapes root")
        require(integer(item["bytes"], 1), "Invalid parent file size")
        before = target.stat()
        bind_file({**item, "path": str(target)}, target)
        after = target.stat()
        require(
            (before.st_size, before.st_mtime_ns, before.st_ino) == (after.st_size, after.st_mtime_ns, after.st_ino),
            "Parent checkpoint changed during hashing",
        )
    config = read_json(checkpoint / "actor/fsdp_config.json")
    require(
        type(config["world_size"]) is int
        and config["world_size"] == 2
        and type(config.get("FSDP_version")) is int
        and config["FSDP_version"] == 1,
        "Parent checkpoint requires native FSDP version one/world two",
    )
    require(digest(path) == expected_sha, "Parent manifest changed during validation")
    return checkpoint, {
        "manifest": manifest_identity,
        "run_id": manifest["run_id"],
        "source_commit": manifest["source_commit"],
        "run_spec_sha256": manifest["run_spec_sha256"],
        "checkpoint": str(checkpoint),
        "step": manifest["step"],
        "world_size": 2,
        "fsdp_version": 1,
        "files": files,
        "scope": "parent-bound checkpoint comparison; native restore remains separately unverified",
    }


def validate_coverage(shape, boxes):
    require(isinstance(shape, list) and shape and all(integer(n, 1) for n in shape), "Invalid shard shape")
    volume = 0
    for index, box in enumerate(boxes):
        offsets, sizes = box["offsets"], box["sizes"]
        require(type(box["rank"]) is int and box["rank"] in (0, 1), "Invalid shard rank")
        require(len(offsets) == len(sizes) == len(shape), "Shard dimensionality mismatch")
        require(
            all(integer(o) and integer(s, 1) and o + s <= n for o, s, n in zip(offsets, sizes, shape, strict=True)),
            "Invalid shard bounds",
        )
        volume += math.prod(sizes)
        for previous in boxes[:index]:
            overlap = all(
                max(a, b) < min(a + x, b + y)
                for a, b, x, y in zip(offsets, previous["offsets"], sizes, previous["sizes"], strict=True)
            )
            require(not overlap, "Overlapping shards")
    require(volume == math.prod(shape), "Incomplete shard coverage")


def validate_dtensor_descriptor(descriptor):
    """R17's native CUDA FSDP mesh, with placement independently reconstructed."""
    require(descriptor["representation"] == "DTensor", "Unknown sharded representation")
    mesh = descriptor["mesh"]
    require(
        mesh["ranks"] == [0, 1]
        and all(type(rank) is int for rank in mesh["ranks"])
        and mesh["names"] == ["fsdp"]
        and mesh["device_type"] == "cuda",
        "Unexpected native DTensor mesh",
    )
    require(descriptor["placements"] == ["Shard(0)"], "Unexpected DTensor placement")
    shape, stride = descriptor["shape"], descriptor["stride"]
    require(len(stride) == len(shape) and all(integer(value) for value in stride), "Invalid DTensor stride")
    width = (shape[0] + 1) // 2
    boxes = []
    for rank in range(2):
        start = min(rank * width, shape[0])
        size = min(width, shape[0] - start)
        if size:
            boxes.append({"offsets": [start] + [0] * (len(shape) - 1), "sizes": [size] + shape[1:], "rank": rank})
    require(descriptor["boxes"] == boxes, "DTensor boxes disagree with mesh placement")


def model_summary(ranks):
    left, right = (row["model"] for row in ranks)
    require(isinstance(left, dict) and left and left.keys() == right.keys(), "Cross-rank model keys differ")
    counts = {"base_count": 0, "base_changed": 0, "adapter_count": 0, "adapter_changed": 0, "all_finite": True}
    for name, a in left.items():
        require(isinstance(name, str) and name, "Invalid tensor name")
        b = right[name]
        require(a["kind"] == b["kind"] and a["descriptor"] == b["descriptor"], "Cross-rank metadata differs")
        if a["kind"] in {"sharded", "dtensor"}:
            boxes = a["descriptor"]["boxes"]
            validate_coverage(a["descriptor"]["shape"], boxes)
            if a["kind"] == "dtensor":
                validate_dtensor_descriptor(a["descriptor"])
                require(
                    all(
                        row["local_tensor_type"] == "torch.Tensor" and row["local_device_type"] == "cpu"
                        for row in (a, b)
                    )
                    and all(rank["cuda_initialized"] is False for rank in ranks),
                    "DTensor audit requires plain local CPU tensors without CUDA initialization",
                )
            else:
                require("representation" not in a["descriptor"], "ShardedTensor cannot conceal another representation")
            rows = a["local"] + b["local"]
            for rank, local in enumerate((a["local"], b["local"])):
                require(all(row["box"]["rank"] == rank for row in local), "Local shard rank mismatch")
            require(
                sorted(json.dumps(row["box"], sort_keys=True) for row in rows)
                == sorted(json.dumps(box, sort_keys=True) for box in boxes),
                "Local shards do not cover global metadata",
            )
        else:
            require(a["kind"] == "replicated", "Unknown tensor representation")
            for key in ("before_sha256", "after_sha256"):
                require(re.fullmatch(r"[0-9a-f]{64}", a[key]) is not None and a[key] == b[key], "Replica hash mismatch")
            rows = [a, b]
        for row in rows:
            require(row["finite"] is True and type(row["changed"]) is bool, "Nonfinite or invalid tensor")
            delta = row["max_abs_delta"]
            require(finite(delta) and delta >= 0 and (delta > 0) == row["changed"], "Tensor delta differs")
        kind = "adapter" if "lora_" in name.lower() else "base"
        counts[kind + "_count"] += 1
        counts[kind + "_changed"] += int(any(row["changed"] for row in rows))
    require(counts["base_count"] > 0 and counts["base_changed"] == 0, "Base tensors changed or missing")
    require(counts["adapter_changed"] > 0, "No LoRA tensor changed")
    counts["passed"] = True
    return counts


def validate_optimizer(report, step):
    require(report["schema"] == "dsh.native-optimizer-delta.v1", "Optimizer schema mismatch")
    require(report["passed"] is True and report["errors"] == [], "Optimizer audit failed")
    active, empty = report["active_state_count"], report["empty_state_count"]
    require(integer(active, 1) and integer(empty), "Invalid optimizer topology")
    require(report["optimizer_step_advanced"] is True, "Optimizer did not advance")
    changed = report["changed_moment_tensors"]
    require(integer(changed, 1) and changed <= 2 * active, "Optimizer moments did not change")
    for label, expected in (("before", step - 1), ("after", step)):
        state = report[label]
        require(state["steps"] == [expected] and type(state["steps"][0]) is int, "Optimizer step mismatch")
        require(state["all_finite"] is True, "Nonfinite optimizer state")
        for key, count in (("active_state_count", active), ("empty_state_count", empty), ("tensor_count", 3 * active)):
            require(type(state[key]) is int and state[key] == count, "Optimizer counts differ")
        require(
            integer(state["nonzero_moment_tensors"], 1) and state["nonzero_moment_tensors"] <= 2 * active,
            "Optimizer moments are zero or invalid",
        )


def audit(
    *,
    expected_run,
    expected_spec,
    step,
    launch,
    batch_audit,
    console_metrics,
    sharded_delta,
    checkpoint_checker,
    optimizer_checker,
    resume_manifest=None,
    resume_manifest_sha256=None,
):
    report = {
        "schema": "mimo.world2-effective-update.v1",
        "world_size": 2,
        "passed": False,
        "effective_update_verified": False,
        "resume_verified": False,
        "exact_inflight_replay_verified": False,
        "capability_improvement_verified": False,
        "restore_evidence": "not-tested; checkpoint comparison is not independent restore",
        "errors": [],
    }
    try:
        require(
            (resume_manifest is None) == (resume_manifest_sha256 is None),
            "Parent manifest and its expected SHA must be supplied together",
        )
        require(integer(step, 2), "Expected absolute step >= 2")
        require(isinstance(expected_run, str) and expected_run, "Expected run required")
        require(re.fullmatch(r"sha256:[0-9a-f]{64}", expected_spec) is not None, "Expected spec SHA required")
        paths = {
            "launch": launch,
            "batch_audit": batch_audit,
            "console_metrics": console_metrics,
            "sharded_delta": sharded_delta,
            "checkpoint_checker": checkpoint_checker,
            "optimizer_checker": optimizer_checker,
        }
        report["inputs"] = {name: identity(path) for name, path in paths.items()}
        launch, batch, delta = (read_json(path) for path in (launch, batch_audit, sharded_delta))
        require(launch["schema"] == "dsh.harbor-m2-launch.v1", "Launch schema mismatch")
        require(
            launch["postprocessor"]["run_id"] == expected_run
            and launch["postprocessor"]["run_spec_sha256"] == expected_spec,
            "Launch run/spec mismatch",
        )
        require(
            batch["schema"] in {"dsh.harbor-training-batch-audit.v1", "dsh.harbor-training-batch-audit.v2"}
            and batch["passed"] is True
            and batch["errors"] == [],
            "Batch audit failed",
        )
        require(batch["launch_sha256"] == "sha256:" + report["inputs"]["launch"]["sha256"], "Batch launch SHA mismatch")
        asynchronous = batch["schema"] == "dsh.harbor-training-batch-audit.v2"
        step_field = "training_global_steps" if asynchronous else "global_steps"
        groups = [g for g in batch["groups"] if g["partition_id"] == "train" and g[step_field] == step]
        require(len(groups) == 1, "Expected one consumed group for selected step")
        group = groups[0]
        require(
            type(group[step_field]) is int and group["status"] == "admitted-and-training-batch-matched",
            "Unconsumed group",
        )
        uid = group["group_uid"]
        require(isinstance(uid, str) and uid, "Group identity required")
        require(
            all(type(i) is int for i in group["session_indexes"])
            and sorted(group["session_indexes"]) == list(range(4)),
            "Incomplete n4 group",
        )
        require(
            sorted(group["transfer_queue_keys"]) == [f"{uid}_{i}_0" for i in range(4)]
            and group["consumed_transfer_queue_keys"] == group["transfer_queue_keys"],
            "Consumed keys mismatch",
        )
        rewards = group["rewards"]
        require(
            len(rewards) == 4 and all(finite(v) for v in rewards) and min(rewards) < max(rewards),
            "Constant or invalid rewards",
        )
        if asynchronous:
            generation_step = group["generation_global_steps"]
            require(
                integer(generation_step)
                and generation_step <= step
                and type(group["global_steps"]) is int
                and group["global_steps"] == generation_step,
                "Invalid generation/consumption step crosswalk",
            )
            keys = group["transfer_queue_keys"]
            consumed = group["consumed_rows"]
            require(
                len(consumed) == 4
                and [row["transfer_queue_key"] for row in consumed] == keys
                and all(
                    type(row["training_global_steps"]) is int
                    and row["training_global_steps"] == step
                    and finite(row["reward"])
                    and row["reward"] == reward
                    for row, reward in zip(consumed, rewards, strict=True)
                ),
                "Invalid unique asynchronous consumption rows",
            )
            versions = group["version_evidence"]
            require(
                len(versions) == 4 and [row["transfer_queue_key"] for row in versions] == keys,
                "Incomplete asynchronous version evidence",
            )
            for evidence in versions:
                require(
                    integer(evidence["min_global_steps"])
                    and integer(evidence["max_global_steps"])
                    and evidence["min_global_steps"] <= evidence["max_global_steps"]
                    and evidence["max_global_steps"] < step
                    and integer(evidence["generation_count"], 1)
                    and type(evidence["versioned_generation_count"]) is int
                    and evidence["versioned_generation_count"] == evidence["generation_count"]
                    and evidence["version_evidence_complete"] is True,
                    "Invalid asynchronous Gateway versions",
                )
        require(Path(console_metrics).stat().st_size <= 64 * 1024 * 1024, "Console metrics exceed bound")
        rows = [
            row
            for row in parse_console_metrics(Path(console_metrics).read_text())
            if row.get("training/global_step") == step
        ]
        require(len(rows) == 1, "Missing/duplicate same-step console metrics")
        fields = (
            "critic/score/min",
            "critic/score/max",
            "critic/advantages/min",
            "critic/advantages/max",
            "actor/grad_norm",
            "actor/pg_loss",
        )
        metrics = {key: rows[0][key] for key in fields}
        require(all(finite(v) for v in metrics.values()), "Nonfinite metrics")
        require(metrics[fields[0]] == min(rewards) and metrics[fields[1]] == max(rewards), "Console rewards differ")
        require(
            metrics[fields[2]] < 0 < metrics[fields[3]] and metrics[fields[4]] > 0,
            "Need signed advantages and nonzero gradient",
        )
        require(
            delta["schema"] == "dsh.native-sharded-checkpoint-delta.v1"
            and type(delta["world_size"]) is int
            and delta["world_size"] == 2,
            "Expected native world2 schema",
        )
        require(delta["passed"] is True and delta["errors"] == [], "Sharded audit failed")
        require(
            delta["checker_sha256"] == report["inputs"]["checkpoint_checker"]["sha256"] == CHECKER_SHA,
            "Checkpoint checker SHA mismatch",
        )
        require(
            delta["optimizer_checker_sha256"] == report["inputs"]["optimizer_checker"]["sha256"] == OPTIMIZER_SHA,
            "Optimizer checker SHA mismatch",
        )
        ranks = delta["ranks"]
        require(
            len(ranks) == 2
            and all(type(row["rank"]) is int for row in ranks)
            and [row["rank"] for row in ranks] == [0, 1],
            "Missing/duplicate rank",
        )
        run_root = absolute(launch["environment"]["RUN_ROOT"])
        root = run_root / "rl-training/checkpoints"
        checkpoints = {"before": root / f"global_step_{step - 1}/actor", "after": root / f"global_step_{step}/actor"}
        if resume_manifest is not None:
            parent, parent_report = bind_parent_checkpoint(
                resume_manifest, resume_manifest_sha256, current_root=run_root, current_run=expected_run, step=step
            )
            checkpoints["before"] = parent / "actor"
            report["parent_checkpoint"] = parent_report
        for label, folder in checkpoints.items():
            bind_file(delta["configs"][label], folder / "fsdp_config.json")
            config = read_json(folder / "fsdp_config.json")
            world_size = config["world_size"]
            require(type(world_size) is int and world_size == 2, "FSDP config is not world2")
            if resume_manifest is not None:
                require(type(config.get("FSDP_version")) is int and config["FSDP_version"] == 1, "FSDP version differs")
            for rank in ranks:
                require(rank["passed"] is True and rank["errors"] == [], "Rank audit failed")
                for key, prefix in (("model", "model"), ("optimizer", "optim"), ("extra", "extra_state")):
                    bind_file(
                        rank["files"][label + "_" + key], folder / f"{prefix}_world_size_2_rank_{rank['rank']}.pt"
                    )
        counts = model_summary(ranks)
        require(counts == delta["model"], "Model summary differs from shard evidence")
        for rank in ranks:
            validate_optimizer(rank["optimizer"], step)
        report.update(
            passed=True,
            effective_update_verified=True,
            identity={"run_id": expected_run, "run_spec_sha256": expected_spec, "step": step, "group_uid": uid},
            consumed_group=group,
            metrics=metrics,
            model=counts,
            ranks=[{"rank": row["rank"], "files": row["files"], "optimizer": row["optimizer"]} for row in ranks],
        )
    except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError) as error:
        report["errors"].append(f"{type(error).__name__}: {error}")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-run", default="mimo9b-001661-r15")
    parser.add_argument("--expected-spec", required=True)
    parser.add_argument("--step", type=int, default=2)
    parser.add_argument("--resume-manifest", type=Path, help="Explicit independent parent checkpoint manifest")
    parser.add_argument("--resume-manifest-sha256", help="Expected SHA256 of the parent manifest")
    for name in (
        "launch",
        "batch-audit",
        "console-metrics",
        "sharded-delta",
        "checkpoint-checker",
        "optimizer-checker",
        "output",
    ):
        parser.add_argument("--" + name, type=Path, required=True)
    args = vars(parser.parse_args())
    output = args.pop("output")
    with output.open("x") as stream:
        report = audit(**args)
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"passed": report["passed"], "output": str(output)}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
