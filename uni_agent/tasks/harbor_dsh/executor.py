"""One native Harbor trial, with bounded evidence and independently checked cleanup.

The worker must validate JobRequest against its frozen operator policy first.
Release wheel/source hashes describe the approved image, not fresh attestation.
Any exception (including cancellation) leaves cleanup unconfirmed to the caller.
max_tokens limits each model request here; episode totals require the training
Gateway session's separately configured and audited token budget. File limits
bound evidence admission after Harbor collection, not upstream download traffic.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import stat
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import tomllib
from harbor.environments.docker.docker import _sanitize_docker_compose_project_name
from harbor.models.trial.config import TrialConfig
from harbor.trial.hooks import TrialEvent

from uni_agent.agents.dsh.agent import _require_result, _run_key
from uni_agent.tasks.harbor_dsh.isolated_trial import _run_bounded_command, create_isolated_trial
from uni_agent.tasks.harbor_dsh.protocol import JobRequest


@dataclass(frozen=True)
class ExecutionResult:
    trial_id: str
    artifacts: dict[str, bytes]
    cleanup_confirmed: bool


def _digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _read_regular(root: Path, path: Path, limit: int) -> bytes:
    """Open beneath an owned root without following links or blocking on FIFOs."""
    relative = path.relative_to(root)
    if not relative.parts or ".." in relative.parts:
        raise ValueError("Invalid evidence path")
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for component in relative.parts[:-1]:
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        descriptor = os.open(relative.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(descriptor, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                raise ValueError("Evidence must be a regular file with no hard links")
            if before.st_size > limit:
                raise ValueError("Evidence exceeds artifact byte budget")
            raw = stream.read(limit + 1)
            after = os.fstat(stream.fileno())
            if len(raw) > limit or (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            ):
                raise ValueError("Evidence changed during bounded read")
            return raw
    finally:
        os.close(directory)


def _task_digest(task_dir: Path) -> str:
    if task_dir.is_symlink() or not task_dir.is_dir():
        raise ValueError("Task root must be a real directory")
    files = {}
    for path in sorted(task_dir.rglob("*")):
        info = path.lstat()
        if stat.S_ISDIR(info.st_mode):
            continue
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("Task tree must contain only regular files and directories")
        raw = _read_regular(task_dir, path, info.st_size)
        files[path.relative_to(task_dir).as_posix()] = hashlib.sha256(raw).hexdigest()
    return _digest(json.dumps(files, sort_keys=True, separators=(",", ":")).encode())


def _json(raw: bytes):
    def reject_constant(value):
        raise ValueError(f"Non-finite JSON number: {value}")

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    return json.loads(raw, parse_constant=reject_constant, object_pairs_hook=unique_object)


async def _docker_inventory(project: str, resource: str) -> bytes:
    command = ["docker", "ps", "--all", "--quiet"] if resource == "container" else ["docker", resource, "ls", "--quiet"]
    command.extend(["--filter", f"label=com.docker.compose.project={project}"])
    code, output, diagnostic = await _run_bounded_command(command, timeout=15)
    if code != 0 or diagnostic:
        raise RuntimeError("Docker cleanup inventory failed")
    return output


async def _confirm_cleanup(trial) -> None:
    # Harbor 0.16.1 may swallow verifier stop exceptions. Inspect resources,
    # including stopped containers, independently of its in-memory stop flag.
    sessions = (trial.agent_environment.session_id, trial._separate_verifier_session_id("trial"))
    for session in sessions:
        project = _sanitize_docker_compose_project_name(session)
        for resource in ("container", "network", "volume"):
            if (await _docker_inventory(project, resource)).strip():
                raise RuntimeError("Harbor cleanup left resources behind")


def _collect_evidence(trial, result, request: JobRequest, private_root: Path) -> dict[str, bytes]:
    if result.exception_info is not None or str(result.id) != str(trial.id):
        raise RuntimeError("Harbor trial failed or returned a different identity")
    paths = trial.paths
    dsh = paths.agent_dir / "dsh"
    reward_path = (
        paths.reward_json_path
        if paths.reward_json_path.exists() or paths.reward_json_path.is_symlink()
        else paths.reward_text_path
    )
    selected = {
        "dsh_trace": dsh / "session.jsonl",
        "dsh_result": dsh / "run.json",
        "harbor_result": paths.result_path,
        "verifier_log": paths.test_stdout_path,
        "reward": reward_path,
    }
    budget = request.budgets.max_artifact_bytes
    artifacts = {}
    for kind, path in selected.items():
        artifacts[kind] = _read_regular(private_root, path, budget)
        budget -= len(artifacts[kind])
    # Auxiliary bridge receipts are private evidence, bounded by the same cap.
    raw_status = _read_regular(private_root, dsh / "status.json", budget)
    budget -= len(raw_status)
    raw_agent = _read_regular(private_root, dsh / "agent-result.json", budget)
    status = _json(raw_status)
    agent = _json(raw_agent)
    harbor = _json(artifacts["harbor_result"])
    session = request.gateway_session_id
    trace_path = f"/tmp/uni-agent-dsh/artifacts/{_run_key(session)}/session.jsonl"
    helper = _require_result(
        _json(artifacts["dsh_result"]),
        expected_trace_path=trace_path,
        expected_dsh_session_id=f"dsh-{session}",
        require_trace=True,
    )
    trace_hash = _digest(artifacts["dsh_trace"])
    events = [_json(line) for line in artifacts["dsh_trace"].splitlines()]
    expected_status = {
        "schema": "dsh.harbor-agent-execution.v1",
        "status": "completed",
        "finish_reason": "completed",
        "gateway_session_id": session,
        "dsh_session_id": f"dsh-{session}",
        "harbor_context_id": str(trial.id),
        "harbor_agent_session_id": trial.config.trial_name + "__agent",
        "trace_sha256": trace_hash,
        "run_sha256": _digest(artifacts["dsh_result"]),
        "agent_result_sha256": _digest(raw_agent),
        "event_count": len(events),
    }
    if (
        not isinstance(status, dict)
        or any(status.get(key) != value for key, value in expected_status.items())
        or status.get("finished") is not True
        or agent.get("finished") is not True
        or result.agent_result is None
        or result.agent_result.metadata.get("dsh") != status
        or helper.get("finish_reason") != "completed"
        or helper.get("profile") != request.dsh_release.profile
        or helper.get("patches_sha256") != _digest(b"[]")
        or helper["trace_sha256"] != trace_hash
        or helper["event_count"] != len(events)
        or not events
        or any(not isinstance(event, dict) for event in events)
        or events[-1].get("type") != "turn/end"
        or agent.get("output", {}).get("response") != helper["final_response"]
        or harbor.get("id") != str(trial.id)
        or harbor.get("exception_info") is not None
        or harbor.get("agent_result", {}).get("metadata", {}).get("dsh") != status
    ):
        raise RuntimeError("DSH finished trace/result identity verification failed")
    info = agent.get("info", {})
    expected_info = {
        "gateway_session_id": session,
        "dsh_session_id": f"dsh-{session}",
        "trace_path": trace_path,
        "trace_sha256": trace_hash,
        "event_count": len(events),
    }
    if any(info.get(key) != value for key, value in expected_info.items()):
        raise RuntimeError("DSH agent result identity mismatch")
    reward = (
        _json(artifacts["reward"]) if reward_path == paths.reward_json_path else {"reward": float(artifacts["reward"])}
    )
    if (
        not isinstance(reward, dict)
        or set(reward) != {"reward"}
        or type(reward["reward"]) not in (float, int)
        or not math.isfinite(reward["reward"])
        or result.verifier_result is None
        or result.verifier_result.rewards != reward
        or harbor.get("verifier_result", {}).get("rewards") != reward
    ):
        raise RuntimeError("Independent verifier reward is missing, non-finite or inconsistent")
    return artifacts


async def execute_job(
    request: JobRequest,
    *,
    task_dir: Path,
    trials_root: Path,
    gateway_base_url: str,
    on_verifying: Callable[[], Awaitable[None]],
) -> ExecutionResult:
    """Execute an already admitted single-file task; failures never imply cleanup."""
    request = JobRequest.model_validate(request.model_dump(mode="json", by_alias=True))
    url = urlsplit(gateway_base_url)
    if (
        url.scheme not in {"http", "https"}
        or not url.hostname
        or url.username is not None
        or url.password is not None
        or url.query
        or url.fragment
        or url.path != request.model_route.session_path
    ):
        raise ValueError("Mapped Gateway URL must preserve the exact session path without credentials")
    if request.dsh_release.profile != "sdk-minimal" or request.dsh_release.patch_sha256s:
        raise ValueError("First execution requires the fixed sdk-minimal profile without patches")
    if not request.budgets.cpus.is_integer():
        raise ValueError("Harbor Docker requires an integer CPU budget")
    if _task_digest(task_dir) != request.task_ref.sha256:
        raise ValueError("Frozen task content hash mismatch")
    task = tomllib.loads(_read_regular(task_dir, task_dir / "task.toml", 1024 * 1024).decode())
    if task.get("environment", {}).get("docker_image") != request.dsh_release.image_digest:
        raise ValueError("Task image does not match the approved DSH release")
    remaining = min(request.budgets.wall_time_seconds, request.budgets.deadline_unix - time.time())
    if remaining <= 0:
        raise ValueError("Job deadline expired")
    if trials_root.is_symlink():
        raise ValueError("Trials root must not be a symlink")
    trials_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    private_root = trials_root.resolve() / request.job_id
    private_root.mkdir(mode=0o700, exist_ok=False)
    config = TrialConfig.model_validate(
        {
            "task": {"path": str(task_dir.resolve())},
            "trials_dir": str(private_root),
            "trial_name": "dsh-" + request.request_sha256.removeprefix("sha256:")[:32],
            "agent": {
                "import_path": "uni_agent.agents.dsh.harbor_agent:DshHarborAgent",
                "model_name": request.model_route.model_name,
                "kwargs": {
                    "gateway_base_url": gateway_base_url,
                    "profile": request.dsh_release.profile,
                    "patches": [],
                    "workdir": "/app",
                    "max_tokens_per_turn": request.budgets.max_tokens,
                    "run_timeout": remaining,
                },
            },
            "environment": {
                "type": "docker",
                "delete": True,
                "override_cpus": int(request.budgets.cpus),
                "override_memory_mb": request.budgets.memory_mb,
            },
        }
    )
    trial = create_isolated_trial(config, allowed_task_dir=task_dir.resolve())
    verifying = False

    async def verification_started(_event):
        nonlocal verifying
        if verifying:
            raise RuntimeError("Native verifier started more than once")
        verifying = True
        await on_verifying()

    trial.add_hook(TrialEvent.VERIFICATION_START, verification_started)
    async with asyncio.timeout(min(remaining, request.budgets.deadline_unix - time.time())):
        result = await trial.run()
    if not verifying:
        raise RuntimeError("Native verifier did not start")
    await _confirm_cleanup(trial)
    if _task_digest(task_dir) != request.task_ref.sha256:
        raise RuntimeError("Frozen task changed during execution")
    artifacts = _collect_evidence(trial, result, request, private_root)
    return ExecutionResult(trial_id=str(trial.id), artifacts=artifacts, cleanup_confirmed=True)
