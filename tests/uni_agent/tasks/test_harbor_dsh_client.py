import asyncio
import hashlib
import time
from types import SimpleNamespace

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from tests.uni_agent.tasks.test_harbor_dsh_protocol import manifest, payload, policy
from uni_agent.tasks.harbor_dsh.client import HarborDshClient, HarborDshClientError
from uni_agent.tasks.harbor_dsh.ledger import JobLedger
from uni_agent.tasks.harbor_dsh.protocol import JobManifest, JobRequest, request_sha256
from uni_agent.tasks.harbor_dsh.worker import HarborWorker
from uni_agent.tasks.harbor_dsh.worker_http import create_app

pytestmark = [pytest.mark.cpu, pytest.mark.level0]
TOKEN = "a" * 32


def request_data(seconds=10.0):
    data = payload()
    data["budgets"]["wall_time_seconds"] = seconds
    data["budgets"]["deadline_unix"] = time.time() + seconds - 0.001
    data["request_sha256"] = request_sha256(data)
    return data


def client(server, data, **kwargs):
    return HarborDshClient(
        base_url=str(server.make_url("/")).rstrip("/"),
        token=TOKEN,
        worker_id="worker-1",
        policy=policy(data),
        poll_interval_seconds=0.001,
        cancel_timeout_seconds=0.05,
        **kwargs,
    )


class ScriptedWorker:
    def __init__(self, data):
        self.request = JobRequest.model_validate(data)
        self.result = manifest(self.request)
        self.contents = {entry["id"]: b"abc" for entry in self.result["artifacts"]}
        for entry in self.result["artifacts"]:
            entry["sha256"] = "sha256:" + hashlib.sha256(b"abc").hexdigest()
        self.state = "succeeded"
        self.cancelled = 0
        self.downloads = []
        self.bad_hash = False
        self.unconfirmed = False
        self.cancel_error = False

    def status(self, job_id):
        response = {
            "job_id": job_id,
            "status": self.state,
            "request": {"request_sha256": "wrong" if self.bad_hash else self.request.request_sha256},
        }
        if self.unconfirmed:
            response["unconfirmed"] = {"cleanup_confirmed": False}
        return response

    def submit(self, data):
        assert data == self.request.model_dump(mode="json", by_alias=True)
        return self.status(self.request.job_id)

    async def cancel(self, job_id):
        self.cancelled += 1
        if self.cancel_error:
            raise ValueError("cancel failed")
        return self.status(job_id)

    def manifest(self, job_id):
        return self.result

    def artifact(self, job_id, artifact_id):
        self.downloads.append(artifact_id)
        return self.contents[artifact_id]


@pytest.mark.asyncio
async def test_real_http_worker_ledger_and_bounded_client(tmp_path):
    data = request_data()

    async def execute(request, **kwargs):
        await kwargs["on_verifying"]()
        return SimpleNamespace(
            trial_id="trial-1",
            cleanup_confirmed=True,
            artifacts={
                kind: b"raw evidence" for kind in ("dsh_trace", "dsh_result", "harbor_result", "verifier_log", "reward")
            },
        )

    with JobLedger(tmp_path / "ledger.sqlite") as ledger:
        worker = HarborWorker(
            ledger=ledger,
            policy=policy(data),
            worker_id="worker-1",
            task_dir=tmp_path,
            root=tmp_path / "worker",
            gateway_base_url="http://host.docker.internal:45678",
            executor=execute,
        )
        async with TestServer(create_app(worker, token=TOKEN)) as server:
            result = await client(server, data).run(JobRequest.model_validate(data))
            assert isinstance(result.manifest, JobManifest)
            assert result.manifest.status == "succeeded"
            assert set(result.artifacts) == {entry.id for entry in result.manifest.artifacts}
            assert list(result.artifacts.values()) == [b"raw evidence"] * 5
            await worker.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["hash", "unconfirmed", "failed", "cancelled", "cancelling"])
async def test_submission_rejects_untrusted_or_failed_state_and_preserves_error(failure):
    data = request_data()
    worker = ScriptedWorker(data)
    if failure == "hash":
        worker.bad_hash = True
    elif failure == "unconfirmed":
        worker.unconfirmed = True
    else:
        worker.state = failure
    worker.cancel_error = True
    async with TestServer(create_app(worker, token=TOKEN)) as server:
        with pytest.raises(HarborDshClientError, match="identity|unconfirmed|state"):
            await client(server, data).run(JobRequest.model_validate(data))
    assert worker.cancelled == 1
    assert worker.downloads == []


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["worker_id", "nonce", "request_sha256", "gateway_session_id"])
async def test_manifest_must_bind_operator_worker_and_published_request(field):
    data = request_data()
    worker = ScriptedWorker(data)
    worker.result[field] = "c" * 32 if field == "nonce" else "forged"
    async with TestServer(create_app(worker, token=TOKEN)) as server:
        with pytest.raises(ValueError):
            await client(server, data).run(JobRequest.model_validate(data))
    assert worker.downloads == []


@pytest.mark.asyncio
@pytest.mark.parametrize("content", [b"ab", b"abd", b"abcd", b"x" * 100000])
async def test_artifact_length_and_hash_are_verified(content):
    data = request_data()
    worker = ScriptedWorker(data)
    worker.contents["obj-0"] = content
    async with TestServer(create_app(worker, token=TOKEN)) as server:
        with pytest.raises(ValueError, match="limit|length|hash"):
            await client(server, data).run(JobRequest.model_validate(data))
    assert worker.downloads == ["obj-0"]


