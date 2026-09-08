import asyncio
import hashlib
import json
import os
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

pytest.importorskip("harbor.trial.single_step")
from harbor.models.trial.paths import TrialPaths
from harbor.trial.hooks import TrialEvent

from uni_agent.tasks.harbor_dsh import executor
from uni_agent.tasks.harbor_dsh.protocol import JobRequest, request_sha256

pytestmark = [pytest.mark.cpu, pytest.mark.level0]
HASH = "sha256:" + "a" * 64
GATEWAY = "http://127.0.0.1:45678/sessions/session-1/v1"


def digest(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


@pytest.fixture
def task_dir(tmp_path):
    path = tmp_path / "task"
    path.mkdir()
    (path / "task.toml").write_text('[environment]\ndocker_image = "' + HASH + '"\n')
    (path / "instruction.md").write_text("Write an answer")
    return path


def request_for(task_dir, **changes):
    files = {
        p.relative_to(task_dir).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in task_dir.rglob("*")
        if p.is_file()
    }
    data = {
        "schema": "dsh.harbor-job-request.v1",
        "job_id": "job-1",
        "idempotency_key": "idem-1",
        "run_id": "run-1",
        "group_uid": "group-1",
        "sample_index": 0,
        "partition_id": "train",
        "gateway_session_id": "session-1",
        "nonce": "ab" * 16,
        "task_ref": {
            "id": "m2-file-write",
            "version": "v1",
            "sha256": digest(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()),
        },
        "dsh_release": {
            "source_sha": "b" * 40,
            "sdk_sha256": HASH,
            "runtime_sha256": HASH,
            "image_digest": HASH,
            "platform": "linux/amd64",
            "profile": "sdk-minimal",
            "patch_sha256s": [],
        },
        "model_route": {
            "gateway_host": "10.0.0.2",
            "gateway_port": 45678,
            "session_path": "/sessions/session-1/v1",
            "model_name": "student-4b",
            "tunnel_alias": "gateway-1",
        },
        "budgets": {
            "deadline_unix": time.time() + 100,
            "wall_time_seconds": 100.0,
            "cpus": 1.0,
            "memory_mb": 1024,
            "max_tokens": 4096,
            "max_artifact_bytes": 40000,
        },
    }
    for field, values in changes.items():
        data[field].update(values)
    data["request_sha256"] = request_sha256(data)
    return JobRequest.model_validate(data)


class FakeTrial:
    def __init__(self, config, *, allowed_task_dir):
        self.config = config
        self.id = uuid4()
        self.paths = TrialPaths(config.trials_dir / config.trial_name)
        self.paths.mkdir()
        self.agent_environment = SimpleNamespace(session_id=config.trial_name + "__env")
        self.hooks = {}
        self.rewrite = lambda: None
        self.cancelled = False
        self.block = False

    def _separate_verifier_session_id(self, key):
        return self.config.trial_name + "__verifier__" + key

    def add_hook(self, event, callback):
        self.hooks[event] = callback

    async def run(self):
        if self.block:
            try:
                await asyncio.sleep(10)
            finally:
                self.cancelled = True
        trace = b'{"type":"turn/end","data":{"reason":"completed"}}\n'
        trace_path = "/tmp/uni-agent-dsh/artifacts/" + hashlib.sha256(b"session-1").hexdigest()[:24] + "/session.jsonl"
        helper = {
            "schema": "dsh.uni-agent.dsh-run.v1",
            "dsh_session_id": "dsh-session-1",
            "trace_sha256": digest(trace),
            "event_count": 1,
            "final_response": "done",
            "profile": "sdk-minimal",
            "finish_reason": "completed",
            "trace_path": trace_path,
            "trace_persisted": True,
            "patches_sha256": digest(b"[]"),
        }
        result = {
            "finished": True,
            "output": {"response": "done"},
            "info": {
                "gateway_session_id": "session-1",
                "dsh_session_id": "dsh-session-1",
                "trace_sha256": digest(trace),
                "trace_path": trace_path,
                "event_count": 1,
            },
        }
        self.dsh_dir = self.paths.agent_dir / "dsh"
        self.dsh_dir.mkdir()
        (self.dsh_dir / "session.jsonl").write_bytes(trace)
        for name, value in (("run.json", helper), ("agent-result.json", result)):
            (self.dsh_dir / name).write_text(json.dumps(value) + "\n")
        metadata = {
            "schema": "dsh.harbor-agent-execution.v1",
            "status": "completed",
            "finished": True,
            "finish_reason": "completed",
            "gateway_session_id": "session-1",
            "dsh_session_id": "dsh-session-1",
            "harbor_context_id": str(self.id),
            "harbor_agent_session_id": self.config.trial_name + "__agent",
            "trace_sha256": digest(trace),
            "run_sha256": digest((self.dsh_dir / "run.json").read_bytes()),
            "agent_result_sha256": digest((self.dsh_dir / "agent-result.json").read_bytes()),
            "event_count": 1,
        }
        (self.dsh_dir / "status.json").write_text(json.dumps(metadata))
        self.result = SimpleNamespace(
            id=self.id,
            exception_info=None,
            agent_result=SimpleNamespace(metadata={"dsh": metadata}),
            verifier_result=SimpleNamespace(rewards={"reward": 1.0}),
        )
        self.paths.reward_text_path.write_bytes(b"1\n")
        self.paths.test_stdout_path.write_bytes(b"verification completed\n")
        self.paths.result_path.write_text(
            json.dumps(
                {
                    "id": str(self.id),
                    "exception_info": None,
                    "agent_result": {"metadata": {"dsh": metadata}},
                    "verifier_result": {"rewards": {"reward": 1.0}},
                }
            )
        )
        await self.hooks[TrialEvent.VERIFICATION_START](SimpleNamespace(trial_id=self.config.trial_name))
        self.rewrite()
        return self.result


@pytest.fixture
def harness(monkeypatch):
    state = SimpleNamespace(trial=None, edit=lambda trial: None)

    def create(config, **kwargs):
        state.trial = FakeTrial(config, **kwargs)
        state.edit(state.trial)
        return state.trial

    monkeypatch.setattr(executor, "create_isolated_trial", create)
    state.inventory = AsyncMock(return_value=b"")
    monkeypatch.setattr(executor, "_docker_inventory", state.inventory)
    return state


def run(request, task_dir, **kwargs):
    return asyncio.run(
        executor.execute_job(
            request,
            task_dir=task_dir,
            trials_root=task_dir.parent / "trials",
            gateway_base_url=GATEWAY,
            on_verifying=AsyncMock(),
            **kwargs,
        )
    )


def test_preserves_native_evidence_and_proves_both_environments_removed(task_dir, harness):
    callback = AsyncMock()
    result = asyncio.run(
        executor.execute_job(
            request_for(task_dir),
            task_dir=task_dir,
            trials_root=task_dir.parent / "trials",
            gateway_base_url=GATEWAY,
            on_verifying=callback,
        )
    )
    assert result.trial_id == str(harness.trial.id)
    assert result.cleanup_confirmed is True
    assert set(result.artifacts) == {"dsh_trace", "dsh_result", "harbor_result", "verifier_log", "reward"}
    assert result.artifacts["dsh_result"] == (harness.trial.dsh_dir / "run.json").read_bytes()
    assert result.artifacts["harbor_result"] == harness.trial.paths.result_path.read_bytes()
    assert result.artifacts["reward"] == b"1\n"
    callback.assert_awaited_once()
    config = harness.trial.config
    assert config.agent.model_name == "student-4b"
    assert config.agent.kwargs["gateway_base_url"] == GATEWAY
    assert config.agent.kwargs["patches"] == []
    assert config.environment.delete is True
    assert os.stat(config.trials_dir).st_mode & 0o777 == 0o700
    projects = {call.args[0] for call in harness.inventory.await_args_list}
    assert projects == {config.trial_name.lower() + "__env", config.trial_name.lower() + "__verifier__trial"}


@pytest.mark.parametrize("case", ["task_hash", "patches", "profile", "image", "expired", "fractional_cpu", "symlink"])
def test_invalid_execution_inputs_never_construct_trial(task_dir, harness, case):
    changes = {
        "patches": {"dsh_release": {"patch_sha256s": [HASH]}},
        "profile": {"dsh_release": {"profile": "sdk"}},
        "image": {"dsh_release": {"image_digest": "sha256:" + "c" * 64}},
        "expired": {"budgets": {"deadline_unix": 1.0}},
        "fractional_cpu": {"budgets": {"cpus": 0.5}},
    }.get(case, {})
    request = request_for(task_dir, **changes)
    if case == "task_hash":
        (task_dir / "instruction.md").write_text("changed")
    elif case == "symlink":
        (task_dir / "link").symlink_to(task_dir / "instruction.md")
    with pytest.raises((ValueError, RuntimeError, OSError)):
        run(request, task_dir)
    assert harness.trial is None


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:45678/v1",
        GATEWAY + "/",
        GATEWAY + "?x=y",
        GATEWAY.replace("session-1", "other"),
        GATEWAY.replace("127.0.0.1", "user:pass@127.0.0.1"),
    ],
)
def test_mapping_must_preserve_exact_session_path(task_dir, harness, url):
    with pytest.raises(ValueError):
        asyncio.run(
            executor.execute_job(
                request_for(task_dir),
                task_dir=task_dir,
                trials_root=task_dir.parent / "trials",
                gateway_base_url=url,
                on_verifying=AsyncMock(),
            )
        )
    assert harness.trial is None


