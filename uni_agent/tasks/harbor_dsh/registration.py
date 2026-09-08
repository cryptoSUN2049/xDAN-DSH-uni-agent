"""Register a real Framework session origin against one frozen controller spec."""

from __future__ import annotations

import asyncio
import fcntl
import hashlib
import ipaddress
import json
import os
import stat
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit
from uuid import uuid4

import aiohttp
from pydantic import Field, TypeAdapter

from uni_agent.gateway.session import SessionHandle

from .protocol import Contract, OpaqueId, RequestPolicy, Sha256
from .task import RunnerContext, _json, _object, _write
from .trajectory_audit import _private_directory, _read, validate_trajectories


def _canonical(value) -> bytes:
    # Controller contract deliberately has no trailing newline.
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def _digest(value) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


class RouteRegistrationConfig(Contract):
    controller_url: str
    token_file: str
    registration_root: str
    controller_id: OpaqueId
    run_spec_sha256: Sha256
    timeout_seconds: Annotated[float, Field(gt=0, le=60, allow_inf_nan=False)] = 30.0


class RegistrationReceipt(Contract):
    schema_: Literal["dsh.harbor-route-registration.v1"] = Field(alias="schema")
    run_id: OpaqueId
    controller_id: OpaqueId
    run_spec_sha256: Sha256
    policy_sha256: Sha256
    policy: RequestPolicy
    registered_at_unix: Annotated[float, Field(gt=0, allow_inf_nan=False)]


def _template(value: dict) -> dict:
    if not isinstance(value, dict) or "gateway_port" in value:
        raise ValueError("Operator policy template must leave gateway_port unbound")
    normalized = RequestPolicy.model_validate({**value, "gateway_port": 1}).model_dump(mode="json")
    normalized.pop("gateway_port")
    return normalized


def _validated_receipt(value, *, run_id, controller_id, run_spec_sha256, policy_template, port=None):
    receipt = RegistrationReceipt.model_validate(value)
    if (receipt.run_id, receipt.controller_id, receipt.run_spec_sha256) != (run_id, controller_id, run_spec_sha256):
        raise ValueError("Controller registration identity mismatch")
    policy = receipt.policy.model_dump(mode="json")
    if receipt.policy_sha256 != _digest(policy):
        raise ValueError("Controller policy hash mismatch")
    registered_port = policy.pop("gateway_port")
    if policy != _template(policy_template) or (port is not None and registered_port != port):
        raise ValueError("Controller policy differs from the operator template or real session port")
    return receipt


