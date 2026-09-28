import asyncio
import hashlib
import json

import numpy as np
import pytest

from uni_agent.framework.framework import GatewayAgentFramework, _RunnerConfig
from uni_agent.gateway.session import SessionHandle, Trajectory
from uni_agent.tasks import TaskResult


async def _noop(**kwargs):
    return None


class Manager:
    def __init__(self, trajectories):
        self.trajectories = trajectories
        self.created = []
        self.finalized = []
        self.aborted = []

    async def create_session(self, session_id, **kwargs):
        self.created.append((session_id, kwargs))
        return SessionHandle(session_id, f"http://resident/{session_id}/v1")

    async def finalize_session(self, session_id):
        self.finalized.append(session_id)
        return self.trajectories

    async def abort_session(self, session_id):
        self.aborted.append(session_id)


def build(tmp_path, trajectories=None, **kwargs):
    if trajectories is None:
        trajectories = [Trajectory([11, 12], [13, 14, 15], [1, 0, 1], [-0.5, 0.0, -0.25], num_turns=2)]
    manager = Manager(trajectories)
    config = _RunnerConfig(f"{__name__}._noop", {}, "inline_async", 0)
    framework = GatewayAgentFramework(manager, runner_registry={"runner": config}, log_dir=str(tmp_path), **kwargs)
    args = dict(
        sample_fields={"raw_prompt": [{"role": "user", "content": "task"}], "uid": "group-1"},
        sample_index=2,
        session_index=3,
        global_steps=5,
        partition_id="train",
        group_size=4,
        runner_name="runner",
        runner_config=config,
        sampling_params={"temperature": 0.7},
    )
    return framework, manager, args


@pytest.mark.asyncio
async def test_stage_preserves_result_context_and_resident_manager(tmp_path):
    framework, manager, args = build(tmp_path)
    result = TaskResult(
        reward=0.75, verifier_reward=0.75, accuracy=0.5, finished=True, reward_info={"evidence": {"digest": "fixed"}}
    )
    calls = []

    async def runner(**kwargs):
        calls.append(kwargs)
        kwargs["tools_kwargs"]["_runner_context"]["group_uid"] = "runner-mutation"
        return result

    framework._inline_runners["runner"] = runner
    for index in range(8):
        stage = await framework._execute_gateway_stage(
            **args, stage_session_id=f"chain-stage-{index}", dump_consumption_crosswalk=False
        )
        assert stage.session_id == f"chain-stage-{index}"
        assert stage.task_result is result
        assert stage.sample_fields is args["sample_fields"]
        assert stage.context == dict(
            partition_id="train",
            gateway_session_id=stage.session_id,
            global_steps=5,
            group_uid="group-1",
            group_size=4,
            sample_index=2,
            session_index=3,
        )
        assert stage.run_dir == tmp_path / "step_5" / stage.session_id
        assert stage.trajectories[0].response_ids is manager.trajectories[0].response_ids
        assert stage.trajectories[0].reward_score == 0.75
        assert stage.trajectories[0].extra_fields["dsh_reward_info"]["evidence"] == {"digest": "fixed"}
    assert framework.gateway_manager is manager
    assert len(manager.created) == len(manager.finalized) == len(calls) == 8
    assert len({call["session"].base_url for call in calls}) == 8
    assert manager.aborted == []
    assert manager.created[0][1]["sampling_params"] == args["sampling_params"]
    assert manager.created[0][1]["sampling_params"] is not args["sampling_params"]


@pytest.mark.asyncio
async def test_stage_dump_has_identical_tokens_without_consumption_key(tmp_path):
    framework, manager, args = build(tmp_path)
    stage = await framework._execute_gateway_stage(**args, stage_session_id="stage-A", dump_consumption_crosswalk=False)
    legacy = await framework._run_agent_episode(**args)
    assert isinstance(legacy, tuple) and len(legacy) == 2 and legacy[1] is args["sample_fields"]
    old_dir = tmp_path / "step_5" / manager.finalized[-1]
    old = json.loads((old_dir / "trajectory.json").read_text())
    new = json.loads((stage.run_dir / "trajectory.json").read_text())
    assert old["schema"] == "uni-agent.trajectory-dump.v2"
    assert old["trajectories"][0]["transfer_queue_key"] == "group-1_3_0"
    assert new["schema"] == "uni-agent.gateway-stage-dump.v1"
    assert "transfer_queue_key" not in json.dumps(new)
    assert (
        new["trajectory_npz_sha256"]
        == "sha256:" + hashlib.sha256((stage.run_dir / "trajectory.npz").read_bytes()).hexdigest()
    )
    with np.load(old_dir / "trajectory.npz") as before, np.load(stage.run_dir / "trajectory.npz") as after:
        assert before.files == after.files
        for name in before.files:
            np.testing.assert_array_equal(before[name], after[name])
        np.testing.assert_array_equal(after["traj0_response_ids"], [13, 14, 15])
        np.testing.assert_array_equal(after["traj0_response_mask"], [1, 0, 1])
        np.testing.assert_array_equal(after["traj0_response_logprobs"], [-0.5, 0.0, -0.25])


@pytest.mark.asyncio
async def test_empty_stage_retains_result_without_dump(tmp_path):
    framework, manager, args = build(tmp_path, [])
    stage = await framework._execute_gateway_stage(**args)
    assert stage.trajectories == [] and isinstance(stage.task_result, TaskResult)
    assert stage.context["gateway_session_id"] == stage.session_id
    assert stage.sample_fields is args["sample_fields"]
    assert len(manager.finalized) == 1 and manager.aborted == []
    assert not (stage.run_dir / "trajectory.npz").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [RuntimeError("runner failed"), asyncio.CancelledError()])
