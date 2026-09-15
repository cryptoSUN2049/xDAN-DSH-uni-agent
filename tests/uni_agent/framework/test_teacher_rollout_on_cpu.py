"""Exercise Teacher wiring through the adapter and the real rollout/TQ stages."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import torch
from omegaconf import OmegaConf

from tests.uni_agent.framework.test_generate_sequences_on_cpu import (
    _build_framework_with_agent_runners,
    _build_prompts,
    _FakeGatewayManager,
    _FakeTransferQueue,
    _inline_runner_config,
)
from tests.uni_agent.framework.test_teacher_scoring_on_cpu import _signal, _trajectory
from uni_agent.framework import entry
from uni_agent.framework import framework as framework_module
from uni_agent.framework.framework import GatewayAgentFramework
from uni_agent.tasks import TaskResult
from verl.experimental.teacher_loop import teacher_manager
from verl.workers.utils.padding import no_padding_2_padding

pytestmark = [pytest.mark.cpu, pytest.mark.level0]


@pytest.fixture
def fake_tq(monkeypatch):
    queue = _FakeTransferQueue()
    monkeypatch.setattr(framework_module, "tq", queue)
    return queue


@pytest.mark.parametrize("enabled,clients", [(True, None), (True, {}), (False, {"qwen": object()})])
def test_adapter_rejects_mismatched_distillation_before_spawning_gateway(monkeypatch, enabled, clients):
    spawn = Mock(side_effect=AssertionError("Invalid configuration must fail before allocating actors"))
    monkeypatch.setattr(entry, "build_gateway_manager", spawn)
    with pytest.raises(ValueError):
        entry.AgentFrameworkRolloutAdapter.create(
            config=OmegaConf.create({"distillation": {"enabled": enabled}}),
            llm_client=object(),
            teacher_client=clients,
        )
    spawn.assert_not_called()


def _config(enabled):
    return OmegaConf.create(
        {
            "distillation": {"enabled": enabled},
            "actor_rollout_ref": {
                "model": {},
                "rollout": {
                    "custom": {
                        "agent_framework": {
                            "log_dir": "",
                            "agent_runners": {"runner": {"runner_fqn": "tests.uni_agent.support.logging_runner"}},
                        }
                    }
                },
            },
        }
    )


def test_adapter_worker_build_and_from_config_preserve_teacher_client(monkeypatch):
    config = _config(True)
    clients = {"qwen": object()}
    gateway = object()
    manager = object()
    factory = Mock(return_value=manager)
    monkeypatch.setattr(teacher_manager, "AsyncTeacherLLMServerManager", factory)
    monkeypatch.setattr(entry, "build_gateway_manager", lambda **kwargs: gateway)
    monkeypatch.setattr(entry, "omega_conf_to_dataclass", lambda config: SimpleNamespace(processor=None))
    monkeypatch.setattr(entry, "tq", SimpleNamespace(init=Mock()))
    monkeypatch.setattr(entry, "init_rollout_trace_config", Mock())
    # Run the real Ray actor implementation in-process; only the actor transport is replaced.
    worker_class = entry.AgentFrameworkWorker.__ray_metadata__.modified_class
    remote = Mock(side_effect=lambda **kwargs: worker_class(**kwargs))
    monkeypatch.setattr(entry, "AgentFrameworkWorker", SimpleNamespace(remote=remote))

    adapter = entry.AgentFrameworkRolloutAdapter.create(config=config, llm_client=object(), teacher_client=clients)

    factory.assert_called_once_with(config=config, teacher_client=clients)
    assert remote.call_args.kwargs["teacher_client"] is clients
    assert adapter.gateway_manager is gateway
    assert isinstance(adapter.framework_worker.framework, GatewayAgentFramework)
    assert adapter.framework_worker.framework.teacher_server_manager is manager


def test_rl_only_custom_framework_does_not_require_new_teacher_argument(monkeypatch):
    result = object()

    class ExistingCustomFramework:
        @classmethod
        def from_config(cls, *, config, gateway_manager, processor, reward_loop_worker_handles):
            return result

    monkeypatch.setattr(entry, "load_class_from_fqn", lambda fqn: ExistingCustomFramework)
    monkeypatch.setattr(entry, "omega_conf_to_dataclass", lambda config: SimpleNamespace(processor=None))
    assert entry.build_agent_framework(config=_config(False), gateway_manager=object()) is result


async def _finished_runner(**kwargs):
    return TaskResult(reward=1.0, verifier_reward=1.0, finished=True)


async def _rollout_framework(manager, *, count=1):
    runtime = _FakeGatewayManager({f"session-sample-0-rollout-{i}": [_trajectory()] for i in range(count)})
    framework = await _build_framework_with_agent_runners(
        agent_runners={"runner": _inline_runner_config(_finished_runner)},
        gateway_manager=runtime,
        n=count,
        val_n=count,
        log_dir="",
        fail_on_rollout_error=True,
        require_finished_episode=True,
        require_verifier_reward=True,
    )
    framework.teacher_server_manager = manager
    return framework


@pytest.mark.asyncio
@pytest.mark.parametrize("validate", [False, True])
async def test_real_rollout_scores_train_and_skips_teacher_on_validation(fake_tq, validate):
    signal = _signal()
    manager = SimpleNamespace(teacher_key="data_source", compute_teacher_logprobs_single=AsyncMock(return_value=signal))
    framework = await _rollout_framework(manager)

    await framework.generate_sequences(_build_prompts(count=1, validate=validate))

    assert len(fake_tq.batch_puts) == 1
    batch = fake_tq.batch_puts[0]["fields"]
    assert batch["loss_mask"].unbind()[0].tolist() == [1, 0, 1]
    assert batch["rm_scores"].unbind()[0].tolist() == [0, 0, 1]
    if validate:
        manager.compute_teacher_logprobs_single.assert_not_awaited()
        assert "teacher_ids" not in batch
        assert "teacher_logprobs" not in batch
    else:
        manager.compute_teacher_logprobs_single.assert_awaited_once()
        assert manager.compute_teacher_logprobs_single.await_args.kwargs["routing_key"] == "deepeyes"
        torch.testing.assert_close(batch["teacher_ids"].unbind()[0], signal[0])
        torch.testing.assert_close(batch["teacher_logprobs"].unbind()[0], signal[1])
        response_teacher = no_padding_2_padding(batch["teacher_logprobs"], batch)
        # VERL consumes rows prompt_len-1 .. seq_len-2. The tool position remains in
        # context but has action loss mask zero, independently from Teacher scores.
        torch.testing.assert_close(response_teacher[0], signal[1][1:4])
        assert response_teacher.shape == (1, 3, 2)
        assert batch["loss_mask"].unbind()[0][1].item() == 0


@pytest.mark.asyncio
async def test_strict_group_teacher_failure_writes_no_sibling_trajectory(fake_tq):
    manager = SimpleNamespace(
        teacher_key="data_source",
        compute_teacher_logprobs_single=AsyncMock(side_effect=[_signal(), RuntimeError("Teacher unavailable")]),
    )
    framework = await _rollout_framework(manager, count=2)

    with pytest.raises(RuntimeError, match="rollout failure"):
        await framework.generate_sequences(_build_prompts(count=1))

    assert manager.compute_teacher_logprobs_single.await_count == 2
    assert fake_tq.batch_puts == []
    assert fake_tq.puts == [
        {"key": "uid-0", "partition_id": "train", "tag": {"status": status}} for status in ("running", "failure")
    ]
