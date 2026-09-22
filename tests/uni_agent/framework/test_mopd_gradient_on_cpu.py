"""Numerical contracts for pinned native PG MOPD; no surrogate/source-text tests."""

from __future__ import annotations

import math

import pytest
import torch
from tensordict import TensorDict

from verl.trainer.distillation.losses import distillation_ppo_loss
from verl.utils import tensordict_utils as tu
from verl.workers.config import (
    ActorConfig,
    DistillationConfig,
    DistillationLossConfig,
    DistillationTeacherModelConfig,
    RolloutConfig,
)

pytestmark = [pytest.mark.cpu, pytest.mark.level0]
DTYPE = torch.float64


def _configs(*, coefficient=1.0):
    actor = ActorConfig(strategy="fsdp", rollout_n=1, use_dynamic_bsz=True, loss_agg_mode="token-mean")
    distill = DistillationConfig(
        enabled=True,
        n_gpus_per_node=2,
        nnodes=1,
        teacher_models={
            "teacher_model": DistillationTeacherModelConfig(
                model_path="unused-frozen-teacher", inference=RolloutConfig(name="vllm")
            )
        },
        distillation_loss=DistillationLossConfig(
            loss_mode="k1",
            use_policy_gradient=True,
            use_task_rewards=False,
            policy_loss_mode="vanilla",
            loss_max_clamp=5.0,
            log_prob_min_clamp=None,
            clip_ratio=0.2,
            clip_ratio_low=0.2,
            clip_ratio_high=0.2,
            distillation_loss_coef=coefficient,
        ),
    )
    return actor, distill


def _data(rows, *, global_tokens=None, global_rows=None, dp_size=1, environment_advantage=7.0):
    """Rows hold full next-token logps; masks only describe response positions."""
    tensor_lists = {name: [] for name in ("prompts", "responses", "response_mask", "old_log_probs", "advantages")}
    teachers = []
    for row in rows:
        prompt_len, mask = row["prompt_len"], row["mask"]
        response_len = len(mask)
        tensor_lists["prompts"].append(torch.arange(prompt_len))
        tensor_lists["responses"].append(torch.arange(response_len))
        tensor_lists["response_mask"].append(torch.tensor(mask, dtype=torch.bool))
        tensor_lists["old_log_probs"].append(torch.tensor(row["old"], dtype=DTYPE))
        tensor_lists["advantages"].append(torch.full((response_len,), environment_advantage, dtype=DTYPE))
        teachers.append(torch.tensor(row["teacher"], dtype=DTYPE).unsqueeze(-1))
    data = TensorDict(
        {name: tu.nested_tensor_from_tensor_list(values) for name, values in tensor_lists.items()},
        batch_size=[len(rows)],
    )
    data["teacher_logprobs"] = tu.nested_tensor_from_tensor_list(teachers, ragged_idx=1)
    for name, value in {
        "dp_size": dp_size,
        "batch_num_tokens": global_tokens if global_tokens is not None else sum(sum(row["mask"]) for row in rows),
        "global_batch_size": global_rows if global_rows is not None else len(rows),
    }.items():
        tu.assign_non_tensor_data(data, name, value)
    return data


def _run(rows, *, coefficient=1.0, **kwargs):
    current = torch.tensor([value for row in rows for value in row["current"]], dtype=DTYPE, requires_grad=True)
    data = _data(rows, **kwargs)
    loss, metrics = distillation_ppo_loss(*_configs(coefficient=coefficient), {"log_probs": current}, data)
    loss.backward()
    assert torch.isfinite(loss) and torch.isfinite(current.grad).all()
    return loss.detach(), current.grad.detach(), metrics


def _single(*, current=-3.0, teacher=-2.0, old=-3.0):
    # Two prompt tokens, one response. Only position1 predicts the response.
    return [
        {
            "prompt_len": 2,
            "mask": [1],
            "current": [-20.0, current, -20.0],
            "teacher": [-0.1, teacher, -0.1],
            "old": [old],
        }
    ]


def test_k1_uses_current_actor_not_old_anchor_and_advantage_is_detached():
    # q-current=0.05; q-old=0.15. A stale rollout/old-policy advantage gives a
    # different numerical result. Differentiating through A also changes grad.
    loss, gradient, _ = _run(_single(current=-1.9, teacher=-1.85, old=-2.0))
    expected = -0.05 * math.exp(0.1)
    assert loss.item() == pytest.approx(expected)
    assert gradient[1].item() == pytest.approx(expected)
    assert gradient[[0, 2]].eq(0).all()


