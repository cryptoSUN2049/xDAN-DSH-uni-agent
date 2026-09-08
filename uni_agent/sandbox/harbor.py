"""Borrow Harbor's existing Linux environment without owning its lifecycle.

This is a SandboxBackend, not a registered Sandbox provider. Harbor Trial must
create and dispose the environment; the adapter only translates data-plane calls.
Harbor is an optional dependency and is imported only for type checking.
"""

from __future__ import annotations

import asyncio
import math
import shlex
import tempfile
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from .base import ExecResult

if TYPE_CHECKING:
    from harbor.environments.base import BaseEnvironment


class BorrowedHarborSandbox:
    """Data-plane view of an already-running Harbor 0.16.1 Linux environment."""

    def __init__(self, environment: BaseEnvironment) -> None:
        if environment.os != "linux":
            raise ValueError("BorrowedHarborSandbox requires a Linux Harbor environment")
        self._environment = environment

    async def exec(
        self,
        argv: list[str],
        *,
        timeout: float | None = None,
        workdir: str | None = None,
        env: dict[str, str] | None = None,
    ) -> ExecResult:
        """Quote argv for Harbor's POSIX command string, preserving argument bytes.

        Harbor accepts integer seconds. Round its timeout up, while enforcing the
        caller's exact deadline around the call. Cancellation/transport failures
        propagate; only timeouts become the existing DshAgent exit-code sentinel.
        Harbor remains responsible for remote process cleanup after cancellation.
        """
        if not argv:
            raise ValueError("argv must not be empty")
        if timeout is not None and (not math.isfinite(timeout) or timeout <= 0):
            raise ValueError("timeout must be finite and positive")
        try:
            result = await asyncio.wait_for(
                self._environment.exec(
                    command=shlex.join(argv),
                    cwd=workdir,
                    env=None if env is None else dict(env),
                    timeout_sec=None if timeout is None else math.ceil(timeout),
                ),
                timeout=timeout,
            )
        except TimeoutError:
            return ExecResult(exit_code=-1, stdout="", stderr=f"Harbor exec timed out after {timeout}s")
        return ExecResult(exit_code=result.return_code, stdout=result.stdout or "", stderr=result.stderr or "")

    async def exec_shell(
        self,
        script: str,
        *,
        timeout: float | None = None,
        workdir: str | None = None,
        env: dict[str, str] | None = None,
    ) -> ExecResult:
        return await self.exec(["bash", "-c", script], timeout=timeout, workdir=workdir, env=env)

    async def _prepare_remote_parent(self, path: str) -> None:
        result = await self.exec(["mkdir", "-p", "--", str(PurePosixPath(path).parent)])
        if result.exit_code != 0:
            raise RuntimeError(f"Harbor file parent creation failed: {result.stderr or result.stdout}")

    async def read_file(self, path: str) -> bytes:
        # Private local files avoid binary data passing through text-only exec.
        # The context also removes partial downloads on failure/cancellation.
        with tempfile.TemporaryDirectory(prefix="uni-agent-harbor-") as directory:
            local = Path(directory) / "content"
            await self._environment.download_file(path, local)
            return local.read_bytes()

    async def write_file(self, path: str, content: bytes | str) -> None:
        with tempfile.TemporaryDirectory(prefix="uni-agent-harbor-") as directory:
            local = Path(directory) / "content"
            local.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
            await self.upload_file(local, path)

    async def upload_file(self, local_file: Path | str, remote_file: str) -> None:
        await self._prepare_remote_parent(remote_file)
        await self._environment.upload_file(local_file, remote_file)

    async def download_file(self, remote_file: str, local_file: Path | str) -> None:
        Path(local_file).parent.mkdir(parents=True, exist_ok=True)
        await self._environment.download_file(remote_file, local_file)

    async def upload(self, local_path: Path | str, remote_path: str) -> None:
        if Path(local_path).is_dir():
            await self._prepare_remote_parent(remote_path)
            await self._environment.upload_dir(local_path, remote_path)
        else:
            await self.upload_file(local_path, remote_path)

    async def download(self, remote_path: str, local_path: Path | str) -> None:
        Path(local_path).parent.mkdir(parents=True, exist_ok=True)
        if await self._environment.is_dir(remote_path):
            await self._environment.download_dir(remote_path, local_path)
        else:
            await self.download_file(remote_path, local_path)

    async def expose_port(self, port: int) -> str:
        raise NotImplementedError("Port routing must be configured by the Harbor environment owner")
