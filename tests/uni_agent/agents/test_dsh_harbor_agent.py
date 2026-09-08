from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

pytest.importorskip("harbor.agents.base")
from harbor.agents.factory import AgentFactory
from harbor.models.agent.context import AgentContext
from harbor.models.trial.config import AgentConfig as HarborAgentConfig

from uni_agent.agents.dsh import runner
from uni_agent.agents.dsh.harbor_agent import _SETUP_CHECK, DshHarborAgent

pytestmark = [pytest.mark.cpu, pytest.mark.level0]
GATEWAY = "http://gateway:1234/sessions/session-1/v1"


def digest(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


class FakeEnvironment:
    os = "linux"

    def __init__(self):
        self.files = {}
        self.calls = []
        self.runner_calls = 0
        self.bad_digest = False
        self.bad_probe = False
        self.setup_exit = 0
        self.finished = True

    async def exec(self, command, cwd=None, env=None, timeout_sec=None):
        argv = shlex.split(command)
        self.calls.append((argv, cwd, env, timeout_sec))
        if argv[:2] == ["python", "-c"]:
            probe = {
                "runner_sha256": "sha256:" + "0" * 64 if self.bad_probe else digest(Path(runner.__file__).read_bytes()),
                "sdk_version": "0.1.2a1",
                "runtime_version": "0.1.2a1",
            }
            return SimpleNamespace(return_code=self.setup_exit, stdout=json.dumps(probe), stderr="")
        if argv[:3] == ["python", "-m", "uni_agent.agents.dsh.runner"]:
            self.runner_calls += 1
            payload = json.loads(self.files[argv[argv.index("--input") + 1]])
            trace_path = env["DSH_UA_TRACE_PATH"]
            trace = b'{"data":{"reason":"completed"},"type":"turn/end"}\n'
            self.files[trace_path] = b"tampered" if self.bad_digest else trace
            result = {
                "schema": "dsh.uni-agent.dsh-run.v1",
                "dsh_session_id": payload["session_id"],
                "trace_sha256": digest(trace),
                "trace_path": trace_path,
                "event_count": 1,
                "finish_reason": "completed" if self.finished else "max_tokens",
                "final_response": "done",
                "trace_persisted": True,
                "profile": env["DSH_UA_PROFILE"],
                "patches_sha256": digest(b"[]"),
            }
            self.files[argv[argv.index("--output") + 1]] = json.dumps(result).encode() + b"\n"
        return SimpleNamespace(return_code=0, stdout=None, stderr=None)

    async def upload_file(self, source_path, target_path):
        self.files[target_path] = Path(source_path).read_bytes()

    async def download_file(self, source_path, target_path):
        Path(target_path).write_bytes(self.files[source_path])


def bridge(tmp_path, **kwargs):
    return DshHarborAgent(
        logs_dir=tmp_path,
        model_name="Qwen/Qwen3-4B",
        gateway_base_url=GATEWAY,
        gateway_api_key="session-secret",
        workdir="/task",
        **kwargs,
    )


@pytest.mark.parametrize("url", ["http://gateway/v1", "http://user:pass@gateway/sessions/id/v1", GATEWAY + "?key=x"])
def test_endpoint_must_be_explicit_session_url(tmp_path, url):
    with pytest.raises(ValueError):
        DshHarborAgent(logs_dir=tmp_path, model_name="Qwen3-4B", gateway_base_url=url)


def test_host_environment_cannot_supply_endpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", GATEWAY)
    with pytest.raises(TypeError):
        DshHarborAgent(logs_dir=tmp_path, model_name="Qwen3-4B")


def test_real_harbor_factory_loads_custom_agent(tmp_path):
    agent = AgentFactory.create_agent_from_config(
        HarborAgentConfig(
            name="uni_agent.agents.dsh.harbor_agent:DshHarborAgent",
            model_name="Qwen/Qwen3-4B",
            kwargs={"gateway_base_url": GATEWAY},
        ),
        logs_dir=tmp_path,
    )
    assert isinstance(agent, DshHarborAgent)
    assert agent.name() == "uni-agent-dsh"
    assert agent.version()
    assert not agent.SUPPORTS_ATIF


def test_setup_program_uses_actual_distribution_names(tmp_path):
    # Names verified against fixed DSH 7840bced python/{sdk,sdk-runtime}/pyproject.toml.
    # Use real importlib.metadata discovery, not a mocked precomputed probe.
    for distribution, module in (
        ("deepseek-harness-sdk", "deepseek_harness"),
        ("deepseek-harness-runtime-bin", "deepseek_harness_runtime"),
    ):
        (tmp_path / f"{module}.py").write_text("")
        metadata = tmp_path / f"{distribution.replace('-', '_')}-0.1.2a1.dist-info"
        metadata.mkdir()
        (metadata / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {distribution}\nVersion: 0.1.2a1\n")
    patch = tmp_path / "profile.patch.yml"
    patch.write_bytes(b"[]\n")
    repository = Path(runner.__file__).parents[3]
    process = subprocess.run(
        [sys.executable, "-c", _SETUP_CHECK, str(patch)],
        cwd=repository,
        env={**os.environ, "PYTHONPATH": os.pathsep.join([str(tmp_path), str(repository)])},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert process.returncode == 0, process.stderr
    probe = json.loads(process.stdout)
    assert probe["runtime_version"] == "0.1.2a1"
    assert probe["sdk_version"] == "0.1.2a1"
    assert probe["runner_sha256"] == digest(Path(runner.__file__).read_bytes())
    assert probe["patches"] == [{"path": str(patch), "sha256": digest(patch.read_bytes())}]


@pytest.mark.parametrize("options", [{"model_name": ""}, {"gateway_api_key": " "}, {"max_tokens_per_turn": 0}])
def test_explicit_model_key_and_budget_validation(tmp_path, options):
    kwargs = {"logs_dir": tmp_path, "gateway_base_url": GATEWAY, "model_name": "Qwen3-4B", **options}
    with pytest.raises(ValueError):
        DshHarborAgent(**kwargs)


@pytest.mark.parametrize(
    "options", [{"extra_env": {"SECRET": "x"}}, {"skills_dir": "/skills"}, {"mcp_servers": [object()]}]
)
def test_unsupported_injection_rejected(tmp_path, options):
    with pytest.raises(ValueError):
        bridge(tmp_path, **options)


@pytest.mark.asyncio
async def test_setup_only_checks_preinstalled_runtime_and_helper(tmp_path):
    environment = FakeEnvironment()
    agent = bridge(tmp_path)
    await agent.setup(environment)
    assert len(environment.calls) == 1
    argv, cwd, env, timeout = environment.calls[0]
    assert argv[:2] == ["python", "-c"]
    assert "pip install" not in argv[2]
    assert cwd == "/task" and env is None and timeout == 30
    assert environment.runner_calls == 0
    assert json.loads((tmp_path / "dsh" / "setup.json").read_text())["sdk_version"] == "0.1.2a1"


@pytest.mark.parametrize("bad_probe,exit_code", [(True, 0), (False, 1)])
@pytest.mark.asyncio
async def test_setup_rejects_wrong_helper_or_missing_dependencies(tmp_path, bad_probe, exit_code):
    environment = FakeEnvironment()
    environment.bad_probe, environment.setup_exit = bad_probe, exit_code
    with pytest.raises(RuntimeError):
        await bridge(tmp_path).setup(environment)
    assert environment.runner_calls == 0


@pytest.mark.asyncio
async def test_run_reuses_dsh_and_preserves_raw_trace_and_result(tmp_path, monkeypatch):
    monkeypatch.setenv("HOST_ONLY_SECRET", "never-forward-this")
    environment = FakeEnvironment()
    agent = bridge(tmp_path)
    agent.session_id = "trial-1__agent"
    agent.context_id = uuid4()
    context = AgentContext(metadata={"existing": "kept"})
    await agent.setup(environment)
    await agent.run("Complete the task", environment, context)
    assert environment.runner_calls == 1
    remote_trace = next(value for key, value in environment.files.items() if key.endswith("/session.jsonl"))
    remote_result = next(value for key, value in environment.files.items() if key.endswith("/result.json"))
    assert (tmp_path / "dsh" / "session.jsonl").read_bytes() == remote_trace
    assert (tmp_path / "dsh" / "run.json").read_bytes() == remote_result
    result = json.loads((tmp_path / "dsh" / "agent-result.json").read_text())
    assert result["finished"] is True
    assert result["info"]["gateway_session_id"] == "session-1"
    assert result["info"]["dsh_session_id"] == "dsh-session-1"
    metadata = context.metadata["dsh"]
    assert metadata["status"] == "completed"
    assert metadata["harbor_agent_session_id"] == "trial-1__agent"
    assert metadata["harbor_context_id"] == str(agent.context_id)
    assert metadata["trace_sha256"] == digest(remote_trace)
    assert context.metadata["existing"] == "kept"
    assert context.rollout_details is None and context.n_output_tokens is None
    helper_env = next(
        call[2] for call in environment.calls if call[0][:3] == ["python", "-m", "uni_agent.agents.dsh.runner"]
    )
    assert helper_env["DSH_UA_BASE_URL"] == GATEWAY
    assert helper_env["DSH_UA_API_KEY"] == "session-secret"
    assert "HOST_ONLY_SECRET" not in helper_env
    for path in (tmp_path / "dsh").iterdir():
        assert b"session-secret" not in path.read_bytes()
        assert b"never-forward-this" not in path.read_bytes()


@pytest.mark.asyncio
async def test_run_requires_same_preflight_environment_and_single_use(tmp_path):
    environment = FakeEnvironment()
    agent = bridge(tmp_path)
    with pytest.raises(RuntimeError, match="setup"):
        await agent.run("task", environment, AgentContext())
    await agent.setup(environment)
    with pytest.raises(RuntimeError, match="environment"):
        await agent.run("task", FakeEnvironment(), AgentContext())
    await agent.run("task", environment, AgentContext())
    with pytest.raises(RuntimeError, match="once"):
        await agent.run("task", environment, AgentContext())


@pytest.mark.asyncio
async def test_tampered_trace_fails_without_claiming_success(tmp_path):
    environment = FakeEnvironment()
    environment.bad_digest = True
    agent = bridge(tmp_path)
    context = AgentContext()
    await agent.setup(environment)
    with pytest.raises(RuntimeError, match="trace"):
        await agent.run("task", environment, context)
    assert context.metadata["dsh"]["status"] == "failed"


@pytest.mark.asyncio
async def test_unfinished_dsh_is_not_marked_complete(tmp_path):
    environment = FakeEnvironment()
    environment.finished = False
    agent = bridge(tmp_path)
    context = AgentContext()
    await agent.setup(environment)
    await agent.run("task", environment, context)
    assert context.metadata["dsh"]["status"] == "unfinished"
    assert context.metadata["dsh"]["finished"] is False


@pytest.mark.asyncio
async def test_cancelled_agent_records_failure_and_propagates(tmp_path, monkeypatch):
    from uni_agent.agents.dsh.agent import DshAgent

    async def cancel(*args, **kwargs):
        raise asyncio.CancelledError()

    monkeypatch.setattr(DshAgent, "run", cancel)
    environment = FakeEnvironment()
    agent = bridge(tmp_path)
    context = AgentContext()
    await agent.setup(environment)
    with pytest.raises(asyncio.CancelledError):
        await agent.run("task", environment, context)
    status = json.loads((tmp_path / "dsh" / "status.json").read_text())
    assert status["status"] == "failed"
    assert status["error_type"] == "CancelledError"


@pytest.mark.asyncio
async def test_existing_context_identity_is_not_overwritten(tmp_path):
    environment = FakeEnvironment()
    agent = bridge(tmp_path)
    await agent.setup(environment)
    with pytest.raises(ValueError, match="already contains"):
        await agent.run("task", environment, AgentContext(metadata={"dsh": {"other": "identity"}}))
    assert environment.runner_calls == 0


def test_only_frozen_t2_patch_path_is_allowed(tmp_path):
    with pytest.raises(ValueError, match="patch"):
        bridge(tmp_path, patches=["/tmp/model-selected.yml"])


@pytest.mark.parametrize("bad", [False, True])
def test_t2_setup_checks_actual_patch_bytes(tmp_path, bad):
    from uni_agent.agents.dsh.harbor_release import T2_PATCH_PATH, T2_PATCH_SHA256

    environment = FakeEnvironment()
    original = environment.exec

    async def exec_with_patch(*args, **kwargs):
        result = await original(*args, **kwargs)
        if result.stdout:
            probe = json.loads(result.stdout)
            probe["patches"] = [{"path": T2_PATCH_PATH, "sha256": "sha256:" + "0" * 64 if bad else T2_PATCH_SHA256}]
            result.stdout = json.dumps(probe)
        return result

    environment.exec = exec_with_patch
    agent = bridge(tmp_path, patches=[T2_PATCH_PATH])
    if bad:
        with pytest.raises(RuntimeError, match="patch"):
            asyncio.run(agent.setup(environment))
    else:
        asyncio.run(agent.setup(environment))
