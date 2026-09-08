import pytest
from aiohttp.test_utils import TestClient, TestServer

from uni_agent.tasks.harbor_dsh.worker_http import create_app


class FakeWorker:
    def submit(self, data):
        return {"job_id": "job-1", "status": "queued", "request": {"request_sha256": "sha256:test"}}

    def manifest(self, job_id):
        raise ValueError("not sealed")

    def artifact(self, job_id, artifact_id):
        raise KeyError(artifact_id)


@pytest.mark.asyncio
async def test_auth_and_unsealed_result_refusal():
    app = create_app(FakeWorker(), token="a" * 32)
    async with TestClient(TestServer(app)) as client:
        response = await client.post("/v1/jobs", json={})
        assert response.status == 401
        headers = {"Authorization": "Bearer " + "a" * 32}
        response = await client.post("/v1/jobs", json={}, headers=headers)
        assert response.status == 202
        assert (await response.json())["status"] == "queued"
        response = await client.get("/v1/jobs/job-1/manifest", headers=headers)
        assert response.status == 409
        response = await client.get("/v1/jobs/job-1/artifacts/not-published", headers=headers)
        assert response.status == 404


@pytest.mark.asyncio
async def test_http_uses_real_ledger_and_returns_only_sealed_artifacts(tmp_path):
    from types import SimpleNamespace

    from tests.uni_agent.tasks.test_harbor_dsh_protocol import payload, policy
    from uni_agent.tasks.harbor_dsh.ledger import JobLedger
    from uni_agent.tasks.harbor_dsh.worker import HarborWorker

    async def execute(request, **kwargs):
        await kwargs["on_verifying"]()
        return SimpleNamespace(
            trial_id="trial-1",
            cleanup_confirmed=True,
            artifacts={
                kind: b"bytes" for kind in ("dsh_trace", "dsh_result", "harbor_result", "verifier_log", "reward")
            },
        )

    data = payload()
    with JobLedger(tmp_path / "ledger.sqlite") as ledger:
        worker = HarborWorker(
            ledger=ledger,
            policy=policy(data),
            worker_id="worker-1",
            task_dir=tmp_path,
            root=tmp_path / "worker",
            gateway_base_url="http://host.docker.internal:45678",
            executor=execute,
            clock=lambda: 1000.0,
        )
        async with TestClient(TestServer(create_app(worker, token="a" * 32))) as client:
            headers = {"Authorization": "Bearer " + "a" * 32}
            response = await client.post("/v1/jobs", json=data, headers=headers)
            assert response.status == 202
            await worker.wait("job-1")
            response = await client.get("/v1/jobs/job-1", headers=headers)
            assert (await response.json())["status"] == "succeeded"
            response = await client.get("/v1/jobs/job-1/manifest", headers=headers)
            manifest = await response.json()
            object_id = manifest["artifacts"][0]["id"]
            response = await client.get("/v1/jobs/job-1/artifacts/" + object_id, headers=headers)
            assert await response.read() == b"bytes"
