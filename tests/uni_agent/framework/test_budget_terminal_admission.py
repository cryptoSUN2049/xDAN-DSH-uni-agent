import json

import pytest

from examples.dsh.ops.audit_qwen3_4b_online_rl import _load_dump_trajectory
from tests.uni_agent.framework.test_gateway_stage_execution import build
from uni_agent.gateway.session import Trajectory

pytestmark = [pytest.mark.cpu, pytest.mark.level0]


def test_budget_proof_survives_exact_dump_roundtrip(tmp_path):
    proof = {"schema": "uni-agent.gateway-budget-proof.v1", "sentinel": "must-not-disappear"}
    info = {"reward": 0.0, "verifier_reward": 0.0, "finished": False}
    trajectory = Trajectory(
        [1, 2],
        [3, 4],
        [1, 0],
        [-0.1, 0.0],
        finished=False,
        reward_score=0.0,
        reward_metrics={"verifier_reward": 0.0},
        chain_id=1,
        extra_fields={
            "dsh_reward_info": info,
            "gateway_budget_proof": proof,
            "budget_admission": {"schema": "sentinel"},
            "session_exhaustion_reason": "max_generated_tokens",
        },
    )
    framework, _, _ = build(tmp_path)
    # Legacy mode dump also preserves evidence, but never authorizes it.
    framework._dump_trajectories(
        tmp_path,
        "session-1",
        [trajectory],
        partition_id="train",
        global_steps=1,
        group_uid="group-1",
        group_size=4,
        sample_index=0,
        session_index=0,
    )
    entry = json.loads((tmp_path / "trajectory.json").read_text())["trajectories"][0]
    restored = _load_dump_trajectory(
        npz_bytes=(tmp_path / "trajectory.npz").read_bytes(), trajectory_meta=entry, trajectory_index=0
    )
    assert restored.chain_id == 1
    assert restored.finished is False
    assert restored.extra_fields["gateway_budget_proof"] == proof
    assert restored.extra_fields["budget_admission"] == {"schema": "sentinel"}
    assert restored.extra_fields["session_exhaustion_reason"] == "max_generated_tokens"


@pytest.mark.parametrize("policy", [True, "budget-terminal", "", None])
def test_rejects_unknown_termination_policy(tmp_path, policy):
    with pytest.raises(ValueError, match="termination_policy"):
        build(tmp_path, termination_policy=policy)


@pytest.mark.parametrize(
    "missing",
    [
        "fail_on_rollout_error",
        "require_finished_episode",
        "require_verifier_reward",
        "require_trajectory_dump",
        "trajectory_postprocessor_pass_context",
    ],
)
def test_budget_policy_cannot_disable_strict_evidence(tmp_path, missing):
    settings = dict(
        termination_policy="budget-terminal-v1",
        fail_on_rollout_error=True,
        require_finished_episode=True,
        require_verifier_reward=True,
        require_trajectory_dump=True,
        trajectory_postprocessor_pass_context=True,
        max_generated_tokens_per_episode=3,
    )
    settings[missing] = False
    with pytest.raises(ValueError, match="budget-terminal"):
        build(tmp_path, **settings)


def test_dump_reader_rejects_false_completion_projection(tmp_path):
    import io

    import numpy as np

    buf = io.BytesIO()
    np.savez(buf, traj0_prompt_ids=[1], traj0_response_ids=[2], traj0_response_mask=[1], traj0_response_logprobs=[-0.1])
    entry = dict(
        prompt_len=1,
        response_len=1,
        model_token_count=1,
        has_logprobs=True,
        reward_score=0.0,
        reward_extra_info={"verifier_reward": 0.0},
        reward_info={"reward": 0.0, "finished": False},
        finished=True,
    )
    with pytest.raises(ValueError, match="completion"):
        _load_dump_trajectory(npz_bytes=buf.getvalue(), trajectory_meta=entry, trajectory_index=0)
