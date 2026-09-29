"""Read-only consistency gate for one n=4, single-rank LoRA training update.

Consumes operator-provided audit reports; never loads model/optimizer tensors.
Public hashes bind report inputs, not their authority. A passing update does not
prove independent reload, exact asynchronous replay, or capability improvement.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _integer(value, minimum=0):
    return type(value) is int and value >= minimum


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _sha(value, *, prefix=True):
    pattern = r"sha256:[0-9a-f]{64}" if prefix else r"(?:sha256:)?[0-9a-f]{64}"
    return isinstance(value, str) and re.fullmatch(pattern, value) is not None


def _path(value):
    path = Path(value)
    _require(path.is_absolute() and ".." not in path.parts, "Checkpoint/run paths must be absolute without traversal")
    return path.resolve()


def _files(report, before, after, kind):
    for key, checkpoint in (("before", before), ("after", after)):
        item = report[key]
        expected = checkpoint / "actor" / f"{kind}_world_size_1_rank_0.pt"
        _require(_path(item["path"]) == expected, f"{kind} {key} checkpoint path mismatch")
        _require(_sha(item["sha256"], prefix=False), f"{kind} {key} SHA256 missing/invalid")
    _require(
        report["before"]["sha256"].removeprefix("sha256:") != report["after"]["sha256"].removeprefix("sha256:"),
        f"{kind} checkpoint hashes did not change",
    )


def _model(report, before, after):
    _require(report["schema"] == "dsh.single-rank-lora-delta.v1" and report["passed"] is True, "Model delta failed")
    _files(report, before, after, "model")
    rows = report["tensors"]
    _require(isinstance(rows, list) and bool(rows), "Model tensor evidence missing")
    names, adapters, adapter_changed, bases, base_changed = set(), 0, 0, 0, 0
    for row in rows:
        name = row["name"]
        _require(isinstance(name, str) and name and name not in names, "Model tensor identity invalid/duplicate")
        names.add(name)
        _require(type(row["adapter"]) is bool and row["adapter"] == ("lora_" in name), "Adapter identity differs")
        _require(row["finite"] is True and type(row["changed"]) is bool, "Nonfinite/invalid model tensor")
        delta = row["max_abs_delta"]
        _require(_finite(delta) and delta >= 0 and (delta > 0) is row["changed"], "Model delta magnitude differs")
        if row["adapter"]:
            adapters += 1
            adapter_changed += int(row["changed"])
        else:
            bases += 1
            base_changed += int(row["changed"])
    for field, count in (
        ("adapter_count", adapters),
        ("adapter_changed", adapter_changed),
        ("base_count", bases),
        ("base_changed", base_changed),
    ):
        _require(_integer(report[field]) and report[field] == count, "Model summary differs from tensor evidence")
    _require(
        adapter_changed > 0 and bases > 0 and base_changed == 0, "Adapter must change with all base tensors unchanged"
    )


def _optimizer(report, before, after, step):
    _require(report["schema"] == "dsh.native-optimizer-delta.v1", "Optimizer schema mismatch")
    _require(report["passed"] is True and report["errors"] == [], "Optimizer delta failed or needs fresh state checks")
    _files(report["files"], before, after, "optim")
    active, empty = report["active_state_count"], report["empty_state_count"]
    _require(_integer(active, 1) and _integer(empty), "Optimizer topology missing/invalid")
    _require(report["optimizer_step_advanced"] is True, "Optimizer did not advance")
    changed = report["changed_moment_tensors"]
    _require(_integer(changed, 1) and changed <= 2 * active, "Optimizer moments did not change/invalid count")
    for key, expected in (("before", step - 1), ("after", step)):
        state = report[key]
        _require(
            isinstance(state["steps"], list)
            and len(state["steps"]) == 1
            and _integer(state["steps"][0], 1)
            and state["steps"][0] == expected,
            "Optimizer must resume at the previous absolute step and advance exactly once",
        )
        _require(state["all_finite"] is True, "Nonfinite optimizer evidence")
        for field, expected_count in (
            ("active_state_count", active),
            ("empty_state_count", empty),
            ("tensor_count", 3 * active),
        ):
            _require(_integer(state[field]) and state[field] == expected_count, "Optimizer state topology differs")
        _require(
            _integer(state["nonzero_moment_tensors"], 1) and state["nonzero_moment_tensors"] <= 2 * active,
            "Optimizer state nonzero evidence missing",
        )


def audit_effective_update(
    *,
    run_id,
    run_spec_sha256,
    step,
    group_uid,
    launch,
    launch_sha256,
    batch_audit,
    metrics_rows,
    model_delta,
    optimizer_delta,
    before_checkpoint,
    after_checkpoint,
):
    """Validate one operator-selected step; all evidence must independently belong to this run.

    The caller owns input provenance. This validates the saved reports and their
    bindings, without re-running their underlying tensor or receipt inspectors.
    """
    report = dict(
        schema="dsh.effective-update-audit.v1",
        passed=False,
        effective_update_verified=False,
        resume_verified=False,
        restore_evidence={"status": "unknown", "reason": "No independent reload evidence supplied"},
        needs_fresh_after_check=False,
        errors=[],
    )
    if isinstance(optimizer_delta, dict):
        report["needs_fresh_after_check"] = any(
            "All optimizer moments are zero" in str(error) for error in (optimizer_delta.get("errors") or [])
        )
    try:
        _require(isinstance(run_id, str) and run_id and isinstance(group_uid, str) and group_uid, "Run/uid required")
        _require(_integer(step, 2), "Step must be an integer >=2 with an existing optimizer checkpoint")
        _require(_sha(run_spec_sha256) and _sha(launch_sha256), "Run spec/launch digest invalid")
        _require(launch["schema"] == "dsh.harbor-m2-launch.v1", "Launch schema mismatch")
        policy = launch["postprocessor"]
        _require(
            policy["run_id"] == run_id and policy["run_spec_sha256"] == run_spec_sha256, "Launch run/spec mismatch"
        )
        before, after = _path(before_checkpoint), _path(after_checkpoint)
        _require(
            before.name == f"global_step_{step - 1}" and after.name == f"global_step_{step}",
            "Checkpoint steps mismatch",
        )
        expected_after = (
            _path(launch["environment"]["RUN_ROOT"]) / "rl-training" / "checkpoints" / f"global_step_{step}"
        )
        _require(after == expected_after, "After checkpoint does not belong to the launch run")
        _require(batch_audit["schema"] == "dsh.harbor-training-batch-audit.v1", "Batch audit schema mismatch")
        _require(batch_audit["passed"] is True and batch_audit["errors"] == [], "Batch audit did not pass")
        _require(batch_audit["launch_sha256"] == launch_sha256, "Batch audit launch digest mismatch")
        groups = [g for g in batch_audit["groups"] if g["partition_id"] == "train" and g["global_steps"] == step]
        _require(
            len(groups) == 1 and groups[0]["group_uid"] == group_uid, "Expected one matching consumed step/uid group"
        )
        group = groups[0]
        _require(
            type(group["global_steps"]) is int and group["status"] == "admitted-and-training-batch-matched",
            "Unconsumed group",
        )
        indexes = group["session_indexes"]
        _require(all(type(i) is int for i in indexes) and sorted(indexes) == list(range(4)), "Incomplete n=4 group")
        keys = group["transfer_queue_keys"]
        _require(sorted(keys) == [f"{group_uid}_{i}_0" for i in range(4)], "Expected four unique single-output TQ keys")
        _require(group["consumed_transfer_queue_keys"] == keys, "Group not fully consumed")
        rewards = group["rewards"]
        _require(len(rewards) == 4 and all(_finite(value) for value in rewards), "Reward evidence invalid")
        _require(min(rewards) < max(rewards), "Consumed group has no reward variance")
        rows = [row for row in metrics_rows if row.get("training/global_step") == step]
        _require(len(rows) == 1 and type(rows[0]["training/global_step"]) is int, "Missing/duplicate same-step metrics")
        metrics = rows[0]
        fields = (
            "critic/score/min",
            "critic/score/max",
            "critic/advantages/min",
            "critic/advantages/max",
            "actor/grad_norm",
            "actor/pg_loss",
        )
        _require(all(_finite(metrics.get(key)) for key in fields), "Required metrics missing/nonfinite")
        _require(
            metrics["critic/score/min"] == min(rewards) and metrics["critic/score/max"] == max(rewards),
            "Metrics scores differ from consumed group",
        )
        _require(
            metrics["critic/advantages/min"] < 0 < metrics["critic/advantages/max"],
            "Need both advantage signs in this step",
        )
        _require(metrics["actor/grad_norm"] > 0, "Need a nonzero gradient in this step")
        _model(model_delta, before, after)
        _optimizer(optimizer_delta, before, after, step)
        report.update(
            passed=True,
            effective_update_verified=True,
            identity=dict(
                run_id=run_id,
                run_spec_sha256=run_spec_sha256,
                step=step,
                group_uid=group_uid,
                launch_sha256=launch_sha256,
                transfer_queue_keys=list(keys),
            ),
            metrics={key: metrics[key] for key in fields},
            rewards=list(rewards),
            checkpoints=dict(
                model={key: model_delta[key] for key in ("before", "after")}, optimizer=optimizer_delta["files"]
            ),
        )
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError) as error:
        report["errors"].append(f"{type(error).__name__}: {error}")
    return report


def parse_console_metrics(text):
    """Extract VERL's console step rows, retaining duplicates so admission rejects them."""
    rows = []
    for line in text.splitlines():
        line = re.sub(r"\x1b\[[0-9;]*m", "", line)
        match = re.search(r"(?:^|\s)step:(\d+)\s+-\s+(.+)", line)
        if match is None:
            continue
        row = {}
        for pair in match[2].split(" - "):
            key, separator, value = pair.partition(":")
            if not separator:
                continue
            key, value = key.strip(), value.strip()
            _require(key not in row, "Duplicate metric key")
            try:
                row[key] = int(value) if re.fullmatch(r"[+-]?\d+", value) else float(value)
            except ValueError:
                continue
        step = int(match[1])
        _require(
            type(row.get("training/global_step")) is int and row["training/global_step"] == step,
            "Console and training metric steps differ",
        )
        rows.append(row)
    return rows


