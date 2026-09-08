import asyncio
from types import SimpleNamespace

import pytest

from tests.uni_agent.tasks.test_harbor_dsh_protocol import payload, policy
from uni_agent.tasks.harbor_dsh.ledger import JobLedger
from uni_agent.tasks.harbor_dsh.worker import HarborWorker


@pytest.mark.asyncio
async def test_worker_executes_once_and_seals_downloads(tmp_path):
    calls = []

    async def execute(request, **kwargs):
        calls.append(request.job_id)
        await kwargs["on_verifying"]()
        return SimpleNamespace(
            trial_id="trial-1",
            cleanup_confirmed=True,
            artifacts={
                kind: b"proof" for kind in ("dsh_trace", "dsh_result", "harbor_result", "verifier_log", "reward")
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
        assert worker.submit(data)["status"] == "queued"
        await worker.wait(data["job_id"])
        assert worker.submit(data)["status"] == "succeeded"
        manifest = worker.manifest(data["job_id"])
        assert len(manifest["artifacts"]) == 5 and calls == ["job-1"]
        assert worker.artifact("job-1", manifest["artifacts"][0]["id"]) == b"proof"
        with pytest.raises(KeyError):
            worker.artifact("job-1", "../../ledger.sqlite")


@pytest.mark.asyncio
async def test_unknown_failure_never_becomes_success_or_auto_retry(tmp_path):
    async def execute(*args, **kwargs):
        raise RuntimeError("cleanup unknown")

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
        worker.submit(data)
        await worker.wait("job-1")
        assert ledger.get("job-1")["status"] == "running"
        assert ledger.get("job-1")["manifest"] is None
        assert (tmp_path / "worker/job-1/unconfirmed.json").exists()
        assert worker.status("job-1")["unconfirmed"]["cleanup_confirmed"] is False
        with pytest.raises(ValueError):
            worker.manifest("job-1")


@pytest.mark.asyncio
async def test_cancel_waits_for_executor_and_keeps_unconfirmed_state(tmp_path):
    entered = asyncio.Event()
    stopped = asyncio.Event()

    async def execute(*args, **kwargs):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

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
        worker.submit(data)
        await entered.wait()
        status = await worker.cancel("job-1")
        assert stopped.is_set()
        assert status["status"] == "cancelling" and status["manifest"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("trigger", ["double_cancel", "handler_cancel", "timeout_then_cancel"])
async def test_cancellation_never_interrupts_executor_cleanup(tmp_path, trigger):
    entered, cleaning, release, cleaned = (asyncio.Event() for _ in range(4))

    async def execute(*args, **kwargs):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaning.set()
            await release.wait()
            cleaned.set()

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
            clock=lambda: data["budgets"]["deadline_unix"] - 0.05 if trigger == "timeout_then_cancel" else 1000.0,
        )
        worker.submit(data)
        await entered.wait()
        callers = []
        if trigger != "timeout_then_cancel":
            callers.append(asyncio.create_task(worker.cancel("job-1")))
        await asyncio.wait_for(cleaning.wait(), 1)
        if trigger == "handler_cancel":
            callers[0].cancel()
            await asyncio.gather(callers[0], return_exceptions=True)
        else:
            callers.append(asyncio.create_task(worker.cancel("job-1")))
        # Let the duplicate cancel / interrupted HTTP waiter reach the worker.
        for _ in range(5):
            await asyncio.sleep(0)
        release.set()
        await asyncio.wait_for(asyncio.gather(*callers, return_exceptions=True), 1)
        await worker.wait("job-1")
        assert cleaned.is_set()
        assert worker.status("job-1")["manifest"] is None
        assert worker.status("job-1")["unconfirmed"]["cleanup_confirmed"] is False
