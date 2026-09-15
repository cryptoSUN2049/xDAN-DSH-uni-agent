"""Exercise the pinned VERL OPD + task-reward loss, including real gradients."""

import numpy as np
import pytest
import torch

from tests.uni_agent.framework.test_teacher_scoring_on_cpu import _framework, _tq_field, _trajectory
from uni_agent.framework.framework import _list_of_tq_fields_to_tensordict
from verl.trainer.distillation.losses import distillation_ppo_loss
from verl.trainer.ppo.core_algos import compute_grpo_outcome_advantage
from verl.utils import tensordict_utils as tu
from verl.workers.config import (
    ActorConfig,
    DistillationConfig,
    DistillationLossConfig,
    DistillationTeacherModelConfig,
    RolloutConfig,
)
from verl.workers.utils.losses import ppo_loss

pytestmark = [pytest.mark.cpu, pytest.mark.level0]


def _batch(*, reward_reversed=False, teacher_delta=0.2, tool_teacher_delta=0.2):
    fields = []
    for reward in [0.0, 1.0] if reward_reversed else [1.0, 0.0]:
        trajectory = _trajectory()
        trajectory.reward_score = reward
        trajectory.extra_fields.update(
            teacher_ids=torch.tensor([[11], [20], [21], [22], [0]], dtype=torch.int32),
            teacher_logprobs=torch.tensor(
                [[-1.0], [-1.0 + teacher_delta], [-1.0 + tool_teacher_delta], [-1.0 + teacher_delta], [0.0]]
            ),
        )
        fields.append(_tq_field(_framework(), trajectory))
    data = _list_of_tq_fields_to_tensordict(fields)
    rewards = torch.stack([field["rm_scores"] for field in fields])
    mask = torch.stack([field["response_mask"] for field in fields])
    advantages, _ = compute_grpo_outcome_advantage(rewards, mask, np.array(["task-1", "task-1"]))
    data["advantages"] = tu.nested_tensor_from_tensor_list(list(advantages))
    data["old_log_probs"] = tu.nested_tensor_from_tensor_list([torch.full((3,), -1.0), torch.full((3,), -1.0)])
    for name, value in {"dp_size": 1, "batch_num_tokens": 4, "global_batch_size": 2}.items():
        tu.assign_non_tensor_data(data, name, value)
    return data, advantages


def _run(*, mode, coefficient=0.3, reward_reversed=False, teacher_delta=0.2, tool_teacher_delta=0.2):
    data, advantages = _batch(
        reward_reversed=reward_reversed, teacher_delta=teacher_delta, tool_teacher_delta=tool_teacher_delta
    )
    student = torch.full((10,), -1.0, requires_grad=True)
    config = ActorConfig(strategy="fsdp", rollout_n=2, use_dynamic_bsz=True, loss_agg_mode="token-mean")
    if mode == "rl":
        loss, metrics = ppo_loss(config, {"log_probs": student}, data)
    else:
        distillation = DistillationConfig(
            enabled=True,
            n_gpus_per_node=2,
            nnodes=1,
            teacher_models={
                "teacher_model": DistillationTeacherModelConfig(
                    model_path="synthetic-teacher", inference=RolloutConfig(name="vllm")
                )
            },
            distillation_loss=DistillationLossConfig(
                loss_mode="k1",
                use_policy_gradient=True,
                use_task_rewards=mode == "hybrid",
                distillation_loss_coef=coefficient,
                loss_max_clamp=None,
                log_prob_min_clamp=None,
            ),
        )
        loss, metrics = distillation_ppo_loss(config, distillation, model_output={"log_probs": student}, data=data)
    assert torch.isfinite(loss)
    loss.backward()
    assert torch.isfinite(student.grad).all()
    return loss.detach(), student.grad.detach(), advantages, metrics