@pytest.mark.parametrize("current,teacher,expected", [(-10.0, -0.1, -5.0), (-0.1, -10.0, 5.0)])
def test_advantage_clip5_caps_magnitude_without_killing_policy_gradient(current, teacher, expected):
    loss, gradient, _ = _run(_single(current=current, teacher=teacher, old=current))
    assert loss.item() == pytest.approx(expected)
    assert gradient[1].item() == pytest.approx(expected)


@pytest.mark.parametrize(
    "advantage,ratio,expected_loss,expected_grad",
    [
        (1.0, 1.1, -1.1, -1.1),
        (1.0, 1.5, -1.2, 0.0),  # PPO upper clip for positive advantage.
        (-1.0, 0.5, 0.8, 0.0),  # PPO lower clip for negative advantage.
        (-1.0, 2.0, 2.0, 2.0),  # Negative advantage is NOT capped at1.2.
        (-1.0, 4.0, 3.0, 0.0),  # Native dual clip3 caps the negative tail.
    ],
)
def test_native_ppo_and_dual_clip_have_expected_gradients(advantage, ratio, expected_loss, expected_grad):
    rows = _single(current=-3.0, teacher=-3.0 + advantage, old=-3.0 - math.log(ratio))
    loss, gradient, _ = _run(rows)
    assert loss.item() == pytest.approx(expected_loss)
    assert gradient[1].item() == pytest.approx(expected_grad)


def _unequal_domain_rows():
    # Domain A has2 assistant tokens; domain B has4. Non-response and tool
    # positions have extreme disagreement to expose accidental mask leakage.
    return [
        {
            "prompt_len": 2,
            "mask": [1, 0, 1],
            "current": [-9.0] * 5,
            "teacher": [-0.1, -8.0, -50.0, -8.0, -0.1],
            "old": [-9.0] * 3,
        },
        {
            "prompt_len": 3,
            "mask": [1, 1, 0, 1, 1],
            "current": [-9.0] * 8,
            "teacher": [-0.1, -0.1, -11.0, -11.0, -50.0, -11.0, -11.0, -0.1],
            "old": [-9.0] * 5,
        },
    ]


def test_variable_lengths_masks_and_global_token_weighting():
    rows = _unequal_domain_rows()
    loss, gradient, _ = _run(rows)
    # Mean over six generated action tokens, not a mean of domain means.
    assert loss.item() == pytest.approx((-2.0 + 8.0) / 6)
    torch.testing.assert_close(gradient[[1, 3]], torch.full((2,), -1 / 6, dtype=DTYPE))
    torch.testing.assert_close(gradient[[7, 8, 10, 11]], torch.full((4,), 2 / 6, dtype=DTYPE))
    assert gradient[[0, 2, 4, 5, 6, 9, 12]].eq(0).all()


@pytest.mark.parametrize("dp_size", [1, 2])
def test_microbatch_partition_and_simulated_dp_average_preserve_global_gradient(dp_size):
    rows = _unequal_domain_rows()
    whole_loss, whole_gradient, _ = _run(rows)
    pieces = [_run([row], global_tokens=6, global_rows=2, dp_size=dp_size) for row in rows]
    # dp_size=2 models the SUM of rank losses followed by DDP gradient average;
    # dp_size=1 models accumulating two uneven microbatches on one rank.
    torch.testing.assert_close(sum(piece[0] for piece in pieces) / dp_size, whole_loss)
    torch.testing.assert_close(torch.cat([piece[1] for piece in pieces]) / dp_size, whole_gradient)
    # A local token denominator would bias equal-sized domain contributions.
    wrong_loss = sum(_run([row])[0] for row in rows) / 2
    assert not torch.isclose(wrong_loss, whole_loss)


def test_pure_opd_ignores_environment_advantage_and_coefficient_knob():
    rows = _unequal_domain_rows()
    loss, gradient, _ = _run(rows, environment_advantage=100.0, coefficient=0.01)
    flipped_loss, flipped_gradient, _ = _run(rows, environment_advantage=-300.0, coefficient=99.0)
    torch.testing.assert_close(loss, flipped_loss)
    torch.testing.assert_close(gradient, flipped_gradient)
