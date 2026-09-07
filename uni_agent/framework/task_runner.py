# ruff: noqa: E501
"""Agent runner that bridges the framework's gateway sessions to uni_agent tasks."""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from uni_agent.rlinsight_adapter import task_span
from uni_agent.tasks import TaskConfigResolver, TaskResult, get_task
from uni_agent.tasks.base import build_reward_info
from uni_agent.tasks.config import _deep_merge

if TYPE_CHECKING:
    from uni_agent.gateway.session import SessionHandle

logger = logging.getLogger(__name__)


def _rewrite_gateway_url(gateway_url: str, proxy_port: int) -> str:
    """Rewrite a gateway URL to the sandbox-internal tunnel (``127.0.0.1:<proxy_port>``).

    Replaces host:port with ``127.0.0.1:<proxy_port>`` and keeps the path, so an
    in-sandbox endpoint reaches the gateway through the reverse tunnel. Example:
    ``http://gateway.example:40169/sessions/abc/v1`` ->
    ``http://127.0.0.1:38197/sessions/abc/v1``.
    """
    return f"http://127.0.0.1:{proxy_port}{urlparse(gateway_url).path}"


def _extract_upstream(gateway_url: str) -> str | None:
    """Extract ``host:port`` from a gateway URL (the tunnel's ``upstream``).

    Returns ``None`` when the URL carries no host or port, so callers can fail
    loudly instead of forwarding a ``None:None`` upstream.
    """
    parsed = urlparse(gateway_url)
    if not parsed.hostname or not parsed.port:
        return None
    return f"{parsed.hostname}:{parsed.port}"


def _inject_gateway_tunnel(task: dict[str, Any], base_url: str) -> dict[str, Any]:
    """Fill the runtime side of an openyuanrong gateway reverse tunnel.

    The sandbox config declares its tunnel port via ``sandbox_kwargs.proxy_port``;
    only the runtime-derived pieces are injected here: ``upstream`` (the gateway
    host:port, so the provider knows where to forward the tunnel) and the agent's
    ``model.base_url`` rewritten to the sandbox-internal tunnel address. The agent
    itself stays tunnel-agnostic -- it just sees a base_url that already points at
    ``127.0.0.1:<proxy_port>``.

    The reverse tunnel is currently supported only on the openyuanrong sandbox;
    configuring ``proxy_port`` on any other provider is rejected loudly instead of
    being silently ignored (which would leave the agent pointed at an unreachable
    ``127.0.0.1`` address).
    """
    provider = (task.get("sandbox") or {}).get("provider")
    if provider != "openyuanrong":
        raise ValueError(
            "the gateway reverse tunnel (sandbox.sandbox_kwargs.proxy_port) is currently "
            f"supported only on 'openyuanrong' sandboxes, got provider={provider!r}; "
            "switch the sandbox provider or drop proxy_port"
        )
    upstream = _extract_upstream(base_url)
    if upstream is None:
        raise ValueError(f"cannot derive gateway tunnel upstream from base_url={base_url!r}")
    proxy_port = task["sandbox"]["sandbox_kwargs"]["proxy_port"]
    return _deep_merge(
        task,
        {
            "sandbox": {"sandbox_kwargs": {"upstream": upstream}},
            "agent": {"model": {"base_url": _rewrite_gateway_url(base_url, proxy_port)}},
        },
    )


def _inject_dsh_artifact_roots(
    task: dict[str, Any],
    *,
    trace_root: str | None,
    result_root: str | None,
) -> dict[str, Any]:
    """Bind one DSH run to operator-owned persistent evidence directories."""
    if trace_root is None and result_root is None:
        return task
    if task.get("name") != "dsh_architecture":
        raise ValueError("DSH artifact roots are supported only for dsh_architecture tasks")
    if trace_root is None or result_root is None:
        raise ValueError("dsh_trace_root and dsh_result_root must be configured together")
    for name, value in (("dsh_trace_root", trace_root), ("dsh_result_root", result_root)):
        if not isinstance(value, str):
            raise ValueError(f"{name} must be an absolute traversal-free path")
        path = PurePosixPath(value)
        if not value.strip() or not path.is_absolute() or ".." in path.parts:
            raise ValueError(f"{name} must be an absolute traversal-free path")
    return _deep_merge(
        task,
        {
            "agent": {"artifact_root": trace_root},
            "result_root": result_root,
        },
    )


