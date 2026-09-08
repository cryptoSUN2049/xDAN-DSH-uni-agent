"""Bind native Harbor verifier evidence to one Framework-owned training session.

No sandbox or agent is created here. Receipt admission is task-level only;
Gateway token/trajectory admission remains a separate postprocessor responsibility.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import os
import stat
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, ClassVar, Literal
from urllib.parse import urlsplit
from uuid import uuid4

from pydantic import ConfigDict, Field, SecretStr, field_validator, model_validator

from uni_agent.agents.dsh.agent import _require_result, _run_key, prompt_from_messages
from uni_agent.agents.dsh.harbor_release import release_patch_paths, release_patch_paths_digest
from uni_agent.tasks.base import Task, TaskConfig, TaskResult, build_reward_info
from uni_agent.tasks.registry import register_task

from .client import DownloadedJob, HarborDshClient
from .evolution_scoring import (
    EVOLUTION_KIND,
    EvolutionBinding,
    FrozenEvolution,
    load_evolution_binding,
    require_evolution_admission,
    score_evolution,
)
from .protocol import (
    Contract,
    JobRequest,
    OpaqueId,
    RequestPolicy,
    Sha256,
    TaskRef,
    request_sha256,
    validate_artifact,
    validate_manifest,
    validate_request,
)


class RunnerContext(Contract):
    partition_id: Literal["train", "val", "test"]
    gateway_session_id: OpaqueId
    global_steps: Annotated[int, Field(ge=0)] | None
    group_uid: OpaqueId
    group_size: Annotated[int, Field(gt=0)]
    sample_index: Annotated[int, Field(ge=0)]
    session_index: Annotated[int, Field(ge=0)]


class T2FixtureBinding(Contract):
    task_ref: TaskRef
    fixture_path: str
    fixture_sha256: Sha256

    @field_validator("fixture_path")
    @classmethod
    def _absolute_path(cls, value):
        if not Path(value).is_absolute() or ".." in Path(value).parts:
            raise ValueError("T2 fixture path must be absolute and traversal-free")
        return value


@dataclass(frozen=True)
class FrozenT2Fixture:
    task_ref: TaskRef
    sha256: str
    raw: bytes


def load_t2_fixture(binding: T2FixtureBinding, task_ref: TaskRef) -> FrozenT2Fixture:
    if binding.task_ref != task_ref:
        raise ValueError("T2 fixture TaskRef mismatch")
    descriptor = os.open(binding.fixture_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 1048576:
            raise ValueError("T2 fixture must be a bounded regular file")
        raw = stream.read(1048577)
    if len(raw) > 1048576 or _digest(raw) != binding.fixture_sha256:
        raise ValueError("T2 fixture hash mismatch")
    fixture = _object(_json(raw))
    if (
        fixture.get("schema") != "dsh.t2-log-tool-case.v1"
        or fixture.get("public") is not True
        or not isinstance(fixture.get("calls"), list)
        or len(fixture["calls"]) < 2
    ):
        raise ValueError("Invalid frozen T2 public fixture")
    return FrozenT2Fixture(task_ref=binding.task_ref, sha256=binding.fixture_sha256, raw=raw)


def _fixture_lane(release, task_ref, fixture, evolution=None):
    patched = bool(release_patch_paths(release))
    if fixture is not None and evolution is not None:
        raise ValueError("T2 and evolution bindings are mutually exclusive")
    if patched != (fixture is not None or evolution is not None):
        raise ValueError("Patched release requires an independent operator fixture binding")
    if fixture is not None and (fixture.task_ref != task_ref or _digest(fixture.raw) != fixture.sha256):
        raise ValueError("Frozen T2 fixture identity mismatch")
    if evolution is not None:
        metadata = _object(_json(evolution.metadata_raw))
        if (
            evolution.kind != EVOLUTION_KIND
            or evolution.task_ref != task_ref
            or _digest(evolution.fixture_raw) != evolution.fixture_sha256
            or _digest(evolution.metadata_raw) != evolution.metadata_sha256
            or metadata.get("environment_digest") != release.runtime_sha256
            or metadata.get("profile") != release.profile
            or metadata.get("patches_sha256") != release_patch_paths_digest(release)
        ):
            raise ValueError("Frozen evolution TaskRef/deployment identity mismatch")


def _evolution_receipt(frozen):
    return {
        "kind": frozen.kind,
        "fixture_sha256": frozen.fixture_sha256,
        "metadata_sha256": frozen.metadata_sha256,
        "source_sha256s": dict(frozen.source_sha256s),
    }


def _verify_t2_business(trace: bytes, reward: float, fixture: FrozenT2Fixture):
    from examples.dsh.capability_tasks.log_tool.verifier import verify_trace

    with tempfile.TemporaryDirectory(prefix="harbor-t2-audit-") as folder:
        path = Path(folder) / "session.jsonl"
        path.write_bytes(trace)
        path.chmod(0o600)
        result = verify_trace(path, _digest(trace), fixture=_json(fixture.raw))
    if result.get("eligible") is not True or type(result.get("passed")) is not bool:
        raise ValueError("T2 business evidence is not eligible")
    if float(result["passed"]) != reward:
        raise ValueError("T2 recomputed business score differs from Harbor reward")


class HarborDshTaskConfig(TaskConfig):
    name: Literal["harbor_dsh"] = "harbor_dsh"
    sandbox: None = None
    agent: None = None
    instruction: str = Field(min_length=1)
    run_id: OpaqueId
    task_ref: TaskRef
    t2_fixture: T2FixtureBinding | None = None
    evolution_binding: EvolutionBinding | None = None
    task_config_optional_only_fields: ClassVar[frozenset[str]] = frozenset({"t2_fixture", "evolution_binding"})
    policy: RequestPolicy
    worker_url: str
    worker_token: SecretStr = Field(exclude=True, repr=False)
    worker_id: OpaqueId
    artifact_root: str
    gateway_base_url: str
    runner_context: RunnerContext
    model_config = ConfigDict(frozen=True)
    task_config_only_fields = frozenset(
        {
            "run_id",
            "task_ref",
            "policy",
            "worker_url",
            "worker_token",
            "worker_id",
            "artifact_root",
            "instruction",
        }
    )

    @model_validator(mode="before")
    @classmethod
    def _no_template(cls, value):
        if isinstance(value, dict) and value.get("prompt_template") is not None:
            raise ValueError("Harbor prompt_template cannot replace original dataset messages")
        return value

    @field_validator("artifact_root")
    @classmethod
    def _absolute_root(cls, value):
        if not Path(value).is_absolute() or ".." in Path(value).parts:
            raise ValueError("Artifact root must be absolute and traversal-free")
        return value


def _digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _canonical(value) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n"
    ).encode()


def _json(raw: bytes):
    def reject_constant(_value):
        raise ValueError("Non-finite JSON evidence")

    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("Duplicate JSON evidence key")
            value[key] = item
        return value

    return json.loads(raw, parse_constant=reject_constant, object_pairs_hook=unique)


def _object(value):
    if not isinstance(value, dict):
        raise ValueError("Evidence must be a JSON object")
    return value


def verify_downloaded_evidence(
    request: JobRequest,
    downloaded: DownloadedJob,
    *,
    worker_id: str,
    t2_fixture: FrozenT2Fixture | None = None,
    evolution: FrozenEvolution | None = None,
) -> float:
    """Pure second-side evidence check; does not attest worker or Gateway tokens."""
    _fixture_lane(request.dsh_release, request.task_ref, t2_fixture, evolution)
    manifest = validate_manifest(
        downloaded.manifest.model_dump(mode="json", by_alias=True), request=request, worker_id=worker_id
    )
    kinds = {entry.kind for entry in manifest.artifacts}
    if manifest.status != "succeeded" or kinds != {
        "dsh_trace",
        "dsh_result",
        "harbor_result",
        "verifier_log",
        "reward",
    }:
        raise ValueError("Expected the five completed first-stage Harbor evidence artifacts")
    if set(downloaded.artifacts) != {entry.id for entry in manifest.artifacts}:
        raise ValueError("Downloaded artifact identities differ from manifest")
    by_kind = {}
    for entry in manifest.artifacts:
        content = downloaded.artifacts[entry.id]
        validate_artifact(entry, content)
        by_kind[entry.kind] = content
    session = request.gateway_session_id
    helper = _require_result(
        _json(by_kind["dsh_result"]),
        expected_trace_path=f"/tmp/uni-agent-dsh/artifacts/{_run_key(session)}/session.jsonl",
        expected_dsh_session_id="dsh-" + session,
        require_trace=True,
    )
    events = [_object(_json(line)) for line in by_kind["dsh_trace"].splitlines()]
    trace_hash = _digest(by_kind["dsh_trace"])
    if (
        helper.get("finish_reason") != "completed"
        or helper.get("profile") != request.dsh_release.profile
        or request.dsh_release.profile != "sdk-minimal"
        or helper.get("patches_sha256") != release_patch_paths_digest(request.dsh_release)
        or type(helper["event_count"]) is not int
        or helper["event_count"] != len(events)
        or helper["trace_sha256"] != trace_hash
        or not events
        or events[-1].get("type") != "turn/end"
    ):
        raise ValueError("DSH trace/result completion or identity mismatch")
    harbor = _object(_json(by_kind["harbor_result"]))
    status = _object(_object(_object(harbor.get("agent_result")).get("metadata")).get("dsh"))
    expected = {
        "schema": "dsh.harbor-agent-execution.v1",
        "status": "completed",
        "finish_reason": "completed",
        "gateway_session_id": session,
        "dsh_session_id": "dsh-" + session,
        "harbor_context_id": manifest.trial_id,
        "harbor_agent_session_id": "dsh-" + request.request_sha256.removeprefix("sha256:")[:32] + "__agent",
        "trace_sha256": trace_hash,
        "run_sha256": _digest(by_kind["dsh_result"]),
        "event_count": len(events),
    }
    if (
        harbor.get("id") != manifest.trial_id
        or "exception_info" not in harbor
        or harbor["exception_info"] is not None
        or status.get("finished") is not True
        or type(status.get("event_count")) is not int
        or any(status.get(key) != value for key, value in expected.items())
    ):
        raise ValueError("Harbor trial/DSH identity mismatch or incomplete execution")
    reward = _json(by_kind["reward"])
    if not isinstance(reward, dict):
        reward = {"reward": reward}
    if set(reward) != {"reward"} or type(reward["reward"]) not in (int, float) or not math.isfinite(reward["reward"]):
        raise ValueError("Invalid independent verifier reward")
    rewards = _object(_object(harbor.get("verifier_result")).get("rewards"))
    if set(rewards) != {"reward"} or type(rewards["reward"]) not in (int, float) or rewards != reward:
        raise ValueError("Harbor verifier reward mismatch")
    if t2_fixture is not None:
        _verify_t2_business(by_kind["dsh_trace"], float(reward["reward"]), t2_fixture)
    if evolution is not None:
        evaluation = score_evolution(
            frozen=evolution,
            task_ref=request.task_ref,
            trace=by_kind["dsh_trace"],
            trace_sha256=trace_hash,
            run_raw=by_kind["dsh_result"],
            run_sha256=_digest(by_kind["dsh_result"]),
            gateway_session_id=session,
        )
        require_evolution_admission(evaluation, float(reward["reward"]))
    return float(reward["reward"])


def _write(directory: int, name: str, raw: bytes) -> None:
    descriptor = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
    with os.fdopen(descriptor, "wb") as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())


def _open_job_root(root: Path, job_id: str) -> tuple[Path, int]:
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(descriptor)
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise ValueError("Artifact root must be owned and private (0700)")
        os.mkdir(job_id, mode=0o700, dir_fd=descriptor)
        child = os.open(job_id, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
        return root.resolve() / job_id, child
    finally:
        os.close(descriptor)


@register_task("harbor_dsh")
class HarborDshTask(Task):
    name = "harbor_dsh"
    config_model = HarborDshTaskConfig

    def __init__(self, config: HarborDshTaskConfig):
        if config.t2_fixture is not None and config.evolution_binding is not None:
            raise ValueError("T2 and evolution bindings are mutually exclusive")
        super().__init__(config.model_copy(deep=True))
        self._fixture = load_t2_fixture(config.t2_fixture, config.task_ref) if config.t2_fixture is not None else None
        self._evolution = (
            load_evolution_binding(
                config.evolution_binding, config.task_ref, repository_root=Path(__file__).resolve().parents[3]
            )
            if config.evolution_binding is not None
            else None
        )
        _fixture_lane(config.policy.dsh_release, config.task_ref, self._fixture, self._evolution)
        self._ran = False

    async def run(self) -> TaskResult:
        if self._ran:
            raise RuntimeError("A Harbor task instance can run only once")
        self._ran = True
        cfg = self.config
        context = cfg.runner_context
        if prompt_from_messages(cfg.prompt) != cfg.instruction:
            raise ValueError("Dataset prompt differs from the frozen Harbor instruction")
        route = urlsplit(cfg.gateway_base_url)
        if (
            route.scheme != "http"
            or not route.hostname
            or route.username is not None
            or route.password is not None
            or route.query
            or route.fragment
            or route.path != f"/sessions/{context.gateway_session_id}/v1"
            or str(ipaddress.ip_address(route.hostname)) != cfg.policy.gateway_host
            or route.port != cfg.policy.gateway_port
        ):
            raise ValueError("Framework session URL differs from the independent operator route/context")
        now = time.time()
        job_id = "job-" + uuid4().hex
        data = {
            "schema": "dsh.harbor-job-request.v1",
            "job_id": job_id,
            "idempotency_key": job_id,
            "run_id": cfg.run_id,
            "group_uid": context.group_uid,
            "sample_index": context.sample_index,
            "partition_id": context.partition_id,
            "gateway_session_id": context.gateway_session_id,
            "nonce": uuid4().hex,
            "task_ref": cfg.task_ref.model_dump(),
            "dsh_release": cfg.policy.dsh_release.model_dump(mode="json"),
            "model_route": {
                "gateway_host": cfg.policy.gateway_host,
                "gateway_port": cfg.policy.gateway_port,
                "session_path": route.path,
                "model_name": cfg.policy.model_name,
                "tunnel_alias": cfg.policy.tunnel_alias,
            },
            "budgets": {
                "deadline_unix": now + cfg.policy.max_wall_time_seconds,
                "wall_time_seconds": cfg.policy.max_wall_time_seconds,
                "cpus": cfg.policy.max_cpus,
                "memory_mb": cfg.policy.max_memory_mb,
                "max_tokens": cfg.policy.max_tokens,
                "max_artifact_bytes": cfg.policy.max_artifact_bytes,
            },
        }
        data["request_sha256"] = request_sha256(data)
        request = validate_request(data, policy=cfg.policy, now_unix=now)
        client = HarborDshClient(
            base_url=cfg.worker_url,
            token=cfg.worker_token.get_secret_value(),
            worker_id=cfg.worker_id,
            policy=cfg.policy,
        )
        directory_path, directory = _open_job_root(Path(cfg.artifact_root), job_id)
        try:
            _write(directory, "request.json", _canonical(request.model_dump(mode="json", by_alias=True)))
            downloaded = await client.run(request)
            manifest = validate_manifest(
                downloaded.manifest.model_dump(mode="json", by_alias=True), request=request, worker_id=cfg.worker_id
            )
            manifest_bytes = _canonical(manifest.model_dump(mode="json", by_alias=True))
            _write(directory, "manifest.json", manifest_bytes)
            if set(downloaded.artifacts) != {entry.id for entry in manifest.artifacts}:
                raise ValueError("Downloaded artifact identities differ from manifest")
            for entry in manifest.artifacts:
                content = downloaded.artifacts[entry.id]
                if not isinstance(content, bytes) or len(content) > entry.size_bytes:
                    raise ValueError("Artifact exceeds declared size or is not bytes")
                _write(directory, entry.id, content)
            reward = verify_downloaded_evidence(
                request, downloaded, worker_id=cfg.worker_id, t2_fixture=self._fixture, evolution=self._evolution
            )
            body = {
                "schema": "dsh.harbor-verifier-receipt.v1",
                "admission_stage": "task-evidence-verified",
                "job_id": request.job_id,
                "request_sha256": request.request_sha256,
                "nonce": request.nonce,
                "run_id": cfg.run_id,
                "framework_context": context.model_dump(),
                "instruction_sha256": _digest(cfg.instruction.encode()),
                "gateway_session_id": context.gateway_session_id,
                "dsh_session_id": "dsh-" + context.gateway_session_id,
                "task_ref": request.task_ref.model_dump(),
                "dsh_release": request.dsh_release.model_dump(mode="json"),
                "worker_id": manifest.worker_id,
                "trial_id": manifest.trial_id,
                "manifest_canonical_sha256": _digest(manifest_bytes),
                "artifacts": [entry.model_dump() for entry in manifest.artifacts],
                "reward": reward,
                "verifier_reward": reward,
                "finished": True,
            }
            if self._fixture is not None:
                body["t2_fixture_sha256"] = self._fixture.sha256
            if self._evolution is not None:
                body["evolution_binding"] = _evolution_receipt(self._evolution)
            receipt_id = _digest(_canonical(body))
            _write(directory, "receipt.json", _canonical({**body, "receipt_id": receipt_id}))
            os.fsync(directory)
            result = TaskResult(
                reward=reward,
                verifier_reward=reward,
                finished=True,
                reward_info={
                    "harbor_dsh": {
                        "schema": body["schema"],
                        "receipt_sha256": receipt_id,
                        "receipt_path": str(directory_path / "receipt.json"),
                        "job_id": request.job_id,
                        "request_sha256": request.request_sha256,
                        "gateway_session_id": request.gateway_session_id,
                    }
                },
            )
            build_reward_info(result)
            return result
        finally:
            os.close(directory)