@pytest.mark.parametrize(
    "case",
    [
        "exception",
        "unfinished",
        "trace",
        "missing",
        "nan_reward",
        "reward_mismatch",
        "symlink",
        "oversize",
        "task_drift",
    ],
)
def test_incomplete_or_tampered_evidence_is_never_success(task_dir, harness, case):
    def edit(trial):
        def rewrite():
            if case == "exception":
                trial.result.exception_info = object()
            elif case == "unfinished":
                trial.result.agent_result.metadata["dsh"]["finished"] = False
            elif case == "trace":
                (trial.dsh_dir / "session.jsonl").write_bytes(b"changed\n")
            elif case == "missing":
                (trial.dsh_dir / "run.json").unlink()
            elif case == "nan_reward":
                trial.paths.reward_text_path.write_bytes(b"nan\n")
                trial.result.verifier_result.rewards = {"reward": float("nan")}
            elif case == "reward_mismatch":
                trial.paths.reward_text_path.write_bytes(b"0\n")
            elif case == "symlink":
                trial.paths.test_stdout_path.unlink()
                trial.paths.test_stdout_path.symlink_to(task_dir / "instruction.md")
            elif case == "oversize":
                trial.paths.test_stdout_path.write_bytes(b"x" * 40001)
            else:
                (task_dir / "instruction.md").write_text("changed during execution")

        trial.rewrite = rewrite

    harness.edit = edit
    with pytest.raises((ValueError, RuntimeError, OSError)):
        run(request_for(task_dir), task_dir)
    assert harness.trial is not None


@pytest.mark.parametrize("remaining", [b"container-id\n", RuntimeError("daemon unavailable")])
def test_unknown_or_incomplete_cleanup_cannot_return_success(task_dir, harness, remaining):
    if isinstance(remaining, Exception):
        harness.inventory.side_effect = remaining
    else:
        harness.inventory.return_value = remaining
    with pytest.raises(RuntimeError):
        run(request_for(task_dir), task_dir)


def test_deadline_cancels_native_trial_without_fabricating_result(task_dir, harness):
    harness.edit = lambda trial: setattr(trial, "block", True)
    with pytest.raises(TimeoutError):
        run(request_for(task_dir, budgets={"deadline_unix": time.time() + 0.03}), task_dir)
    assert harness.trial.cancelled is True


def test_private_job_directory_is_exclusive(task_dir, harness):
    request = request_for(task_dir)
    run(request, task_dir)
    with pytest.raises(FileExistsError):
        run(request, task_dir)
