import json

import pytest
from aiohttp import ClientSession, web
from aiohttp.test_utils import TestClient, TestServer

from deployment.services.harbor_modal_ingress import ModalIngress, ModalIngressConfig, proxy_app
from tests.uni_agent.deployment.test_harbor_run_controller import make_spec


def config(tmp_path, **changes):
    credentials = tmp_path / "tunnel.json"
    credentials.write_text("{}")
    credentials.chmod(0o600)
    return ModalIngressConfig.model_validate(
        dict(
            origin="https://gateway.example.com",
            tunnel_id="11111111-1111-4111-8111-111111111111",
            credentials_file=credentials,
            listen_port=47103,
            **changes,
        )
    )


def test_docker_runspec_canonical_compatibility(tmp_path):
    spec = make_spec(tmp_path)
    assert "modal_ingress" not in spec.model_dump(mode="json")
    assert "modal_ingress" not in json.loads(spec.model_dump_json())


@pytest.mark.parametrize(
    "origin",
    [
        "http://gateway.example.com",
        "https://localhost",
        "https://gateway.example.com:444",
        "https://gateway.example.com/path",
    ],
)
def test_invalid_origin(tmp_path, origin):
    data = config(tmp_path).model_dump()
    data["origin"] = origin
    with pytest.raises(ValueError):
        ModalIngressConfig.model_validate(data)


@pytest.mark.asyncio
async def test_proxy_only_model_routes_preserves_sse_and_status():
    seen = []

    async def upstream(request):
        seen.append((request.raw_path, await request.read(), request.headers.get("Authorization")))
        return web.Response(
            status=201,
            body=b"data: first\n\ndata: [DONE]\n\n",
            headers={"Content-Type": "text/event-stream", "Connection": "close"},
        )

    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", upstream)
    async with TestServer(app) as server:
        async with TestClient(
            TestServer(proxy_app(str(server.make_url("")).rstrip("/"), "/probe-secret", "nonce"))
        ) as client:
            for path in ["/health", "/v1/sessions", "/sessions/s/v1/admin", "/sessions/s/v1/chat/completions/extra"]:
                assert (await client.post(path)).status == 404
            response = await client.post(
                "/sessions/s/v1/chat/completions?x=1", data=b"{}", headers={"Authorization": "Bearer model"}
            )
            assert response.status == 201
            assert await response.read() == b"data: first\n\ndata: [DONE]\n\n"
            assert seen == [("/sessions/s/v1/chat/completions?x=1", b"{}", "Bearer model")]
            assert await (await client.get("/probe-secret")).text() == "nonce"


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body", [(200, "wrong"), (302, "nonce"), (200, "nonce")])
async def test_public_probe_requires_exact_nonce_and_no_redirect(tmp_path, status, body):
    async def endpoint(request):
        return web.Response(status=status, text=body, headers={"Location": "/elsewhere"})

    app = web.Application()
    app.router.add_get("/probe", endpoint)
    spec = make_spec(tmp_path)
    ingress = ModalIngress(spec.model_copy(update={"modal_ingress": config(tmp_path)}))
    ingress.nonce = "nonce"
    async with TestServer(app) as server, ClientSession() as client:
        assert await ingress._probe(client, str(server.make_url("/probe"))) is (status == 200 and body == "nonce")