@pytest.mark.asyncio
async def test_manifest_total_budget_rejected_before_download():
    data = request_data()
    worker = ScriptedWorker(data)
    worker.result["artifacts"][0]["size_bytes"] = 10001
    async with TestServer(create_app(worker, token=TOKEN)) as server:
        with pytest.raises(ValueError, match="budget"):
            await client(server, data).run(JobRequest.model_validate(data))
    assert worker.downloads == []


@pytest.mark.asyncio
async def test_whole_run_deadline_cancels_waiting_job():
    data = request_data(0.15)
    worker = ScriptedWorker(data)
    worker.state = "running"
    async with TestServer(create_app(worker, token=TOKEN)) as server:
        with pytest.raises(TimeoutError):
            await client(server, data).run(JobRequest.model_validate(data))
    assert worker.cancelled == 1


@pytest.mark.asyncio
async def test_parent_cancellation_is_preserved():
    data = request_data()
    worker = ScriptedWorker(data)
    worker.state = "running"
    submitted = asyncio.Event()
    original_submit = worker.submit

    def submit(data):
        submitted.set()
        return original_submit(data)

    worker.submit = submit
    async with TestServer(create_app(worker, token=TOKEN)) as server:
        task = asyncio.create_task(client(server, data).run(JobRequest.model_validate(data)))
        await submitted.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert worker.cancelled == 1


@pytest.mark.asyncio
async def test_redirect_is_not_followed_or_authorized():
    hits = []

    async def redirected(request):
        hits.append(request.headers.get("Authorization"))
        return web.Response()

    target = web.Application()
    target.router.add_route("*", "/{tail:.*}", redirected)
    async with TestServer(target) as target_server:

        async def redirect(request):
            raise web.HTTPTemporaryRedirect(str(target_server.make_url("/capture")))

        app = web.Application()
        app.router.add_route("*", "/{tail:.*}", redirect)
        async with TestServer(app) as server:
            data = request_data()
            with pytest.raises(HarborDshClientError, match="HTTP"):
                await client(server, data).run(JobRequest.model_validate(data))
    assert hits == []


@pytest.mark.asyncio
async def test_json_body_has_incremental_limit():
    async def oversized(request):
        return web.Response(body=b" " * 65537, status=202)

    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", oversized)
    async with TestServer(app) as server:
        data = request_data()
        with pytest.raises(HarborDshClientError, match="limit"):
            await client(server, data).run(JobRequest.model_validate(data))


@pytest.mark.parametrize(
    "origin",
    [
        "http://localhost:1",
        "http://10.0.0.2:1",
        "https://127.0.0.1:1",
        "http://u:p@127.0.0.1:1",
        "http://127.0.0.1:1/path",
        "http://127.0.0.1:1?x=1",
        "http://127.0.0.1",
        "http://127.0.0.1:1#fragment",
    ],
)
def test_operator_origin_must_be_explicit_loopback(origin):
    data = request_data()
    with pytest.raises(ValueError):
        HarborDshClient(base_url=origin, token=TOKEN, worker_id="worker-1", policy=policy(data))


@pytest.mark.asyncio
async def test_chunked_artifact_overrun_is_rejected_without_content_length():
    data = request_data()
    worker = ScriptedWorker(data)

    @web.middleware
    async def chunked(request, handler):
        if "/artifacts/" not in request.path:
            return await handler(request)
        response = web.StreamResponse()
        await response.prepare(request)
        await response.write(b"ab")
        await response.write(b"cd")
        await response.write_eof()
        return response

    app = create_app(worker, token=TOKEN)
    app.middlewares.append(chunked)
    async with TestServer(app) as server:
        with pytest.raises(HarborDshClientError, match="limit"):
            await client(server, data).run(JobRequest.model_validate(data))
    assert worker.cancelled == 1


@pytest.mark.asyncio
async def test_download_is_inside_whole_run_deadline():
    data = request_data(0.15)
    worker = ScriptedWorker(data)
    release = asyncio.Event()

    @web.middleware
    async def stalled(request, handler):
        if "/artifacts/" in request.path:
            await release.wait()
        return await handler(request)

    app = create_app(worker, token=TOKEN)
    app.middlewares.append(stalled)
    async with TestServer(app) as server:
        try:
            with pytest.raises(TimeoutError):
                await client(server, data).run(JobRequest.model_validate(data))
        finally:
            release.set()
    assert worker.cancelled == 1


@pytest.mark.asyncio
async def test_poll_rechecks_request_hash():
    data = request_data()
    worker = ScriptedWorker(data)
    worker.state = "running"
    original_submit = worker.submit

    def submit(data):
        result = original_submit(data)
        worker.bad_hash = True
        return result

    worker.submit = submit
    async with TestServer(create_app(worker, token=TOKEN)) as server:
        with pytest.raises(HarborDshClientError, match="identity"):
            await client(server, data).run(JobRequest.model_validate(data))
    assert worker.downloads == []


@pytest.mark.asyncio
async def test_independent_policy_rejects_request_before_submission():
    data = request_data()
    worker = ScriptedWorker(data)
    altered = request_data()
    altered["task_ref"]["id"] = "not-approved"
    altered["request_sha256"] = request_sha256(altered)
    async with TestServer(create_app(worker, token=TOKEN)) as server:
        with pytest.raises(ValueError, match="not approved"):
            await client(server, data).run(JobRequest.model_validate(altered))
    assert worker.cancelled == 0
    assert worker.downloads == []


@pytest.mark.parametrize("token", ["short", "a" * 32 + "\n", "a" * 32 + " ", "界" * 32])
def test_invalid_auth_token_is_rejected(token):
    data = request_data()
    with pytest.raises(ValueError, match="token"):
        HarborDshClient(base_url="http://127.0.0.1:47081", token=token, worker_id="worker-1", policy=policy(data))
