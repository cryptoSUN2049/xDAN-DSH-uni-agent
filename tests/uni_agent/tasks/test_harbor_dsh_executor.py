import asyncio
import hashlib
import json
import os
import time
from pathlib import Path
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
    def __init__(self, config, *, allowed_task_dir, **strategy_kwargs):
        self.strategy_kwargs = strategy_kwargs
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
            "patches_sha256": digest(json.dumps(self.config.agent.kwargs["patches"], separators=(",", ":")).encode()),
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
    with pytest.raises(executor.CleanExecutionRejected) as raised:
        run(request_for(task_dir, budgets={"deadline_unix": time.time() + 0.03}), task_dir)
    assert isinstance(raised.value.__cause__, TimeoutError)
    assert harness.inventory.await_count == 6
    assert harness.trial.cancelled is True


def test_private_job_directory_is_exclusive(task_dir, harness):
    request = request_for(task_dir)
    run(request, task_dir)
    with pytest.raises(FileExistsError):
        run(request, task_dir)


def test_frozen_t2_patch_is_forwarded_and_bound(task_dir, harness):
    from uni_agent.agents.dsh.harbor_release import T2_PATCH_PATH, T2_PATCH_SHA256

    patch = task_dir / "environment" / "evolution.patch.yml"
    patch.parent.mkdir(exist_ok=True)
    source = Path(__file__).resolve().parents[3] / "examples/dsh/evolution.patch.yml"
    patch.write_bytes(source.read_bytes())
    request = request_for(task_dir, dsh_release={"patch_sha256s": [T2_PATCH_SHA256]})
    result = run(request, task_dir)
    assert result.cleanup_confirmed
    assert harness.trial.config.agent.kwargs["patches"] == [T2_PATCH_PATH]


def test_frozen_t2_patch_bytes_cannot_be_substituted(task_dir, harness):
    from uni_agent.agents.dsh.harbor_release import T2_PATCH_SHA256

    patch = task_dir / "environment" / "evolution.patch.yml"
    patch.parent.mkdir(exist_ok=True)
    patch.write_text("changed")
    request = request_for(task_dir, dsh_release={"patch_sha256s": [T2_PATCH_SHA256]})
    with pytest.raises(ValueError, match="patch"):
        run(request, task_dir)
    assert harness.trial is None


def evolution_task(task_dir):
    from uni_agent.agents.dsh.harbor_release import T2_PATCH_PATH

    source = Path(__file__).resolve().parents[3]
    (task_dir / "environment").mkdir()
    (task_dir / "environment/evolution.patch.yml").write_bytes(
        (source / "examples/dsh/evolution.patch.yml").read_bytes()
    )
    (task_dir / "tests").mkdir()
    raw = b'{"schema":"dsh.evolution.fixture.v1","operation":"redact_email","input":"a@b.org"}'
    (task_dir / "tests/fixture.json").write_bytes(raw)
    sources = {
        p: digest((source / p).read_bytes()) for p in ["examples/dsh/evolution_verifier.py", "examples/dsh/verifier.py"]
    }
    metadata = dict(
        operation="redact_email",
        candidate_tool_name="redact_payload",
        scenario_id="redact-holdout-01",
        task_id="dsh/harness-evolution/redact-holdout-01",
        task_version="1",
        fixture_digest=digest(raw),
        fixture_path="/app/fixture.json",
        profile="sdk-minimal",
        environment_digest=HASH,
        patches_sha256=digest(json.dumps([T2_PATCH_PATH], separators=(",", ":")).encode()),
        verifier_id="dsh-harness-evolution-verifier",
        verifier_version="1",
        verifier_code_digest=sources["examples/dsh/evolution_verifier.py"],
    )
    raw_meta = json.dumps(metadata).encode()
    (task_dir / "tests/metadata.json").write_bytes(raw_meta)
    descriptor = dict(
        kind="evolution-v2-lifecycle-v1",
        fixture_sha256=digest(raw),
        metadata_sha256=digest(raw_meta),
        source_sha256s=sources,
    )
    (task_dir / "evolution.json").write_text(json.dumps(descriptor))
    return descriptor, metadata


