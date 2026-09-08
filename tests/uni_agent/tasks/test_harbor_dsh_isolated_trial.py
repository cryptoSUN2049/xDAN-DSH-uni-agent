import asyncio
import io
import json
import os
import sys
import tarfile
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("harbor.trial.single_step")
from harbor.models.trial.config import TrialConfig
from harbor.trial.single_step import SingleStepTrial

from uni_agent.tasks.harbor_dsh import isolated_trial
from uni_agent.tasks.harbor_dsh.isolated_trial import IsolatedDshTrial, create_isolated_trial

pytestmark = [pytest.mark.cpu, pytest.mark.level0]


@pytest.fixture
def task_dir(tmp_path):
    task = tmp_path / "task"
    for directory in ("environment", "tests", "solution"):
        (task / directory).mkdir(parents=True)
    (task / "instruction.md").write_text("Write the answer to /app/answer.txt")
    (task / "task.toml").write_text(
        'schema_version = "1.3"\nartifacts = ["/app/answer.txt"]\n'
        '[environment]\nworkdir = "/app"\n'
        '[verifier]\nenvironment_mode = "separate"\n'
        '[verifier.environment]\nworkdir = "/app"\n'
    )
    (task / "environment/Dockerfile").write_text("FROM scratch\n")
    (task / "tests/Dockerfile").write_text("FROM scratch\nCOPY test.sh /tests/test.sh\n")
    (task / "tests/test.sh").write_text("#!/bin/sh\nexit 0\n")
    (task / "solution/solve.sh").write_text("#!/bin/sh\nexit 0\n")
    return task


def config(task_dir, **overrides):
    values = {
        "task": {"path": str(task_dir)},
        "trial_name": "isolated-1",
        "trials_dir": str(task_dir.parent / "private-trials"),
        "agent": {"name": "oracle"},
        "environment": {"type": "docker", "delete": True},
    }
    values.update(overrides)
    return TrialConfig.model_validate(values)


def close(trial):
    # Construction opens the host log handler, but never starts containers.
    trial._close_logger_handler()


def test_real_factory_preserves_subclass_and_only_verifier_has_host_mount(task_dir):
    trial = create_isolated_trial(config(task_dir), allowed_task_dir=task_dir)
    try:
        assert type(trial) is IsolatedDshTrial
        assert isinstance(trial, SingleStepTrial)
        assert trial._agent_env_mounts == []
        assert trial.agent_environment._mounts == []
        mounts = trial._verifier_env_mounts(trial.task.config.verifier.environment)
        assert len(mounts) == 1
        assert mounts[0]["source"] == str(trial.paths.verifier_dir.resolve())
        assert mounts[0]["target"] == "/logs/verifier"
    finally:
        close(trial)


def test_async_create_does_not_use_upstream_hardcoded_factory(task_dir):
    trial = asyncio.run(IsolatedDshTrial.create(config(task_dir), allowed_task_dir=task_dir))
    try:
        assert type(trial) is IsolatedDshTrial
    finally:
        close(trial)


@pytest.mark.parametrize(
    "override",
    [
        {"environment": {"mounts": [{"type": "bind", "source": "/tmp", "target": "/host"}]}},
        {"environment": {"extra_docker_compose": ["/tmp/extra.yaml"]}},
        {"environment": {"kwargs": {"mounts": []}}},
        {"environment": {"env": {"SECRET": "value"}}},
        {"environment": {"delete": False}},
        {"environment": {"type": "modal"}},
        {"environment": {"import_path": "custom:Environment"}},
        {"agent": {"name": "oracle", "skills": ["/tmp/skills"]}},
        {"agent": {"name": "oracle", "env": {"SECRET": "value"}}},
        {"agent": {"name": "oracle", "kwargs": {"extra_env": {"SECRET": "value"}}}},
        {"agent": {"name": "oracle", "include_logs": ["*.json"]}},
        {"agent": {"import_path": "custom:Agent"}},
        {"verifier": {"disable": True}},
        {"verifier": {"env": {"SECRET": "value"}}},
        {"verifier": {"kwargs": {"anything": True}}},
        {"verifier": {"import_path": "custom:Verifier"}},
        {"verifier": {"exclude_logs": ["*"]}},
        {"artifacts": ["/etc/passwd"]},
        {"extra_instruction_paths": ["/tmp/extra.md"]},
        {"trial_name": "../escape"},
        {"task": {"path": "relative", "git_url": "https://example.com/repo"}},
    ],
)
def test_rejects_unsafe_runtime_overrides_before_creating_logs(task_dir, override):
    with pytest.raises(ValueError):
        create_isolated_trial(config(task_dir, **override), allowed_task_dir=task_dir)
    assert not (task_dir.parent / "private-trials").exists()


