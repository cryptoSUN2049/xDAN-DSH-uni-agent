from __future__ import annotations

import asyncio
import json
import os
import shlex
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from uni_agent.sandbox.base import Sandbox, SandboxBackend
from uni_agent.sandbox.harbor import BorrowedHarborSandbox
from uni_agent.sandbox.registry import SANDBOX_MODULES


class FakeEnvironment:
    os = "linux"

    def __init__(self):
        self.calls = []
        self.files = {}
        self.transfer_paths = []
        self.failure = None

    async def exec(self, command, cwd=None, env=None, timeout_sec=None):
        self.calls.append((command, cwd, env, timeout_sec))
        return SimpleNamespace(return_code=0, stdout=None, stderr=None)

    async def upload_file(self, source_path, target_path):
        self.transfer_paths.append(Path(source_path))
        if self.failure:
            raise self.failure
        self.files[target_path] = Path(source_path).read_bytes()

    async def download_file(self, source_path, target_path):
        self.transfer_paths.append(Path(target_path))
        Path(target_path).write_bytes(b"partial")
        if self.failure:
            raise self.failure
        Path(target_path).write_bytes(self.files[source_path])


pytestmark = [pytest.mark.cpu, pytest.mark.level0]


def test_borrow_has_no_lifecycle_or_provider_registration():
    adapter = BorrowedHarborSandbox(FakeEnvironment())
    assert isinstance(adapter, SandboxBackend)
    assert not isinstance(adapter, Sandbox)
    for name in ("start", "stop", "__aenter__", "__aexit__"):
        assert not hasattr(adapter, name)
    assert "harbor" not in SANDBOX_MODULES


def test_windows_environment_rejected():
    environment = FakeEnvironment()
    environment.os = "windows"
    with pytest.raises(ValueError, match="Linux"):
        BorrowedHarborSandbox(environment)