def test_evolution_injects_request_taskref_outside_task_tree(task_dir, harness):
    from uni_agent.agents.dsh.harbor_release import T2_PATCH_SHA256

    descriptor, _ = evolution_task(task_dir)
    request = request_for(task_dir, dsh_release={"patch_sha256s": [T2_PATCH_SHA256]})
    result = run(request, task_dir)
    assert result.cleanup_confirmed
    kwargs = harness.trial.strategy_kwargs
    assert kwargs["strategy"] == "evolution-v2-lifecycle-v1"
    binding = json.loads(kwargs["evolution_binding"])
    assert binding == {
        **descriptor,
        "task_ref": request.task_ref.model_dump(),
        "fixture_path": "/tests/fixture.json",
        "metadata_path": "/tests/metadata.json",
    }
    assert "task_ref" not in json.loads((task_dir / "evolution.json").read_text())


@pytest.mark.parametrize(
    "bad",
    ["source", "fixture", "metadata", "kind", "self_reference", "runtime", "patch_path", "fixture_path", "unpatched"],
)
def test_evolution_preflight_rejects_before_trial(task_dir, harness, bad):
    from uni_agent.agents.dsh.harbor_release import T2_PATCH_SHA256

    descriptor, metadata = evolution_task(task_dir)
    if bad == "source":
        descriptor["source_sha256s"]["examples/dsh/verifier.py"] = HASH
    if bad == "fixture":
        (task_dir / "tests/fixture.json").write_bytes(b"changed")
    if bad == "metadata":
        (task_dir / "tests/metadata.json").write_bytes(b"changed")
    if bad == "kind":
        descriptor["kind"] = "other"
    if bad == "self_reference":
        descriptor["task_ref"] = dict(id="forged", version="v1", sha256=HASH)
    if bad in ("runtime", "patch_path", "fixture_path"):
        field = {"runtime": "environment_digest", "patch_path": "patches_sha256", "fixture_path": "fixture_path"}[bad]
        metadata[field] = "/tmp/another.json" if bad == "fixture_path" else "sha256:" + "c" * 64
        raw = json.dumps(metadata).encode()
        (task_dir / "tests/metadata.json").write_bytes(raw)
        descriptor["metadata_sha256"] = digest(raw)
    (task_dir / "evolution.json").write_text(json.dumps(descriptor))
    request = request_for(task_dir, dsh_release={"patch_sha256s": [] if bad == "unpatched" else [T2_PATCH_SHA256]})
    with pytest.raises(ValueError):
        run(request, task_dir)
    assert harness.trial is None


def evolution_v2_task(task_dir):
    from uni_agent.tasks.harbor_dsh.evolution_scoring_v2 import EVOLUTION_V2_KIND, SOURCE_HASHES, VERIFIER_BUNDLE_SHA256

    marker, metadata = evolution_task(task_dir)
    metadata.update(task_version="2", verifier_version="2", verifier_code_digest=VERIFIER_BUNDLE_SHA256)
    meta_raw = json.dumps(metadata).encode()
    (task_dir / "tests/metadata.json").write_bytes(meta_raw)
    marker.update(
        kind=EVOLUTION_V2_KIND,
        metadata_sha256=digest(meta_raw),
        source_sha256s={"examples/dsh/" + k: "sha256:" + v for k, v in SOURCE_HASHES.items()},
        verifier_bundle_sha256=VERIFIER_BUNDLE_SHA256,
    )
    (task_dir / "evolution.json").write_text(json.dumps(marker))
    return marker


def test_v2_executor_freezes_exact_marker_and_selects_strategy(task_dir, harness):
    from uni_agent.agents.dsh.harbor_release import T2_PATCH_SHA256

    marker = evolution_v2_task(task_dir)
    request = request_for(task_dir, dsh_release={"patch_sha256s": [T2_PATCH_SHA256]}, task_ref={"version": "v2"})
    result = run(request, task_dir)
    assert result.cleanup_confirmed
    kwargs = harness.trial.strategy_kwargs
    assert kwargs["strategy"] == marker["kind"]
    assert json.loads(kwargs["evolution_binding"]) == {
        **marker,
        "task_ref": request.task_ref.model_dump(),
        "fixture_path": "/tests/fixture.json",
        "metadata_path": "/tests/metadata.json",
    }


