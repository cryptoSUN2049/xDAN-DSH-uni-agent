"""Pure contracts for a bounded Harbor worker; no transport or training admission.

Hashes bind content, not authority. The caller supplies an independently frozen
operator policy and published request. Stateful callers must serialize replay
checks with job insertion; these functions do not provide a distributed lock.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import math
from collections.abc import Iterable, Mapping
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator, model_validator

OpaqueId = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")]
Sha256 = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
PositiveInt = Annotated[int, Field(gt=0)]
PositiveFloat = Annotated[float, Field(gt=0, allow_inf_nan=False)]
Port = Annotated[int, Field(ge=1, le=65535)]


def _array(value: Any) -> tuple:
    if not isinstance(value, list | tuple):
        raise ValueError("Expected an array")
    return tuple(value)


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, revalidate_instances="always")


class TaskRef(Contract):
    id: OpaqueId
    version: OpaqueId
    sha256: Sha256


class DshRelease(Contract):
    source_sha: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
    sdk_sha256: Sha256
    runtime_sha256: Sha256
    image_digest: Sha256
    platform: Literal["linux/amd64", "linux/arm64"]
    profile: OpaqueId
    patch_sha256s: Annotated[tuple[Sha256, ...], BeforeValidator(_array)]


class ModelRoute(Contract):
    gateway_host: str
    gateway_port: Port
    session_path: str
    model_name: Annotated[str, Field(min_length=1, max_length=256)]
    tunnel_alias: OpaqueId

    @field_validator("gateway_host")
    @classmethod
    def _ip_only(cls, value: str) -> str:
        address = ipaddress.ip_address(value)
        if "%" in value or address.is_unspecified or address.is_multicast:
            raise ValueError("Gateway must be a specific node IP")
        return str(address)

    @field_validator("model_name")
    @classmethod
    def _model_name(cls, value: str) -> str:
        if value != value.strip() or any(ord(character) < 32 for character in value):
            raise ValueError("Invalid model name")
        return value


class Budgets(Contract):
    deadline_unix: PositiveFloat
    wall_time_seconds: PositiveFloat
    cpus: PositiveFloat
    memory_mb: PositiveInt
    max_tokens: PositiveInt
    max_artifact_bytes: PositiveInt


class _RequestBody(Contract):
    schema_: Literal["dsh.harbor-job-request.v1"] = Field(alias="schema")
    job_id: OpaqueId
    idempotency_key: OpaqueId
    run_id: OpaqueId
    group_uid: OpaqueId
    sample_index: Annotated[int, Field(ge=0)]
    partition_id: Literal["train", "val", "test"]
    gateway_session_id: OpaqueId
    nonce: Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
    task_ref: TaskRef
    dsh_release: DshRelease
    model_route: ModelRoute
    budgets: Budgets

    @model_validator(mode="after")
    def _session_path(self):
        if self.model_route.session_path != f"/sessions/{self.gateway_session_id}/v1":
            raise ValueError("Gateway path does not match the published session")
        return self


def request_sha256(value: Mapping[str, Any] | JobRequest) -> str:
    """Hash validated normalized fields, excluding request_sha256 itself.

    JSON uses sorted keys, UTF-8, compact separators and no NaN. Numeric budget
    fields normalize to floats before hashing; tuple arrays serialize as lists.
    """
    data = value.model_dump(mode="json", by_alias=True) if isinstance(value, JobRequest) else dict(value)
    data.pop("request_sha256", None)
    body = _RequestBody.model_validate(data).model_dump(mode="json", by_alias=True)
    raw = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
    return "sha256:" + hashlib.sha256(raw).hexdigest()


class JobRequest(_RequestBody):
    request_sha256: Sha256

    @model_validator(mode="after")
    def _hash(self):
        if self.request_sha256 != request_sha256(self):
            raise ValueError("Request hash mismatch")
        return self


class RequestPolicy(Contract):
    task_refs: Annotated[tuple[TaskRef, ...], BeforeValidator(_array), Field(min_length=1)]
    dsh_release: DshRelease
    gateway_host: str
    gateway_port: Port
    model_name: str
    tunnel_alias: OpaqueId
    max_wall_time_seconds: PositiveFloat
    max_cpus: PositiveFloat
    max_memory_mb: PositiveInt
    max_tokens: PositiveInt
    max_artifact_bytes: PositiveInt


def validate_request(data: Mapping[str, Any], *, policy: RequestPolicy, now_unix: float) -> JobRequest:
    request = JobRequest.model_validate(data)
    if isinstance(now_unix, bool) or not math.isfinite(now_unix) or now_unix <= 0:
        raise ValueError("Invalid controller time")
    if request.task_ref not in policy.task_refs or request.dsh_release != policy.dsh_release:
        raise ValueError("Task or DSH release is not approved")
    for field in ("gateway_host", "gateway_port", "model_name", "tunnel_alias"):
        if getattr(request.model_route, field) != getattr(policy, field):
            raise ValueError(f"Unapproved model route: {field}")
    for field in ("wall_time_seconds", "cpus", "memory_mb", "max_tokens", "max_artifact_bytes"):
        limit = field if field.startswith("max_") else f"max_{field}"
        if getattr(request.budgets, field) > getattr(policy, limit):
            raise ValueError(f"Budget exceeds operator limit: {field}")
    if not now_unix < request.budgets.deadline_unix <= now_unix + request.budgets.wall_time_seconds:
        raise ValueError("Deadline expired or exceeds the execution budget")
    return request


def check_replay(request: JobRequest, existing: Iterable[JobRequest]) -> bool:
    """Return True for the same published request, reject conflicting reuse.

    No implicit retry is authorized. Retain failed/unknown job identities in the
    caller's ledger too. Atomic ledger insertion belongs to the future worker.
    """
    duplicate = False
    for previous in existing:
        if previous.request_sha256 == request.request_sha256:
            duplicate = True
            continue
        for field in ("idempotency_key", "job_id", "nonce", "gateway_session_id"):
            if getattr(previous, field) == getattr(request, field):
                raise ValueError(f"Identity reused by a different request: {field}")
    return duplicate


ArtifactKind = Literal["dsh_trace", "dsh_result", "harbor_result", "verifier_log", "reward", "receipt", "binding"]


class Artifact(Contract):
    id: OpaqueId
    kind: ArtifactKind
    size_bytes: Annotated[int, Field(ge=0)]
    sha256: Sha256


class JobManifest(Contract):
    schema_: Literal["dsh.harbor-job-manifest.v1"] = Field(alias="schema")
    job_id: OpaqueId
    request_sha256: Sha256
    gateway_session_id: OpaqueId
    nonce: Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
    worker_id: OpaqueId
    trial_id: OpaqueId | None
    status: Literal["succeeded", "failed", "cancelled"]
    sealed_at_unix: PositiveFloat
    error_code: OpaqueId | None = None
    artifacts: Annotated[tuple[Artifact, ...], BeforeValidator(_array)]

    @model_validator(mode="after")
    def _sealed(self):
        ids = [artifact.id for artifact in self.artifacts]
        kinds = [artifact.kind for artifact in self.artifacts]
        if len(set(ids)) != len(ids) or len(set(kinds)) != len(kinds):
            raise ValueError("Duplicate artifact identity or kind")
        if self.status == "succeeded":
            required = {"dsh_trace", "dsh_result", "harbor_result", "verifier_log", "reward"}
            if self.trial_id is None or self.error_code is not None or not required.issubset(kinds):
                raise ValueError("Successful execution requires complete evidence and no infrastructure error")
        elif self.error_code is None:
            raise ValueError("Failed or cancelled execution requires a classified error")
        return self


def validate_manifest(data: Mapping[str, Any], *, request: JobRequest, worker_id: str) -> JobManifest:
    """Bind sealed metadata to controller expectations, not training eligibility."""
    manifest = JobManifest.model_validate(data)
    for field in ("job_id", "request_sha256", "gateway_session_id", "nonce"):
        if getattr(manifest, field) != getattr(request, field):
            raise ValueError(f"Manifest identity mismatch: {field}")
    if manifest.worker_id != worker_id:
        raise ValueError("Unregistered worker identity")
    if sum(artifact.size_bytes for artifact in manifest.artifacts) > request.budgets.max_artifact_bytes:
        raise ValueError("Artifact bytes exceed the published budget")
    return manifest


def validate_artifact(artifact: Artifact, content: bytes) -> None:
    """Verify downloaded raw bytes; never resolve an artifact ID as a path."""
    if not isinstance(content, bytes) or len(content) != artifact.size_bytes:
        raise ValueError("Artifact length mismatch")
    if "sha256:" + hashlib.sha256(content).hexdigest() != artifact.sha256:
        raise ValueError("Artifact hash mismatch")
