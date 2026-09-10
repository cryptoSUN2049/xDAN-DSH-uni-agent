"""Controller-only diagnostic evidence audit; never authorizes training consumption.

Unlike training admission, a verified negative receipt is a useful observation.
Original booleans and artifacts are always preserved and rescored without coercion.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING, Any

from examples.dsh.capabilities.memory_chain import runtime_digest
from examples.dsh.capabilities.memory_training_stage import StageSpec, _binding
from examples.dsh.capabilities.memory_verifier import canonical, loads, read_regular, sha
from examples.dsh.capabilities.work_state import verifier
from uni_agent.tasks.base import build_reward_info
from uni_agent.tasks.dsh.trajectory_audit import (
    TrajectoryAuditError,
    _canonical_json_bytes,
    _digest,
    _load_json_object,
    _require_digest,
    _require_equal,
    _require_finite,
    _require_object,
    _require_string,
    _validate_partition,
    _validate_token_evidence,
    _validate_trace,
)

if TYPE_CHECKING:
    from uni_agent.framework.framework import GatewayStageExecution


def _validate_diagnostic_artifacts(
    *,
    reward_info: dict[str, Any],
    dsh: dict[str, Any],
    result_root: Path,
) -> None:
    reward = _require_finite(reward_info.get("reward"), field="reward_info.reward")
    verifier_reward = _require_finite(
        reward_info.get("verifier_reward"),
        field="reward_info.verifier_reward",
    )
    _require_equal(verifier_reward, reward, field="reward_info.verifier_reward")

    dsh_session_id = _require_string(dsh.get("dsh_session_id"), field="reward_info.dsh.dsh_session_id")
    rollout_id = _require_string(dsh.get("rollout_id"), field="reward_info.dsh.rollout_id")
    _require_equal(dsh_session_id, f"dsh-{rollout_id}", field="reward_info.dsh.dsh_session_id")
    trace_sha256 = _require_digest(dsh.get("trace_sha256"), field="reward_info.dsh.trace_sha256")
    artifact_sha256 = _require_digest(dsh.get("artifact_sha256"), field="reward_info.dsh.artifact_sha256")
    receipt_sha256 = _require_digest(dsh.get("receipt_sha256"), field="reward_info.dsh.receipt_sha256")
    environment_digest = _require_digest(
        dsh.get("environment_digest"),
        field="reward_info.dsh.environment_digest",
    )
    verifier_code_digest = _require_digest(
        dsh.get("verifier_code_digest"),
        field="reward_info.dsh.verifier_code_digest",
    )
    artifact_key = hashlib.sha256(f"{dsh_session_id}\0{trace_sha256}".encode()).hexdigest()[:24]
    result_dir = result_root / artifact_key

    envelope, envelope_bytes = _load_json_object(result_dir / "agent-result.json", field="DSH result envelope")
    if _digest(envelope_bytes) != artifact_sha256:
        raise TrajectoryAuditError("reward_info.dsh.artifact_sha256 does not match result envelope bytes")
    if envelope.get("schema") != "dsh.uni-agent.task-result.v1":
        raise TrajectoryAuditError("DSH result envelope has the wrong schema")
    if type(envelope.get("finished")) is not bool:
        raise TrajectoryAuditError("DSH result envelope finished must be boolean")
    envelope_dsh = _require_object(envelope.get("dsh"), field="DSH result envelope dsh")
    _require_equal(envelope_dsh.get("dsh_session_id"), dsh_session_id, field="result envelope dsh_session_id")
    _require_equal(envelope_dsh.get("trace_sha256"), trace_sha256, field="result envelope trace_sha256")
    metadata = _require_object(envelope.get("metadata"), field="DSH result envelope metadata")

    receipt, receipt_bytes = _load_json_object(
        result_dir / "verifier-receipt.json",
        field="DSH verifier receipt",
    )
    if receipt_bytes != _canonical_json_bytes(receipt):
        raise TrajectoryAuditError("DSH verifier receipt is not canonical JSON")
    if receipt.get("schema") != "dsh.verifier-receipt.v1" or dsh.get("schema") != receipt.get("schema"):
        raise TrajectoryAuditError("DSH verifier receipt has the wrong schema")
    receipt_body = {key: value for key, value in receipt.items() if key != "receipt_id"}
    if _digest(_canonical_json_bytes(receipt_body)) != receipt_sha256:
        raise TrajectoryAuditError("reward_info.dsh.receipt_sha256 does not match verifier receipt")
    _require_equal(receipt.get("receipt_id"), receipt_sha256, field="verifier receipt receipt_id")
    if receipt.get("fresh") is not True or dsh.get("freshness") != "fresh":
        raise TrajectoryAuditError("DSH verifier receipt must be fresh")
    _require_equal(dsh.get("eligible"), receipt.get("eligible"), field="reward_info.dsh.eligible")
    if type(receipt.get("eligible")) is not bool or type(receipt.get("finished")) is not bool:
        raise TrajectoryAuditError("DSH verifier receipt eligibility and finished must be boolean")
    _require_equal(receipt["finished"], reward_info.get("finished"), field="receipt finished")
    _require_equal(receipt.get("reward"), reward, field="verifier receipt reward")
    _require_equal(receipt.get("dsh_session_id"), dsh_session_id, field="verifier receipt dsh_session_id")
    _require_equal(receipt.get("trace_sha256"), trace_sha256, field="verifier receipt trace_sha256")
    _require_equal(receipt.get("artifact_sha256"), artifact_sha256, field="verifier receipt artifact_sha256")
    _require_equal(receipt.get("environment_digest"), environment_digest, field="verifier receipt environment_digest")

    verifier = _require_object(receipt.get("verifier"), field="DSH verifier receipt verifier")
    identity_fields = (
        ("task_id", receipt.get("task_id"), metadata.get("task_id")),
        ("task_version", receipt.get("task_version"), metadata.get("task_version")),
        ("split", dsh.get("split"), metadata.get("split")),
        ("environment_digest", environment_digest, metadata.get("environment_digest")),
        ("verifier_id", verifier.get("id"), metadata.get("verifier_id")),
        ("verifier_version", verifier.get("version"), metadata.get("verifier_version")),
        ("verifier_code_digest", verifier.get("code_digest"), metadata.get("verifier_code_digest")),
    )
    for field, receipt_value, envelope_value in identity_fields:
        _require_equal(dsh.get(field), receipt_value, field=f"reward_info.dsh.{field}")
        _require_equal(receipt_value, envelope_value, field=f"result envelope metadata.{field}")
    _require_equal(verifier.get("code_digest"), verifier_code_digest, field="verifier receipt code_digest")


def audit_diagnostic_stage(spec: StageSpec, execution: GatewayStageExecution) -> dict:
    """Return trusted diagnostic summaries or raise on broken evidence.

    This report contains verifier-side paths and is not actor prompt material.
    ``training_consumed`` is always false: an audit is not a queue receipt.
    """
    for name, expected in spec.file_hashes.items():
        if sha(read_regular(name)) != expected:
            raise TrajectoryAuditError("Stage input or source changed")
    if runtime_digest(spec.operator.runtime_executable) != spec.operator.environment_digest:
        raise TrajectoryAuditError("Runtime changed")
    expected_context = {
        "partition_id": spec.context.partition,
        "gateway_session_id": spec.gateway_session_id,
        "group_uid": spec.context.group_uid,
        "session_index": spec.context.sibling,
        "global_steps": spec.context.global_steps,
    }
    if spec.context.partition not in {"train", "val"}:
        raise TrajectoryAuditError("Invalid stage partition")
    if execution.session_id != spec.gateway_session_id or any(
        execution.context.get(k) != v for k, v in expected_context.items()
    ):
        raise TrajectoryAuditError("Stage execution context mismatch")
    if not execution.trajectories:
        raise TrajectoryAuditError("Missing actual trajectories")
    reward_info = build_reward_info(execution.task_result)
    for trajectory in execution.trajectories:
        _validate_token_evidence(trajectory)
        if any(type(token) is not int or token < 0 for token in trajectory.prompt_ids + trajectory.response_ids):
            raise TrajectoryAuditError("Token IDs must be nonnegative integers")
        if any(type(mask) is not int or mask not in (0, 1) for mask in trajectory.response_mask):
            raise TrajectoryAuditError("Response mask must contain integer 0 or 1")
        for probability in trajectory.response_logprobs:
            _require_finite(probability, field="response log probability")
        _require_equal(trajectory.extra_fields.get("dsh_reward_info"), reward_info, field="TaskResult reward info")
        _require_equal(trajectory.finished, reward_info.get("finished"), field="typed finished")
        _require_equal(trajectory.reward_score, reward_info.get("reward"), field="typed reward")
    dsh = _require_object(reward_info.get("dsh"), field="reward_info.dsh")
    _require_equal(dsh.get("rollout_id"), spec.gateway_session_id, field="rollout session")
    _validate_partition(dsh=dsh, partition_id=spec.context.partition)
    _validate_trace(dsh=dsh, trace_root=spec.trace_root)
    _validate_diagnostic_artifacts(reward_info=reward_info, dsh=dsh, result_root=spec.result_root)
    key = hashlib.sha256(f"{dsh['dsh_session_id']}\0{dsh['trace_sha256']}".encode()).hexdigest()[:24]
    result_dir = spec.result_root / key
    receipt_path = result_dir / "verifier-receipt.json"
    envelope_path = result_dir / "agent-result.json"
    receipt = loads(read_regular(receipt_path))
    envelope = loads(read_regular(envelope_path))
    fixture = loads(read_regular(spec.fixture_path))
    prompt = loads(read_regular(spec.task_config_path.parent / "prompt.json"))
    if spec.raw_prompt != prompt or envelope.get("prompt") != prompt:
        raise TrajectoryAuditError("Stage prompt changed or does not match execution")
    if envelope.get("metadata") != spec.metadata or sha(canonical(fixture)) != spec.metadata["fixture_sha256"]:
        raise TrajectoryAuditError("Stage metadata or fixture mismatch")
    if fixture["training_stage"] != _binding(spec.context, spec.operator) or fixture["chain_id"] != spec.chain_id:
        raise TrajectoryAuditError("Stage group/source identity mismatch")
    if fixture["role"] != spec.role:
        raise TrajectoryAuditError("Stage role mismatch")
    _require_equal(envelope["dsh"].get("gateway_session_id"), spec.gateway_session_id, field="envelope gateway session")
    if verifier.bundle_digest() != spec.metadata["verifier_code_digest"]:
        raise TrajectoryAuditError("Verifier bundle changed")
    trace_path = spec.trace_root / hashlib.sha256(spec.gateway_session_id.encode()).hexdigest()[:24] / "session.jsonl"
    events = [loads(line) for line in read_regular(trace_path, 8_000_000).splitlines() if line]
    scored = verifier.score(fixture, events, envelope["response"], envelope["finished"], dsh["dsh_session_id"])
    for field in ("reward", "finished", "eligible"):
        _require_equal(scored[field], receipt[field], field=f"rescored {field}")
    evidence = [spec.metadata["fixture_sha256"], dsh["trace_sha256"], sha(canonical(fixture["training_stage"]))]
    if spec.role == "reader":
        evidence.extend(
            [
                fixture["writer_binding"]["receipt_id"],
                fixture["writer_binding"]["manifest_sha256"],
                scored["extra_info"]["output_snapshot_sha256"],
            ]
        )
    _require_equal(receipt.get("evidence"), evidence, field="rescored artifact evidence")
    _require_equal(receipt.get("issuer"), {"kind": "trusted-verifier", "id": "uni-agent-dsh"}, field="receipt issuer")
    calls = verifier.parent._tool_calls(events)
    memory_root = Path(fixture["memory_root"])
    reads = [
        Path(call["parsed_arguments"]["path"])
        for call in calls
        if call["name"] == "str_replace_editor"
        and isinstance(call["parsed_arguments"], dict)
        and call["parsed_arguments"].get("command") == "view"
        and isinstance(call["parsed_arguments"].get("path"), str)
    ]
    extra = scored["extra_info"]
    reason = (
        "unfinished"
        if not receipt["finished"]
        else "ineligible"
        if not receipt["eligible"]
        else ("zero_reward" if receipt["reward"] == 0 else "success")
    )
    return {
        "finished": receipt["finished"],
        "eligible": receipt["eligible"],
        "reward": receipt["reward"],
        "receipt_id": receipt["receipt_id"],
        "trace_sha256": dsh["trace_sha256"],
        "artifact_sha256": dsh["artifact_sha256"],
        "fixture_sha256": spec.metadata["fixture_sha256"],
        "model_tokens": sum(sum(t.response_mask) for t in execution.trajectories),
        "tool_call_count": len(calls),
        "memory_view_attempt_count": sum(p.is_relative_to(memory_root) for p in reads),
        "index_view_attempt_count": sum(p == memory_root / "index.md" for p in reads),
        "read_metric_scope": "view attempts, including failed calls; not evidence of successful reads",
        "reason": reason,
        "errors": extra["errors"],
        "unsafe": extra["unsafe"],
        "checks": extra["checks"],
        "receipt_path": str(receipt_path),
        "envelope_path": str(envelope_path),
        "trace_path": str(trace_path),
        "fixture_path": str(spec.fixture_path),
        "training_consumed": False,
    }
