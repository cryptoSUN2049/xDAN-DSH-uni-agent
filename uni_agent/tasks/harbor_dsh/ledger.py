"""Durable single-worker job admission; reopening never retries active jobs.

The executor must acknowledge cleanup with a sealed terminal manifest. This
ledger does not execute tasks, authenticate clients, or prove artifact contents.
"""

from __future__ import annotations

import json
import math
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .protocol import JobRequest, RequestPolicy, validate_manifest, validate_request


class JobLedger:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(path, isolation_level=None, timeout=10)
        path.chmod(0o600)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("""CREATE TABLE IF NOT EXISTS jobs (
            job_id TEXT PRIMARY KEY, idempotency_key TEXT UNIQUE NOT NULL,
            nonce TEXT UNIQUE NOT NULL, gateway_session_id TEXT UNIQUE NOT NULL,
            request_hash TEXT NOT NULL, request TEXT NOT NULL,
            status TEXT NOT NULL, manifest TEXT)""")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.db.close()

    @contextmanager
    def _transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def get(self, job_id: str) -> dict:
        row = self.db.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        return {
            "job_id": row["job_id"],
            "status": row["status"],
            "request": json.loads(row["request"]),
            "manifest": json.loads(row["manifest"]) if row["manifest"] else None,
        }

    def submit(self, data: dict, *, policy: RequestPolicy, now_unix: float) -> dict:
        request = JobRequest.model_validate(data)
        with self._transaction():
            rows = self.db.execute(
                """SELECT job_id, request_hash FROM jobs WHERE
                job_id=? OR idempotency_key=? OR nonce=? OR gateway_session_id=?""",
                (request.job_id, request.idempotency_key, request.nonce, request.gateway_session_id),
            ).fetchall()
            if rows:
                if len(rows) != 1 or rows[0]["request_hash"] != request.request_sha256:
                    raise ValueError("Conflicting job identity; implicit retries are forbidden")
                # A published request stays inspectable after its deadline.
                return self.get(rows[0]["job_id"])
            validate_request(data, policy=policy, now_unix=now_unix)
            if self.db.execute("SELECT 1 FROM jobs WHERE status IN ('running','verifying','cancelling')").fetchone():
                raise ValueError("Worker already has an active or unconfirmed job")
            self.db.execute(
                "INSERT INTO jobs VALUES (?,?,?,?,?,?,?,NULL)",
                (
                    request.job_id,
                    request.idempotency_key,
                    request.nonce,
                    request.gateway_session_id,
                    request.request_sha256,
                    request.model_dump_json(by_alias=True),
                    "queued",
                ),
            )
            return self.get(request.job_id)

    def start(self, job_id: str, *, now_unix: float) -> dict:
        with self._transaction():
            job = self.get(job_id)
            if isinstance(now_unix, bool) or not math.isfinite(now_unix):
                raise ValueError("Invalid executor time")
            if now_unix >= job["request"]["budgets"]["deadline_unix"]:
                raise ValueError("Queued job deadline expired")
            if job["status"] != "queued":
                raise ValueError("Only a queued job can start")
            if self.db.execute("SELECT 1 FROM jobs WHERE status IN ('running','verifying','cancelling')").fetchone():
                raise ValueError("Worker already has an active or unconfirmed job")
            self.db.execute("UPDATE jobs SET status='running' WHERE job_id=?", (job_id,))
            return self.get(job_id)

    def verifying(self, job_id: str) -> dict:
        with self._transaction():
            if self.get(job_id)["status"] != "running":
                raise ValueError("Only a running job can begin verification")
            self.db.execute("UPDATE jobs SET status='verifying' WHERE job_id=?", (job_id,))
            return self.get(job_id)

    def cancel(self, job_id: str) -> dict:
        with self._transaction():
            job = self.get(job_id)
            if job["status"] in ("queued", "running", "verifying"):
                self.db.execute("UPDATE jobs SET status='cancelling' WHERE job_id=?", (job_id,))
            return self.get(job_id)

    def seal(self, job_id: str, data: dict, *, worker_id: str) -> dict:
        """Called only after the executor confirms stop and artifact persistence."""
        with self._transaction():
            job = self.get(job_id)
            request = JobRequest.model_validate(job["request"])
            manifest = validate_manifest(data, request=request, worker_id=worker_id)
            if job["manifest"] is not None:
                if job["manifest"] != manifest.model_dump(mode="json", by_alias=True):
                    raise ValueError("A sealed result is immutable")
                return job
            if job["status"] == "cancelling" and manifest.status != "cancelled":
                raise ValueError("Cancellation must be acknowledged, not replaced by success")
            if manifest.status == "succeeded" and job["status"] != "verifying":
                raise ValueError("Success requires a completed verification phase")
            if job["status"] == "queued" and manifest.status != "failed":
                raise ValueError("An unstarted job cannot complete")
            self.db.execute(
                "UPDATE jobs SET status=?, manifest=? WHERE job_id=?",
                (manifest.status, manifest.model_dump_json(by_alias=True), job_id),
            )
            return self.get(job_id)
