"""OPD must extend the resident memory frameworks without loosening admission."""

from unittest.mock import Mock

import pytest
from omegaconf import OmegaConf

from tests.uni_agent.framework.test_native_memory_framework import ForbiddenRewardWorker
from tests.uni_agent.framework.test_native_memory_framework import wired as native_wired
from uni_agent.framework.memory_chain import NativeMemoryFramework
from uni_agent.framework.work_state import NativeWorkStateFramework
from verl.experimental.teacher_loop import teacher_manager

wired = native_wired
pytestmark = [pytest.mark.cpu, pytest.mark.level0]


def _config(wired, framework_cls, tmp_path):
    original, _, _, _ = wired
    config = OmegaConf.create(OmegaConf.to_container(original.test_full_config))
    config.distillation = {"enabled": True}
    if framework_cls is NativeWorkStateFramework:
        spec = config.actor_rollout_ref.rollout.custom.agent_framework.memory_operator
        spec.task_manifest = str(tmp_path / "manifest.json")
        spec.task_manifest_sha256 = "frozen-manifest"
        spec.family = "work-state-v1"
    return config


@pytest.mark.parametrize("framework_cls", [NativeMemoryFramework, NativeWorkStateFramework])
def test_resident_framework_forwards_teacher_and_keeps_memory_contract(wired, framework_cls, tmp_path, monkeypatch):
    _, gateway, _, _ = wired
    config = _config(wired, framework_cls, tmp_path)
    clients = {"qwen": object()}
    teacher = object()
    factory = Mock(return_value=teacher)
    monkeypatch.setattr(teacher_manager, "AsyncTeacherLLMServerManager", factory)

    framework = framework_cls.from_config(
        config=config,
        gateway_manager=gateway,
        teacher_client=clients,
        reward_loop_worker_handles=[ForbiddenRewardWorker()],
    )

    factory.assert_called_once_with(config=config, teacher_client=clients)
    assert framework.teacher_server_manager is teacher
    assert framework.reward_loop_worker_handles is None
    assert framework._fail_on_rollout_error
    assert framework._require_finished_episode
    assert framework._require_verifier_reward
    assert framework._require_trajectory_dump
    assert framework._rollout_config.n == 4
    assert framework._rollout_config.val_kwargs.n == 1
    assert type(framework._memory_operator) is framework_cls.operator_type


@pytest.mark.parametrize("framework_cls", [NativeMemoryFramework, NativeWorkStateFramework])
@pytest.mark.parametrize(
    "field,value,error",
    [
        ("trainer.v1.trainer_mode", "async", "sync"),
        ("actor_rollout_ref.rollout.n", 1, "n4"),
        ("actor_rollout_ref.rollout.custom.agent_framework.require_verifier_reward", False, "require_verifier_reward"),
    ],
)
def test_resident_opd_rejects_weakened_training_contract(
    wired, framework_cls, field, value, error, tmp_path, monkeypatch
):
    _, gateway, _, _ = wired
    config = _config(wired, framework_cls, tmp_path)
    OmegaConf.update(config, field, value)
    monkeypatch.setattr(teacher_manager, "AsyncTeacherLLMServerManager", Mock(return_value=object()))
    with pytest.raises(ValueError, match=error):
        framework_cls.from_config(config=config, gateway_manager=gateway, teacher_client={"qwen": object()})