def _json_object(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, "Duplicate JSON key")
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError(f"Nonfinite JSON value: {value}")

    value = json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid_constant)
    _require(isinstance(value, dict), "Expected JSON object")
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("run-id", "run-spec-sha256", "group-uid", "before-checkpoint", "after-checkpoint"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--step", type=int, required=True)
    for name in ("launch", "batch-audit", "console-metrics", "model-delta", "optimizer-delta"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = vars(parser.parse_args())
    artifacts = {}
    try:
        for key in ("launch", "batch_audit", "console_metrics", "model_delta", "optimizer_delta"):
            path = args[key]
            _require(
                path.is_file() and not path.is_symlink() and path.stat().st_size <= 64 * 1024 * 1024,
                "Expected bounded regular input report/log",
            )
            raw = path.read_bytes()
            artifacts[key] = {"path": str(path.resolve()), "sha256": "sha256:" + hashlib.sha256(raw).hexdigest()}
            args[key] = parse_console_metrics(raw.decode()) if key == "console_metrics" else _json_object(raw)
        args["metrics_rows"] = args.pop("console_metrics")
        report = audit_effective_update(**args, launch_sha256=artifacts["launch"]["sha256"])
    except (OSError, ValueError, TypeError, UnicodeError) as error:
        report = dict(
            schema="dsh.effective-update-audit.v1",
            passed=False,
            effective_update_verified=False,
            resume_verified=False,
            restore_evidence={"status": "unknown"},
            errors=[f"{type(error).__name__}: {error}"],
        )
    report["input_artifacts"] = artifacts
    print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
