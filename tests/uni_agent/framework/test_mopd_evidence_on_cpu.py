"""Audit the real native routing/scoring path without launching teacher workers."""

import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import numpy as np
import pytest
import torch

from tests.uni_agent.framework.test_generate_sequences_on_cpu import (
    _build_prompts,
    _FakeGatewayManager,
    _FakeTransferQueue,
    _inline_runner_config,
)
from tests.uni_agent.framework.test_teacher_scoring_on_cpu import _framework, _trajectory
from uni_agent.framework.framework import GatewayAgentFramework
from uni_agent.tasks import TaskResult
from verl.experimental.teacher_loop.teacher_manager import AsyncTeacherLLMServerManager

pytestmark = [pytest.mark.cpu, pytest.mark.level0]


@pytest.fixture(name="fake_tq")
def _fake_tq(monkeypatch):
    from uni_agent.framework import framework as framework_module

    fake = _FakeTransferQueue()
    monkeypatch.setattr(framework_module, "tq", fake)
    return fake


def _manager():
    manager = object.__new__(AsyncTeacherLLMServerManager)
    manager.teacher_key = "teacher_domain"
    manager.distillation_loss_config = SimpleNamespace(loss_settings=SimpleNamespace(use_topk=False))
    manager.teacher_model_configs = {
        domain: SimpleNamespace(model_path=f"/frozen/{domain}/step_10", inference=SimpleNamespace(temperature=1.0))
        for domain in ("swe", "terminal")
    }
    manager.teacher_client = {}
    for domain, value in (("swe", -0.25), ("terminal", -0.75)):
        manager.teacher_client[domain] = SimpleNamespace(
            generate=AsyncMock(
                return_value=SimpleNamespace(
                    extra_fields={"prompt_ids": [[11], [20], [21], [22], [0]], "prompt_logprobs": [[value]] * 5}
                )
            )
        )
    return manager


def _digest(ids):
    return "sha256:" + hashlib.sha256(json.dumps(ids, separators=(",", ":")).encode()).hexdigest()


@pytest.mark.asyncio
async def test_real_native_two_teacher_routing_binds_scoring_evidence():
    manager = _manager()
    framework = _framework(manager)
    for domain, value in (("swe", -0.25), ("terminal", -0.75)):
        result = await framework._compute_teacher_logprobs(
            [_trajectory()], {"teacher_domain": np.array(domain)}, validate=False
        )
        trajectory = result[0]
        evidence = trajectory.extra_fields["teacher_scoring_evidence"]
        assert trajectory.extra_fields["teacher_domain"] == domain
        assert evidence["resolved_teacher_key"] == domain
        assert evidence["configured_model_path"] == f"/frozen/{domain}/step_10"
        assert evidence["identity_source"] == "native_manager_configuration"
        assert evidence["loaded_weights_verified"] is False
        assert evidence["prompt_token_ids_sha256"] == _digest([10, 11])
        assert evidence["sequence_token_ids_sha256"] == _digest([10, 11, 20, 21, 22])
        assert evidence["response_mask_sha256"] == _digest([1, 0, 1])
        assert evidence["token_hash_encoding"] == "compact-json-integer-array-utf8"
        assert evidence["sequence_length"] == 5
        assert evidence["assistant_token_count"] == 2
        assert torch.all(trajectory.extra_fields["teacher_logprobs"] == value)
        manager.teacher_client[domain].generate.assert_awaited_once()
        assert manager.teacher_client[domain].generate.await_args.kwargs["prompt_ids"] == [10, 11, 20, 21, 22]


@pytest.mark.asyncio
@pytest.mark.parametrize("fields", [{}, {"teacher_domain": "unknown"}, {"teacher_domain": ""}])
async def test_missing_or_unknown_native_route_fails_before_any_teacher_request(fields):
    manager = _manager()
    trajectory = _trajectory()
    with pytest.raises(ValueError):
        await _framework(manager)._compute_teacher_logprobs([trajectory], fields, validate=False)
    for client in manager.teacher_client.values():
        client.generate.assert_not_awaited()
    assert "teacher_scoring_evidence" not in trajectory.extra_fields


@pytest.mark.asyncio
async def test_scoring_evidence_and_actual_tensors_survive_disk_and_tq(tmp_path):
    framework = _framework(_manager())
    fields = {"teacher_domain": "swe", "data_source": "tasks-train"}
    trajectory = (await framework._compute_teacher_logprobs([_trajectory()], fields, validate=False))[0]
    field, _ = framework._trajectory_to_tq_field_and_tag(
        trajectory=trajectory, sample_fields=fields, session_index=0, global_steps=1, uid="case"
    )
    assert field["teacher_domain"] == "swe"
    assert field["data_source"] == "tasks-train"
    assert field["extra_fields"]["teacher_scoring_evidence"] == trajectory.extra_fields["teacher_scoring_evidence"]
    framework._dump_trajectories(
        tmp_path,
        "session",
        [trajectory],
        partition_id="train",
        global_steps=1,
        group_uid="case",
        group_size=1,
        sample_index=0,
        session_index=0,
    )
    meta = json.loads((tmp_path / "trajectory.json").read_text())["trajectories"][0]
    assert meta["teacher_domain"] == "swe"
    assert meta["teacher_scoring_evidence"] == trajectory.extra_fields["teacher_scoring_evidence"]
    with np.load(tmp_path / "trajectory.npz") as dump:
        np.testing.assert_array_equal(dump["traj0_teacher_ids"], trajectory.extra_fields["teacher_ids"].numpy())
        np.testing.assert_array_equal(
            dump["traj0_teacher_logprobs"], trajectory.extra_fields["teacher_logprobs"].numpy()
        )