async def test_stage_error_aborts_without_finalizing(tmp_path, failure):
    framework, manager, args = build(tmp_path)

    async def runner(**kwargs):
        raise failure

    framework._inline_runners["runner"] = runner
    with pytest.raises(type(failure)):
        await framework._execute_gateway_stage(**args, stage_session_id="failed-stage")
    assert len(manager.created) == 1
    assert manager.aborted == ["failed-stage"] and manager.finalized == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "identity",
    ["", ".", "..", "../escape", "/absolute", "a/b", "a\\b", "has space", "a\n", "中文", "a" * 129, 1, False],
)
async def test_unsafe_stage_id_rejected_before_gateway_or_files(tmp_path, identity):
    framework, manager, args = build(tmp_path)
    with pytest.raises(ValueError, match="stage_session_id"):
        await framework._execute_gateway_stage(**args, stage_session_id=identity)
    assert manager.created == []
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_sample_cannot_inject_stage_operator_options(tmp_path):
    framework, manager, args = build(tmp_path)
    args["sample_fields"].update(stage_session_id="../escape", dump_consumption_crosswalk=False)
    stage = await framework._execute_gateway_stage(**args)
    assert stage.session_id.startswith("session-sample-2-rollout-3-")
    dump = json.loads((stage.run_dir / "trajectory.json").read_text())
    assert dump["schema"] == "uni-agent.trajectory-dump.v2"


@pytest.mark.asyncio
@pytest.mark.parametrize("flag", [0, 1, "false", None])
async def test_crosswalk_flag_must_be_bool(tmp_path, flag):
    framework, manager, args = build(tmp_path)
    with pytest.raises(ValueError, match="dump_consumption_crosswalk"):
        await framework._execute_gateway_stage(**args, dump_consumption_crosswalk=flag)
    assert manager.created == []


@pytest.mark.asyncio
async def test_trusted_stage_budget_reaches_real_gateway_session(tmp_path):
    from tests.uni_agent.gateway.test_session_generation_budget import Backend
    from tests.uni_agent.support import FakeTokenizer
    from uni_agent.gateway.config import GatewayActorConfig
    from uni_agent.gateway.gateway import _GatewayActor

    framework, manager, args = build(tmp_path)
    actor = _GatewayActor(GatewayActorConfig(tokenizer=FakeTokenizer()), Backend())
    actor._server_base_url = "http://resident"
    framework.gateway_manager = actor
    args["sample_fields"]["max_generated_tokens"] = 999
    seen = []

    async def runner(**kwargs):
        seen.append(actor._sessions[kwargs["session"].session_id]._max_generated_tokens)
        return TaskResult()

    framework._inline_runners["runner"] = runner
    for stage in ("A", "B"):
        await framework._execute_gateway_stage(**args, stage_session_id=stage, max_generated_tokens=8192)
    assert seen == [8192, 8192]


@pytest.mark.asyncio
@pytest.mark.parametrize("budget", [None, 8192])
async def test_regular_episode_passes_only_operator_generation_budget(tmp_path, budget):
    framework, manager, args = build(tmp_path, max_generated_tokens_per_episode=budget)
    args["sample_fields"]["max_generated_tokens_per_episode"] = 999999
    await framework._run_agent_episode(**args)
    if budget is None:
        assert "max_generated_tokens" not in manager.created[0][1]
    else:
        assert manager.created[0][1]["max_generated_tokens"] == budget


@pytest.mark.parametrize("budget", [0, -1, True, 1.5, "8192"])
def test_regular_episode_rejects_invalid_generation_budget(tmp_path, budget):
    with pytest.raises(ValueError, match="max_generated_tokens_per_episode"):
        build(tmp_path, max_generated_tokens_per_episode=budget)


@pytest.mark.asyncio
@pytest.mark.parametrize("reason_key", ["materialization_reason", "session_exhaustion_reason"])
@pytest.mark.parametrize("reason", ["max_generated_tokens", "max_trajectory_length"])
async def test_budgeted_episode_cannot_hide_truncation_with_longest_selection(tmp_path, reason_key, reason):
    trajectories = [
        Trajectory([11], [12], [1], [-0.1], extra_fields={reason_key: reason}),
        Trajectory([13], [14, 15], [1, 1], [-0.2, -0.3]),
    ]
    framework, manager, args = build(tmp_path, trajectories, max_generated_tokens_per_episode=14336)
    args["runner_config"].trajectory_selection = "longest"

    async def runner(**kwargs):
        return TaskResult(reward=1.0, verifier_reward=1.0, finished=True)

    framework._inline_runners["runner"] = runner
    with pytest.raises(ValueError, match="truncated rollout"):
        await framework._run_agent_episode(**args)
    assert all(t.reward_score is None for t in trajectories)
    assert manager.finalized and not manager.aborted
    assert not list(tmp_path.rglob("trajectory.npz"))


def test_from_config_passes_episode_budget(tmp_path):
    from omegaconf import OmegaConf

    cfg = OmegaConf.create(
        {
            "actor_rollout_ref": {
                "rollout": {
                    "custom": {
                        "agent_framework": {
                            "agent_runners": {
                                "runner": {"runner_fqn": f"{__name__}._noop", "dispatch_mode": "inline_async"}
                            },
                            "log_dir": str(tmp_path),
                            "max_generated_tokens_per_episode": 14336,
                        }
                    }
                }
            }
        }
    )
    framework = GatewayAgentFramework.from_config(config=cfg, gateway_manager=Manager([]))
    assert framework._max_generated_tokens_per_episode == 14336
