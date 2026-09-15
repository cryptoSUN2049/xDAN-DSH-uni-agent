"""Require actual Gateway version evidence before a strict group reaches TQ."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from omegaconf import OmegaConf

from tests.uni_agent.framework.test_generate_sequences_on_cpu import (
    _build_prompts,
    _FakeGatewayManager,
    _FakeTransferQueue,
    _inline_runner_config,
)
from tests.uni_agent.framework.test_teacher_rollout_on_cpu import _finished_runner
from tests.uni_agent.framework.test_teacher_scoring_on_cpu import _trajectory
from uni_agent.framework import framework as module
from uni_agent.framework.framework import GatewayAgentFramework

pytestmark = [pytest.mark.cpu, pytest.mark.level0]


def _evidence():
    return {
        "generation_count": 2,
        "versioned_generation_count": 2,
        "version_evidence_complete": True,
        "min_global_steps": 3,
        "max_global_steps": 5,
    }


def _config(required=True, strict=True):
    return OmegaConf.create(
        {
            "actor_rollout_ref": {
                "rollout": {
                    "n": 2,
                    "temperature": 1.0,
                    "top_p": 1.0,
                    "top_k": -1,
                    "calculate_log_probs": True,
                    "val_kwargs": {"n": 1, "temperature": 0.0, "top_p": 1.0, "top_k": -1},
                    "custom": {
                        "agent_framework": {
                            "log_dir": "",
                            "fail_on_rollout_error": strict,
                            "require_version_evidence": required,
                            "agent_runners": {"runner": _inline_runner_config(_finished_runner)},
                        }
                    },
                }
            }
        }
    )


@pytest.mark.parametrize("required", [None, 0, 1, "true", [], {}])
def test_version_evidence_config_requires_boolean(required):
    with pytest.raises(ValueError, match="require_version_evidence"):
        GatewayAgentFramework.from_config(config=_config(required), gateway_manager=SimpleNamespace())


def test_version_evidence_requires_atomic_group_admission():
    with pytest.raises(ValueError, match="fail_on_rollout_error"):
        GatewayAgentFramework.from_config(config=_config(True, False), gateway_manager=SimpleNamespace())


def test_direct_constructor_cannot_bypass_strict_version_contract():
    with pytest.raises(ValueError, match="fail_on_rollout_error"):
        GatewayAgentFramework(gateway_manager=SimpleNamespace(), runner_registry={}, require_version_evidence=True)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        {},
        {"generation_count": 0},
        {"generation_count": True},
        {"versioned_generation_count": 1},
        {"versioned_generation_count": 2.0},
        {"version_evidence_complete": False},
        {"version_evidence_complete": 1},
        {"min_global_steps": None},
        {"min_global_steps": -1},
        {"max_global_steps": True},
        {"max_global_steps": 5.0},
        {"min_global_steps": 6, "max_global_steps": 5},
    ],
    ids=[
        "missing",
        "empty",
        "bool-count",
        "partial",
        "float-count",
        "incomplete",
        "truthy",
        "missing-min",
        "negative",
        "bool-max",
        "float-max",
        "reverse-span",
    ],
)
async def test_bad_version_evidence_rejects_entire_group_without_scheduler_fallback(monkeypatch, change):
    first, second = _trajectory(), _trajectory()
    first.extra_fields.update(_evidence())
    if change:
        second.extra_fields.update({**_evidence(), **change})
    queue = _FakeTransferQueue()
    monkeypatch.setattr(module, "tq", queue)
    framework = GatewayAgentFramework.from_config(
        config=_config(),
        gateway_manager=_FakeGatewayManager(
            {"session-sample-0-rollout-0": [first], "session-sample-0-rollout-1": [second]}
        ),
    )
    snapshot = deepcopy(second.extra_fields)
    with pytest.raises(RuntimeError, match="rollout failure"):
        await framework.generate_sequences(_build_prompts(count=1, global_steps=99))
    assert queue.batch_puts == []
    assert queue.puts == [
        {"key": "uid-0", "partition_id": "train", "tag": {"status": status}} for status in ("running", "failure")
    ]
    assert second.extra_fields == snapshot


@pytest.mark.asyncio
async def test_complete_cross_version_spans_keep_actual_min_max(monkeypatch):
    queue = _FakeTransferQueue()
    monkeypatch.setattr(module, "tq", queue)
    trajectories = [_trajectory(), _trajectory()]
    for trajectory in trajectories:
        trajectory.extra_fields.update(_evidence())
    framework = GatewayAgentFramework.from_config(
        config=_config(),
        gateway_manager=_FakeGatewayManager(
            {f"session-sample-0-rollout-{i}": [trajectory] for i, trajectory in enumerate(trajectories)}
        ),
    )
    await framework.generate_sequences(_build_prompts(count=1, global_steps=99))
    assert len(queue.batch_puts) == 1
    assert [(tag["min_global_steps"], tag["max_global_steps"]) for tag in queue.batch_puts[0]["tags"]] == [
        (3, 5),
        (3, 5),
    ]


def test_default_rl_still_allows_legacy_scheduler_fallback():
    framework = GatewayAgentFramework(gateway_manager=SimpleNamespace(), runner_registry={})
    _, tag = framework._trajectory_to_tq_field_and_tag(
        trajectory=_trajectory(), sample_fields={}, session_index=0, global_steps=99, uid="legacy"
    )
    assert (tag["min_global_steps"], tag["max_global_steps"]) == (99, 99)
