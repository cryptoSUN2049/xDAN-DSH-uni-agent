import copy

import pytest

from tests.uni_agent.tasks.test_harbor_dsh_protocol import manifest, payload, policy
from uni_agent.tasks.harbor_dsh.ledger import JobLedger
from uni_agent.tasks.harbor_dsh.protocol import JobRequest, request_sha256


def second(data):
    data = copy.deepcopy(data)
    for field in ("job_id", "idempotency_key", "gateway_session_id"):
        data[field] += "-2"
    data["nonce"] = "cd" * 16
    data["model_route"]["session_path"] = "/sessions/" + data["gateway_session_id"] + "/v1"
    data["request_sha256"] = request_sha256(data)
    return data


def test_restart_keeps_identity_and_does_not_repeat_running_job(tmp_path):
    data = payload()
    with JobLedger(tmp_path / "jobs.sqlite") as jobs:
        assert jobs.submit(data, policy=policy(data), now_unix=1000)["status"] == "queued"
        jobs.start(data["job_id"], now_unix=1000)
    with JobLedger(tmp_path / "jobs.sqlite") as jobs:
        assert jobs.submit(data, policy=policy(data), now_unix=1200)["status"] == "running"
        with pytest.raises(ValueError):
            jobs.start(data["job_id"], now_unix=1000)


def test_two_connections_cannot_start_two_jobs_or_reuse_nonce(tmp_path):
    data = payload()
    with JobLedger(tmp_path / "jobs.sqlite") as one, JobLedger(tmp_path / "jobs.sqlite") as two:
        one.submit(data, policy=policy(data), now_unix=1000)
        other = second(data)
        two.submit(other, policy=policy(data), now_unix=1000)
        one.start(data["job_id"], now_unix=1000)
        with pytest.raises(ValueError):
            two.start(other["job_id"], now_unix=1000)
        other["job_id"] += "-3"
        other["request_sha256"] = request_sha256(other)
        with pytest.raises(ValueError):
            two.submit(other, policy=policy(data), now_unix=1000)


def test_cancel_does_not_claim_cleanup_or_release_running_slot(tmp_path):
    data = payload()
    with JobLedger(tmp_path / "jobs.sqlite") as jobs:
        jobs.submit(data, policy=policy(data), now_unix=1000)
        jobs.start(data["job_id"], now_unix=1000)
        assert jobs.cancel(data["job_id"])["status"] == "cancelling"
        assert jobs.cancel(data["job_id"])["status"] == "cancelling"
        assert jobs.get(data["job_id"])["manifest"] is None


def test_conflicting_idempotency_and_expired_new_request_rejected(tmp_path):
    data = payload()
    with JobLedger(tmp_path / "jobs.sqlite") as jobs:
        jobs.submit(data, policy=policy(data), now_unix=1000)
        conflict = copy.deepcopy(data)
        conflict["budgets"]["max_tokens"] -= 1
        conflict["request_sha256"] = request_sha256(conflict)
        with pytest.raises(ValueError):
            jobs.submit(conflict, policy=policy(data), now_unix=1000)
        with pytest.raises(ValueError):
            jobs.submit(second(data), policy=policy(data), now_unix=1200)


def test_success_requires_verification_and_seal_is_immutable(tmp_path):
    data = payload()
    receipt = manifest(JobRequest.model_validate(data))
    with JobLedger(tmp_path / "jobs.sqlite") as jobs:
        jobs.submit(data, policy=policy(data), now_unix=1000)
        jobs.start(data["job_id"], now_unix=1000)
        with pytest.raises(ValueError):
            jobs.seal(data["job_id"], receipt, worker_id="worker-1")
        jobs.verifying(data["job_id"])
        assert jobs.seal(data["job_id"], receipt, worker_id="worker-1")["status"] == "succeeded"
        assert jobs.cancel(data["job_id"])["status"] == "succeeded"
        receipt["sealed_at_unix"] += 1
        with pytest.raises(ValueError):
            jobs.seal(data["job_id"], receipt, worker_id="worker-1")


def test_queued_expiry_and_cancel_acknowledgement(tmp_path):
    data = payload()
    with JobLedger(tmp_path / "jobs.sqlite") as jobs:
        jobs.submit(data, policy=policy(data), now_unix=1000)
        with pytest.raises(ValueError):
            jobs.start(data["job_id"], now_unix=1200)
        assert jobs.get(data["job_id"])["status"] == "queued"
        jobs.cancel(data["job_id"])
        receipt = manifest(JobRequest.model_validate(data))
        receipt.update(status="cancelled", trial_id=None, artifacts=[], error_code="cancel-before-start")
        assert jobs.seal(data["job_id"], receipt, worker_id="worker-1")["status"] == "cancelled"


def test_parallel_start_claims_only_one_slot(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    path = tmp_path / "jobs.sqlite"
    data = payload()
    other = second(data)
    with JobLedger(path) as jobs:
        jobs.submit(data, policy=policy(data), now_unix=1000)
        jobs.submit(other, policy=policy(data), now_unix=1000)
    barrier = Barrier(2)

    def claim(job_id):
        with JobLedger(path) as jobs:
            barrier.wait(timeout=5)
            try:
                jobs.start(job_id, now_unix=1000)
                return True
            except ValueError:
                return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(claim, (data["job_id"], other["job_id"]))) == [False, True]
