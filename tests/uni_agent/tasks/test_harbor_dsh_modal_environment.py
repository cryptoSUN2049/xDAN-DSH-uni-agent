import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from harbor.environments.modal import ModalEnvironment

from uni_agent.tasks.harbor_dsh.modal_environment import (
    ModalCleanupError,
    ModalExecutionScope,
    TrackedModalEnvironment,
)


def sandbox(identity="sb-agent", polls=(137,), terminate_error=None):
    return SimpleNamespace(
        object_id=identity,
        terminate=SimpleNamespace(aio=AsyncMock(side_effect=terminate_error)),
        poll=SimpleNamespace(aio=AsyncMock(side_effect=list(polls))),
    )


def environment(session="agent"):
    env = object.__new__(TrackedModalEnvironment)
    env.session_id = session
    return env


@pytest.mark.asyncio
async def test_agent_and_verifier_resources_are_independently_confirmed(monkeypatch):
    a, v = sandbox(), sandbox("sb-verifier", (None, 124))
    create = AsyncMock(side_effect=[a, v])
    monkeypatch.setattr(ModalEnvironment, "_create_sandbox", create)
    async with ModalExecutionScope(poll_interval=0.001) as scope:
        await environment()._create_sandbox()
        await environment("verifier")._create_sandbox()
        assert not scope.cleanup_confirmed
    assert scope.cleanup_confirmed
    assert scope.evidence == (
        {"sandbox_id": "sb-agent", "session_id": "agent", "returncode": 137},
        {"sandbox_id": "sb-verifier", "session_id": "verifier", "returncode": 124},
    )
    a.terminate.aio.assert_awaited_once()
    v.terminate.aio.assert_awaited_once()


@pytest.mark.asyncio
async def test_missing_scope_fails_before_creation(monkeypatch):
    create = AsyncMock()
    monkeypatch.setattr(ModalEnvironment, "_create_sandbox", create)
    with pytest.raises(RuntimeError, match="scope"):
        await environment()._create_sandbox()
    create.assert_not_awaited()


@pytest.mark.asyncio
async def test_creation_failure_never_confirms_cleanup(monkeypatch):
    monkeypatch.setattr(ModalEnvironment, "_create_sandbox", AsyncMock(side_effect=RuntimeError("create failed")))
    with pytest.raises(ModalCleanupError):
        async with ModalExecutionScope() as scope:
            await environment()._create_sandbox()
    assert not scope.cleanup_confirmed


@pytest.mark.asyncio
async def test_termination_failure_attempts_other_resource(monkeypatch):
    bad, good = sandbox(terminate_error=RuntimeError("transport")), sandbox("sb-good")
    monkeypatch.setattr(ModalEnvironment, "_create_sandbox", AsyncMock(side_effect=[bad, good]))
    with pytest.raises(ModalCleanupError):
        async with ModalExecutionScope() as scope:
            await environment()._create_sandbox()
            await environment("verifier")._create_sandbox()
    assert not scope.cleanup_confirmed
    good.terminate.aio.assert_awaited_once()


@pytest.mark.asyncio
async def test_never_terminal_times_out(monkeypatch):
    sb = sandbox()
    sb.poll.aio = AsyncMock(return_value=None)
    monkeypatch.setattr(ModalEnvironment, "_create_sandbox", AsyncMock(return_value=sb))
    with pytest.raises(ModalCleanupError):
        async with ModalExecutionScope(cleanup_timeout=0.02, poll_interval=0.001) as scope:
            await environment()._create_sandbox()
    assert not scope.cleanup_confirmed


@pytest.mark.asyncio
async def test_parallel_scopes_do_not_mix_resources(monkeypatch):
    async def create(env, **kwargs):
        await asyncio.sleep(0)
        return sandbox("sb-" + env.session_id)

    monkeypatch.setattr(ModalEnvironment, "_create_sandbox", create)

    async def run(name):
        async with ModalExecutionScope() as scope:
            await environment(name)._create_sandbox()
        return scope.evidence

    first, second = await asyncio.gather(run("one"), run("two"))
    assert first[0]["sandbox_id"] == "sb-one"
    assert second[0]["sandbox_id"] == "sb-two"
    assert len(first) == len(second) == 1


@pytest.mark.asyncio
async def test_cancelled_owner_does_not_lose_created_handle(monkeypatch):
    started, release = asyncio.Event(), asyncio.Event()
    sb = sandbox()

    async def create(env, **kwargs):
        started.set()
        await release.wait()
        return sb

    monkeypatch.setattr(ModalEnvironment, "_create_sandbox", create)
    scopes = []

    async def run():
        async with ModalExecutionScope() as scope:
            scopes.append(scope)
            await environment()._create_sandbox()

    owner = asyncio.create_task(run())
    await started.wait()
    owner.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await owner
    assert scopes[0].cleanup_confirmed
    sb.terminate.aio.assert_awaited_once()


@pytest.mark.asyncio
async def test_closed_inherited_scope_rejects_late_creation(monkeypatch):
    release = asyncio.Event()
    create = AsyncMock(return_value=sandbox())
    monkeypatch.setattr(ModalEnvironment, "_create_sandbox", create)

    async def late():
        await release.wait()
        await environment()._create_sandbox()

    async with ModalExecutionScope() as scope:
        task = asyncio.create_task(late())
    assert not scope.cleanup_confirmed
    release.set()
    with pytest.raises(RuntimeError, match="scope"):
        await task
    create.assert_not_awaited()


@pytest.mark.asyncio
async def test_wrong_harbor_version_fails_before_create(monkeypatch):
    monkeypatch.setattr("uni_agent.tasks.harbor_dsh.modal_environment.importlib.metadata.version", lambda _: "0.99")
    create = AsyncMock()
    monkeypatch.setattr(ModalEnvironment, "_create_sandbox", create)
    with pytest.raises(ValueError, match="0.16.1"):
        async with ModalExecutionScope():
            await environment()._create_sandbox()
    create.assert_not_awaited()


@pytest.mark.asyncio
async def test_hanging_allocation_does_not_prevent_known_resource_cleanup(monkeypatch):
    sb = sandbox()
    hanging = asyncio.Event()

    async def create(env, **kwargs):
        if env.session_id == "stuck":
            await hanging.wait()
        return sb

    monkeypatch.setattr(ModalEnvironment, "_create_sandbox", create)
    with pytest.raises(ModalCleanupError):
        async with ModalExecutionScope(cleanup_timeout=0.02) as scope:
            await environment()._create_sandbox()
            late = asyncio.create_task(environment("stuck")._create_sandbox())
            await asyncio.sleep(0)
    await asyncio.gather(late, return_exceptions=True)
    assert not scope.cleanup_confirmed
    sb.terminate.aio.assert_awaited_once()


@pytest.mark.asyncio
async def test_nested_scope_rejected_and_normal_body_error_preserved():
    with pytest.raises(RuntimeError, match="nested"):
        async with ModalExecutionScope():
            async with ModalExecutionScope():
                pass
    with pytest.raises(ValueError, match="body failed"):
        async with ModalExecutionScope():
            raise ValueError("body failed")
