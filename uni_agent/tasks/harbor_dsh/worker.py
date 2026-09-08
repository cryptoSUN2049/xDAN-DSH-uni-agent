"""Single-job orchestration over the durable ledger and real Harbor executor."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from pathlib import Path
from urllib.parse import urlparse

from .execution_outcome import CleanExecutionRejected
from .ledger import JobLedger
from .protocol import Artifact, JobRequest, RequestPolicy, validate_artifact, validate_manifest


def _persist(path: Path, content: bytes) -> None:
    with path.open("xb") as output:
        output.write(content)
        output.flush()
        os.fsync(output.fileno())
    path.chmod(0o600)
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class HarborWorker:
    def __init__(
        self,
        *,
        ledger: JobLedger,
        policy: RequestPolicy,
        worker_id: str,
        task_dir: Path,
        root: Path,
        gateway_base_url: str,
        executor=None,
        clock=time.time,
    ):
        route = urlparse(gateway_base_url)
        if (
            route.scheme != "http"
            or route.hostname != "host.docker.internal"
            or not route.port
            or route.path not in ("", "/")
            or route.query
            or route.fragment
            or route.username
            or route.password
        ):
            raise ValueError("Expected operator-owned Docker-to-host HTTP tunnel origin")
        if executor is None:
            from .executor import execute_job

            executor = execute_job
        self.ledger, self.policy, self.worker_id = ledger, policy, worker_id
        self.task_dir, self.root = task_dir.resolve(), root.resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.gateway_base_url = gateway_base_url.rstrip("/")
        self.executor, self.clock = executor, clock
        self.tasks: dict[str, asyncio.Task] = {}
        self.executions: dict[str, asyncio.Task] = {}

    def submit(self, data: dict) -> dict:
        request = JobRequest.model_validate(data)
        try:
            self.ledger.get(request.job_id)
            existed = True
        except KeyError:
            existed = False
        if not existed and any(not task.done() for task in self.tasks.values()):
            raise ValueError("Worker is busy")
        job = self.ledger.submit(data, policy=self.policy, now_unix=self.clock())
        if not existed:
            directory = self.root / request.job_id
            directory.mkdir(mode=0o700)  # Existing evidence must never be overwritten.
            _persist(directory / "request.json", request.model_dump_json(by_alias=True).encode())
            self.tasks[request.job_id] = asyncio.create_task(self._run(request, directory))
        return job

    async def _run(self, request: JobRequest, directory: Path) -> None:
        try:
            self.ledger.start(request.job_id, now_unix=self.clock())

            async def verifying():
                self.ledger.verifying(request.job_id)

            execution = asyncio.create_task(
                self.executor(
                    request,
                    task_dir=self.task_dir,
                    trials_root=directory / "trials",
                    gateway_base_url=self.gateway_base_url + request.model_route.session_path,
                    on_verifying=verifying,
                )
            )
            self.executions[request.job_id] = execution
            try:
                result = await asyncio.wait_for(
                    asyncio.shield(execution),
                    timeout=min(request.budgets.wall_time_seconds, request.budgets.deadline_unix - self.clock()),
                )
            except CleanExecutionRejected as error:
                # This signal can only be emitted after independent Docker
                # inventory confirms stop. Publish no reward or rollout.
                manifest = {
                    "schema": "dsh.harbor-job-manifest.v1",
                    "job_id": request.job_id,
                    "request_sha256": request.request_sha256,
                    "gateway_session_id": request.gateway_session_id,
                    "nonce": request.nonce,
                    "worker_id": self.worker_id,
                    "trial_id": error.trial_id,
                    "status": "cancelled",
                    "sealed_at_unix": self.clock(),
                    "error_code": error.error_code,
                    "artifacts": [],
                }
                validated = validate_manifest(manifest, request=request, worker_id=self.worker_id)
                _persist(directory / "manifest.json", validated.model_dump_json(by_alias=True).encode())
                self.ledger.seal(request.job_id, manifest, worker_id=self.worker_id)
                return
            finally:
                # Timeout, cancellation and HTTP retries share one cancellation
                # owner. Never interrupt an executor already unwinding cleanup.
                self._cancel_execution(request.job_id)
                await asyncio.shield(asyncio.gather(execution, return_exceptions=True))
            if result.cleanup_confirmed is not True:
                raise RuntimeError("Executor cleanup is unconfirmed")
            entries = []
            total = 0
            for index, (kind, content) in enumerate(sorted(result.artifacts.items())):
                if not isinstance(content, bytes):
                    raise ValueError("Executor artifacts must be raw bytes")
                total += len(content)
                if total > request.budgets.max_artifact_bytes:
                    raise ValueError("Artifact budget exceeded")
                artifact = Artifact(
                    id=f"object-{index}",
                    kind=kind,
                    size_bytes=len(content),
                    sha256="sha256:" + hashlib.sha256(content).hexdigest(),
                )
                entries.append(artifact.model_dump(mode="json"))
                _persist(directory / artifact.id, content)
            manifest = {
                "schema": "dsh.harbor-job-manifest.v1",
                "job_id": request.job_id,
                "request_sha256": request.request_sha256,
                "gateway_session_id": request.gateway_session_id,
                "nonce": request.nonce,
                "worker_id": self.worker_id,
                "trial_id": result.trial_id,
                "status": "succeeded",
                "sealed_at_unix": self.clock(),
                "artifacts": entries,
            }
            validated = validate_manifest(manifest, request=request, worker_id=self.worker_id)
            _persist(directory / "manifest.json", validated.model_dump_json(by_alias=True).encode())
            self.ledger.seal(request.job_id, manifest, worker_id=self.worker_id)
        except BaseException as error:
            # No generic exception proves remote/Harbor cleanup. Keep the ledger
            # slot occupied until an explicit reconciliation confirms stop.
            _persist(
                directory / "unconfirmed.json",
                json.dumps(
                    {"error_type": type(error).__name__, "cleanup_confirmed": False, "automatic_retry": False}
                ).encode(),
            )
            if not isinstance(error, Exception | asyncio.CancelledError):
                raise

    def _cancel_execution(self, job_id: str) -> None:
        execution = self.executions.get(job_id)
        if execution is not None and not execution.done() and not execution.cancelling():
            execution.cancel()

    async def wait(self, job_id: str) -> None:
        await asyncio.shield(self.tasks[job_id])

    async def cancel(self, job_id: str) -> dict:
        job = self.ledger.cancel(job_id)
        task = self.tasks.get(job_id)
        if task is not None and not task.done():
            self._cancel_execution(job_id)
            # Cancelling an HTTP waiter must not cancel the job owner/cleanup.
            await asyncio.shield(task)
        return self.ledger.get(job_id) if task is not None else job

    def status(self, job_id: str) -> dict:
        job = self.ledger.get(job_id)
        error_path = self.root / job_id / "unconfirmed.json"
        if error_path.exists():
            with error_path.open("rb") as source:
                raw = source.read(4097)
            if len(raw) > 4096:
                raise ValueError("Invalid worker error record")
            job["unconfirmed"] = json.loads(raw)
        return job

    def manifest(self, job_id: str) -> dict:
        result = self.ledger.get(job_id)["manifest"]
        if result is None:
            raise ValueError("Job has no sealed manifest")
        return result

    def artifact(self, job_id: str, artifact_id: str) -> bytes:
        manifest = self.manifest(job_id)
        for entry in manifest["artifacts"]:
            if entry["id"] == artifact_id:
                artifact = Artifact.model_validate(entry)
                path = self.root / job_id / artifact.id
                if path.is_symlink() or not path.is_file():
                    raise ValueError("Artifact is not a regular persisted file")
                with path.open("rb") as source:
                    content = source.read(artifact.size_bytes + 1)
                validate_artifact(artifact, content)
                return content
        raise KeyError(artifact_id)

    async def close(self):
        for job_id, task in self.tasks.items():
            if not task.done():
                await self.cancel(job_id)