@pytest.mark.asyncio
async def test_exec_preserves_argv_and_environment_without_shell_expansion(tmp_path):
    class ShellEnvironment(FakeEnvironment):
        async def exec(self, command, cwd=None, env=None, timeout_sec=None):
            await super().exec(command, cwd, env, timeout_sec)
            process = await asyncio.create_subprocess_exec(
                "sh",
                "-c",
                command,
                cwd=cwd,
                env={**os.environ, **(env or {})},
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()
            return SimpleNamespace(return_code=process.returncode, stdout=stdout.decode(), stderr=stderr.decode())

    environment = ShellEnvironment()
    adapter = BorrowedHarborSandbox(environment)
    args = ["", "two words", "'quoted'", "$(touch injected)", "`touch injected`", "line\nbreak", "中文"]
    program = "import json,os,sys;print(json.dumps([sys.argv[1:],os.environ['VALUE'],os.getcwd()]))"
    result = await adapter.exec(
        [sys.executable, "-c", program, *args], workdir=str(tmp_path), env={"VALUE": "$literal"}, timeout=2.5
    )
    assert result.exit_code == 0
    assert json.loads(result.stdout) == [args, "$literal", str(tmp_path)]
    assert not (tmp_path / "injected").exists()
    assert environment.calls[0][3] == 3  # Harbor's integer seconds; outer deadline retains 2.5.


@pytest.mark.asyncio
async def test_exec_maps_nonzero_and_nullable_output():
    environment = FakeEnvironment()

    async def fail(**kwargs):
        return SimpleNamespace(return_code=23, stdout=None, stderr="failed")

    environment.exec = fail
    result = await BorrowedHarborSandbox(environment).exec(["false"])
    assert (result.exit_code, result.stdout, result.stderr) == (23, "", "failed")


@pytest.mark.asyncio
async def test_fractional_timeout_cancels_call_and_maps_to_minus_one():
    environment = FakeEnvironment()
    cancelled = asyncio.Event()

    async def slow(**kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    environment.exec = slow
    result = await BorrowedHarborSandbox(environment).exec(["sleep", "5"], timeout=0.01)
    assert result.exit_code == -1
    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_infrastructure_error_propagates():
    environment = FakeEnvironment()

    async def broken(**kwargs):
        raise ConnectionError("environment disconnected")

    environment.exec = broken
    with pytest.raises(ConnectionError):
        await BorrowedHarborSandbox(environment).exec(["true"])


@pytest.mark.asyncio
async def test_exec_shell_is_explicit_bash():
    environment = FakeEnvironment()
    await BorrowedHarborSandbox(environment).exec_shell("printf '%s' hello", workdir="/task")
    assert shlex.split(environment.calls[0][0]) == ["bash", "-c", "printf '%s' hello"]
    assert environment.calls[0][1:] == ("/task", None, None)


@pytest.mark.parametrize("content", [b"\x00\xff\r\n", "你好\n", b""])
@pytest.mark.asyncio
async def test_file_roundtrip_preserves_bytes_and_removes_temporaries(content):
    environment = FakeEnvironment()
    adapter = BorrowedHarborSandbox(environment)
    path = "/a dir/$(not-a-command)/file.bin"
    await adapter.write_file(path, content)
    expected = content.encode() if isinstance(content, str) else content
    assert await adapter.read_file(path) == expected
    assert shlex.split(environment.calls[0][0]) == ["mkdir", "-p", "--", "/a dir/$(not-a-command)"]
    assert environment.transfer_paths
    assert all(not path.exists() and not path.parent.exists() for path in environment.transfer_paths)


@pytest.mark.parametrize("operation", ["read", "write"])
@pytest.mark.parametrize("failure", [RuntimeError("transfer failed"), asyncio.CancelledError()])
@pytest.mark.asyncio
async def test_transfer_failure_and_cancellation_remove_temporaries(operation, failure):
    environment = FakeEnvironment()
    environment.failure = failure
    adapter = BorrowedHarborSandbox(environment)
    with pytest.raises(type(failure)):
        if operation == "write":
            await adapter.write_file("/task/file", b"secret")
        else:
            await adapter.read_file("/task/file")
    assert all(not path.exists() and not path.parent.exists() for path in environment.transfer_paths)


@pytest.mark.asyncio
async def test_expose_port_requires_owner_configuration():
    with pytest.raises(NotImplementedError, match="Harbor"):
        await BorrowedHarborSandbox(FakeEnvironment()).expose_port(8000)


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
@pytest.mark.asyncio
async def test_invalid_timeout_rejected(timeout):
    with pytest.raises(ValueError, match="timeout"):
        await BorrowedHarborSandbox(FakeEnvironment()).exec(["true"], timeout=timeout)


@pytest.mark.asyncio
async def test_empty_argv_rejected():
    with pytest.raises(ValueError, match="argv"):
        await BorrowedHarborSandbox(FakeEnvironment()).exec([])


@pytest.mark.asyncio
async def test_parent_creation_failure_prevents_upload():
    environment = FakeEnvironment()

    async def denied(**kwargs):
        return SimpleNamespace(return_code=1, stdout=None, stderr="permission denied")

    environment.exec = denied
    with pytest.raises(RuntimeError, match="permission denied"):
        await BorrowedHarborSandbox(environment).write_file("/protected/content", b"data")
    assert environment.transfer_paths == []


@pytest.mark.asyncio
async def test_upload_download_files_use_native_transfer(tmp_path):
    environment = FakeEnvironment()

    async def is_dir(path):
        return False

    environment.is_dir = is_dir
    adapter = BorrowedHarborSandbox(environment)
    source = tmp_path / "source.bin"
    source.write_bytes(b"\x00\xffbinary")
    await adapter.upload(source, "/task/input.bin")
    target = tmp_path / "new-parent" / "download.bin"
    await adapter.download("/task/input.bin", target)
    assert target.read_bytes() == source.read_bytes()
    assert source.exists()  # Caller-owned files are not temporary adapter files.


@pytest.mark.asyncio
async def test_directory_transfer_delegates_to_harbor(tmp_path):
    environment = FakeEnvironment()
    transfers = []

    async def upload_dir(source, target):
        transfers.append(("upload", source, target))

    async def download_dir(source, target):
        transfers.append(("download", source, target))

    async def is_dir(path):
        return True

    environment.upload_dir = upload_dir
    environment.download_dir = download_dir
    environment.is_dir = is_dir
    adapter = BorrowedHarborSandbox(environment)
    source = tmp_path / "source"
    source.mkdir()
    target = tmp_path / "new-parent" / "output"
    await adapter.upload(source, "/task/input")
    await adapter.download("/task/input", target)
    assert transfers == [("upload", source, "/task/input"), ("download", "/task/input", target)]
    assert target.parent.is_dir()
