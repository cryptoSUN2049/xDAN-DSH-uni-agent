"""One Mac-owned run: register a live Gateway port, then start its frozen worker.

Run with python -m deployment.services.harbor_run_controller --run-spec PATH.
No job payload can approve a route. Only the separate registration credential
held by the trusted runner can fill the single initially unknown gateway port.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import ipaddress
import json
import math
import os
import stat
import time
from pathlib import Path
from typing import Annotated

from aiohttp import web
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from deployment.services.harbor_tunnel import SshTunnel
from uni_agent.tasks.harbor_dsh.protocol import OpaqueId, Port, RequestPolicy, Sha256


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def digest(value):
    return "sha256:" + hashlib.sha256(canonical(value)).hexdigest()


def persist(path, value):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        output.write(canonical(value))
        output.flush()
        os.fsync(output.fileno())
    parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(parent)
    finally:
        os.close(parent)


def read_token(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("Credential file must be owned, regular and private")
        raw = source.read(4097)
    token = raw.decode().strip()
    if not 32 <= len(token) <= 4096 or any(ord(c) < 33 or ord(c) > 126 for c in token):
        raise ValueError("Invalid private credential")
    return token


class RunSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    run_id: OpaqueId
    controller_id: OpaqueId
    worker_id: OpaqueId
    deadline_unix: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    policy_template: dict
    root: Path
    task_dir: Path
    registration_token_file: Path
    worker_token_file: Path
    ssh_host: str
    ssh_port: Port
    ssh_user: Annotated[str, Field(pattern=r"^[a-z_][a-z0-9_-]*$")]
    ssh_key: Path
    known_hosts: Path
    control_port: Port
    worker_port: Port
    model_port: Port
    remote_control_port: Port
    remote_worker_port: Port

    @field_validator("ssh_host")
    @classmethod
    def _ssh_ip(cls, value):
        address = ipaddress.ip_address(value)
        if address.version != 4 or address.is_unspecified or address.is_multicast:
            raise ValueError("First run requires a specific IPv4 SSH host")
        return str(address)

    @field_validator("policy_template")
    @classmethod
    def _template(cls, value):
        if "gateway_port" in value:
            raise ValueError("Operator template must leave gateway_port unbound")
        template = RequestPolicy.model_validate({**value, "gateway_port": 1}).model_dump(mode="json")
        template.pop("gateway_port")
        address = ipaddress.ip_address(template["gateway_host"])
        if address.version != 4 or address.is_unspecified or address.is_multicast:
            raise ValueError("First run requires one specific IPv4 Gateway node")
        template["gateway_host"] = str(address)
        return template

    @model_validator(mode="after")
    def _paths_ports(self):
        for name in ("root", "task_dir", "registration_token_file", "worker_token_file", "ssh_key", "known_hosts"):
            path = getattr(self, name)
            if not path.is_absolute() or ".." in path.parts:
                raise ValueError("Operator paths must be absolute and traversal-free")
        if (
            len({self.control_port, self.worker_port, self.model_port}) != 3
            or self.remote_control_port == self.remote_worker_port
        ):
            raise ValueError("Owned forwarding/listening ports must be distinct")
        return self


class Registration(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    gateway_host: str
    gateway_port: Port
    run_spec_sha256: Sha256


class WorkerService:
    def __init__(self, worker, ledger, runner):
        self.worker, self.ledger, self.runner = worker, ledger, runner
        self.alive = True

    async def close(self):
        if not self.alive:
            return
        self.alive = False
        for site in tuple(self.runner.sites):
            await site.stop()
        await self.worker.close()
        await self.runner.cleanup()
        self.ledger.__exit__(None, None, None)


async def start_worker(spec, policy):
    from uni_agent.tasks.harbor_dsh.ledger import JobLedger
    from uni_agent.tasks.harbor_dsh.worker import HarborWorker
    from uni_agent.tasks.harbor_dsh.worker_http import create_app as worker_app

    ledger = JobLedger(spec.root / "jobs.sqlite")

    class RunWorker(HarborWorker):
        def submit(self, data):
            if data.get("run_id") != spec.run_id:
                raise ValueError("Job is not part of this controller run")
            return super().submit(data)

    worker = RunWorker(
        ledger=ledger,
        policy=policy,
        worker_id=spec.worker_id,
        task_dir=spec.task_dir,
        root=spec.root / "jobs",
        gateway_base_url=f"http://host.docker.internal:{spec.model_port}",
    )
    runner = web.AppRunner(worker_app(worker, token=read_token(spec.worker_token_file)), access_log=None)
    try:
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", spec.worker_port).start()
    except BaseException:
        await runner.cleanup()
        await worker.close()
        ledger.__exit__(None, None, None)
        raise
    return WorkerService(worker, ledger, runner)


class HarborRunController:
    def __init__(self, spec, *, tunnel_factory=SshTunnel, worker_factory=start_worker, clock=time.time):
        self.spec = RunSpec.model_validate(spec.model_dump(mode="json"))
        self.spec_sha256 = digest(self.spec.model_dump(mode="json"))
        self.token = read_token(self.spec.registration_token_file)
        if hmac.compare_digest(self.token, read_token(self.spec.worker_token_file)):
            raise ValueError("Registration and job credentials must differ")
        self.tunnel_factory, self.worker_factory, self.clock = tunnel_factory, worker_factory, clock
        self.control = self.model = self.worker = None
        self.receipt = None
        self.state = "new"
        self.lock = asyncio.Lock()
        self.root_owned = False

    def _check_time(self):
        now = self.clock()
        if isinstance(now, bool) or not math.isfinite(now) or not now < self.spec.deadline_unix:
            raise ValueError("Run deadline expired")

    async def start(self):
        self._check_time()
        if self.state != "new":
            raise ValueError("Controller cannot restart a run")
        self.spec.root.mkdir(mode=0o700, parents=True, exist_ok=False)
        self.root_owned = True
        persist(self.spec.root / "run-spec.json", self.spec.model_dump(mode="json"))
        self.control = self.tunnel_factory(self.spec, kind="control")
        try:
            await self.control.start()
            self._check_time()
            self.state = "unregistered"
        except BaseException:
            self.state = "failed"
            await self.control.close()
            raise

    async def register(self, run_id, data):
        registration = Registration.model_validate(data)
        async with self.lock:
            self._check_time()
            if self.state not in {"unregistered", "ready"} or not self.control.alive:
                raise ValueError("Run is not accepting registrations")
            if run_id != self.spec.run_id or registration.run_spec_sha256 != self.spec_sha256:
                raise ValueError("Wrong run identity")
            if registration.gateway_host != self.spec.policy_template["gateway_host"]:
                raise ValueError("Gateway node is not approved")
            if self.receipt is not None:
                if (
                    not self.model.alive
                    or not self.worker.alive
                    or registration.gateway_port != self.receipt["policy"]["gateway_port"]
                ):
                    raise ValueError("Registered endpoint changed or stopped")
                return json.loads(canonical(self.receipt))
            self.state = "registering"
            policy = RequestPolicy.model_validate(
                {**self.spec.policy_template, "gateway_port": registration.gateway_port}
            )
            try:
                persist(self.spec.root / "registration-intent.json", registration.model_dump(mode="json"))
                self.model = self.tunnel_factory(self.spec, kind="model", gateway_port=registration.gateway_port)
                await self.model.start()
                self._check_time()
                persist(self.spec.root / "effective-policy.json", policy.model_dump(mode="json"))
                self.worker = await asyncio.wait_for(
                    self.worker_factory(self.spec, policy), min(30, self.spec.deadline_unix - self.clock())
                )
                self._check_time()
                self.receipt = {
                    "schema": "dsh.harbor-route-registration.v1",
                    "run_id": self.spec.run_id,
                    "controller_id": self.spec.controller_id,
                    "run_spec_sha256": self.spec_sha256,
                    "policy_sha256": digest(policy.model_dump(mode="json")),
                    "policy": policy.model_dump(mode="json"),
                    "registered_at_unix": self.clock(),
                }
                persist(self.spec.root / "registration-receipt.json", self.receipt)
                self.state = "ready"
                return json.loads(canonical(self.receipt))
            except BaseException:
                self.state = "failed"
                try:
                    if self.worker is not None:
                        await asyncio.wait_for(self.worker.close(), 30)
                finally:
                    if self.model is not None:
                        await self.model.close()
                raise

    async def close(self):
        async with self.lock:
            if self.state == "closed":
                return
            self.state = "closed"
            failures = []
            for service in (self.worker, self.model, self.control):
                if service is not None:
                    try:
                        await asyncio.wait_for(service.close(), 30)
                    except (Exception, asyncio.CancelledError) as error:
                        failures.append(type(error).__name__)
            if self.root_owned:
                persist(
                    self.spec.root / "controller-stop.json",
                    {"cleanup_errors": failures, "docker_cleanup_proven": False},
                )
            if failures:
                raise RuntimeError("Controller shutdown has unconfirmed cleanup")


def create_app(controller):
    @web.middleware
    async def authenticate(request, handler):
        expected = ("Bearer " + controller.token).encode()
        if not hmac.compare_digest(request.headers.get("Authorization", "").encode(), expected):
            raise web.HTTPUnauthorized()
        try:
            return await handler(request)
        except (ValueError, TypeError, KeyError):
            raise web.HTTPConflict(text="Run registration rejected") from None
        except RuntimeError:
            raise web.HTTPServiceUnavailable(text="Run startup failed") from None

    async def register(request):
        value = await controller.register(request.match_info["run_id"], await request.json())
        return web.json_response(value)

    app = web.Application(middlewares=[authenticate], client_max_size=16384)
    app.router.add_post("/v1/runs/{run_id}/gateway", register)
    return app


async def main(path):
    spec = RunSpec.model_validate_json(path.read_bytes())
    if not 0 < spec.deadline_unix - time.time() <= 14400:
        raise ValueError("Run must have a future deadline within four hours")
    controller = HarborRunController(spec)
    runner = web.AppRunner(create_app(controller), access_log=None, shutdown_timeout=2)
    try:
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", spec.control_port).start()
        await controller.start()
        print(
            json.dumps({"run_id": spec.run_id, "state": controller.state, "run_spec_sha256": controller.spec_sha256}),
            flush=True,
        )
        while time.time() < spec.deadline_unix and controller.state != "failed":
            if not controller.control.alive or (controller.model is not None and not controller.model.alive):
                break
            await asyncio.sleep(min(1, max(0, spec.deadline_unix - time.time())))
    finally:
        await runner.cleanup()
        await controller.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-spec", type=Path, required=True)
    asyncio.run(main(parser.parse_args().run_spec))
