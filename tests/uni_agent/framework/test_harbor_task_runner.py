"""Runtime-owned Harbor bindings must never be supplied by dataset samples."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from uni_agent.framework import task_runner
from uni_agent.tasks import TaskResult


@pytest.fixture
def captured_runner(monkeypatch):
    captured = {}

    class Resolver:
        def resolve(self, sample_config, runtime_model):
            captured["runtime_model"] = runtime_model
            return {**sample_config, "gateway_base_url": "stale", "runner_context": {"stale": True}}

    class FakeTask:
        async def run(self):
            return TaskResult(reward=0, finished=True)

    def build(config):
        captured["task"] = config
        return FakeTask()

    monkeypatch.setattr(task_runner, "TaskConfigResolver", Resolver)
    monkeypatch.setattr(task_runner, "get_task", build)
    return captured


def runtime():
    return {
        "partition_id": "train",
        "gateway_session_id": "session-1",
        "global_steps": 0,
        "group_uid": "group-1",
        "group_size": 2,
        "sample_index": 0,
        "session_index": 0,
    }


def session():
    return SimpleNamespace(session_id="session-1", base_url="http://gateway:1234/sessions/session-1/v1")


@pytest.mark.asyncio
async def test_runtime_bindings_override_defaults_without_mutating_framework(captured_runner):
    context = runtime()
    original = deepcopy(context)
    prompt = [{"role": "user", "content": "Frozen instruction"}]
    await task_runner.run_task(
        session=session(),
        raw_prompt=prompt,
        tools_kwargs={"task": {"name": "harbor_dsh"}, "_runner_context": context},
    )
    task = captured_runner["task"]
    assert task["gateway_base_url"] == session().base_url
    assert task["runner_context"] == original
    assert task["runner_context"] is not context
    task["runner_context"]["group_uid"] = "changed"
    assert context == original
    assert task["prompt"] == prompt
    # Harbor owns its remote Agent; no unused local Agent model is injected.
    assert captured_runner["runtime_model"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["gateway_base_url", "runner_context"])
async def test_sample_cannot_supply_runtime_fields(captured_runner, field):
    with pytest.raises(ValueError, match="runtime"):
        await task_runner.run_task(
            session=session(),
            raw_prompt=[{"role": "user", "content": "Frozen instruction"}],
            tools_kwargs={"task": {"name": "harbor_dsh", field: None}, "_runner_context": runtime()},
        )
    assert "task" not in captured_runner


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault",
    [
        "context_missing",
        "context_empty",
        "context_wrong_session",
        "session_missing",
        "url_missing",
        "url_wrong_session",
    ],
)
async def test_missing_or_mismatched_live_identity_never_executes(captured_runner, fault):
    handle, context = session(), runtime()
    if fault == "context_missing":
        context = None
    elif fault == "context_empty":
        context = {}
    elif fault == "context_wrong_session":
        context["gateway_session_id"] = "different"
    elif fault == "session_missing":
        handle = None
    elif fault == "url_missing":
        handle.base_url = ""
    else:
        handle.base_url = "http://gateway:1234/sessions/different/v1"
    with pytest.raises(ValueError, match="Harbor"):
        await task_runner.run_task(
            session=handle,
            raw_prompt=[{"role": "user", "content": "Frozen instruction"}],
            tools_kwargs={"task": {"name": "harbor_dsh"}, "_runner_context": context},
        )
    assert "task" not in captured_runner


@pytest.mark.asyncio
async def test_real_resolver_loads_operator_fields_without_runtime_placeholders(monkeypatch, tmp_path):
    import yaml

    from tests.uni_agent.tasks.test_harbor_dsh_task import config
    from uni_agent.tasks.harbor_dsh.task import HarborDshTask

    cfg = config(tmp_path)
    defaults = cfg.model_dump(mode="json", exclude={"gateway_base_url", "runner_context", "prompt"})
    defaults["worker_token"] = "a" * 32
    path = tmp_path / "task.yaml"
    path.write_text(yaml.safe_dump(defaults))
    captured = {}

    async def run(instance):
        captured["config"] = instance.config
        return TaskResult(reward=0, finished=True)

    monkeypatch.setattr(HarborDshTask, "run", run)
    context = cfg.runner_context.model_dump(mode="json")
    await task_runner.run_task(
        session=SimpleNamespace(session_id="session-1", base_url=cfg.gateway_base_url),
        raw_prompt=cfg.prompt,
        tools_kwargs={"task": {"name": "harbor_dsh"}, "_runner_context": context},
        task_config_path=str(path),
        require_result=True,
    )
    assert captured["config"].gateway_base_url == cfg.gateway_base_url
    assert captured["config"].runner_context == cfg.runner_context
    assert captured["config"].instruction == cfg.instruction
    assert captured["config"].agent is None and captured["config"].sandbox is None
    for field in cfg.task_config_only_fields:
        with pytest.raises(ValueError, match="task-config-only"):
            await task_runner.run_task(
                session=SimpleNamespace(session_id="session-1", base_url=cfg.gateway_base_url),
                raw_prompt=cfg.prompt,
                tools_kwargs={"task": {"name": "harbor_dsh", field: defaults[field]}, "_runner_context": context},
                task_config_path=str(path),
            )
