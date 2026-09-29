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

CHECKER_SHA = "ee49a0f89a5ac651ea59bcd4d5f09ff97c0f40f04a0aac4b3275b3bdbc163715"
OPTIMIZER_SHA = "037d220fdd280d5ca07989554031db99c82ca6b450aef6327b47a6910cc0ccee"


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


def model_summary(ranks):
    left, right = (row["model"] for row in ranks)
    require(isinstance(left, dict) and left and left.keys() == right.keys(), "Cross-rank model keys differ")
    counts = {"base_count": 0, "base_changed": 0, "adapter_count": 0, "adapter_changed": 0, "all_finite": True}
    for name, a in left.items():
        require(isinstance(name, str) and name, "Invalid tensor name")
        b = right[name]
        require(a["kind"] == b["kind"] and a["descriptor"] == b["descriptor"], "Cross-rank metadata differs")
        if a["kind"] == "sharded":
            boxes = a["descriptor"]["boxes"]
            validate_coverage(a["descriptor"]["shape"], boxes)
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
            batch["schema"] == "dsh.harbor-training-batch-audit.v1"
            and batch["passed"] is True
            and batch["errors"] == [],
            "Batch audit failed",
        )
        require(batch["launch_sha256"] == "sha256:" + report["inputs"]["launch"]["sha256"], "Batch launch SHA mismatch")
        groups = [g for g in batch["groups"] if g["partition_id"] == "train" and g["global_steps"] == step]
        require(len(groups) == 1, "Expected one consumed group for selected step")
        group = groups[0]
        require(
            type(group["global_steps"]) is int and group["status"] == "admitted-and-training-batch-matched",
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
        root = absolute(launch["environment"]["RUN_ROOT"]) / "rl-training/checkpoints"
        checkpoints = {"before": root / f"global_step_{step - 1}/actor", "after": root / f"global_step_{step}/actor"}
        for label, folder in checkpoints.items():
            bind_file(delta["configs"][label], folder / "fsdp_config.json")
            world_size = read_json(folder / "fsdp_config.json")["world_size"]
            require(type(world_size) is int and world_size == 2, "FSDP config is not world2")
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