def _validate_dsh_episode_files(files: object) -> list[dict[str, str]]:
    """Validate the operator's explicit small-file copy list, never a directory tree."""
    if not isinstance(files, list) or not files:
        raise ValueError("dsh_episode_files must be a non-empty file list")
    paths: set[str] = set()
    for entry in files:
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256"}:
            raise ValueError("DSH episode file entry must contain only path and sha256")
        name = entry["path"]
        if not isinstance(name, str) or not name:
            raise ValueError("DSH episode file path must be non-empty")
        path = PurePosixPath(name)
        if (
            not path.parts
            or path.is_absolute()
            or ".." in path.parts
            or path.as_posix() != name
            or any(part.startswith(".") for part in path.parts)
            or path.parts[0] == "verl"
            or name in paths
        ):
            raise ValueError("DSH episode file path must be unique, relative and exclude hidden trees/verl")
        if not isinstance(entry["sha256"], str) or re.fullmatch(r"sha256:[0-9a-f]{64}", entry["sha256"]) is None:
            raise ValueError("DSH episode file sha256 must be a lowercase SHA256 digest")
        paths.add(name)
    return [dict(entry) for entry in files]


def _dsh_episode_path(value: str) -> Path:
    if not isinstance(value, str) or not value or not Path(value).is_absolute() or ".." in Path(value).parts:
        raise ValueError("DSH episode paths must be absolute and traversal-free")
    path = Path(value)
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        raise ValueError("DSH episode paths must not contain symlinks")
    return path


def _read_dsh_episode_files(root: str, files: list[dict[str, str]]) -> list[tuple[str, bytes]]:
    directory = _dsh_episode_path(root)
    contents = []
    for entry in files:
        path = _dsh_episode_path(str(directory / entry["path"]))
        if not path.is_file():
            raise ValueError(f"DSH episode input file is missing: {entry['path']}")
        data = path.read_bytes()
        if "sha256:" + hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise ValueError(f"DSH episode input digest mismatch: {entry['path']}")
        contents.append((entry["path"], data))
    return contents


def _verify_dsh_episode_files(workdir: str, source_root: str, files: list[dict[str, str]]) -> None:
    """Detect persistent input changes; this is not containment against same-UID code."""
    _read_dsh_episode_files(source_root, files)
    _read_dsh_episode_files(workdir, files)


def _prepare_dsh_episode_workdir(
    task: dict[str, Any],
    *,
    session: SessionHandle,
    workdir_root: str | None,
    source_root: str | None,
    files: list[dict[str, str]] | None,
) -> dict[str, Any]:
    if workdir_root is None and source_root is None and files is None:
        return task
    if workdir_root is None or source_root is None or files is None:
        raise ValueError("DSH episode workdir root, source root and files must be configured together")
    if task.get("name") != "dsh_architecture" or (task.get("sandbox") or {}).get("provider") != "local":
        raise ValueError("DSH episode workdirs require a local dsh_architecture task")
    from uni_agent.agents.dsh.agent import extract_gateway_session_id

    if not session.base_url or extract_gateway_session_id(session.base_url) != session.session_id:
        raise ValueError("DSH episode Gateway session identity does not match its URL")
    files = _validate_dsh_episode_files(files)
    root = _dsh_episode_path(workdir_root)
    contents = _read_dsh_episode_files(source_root, files)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    workspace = root / session.session_id
    workspace.mkdir(mode=0o700)  # Session replay must never reuse a previous task directory.
    for name, data in contents:
        target = workspace / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as output:
            output.write(data)
        target.chmod(0o600)
    return _deep_merge(task, {"workdir": str(workspace), "agent": {"default_workdir": str(workspace)}})


