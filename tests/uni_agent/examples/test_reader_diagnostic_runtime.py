import asyncio
import os
import signal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.fixture
def runtime_case(tmp_path, monkeypatch):
    import importlib

    importlib.import_module("uni_agent.framework.framework")
    from examples.dsh.capabilities import reader_diagnostic_runtime as runtime

    manifest = dict(
        root=str(tmp_path),
        model_path=str(tmp_path / "model"),
        model_name="reader-qwen",
        runner_python="/venv/bin/python",
        cuda_visible_devices="2",
    )
    (tmp_path / "model").mkdir()
    calls = []
    process = SimpleNamespace(pid=43210, poll=lambda: None, wait=lambda timeout: 0)

    def popen(args, **kwargs):
        calls.append((args, kwargs))
        return process

    kills = []
    monkeypatch.setattr(runtime.subprocess, "Popen", popen)
    monkeypatch.setattr(runtime.os, "killpg", lambda pid, sig: kills.append((pid, sig)))
    monkeypatch.setattr(runtime, "_wait_ready", AsyncMock())
    actor = SimpleNamespace(start=AsyncMock(), shutdown=AsyncMock())
    monkeypatch.setattr(runtime, "_create_actor", lambda *args: actor)
    return runtime, manifest, calls, kills, actor


def test_owned_backend_starts_pinned_and_stops_only_own_group(runtime_case):
    runtime, manifest, calls, kills, actor = runtime_case
    original_environment = dict(os.environ)

    async def run():
        async with runtime.open_executor(manifest) as execute:
            assert callable(execute)
            assert actor.start.await_count == 1

    asyncio.run(run())
    args, kwargs = calls[0]
    assert args[:3] == ["/venv/bin/python", "-m", "vllm.entrypoints.openai.api_server"]
    assert args[args.index("--model") + 1] == manifest["model_path"]
    assert args[args.index("--gpu-memory-utilization") + 1] == "0.5"
    assert args[args.index("--max-model-len") + 1] == "16384"
    assert "--enforce-eager" in args
    assert kwargs["start_new_session"] is True
    assert kwargs["env"]["CUDA_VISIBLE_DEVICES"] == "2"
    assert kwargs["env"]["DSH_RUNTIME_MODE"] == "exe"
    assert dict(os.environ) == original_environment
    assert kills == [(43210, signal.SIGTERM)]
    assert actor.shutdown.await_count == 1


@pytest.mark.parametrize("failure", ["startup", "cancel", "actor"])
def test_failure_and_cancellation_clean_owned_resources(runtime_case, failure):
    runtime, manifest, _, kills, actor = runtime_case
    if failure == "startup":
        runtime._wait_ready.side_effect = RuntimeError("unready")
    elif failure == "actor":
        actor.start.side_effect = RuntimeError("actor")

    async def run():
        async with runtime.open_executor(manifest):
            raise asyncio.CancelledError()

    with pytest.raises((RuntimeError, asyncio.CancelledError)):
        asyncio.run(run())
    assert kills == [(43210, signal.SIGTERM)]
    assert actor.shutdown.await_count == (0 if failure == "startup" else 1)


def test_executor_uses_real_framework_stage_and_inline_task_runner(runtime_case, monkeypatch, tmp_path):
    from examples.dsh.capabilities.memory_training_stage import GroupContext
    from uni_agent.framework import task_runner
    from uni_agent.gateway.session import SessionHandle, Trajectory
    from uni_agent.tasks.base import TaskResult

    runtime, manifest, _, _, actor = runtime_case
    actor.create_session = AsyncMock(return_value=SessionHandle("GB", "http://localhost/sessions/GB/v1"))
    actor.finalize_session = AsyncMock(return_value=[Trajectory([1], [2], [1], [-0.1])])
    actor.abort_session = AsyncMock()
    runner = AsyncMock(return_value=TaskResult(reward=0, verifier_reward=0, finished=False))
    monkeypatch.setattr(task_runner, "run_task", runner)
    spec = SimpleNamespace(
        context=GroupContext("run", "val", "group", 1, 3),
        raw_prompt=[{"role": "user", "content": "goal"}],
        metadata={"task_id": "task"},
        task_config_path=tmp_path / "task.yaml",
        gateway_session_id="GB",
    )

    async def run():
        async with runtime.open_executor(manifest) as execute:
            result = await execute(spec)
            assert result.session_id == "GB"
            assert result.context["group_size"] == 1
            assert result.task_result.finished is False
            assert result.run_dir.joinpath("trajectory.npz").exists()

    asyncio.run(run())
    assert runner.call_args.kwargs["require_result"] is True
    assert runner.call_args.kwargs["model_name"] == "reader-qwen"
    assert actor.create_session.call_args.kwargs["max_generated_tokens"] == 8192
    assert actor.create_session.call_args.kwargs["sampling_params"] == {
        "temperature": 0.7,
        "top_p": 0.9,
        "max_tokens": 4096,
    }


