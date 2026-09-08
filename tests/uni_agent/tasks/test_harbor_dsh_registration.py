import asyncio
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from tests.uni_agent.tasks.test_harbor_dsh_protocol import payload, policy
from uni_agent.gateway.session import SessionHandle
from uni_agent.tasks.harbor_dsh.registration import ensure_harbor_route, load_registered_policy

pytestmark = [pytest.mark.cpu, pytest.mark.level0]


def checksum(value):
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        ).hexdigest()
    )


def setup(tmp_path):
    template = policy(payload()).model_dump(mode="json")
    template.pop("gateway_port")
    token = tmp_path / "token"
    token.write_text("registration-private-token" * 2)
    token.chmod(0o600)
    cfg = {
        "controller_url": "http://127.0.0.1:1",
        "token_file": str(token),
        "registration_root": str(tmp_path / "registrations"),
        "controller_id": "controller-1",
        "run_spec_sha256": "sha256:" + "d" * 64,
        "timeout_seconds": 0.2,
    }
    ctx = {
        "partition_id": "train",
        "gateway_session_id": "session-1",
        "global_steps": 1,
        "group_uid": "group-1",
        "group_size": 1,
        "sample_index": 0,
        "session_index": 0,
    }
    session = SessionHandle(session_id="session-1", base_url="http://10.0.0.2:45678/sessions/session-1/v1")
    return cfg, template, ctx, session


def receipt(cfg, template, port=45678):
    resolved = {**copy.deepcopy(template), "gateway_port": port}
    return {
        "schema": "dsh.harbor-route-registration.v1",
        "run_id": "run-1",
        "controller_id": cfg["controller_id"],
        "run_spec_sha256": cfg["run_spec_sha256"],
        "policy": resolved,
        "policy_sha256": checksum(resolved),
        "registered_at_unix": 1000.0,
    }


async def register(server, cfg, template, ctx, session):
    return await ensure_harbor_route(
        session=session,
        runner_context=ctx,
        run_id="run-1",
        policy_template=template,
        registration={**cfg, "controller_url": str(server.make_url("/")).rstrip("/")},
    )


@pytest.mark.asyncio
async def test_real_http_registration_saves_independent_policy_and_is_concurrent_idempotent(tmp_path):
    cfg, template, ctx, session = setup(tmp_path)
    response = receipt(cfg, template)
    seen = []

    async def handle(request):
        assert request.headers["Authorization"] == "Bearer " + Path(cfg["token_file"]).read_text()
        seen.append(await request.json())
        return web.json_response(response)

    app = web.Application()
    app.router.add_post("/v1/runs/run-1/gateway", handle)
    async with TestServer(app) as server:
        results = await asyncio.gather(*(register(server, cfg, template, ctx, session) for _ in range(3)))
    assert all(result.gateway_port == 45678 for result in results)
    assert all(
        item == {"gateway_host": "10.0.0.2", "gateway_port": 45678, "run_spec_sha256": cfg["run_spec_sha256"]}
        for item in seen
    )
    saved = Path(cfg["registration_root"]) / "run-1" / "registration.json"
    assert saved.stat().st_mode & 0o777 == 0o600
    assert saved.parent.stat().st_mode & 0o777 == 0o700
    assert Path(cfg["token_file"]).read_bytes() not in saved.read_bytes()
    loaded = load_registered_policy(
        registration_root=cfg["registration_root"],
        run_id="run-1",
        controller_id=cfg["controller_id"],
        run_spec_sha256=cfg["run_spec_sha256"],
        policy_template=template,
    )
    assert loaded == results[0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "attack",
    [
        "run_id",
        "controller_id",
        "run_spec_sha256",
        "policy_sha256",
        "port",
        "model",
        "budget",
        "release",
        "task",
        "host",
    ],
)
async def test_response_cannot_change_frozen_operator_contract(tmp_path, attack):
    cfg, template, ctx, session = setup(tmp_path)
    response = receipt(cfg, template)
    if attack in {"run_id", "controller_id", "run_spec_sha256", "policy_sha256"}:
        response[attack] = "wrong"
    else:
        key = {"port": "gateway_port", "model": "model_name", "budget": "max_tokens", "host": "gateway_host"}.get(
            attack
        )
        if key:
            response["policy"][key] = {"port": 45679, "model": "wrong", "budget": 1, "host": "10.0.0.9"}[attack]
        elif attack == "release":
            response["policy"]["dsh_release"]["source_sha"] = "e" * 40
        else:
            response["policy"]["task_refs"][0]["id"] = "wrong"
        response["policy_sha256"] = checksum(response["policy"])

    async def handle(request):
        return web.json_response(response)

    app = web.Application()
    app.router.add_post("/v1/runs/run-1/gateway", handle)
    async with TestServer(app) as server:
        with pytest.raises(ValueError):
            await register(server, cfg, template, ctx, session)
    assert not list(tmp_path.rglob("registration.json"))


