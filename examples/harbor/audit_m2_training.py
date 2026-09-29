"""Revalidate Harbor evidence and match admitted groups to trainer batch dumps.

This does not attest optimizer steps, parameter changes, or token-level causality.
Run against the original private artifact and registration paths after training.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path

from examples.dsh.ops.audit_qwen3_4b_online_rl import _load_dump_trajectory
from uni_agent.framework.trajectory_identity import trajectory_tq_key
from uni_agent.tasks.harbor_dsh.registration import validate_registered_trajectories
from uni_agent.tasks.harbor_dsh.task import RunnerContext


def _pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate JSON key")
        value[key] = item
    return value


def _json(raw):
    def invalid(value):
        raise ValueError("Nonfinite JSON value")

    return json.loads(raw, object_pairs_hook=_pairs, parse_constant=invalid)


def _read(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Expected regular evidence file: {path}")
    return path.read_bytes()


def _rows(directory):
    if not directory.is_dir() or directory.is_symlink():
        raise ValueError(f"Trainer dump directory missing: {directory}")
    rows = defaultdict(list)
    for path in sorted(directory.rglob("*.jsonl")):
        for line in _read(path).splitlines():
            if not line.strip():
                continue
            row = _json(line)
            step, uid, score = row["step"], row["uid"], row["score"]
            if type(step) is not int or step < 0 or not isinstance(uid, str) or not uid:
                raise ValueError("Invalid trainer step or uid")
            if type(score) not in (int, float) or not math.isfinite(score):
                raise ValueError("Invalid trainer score")
            rows[step, uid].append(score)
    return rows


def _async_consumption(rows):
    """A TQ key identifies one actual trainer consumption, regardless of sampling step."""
    result = {}
    for (step, key), scores in rows.items():
        if key in result or len(scores) != 1:
            raise ValueError("TQ key consumed more than once")
        result[key] = (step, scores[0])
    return result


def _version_evidence(entry, key):
    names = ("min_global_steps", "max_global_steps", "generation_count", "versioned_generation_count")
    values = {name: entry[name] for name in names}
    if (
        any(type(value) is not int for value in values.values())
        or not 0 <= values["min_global_steps"] <= values["max_global_steps"]
        or values["generation_count"] <= 0
        or values["generation_count"] != values["versioned_generation_count"]
        or entry["version_evidence_complete"] is not True
    ):
        raise ValueError("Incomplete Gateway version evidence")
    return dict(transfer_queue_key=key, **values, version_evidence_complete=True)


def audit_training(
    *,
    launch_path,
    agent_log_dir,
    validation_data_dir=None,
    validation_n=None,
    rollout_data_dir=None,
    train_n=None,
    val_only=False,
    no_validation=False,
    async_training=False,
):
    """Report batch correspondence; optimizer verification remains a separate gate."""
    report = dict(
        schema="dsh.harbor-training-batch-audit.v2" if async_training is True else "dsh.harbor-training-batch-audit.v1",
        passed=False,
        groups=[],
        unconsumed_groups=[],
        unconsumed_trajectory_count=0,
        errors=[],
        optimizer_update_verified=False,
    )
    try:
        if type(val_only) is not bool or type(no_validation) is not bool:
            raise ValueError("val_only and no_validation must be booleans")
        if type(async_training) is not bool or (async_training and (not no_validation or val_only)):
            raise ValueError("async_training requires explicit training-only audit")
        if no_validation and (val_only or validation_data_dir is not None or validation_n is not None):
            raise ValueError("no_validation conflicts with validation options")
        counts = {} if no_validation else dict(val=validation_n)
        if not val_only:
            counts["train"] = train_n
        if any(type(n) is not int or n <= 0 for n in counts.values()):
            raise ValueError("Expected rollout counts must be positive integers")
        raw_launch = _read(Path(launch_path))
        launch = _json(raw_launch)
        if launch["schema"] != "dsh.harbor-m2-launch.v1":
            raise ValueError("Unexpected launch schema")
        report["launch_sha256"] = "sha256:" + hashlib.sha256(raw_launch).hexdigest()
        kwargs = launch["postprocessor"]
        if "context" in kwargs:
            raise ValueError("Operator kwargs must not supply runtime context")
        report["mode"] = (
            "training-only" if no_validation else "validation-only" if val_only else "training-and-validation"
        )
        rows = {} if no_validation else dict(val=_rows(Path(validation_data_dir)))
        if not val_only:
            rows["train"] = _rows(Path(rollout_data_dir))
        consumption = _async_consumption(rows["train"]) if async_training else {}
        seen_tq_keys = set()
        log_root = Path(agent_log_dir)
        if not log_root.is_dir() or log_root.is_symlink():
            raise ValueError("Agent log directory missing")
        groups = {}
        seen_sessions, seen_receipts = set(), set()
        known = dict(train=set(), val=set())
        for path in sorted(log_root.rglob("trajectory.json")):
            meta = _json(_read(path))
            if meta["schema"] != "uni-agent.trajectory-dump.v2":
                raise ValueError("Unsupported trajectory dump schema")
            if val_only and meta.get("partition_id") == "train":
                continue
            context = RunnerContext.model_validate({field: meta[field] for field in RunnerContext.model_fields})
            partition = context.partition_id
            if partition not in counts or context.global_steps is None:
                raise ValueError("Only explicit train/val steps may be audited")
            if meta["session_id"] != context.gateway_session_id or context.gateway_session_id in seen_sessions:
                raise ValueError("Duplicate or mismatched Gateway session")
            seen_sessions.add(context.gateway_session_id)
            if context.group_size != counts[partition]:
                raise ValueError("Rollout count differs from operator count")
            if context.session_index >= context.group_size:
                raise ValueError("Rollout session index exceeds group size")
            key = (partition, context.global_steps, context.group_uid)
            group = groups.setdefault(
                key,
                dict(
                    partition_id=partition,
                    global_steps=context.global_steps,
                    group_uid=context.group_uid,
                    session_indexes=[],
                    rewards=[],
                    termination_kinds=[],
                    transfer_queue_keys=[],
                    consumed_transfer_queue_keys=[],
                ),
            )
            group["session_indexes"].append(context.session_index)
            if async_training:
                group.setdefault("generation_global_steps", context.global_steps)
                group.setdefault("training_global_steps", None)
                group.setdefault("consumed_rows", [])
                group.setdefault("version_evidence", [])
            raw_npz = _read(path.parent / "trajectory.npz")
            if meta["trajectory_npz_sha256"] != "sha256:" + hashlib.sha256(raw_npz).hexdigest():
                raise ValueError("Trajectory NPZ digest mismatch")
            entries = meta["trajectories"]
            if not entries or type(meta["num_trajectories"]) is not int or meta["num_trajectories"] != len(entries):
                raise ValueError("Trajectory count mismatch")
            local_receipts = set()
            for index, entry in enumerate(entries):
                tq_key = trajectory_tq_key(context.group_uid, context.session_index, index)
                if entry["transfer_queue_key"] != tq_key or entry["trajectory_index"] != index:
                    raise ValueError("TransferQueue key mismatch")
                if async_training:
                    if tq_key in seen_tq_keys:
                        raise ValueError("Duplicate global TransferQueue key")
                    seen_tq_keys.add(tq_key)
                    group["version_evidence"].append(_version_evidence(entry, tq_key))
                trajectory = _load_dump_trajectory(npz_bytes=raw_npz, trajectory_meta=entry, trajectory_index=index)
                validate_registered_trajectories((trajectory,), context=context.model_dump(), **kwargs)
                if kwargs.get("termination_policy") == "budget-terminal-v1":
                    from uni_agent.tasks.harbor_dsh.budget_admission import bind_budget_dump

                    bind_budget_dump(
                        [trajectory],
                        context=context.model_dump(),
                        metadata=meta,
                        npz_sha256=meta["trajectory_npz_sha256"],
                        artifact_root=kwargs["artifact_root"],
                        online=False,
                    )
                receipt = trajectory.extra_fields["dsh_reward_info"]["harbor_dsh"]["receipt_sha256"]
                if receipt in seen_receipts:
                    raise ValueError("Receipt reused across sessions")
                local_receipts.add(receipt)
                consumed_step = consumption.get(tq_key, (None, None))[0] if async_training else context.global_steps
                if async_training and consumed_step is not None and consumed_step < context.global_steps:
                    raise ValueError("Trainer consumption precedes generation")
                if async_training and consumed_step is not None and entry["max_global_steps"] >= consumed_step:
                    raise ValueError("Consumed trajectory claims a future policy version")
                joined = (consumed_step, tq_key)
                if joined in known[partition]:
                    raise ValueError("Duplicate admitted TransferQueue key")
                known[partition].add(joined)
                if joined in rows[partition]:
                    if rows[partition][joined] != [trajectory.reward_score]:
                        raise ValueError("Trainer row duplicated or reward mismatched")
                    group["consumed_transfer_queue_keys"].append(tq_key)
                    if async_training:
                        group["consumed_rows"].append(
                            dict(
                                transfer_queue_key=tq_key,
                                training_global_steps=consumed_step,
                                reward=trajectory.reward_score,
                            )
                        )
                group["termination_kinds"].append(
                    (trajectory.extra_fields.get("budget_admission") or {}).get(
                        "termination_kind", "completed" if trajectory.finished is True else "unfinished"
                    )
                )
                group["rewards"].append(trajectory.reward_score)
                group["transfer_queue_keys"].append(tq_key)
            seen_receipts.update(local_receipts)
        for key, group in sorted(groups.items()):
            if not group["consumed_transfer_queue_keys"]:
                if len(set(group["session_indexes"])) != len(group["session_indexes"]):
                    raise ValueError("Duplicate rollout session index")
                group["status"] = "admitted-not-consumed"
                group["complete"] = sorted(group["session_indexes"]) == list(range(counts[key[0]]))
                report["unconsumed_groups"].append(group)
                report["unconsumed_trajectory_count"] += len(group["transfer_queue_keys"])
                continue
            if sorted(group["session_indexes"]) != list(range(counts[key[0]])):
                raise ValueError("Incomplete rollout group")
            if group["consumed_transfer_queue_keys"] != group["transfer_queue_keys"]:
                raise ValueError("Partially consumed rollout group")
            if async_training:
                steps = {row["training_global_steps"] for row in group["consumed_rows"]}
                if len(steps) != 1:
                    raise ValueError("Rollout group consumed across different training steps")
                group["training_global_steps"] = steps.pop()
            group["status"] = "admitted-and-training-batch-matched" if key[0] == "train" else "admitted-and-evaluated"
            group["has_reward_variance"] = len(set(group["rewards"])) > 1
            report["groups"].append(group)
        required_partition = "val" if val_only else "train"
        if not any(group["partition_id"] == required_partition for group in report["groups"]):
            raise ValueError("No " + required_partition + " groups")
        for partition in counts:
            if not set(rows[partition]).issubset(known[partition]):
                raise ValueError(f"Unexpected trainer rows: {partition}")
        report["passed"] = True
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as error:
        report["errors"].append(f"{type(error).__name__}: {error}")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("launch-path", "agent-log-dir"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--validation-data-dir", type=Path)
    parser.add_argument("--rollout-data-dir", type=Path)
    parser.add_argument("--train-n", type=int)
    parser.add_argument("--validation-n", type=int)
    parser.add_argument("--val-only", action="store_true")
    parser.add_argument("--no-validation", action="store_true", help="Audit training with validation disabled")
    parser.add_argument(
        "--async-training", action="store_true", help="Join unique TQ keys to actual consumption steps (v2)"
    )
    args = parser.parse_args()
    report = audit_training(**vars(args))
    print(json.dumps(report, sort_keys=True, indent=2, allow_nan=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
