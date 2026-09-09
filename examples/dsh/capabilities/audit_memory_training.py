"""Independently join native memory stage evidence to pinned VERL's consumed rows.

Run only on trusted artifacts from this project's own runs. This is a read-only
consumer, not a TQ client, optimizer audit, or security sandbox.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from pathlib import Path

from examples.dsh.capabilities.memory_verifier import canonical, read_regular, sha
from examples.dsh.ops.audit_qwen3_4b_online_rl import _load_dump_trajectory
from uni_agent.framework.memory_chain import audit_memory_chain_crosswalk
from uni_agent.tasks.dsh.trajectory_audit import validate_trajectory


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _constant(value):
    raise ValueError(f"Nonfinite JSON constant: {value}")


def _json(path):
    value = json.loads(read_regular(path, 8_000_000), parse_constant=_constant)
    _require(isinstance(value, dict), "Expected JSON object")
    return value


def _validate_task_course(task, run_root):
    course = task.get("course_id", "work-state-v1")
    expected = "work-state-short-fact-v1" if task["family"] == "WS07" else "work-state-v1"
    _require(course == expected, "Work-state task course mismatch")
    plan_path = Path(run_root) / "memory-launch-plan.json"
    if not plan_path.exists() and course == "work-state-v1":
        return  # Historical CPU fixtures predate the optional course identity.
    plan = _json(plan_path)
    _require(plan.get("course_id", "work-state-v1") == course, "Work-state run/task course mismatch")
    if plan.get("checkpoint_origin"):
        _require(
            plan["checkpoint_origin"].get("course_id", "work-state-v1") == course, "Work-state mother course mismatch"
        )
    if course == "work-state-short-fact-v1":
        run = _json(Path(run_root) / "run-manifest.json")
        raw = read_regular(run["paths"]["dataset_manifest"])
        _require(
            sha(raw) == run["sha256"]["dataset_manifest"] and json.loads(raw) == plan,
            "Work-state course plan binding mismatch",
        )


def _work_state_lineage(record, item, result_root):
    # Lazy import keeps old runs independent of optional work-state implementation.
    from examples.dsh.capabilities.work_state import verifier
    from examples.dsh.capabilities.work_state.bundle import pack_bundle
    from examples.dsh.capabilities.work_state.tasks import make_task

    receipt_path = Path(item["stage_receipt_path"])
    receipt = _json(receipt_path)
    envelope = _json(receipt_path.with_name("agent-result.json"))
    metadata = envelope["metadata"]
    fixture_path = result_root.parent.parent / "fixture.json"
    _require(metadata["fixture_path"] == str(fixture_path), "Work-state fixture location mismatch")
    raw = read_regular(fixture_path)
    _require(sha(raw) == metadata["fixture_sha256"], "Work-state fixture hash changed")
    fixture = _json(fixture_path)
    role = "writer" if item["role"] == "A" else "reader"
    _require(
        fixture["schema"] == "dsh.work-state-stage.v1"
        and fixture["contract_id"] == metadata["contract_id"] == "work-state-v1"
        and fixture["role"] == role
        and fixture["chain_id"] == item["chain_id"],
        "Work-state fixture contract/role/chain mismatch",
    )
    chains = [_json(ref["receipt_path"]) for ref in record["chains"]]
    chain = next(c for c in chains if c["chain_id"] == item["chain_id"])
    expected_binding = dict(
        schema="dsh.memory-training-stage.v1",
        split="train" if record["partition"] == "train" else "validation",
        run_id=record["run_id"],
        group_uid=record["uid"],
        sibling=chain["sibling"],
        checkpoint_identity=chain["checkpoint_identity"],
    )
    _require(
        fixture["training_stage"] == metadata["training_stage"] == expected_binding,
        "Work-state stage training identity mismatch",
    )
    _require(
        metadata["task_id"] == f"dsh/work-state/{item['chain_id']}/{role}"
        and metadata["task_version"] == "1"
        and metadata["split"] == expected_binding["split"],
        "Work-state task identity mismatch",
    )
    task = fixture["task"]
    _validate_task_course(task, fixture_path.parents[3])
    _require(task == make_task(task["family"], task["variant"], task["seed"]), "Work-state task definition changed")
    _require(
        sha(canonical(task)) == fixture["source_version"] == chain["frozen"]["source_version"],
        "Work-state task source digest mismatch",
    )
    _require(
        metadata["verifier_id"] == receipt["verifier"]["id"] == verifier.VERIFIER_ID
        and metadata["verifier_version"] == receipt["verifier"]["version"] == verifier.VERIFIER_VERSION
        and metadata["verifier_code_digest"] == receipt["verifier"]["code_digest"] == verifier.bundle_digest(),
        "Work-state verifier version/bundle mismatch",
    )
    _require(envelope["prompt"] == _read_prompt(fixture_path.with_name("prompt.json")), "Work-state prompt changed")
    if role == "reader":
        binding = fixture["writer_binding"]
        writer_items = [i for i in record["items"] if i["chain_id"] == item["chain_id"] and i["role"] == "A"]
        writer_receipt = _json(writer_items[0]["stage_receipt_path"])
        _require(
            binding
            == dict(
                dsh_session_id=writer_receipt["dsh_session_id"],
                gateway_session_id=writer_items[0]["gateway_session_id"],
                receipt_id=writer_receipt["receipt_id"],
                trace_sha256=writer_receipt["trace_sha256"],
                manifest_sha256=chain["frozen"]["manifest_sha256"],
                content_sha256=chain["frozen"]["content_sha256"],
            ),
            "Work-state reader parent binding mismatch",
        )
        _require(
            str(Path(fixture["frozen_dir"]) / "manifest.json") == chain["frozen_manifest_path"]
            and str(Path(fixture["frozen_dir"]) / "memory.bin") == chain["frozen_content_path"],
            "Work-state frozen location mismatch",
        )
    else:
        # Original A files must still equal the actual frozen bytes, including missing entries.
        _require(
            pack_bundle(Path(fixture["memory_root"]), task["memory_paths"], fixture["max_bytes"])
            == read_regular(chain["frozen_content_path"]),
            "Work-state writer/frozen bytes changed",
        )
    trace = result_root.parent / "traces" / hashlib.sha256(item["gateway_session_id"].encode()).hexdigest()[:24]
    events = [
        json.loads(line, parse_constant=_constant)
        for line in read_regular(trace / "session.jsonl", 8_000_000).splitlines()
        if line
    ]
    scored = verifier.score(fixture, events, envelope["response"], envelope["finished"], receipt["dsh_session_id"])
    _require(
        all(scored[k] == receipt[k] for k in ("reward", "finished", "eligible", "accuracy"))
        and scored["eligible"] is True,
        "Work-state independent score mismatch",
    )
    if role == "reader":
        snapshot = scored["extra_info"]["output_snapshot_sha256"]
        _require(
            receipt["evidence"]
            == [
                metadata["fixture_sha256"],
                receipt["trace_sha256"],
                sha(canonical(expected_binding)),
                fixture["writer_binding"]["receipt_id"],
                fixture["writer_binding"]["manifest_sha256"],
                snapshot,
            ],
            "Work-state output snapshot changed or missing",
        )


def _read_prompt(path):
    return json.loads(read_regular(path), parse_constant=_constant)


def _stage_lineage(record):
    """Recheck original trace/result bytes, beyond crosswalk's NPZ/receipt hashes."""
    contract = record.get("contract_id", "legacy-memory-v1")
    _require(contract in ("legacy-memory-v1", "work-state-v1"), "Unknown stage contract")
    for item in record["items"]:
        meta = _json(item["stage_json_path"])
        own = [i for i in record["items"] if i["gateway_session_id"] == item["gateway_session_id"]]
        _require(
            meta["num_trajectories"] == len(meta["trajectories"]) == len(own)
            and [i["stage_index"] for i in own] == list(range(len(own))),
            "Stage contexts are not completely covered",
        )
        _require(
            meta["partition_id"] == record["partition"]
            and meta["global_steps"] == record["global_steps"]
            and meta["group_uid"] == record["uid"]
            and meta["group_size"] == (4 if record["partition"] == "train" else 1)
            and meta["session_index"] == int(item["tq_key"].rsplit("_", 2)[1]),
            "Stage group/partition/trainer step mismatch",
        )
        trajectory = _load_dump_trajectory(
            npz_bytes=read_regular(item["stage_npz_path"], 64_000_000),
            trajectory_meta=meta["trajectories"][item["stage_index"]],
            trajectory_index=item["stage_index"],
        )
        result_root = Path(item["stage_receipt_path"]).parents[1]
        _require(result_root.name == "results", "Expected StageSpec results layout")
        validate_trajectory(
            trajectory,
            partition_id=record["partition"],
            gateway_session_id=item["gateway_session_id"],
            trace_root=str(result_root.parent / "traces"),
            result_root=str(result_root),
        )
        if contract == "work-state-v1":
            _work_state_lineage(record, item, result_root)