@pytest.mark.asyncio
async def test_unverifiable_mopd_manager_cannot_emit_successful_identity():
    manager = SimpleNamespace(teacher_key="teacher_domain", compute_teacher_logprobs_single=AsyncMock())
    with pytest.raises(ValueError, match="native teacher"):
        await _framework(manager)._compute_teacher_logprobs([_trajectory()], {"teacher_domain": "swe"}, validate=False)
    manager.compute_teacher_logprobs_single.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_scoring_emits_no_identity_on_input_trajectory():
    manager = _manager()
    manager.teacher_client["swe"].generate.side_effect = RuntimeError("scoring failed")
    trajectory = _trajectory()
    with pytest.raises(RuntimeError, match="scoring failed"):
        await _framework(manager)._compute_teacher_logprobs([trajectory], {"teacher_domain": "swe"}, validate=False)
    assert "teacher_scoring_evidence" not in trajectory.extra_fields


@pytest.mark.asyncio
async def test_hash_binds_tool_history_and_mask_not_just_student_actions():
    framework = _framework(_manager())
    original = _trajectory()
    altered = _trajectory()
    altered.response_ids[1] = 999  # Tool observation: masked out of gradients but still in teacher context.
    result = await framework._compute_teacher_logprobs([original, altered], {"teacher_domain": "swe"}, validate=False)
    first, second = [trajectory.extra_fields["teacher_scoring_evidence"] for trajectory in result]
    assert first["prompt_token_ids_sha256"] == second["prompt_token_ids_sha256"]
    assert first["sequence_token_ids_sha256"] != second["sequence_token_ids_sha256"]


@pytest.mark.asyncio
async def test_validation_keeps_domain_without_claiming_teacher_scored():
    framework = _framework(_manager())
    trajectory = (
        await framework._compute_teacher_logprobs([_trajectory()], {"teacher_domain": "terminal"}, validate=True)
    )[0]
    assert trajectory.extra_fields["teacher_domain"] == "terminal"
    assert "teacher_scoring_evidence" not in trajectory.extra_fields
    for client in framework.teacher_server_manager.teacher_client.values():
        client.generate.assert_not_awaited()


def _chain_guard_framework(count, *, flag=True, selection="all"):
    from omegaconf import OmegaConf

    async def runner(**kwargs):
        return TaskResult(reward=1.0, finished=True)

    config = OmegaConf.create(
        {
            "actor_rollout_ref": {
                "rollout": {
                    "n": 1,
                    "temperature": 1.0,
                    "top_p": 1.0,
                    "top_k": -1,
                    "calculate_log_probs": True,
                    "val_kwargs": {"n": 1},
                    "custom": {
                        "agent_framework": {
                            "agent_runners": {"runner": _inline_runner_config(runner, trajectory_selection=selection)},
                            "log_dir": None,
                            "fail_on_rollout_error": True,
                            "require_single_trajectory_per_session": flag,
                        }
                    },
                }
            }
        }
    )
    return GatewayAgentFramework.from_config(
        config=config,
        gateway_manager=_FakeGatewayManager({"session-sample-0-rollout-0": [_trajectory() for _ in range(count)]}),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [0, 2])
async def test_strict_chain_guard_rejects_whole_session_before_teacher_or_tq(count, fake_tq):
    framework = _chain_guard_framework(count)
    teacher = SimpleNamespace(teacher_key="teacher_route", compute_teacher_logprobs_single=AsyncMock())
    framework.teacher_server_manager = teacher
    with pytest.raises(RuntimeError, match="exactly one admitted trajectory"):
        await framework.generate_sequences(_build_prompts(count=1, global_steps=1))
    teacher.compute_teacher_logprobs_single.assert_not_awaited()
    assert not fake_tq.batch_puts


@pytest.mark.asyncio
@pytest.mark.parametrize("flag,count", [(True, 1), (False, 2)])
async def test_single_chain_guard_is_opt_in_and_keeps_legacy_all_chains(flag, count, fake_tq):
    framework = _chain_guard_framework(count, flag=flag)
    await framework.generate_sequences(_build_prompts(count=1, global_steps=1))
    assert len(fake_tq.batch_puts[0]["fields"]) == count


@pytest.mark.parametrize("flag", ["true", 1, None])
def test_chain_guard_requires_boolean(flag):
    with pytest.raises(ValueError, match="require_single_trajectory_per_session must be a bool"):
        _chain_guard_framework(1, flag=flag)


def test_chain_guard_cannot_hide_extra_chains_with_longest_selection():
    with pytest.raises(ValueError, match="trajectory_selection='all'"):
        _chain_guard_framework(2, selection="longest")


def test_chain_guard_cannot_silently_drop_failed_sessions():
    with pytest.raises(ValueError, match="requires fail_on_rollout_error"):
        GatewayAgentFramework(
            gateway_manager=SimpleNamespace(), runner_registry={}, require_single_trajectory_per_session=True
        )


@pytest.mark.asyncio
async def test_chain_guard_counts_postprocessed_admitted_trajectories(fake_tq):
    framework = _chain_guard_framework(1)
    framework._trajectory_postprocessor = lambda trajectories, **kwargs: list(trajectories) * 2
    with pytest.raises(RuntimeError, match="exactly one admitted trajectory"):
        await framework.generate_sequences(_build_prompts(count=1, global_steps=1))
    assert not fake_tq.batch_puts
