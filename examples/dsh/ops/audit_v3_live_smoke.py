"""Audit eight inference episodes from persisted artifacts, without model calls.

This validates consistency and the existing verifier contract. It does not prove
containment against code running as the evidence writer's Unix user, or qualify
data for training. Synthetic test artifacts are not live execution evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

import numpy as np

from examples.dsh.evolution_v3_catalog import FAMILY_IDS
from examples.dsh.evolution_v3_live import load_live_scenarios
from examples.dsh.evolution_v3_live_verifier import evaluate_live_trace
from examples.dsh.ops.audit_qwen3_4b_online_rl import _audit_dump
from examples.dsh.ops.run_v3_live_smoke import _json_object, load_prepared_run


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def _file(root: Path, path: Path) -> Path:
    _require(path.is_relative_to(root), "artifact_outside_root")
    _require(not any(p.is_symlink() for p in (path, *path.parents) if p.is_relative_to(root)), "artifact_symlink")
    _require(path.is_file(), "artifact_missing")
    return path


def _record(root: Path, path: Path) -> dict[str, Any]:
    return _json_object(_file(root, path).read_bytes())


def _time(value: object) -> datetime:
    _require(isinstance(value, str), "timestamp_missing")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    _require(result.tzinfo is not None and result.utcoffset().total_seconds() == 0, "timestamp_not_utc")
    return result


def _token_arrays(path: Path, count: int) -> None:
    """Preserve dtype/shape checks before the existing loader converts to lists."""
    try:
        with np.load(path, allow_pickle=False) as arrays:
            for index in range(count):
                for field in ("prompt_ids", "response_ids", "response_mask", "response_logprobs"):
                    array = arrays[f"traj{index}_{field}"]
                    _require(array.ndim == 1, "token_array_not_vector")
                    if field.endswith("_ids"):
                        _require(
                            array.dtype.kind in "iu" and bool(np.all(array >= 0)), "token_ids_not_unsigned_integers"
                        )
                    elif field == "response_mask":
                        _require(
                            array.dtype.kind in "biu" and bool(np.all((array == 0) | (array == 1))),
                            "token_mask_invalid",
                        )
                    else:
                        _require(array.dtype.kind == "f" and bool(np.all(np.isfinite(array))), "token_logprobs_invalid")
    except (zipfile.BadZipFile, EOFError, KeyError) as exc:
        raise ValueError("token_archive_unreadable") from exc


def _evidence(root: Path, manifest: dict[str, Any]) -> tuple[dict[str, Any], datetime, datetime]:
    value = _record(root, Path(manifest["paths"]["inference_evidence_path"]))
    _require(manifest.get("status") == "completed", "run_not_completed")
    _require(value.get("schema") == "dsh.inference-evidence.v1", "inference_schema_invalid")
    _require(value.get("status") == "completed", "inference_not_completed")
    _require(value.get("partition_id") == "val" and value.get("global_steps") is None, "inference_partition_invalid")
    start, end = _time(value.get("started_at")), _time(value.get("finished_at"))
    _require(
        _time(manifest.get("started_at")) <= start <= end <= _time(manifest.get("finished_at")), "run_window_invalid"
    )
    samples = value.get("samples")
    _require(isinstance(samples, list) and len(samples) == len(FAMILY_IDS), "inference_sample_count")
    uids = set()
    for expected, sample in zip(manifest["samples"], samples, strict=True):
        _require(isinstance(sample, dict), "inference_sample_invalid")
        _require(
            type(sample.get("sample_index")) is int and sample["sample_index"] == expected["sample_index"],
            "sample_index_mismatch",
        )
        _require(sample.get("metadata") == expected["metadata"], "sample_metadata_mismatch")
        uid = sample.get("uid")
        _require(isinstance(uid, str) and str(UUID(uid)) == uid and uid not in uids, "sample_uid_invalid_or_reused")
        uids.add(uid)
    return value, start, end


def _episode(
    root: Path,
    manifest: dict[str, Any],
    sample: dict[str, Any],
    scenario: dict[str, Any],
    dump_path: Path,
    start: datetime,
    end: datetime,
    repository_root: Path,
) -> dict[str, Any]:
    paths = {key: Path(value) for key, value in manifest["paths"].items()}
    meta = _record(root, dump_path)
    gateway = meta.get("gateway_session_id")
    _require(
        isinstance(gateway, str)
        and re.fullmatch(rf"session-sample-{sample['sample_index']}-rollout-0-[0-9a-f]{{32}}", gateway) is not None,
        "gateway_identity_invalid",
    )
    _require(dump_path == paths["agent_log_dir"] / gateway / "trajectory.json", "dump_location_mismatch")
    # Recheck earlier episodes too: a later same-UID process could otherwise
    # leave changes after that episode's own completion check.
    inventory = json.loads(_file(root, Path(manifest["episode_files_path"])).read_bytes())
    for entry in inventory:
        copied = _file(root, root / "artifacts/workspaces" / gateway / entry["path"])
        _require(
            "sha256:" + hashlib.sha256(copied.read_bytes()).hexdigest() == entry["sha256"],
            "episode_trusted_file_digest_mismatch",
        )
    _require(meta.get("schema") == "uni-agent.trajectory-dump.v2", "dump_schema_invalid")
    _require(meta.get("session_id") == gateway and meta.get("group_uid") == sample["uid"], "dump_identity_mismatch")
    _require(
        type(meta.get("sample_index")) is int and meta["sample_index"] == sample["sample_index"], "dump_sample_mismatch"
    )
    _require(
        type(meta.get("session_index")) is int
        and meta["session_index"] == 0
        and type(meta.get("group_size")) is int
        and meta["group_size"] == 1,
        "dump_rollout_mismatch",
    )
    _require(meta.get("partition_id") == "val" and meta.get("global_steps") is None, "dump_partition_invalid")
    trajectories = meta.get("trajectories")
    _require(isinstance(trajectories, list) and bool(trajectories), "dump_trajectories_missing")
    _require(all(t.get("finished") is True for t in trajectories), "dump_unfinished_chain")
    trace_path = paths["trace_root"] / hashlib.sha256(gateway.encode()).hexdigest()[:24] / "session.jsonl"
    trace_bytes = _file(root, trace_path).read_bytes()
    events = [_json_object(line) for line in trace_bytes.splitlines()]
    lineage = trajectories[-1]["reward_info"]["dsh"]
    _require(isinstance(lineage.get("dsh_session_id"), str) and bool(lineage["dsh_session_id"]), "dsh_session_missing")
    trace_digest = "sha256:" + hashlib.sha256(trace_bytes).hexdigest()
    _require(lineage.get("trace_sha256") == trace_digest, "episode_trace_digest_mismatch")
    result_dir = (
        paths["result_root"] / hashlib.sha256(f"{lineage['dsh_session_id']}\0{trace_digest}".encode()).hexdigest()[:24]
    )
    envelope = _record(root, result_dir / "agent-result.json")
    receipt = _record(root, result_dir / "verifier-receipt.json")
    _require(envelope.get("metadata") == sample["metadata"], "envelope_metadata_mismatch")
    _require(envelope.get("dsh", {}).get("gateway_session_id") == gateway, "envelope_gateway_mismatch")
    _require(receipt.get("issuer") == {"kind": "trusted-verifier", "id": "uni-agent-dsh"}, "receipt_issuer_invalid")
    _require(start <= _time(receipt.get("issued_at")) <= end, "receipt_outside_run_window")
    # Every chain in the episode must project the same final receipt. This also
    # ensures the legacy validator reads only the already checked artifact paths.
    _require(all(t["reward_info"]["dsh"] == lineage for t in trajectories), "episode_lineage_mismatch")
    _token_arrays(_file(root, dump_path.with_name("trajectory.npz")), len(trajectories))
    reasons, keys, rewards, receipts = _audit_dump(
        dump_path=dump_path, meta=meta, trace_root=paths["trace_root"], result_root=paths["result_root"]
    )
    _require(not reasons, "trajectory_audit:" + ";".join(reasons))
    _require(len(rewards) == len(trajectories) and len(set(receipts)) == 1, "episode_receipt_mismatch")
    fixture = _file(repository_root, repository_root / sample["metadata"]["fixture_path"]).read_bytes()
    evaluation = evaluate_live_trace(
        scenario,
        events=events,
        response=envelope.get("response"),
        environment_digest=manifest["runtime"]["environment_digest"],
        fixture_bytes=fixture,
        trace_sha256=trace_digest,
    )
    _require(evaluation["eligible"] is True, "verifier_recomputed_ineligible")
    _require(
        receipt.get("reward") == evaluation["reward"] and receipt.get("accuracy") == float(evaluation["passed"]),
        "verifier_recomputed_reward_mismatch",
    )
    return {
        "gateway_session_id": gateway,
        "dsh_session_id": lineage["dsh_session_id"],
        "receipt_id": receipts[0],
        "transfer_queue_keys": keys,
        "final_key": keys[-1],
        "reward": rewards[-1],
        "passed": evaluation["passed"],
        "observation": evaluation["observation"],
        "verifier_reasons": evaluation["reasons"],
    }


def _readback(value: dict[str, Any], families: list[dict[str, Any]]) -> None:
    read = value.get("readback")
    _require(isinstance(read, dict), "inference_readback_missing")
    expected_keys = {family["final_key"]: family["reward"] for family in families}
    keys, scores = read.get("final_keys"), read.get("scores")
    _require(
        isinstance(keys, list) and isinstance(scores, list) and len(keys) == len(scores) == len(families),
        "readback_count_mismatch",
    )
    _require(
        all(isinstance(key, str) for key in keys) and len(set(keys)) == len(keys), "readback_key_invalid_or_duplicate"
    )
    _require(all(type(score) in (int, float) and math.isfinite(score) for score in scores), "readback_score_invalid")
    _require(dict(zip(keys, scores, strict=True)) == expected_keys, "readback_scores_or_keys_mismatch")
    traj_keys = read.get("traj_keys")
    _require(
        isinstance(traj_keys, list) and all(isinstance(key, str) for key in traj_keys),
        "readback_trajectory_keys_invalid",
    )
    _require(
        len(set(traj_keys)) == len(traj_keys)
        and set(traj_keys) == {key for family in families for key in family["transfer_queue_keys"]},
        "readback_trajectory_keys_mismatch",
    )
    _require(
        read.get("uid_status") == {sample["uid"]: "finished" for sample in value["samples"]},
        "readback_uid_status_mismatch",
    )


def audit_run(run_root: Path, *, repository_root: Path) -> dict[str, Any]:
    """Recompute a fail-closed report; never promote the source blocked bundle."""
    report: dict[str, Any] = {
        "schema": "dsh.evolution.live-smoke-report.v1",
        "audited_at": datetime.now(timezone.utc).isoformat(),
        "process_evidence_complete": False,
        "inference_readback_verified": False,
        "live_contract_passed": False,
        "training_eligible": False,
        "errors": [],
        "families": [{"family_id": family, "passed": False, "errors": []} for family in FAMILY_IDS],
    }
    try:
        manifest = load_prepared_run(run_root, repository_root=repository_root)
        root, repository_root = run_root.resolve(), repository_root.resolve()
        report["release_id"] = manifest["bundle"]["release_id"]
        evidence, start, end = _evidence(root, manifest)
        bundle = _record(Path(manifest["bundle"]["path"]), Path(manifest["bundle"]["path"]) / "manifest.json")
        scenario_path = _file(repository_root, repository_root / bundle["scenario_source"]["path"])
        scenarios = load_live_scenarios(scenario_path, repository_root=repository_root)
        scenario_by_id = {scenario["scenario_id"]: scenario for scenario in scenarios}
        dumps: dict[str, list[Path]] = {}
        registered = {sample["uid"] for sample in evidence["samples"]}
        for path in sorted(Path(manifest["paths"]["agent_log_dir"]).rglob("trajectory.json")):
            uid = _record(root, path).get("group_uid")
            _require(isinstance(uid, str) and uid in registered, "dump_uid_unregistered")
            dumps.setdefault(uid, []).append(path)
        for family, sample in zip(report["families"], evidence["samples"], strict=True):
            try:
                matches = dumps.get(sample["uid"], [])
                _require(len(matches) == 1, "episode_dump_missing_or_duplicate")
                family.update(
                    _episode(
                        root,
                        manifest,
                        sample,
                        scenario_by_id[sample["metadata"]["scenario_id"]],
                        matches[0],
                        start,
                        end,
                        repository_root,
                    )
                )
            except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError) as exc:
                family["errors"].append(f"{type(exc).__name__}:{exc}")
        complete = not any(family["errors"] for family in report["families"])
        if complete:
            for key in ("gateway_session_id", "dsh_session_id", "receipt_id"):
                _require(len({family[key] for family in report["families"]}) == len(FAMILY_IDS), f"reused_{key}")
            report["process_evidence_complete"] = True
            _readback(evidence, report["families"])
            report["inference_readback_verified"] = True
            report["live_contract_passed"] = all(family["passed"] for family in report["families"])
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError) as exc:
        report["errors"].append(f"{type(exc).__name__}:{exc}")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_root", type=Path)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    report = audit_run(args.run_root, repository_root=args.repository_root)
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    if report["live_contract_passed"]:
        raise SystemExit(0)
    raise SystemExit(1 if report["process_evidence_complete"] and report["inference_readback_verified"] else 2)


if __name__ == "__main__":
    main()
