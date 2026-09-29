import json
from dataclasses import replace
from pathlib import Path

import pytest

from tests.uni_agent.gateway.test_session_multiple_chains_on_cpu import _run
from tests.uni_agent.support import FakeTokenizer
from tests.uni_agent.tasks import test_harbor_dsh_task as fixtures
from tests.uni_agent.tasks.test_harbor_budget_terminal import MODE, terminal_contents
from uni_agent.gateway.session import GatewaySession, MessageCodec, SessionHandle
from uni_agent.tasks.base import build_reward_info
from uni_agent.tasks.dsh.trajectory_audit import TrajectoryAuditError
from uni_agent.tasks.harbor_dsh.protocol import RequestPolicy
from uni_agent.tasks.harbor_dsh.task import HarborDshTask
from uni_agent.tasks.harbor_dsh.trajectory_audit import validate_trajectories
from verl.workers.rollout.replica import TokenOutput

pytestmark = [pytest.mark.cpu, pytest.mark.level0]
transport = fixtures.transport


async def make_case(tmp_path, transport, *, completed=False, score=1.0, context_limit=False):
    limits = {"max_generated_tokens": 9 if completed or context_limit else 3, "trajectory_capacity": 1000}
    codec = MessageCodec(FakeTokenizer())
    messages = [{"role": "user", "content": "Write the answer"}]
    if context_limit:
        limits["trajectory_capacity"] = len(codec.build_initial_tokens(messages)) + 3
    session = GatewaySession(
        SessionHandle("session-1"),
        codec,
        max_generated_tokens=limits["max_generated_tokens"],
        prompt_length=limits["trajectory_capacity"] - 3,
        response_length=3,
        sampling_params={"logprobs": True},
    )

    class Backend:
        async def generate(self, *, sampling_params, **kwargs):
            count = min(3, sampling_params["max_tokens"])
            return TokenOutput(
                token_ids=[65] * count,
                log_probs=[-0.1] * count,
                stop_reason="completed" if completed else "length",
            )

    await _run(session, Backend(), messages, max_tokens=3)
    trajectory = (await session.finalize())[0]
    original = fixtures.config(tmp_path)
    policy = RequestPolicy.model_validate(
        {
            **original.policy.model_dump(),
            "termination_policy": MODE,
            "budget_limits": limits,
        }
    )
    cfg = fixtures.config(tmp_path, policy=policy)
    transport[1].update(score=score)
    if not completed:
        transport[1]["fn"] = lambda request, contents: terminal_contents(contents)
    result = await HarborDshTask(cfg).run()
    trajectory = replace(
        trajectory,
        finished=result.finished,
        reward_score=score,
        extra_fields={
            **trajectory.extra_fields,
            "dsh_reward_info": build_reward_info(result),
        },
    )
    kwargs = dict(
        context=cfg.runner_context.model_dump(),
        artifact_root=cfg.artifact_root,
        run_id=cfg.run_id,
        worker_id=cfg.worker_id,
        task_ref=cfg.task_ref,
        policy=policy,
        instruction=cfg.instruction,
        termination_policy=MODE,
        budget_limits=limits,
    )
    directory = Path(result.reward_info["harbor_dsh"]["receipt_path"]).parent
    return trajectory, result, kwargs, directory


@pytest.mark.asyncio
@pytest.mark.parametrize("completed,context_limit,score", [(True, False, 1.0), (False, False, 0.0), (False, True, 1.0)])
async def test_real_gateway_and_worker_evidence_online_then_read_only_offline(
    tmp_path, transport, completed, context_limit, score
):
    trajectory, result, kwargs, directory = await make_case(
        tmp_path,
        transport,
        completed=completed,
        context_limit=context_limit,
        score=score,
    )
    with pytest.raises(TrajectoryAuditError):
        validate_trajectories((trajectory,), **kwargs)
    assert not list(directory.glob("admission-chain-*.json"))
    admitted = validate_trajectories((trajectory,), task_result=result, **kwargs)[0]
    assert admitted.finished is completed
    assert admitted.reward_score == score
    assert admitted.response_ids is trajectory.response_ids
    assert any(admitted.response_mask)
    assert admitted.extra_fields["budget_admission"]["termination_kind"] == (
        "completed" if completed else "budget_exhausted"
    )
    saved = directory / f"admission-chain-{admitted.chain_id}.json"
    before = saved.read_bytes()
    assert saved.stat().st_mode & 0o777 == 0o600
    again = validate_trajectories((admitted,), **kwargs)[0]
    assert again.extra_fields == admitted.extra_fields
    assert saved.read_bytes() == before
    body = json.loads(before)
    body["termination_kind"] = "forged"
    saved.write_text(json.dumps(body))
    with pytest.raises(TrajectoryAuditError):
        validate_trajectories((admitted,), **kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize("attack", ["proof", "token", "limits", "policy", "finished", "receipt"])
async def test_joint_admission_fails_closed_before_writing_private_evidence(tmp_path, transport, attack):
    trajectory, result, kwargs, directory = await make_case(tmp_path, transport)
    if attack == "proof":
        trajectory.extra_fields.pop("gateway_budget_proof")
    elif attack == "token":
        trajectory.response_ids[0] += 1
    elif attack == "limits":
        kwargs["budget_limits"] = {**kwargs["budget_limits"], "max_generated_tokens": 4}
    elif attack == "policy":
        kwargs["termination_policy"] = "completed-only"
    elif attack == "finished":
        trajectory.finished = True
    else:
        path = directory / "receipt.json"
        path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(TrajectoryAuditError):
        validate_trajectories((trajectory,), task_result=result, **kwargs)
    assert not list(directory.glob("admission-chain-*.json"))
