"""MiMo synchronous rollout must not cross policy versions."""

from types import SimpleNamespace

import pytest

from tests.uni_agent.framework.test_teacher_scoring_on_cpu import _trajectory
from uni_agent.framework.framework import GatewayAgentFramework


def framework(**kwargs):
    return GatewayAgentFramework(
        gateway_manager=SimpleNamespace(),
        runner_registry={},
        fail_on_rollout_error=True,
        require_version_evidence=True,
        require_single_policy_version=True,
        **kwargs,
    )


def test_single_version_guard_requires_complete_evidence():
    with pytest.raises(ValueError, match="requires require_version_evidence"):
        GatewayAgentFramework(
            gateway_manager=SimpleNamespace(),
            runner_registry={},
            fail_on_rollout_error=True,
            require_single_policy_version=True,
        )


@pytest.mark.parametrize("low,high,step", [(1, 2, 2), (0, 1, 1)])
def test_mixed_version_rejected(low, high, step):
    trajectory = _trajectory()
    trajectory.extra_fields.update(
        generation_count=2,
        versioned_generation_count=2,
        version_evidence_complete=True,
        min_global_steps=low,
        max_global_steps=high,
    )
    with pytest.raises(ValueError, match="single policy version"):
        framework()._trajectory_to_tq_field_and_tag(
            trajectory=trajectory, sample_fields={}, session_index=0, global_steps=step, uid="sample"
        )


def test_current_single_version_admitted():
    trajectory = _trajectory()
    trajectory.extra_fields.update(
        generation_count=2,
        versioned_generation_count=2,
        version_evidence_complete=True,
        min_global_steps=2,
        max_global_steps=2,
    )
    field, _ = framework()._trajectory_to_tq_field_and_tag(
        trajectory=trajectory, sample_fields={}, session_index=0, global_steps=3, uid="sample"
    )
    assert field["extra_fields"]["max_global_steps"] == 2