@pytest.mark.asyncio
@pytest.mark.parametrize("attack", ["session", "context", "host", "prebound", "public-token"])
async def test_untrusted_inputs_are_rejected_before_http(tmp_path, attack):
    cfg, template, ctx, session = setup(tmp_path)
    if attack == "session":
        session = SimpleNamespace(session_id="session-1", base_url=session.base_url)
    elif attack == "context":
        ctx["gateway_session_id"] = "wrong"
    elif attack == "host":
        session = SessionHandle(session_id="session-1", base_url="http://10.0.0.9:45678/sessions/session-1/v1")
    elif attack == "prebound":
        template["gateway_port"] = 1
    else:
        Path(cfg["token_file"]).chmod(0o644)
    with pytest.raises(ValueError):
        await ensure_harbor_route(
            session=session, runner_context=ctx, run_id="run-1", policy_template=template, registration=cfg
        )


@pytest.mark.asyncio
async def test_redirect_is_not_followed(tmp_path):
    cfg, template, ctx, session = setup(tmp_path)
    hits = []

    async def redirect(request):
        raise web.HTTPTemporaryRedirect("/leak")

    async def leaked(request):
        hits.append(request.headers.get("Authorization"))
        return web.Response()

    app = web.Application()
    app.router.add_post("/v1/runs/run-1/gateway", redirect)
    app.router.add_route("*", "/leak", leaked)
    async with TestServer(app) as server:
        with pytest.raises(ValueError):
            await register(server, cfg, template, ctx, session)
    assert hits == []


@pytest.mark.asyncio
async def test_existing_registration_cannot_be_replaced_by_another_port(tmp_path):
    cfg, template, ctx, session = setup(tmp_path)
    response = receipt(cfg, template)

    async def handle(request):
        return web.json_response(response)

    app = web.Application()
    app.router.add_post("/v1/runs/run-1/gateway", handle)
    async with TestServer(app) as server:
        await register(server, cfg, template, ctx, session)
        response = receipt(cfg, template, 45679)
        session = SessionHandle(session_id="session-1", base_url="http://10.0.0.2:45679/sessions/session-1/v1")
        with pytest.raises(ValueError, match="registration"):
            await register(server, cfg, template, ctx, session)


@pytest.mark.asyncio
async def test_runner_registers_only_explicit_operator_kwargs_after_resolving_template(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock

    import yaml

    from tests.uni_agent.tasks.test_harbor_dsh_task import config
    from uni_agent.framework import task_runner
    from uni_agent.tasks.base import TaskResult
    from uni_agent.tasks.harbor_dsh import registration as registration_module

    cfg, template, ctx, session = setup(tmp_path)
    frozen = config(tmp_path).model_dump(mode="json")
    frozen.pop("gateway_base_url")
    frozen.pop("runner_context")
    frozen["worker_token"] = "worker-test-token" * 3
    frozen["policy"] = template
    path = tmp_path / "tasks.yaml"
    path.write_text(yaml.safe_dump(frozen))
    register = AsyncMock(return_value=policy(payload()))
    monkeypatch.setattr(registration_module, "ensure_harbor_route", register)
    received = []

    def get_task(value):
        received.append(value)
        return SimpleNamespace(run=AsyncMock(return_value=TaskResult(reward=0, verifier_reward=0, finished=True)))

    monkeypatch.setattr(task_runner, "get_task", get_task)
    await task_runner.run_task(
        session=session,
        tools_kwargs={"task": {"name": "harbor_dsh"}, "_runner_context": ctx},
        raw_prompt=[{"role": "user", "content": "Write the answer"}],
        task_config_path=str(path),
        harbor_route_registration=cfg,
        require_result=True,
    )
    assert register.call_count == 1
    assert register.call_args.kwargs["session"] is session
    assert register.call_args.kwargs["registration"] == cfg
    assert register.call_args.kwargs["policy_template"] == template
    assert received[0]["policy"]["gateway_port"] == 45678
    assert received[0]["runner_context"] == ctx


@pytest.mark.asyncio
async def test_sample_cannot_supply_registration_configuration(tmp_path):
    from uni_agent.framework.task_runner import run_task

    cfg, _, ctx, session = setup(tmp_path)
    with pytest.raises(ValueError, match="registration"):
        await run_task(
            session=session,
            tools_kwargs={"task": {"name": "harbor_dsh", "harbor_route_registration": cfg}, "_runner_context": ctx},
        )


@pytest.mark.asyncio
async def test_client_matches_real_controller_schema_and_hash_contract(tmp_path):
    from deployment.services.harbor_run_controller import create_app
    from tests.uni_agent.deployment.test_harbor_run_controller import make_controller

    cfg, template, ctx, session = setup(tmp_path)
    controller, calls, _ = make_controller(tmp_path)
    cfg["token_file"] = str(controller.spec.registration_token_file)
    cfg["run_spec_sha256"] = controller.spec_sha256
    await controller.start()
    try:
        async with TestServer(create_app(controller)) as server:
            resolved = await register(server, cfg, template, ctx, session)
        assert resolved.gateway_port == 45678
        assert calls == ["start:control", "start:model", "worker-policy:45678"]
    finally:
        await controller.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["oversized", "timeout"])
