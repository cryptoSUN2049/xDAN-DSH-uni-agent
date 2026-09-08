import asyncio
import signal

import pytest

from deployment.services.harbor_tunnel import SshTunnel
from tests.uni_agent.deployment.test_harbor_run_controller import make_spec


class Process:
    def __init__(self, code=None):
        self.returncode = code
        self.signals = []
        self.done = asyncio.Event()
        if code is not None:
            self.done.set()

    async def wait(self):
        await self.done.wait()
        return self.returncode

    def send_signal(self, value):
        self.signals.append(value)
        self.returncode = -value
        self.done.set()

    def kill(self):
        self.send_signal(signal.SIGKILL)


@pytest.mark.asyncio
async def test_only_owned_master_stops_and_argv_uses_fixed_forward(tmp_path):
    spec = make_spec(tmp_path)
    spec.root.mkdir()
    calls = []
    owned = Process()

    async def spawn(*args, **kwargs):
        calls.append(args)
        if len(calls) == 1:
            (spec.root / "model.sock").touch()
            return owned
        return Process(0)

    tunnel = SshTunnel(spec, kind="model", gateway_port=45678, spawn=spawn)
    await tunnel.start()
    assert tunnel.alive
    assert "127.0.0.1:47102:10.0.0.2:45678" in calls[0]
    assert "StrictHostKeyChecking=yes" in calls[0]
    assert "ExitOnForwardFailure=yes" in calls[0]
    assert "-O" in calls[1] and "check" in calls[1]
    await tunnel.close()
    assert owned.signals == [signal.SIGTERM]
    await tunnel.close()
    assert owned.signals == [signal.SIGTERM]


@pytest.mark.asyncio
async def test_failed_master_start_never_claims_ready(tmp_path):
    spec = make_spec(tmp_path)
    spec.root.mkdir()
    process = Process(255)

    async def spawn(*args, **kwargs):
        return process

    tunnel = SshTunnel(spec, kind="control", spawn=spawn)
    with pytest.raises(RuntimeError, match="exited"):
        await tunnel.start()
    assert not tunnel.alive


@pytest.mark.asyncio
async def test_cancelled_start_reaps_checker_and_owned_master(tmp_path):
    spec = make_spec(tmp_path)
    spec.root.mkdir()
    master, checker = Process(), Process()
    checking = asyncio.Event()
    calls = 0

    async def spawn(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            (spec.root / "control.sock").touch()
            return master
        checking.set()
        return checker

    tunnel = SshTunnel(spec, kind="control", spawn=spawn)
    start = asyncio.create_task(tunnel.start())
    await checking.wait()
    start.cancel()
    with pytest.raises(asyncio.CancelledError):
        await start
    assert checker.signals == [signal.SIGKILL]
    assert master.signals == [signal.SIGTERM]


def test_invalid_tunnel_port_cannot_be_interpolated(tmp_path):
    with pytest.raises(ValueError):
        SshTunnel(make_spec(tmp_path), kind="model", gateway_port="45678 -R bad")