@pytest.mark.parametrize(
    "text",
    [
        'schema_version="1.3"\n[verifier]\nenvironment_mode="shared"\n',
        'schema_version="1.3"\n[verifier]\nenvironment_mode="separate"\n',
        'schema_version="1.3"\n[environment]\nskills_dir="/skills"\n'
        '[verifier]\nenvironment_mode="separate"\n[verifier.environment]\n',
        'schema_version="1.3"\n[environment]\nenv={SECRET="value"}\n'
        '[verifier]\nenvironment_mode="separate"\n[verifier.environment]\n',
    ],
)
def test_requires_explicit_clean_separate_verifier(task_dir, text):
    (task_dir / "task.toml").write_text(text)
    with pytest.raises(ValueError):
        create_isolated_trial(config(task_dir), allowed_task_dir=task_dir)


def test_allowlist_is_external_and_exact(task_dir):
    with pytest.raises(ValueError, match="allowlist"):
        create_isolated_trial(config(task_dir), allowed_task_dir=task_dir.parent)


def test_version_drift_fails_closed(task_dir, monkeypatch):
    monkeypatch.setattr(isolated_trial.importlib.metadata, "version", lambda name: "0.16.2")
    with pytest.raises(ValueError, match="0.16.1"):
        create_isolated_trial(config(task_dir), allowed_task_dir=task_dir)


def test_configuration_is_snapshotted_before_upstream_keeps_it(task_dir):
    original = config(task_dir)
    trial = create_isolated_trial(original, allowed_task_dir=task_dir)
    try:
        original.environment.env["NEW"] = "value"
        assert trial.config.environment.env == {}
    finally:
        close(trial)


def test_real_dsh_bridge_constructs_without_model_or_container_calls(task_dir):
    trial = create_isolated_trial(
        config(
            task_dir,
            agent={
                "import_path": "uni_agent.agents.dsh.harbor_agent:DshHarborAgent",
                "model_name": "student-4b",
                "kwargs": {"gateway_base_url": "http://127.0.0.1:12345/sessions/test-1/v1"},
            },
        ),
        allowed_task_dir=task_dir,
    )
    try:
        assert trial.agent.name() == "uni-agent-dsh"
        assert trial._agent_env_mounts == []
        assert not (trial.paths.agent_dir / "dsh").exists()
    finally:
        close(trial)


@pytest.mark.parametrize("key", ["skills_dir", "extra_env", "mcp_servers", "unknown"])
def test_dsh_kwargs_cannot_bypass_injection_guards(task_dir, key):
    with pytest.raises(ValueError, match="kwargs"):
        create_isolated_trial(
            config(
                task_dir,
                agent={
                    "import_path": "uni_agent.agents.dsh.harbor_agent:DshHarborAgent",
                    "kwargs": {key: "injected"},
                },
            ),
            allowed_task_dir=task_dir,
        )


@pytest.mark.parametrize("section", ["environment", "verifier.environment"])
@pytest.mark.parametrize("setting", ['skills_dir="/skills"', 'env={SECRET="value"}'])
def test_task_environment_injection_rejected_with_otherwise_valid_task(task_dir, section, setting):
    path = task_dir / "task.toml"
    path.write_text(path.read_text().replace(f"[{section}]", f"[{section}]\n{setting}"))
    with pytest.raises(ValueError, match="injection"):
        create_isolated_trial(config(task_dir), allowed_task_dir=task_dir)


def test_task_verifier_env_cannot_be_injected(task_dir):
    path = task_dir / "task.toml"
    path.write_text(path.read_text().replace("[verifier]", '[verifier]\nenv={SECRET="value"}'))
    with pytest.raises(ValueError, match="injection"):
        create_isolated_trial(config(task_dir), allowed_task_dir=task_dir)


@pytest.mark.parametrize("return_code", [0, 1])
def test_setup_creates_container_log_directory_before_agent_setup(task_dir, monkeypatch, return_code):
    trial = create_isolated_trial(config(task_dir), allowed_task_dir=task_dir)
    calls = []

    async def exec_command(**kwargs):
        calls.append(("mkdir", kwargs))
        return SimpleNamespace(return_code=return_code)

    async def upstream_setup(self):
        calls.append(("setup", self))

    monkeypatch.setattr(trial.agent_environment, "exec", exec_command)
    monkeypatch.setattr(SingleStepTrial, "_setup_agent", upstream_setup)
    try:
        if return_code:
            with pytest.raises(RuntimeError, match="log directory"):
                asyncio.run(trial._setup_agent())
            assert len(calls) == 1
        else:
            asyncio.run(trial._setup_agent())
            assert [call[0] for call in calls] == ["mkdir", "setup"]
        assert calls[0][1] == {"command": "mkdir -p -- /logs/agent", "timeout_sec": 30, "user": "root"}
        assert trial._agent_env_mounts == []
    finally:
        close(trial)


