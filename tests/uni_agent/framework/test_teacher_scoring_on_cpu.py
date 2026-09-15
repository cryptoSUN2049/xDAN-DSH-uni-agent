"""Teacher supervision must stay aligned from admitted trajectories through TQ."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import numpy as np
import pytest
import torch

from uni_agent.framework.framework import GatewayAgentFramework, _list_of_tq_fields_to_tensordict
from uni_agent.gateway.session import Trajectory

pytestmark = [pytest.mark.cpu, pytest.mark.level0]


def _trajectory(response_ids=None):
    response_ids = [20, 21, 22] if response_ids is None else response_ids
    return Trajectory(
        prompt_ids=[10, 11],
        response_ids=response_ids,
        response_mask=[1, 0] + [1] * (len(response_ids) - 2),
        response_logprobs=[-0.1] * len(response_ids),
        finished=True,
        reward_score=1.0,
        reward_metrics={"verifier_reward": 1.0},
        num_turns=2,
        multi_modal_data={},
        extra_fields={"dsh_reward_info": {"receipt_sha256": "verified"}},
    )


def _signal(sequence_length=5, topk=2):
    ids = torch.arange(sequence_length * topk, dtype=torch.int32).reshape(sequence_length, topk)
    # Distinct positions reveal an accidental second roll of already shifted rows.
    logprobs = -(ids.float() + 1) / 10
    return ids, logprobs


def _framework(manager=None):
    return GatewayAgentFramework(gateway_manager=SimpleNamespace(), runner_registry={}, teacher_server_manager=manager)


def _manager(**kwargs):
    return SimpleNamespace(teacher_key="teacher_route", compute_teacher_logprobs_single=AsyncMock(**kwargs))


def _tq_field(framework, trajectory):
    field, _ = framework._trajectory_to_tq_field_and_tag(
        trajectory=trajectory, sample_fields={"uid": "case"}, session_index=0, global_steps=1, uid="case"
    )
    return field


@pytest.mark.asyncio
@pytest.mark.parametrize("topk", [1, 2, 32])
async def test_teacher_scores_student_sequence_without_second_shift_or_mask_changes(topk):
    signal = _signal(topk=topk)
    manager = _manager(return_value=signal)
    framework = _framework(manager)
    original = _trajectory()
    original.extra_fields["mm_processor_kwargs"] = {"min_pixels": 16}
    original.multi_modal_data = {"images": ["image-object"]}
    snapshot = deepcopy(original)

    result = await framework._compute_teacher_logprobs([original], {"teacher_route": "qwen"}, validate=False)

    manager.compute_teacher_logprobs_single.assert_awaited_once_with(
        sequence_ids=[10, 11, 20, 21, 22],
        multi_modal_data={"images": ["image-object"]},
        mm_processor_kwargs={"min_pixels": 16},
        routing_key="qwen",
    )
    assert len(result) == 1 and result[0] is not original
    assert original == snapshot
    assert result[0].response_mask == [1, 0, 1]
    assert result[0].response_ids == original.response_ids
    assert result[0].reward_score == 1.0
    assert result[0].extra_fields["dsh_reward_info"] == snapshot.extra_fields["dsh_reward_info"]
    torch.testing.assert_close(result[0].extra_fields["teacher_ids"], signal[0])
    torch.testing.assert_close(result[0].extra_fields["teacher_logprobs"], signal[1])


@pytest.mark.asyncio
@pytest.mark.parametrize("routing_key", ["qwen", np.str_("qwen"), np.array("qwen"), np.array(["qwen"])])
async def test_teacher_route_normalizes_singleton_dataset_scalars(routing_key):
    manager = _manager(return_value=_signal())
    await _framework(manager)._compute_teacher_logprobs([_trajectory()], {"teacher_route": routing_key}, validate=False)
    assert manager.compute_teacher_logprobs_single.await_args.kwargs["routing_key"] == "qwen"
    assert type(manager.compute_teacher_logprobs_single.await_args.kwargs["routing_key"]) is str


@pytest.mark.asyncio
async def test_absent_teacher_route_is_delegated_to_manager_default():
    manager = _manager(return_value=_signal())
    await _framework(manager)._compute_teacher_logprobs([_trajectory()], {}, validate=False)
    assert manager.compute_teacher_logprobs_single.await_args.kwargs["routing_key"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("validate,has_manager", [(True, True), (False, False), (True, False)])
async def test_validation_and_rl_only_do_not_request_teacher(validate, has_manager):
    manager = _manager(side_effect=AssertionError("Teacher must not run"))
    trajectory = _trajectory()
    result = await _framework(manager if has_manager else None)._compute_teacher_logprobs(
        [trajectory], {}, validate=validate
    )
    assert result == [trajectory]
    assert "teacher_ids" not in trajectory.extra_fields
    manager.compute_teacher_logprobs_single.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "signal",
    [
        (torch.ones(4, 2, dtype=torch.int32), torch.zeros(4, 2)),
        (torch.ones(5, 2, dtype=torch.int32), torch.zeros(5, 3)),
        (torch.ones(5, 0, dtype=torch.int32), torch.zeros(5, 0)),
        (torch.ones(5, dtype=torch.int32), torch.zeros(5)),
        (torch.ones(5, 2), torch.zeros(5, 2)),
        (torch.ones(5, 2, dtype=torch.int32), torch.full((5, 2), float("nan"))),
        (torch.ones(5, 2, dtype=torch.int32), torch.full((5, 2), float("inf"))),
    ],
    ids=["wrong-length", "different-shapes", "empty-topk", "wrong-rank", "float-ids", "nan", "inf"],
)
async def test_malformed_teacher_supervision_fails_closed_without_mutation(signal):
    original = _trajectory()
    snapshot = deepcopy(original)
    with pytest.raises(ValueError):
        await _framework(_manager(return_value=signal))._compute_teacher_logprobs([original], {}, validate=False)
    assert original == snapshot


@pytest.mark.asyncio
async def test_teacher_failure_after_first_trajectory_does_not_partially_mutate_inputs():
    originals = [_trajectory(), _trajectory([20, 21, 22, 23, 24])]
    snapshot = deepcopy(originals)
    manager = _manager(side_effect=[_signal(), RuntimeError("Teacher unavailable")])
    with pytest.raises(RuntimeError, match="Teacher unavailable"):
        await _framework(manager)._compute_teacher_logprobs(originals, {}, validate=False)
    assert originals == snapshot
    assert manager.compute_teacher_logprobs_single.await_count == 2


@pytest.mark.asyncio
async def test_teacher_tq_fields_are_top_level_and_ragged_on_sequence_axis():
    signals = [_signal(5, 2), _signal(7, 2)]
    framework = _framework(_manager(side_effect=signals))
    trajectories = await framework._compute_teacher_logprobs(
        [_trajectory(), _trajectory([20, 21, 22, 23, 24])], {}, validate=False
    )
    fields = [_tq_field(framework, trajectory) for trajectory in trajectories]
    for field, trajectory, signal in zip(fields, trajectories, signals, strict=True):
        for name, expected in zip(("teacher_ids", "teacher_logprobs"), signal, strict=True):
            assert name not in field["extra_fields"]
            assert name in trajectory.extra_fields, "TQ conversion must not mutate the trajectory"
            torch.testing.assert_close(field[name], expected)
        assert field["loss_mask"].tolist() == trajectory.response_mask
        assert field["extra_fields"]["dsh_reward_info"] == {"receipt_sha256": "verified"}

    batch = _list_of_tq_fields_to_tensordict(fields)
    for name, signal_index in (("teacher_ids", 0), ("teacher_logprobs", 1)):
        assert batch[name].is_nested
        assert batch[name].values().shape == (12, 2)
        assert batch[name].offsets().tolist() == [0, 5, 12]
        for actual, signal in zip(batch[name].unbind(), signals, strict=True):
            torch.testing.assert_close(actual, signal[signal_index])


@pytest.mark.parametrize("missing", ["teacher_ids", "teacher_logprobs", "both"])
@pytest.mark.parametrize("missing_index", [0, 1])
def test_partial_teacher_batch_must_not_silently_drop_supervision(missing, missing_index):
    ids, logprobs = _signal()
    fields = [
        {"input_ids": torch.arange(5), "teacher_ids": ids.clone(), "teacher_logprobs": logprobs.clone()}
        for _ in range(2)
    ]
    for key in ("teacher_ids", "teacher_logprobs") if missing == "both" else (missing,):
        del fields[missing_index][key]
    with pytest.raises(ValueError):
        _list_of_tq_fields_to_tensordict(fields)