@pytest.mark.parametrize("model,exited", [("reader-qwen", False), ("other", False), ("reader-qwen", True)])
def test_readiness_requires_health_and_expected_model(monkeypatch, model, exited):
    import httpx

    from examples.dsh.capabilities.reader_diagnostic_runtime import _wait_ready

    requests = []

    def handle(request):
        requests.append(request.url.path)
        return httpx.Response(200, json={"data": [{"id": model}]})

    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handle), **kw))
    process = SimpleNamespace(poll=lambda: 1 if exited else None)
    if exited or model == "other":
        with pytest.raises(RuntimeError):
            asyncio.run(_wait_ready(process, "http://localhost:9999", "reader-qwen", timeout=1))
    else:
        asyncio.run(_wait_ready(process, "http://localhost:9999", "reader-qwen", timeout=1))
        assert requests == ["/health", "/v1/models"]


def test_actor_configuration_is_local_and_parser_pinned(monkeypatch, tmp_path):
    from unittest.mock import Mock

    import transformers

    from examples.dsh.capabilities.reader_diagnostic_runtime import _create_actor
    from uni_agent.gateway import gateway

    tokenizer = Mock()
    load = Mock(return_value=tokenizer)
    monkeypatch.setattr(transformers.AutoTokenizer, "from_pretrained", load)
    make = Mock()
    monkeypatch.setattr(gateway, "_GatewayActor", make)
    _create_actor({"model_path": tmp_path, "model_name": "qwen"}, "http://localhost:9999")
    assert load.call_args.kwargs == {"local_files_only": True, "trust_remote_code": False}
    config, backend = make.call_args.args
    assert config.tool_parser_name == "hermes" and config.rollout_backend == "vllm"
    assert config.apply_chat_template_kwargs == {"enable_thinking": False}
    assert config.prompt_length == config.response_length == 8192
    assert backend._completions_url == "http://localhost:9999/v1/completions"


def test_import_does_not_load_cuda_or_transformers():
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import examples.dsh.capabilities.reader_diagnostic_runtime; "
                "assert 'torch' not in sys.modules; assert 'transformers' not in sys.modules"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_stubborn_owned_backend_kills_same_group_only(runtime_case):
    runtime, _, _, kills, _ = runtime_case
    from unittest.mock import Mock

    process = SimpleNamespace(pid=43210, wait=Mock(side_effect=[runtime.subprocess.TimeoutExpired("owned", 10), 0]))
    asyncio.run(runtime._stop_process(process))
    assert kills == [(43210, signal.SIGTERM), (43210, signal.SIGKILL)]


def test_inline_stage_timeout_aborts_session_then_stops_owned_backend(runtime_case, monkeypatch, tmp_path):
    from examples.dsh.capabilities.memory_training_stage import GroupContext
    from uni_agent.framework import task_runner
    from uni_agent.gateway.session import SessionHandle

    runtime, manifest, _, kills, actor = runtime_case
    manifest["stage_timeout_seconds"] = 0.01
    actor.create_session = AsyncMock(return_value=SessionHandle("GB", "http://localhost/sessions/GB/v1"))
    actor.abort_session = AsyncMock()

    async def hanging_runner(**kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr(task_runner, "run_task", hanging_runner)
    spec = SimpleNamespace(
        context=GroupContext("run", "val", "group", 1, 3),
        raw_prompt=[],
        metadata={},
        task_config_path=tmp_path / "task.yaml",
        gateway_session_id="GB",
    )

    async def run():
        async with runtime.open_executor(manifest) as execute:
            await execute(spec)

    with pytest.raises(TimeoutError):
        asyncio.run(run())
    actor.abort_session.assert_awaited_once_with("GB")
    assert actor.shutdown.await_count == 1
    assert kills == [(43210, signal.SIGTERM)]