def test_log_directory_transport_failure_does_not_start_agent(task_dir, monkeypatch):
    trial = create_isolated_trial(config(task_dir), allowed_task_dir=task_dir)
    setup = AsyncMock()
    monkeypatch.setattr(trial.agent_environment, "exec", AsyncMock(side_effect=TimeoutError("transport")))
    monkeypatch.setattr(SingleStepTrial, "_setup_agent", setup)
    try:
        with pytest.raises(TimeoutError):
            asyncio.run(trial._setup_agent())
        setup.assert_not_awaited()
    finally:
        close(trial)


def answer_transport(trial, monkeypatch, folder):
    calls = []
    container_id = "a" * 64

    async def archive(argv, **kwargs):
        assert argv == ["docker", "cp", f"{container_id}:/app/answer.txt", "-"]
        calls.append(argv)
        answer = folder / "answer.txt"
        if not answer.exists() and not answer.is_symlink():
            message = (
                f"Error response from daemon: Could not find the file /app/answer.txt in container {container_id}\n"
            )
            return 1, b"", message.encode()
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w", dereference=False) as tar:
            tar.add(answer, arcname="answer.txt")
        return 0, stream.getvalue(), b""

    monkeypatch.setattr(isolated_trial, "_run_bounded_command", archive)
    monkeypatch.setattr(
        trial.agent_environment,
        "_run_docker_compose_command",
        AsyncMock(
            return_value=SimpleNamespace(return_code=0, stdout=container_id + "\n", stderr=""),
        ),
    )
    for name in ("exec", "service_download_file", "service_download_dir", "service_is_dir"):
        monkeypatch.setattr(trial.agent_environment, name, AsyncMock(side_effect=AssertionError("unsafe copy")))
    return calls


@pytest.mark.parametrize("content", [b"", b"\x00\xff\n", b"a" * 4096, None])
def test_bounded_answer_collection_copies_only_snapshot_bytes(task_dir, monkeypatch, content):
    trial = create_isolated_trial(config(task_dir), allowed_task_dir=task_dir)
    folder = task_dir.parent / "agent-app"
    folder.mkdir()
    if content is not None:
        (folder / "answer.txt").write_bytes(content)
    calls = answer_transport(trial, monkeypatch, folder)
    try:
        asyncio.run(trial._collect_artifacts())
        target = trial.paths.artifacts_dir / "app/answer.txt"
        if content is None:
            assert not target.exists()
        else:
            assert target.read_bytes() == content
        manifest = json.loads((trial.paths.artifacts_dir / "manifest.json").read_text())
        answer = next(entry for entry in manifest if entry["source"] == "/app/answer.txt")
        assert answer["status"] == ("empty" if content is None else "ok")
        asyncio.run(trial._collect_artifacts())
        assert len(calls) == 1
    finally:
        close(trial)


@pytest.mark.parametrize("kind", ["symlink", "dangling", "directory", "oversize", "fifo"])
def test_unsafe_answer_is_rejected_and_recovery_cannot_retry_collection(task_dir, monkeypatch, kind):
    trial = create_isolated_trial(config(task_dir), allowed_task_dir=task_dir)
    folder = task_dir.parent / "agent-app"
    folder.mkdir()
    answer = folder / "answer.txt"
    if kind in {"symlink", "dangling"}:
        target = folder / "other"
        if kind == "symlink":
            target.write_text("malicious")
        answer.symlink_to(target)
    elif kind == "directory":
        answer.mkdir()
    elif kind == "oversize":
        answer.write_bytes(b"x" * 4097)
    elif kind == "fifo":
        os.mkfifo(answer)
    calls = answer_transport(trial, monkeypatch, folder)
    trial._init_result()
    monkeypatch.setattr(trial, "_sync_agent_output", AsyncMock())
    stop = AsyncMock()
    monkeypatch.setattr(trial, "_stop_agent_environment", stop)
    try:
        with pytest.raises(RuntimeError, match="answer"):
            asyncio.run(trial._collect_artifacts())
        assert not (trial.paths.artifacts_dir / "app/answer.txt").exists()
        asyncio.run(trial._recover_outputs())
        assert len(calls) == 1
        stop.assert_awaited_once()
    finally:
        close(trial)