async def run_task(
    *,
    session: SessionHandle,
    tools_kwargs: dict[str, Any] | None = None,
    raw_prompt: Any = None,
    sample_index: int | None = None,
    task_config_path: str | None = None,
    api_key: str = "EMPTY",
    model_name: str | None = None,
    report_reward: bool = False,
    require_reward_post: bool = False,
    dsh_trace_root: str | None = None,
    dsh_result_root: str | None = None,
    dsh_episode_workdir_root: str | None = None,
    dsh_episode_source_root: str | None = None,
    dsh_episode_files: list[dict[str, str]] | None = None,
    **_: Any,
) -> TaskResult:
    """Resolve the sample's task, run it against ``session``, and return its result.

    Satisfies the framework's ``AgentRunner`` contract (``session`` / ``raw_prompt``
    / ``sample_index`` / ``tools_kwargs``). The framework's ``raw_prompt`` contains
    the authoritative dataset/source messages and overrides any serialized Task prompt.

    Run-level defaults come from the per-task-name YAML file selected by
    ``task_config_path``. ``TaskConfigResolver`` applies that Task Config, the
    sample values, and the live endpoint in order. When ``report_reward`` is set,
    the task's reward + info are POSTed back to the session's reward-info endpoint;
    the standalone evaluator reads the returned :class:`TaskResult` directly. ``require_reward_post`` makes that
    delivery an episode precondition and raises when the endpoint is absent or the POST is not acknowledged.
    """
    if type(report_reward) is not bool:
        raise ValueError("report_reward must be a bool")
    if type(require_reward_post) is not bool:
        raise ValueError("require_reward_post must be a bool")
    if require_reward_post and not report_reward:
        raise ValueError("require_reward_post requires report_reward=True")
    episode_workdir = any(
        value is not None for value in (dsh_episode_workdir_root, dsh_episode_source_root, dsh_episode_files)
    )
    if episode_workdir and not require_reward_post:
        raise ValueError("DSH episode workdirs require acknowledged reward reporting")

    sample_config = tools_kwargs.get("task") if tools_kwargs else None
    if not isinstance(sample_config, dict):
        raise ValueError("run_task requires tools_kwargs['task'] (the serialized Task Config)")
    sample_config = dict(sample_config)
    sample_config["prompt"] = raw_prompt

    resolver = TaskConfigResolver.from_file(task_config_path) if task_config_path else TaskConfigResolver()
    task = resolver.resolve(
        sample_config,
        runtime_model={
            "base_url": session.base_url,
            "api_key": api_key,
            "model_name": model_name,
        },
    )
    task = _inject_dsh_artifact_roots(
        task,
        trace_root=dsh_trace_root,
        result_root=dsh_result_root,
    )
    task = _prepare_dsh_episode_workdir(
        task,
        session=session,
        workdir_root=dsh_episode_workdir_root,
        source_root=dsh_episode_source_root,
        files=dsh_episode_files,
    )

    # openyuanrong reverse tunnel: the sandbox config pins the in-sandbox tunnel
    # port (sandbox_kwargs.proxy_port); only the gateway upstream + the agent's
    # base_url rewrite are runtime-derived (session.base_url), so fill them in
    # here when a tunnel is configured. The provider check lives inside
    # _inject_gateway_tunnel (rejected loudly for non-Yuanrong sandboxes).
    tunnel_port = (task.get("sandbox") or {}).get("sandbox_kwargs", {}).get("proxy_port")
    if tunnel_port and session.base_url:
        task = _inject_gateway_tunnel(task, session.base_url)

    task_name = task.get("name")
    logger.info("run_task start: task=%s sample_index=%s", task_name, sample_index)

    prompt = task.get("prompt", [])
    with task_span(tools_kwargs, task_name=task_name, prompt=prompt) as span:
        task_instance = get_task(task)
        try:
            result = await task_instance.run()
        finally:
            if episode_workdir:
                assert dsh_episode_source_root is not None and dsh_episode_files is not None
                _verify_dsh_episode_files(task["workdir"], dsh_episode_source_root, dsh_episode_files)
        reward_posted = False
        if report_reward:
            if session.reward_info_url:
                reward_posted = await _post_reward_info(session.reward_info_url, result)
            elif require_reward_post:
                raise RuntimeError("reward-info endpoint is required but the session did not provide one")
        if require_reward_post and not reward_posted:
            raise RuntimeError("reward acknowledgement was not received from the reward-info endpoint")
        span.record_result(result, reward_posted=reward_posted)
        logger.info(
            "run_task done: task=%s reward=%s acc=%s finished=%s reward_posted=%s",
            task_name,
            result.reward,
            result.accuracy,
            result.finished,
            reward_posted,
        )
        return result


async def _post_reward_info(reward_info_url: str, result: TaskResult) -> bool:
    """Best-effort POST of task reward, accuracy, and Agent completion."""
    import aiohttp

    reward_info = _reward_info_from_result(result)
    try:
        timeout = aiohttp.ClientTimeout(total=None)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(reward_info_url, json={"reward_info": reward_info}) as response:
                response.raise_for_status()
        logger.debug("posted reward_info to %s: %s", reward_info_url, reward_info)
    except Exception as exc:  # noqa: BLE001 - reward-info is best-effort telemetry
        logger.warning("failed to post reward_info to %s: %s: %s", reward_info_url, type(exc).__name__, exc)
        return False
    return True


def _reward_info_from_result(result: TaskResult) -> dict[str, Any]:
    """Build the session reward payload consumed by the trajectory framework."""
    return build_reward_info(result)