@pytest.mark.asyncio
async def test_private_credentials_checked_before_spawn(tmp_path):
    spec = make_spec(tmp_path)
    cfg = config(tmp_path)
    cfg.credentials_file.chmod(0o644)
    calls = []

    async def spawn(*args, **kwargs):
        calls.append(args)

    ingress = ModalIngress(spec.model_copy(update={"modal_ingress": cfg}), spawn=spawn)
    with pytest.raises(ValueError):
        await ingress.start()
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, "ingress", "worker"])
async def test_controller_owns_ingress_order_and_failure_cleanup(tmp_path, failure):
    from deployment.services.harbor_run_controller import HarborRunController
    from tests.uni_agent.deployment.test_harbor_run_controller import FakeService, registration

    calls = []
    spec = make_spec(tmp_path).model_copy(update={"modal_ingress": config(tmp_path)})

    class Ingress(FakeService):
        async def start(self):
            await super().start()
            if failure == "ingress":
                raise RuntimeError("public nonce mismatch")

    def tunnel_factory(spec, *, kind, gateway_port=None):
        return FakeService(calls, kind)

    async def worker_factory(spec, policy):
        assert calls[-1] == "start:ingress"
        assert spec.modal_ingress.origin == "https://gateway.example.com"
        if failure == "worker":
            raise RuntimeError("worker failed")
        calls.append("start:worker")
        return FakeService(calls, "worker")

    ctl = HarborRunController(
        spec,
        tunnel_factory=tunnel_factory,
        ingress_factory=lambda spec: Ingress(calls, "ingress"),
        worker_factory=worker_factory,
        clock=lambda: 1000,
    )
    await ctl.start()
    if failure:
        with pytest.raises(RuntimeError):
            await ctl.register("run-1", registration(ctl))
        assert calls[-2:] == ["close:ingress", "close:model"]
        assert not (spec.root / "registration-receipt.json").exists()
    else:
        await ctl.register("run-1", registration(ctl))
        assert calls == ["start:control", "start:model", "start:ingress", "start:worker"]
        ctl.ingress.alive = False
        assert ctl._unhealthy_reason() == "ingress-unavailable"
        with pytest.raises(ValueError):
            await ctl.register("run-1", registration(ctl))
    await ctl.close()
    assert calls[-3:] == ["close:ingress", "close:model", "close:control"]


@pytest.mark.asyncio
@pytest.mark.parametrize("exit_early", [False, True])
async def test_owned_named_tunnel_launch_and_close(tmp_path, monkeypatch, exit_early):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    spec = make_spec(tmp_path).model_copy(update={"modal_ingress": config(tmp_path)})
    spec.root.mkdir()
    process = SimpleNamespace(returncode=1 if exit_early else None)
    process.wait = AsyncMock(return_value=0)

    def stop():
        process.returncode = 0

    process.terminate = stop
    process.kill = stop
    spawn = AsyncMock(return_value=process)
    ingress = ModalIngress(spec, spawn=spawn)
    probe = AsyncMock(return_value=True)
    monkeypatch.setattr(ingress, "_probe", probe)
    # Bind an ephemeral local socket; production config still requires nonzero fixed port.
    monkeypatch.setattr(
        "deployment.services.harbor_modal_ingress.web.TCPSite", lambda runner, host, port: TestSite(runner)
    )
    if exit_early:
        with pytest.raises(RuntimeError):
            await ingress.start()
        assert not ingress.alive
    else:
        await ingress.start()
        assert ingress.alive
        probe.assert_awaited_once()
    assert spawn.call_args.args == (
        "cloudflared",
        "tunnel",
        "--config",
        str(spec.root / "modal-tunnel.json"),
        "--no-autoupdate",
        "run",
        str(spec.modal_ingress.tunnel_id),
    )
    frozen = json.loads((spec.root / "modal-tunnel.json").read_text())
    assert frozen["ingress"][-1] == {"service": "http_status:404"}
    assert (spec.root / "modal-tunnel-credentials.json").stat().st_mode & 0o077 == 0
    await ingress.close()
    await ingress.close()
    assert not ingress.alive


class TestSite:
    __test__ = False

    def __init__(self, runner):
        self.runner = runner

    async def start(self):
        pass


@pytest.mark.asyncio
async def test_sse_first_chunk_arrives_before_upstream_finishes():
    import asyncio

    release = asyncio.Event()

    async def stream(request):
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await response.prepare(request)
        await response.write(b"data: first\n\n")
        await release.wait()
        await response.write(b"data: last\n\n")
        return response

    app = web.Application()
    app.router.add_post("/sessions/s/v1/chat/completions", stream)
    async with TestServer(app) as upstream:
        async with TestClient(
            TestServer(proxy_app(str(upstream.make_url("")).rstrip("/"), "/probe", "nonce"))
        ) as client:
            try:
                response = await client.post("/sessions/s/v1/chat/completions", data=b"{}")
                assert await asyncio.wait_for(response.content.readexactly(13), 1) == b"data: first\n\n"
            finally:
                release.set()
            assert await response.read() == b"data: last\n\n"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [302, 429, 500])