@pytest.mark.parametrize("reply", [b"", b"not-a-tar", b"x" * 65537])
def test_malformed_or_oversized_answer_archive_is_rejected(task_dir, monkeypatch, reply):
    trial = create_isolated_trial(config(task_dir), allowed_task_dir=task_dir)
    answer_transport(trial, monkeypatch, task_dir)
    monkeypatch.setattr(isolated_trial, "_run_bounded_command", AsyncMock(return_value=(0, reply, b"")))
    try:
        with pytest.raises(RuntimeError, match="answer"):
            asyncio.run(trial._collect_artifacts())
        assert not (trial.paths.artifacts_dir / "app/answer.txt").exists()
    finally:
        close(trial)


def test_trial_run_records_artifact_error_and_never_scores_or_retries(task_dir, monkeypatch):
    trial = create_isolated_trial(config(task_dir), allowed_task_dir=task_dir)
    folder = task_dir.parent / "agent-app"
    folder.mkdir()
    (folder / "answer.txt").write_bytes(b"x" * 4097)
    calls = answer_transport(trial, monkeypatch, folder)
    for method in ("_prepare", "_run_agent", "_upload_agent_logs", "_sync_agent_output", "_stop_agent_environment"):
        monkeypatch.setattr(trial, method, AsyncMock())
    verifier = AsyncMock()
    monkeypatch.setattr(trial, "_run_verifier", verifier)
    result = asyncio.run(trial.run())
    assert result.exception_info.exception_type == "AnswerArtifactError"
    assert result.exception_info.exception_message == "Rejected unsafe or malformed answer artifact"
    assert result.verifier_result is None
    verifier.assert_not_awaited()
    assert len(calls) == 1
    assert not (trial.paths.artifacts_dir / "app/answer.txt").exists()


@pytest.mark.parametrize("channel", ["stdout", "stderr"])
def test_stream_limit_terminates_and_reaps_real_subprocess(channel, monkeypatch):
    processes = []
    original = asyncio.create_subprocess_exec

    async def spawn(*args, **kwargs):
        process = await original(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    script = f"import sys,time; sys.{channel}.write('x'*100000); sys.{channel}.flush(); time.sleep(30)"
    with pytest.raises(isolated_trial.AnswerArtifactError, match="limit"):
        asyncio.run(isolated_trial._run_bounded_command([sys.executable, "-c", script], timeout=2))
    assert len(processes) == 1
    assert processes[0].returncode is not None


def test_command_timeout_is_bounded():
    with pytest.raises(TimeoutError):
        asyncio.run(
            isolated_trial._run_bounded_command(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                timeout=0.1,
            )
        )


def test_small_command_preserves_binary_output_and_exit_code():
    result = asyncio.run(
        isolated_trial._run_bounded_command(
            [
                sys.executable,
                "-c",
                "import sys; sys.stdout.buffer.write(b'\\x00\\xff'); sys.stderr.write('error'); sys.exit(3)",
            ],
            timeout=2,
        )
    )
    assert result == (3, b"\x00\xff", b"error")


@pytest.mark.parametrize(
    "error", [b"permission denied", b"No such container", b"Could not find the file /app/answer.txt", b""]
)
def test_docker_failure_is_not_assumed_missing(task_dir, monkeypatch, error):
    trial = create_isolated_trial(config(task_dir), allowed_task_dir=task_dir)
    answer_transport(trial, monkeypatch, task_dir)
    monkeypatch.setattr(isolated_trial, "_run_bounded_command", AsyncMock(return_value=(1, b"", error)))
    try:
        with pytest.raises(isolated_trial.AnswerArtifactError):
            asyncio.run(trial._collect_artifacts())
    finally:
        close(trial)


def test_command_cancellation_reaps_child(monkeypatch):
    async def scenario():
        spawned = asyncio.Event()
        processes = []
        original = asyncio.create_subprocess_exec

        async def spawn(*args, **kwargs):
            process = await original(*args, **kwargs)
            processes.append(process)
            spawned.set()
            return process

        monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
        task = asyncio.create_task(
            isolated_trial._run_bounded_command(
                [
                    sys.executable,
                    "-c",
                    "import time; time.sleep(30)",
                ]
            )
        )
        await spawned.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert processes[0].returncode is not None

    asyncio.run(scenario())


@pytest.mark.parametrize("case", ["traversal", "hardlink", "second_file", "trailing_archive", "no_end_markers"])
def test_archive_parser_never_extracts_unapproved_entries(case):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        entry = tarfile.TarInfo("../answer.txt" if case == "traversal" else "answer.txt")
        if case == "hardlink":
            entry.type = tarfile.LNKTYPE
            entry.linkname = "/etc/passwd"
        archive.addfile(entry)
        if case == "second_file":
            archive.addfile(tarfile.TarInfo("other"))
    raw = output.getvalue()
    if case == "trailing_archive":
        raw += raw
    elif case == "no_end_markers":
        raw = raw[:512]
    with pytest.raises(isolated_trial.AnswerArtifactError):
        isolated_trial._answer_from_tar(raw)
