"""Read-only admission of Harbor evidence bound to finalized Gateway trajectories."""

from __future__ import annotations

import os
import stat
from collections.abc import Mapping
from pathlib import Path

from pydantic import TypeAdapter

from uni_agent.gateway.session import Trajectory
from uni_agent.tasks.dsh.trajectory_audit import TrajectoryAuditError, _require_finite, _validate_token_evidence

from .client import DownloadedJob
from .evolution_scoring import EvolutionBinding, FrozenEvolution, load_evolution_binding
from .protocol import JobRequest, OpaqueId, RequestPolicy, TaskRef, validate_manifest, validate_request
from .task import (
    FrozenT2Fixture,
    RunnerContext,
    T2FixtureBinding,
    _canonical,
    _digest,
    _evolution_receipt,
    _fixture_lane,
    _json,
    _object,
    load_t2_fixture,
    verify_downloaded_evidence,
)


def _private_directory(path, *, dir_fd=None) -> int:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=dir_fd)
    info = os.fstat(descriptor)
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        os.close(descriptor)
        raise TrajectoryAuditError("Evidence directory is not owned and private")
    return descriptor


def _read(directory: int, name: str, limit: int) -> bytes:
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_uid != os.getuid()
            or stat.S_IMODE(before.st_mode) & 0o077
            or before.st_size > limit
        ):
            raise TrajectoryAuditError("Evidence must be a private bounded regular file without hard links")
        raw = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
        if len(raw) > limit or (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            raise TrajectoryAuditError("Evidence changed during bounded read")
        return raw


def _read_object(directory: int, name: str) -> tuple[dict, bytes]:
    raw = _read(directory, name, 65536)
    value = _object(_json(raw))
    if raw != _canonical(value):
        raise TrajectoryAuditError("Saved control evidence is not canonical JSON")
    return value, raw


def _verify_saved(
    directory: int,
    *,
    context: RunnerContext,
    run_id: str,
    worker_id: str,
    task_ref: TaskRef,
    policy: RequestPolicy,
    instruction: str,
    t2_fixture: FrozenT2Fixture | None = None,
    evolution: FrozenEvolution | None = None,
) -> tuple[dict, str, float]:
    request_data, _ = _read_object(directory, "request.json")
    parsed = JobRequest.model_validate(request_data)
    # Recheck the recorded execution-window contract, not current wall-clock
    # freshness. Session/nonce replay prevention belongs to the worker ledger.
    request = validate_request(
        request_data,
        policy=policy,
        now_unix=parsed.budgets.deadline_unix - parsed.budgets.wall_time_seconds,
    )
    if request.run_id != run_id or request.task_ref != task_ref:
        raise TrajectoryAuditError("Saved run/task differs from operator configuration")
    for field in ("gateway_session_id", "group_uid", "sample_index", "partition_id"):
        if getattr(request, field) != getattr(context, field):
            raise TrajectoryAuditError("Saved request differs from Framework context")
    manifest_data, manifest_bytes = _read_object(directory, "manifest.json")
    manifest = validate_manifest(manifest_data, request=request, worker_id=worker_id)
    artifacts = {entry.id: _read(directory, entry.id, entry.size_bytes) for entry in manifest.artifacts}
    reward = verify_downloaded_evidence(
        request, DownloadedJob(manifest, artifacts), worker_id=worker_id, t2_fixture=t2_fixture, evolution=evolution
    )
    receipt, _ = _read_object(directory, "receipt.json")
    body = {key: value for key, value in receipt.items() if key != "receipt_id"}
    expected = {
        "schema": "dsh.harbor-verifier-receipt.v1",
        "admission_stage": "task-evidence-verified",
        "job_id": request.job_id,
        "request_sha256": request.request_sha256,
        "nonce": request.nonce,
        "run_id": run_id,
        "framework_context": context.model_dump(),
        "instruction_sha256": _digest(instruction.encode()),
        "gateway_session_id": context.gateway_session_id,
        "dsh_session_id": "dsh-" + context.gateway_session_id,
        "task_ref": request.task_ref.model_dump(),
        "dsh_release": request.dsh_release.model_dump(mode="json"),
        "worker_id": worker_id,
        "trial_id": manifest.trial_id,
        "manifest_canonical_sha256": _digest(manifest_bytes),
        "artifacts": [entry.model_dump() for entry in manifest.artifacts],
        "reward": reward,
        "verifier_reward": reward,
        "finished": True,
    }
    if t2_fixture is not None:
        expected["t2_fixture_sha256"] = t2_fixture.sha256
    if evolution is not None:
        expected["evolution_binding"] = _evolution_receipt(evolution)
    # Canonical comparison also distinguishes bool/int/float substitutions.
    if _canonical(body) != _canonical(expected):
        raise TrajectoryAuditError("Harbor receipt does not bind the verified evidence and Framework context")
    receipt_id = _digest(_canonical(body))
    if receipt.get("receipt_id") != receipt_id:
        raise TrajectoryAuditError("Harbor receipt body hash mismatch")
    return expected, receipt_id, reward


def validate_trajectories(
    trajectories: tuple[Trajectory, ...],
    *,
    context: Mapping[str, object],
    artifact_root: str,
    run_id: str,
    worker_id: str,
    task_ref: Mapping[str, object] | TaskRef,
    policy: Mapping[str, object] | RequestPolicy,
    instruction: str,
    t2_fixture: Mapping[str, object] | T2FixtureBinding | None = None,
    evolution_binding: Mapping[str, object] | EvolutionBinding | None = None,
) -> list[Trajectory]:
    """FQN postprocessor; all kwargs except context must be operator configured.

    Returns the original objects and token arrays. Hashes prove consistency with
    trusted saved evidence, not an independent model run or worker attestation.
    """
    try:
        if not trajectories:
            raise TrajectoryAuditError("Harbor audit requires at least one trajectory")
        trusted_context = RunnerContext.model_validate(dict(context))
        trusted_policy = RequestPolicy.model_validate(policy)
        trusted_task = TaskRef.model_validate(task_ref)
        fixture = (
            load_t2_fixture(T2FixtureBinding.model_validate(t2_fixture), trusted_task)
            if t2_fixture is not None
            else None
        )
        evolution = (
            load_evolution_binding(
                EvolutionBinding.model_validate(evolution_binding),
                trusted_task,
                repository_root=Path(__file__).resolve().parents[3],
            )
            if evolution_binding is not None
            else None
        )
        _fixture_lane(trusted_policy.dsh_release, trusted_task, fixture, evolution)
        TypeAdapter(OpaqueId).validate_python(run_id)
        TypeAdapter(OpaqueId).validate_python(worker_id)
        if not isinstance(instruction, str) or not instruction:
            raise TrajectoryAuditError("Operator instruction is required")
        root = Path(artifact_root)
        if not root.is_absolute() or ".." in root.parts:
            raise TrajectoryAuditError("Operator artifact root must be absolute")
        root_fd = _private_directory(root)
        try:
            for trajectory in trajectories:
                _validate_token_evidence(trajectory)
                info = _object((trajectory.extra_fields or {}).get("dsh_reward_info"))
                if trajectory.finished is not True or info.get("finished") is not True:
                    raise TrajectoryAuditError("Typed and receipt completion must be true")
                metadata = _object(info.get("harbor_dsh"))
                job_id = TypeAdapter(OpaqueId).validate_python(metadata.get("job_id"))
                directory = _private_directory(job_id, dir_fd=root_fd)
                try:
                    body, receipt_id, reward = _verify_saved(
                        directory,
                        context=trusted_context,
                        run_id=run_id,
                        worker_id=worker_id,
                        task_ref=trusted_task,
                        policy=trusted_policy,
                        instruction=instruction,
                        t2_fixture=fixture,
                        evolution=evolution,
                    )
                finally:
                    os.close(directory)
                expected_metadata = {
                    "schema": body["schema"],
                    "receipt_sha256": receipt_id,
                    "receipt_path": str(root.resolve() / job_id / "receipt.json"),
                    "job_id": body["job_id"],
                    "request_sha256": body["request_sha256"],
                    "gateway_session_id": trusted_context.gateway_session_id,
                }
                if _canonical(metadata) != _canonical(expected_metadata):
                    raise TrajectoryAuditError("Task reward metadata does not match saved Harbor receipt")
                for value in (trajectory.reward_score, info.get("reward"), info.get("verifier_reward")):
                    if _require_finite(value, field="Harbor reward") != reward:
                        raise TrajectoryAuditError("Typed reward differs from the verified Harbor reward")
        finally:
            os.close(root_fd)
    except TrajectoryAuditError:
        raise
    except (OSError, ValueError, TypeError, RuntimeError, KeyError) as error:
        raise TrajectoryAuditError("Harbor saved evidence or runtime binding was rejected") from error
    return list(trajectories)
