"""Bounded controller transport over an operator-owned SSH loopback forward.

Success means verified transport of sealed worker evidence, not RL admission.
The caller owns the request, route policy, worker identity and later receipt audit.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import math
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

import aiohttp
from pydantic import TypeAdapter

from .protocol import (
    JobManifest,
    JobRequest,
    OpaqueId,
    RequestPolicy,
    validate_artifact,
    validate_manifest,
    validate_request,
)


class HarborDshClientError(ValueError):
    """Rejected HTTP status, job identity, state or bounded response."""


@dataclass(frozen=True)
class DownloadedJob:
    manifest: JobManifest
    artifacts: dict[str, bytes]


class HarborDshClient:
    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        worker_id: str,
        policy: RequestPolicy,
        poll_interval_seconds: float = 0.25,
        cancel_timeout_seconds: float = 2.0,
    ):
        route = urlsplit(base_url)
        if (
            base_url != base_url.strip()
            or route.scheme != "http"
            or not route.hostname
            or not ipaddress.ip_address(route.hostname).is_loopback
            or not route.port
            or route.username is not None
            or route.password is not None
            or route.path not in ("", "/")
            or route.query
            or route.fragment
        ):
            raise ValueError("Expected an operator-owned loopback HTTP origin with explicit port")
        if len(token) < 32 or any(not 33 <= ord(character) <= 126 for character in token):
            raise ValueError("Expected a private printable ASCII run token of at least 32 characters")
        for value in (poll_interval_seconds, cancel_timeout_seconds):
            if isinstance(value, bool) or not math.isfinite(value) or not 0 < value <= 5:
                raise ValueError("Polling and cancellation intervals must be finite and at most five seconds")
        self.base_url = base_url.rstrip("/")
        self._token = token
        self.worker_id = TypeAdapter(OpaqueId).validate_python(worker_id)
        self.policy = RequestPolicy.model_validate(policy)
        self.poll_interval_seconds = poll_interval_seconds
        self.cancel_timeout_seconds = cancel_timeout_seconds

    async def _read(self, response: aiohttp.ClientResponse, *, expected_status: int, limit: int) -> bytes:
        if response.status != expected_status:
            raise HarborDshClientError(f"Unexpected worker HTTP status: {response.status}")
        if response.headers.get("Content-Encoding", "identity").lower() != "identity":
            raise HarborDshClientError("Encoded worker responses are not accepted")
        if response.content_length is not None and response.content_length > limit:
            raise HarborDshClientError("Response exceeds byte limit")
        content = bytearray()
        async for chunk in response.content.iter_chunked(min(8192, limit + 1)):
            if len(content) + len(chunk) > limit:
                raise HarborDshClientError("Response exceeds byte limit")
            content.extend(chunk)
        return bytes(content)

    async def _json(self, session, method, path, *, expected_status=200, data=None):
        async with session.request(method, self.base_url + path, json=data, allow_redirects=False) as response:
            raw = await self._read(response, expected_status=expected_status, limit=65536)
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise HarborDshClientError("Expected a worker JSON object")
        return value

    @staticmethod
    def _status(value: dict, request: JobRequest) -> str:
        if value.get("job_id") != request.job_id or value.get("accepted_request_sha256") != request.request_sha256:
            raise HarborDshClientError("Worker status identity mismatch")
        if "unconfirmed" in value:
            raise HarborDshClientError("Worker execution or cleanup is unconfirmed")
        if set(value) != {"job_id", "status", "accepted_request_sha256"}:
            raise HarborDshClientError("Unexpected worker status fields")
        state = value.get("status")
        if state not in ("queued", "running", "verifying", "succeeded"):
            raise HarborDshClientError("Worker job state cannot yield trusted evidence")
        return state

    async def run(self, request: JobRequest) -> DownloadedJob:
        now = time.time()
        # Revalidate even typed objects; never derive policy from server responses.
        request = validate_request(request.model_dump(mode="json", by_alias=True), policy=self.policy, now_unix=now)
        timeout = min(request.budgets.wall_time_seconds, request.budgets.deadline_unix - now)
        job_path = f"/v1/jobs/{request.job_id}"
        async with aiohttp.ClientSession(
            headers={"Authorization": "Bearer " + self._token},
            timeout=aiohttp.ClientTimeout(total=None),
            trust_env=False,
            auto_decompress=False,
            cookie_jar=aiohttp.DummyCookieJar(),
            read_bufsize=8192,
        ) as session:
            try:
                async with asyncio.timeout(timeout):
                    status = self._status(
                        await self._json(
                            session,
                            "POST",
                            "/v1/jobs",
                            expected_status=202,
                            data=request.model_dump(mode="json", by_alias=True),
                        ),
                        request,
                    )
                    while status != "succeeded":
                        await asyncio.sleep(self.poll_interval_seconds)
                        status = self._status(await self._json(session, "GET", job_path), request)
                    manifest = validate_manifest(
                        await self._json(session, "GET", job_path + "/manifest"),
                        request=request,
                        worker_id=self.worker_id,
                    )
                    if manifest.status != "succeeded":
                        raise HarborDshClientError("Worker manifest state is not succeeded")
                    artifacts = {}
                    for artifact in manifest.artifacts:
                        async with session.get(
                            self.base_url + job_path + "/artifacts/" + artifact.id, allow_redirects=False
                        ) as response:
                            content = await self._read(response, expected_status=200, limit=artifact.size_bytes)
                        validate_artifact(artifact, content)
                        artifacts[artifact.id] = content
                    return DownloadedJob(manifest=manifest, artifacts=artifacts)
            except (Exception, asyncio.CancelledError) as error:
                # Submission may have reached the worker even if its response was
                # lost. Cancel once, without retrying work or claiming cleanup.
                try:
                    async with asyncio.timeout(self.cancel_timeout_seconds):
                        await self._json(session, "POST", job_path + "/cancel")
                except (Exception, asyncio.CancelledError):
                    error.add_note("Worker cancellation could not be confirmed; do not automatically retry this job")
                else:
                    error.add_note("Cancellation requested; remote cleanup remains subject to worker reconciliation")
                raise