def _rows(run_root):
    rows, errors, inputs = [], [], []
    for partition, directory in (("train", "rollouts"), ("val", "validation")):
        for file in sorted((run_root / directory).rglob("*.jsonl")):
            try:
                raw = read_regular(file, 64_000_000)
                inputs.append(dict(path=str(file), sha256=sha(raw)))
                for number, line in enumerate(raw.decode().splitlines(), 1):
                    if not line.strip():
                        continue
                    row = json.loads(line, parse_constant=_constant)
                    _require(isinstance(row, dict), f"Invalid row {number}")
                    uid, step, score = row.get("uid"), row.get("step"), row.get("score")
                    _require(isinstance(uid, str) and uid, f"Invalid uid at row {number}")
                    _require(type(step) is int and step >= 0, f"Invalid step at row {number}")
                    _require(type(score) in (int, float) and math.isfinite(score), f"Invalid score at row {number}")
                    rows.append(dict(partition=partition, step=step, uid=uid, score=score))
            except (OSError, ValueError, TypeError) as error:
                errors.append(f"{file}: {error}")
    return rows, errors, inputs


def audit_memory_training(run_root: Path, *, memory_root: Path, expected_run_id: str) -> dict:
    run_root, memory_root = Path(run_root), Path(memory_root)
    _require(isinstance(expected_run_id, str) and expected_run_id, "Explicit run identity required")
    rows, errors, inputs = _rows(run_root)
    counts = Counter((r["partition"], r["step"], r["uid"]) for r in rows)
    row_by_key = {(r["partition"], r["step"], r["uid"]): r for r in rows}
    groups, declared, admitted, scopes = [], Counter(), set(), set()
    for path in sorted((memory_root / "groups").glob("*/crosswalk.json")):
        group = dict(
            path=str(path),
            status="rejected",
            crosswalk_consumption_verified=False,
            submission_verified=False,
            consumption_verified=False,
            reasons=[],
            missing_keys=[],
        )
        groups.append(group)
        try:
            record = _json(path)
            scope = (record["partition"], record["global_steps"], record["uid"])
            group.update(
                expected_policy_version=record["expected_policy_version"],
                partition=scope[0],
                global_steps=scope[1],
                uid=scope[2],
                crosswalk_sha256=sha(read_regular(path)),
            )
            keys = [(scope[0], scope[1], item["tq_key"]) for item in record["items"]]
            declared.update(keys)
            _require(scope not in scopes, "Duplicate group identity")
            scopes.add(scope)
            _require(record["run_id"] == expected_run_id, "Run identity mismatch")
            checked = audit_memory_chain_crosswalk(path)
            _require(checked["consumption_verified"] is False, "Crosswalk cannot certify consumption")
            _stage_lineage(record)
            group["stage_evidence_verified"] = True
            submission_path = path.with_name("submission.json")
            if not submission_path.exists():
                group["status"] = "prepared-unsubmitted"
                group["reasons"].append("missing_submission")
                continue
            submission = _json(submission_path)
            _require(
                submission["status"] == "tq-write-returned-not-consumed"
                and submission["crosswalk_sha256"] == group["crosswalk_sha256"]
                and submission["keys"] == checked["keys"],
                "Submission does not bind crosswalk and complete keys",
            )
            group["submission_verified"] = True
            group["status"] = "submitted-unconsumed"
            admitted.update(keys)
            missing = [key[2] for key in keys if counts[key] == 0]
            duplicate = [key[2] for key in keys if counts[key] > 1]
            mismatched = [
                key[2]
                for key, item in zip(keys, record["items"], strict=True)
                if key in row_by_key
                and not math.isclose(row_by_key[key]["score"], item["stage_reward"], rel_tol=1e-6, abs_tol=1e-7)
            ]
            group.update(missing_keys=missing, duplicate_keys=duplicate, score_mismatch_keys=mismatched)
            if missing:
                group["reasons"].append("missing_consumed_keys")
            if duplicate:
                group["reasons"].append("duplicate_consumption")
            if mismatched:
                group["reasons"].append("stage_score_mismatch")
            if not group["reasons"]:
                group.update(status="consumed", consumption_verified=True)
        except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
            group["reasons"].append(f"{type(error).__name__}: {error}")
    unknown = [dict(partition=k[0], step=k[1], uid=k[2]) for k in counts if k not in admitted]
    duplicates = [dict(partition=k[0], step=k[1], uid=k[2], count=n) for k, n in counts.items() if n > 1]
    overlapping = [dict(partition=k[0], step=k[1], uid=k[2]) for k, n in declared.items() if n > 1]
    completed, manifest_hash = False, None
    try:
        manifest = _json(run_root / "run-manifest.json")
        completed = manifest.get("status") == "completed"
        manifest_hash = sha(read_regular(run_root / "run-manifest.json"))
    except (OSError, ValueError, TypeError) as error:
        errors.append(f"run manifest: {error}")
    verified = (
        bool(groups)
        and all(g["consumption_verified"] for g in groups)
        and not (unknown or duplicates or overlapping or errors)
    )
    return dict(
        schema="dsh.memory-training-consumption-audit.v1",
        passed=verified and completed,
        consumption_verified=verified,
        run_completed=completed,
        run_id=expected_run_id,
        run_manifest_sha256=manifest_hash,
        inputs=inputs,
        groups=groups,
        errors=errors,
        unknown_or_unadmitted_consumption=unknown,
        duplicate_consumption=duplicates,
        overlapping_crosswalk_keys=overlapping,
        summary=dict(
            groups=len(groups),
            consumed_groups=sum(g["consumption_verified"] for g in groups),
            consumed_rows=len(rows),
            unique_consumed_rows=len(counts),
        ),
        limitations=[
            "Trainer JSONL proves observed TQ batch consumption, not optimizer update or ability gains.",
            "Crosswalk and submission records alone never establish trainer consumption.",
        ],
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_root", type=Path)
    parser.add_argument("--memory-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit_memory_training(args.run_root, memory_root=args.memory_root, expected_run_id=args.run_id)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps(dict(passed=report["passed"], summary=report["summary"])))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