def _absolute(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("Operator path must be absolute and traversal-free")
    return path


def _token(path: str) -> str:
    path = _absolute(path)
    if any((parent / ".git").exists() for parent in path.resolve().parents):
        raise ValueError("Registration token must be outside a repository")
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        token = _read(directory, path.name, 4096).decode().strip()
    finally:
        os.close(directory)
    if not 32 <= len(token) <= 4096 or any(not 33 <= ord(c) <= 126 for c in token):
        raise ValueError("Invalid registration token")
    return token


def _run_directory(root: str, run_id: str, *, create: bool) -> int:
    path = _absolute(root)
    TypeAdapter(OpaqueId).validate_python(run_id)
    if create:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    root_fd = _private_directory(path)
    try:
        if create:
            try:
                os.mkdir(run_id, mode=0o700, dir_fd=root_fd)
            except FileExistsError:
                pass
        return _private_directory(run_id, dir_fd=root_fd)
    finally:
        os.close(root_fd)


async def _store(root: str, receipt: RegistrationReceipt):
    directory = _run_directory(root, receipt.run_id, create=True)
    lock = None
    temporary = None
    try:
        lock = os.open("registration.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        info = os.fstat(lock)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("Unsafe registration lock")
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                await asyncio.sleep(0.01)
        raw = _canonical(receipt.model_dump(mode="json", by_alias=True))
        try:
            previous = _read(directory, "registration.json", 65536)
        except FileNotFoundError:
            temporary = "registration-" + uuid4().hex
            _write(directory, temporary, raw)
            os.rename(temporary, "registration.json", src_dir_fd=directory, dst_dir_fd=directory)
            temporary = None
            os.fsync(directory)
        else:
            if previous != raw:
                raise ValueError("Existing registration differs; start a new run instead")
    finally:
        if temporary is not None:
            os.unlink(temporary, dir_fd=directory)
        if lock is not None:
            os.close(lock)
        os.close(directory)


async def ensure_harbor_route(
    *,
    session: SessionHandle,
    runner_context: dict,
    run_id: str,
    policy_template: dict,
    registration: dict | RouteRegistrationConfig,
) -> RequestPolicy:
    """Only the trusted runner supplies session/context and operator-only kwargs."""
    cfg = RouteRegistrationConfig.model_validate(registration)
    template = _template(policy_template)
    context = RunnerContext.model_validate(runner_context)
    TypeAdapter(OpaqueId).validate_python(run_id)
    if not isinstance(session, SessionHandle) or session.session_id != context.gateway_session_id:
        raise ValueError("Registration requires the real Framework SessionHandle and matching context")
    route = urlsplit(session.base_url)
    if (
        route.scheme != "http"
        or route.hostname != template["gateway_host"]
        or not route.port
        or route.username is not None
        or route.password is not None
        or route.query
        or route.fragment
        or route.path != f"/sessions/{session.session_id}/v1"
    ):
        raise ValueError("Session route differs from the approved Gateway origin/context")
    origin = urlsplit(cfg.controller_url)
    if (
        origin.scheme != "http"
        or not origin.hostname
        or not ipaddress.ip_address(origin.hostname).is_loopback
        or not origin.port
        or origin.username is not None
        or origin.password is not None
        or origin.path not in ("", "/")
        or origin.query
        or origin.fragment
    ):
        raise ValueError("Controller must use an operator-owned loopback HTTP origin")
    token = _token(cfg.token_file)
    async with asyncio.timeout(cfg.timeout_seconds):
        async with aiohttp.ClientSession(
            headers={"Authorization": "Bearer " + token},
            timeout=aiohttp.ClientTimeout(total=None),
            trust_env=False,
            auto_decompress=False,
            cookie_jar=aiohttp.DummyCookieJar(),
            read_bufsize=8192,
        ) as client:
            async with client.post(
                cfg.controller_url.rstrip("/") + f"/v1/runs/{run_id}/gateway",
                allow_redirects=False,
                json={
                    "gateway_host": route.hostname,
                    "gateway_port": route.port,
                    "run_spec_sha256": cfg.run_spec_sha256,
                },
            ) as response:
                if response.status != 200 or response.headers.get("Content-Encoding", "identity") != "identity":
                    raise ValueError("Controller registration HTTP response rejected")
                raw = bytearray()
                async for chunk in response.content.iter_chunked(8192):
                    if len(raw) + len(chunk) > 65536:
                        raise ValueError("Controller response exceeds byte limit")
                    raw.extend(chunk)
        receipt = _validated_receipt(
            _object(_json(bytes(raw))),
            run_id=run_id,
            controller_id=cfg.controller_id,
            run_spec_sha256=cfg.run_spec_sha256,
            policy_template=template,
            port=route.port,
        )
        await _store(cfg.registration_root, receipt)
    return receipt.policy


def load_registered_policy(
    *, registration_root: str, run_id: str, controller_id: str, run_spec_sha256: str, policy_template: dict
) -> RequestPolicy:
    """Load independent controller evidence; never select a port from task receipts."""
    directory = _run_directory(registration_root, run_id, create=False)
    try:
        raw = _read(directory, "registration.json", 65536)
    finally:
        os.close(directory)
    value = _object(_json(raw))
    if raw != _canonical(value):
        raise ValueError("Saved registration is not canonical")
    return _validated_receipt(
        value,
        run_id=run_id,
        controller_id=controller_id,
        run_spec_sha256=run_spec_sha256,
        policy_template=policy_template,
    ).policy


def validate_registered_trajectories(
    trajectories,
    *,
    context,
    artifact_root,
    run_id,
    worker_id,
    task_ref,
    policy_template,
    instruction,
    registration_root,
    controller_id,
    run_spec_sha256,
    t2_fixture=None,
):
    """Static FQN kwargs support a port learned only from independent registration."""
    policy = load_registered_policy(
        registration_root=registration_root,
        run_id=run_id,
        controller_id=controller_id,
        run_spec_sha256=run_spec_sha256,
        policy_template=policy_template,
    )
    return validate_trajectories(
        trajectories,
        context=context,
        artifact_root=artifact_root,
        run_id=run_id,
        worker_id=worker_id,
        task_ref=task_ref,
        policy=policy,
        instruction=instruction,
        t2_fixture=t2_fixture,
    )
