import asyncio
import json
from copy import deepcopy

import pytest
from aiohttp.test_utils import TestClient, TestServer

from deployment.services.harbor_run_controller import HarborRunController, RunSpec, create_app
from tests.uni_agent.tasks.test_harbor_dsh_protocol import payload, policy


def make_spec(tmp_path):
    template = policy(payload()).model_dump(mode="json")
    template.pop("gateway_port")
    for name, content in (("registration-token", "r" * 32), ("worker-token", "w" * 32)):
        path = tmp_path / name
        path.write_text(content)
        path.chmod(0o600)
    return RunSpec(
        run_id="run-1",
        controller_id="controller-1",
        worker_id="worker-1",
        deadline_unix=1100,
        policy_template=template,
        root=tmp_path / "run",
        task_dir=tmp_path,
        registration_token_file=tmp_path / "registration-token",
        worker_token_file=tmp_path / "worker-token",
        ssh_host="203.0.113.1",
        ssh_port=2222,
        ssh_user="root",
        ssh_key=tmp_path / "key",
        known_hosts=tmp_path / "known_hosts",
        control_port=47100,
        worker_port=47101,
        model_port=47102,
        remote_control_port=47200,
        remote_worker_port=47201,
    )


class FakeService:
    def __init__(self, calls, name):
        self.calls, self.name, self.alive = calls, name, True

    async def start(self):
        self.calls.append("start:" + self.name)

    async def close(self):
        self.alive = False
        self.calls.append("close:" + self.name)


def make_controller(tmp_path, fail_worker=False):
    calls = []
    tunnels = []

    def tunnel_factory(spec, *, kind, gateway_port=None):
        service = FakeService(calls, kind)
        tunnels.append(service)
        return service

    async def worker_factory(spec, effective_policy):
        calls.append("worker-policy:" + str(effective_policy.gateway_port))
        if fail_worker:
            raise RuntimeError("worker bind failed")
        return FakeService(calls, "worker")

    ctl = HarborRunController(
        make_spec(tmp_path), tunnel_factory=tunnel_factory, worker_factory=worker_factory, clock=lambda: 1000
    )
    return ctl, calls, tunnels


def registration(ctl, **changes):
    result = {"gateway_host": "10.0.0.2", "gateway_port": 45678, "run_spec_sha256": ctl.spec_sha256}
    result.update(changes)
    return result


@pytest.mark.asyncio
async def test_concurrent_registration_starts_once_and_freezes_only_port(tmp_path):
    ctl, calls, _ = make_controller(tmp_path)
    await ctl.start()
    before = deepcopy(ctl.spec.policy_template)
    first, second = await asyncio.gather(
        ctl.register("run-1", registration(ctl)), ctl.register("run-1", registration(ctl))
    )
    assert first == second
    assert calls == ["start:control", "start:model", "worker-policy:45678"]
    assert ctl.spec.policy_template == before
    assert first["policy"] == {**before, "gateway_port": 45678}
    persisted = json.loads((ctl.spec.root / "effective-policy.json").read_text())
    assert persisted == first["policy"]
    with pytest.raises(ValueError):
        await ctl.register("run-1", registration(ctl, gateway_port=45679))
    await ctl.close()
    assert calls[-3:] == ["close:worker", "close:model", "close:control"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        {"gateway_host": "10.0.0.3"},
        {"run_spec_sha256": "sha256:" + "0" * 64},
        {"gateway_port": True},
        {"max_tokens": 999},
    ],
)
async def test_bad_registration_never_starts_model_or_worker(tmp_path, change):
    ctl, calls, _ = make_controller(tmp_path)
    await ctl.start()
    with pytest.raises(ValueError):
        await ctl.register("run-1", registration(ctl, **change))
    assert calls == ["start:control"]
    await ctl.close()


@pytest.mark.asyncio
async def test_worker_start_failure_stops_model_and_prevents_retry(tmp_path):
    ctl, calls, _ = make_controller(tmp_path, fail_worker=True)
    await ctl.start()
    with pytest.raises(RuntimeError):
        await ctl.register("run-1", registration(ctl))
    assert calls[-1] == "close:model"
    with pytest.raises(ValueError):
        await ctl.register("run-1", registration(ctl))
    await ctl.close()