async def test_upstream_status_and_redirect_are_preserved(tmp_path, status):
    calls = []

    async def upstream(request):
        calls.append(request.path)
        return web.Response(status=status, text="upstream", headers={"Location": "/private"})

    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", upstream)
    async with TestServer(app) as server:
        async with TestClient(TestServer(proxy_app(str(server.make_url("")).rstrip("/"), "/probe", "nonce"))) as client:
            response = await client.post("/sessions/s/v1/messages", data=b"{}", allow_redirects=False)
            assert response.status == status
            assert await response.text() == "upstream"
            assert calls == ["/sessions/s/v1/messages"]


@pytest.mark.parametrize("kind", ["shared-port", "credential-symlink", "relative-credential"])
def test_ingress_config_rejects_ambiguous_local_contract(tmp_path, kind):
    from deployment.services.harbor_run_controller import RunSpec

    cfg = config(tmp_path)
    if kind == "shared-port":
        spec = make_spec(tmp_path).model_dump()
        spec["modal_ingress"] = cfg.model_copy(update={"listen_port": spec["model_port"]})
        with pytest.raises(ValueError):
            RunSpec.model_validate(spec)
    elif kind == "relative-credential":
        with pytest.raises(ValueError):
            ModalIngressConfig.model_validate({**cfg.model_dump(), "credentials_file": "relative"})
    else:
        link = tmp_path / "link"
        link.symlink_to(cfg.credentials_file)
        spec = make_spec(tmp_path).model_copy(
            update={"modal_ingress": cfg.model_copy(update={"credentials_file": link})}
        )
        import asyncio

        with pytest.raises(OSError):
            asyncio.run(ModalIngress(spec).start())


@pytest.mark.asyncio
async def test_upstream_disconnect_never_fabricates_complete_sse():
    from aiohttp import ClientPayloadError

    async def broken(request):
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream", "Content-Length": "100"})
        await response.prepare(request)
        await response.write(b"data: partial\n\n")
        request.transport.close()
        return response

    app = web.Application()
    app.router.add_post("/sessions/s/v1/chat/completions", broken)
    async with TestServer(app) as server:
        async with TestClient(TestServer(proxy_app(str(server.make_url("")).rstrip("/"), "/probe", "nonce"))) as client:
            response = await client.post("/sessions/s/v1/chat/completions", data=b"{}")
            if response.status == 200:
                with pytest.raises(ClientPayloadError):
                    await response.read()
            else:
                assert response.status == 502


@pytest.mark.asyncio
async def test_wrong_public_mapping_never_marks_ready_and_closes_process(tmp_path, monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    spec = make_spec(tmp_path).model_copy(update={"modal_ingress": config(tmp_path)})
    spec.root.mkdir()
    process = SimpleNamespace(returncode=None, wait=AsyncMock(return_value=0))

    def stop():
        process.returncode = 0

    process.terminate = process.kill = stop
    ingress = ModalIngress(spec, spawn=AsyncMock(return_value=process))
    monkeypatch.setattr(
        "deployment.services.harbor_modal_ingress.web.TCPSite", lambda runner, host, port: TestSite(runner)
    )
    monkeypatch.setattr(ingress, "_probe", AsyncMock(return_value=False))
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(ingress.start(), 0.03)
    assert not ingress.alive
    assert process.returncode == 0
    assert ingress.runner is None


@pytest.mark.parametrize("repository", ["worktree", "main"])
def test_modal_runtime_root_cannot_persist_credentials_in_repository(tmp_path, repository):
    from pathlib import Path

    from deployment.services.harbor_run_controller import RunSpec

    current = Path(__file__).resolve().parents[3]
    target = (
        current
        if repository == "worktree"
        else next((parent for parent in current.parents if (parent / ".git").is_dir()), current)
    )
    spec = make_spec(tmp_path).model_dump()
    spec.update(root=target / "private-modal-runtime", modal_ingress=config(tmp_path))
    with pytest.raises(ValueError, match="outside the repository"):
        RunSpec.model_validate(spec)