async def test_control_response_is_bounded(tmp_path, failure):
    cfg, template, ctx, session = setup(tmp_path)
    release = asyncio.Event()

    async def handle(request):
        if failure == "timeout":
            await release.wait()
        return web.Response(body=b" " * 65537)

    app = web.Application()
    app.router.add_post("/v1/runs/run-1/gateway", handle)
    async with TestServer(app) as server:
        try:
            with pytest.raises(TimeoutError if failure == "timeout" else ValueError):
                await register(server, cfg, template, ctx, session)
        finally:
            release.set()
    assert not list(tmp_path.rglob("registration.json"))


@pytest.mark.asyncio
async def test_audit_wrapper_reads_registered_port_not_task_receipt(tmp_path, monkeypatch):
    from tests.uni_agent.tasks.test_harbor_dsh_task import config, downloaded, evidence
    from uni_agent.gateway.session import Trajectory
    from uni_agent.tasks.base import build_reward_info
    from uni_agent.tasks.harbor_dsh.client import HarborDshClient
    from uni_agent.tasks.harbor_dsh.registration import validate_registered_trajectories
    from uni_agent.tasks.harbor_dsh.task import HarborDshTask

    cfg, template, _, session = setup(tmp_path)
    task_cfg = config(tmp_path)
    context = task_cfg.runner_context.model_dump()
    response = receipt(cfg, template)

    async def handle(request):
        return web.json_response(response)

    app = web.Application()
    app.router.add_post("/v1/runs/run-1/gateway", handle)
    async with TestServer(app) as server:
        await register(server, cfg, template, context, session)

    async def run(self, request):
        return downloaded(request, evidence(request))

    monkeypatch.setattr(HarborDshClient, "run", run)
    result = await HarborDshTask(task_cfg).run()
    trajectory = Trajectory(
        prompt_ids=[1],
        response_ids=[2],
        response_mask=[1],
        response_logprobs=[-0.1],
        finished=True,
        reward_score=1.0,
        extra_fields={"dsh_reward_info": build_reward_info(result)},
    )
    kwargs = {
        "context": context,
        "artifact_root": task_cfg.artifact_root,
        "run_id": "run-1",
        "worker_id": "worker-1",
        "task_ref": task_cfg.task_ref,
        "policy_template": template,
        "instruction": task_cfg.instruction,
        "registration_root": cfg["registration_root"],
        "controller_id": cfg["controller_id"],
        "run_spec_sha256": cfg["run_spec_sha256"],
    }
    assert validate_registered_trajectories((trajectory,), **kwargs)[0] is trajectory
    saved = Path(cfg["registration_root"]) / "run-1" / "registration.json"
    response = receipt(cfg, template, 45679)
    saved.write_bytes(json.dumps(response, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode())
    with pytest.raises(ValueError):
        validate_registered_trajectories((trajectory,), **kwargs)