@pytest.mark.asyncio
async def test_job_token_cannot_register_and_wrong_run_is_rejected(tmp_path):
    ctl, calls, _ = make_controller(tmp_path)
    await ctl.start()
    async with TestClient(TestServer(create_app(ctl))) as client:
        response = await client.post(
            "/v1/runs/run-1/gateway", json=registration(ctl), headers={"Authorization": "Bearer " + "w" * 32}
        )
        assert response.status == 401
        response = await client.post(
            "/v1/runs/other-run/gateway", json=registration(ctl), headers={"Authorization": "Bearer " + "r" * 32}
        )
        assert response.status == 409
    assert calls == ["start:control"]
    await ctl.close()


@pytest.mark.asyncio
async def test_deadline_and_dead_tunnel_reject_registration(tmp_path):
    ctl, calls, tunnels = make_controller(tmp_path)
    await ctl.start()
    ctl.clock = lambda: 1100
    with pytest.raises(ValueError):
        await ctl.register("run-1", registration(ctl))
    ctl.clock = lambda: 1000
    tunnels[0].alive = False
    with pytest.raises(ValueError):
        await ctl.register("run-1", registration(ctl))
    assert calls == ["start:control"]
    await ctl.close()


@pytest.mark.asyncio
async def test_cleanup_failure_still_stops_owned_tunnels(tmp_path):
    ctl, calls, _ = make_controller(tmp_path)
    await ctl.start()
    await ctl.register("run-1", registration(ctl))

    async def fail_close():
        raise RuntimeError("cleanup unknown")

    ctl.worker.close = fail_close
    with pytest.raises(RuntimeError, match="unconfirmed"):
        await ctl.close()
    assert calls[-2:] == ["close:model", "close:control"]
    assert json.loads((ctl.spec.root / "controller-stop.json").read_text())["cleanup_errors"] == ["RuntimeError"]


@pytest.mark.asyncio
async def test_registration_after_close_never_restarts_worker(tmp_path):
    ctl, calls, _ = make_controller(tmp_path)
    await ctl.start()
    await ctl.close()
    with pytest.raises(ValueError):
        await ctl.register("run-1", registration(ctl))
    assert calls == ["start:control", "close:control"]


def test_template_cannot_preapprove_a_port(tmp_path):
    raw = make_spec(tmp_path).model_dump(mode="json")
    raw["policy_template"]["gateway_port"] = 45678
    with pytest.raises(ValueError, match="unbound"):
        RunSpec.model_validate(raw)


@pytest.mark.asyncio
async def test_reused_root_is_not_modified_on_failed_start_or_close(tmp_path):
    ctl, calls, _ = make_controller(tmp_path)
    ctl.spec.root.mkdir()
    marker = ctl.spec.root / "prior-run.json"
    marker.write_text("old evidence")
    with pytest.raises(FileExistsError):
        await ctl.start()
    await ctl.close()
    assert sorted(p.name for p in ctl.spec.root.iterdir()) == ["prior-run.json"]
    assert calls == []


@pytest.mark.asyncio
async def test_real_factory_binds_run_and_closes_listener_before_worker(monkeypatch, tmp_path):
    from deployment.services.harbor_run_controller import start_worker
    from uni_agent.tasks.harbor_dsh import worker as worker_module

    calls = []

    class Worker:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def submit(self, data):
            return data

        async def close(self):
            calls.append("worker-close")

    class Site:
        def __init__(self, runner, host, port):
            assert host == "127.0.0.1"
            runner.sites.add(self)

        async def start(self):
            calls.append("site-start")

        async def stop(self):
            calls.append("site-stop")

    class Runner:
        def __init__(self, *args, **kwargs):
            self.sites = set()

        async def setup(self):
            pass

        async def cleanup(self):
            calls.append("runner-cleanup")

    monkeypatch.setattr(worker_module, "HarborWorker", Worker)
    monkeypatch.setattr("deployment.services.harbor_run_controller.web.AppRunner", Runner)
    monkeypatch.setattr("deployment.services.harbor_run_controller.web.TCPSite", Site)
    spec = make_spec(tmp_path)
    service = await start_worker(spec, policy(payload()))
    assert service.worker.submit({"run_id": "run-1"}) == {"run_id": "run-1"}
    with pytest.raises(ValueError, match="controller run"):
        service.worker.submit({"run_id": "other-run"})
    await service.close()
    assert calls == ["site-start", "site-stop", "worker-close", "runner-cleanup"]