def test_native_hybrid_gradient_is_rl_plus_weighted_opd():
    pure_loss, pure_grad, advantages, _ = _run(mode="opd")
    rl_loss, rl_grad, _, _ = _run(mode="rl")
    hybrid_loss, hybrid_grad, _, metrics = _run(mode="hybrid", coefficient=0.3)

    assert advantages[0, 0] > 0 and advantages[1, 0] < 0
    assert advantages[:, 1].eq(0).all()
    assert pure_grad.abs().sum() > 0 and rl_grad.abs().sum() > 0
    torch.testing.assert_close(hybrid_loss, rl_loss + 0.3 * pure_loss)
    torch.testing.assert_close(hybrid_grad, rl_grad + 0.3 * pure_grad)
    assert "distillation/loss" in metrics and "actor/pg_loss" in metrics
    # Teacher prefers sampled tokens (log p_teacher - log p_student = +0.2),
    # so gradient descent raises both sequences' action probabilities.
    assert pure_grad[[1, 3, 6, 8]].lt(0).all()
    # Harbor success advantage raises actions for the winner and lowers the loser.
    assert rl_grad[[1, 3]].lt(0).all() and rl_grad[[6, 8]].gt(0).all()


def test_pure_opd_ignores_task_reward_but_hybrid_responds_to_it():
    pure_loss, pure_grad, _, _ = _run(mode="opd")
    flipped_loss, flipped_grad, _, _ = _run(mode="opd", reward_reversed=True)
    torch.testing.assert_close(pure_loss, flipped_loss)
    torch.testing.assert_close(pure_grad, flipped_grad)
    _, hybrid_grad, _, _ = _run(mode="hybrid")
    _, hybrid_flipped, _, _ = _run(mode="hybrid", reward_reversed=True)
    assert not torch.allclose(hybrid_grad, hybrid_flipped)


@pytest.mark.parametrize("mode", ["opd", "rl", "hybrid"])
def test_tool_teacher_scores_never_contribute_to_action_gradient(mode):
    original_loss, original_grad, _, _ = _run(mode=mode, tool_teacher_delta=0.2)
    changed_loss, changed_grad, _, _ = _run(mode=mode, tool_teacher_delta=-30.0)
    torch.testing.assert_close(original_loss, changed_loss)
    torch.testing.assert_close(original_grad, changed_grad)
    assert original_grad[[0, 2, 4, 5, 7, 9]].eq(0).all()


def test_teacher_disagreement_reverses_opd_gradient():
    _, positive_grad, _, _ = _run(mode="opd", teacher_delta=0.2)
    _, negative_grad, _, _ = _run(mode="opd", teacher_delta=-0.2)
    assert positive_grad[[1, 3, 6, 8]].lt(0).all()
    assert negative_grad[[1, 3, 6, 8]].gt(0).all()


@pytest.mark.parametrize("chunked", [False, True])
def test_native_fsdp_topk_accepts_manager_int32_ids_and_backpropagates(chunked):
    from verl.trainer.distillation.fsdp.losses import compute_forward_kl_topk

    teacher_ids = tu.nested_tensor_from_tensor_list(
        [torch.tensor([[0, 2], [1, 3], [2, 0]], dtype=torch.int32)], ragged_idx=1
    )
    teacher_logprobs = tu.nested_tensor_from_tensor_list([torch.full((3, 2), -1.0)], ragged_idx=1)
    config = DistillationConfig(
        enabled=True,
        n_gpus_per_node=2,
        nnodes=1,
        teacher_models={
            "teacher_model": DistillationTeacherModelConfig(
                model_path="synthetic-teacher", inference=RolloutConfig(name="vllm")
            )
        },
        distillation_loss=DistillationLossConfig(
            loss_mode="forward_kl_topk",
            use_policy_gradient=False,
            topk=2,
            use_chunked_topk=chunked,
            chunked_topk_chunk_size=2,
        ),
    )
    logits = torch.zeros((1, 3, 4), requires_grad=True)
    outputs = compute_forward_kl_topk(logits, teacher_logprobs, teacher_ids, config, "thd")
    loss = outputs["distillation_losses"].sum()
    assert torch.isfinite(loss)
    loss.backward()
    assert torch.isfinite(logits.grad).all()
    assert logits.grad.abs().sum() > 0
