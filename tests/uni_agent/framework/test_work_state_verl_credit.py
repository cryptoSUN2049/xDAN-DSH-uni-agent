"""Actual work-state CPU stage/TQ layout into locked VERL GRPO; no GPU trainer."""

import asyncio
import json
from types import SimpleNamespace

import numpy as np
import pytest
import torch

from examples.dsh.capabilities.memory_verifier import canonical, sha
from examples.dsh.capabilities.work_state import stage
from examples.dsh.capabilities.work_state.tasks import make_task
from tests.uni_agent.examples.test_memory_credit_grpo import pinned_math as locked_math
from tests.uni_agent.examples.test_work_state_stage import execute_synthetic_stage
from tests.uni_agent.framework.test_native_memory_framework import wired as native_wired
from uni_agent.framework import framework as framework_module
from uni_agent.framework.memory_chain import audit_memory_chain_crosswalk
from uni_agent.framework.work_state import NativeWorkStateFramework
from verl.protocol import DataProto
from verl.trainer.ppo import core_algos

wired = native_wired
pinned_math = locked_math


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal", [(0, 0, 0, 0), (1, 1, 1, 1), (0, 0, 1, 1)])
async def test_actual_workstate_n4_layout_only_terminal_b_creates_variance(
    wired, tmp_path, monkeypatch, pinned_math, terminal
):
    base, manager, queue, _ = wired
    task = make_task("WS01", 0, 16)
    manifest = tmp_path / "credit-tasks.json"
    manifest.write_bytes(
        canonical(
            {
                "schema": "dsh.work-state-dataset.v1",
                "tasks": {task["task_id"]: {"family": "WS01", "variant": 0, "seed": 16, "split": "train"}},
            }
        )
    )
    operator = stage.WorkStateOperator(
        **{**vars(base._memory_operator), "family": "work-state-v1"},
        task_manifest=manifest,
        task_manifest_sha256=sha(manifest.read_bytes()),
    )
    config = base.test_full_config
    config.actor_rollout_ref.rollout.custom.agent_framework.memory_operator = {
        k: str(v) if hasattr(v, "__fspath__") else v for k, v in vars(operator).items()
    }
    framework = NativeWorkStateFramework.from_config(config=config, gateway_manager=manager)
    specs, executions = {}, []
    for name in ("prepare_writer_stage", "freeze_and_prepare_reader"):
        original = getattr(stage, name)

        def capture(*args, _original=original, **kwargs):
            spec = _original(*args, **kwargs)
            specs[str(spec.task_config_path)] = spec
            return spec

        monkeypatch.setattr(stage, name, capture)

    async def remote(**kwargs):
        spec = specs[kwargs["runner_kwargs"]["task_config_path"]]
        bad = spec.role == "writer" or terminal[spec.context.sibling] == 0
        execution = await asyncio.to_thread(execute_synthetic_stage, spec, bad_memory=bad)
        # CPU token fixture includes a tool/context position; production tokens are untouched.
        for trajectory in execution.trajectories:
            trajectory.response_ids = [2, 3, 4]
            trajectory.response_mask = [1, 0, 1]
            trajectory.response_logprobs = [-0.1, 0.0, -0.2]
        manager.by_session[spec.gateway_session_id] = execution.trajectories
        executions.append(execution)
        return execution.task_result

    monkeypatch.setattr(framework_module, "_run_agent_runner_ray_task", SimpleNamespace(remote=remote))
    result = await framework._run_prompt_rollouts(
        sample_fields={
            "uid": "workstate-credit",
            "agent_name": "task",
            "raw_prompt": [],
            "tools_kwargs": {"task": {"metadata": {"work_state_task_id": task["task_id"]}}},
        },
        sample_index=0,
        global_steps=7,
        partition_id="train",
        num_sessions=4,
    )
    assert result["num_success_sessions"] == 4, result
    crosswalk_path = next(operator.root.glob("groups/*/crosswalk.json"))
    crosswalk_before = crosswalk_path.read_bytes()
    record = json.loads(crosswalk_before)
    audit = audit_memory_chain_crosswalk(crosswalk_path)
    batch = queue.batches[0]
    keys, fields = batch["keys"], batch["fields"]
    assert keys == audit["keys"] == [f"workstate-credit_{s}_{i}" for s in range(4) for i in range(2)]
    assert audit["terminal_rewards"] == list(terminal)
    assert [item["role"] for item in record["items"]] == ["A", "B"] * 4
    rewards = fields["rm_scores"].to_padded_tensor(0)
    masks = fields["response_mask"].to_padded_tensor(0)
    original_rewards = rewards.clone()
    expected_stage_rewards = torch.tensor([score for b in terminal for score in (0.0, float(b))])
    torch.testing.assert_close(rewards.sum(dim=1), expected_stage_rewards)
    assert masks.tolist() == [[1, 0, 1]] * 8
    data = DataProto.from_dict(
        tensors={"token_level_rewards": rewards, "response_mask": masks},
        non_tensors={"uid": np.array([fields["uid"][i] for i in range(len(keys))])},
    )
    output = pinned_math(data, keys, core_algos.AdvantageEstimator.GRPO, num_repeat=4)
    advantage = output.batch["advantages"]
    assert torch.isfinite(advantage).all()
    assert torch.count_nonzero(advantage[:, 1]) == 0
    for sibling in range(4):
        torch.testing.assert_close(advantage[2 * sibling], advantage[2 * sibling + 1])
    if len(set(terminal)) == 1:
        assert torch.count_nonzero(advantage) == 0
    else:
        centered = torch.tensor(terminal, dtype=torch.float32)
        centered = (centered - centered.mean()) / (centered.std() + 1e-6)
        expected = centered.repeat_interleave(2).unsqueeze(1) * masks
        torch.testing.assert_close(advantage, expected)
        assert torch.count_nonzero(advantage) == 16
    torch.testing.assert_close(output.batch["returns"], advantage)
    torch.testing.assert_close(data.batch["token_level_rewards"], original_rewards)
    torch.testing.assert_close(fields["rm_scores"].to_padded_tensor(0), original_rewards)
    assert crosswalk_path.read_bytes() == crosswalk_before
    assert sorted(e.task_result.reward for e in executions) == sorted(expected_stage_rewards.tolist())
