"""Scoped resource evidence for the optional, pinned Harbor Modal backend.

Harbor owns trial ordering; this module independently confirms resource cleanup.
A cleared Harbor environment handle is never evidence of termination.
"""

from __future__ import annotations

import asyncio
import importlib.metadata
import math
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from harbor.environments.modal import ModalEnvironment

_SCOPE: ContextVar[ModalExecutionScope | None] = ContextVar("harbor_modal_execution_scope", default=None)


class ModalCleanupError(RuntimeError):
    """Known or indeterminate Modal resources could not be confirmed terminated."""


@dataclass
class _Resource:
    handle: Any
    session_id: str
    sandbox_id: str
    allocation: asyncio.Task
    returncode: int | None = None


class ModalExecutionScope:
    """Collect both Harbor environments and bound independent cleanup on exit.

    Empty scopes do not confirm that a trial ran. Callers must also check expected
    agent/verifier session identities before admitting a successful result.
    """

    def __init__(self, *, cleanup_timeout: float = 30, poll_interval: float = 0.1):
        for value in (cleanup_timeout, poll_interval):
            if isinstance(value, bool) or not math.isfinite(value) or value <= 0:
                raise ValueError("Modal cleanup bounds must be finite positive numbers")
        self.cleanup_timeout = cleanup_timeout
        self.poll_interval = poll_interval
        self.cleanup_confirmed = False
        self._resources: list[_Resource] = []
        self._allocations: list[asyncio.Task] = []
        self._allocation_failed = False
        self._closed = False
        self._token = None

    @property
    def evidence(self) -> tuple[dict[str, object], ...]:
        return tuple(
            {"sandbox_id": resource.sandbox_id, "session_id": resource.session_id, "returncode": resource.returncode}
            for resource in self._resources
        )

    async def __aenter__(self):
        if self._closed or self._token is not None or _SCOPE.get() is not None:
            raise RuntimeError("Modal scope cannot be reused or nested")
        self._token = _SCOPE.set(self)
        return self

    async def _allocate(self, environment, create, kwargs):
        try:
            sandbox = await create(**kwargs)
            resource = _Resource(sandbox, environment.session_id, sandbox.object_id, asyncio.current_task())
            self._resources.append(resource)
            if not isinstance(resource.sandbox_id, str) or not resource.sandbox_id:
                raise ValueError("Modal sandbox has no resource identity")
            if sum(item.sandbox_id == resource.sandbox_id for item in self._resources) != 1:
                raise ValueError("Duplicate Modal resource identity")
            return sandbox
        except BaseException:
            # A failed create can be a lost acknowledgement after allocation.
            self._allocation_failed = True
            raise

    async def create(self, environment, create, kwargs):
        if self._closed:
            raise RuntimeError("Modal execution scope is closed")
        task = asyncio.create_task(self._allocate(environment, create, kwargs))
        self._allocations.append(task)
        return await asyncio.shield(task)

    async def _terminate(self, resource: _Resource):
        await resource.handle.terminate.aio()
        while True:
            code = await resource.handle.poll.aio()
            if type(code) is int:
                resource.returncode = code
                return
            if code is not None:
                raise ModalCleanupError("Modal poll returned an invalid status")
            await asyncio.sleep(self.poll_interval)

    async def _cleanup_allocation(self, allocation):
        try:
            await allocation
        except asyncio.CancelledError:
            if asyncio.current_task().cancelling():
                raise
        except Exception:
            # Preserve any handle already recorded before a validation failure.
            pass
        for resource in self._resources:
            if resource.allocation is allocation:
                await self._terminate(resource)

    async def _cleanup(self):
        try:
            async with asyncio.timeout(self.cleanup_timeout):
                results = await asyncio.gather(
                    *(self._cleanup_allocation(allocation) for allocation in self._allocations), return_exceptions=True
                )
                if self._allocation_failed or any(isinstance(result, BaseException) for result in results):
                    raise ModalCleanupError("Modal creation or independent termination was not confirmed")
                self.cleanup_confirmed = bool(self._resources)
        except TimeoutError as error:
            raise ModalCleanupError("Modal independent cleanup timed out") from error

    async def __aexit__(self, exc_type, exc, tb):
        self._closed = True
        _SCOPE.reset(self._token)
        cleanup = asyncio.create_task(self._cleanup())
        interrupted = False
        while True:
            try:
                await asyncio.shield(cleanup)
                break
            except asyncio.CancelledError:
                interrupted = True
                if cleanup.done():
                    cleanup.result()
                    break
        if interrupted:
            raise asyncio.CancelledError
        return False


class TrackedModalEnvironment(ModalEnvironment):
    """Fixed Harbor EnvironmentFactory seam; only usable inside an owned scope."""

    async def _create_sandbox(self, *, entrypoint=None, block_network=None, experimental_options=None):
        scope = _SCOPE.get()
        if scope is None or scope._closed:
            raise RuntimeError("TrackedModalEnvironment requires an active Modal execution scope")
        if importlib.metadata.version("harbor") != "0.16.1":
            raise ValueError("TrackedModalEnvironment requires Harbor 0.16.1")
        return await scope.create(
            self,
            super()._create_sandbox,
            dict(entrypoint=entrypoint, block_network=block_network, experimental_options=experimental_options),
        )