@pytest.mark.parametrize("bad", ["v1_version", "bundle", "source", "missing_bundle", "extra"])
def test_v2_marker_rejects_before_trial(task_dir, harness, bad):
    from uni_agent.agents.dsh.harbor_release import T2_PATCH_SHA256

    marker = evolution_v2_task(task_dir)
    if bad == "bundle":
        marker["verifier_bundle_sha256"] = HASH
    elif bad == "source":
        marker["source_sha256s"].pop("examples/dsh/evolution_verifier_v2.py")
    elif bad == "missing_bundle":
        marker.pop("verifier_bundle_sha256")
    elif bad == "extra":
        marker["fixture_path"] = "/tmp/forged"
    (task_dir / "evolution.json").write_text(json.dumps(marker))
    request = request_for(
        task_dir,
        dsh_release={"patch_sha256s": [T2_PATCH_SHA256]},
        task_ref={"version": "v1" if bad == "v1_version" else "v2"},
    )
    with pytest.raises(ValueError):
        run(request, task_dir)
    assert harness.trial is None


@pytest.mark.parametrize("cleanup_unknown", [False, True])
def test_failed_trial_only_acknowledges_independently_confirmed_cleanup(task_dir, harness, cleanup_unknown):
    from uni_agent.tasks.harbor_dsh.execution_outcome import CleanExecutionRejected

    def edit(trial):
        trial.rewrite = lambda: setattr(trial.result, "exception_info", object())

    harness.edit = edit
    if cleanup_unknown:
        harness.inventory.return_value = b"container-still-present\n"
    with pytest.raises(RuntimeError) as caught:
        run(request_for(task_dir), task_dir)
    assert isinstance(caught.value, CleanExecutionRejected) is not cleanup_unknown
    assert harness.inventory.await_count == (1 if cleanup_unknown else 6)


@pytest.mark.parametrize(
    "cleanup", ["complete", "missing-verifier", "unconfirmed", "failed-clean", "failed-unknown", "cancelled-clean"]
)
def test_modal_executor_uses_tracked_scope_and_preserves_evidence(task_dir, harness, monkeypatch, cleanup):
    from uni_agent.agents.dsh.harbor_release import T2_PATCH_SHA256
    from uni_agent.tasks.harbor_dsh.environment_backend import TRACKED_MODAL_IMPORT

    patch = task_dir / "environment/evolution.patch.yml"
    patch.parent.mkdir()
    patch.write_bytes((Path(__file__).resolve().parents[3] / "examples/dsh/evolution.patch.yml").read_bytes())
    (task_dir / "task.toml").write_text(
        '[environment]\ndocker_image = "registry.example.com/dsh@' + HASH + '"\n'
        'network_mode = "allowlist"\nallowed_hosts = ["gateway.example.com"]\n'
        '[verifier]\nenvironment_mode = "separate"\n[verifier.environment]\nnetwork_mode = "no-network"\n'
    )
    scopes = []
    if cleanup in {"failed-clean", "failed-unknown", "cancelled-clean"}:

        async def fail():
            if cleanup == "cancelled-clean":
                raise asyncio.CancelledError()
            raise RuntimeError("trial failed before verifier")

        harness.edit = lambda trial: setattr(trial, "run", fail)

    class Scope:
        def __init__(self, **kwargs):
            self.cleanup_confirmed = False
            scopes.append(self)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            self.cleanup_confirmed = cleanup not in {"unconfirmed", "failed-unknown"}
            name = harness.trial.config.trial_name
            self.evidence = (
                {"session_id": name + "__env", "sandbox_id": "sb-agent", "returncode": 137},
                {"session_id": name + "__verifier__trial", "sandbox_id": "sb-verifier", "returncode": 137},
            )
            if cleanup in {"missing-verifier", "failed-clean", "failed-unknown", "cancelled-clean"}:
                self.evidence = self.evidence[:1]

    monkeypatch.setattr(executor, "_modal_execution_scope", lambda **kwargs: Scope(**kwargs))
    request = request_for(task_dir, dsh_release={"patch_sha256s": [T2_PATCH_SHA256]})
    execution = executor.execute_job(
        request,
        task_dir=task_dir,
        trials_root=task_dir.parent / "trials",
        gateway_base_url="https://gateway.example.com" + request.model_route.session_path,
        on_verifying=AsyncMock(),
        environment_backend="modal",
    )
    if cleanup in {"failed-clean", "cancelled-clean"}:
        with pytest.raises(executor.CleanExecutionRejected):
            asyncio.run(execution)
        records = list((task_dir.parent / "trials").rglob("modal-cleanup.json"))
        assert len(records) == 1
        assert len(json.loads(records[0].read_text())["resources"]) == 1
        harness.inventory.assert_not_called()
        return
    if cleanup == "failed-unknown":
        with pytest.raises(RuntimeError) as raised:
            asyncio.run(execution)
        assert not isinstance(raised.value, executor.CleanExecutionRejected)
        assert not list((task_dir.parent / "trials").rglob("modal-cleanup.json"))
        return
    if cleanup != "complete":
        with pytest.raises(RuntimeError, match="cleanup evidence"):
            asyncio.run(execution)
        harness.inventory.assert_not_called()
        return
    result = asyncio.run(execution)
    assert result.cleanup_confirmed and scopes[0].cleanup_confirmed
    assert harness.trial.config.environment.import_path == TRACKED_MODAL_IMPORT
    assert harness.trial.config.environment.type.value == "modal"
    assert set(result.artifacts) == {"dsh_trace", "dsh_result", "harbor_result", "verifier_log", "reward"}
    harness.inventory.assert_not_called()


