"""Harbor 0.16.1 mount isolation for the approved single-file DSH task.

The caller must freeze and audit the allowlisted task directory, including both
Compose definitions and images. This is not a general Docker/Compose security
validator. It removes Harbor-injected agent host mounts, while reusing Harbor's
separate verifier lifecycle and host-side DSH bridge evidence collection.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import importlib.metadata
import json
import re
import shlex
from pathlib import Path

from harbor.models.environment_type import EnvironmentType
from harbor.models.task.task import Task
from harbor.models.task.verifier_mode import VerifierEnvironmentMode, resolve_task_verifier_mode
from harbor.models.trial.artifact_manifest import ArtifactManifestEntry
from harbor.models.trial.config import ServiceVolumeConfig, TrialConfig
from harbor.trial.artifact_handler import ArtifactHandler
from harbor.trial.single_step import SingleStepTrial

_DSH_IMPORT = "uni_agent.agents.dsh.harbor_agent:DshHarborAgent"
_DSH_KWARGS = {
    "gateway_base_url",
    "gateway_api_key",
    "workdir",
    "profile",
    "patches",
    "runner_python",
    "max_tokens_per_turn",
    "run_timeout",
    "reasoning_effort",
}

MAX_ANSWER_BYTES = 4096


class AnswerArtifactError(RuntimeError):
    """The fixed answer artifact failed bounded snapshot admission."""


_ANSWER_READ_SCRIPT = """import base64, json, os, stat, sys
def snapshot():
    parent = os.open(sys.argv[1], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        try:
            fd = os.open('answer.txt', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        except FileNotFoundError:
            return {'status': 'missing'}
        with os.fdopen(fd, 'rb') as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > 4096:
                raise ValueError('not a bounded regular file')
            content = stream.read(4097)
            after = os.fstat(stream.fileno())
            if (len(content) > 4096 or len(content) != before.st_size
                or before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns
                or before.st_ctime_ns != after.st_ctime_ns):
                raise ValueError('file changed during snapshot')
            return {'status': 'ok', 'content': base64.b64encode(content).decode('ascii')}
    finally:
        os.close(parent)
try:
    result = snapshot()
except (OSError, ValueError):
    result = {'status': 'rejected'}
print(json.dumps(result, separators=(',', ':')))
"""


class _BoundedAnswerArtifacts(ArtifactHandler):
    async def _download_artifact(self, *, source_env, artifacts_dir, artifact, convention_source):
        if artifact.source != "/app/answer.txt":
            # The only other configured entry is Harbor's unmounted convention
            # directory. Its original mounted-provider path inspects the host.
            return await super()._download_artifact(
                source_env=source_env,
                artifacts_dir=artifacts_dir,
                artifact=artifact,
                convention_source=convention_source,
            )
        result = await asyncio.wait_for(
            source_env.exec(
                command=shlex.join(["python", "-c", _ANSWER_READ_SCRIPT, "/app"]),
                timeout_sec=30,
                user="root",
            ),
            timeout=30,
        )
        if result.return_code != 0 or len(result.stdout) > 6000:
            raise AnswerArtifactError("Invalid bounded answer snapshot response")
        try:
            envelope = json.loads(result.stdout)
            if envelope == {"status": "missing"}:
                content = None
            elif isinstance(envelope, dict) and set(envelope) == {"status", "content"} and envelope["status"] == "ok":
                content = base64.b64decode(envelope["content"], validate=True)
                if len(content) > MAX_ANSWER_BYTES:
                    raise ValueError("answer too large")
            else:
                raise ValueError("answer is not a bounded regular file")
        except (ValueError, TypeError, binascii.Error) as error:
            raise AnswerArtifactError("Rejected unsafe or malformed answer artifact") from error
        target = artifacts_dir / "app" / "answer.txt"
        if target.is_symlink() or target.exists() or target.parent.is_symlink():
            raise AnswerArtifactError("Refusing to overwrite an existing answer artifact")
        if content is not None:
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with target.open("xb") as output:
                output.write(content)
            target.chmod(0o600)
        return ArtifactManifestEntry(
            source="/app/answer.txt",
            destination="app/answer.txt",
            type="file",
            status="empty" if content is None else "ok",
        )


def _validate_runtime(config: TrialConfig, allowed_task_dir: Path) -> Path:
    if importlib.metadata.version("harbor") != "0.16.1":
        raise ValueError("IsolatedDshTrial requires Harbor 0.16.1")
    task = config.task
    if (
        task.path is None
        or task.git_url
        or task.name
        or task.ref
        or task.source
        or task.git_commit_id
        or task.download_dir
        or task.overwrite
    ):
        raise ValueError("Only the frozen local task allowlist is supported")
    task_dir = task.path.resolve(strict=True)
    if task_dir != Path(allowed_task_dir).resolve(strict=True):
        raise ValueError("Task is not the exact allowlisted directory")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", config.trial_name):
        raise ValueError("Unsafe trial name")
    env, agent, verifier = config.environment, config.agent, config.verifier
    if (
        env.type != EnvironmentType.DOCKER
        or env.import_path
        or not env.delete
        or env.mounts
        or env.extra_docker_compose
        or env.env
        or env.kwargs
    ):
        raise ValueError("Docker requires cleanup and no runtime mounts/compose/env/kwargs")
    if (
        agent.skills
        or agent.mcp_servers
        or agent.env
        or agent.include_logs
        or agent.exclude_logs
        or config.extra_instruction_paths
        or config.artifacts
    ):
        raise ValueError("Runtime skill/MCP/env/log/artifact/instruction overrides are not supported")
    if agent.import_path == _DSH_IMPORT and agent.name is None:
        if set(agent.kwargs) - _DSH_KWARGS:
            raise ValueError("Unsupported DSH bridge kwargs")
    elif agent.import_path or agent.name not in {"oracle", "nop"} or agent.kwargs:
        raise ValueError("Only the DSH bridge or builtin oracle/nop is supported")
    if verifier.disable or verifier.import_path or verifier.kwargs or verifier.env:
        raise ValueError("The native independent verifier must remain enabled and unmodified")
    if verifier.include_logs or verifier.exclude_logs:
        raise ValueError("Verifier evidence must not be filtered")
    return task_dir


def _validate_task(task: Task) -> None:
    config = task.config
    if task.has_steps:
        raise ValueError("Only single-step tasks are supported")
    if resolve_task_verifier_mode(config) != VerifierEnvironmentMode.SEPARATE or config.verifier.environment is None:
        raise ValueError("An explicit separate verifier environment is required")
    if config.artifacts != ["/app/answer.txt"]:
        raise ValueError("This lane only transfers the explicit /app/answer.txt artifact")
    for env in (config.environment, config.verifier.environment):
        if env.os != "linux" or env.skills_dir or env.mcp_servers or env.env:
            raise ValueError("Task environments require Linux without skill/MCP/env injection")
    if config.verifier.env:
        raise ValueError("Task verifier env injection is not supported")


class IsolatedDshTrial(SingleStepTrial):
    def __init__(self, config: TrialConfig, *, allowed_task_dir: Path):
        # Upstream retains config by reference; isolate it from caller mutations.
        snapshot = config.model_copy(deep=True)
        task_dir = _validate_runtime(snapshot, allowed_task_dir)
        task = Task(task_dir=task_dir)
        _validate_task(task)
        self._artifact_collection_failed = False
        super().__init__(snapshot, _task=task)

    def _init_artifact_handler(self) -> None:
        self._validate_artifact_configuration()
        self._artifact_handler = _BoundedAnswerArtifacts(
            artifacts=self.task.config.artifacts,
            logger=self.logger,
        )

    async def _collect_artifacts(self, *, stop_main_before_sidecars: bool = False) -> None:
        if self._artifact_collection_failed:
            # Trial.run invokes recovery after exceptions/cancellation. Do not
            # re-read a rejected path or turn infrastructure failure into 0/1.
            return
        try:
            await super()._collect_artifacts(stop_main_before_sidecars=stop_main_before_sidecars)
        except BaseException:
            self._artifact_collection_failed = True
            raise

    @property
    def _agent_env_mounts(self) -> list[ServiceVolumeConfig]:
        return []

    async def _setup_agent(self) -> None:
        # Oracle redirects stdout here; upstream used a bind mount to create it.
        # This is a container-local directory, never a restored host mount.
        result = await asyncio.wait_for(
            self.agent_environment.exec(command="mkdir -p -- /logs/agent", timeout_sec=30, user="root"),
            timeout=30,
        )
        if result.return_code != 0:
            raise RuntimeError("Failed to create the isolated agent log directory")
        await super()._setup_agent()

    @classmethod
    async def create(cls, config: TrialConfig, *, allowed_task_dir: Path) -> IsolatedDshTrial:
        # Trial.create hardcodes SingleStepTrial; never delegate to that factory.
        return cls(config, allowed_task_dir=allowed_task_dir)


def create_isolated_trial(config: TrialConfig, *, allowed_task_dir: Path) -> IsolatedDshTrial:
    """Construct the local trial without downloading tasks or starting resources."""
    return IsolatedDshTrial(config, allowed_task_dir=allowed_task_dir)
