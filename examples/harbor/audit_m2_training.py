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


def audit_training(*, launch_path, agent_log_dir, rollout_data_dir, validation_data_dir, train_n, validation_n):
    """Report batch correspondence; optimizer verification remains a separate gate."""
    report = dict(
        schema="dsh.harbor-training-batch-audit.v1", passed=False, groups=[], errors=[], optimizer_update_verified=False
    )
    try:
        if any(type(n) is not int or n <= 0 for n in (train_n, validation_n)):
            raise ValueError("Expected rollout counts must be positive integers")
        raw_launch = _read(Path(launch_path))
        launch = _json(raw_launch)
        if launch["schema"] != "dsh.harbor-m2-launch.v1":
            raise ValueError("Unexpected launch schema")
        report["launch_sha256"] = "sha256:" + hashlib.sha256(raw_launch).hexdigest()
        kwargs = launch["postprocessor"]
        if "context" in kwargs:
            raise ValueError("Operator kwargs must not supply runtime context")
        counts = dict(train=train_n, val=validation_n)
        rows = dict(train=_rows(Path(rollout_data_dir)), val=_rows(Path(validation_data_dir)))
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
            context = RunnerContext.model_validate({field: meta[field] for field in RunnerContext.model_fields})
            partition = context.partition_id
            if partition not in counts or context.global_steps is None:
                raise ValueError("Only explicit train/val steps may be audited")
            if meta["session_id"] != context.gateway_session_id or context.gateway_session_id in seen_sessions:
                raise ValueError("Duplicate or mismatched Gateway session")
            seen_sessions.add(context.gateway_session_id)
            if context.group_size != counts[partition]:
                raise ValueError("Rollout count differs from operator count")
            key = (partition, context.global_steps, context.group_uid)
            group = groups.setdefault(
                key,
                dict(
                    partition_id=partition,
                    global_steps=context.global_steps,
                    group_uid=context.group_uid,
                    session_indexes=[],
                    rewards=[],
                    transfer_queue_keys=[],
                ),
            )
            group["session_indexes"].append(context.session_index)
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
                trajectory = _load_dump_trajectory(npz_bytes=raw_npz, trajectory_meta=entry, trajectory_index=index)
                validate_registered_trajectories((trajectory,), context=context.model_dump(), **kwargs)
                receipt = trajectory.extra_fields["dsh_reward_info"]["harbor_dsh"]["receipt_sha256"]
                if receipt in seen_receipts:
                    raise ValueError("Receipt reused across sessions")
                local_receipts.add(receipt)
                joined = (context.global_steps, tq_key)
                if joined in known[partition]:
                    raise ValueError("Duplicate admitted TransferQueue key")
                known[partition].add(joined)
                if rows[partition].get(joined) != [trajectory.reward_score]:
                    raise ValueError("Trainer row missing, duplicated, or reward mismatched")
                group["rewards"].append(trajectory.reward_score)
                group["transfer_queue_keys"].append(tq_key)
            seen_receipts.update(local_receipts)
        for key, group in sorted(groups.items()):
            if sorted(group["session_indexes"]) != list(range(counts[key[0]])):
                raise ValueError("Incomplete rollout group")
            group["status"] = "admitted-and-training-batch-matched" if key[0] == "train" else "admitted-and-evaluated"
            group["has_reward_variance"] = len(set(group["rewards"])) > 1
            report["groups"].append(group)
        if not any(group["partition_id"] == "train" for group in report["groups"]):
            raise ValueError("No training groups")
        for partition in counts:
            if set(rows[partition]) != known[partition]:
                raise ValueError(f"Unexpected trainer rows: {partition}")
        report["passed"] = True
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as error:
        report["errors"].append(f"{type(error).__name__}: {error}")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("launch-path", "agent-log-dir", "rollout-data-dir", "validation-data-dir"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("train-n", "validation-n"):
        parser.add_argument("--" + name, type=int, required=True)
    args = parser.parse_args()
    report = audit_training(**vars(args))
    print(json.dumps(report, sort_keys=True, indent=2, allow_nan=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