@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
@pytest.mark.parametrize("cleanup_unknown", [False, True])
def test_raised_trial_failure_checks_cleanup_before_rejection(task_dir, harness, error_type, cleanup_unknown):
    from uni_agent.tasks.harbor_dsh.execution_outcome import CleanExecutionRejected

    failure = error_type("trial failed")

    def edit(trial):
        trial.run = AsyncMock(side_effect=failure)

    harness.edit = edit
    if cleanup_unknown:
        harness.inventory.return_value = b"remaining-volume\n"
    with pytest.raises(RuntimeError) as caught:
        run(request_for(task_dir), task_dir)
    assert isinstance(caught.value, CleanExecutionRejected) is not cleanup_unknown
    if not cleanup_unknown:
        assert caught.value.__cause__ is failure
    assert harness.inventory.await_count == (1 if cleanup_unknown else 6)


@pytest.mark.asyncio
async def test_repeated_cancel_cannot_interrupt_failure_cleanup(task_dir, harness):
    from uni_agent.tasks.harbor_dsh.execution_outcome import CleanExecutionRejected

    running, checking, release = (asyncio.Event() for _ in range(3))

    async def trial_run():
        running.set()
        await asyncio.Event().wait()

    async def inventory(*args):
        assert harness.trial.run.call_count == 1
        checking.set()
        await release.wait()
        return b""

    harness.edit = lambda trial: setattr(trial, "run", AsyncMock(side_effect=trial_run))
    harness.inventory.side_effect = inventory
    task = asyncio.create_task(
        executor.execute_job(
            request_for(task_dir),
            task_dir=task_dir,
            trials_root=task_dir.parent / "trials",
            gateway_base_url=GATEWAY,
            on_verifying=AsyncMock(),
        )
    )
    await running.wait()
    task.cancel()
    try:
        await asyncio.wait_for(checking.wait(), 0.2)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
    finally:
        release.set()
        outcome = (await asyncio.gather(task, return_exceptions=True))[0]
    assert isinstance(outcome, CleanExecutionRejected)
    assert isinstance(outcome.__cause__, asyncio.CancelledError)
    assert harness.inventory.await_count == 6


@pytest.mark.asyncio
async def test_failure_cleanup_has_a_total_deadline(task_dir, harness, monkeypatch):
    from uni_agent.tasks.harbor_dsh.execution_outcome import CleanExecutionRejected

    monkeypatch.setattr(executor, "_CLEANUP_CONFIRM_TIMEOUT_SECONDS", 0.02, raising=False)
    harness.edit = lambda trial: setattr(trial, "run", AsyncMock(side_effect=RuntimeError("trial failed")))
    stopped = asyncio.Event()

    async def inventory(*args):
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    harness.inventory.side_effect = inventory
    with pytest.raises(TimeoutError) as caught:
        await asyncio.wait_for(
            executor.execute_job(
                request_for(task_dir),
                task_dir=task_dir,
                trials_root=task_dir.parent / "trials",
                gateway_base_url=GATEWAY,
                on_verifying=AsyncMock(),
            ),
            0.5,
        )
    assert not isinstance(caught.value, CleanExecutionRejected)
    assert stopped.is_set()
