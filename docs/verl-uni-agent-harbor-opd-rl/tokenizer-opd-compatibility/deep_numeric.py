"""Exercise deployed VERL loss with independent value/gradient controls; CPU only."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import torch

from verl.trainer.distillation.losses import distillation_loss
from verl.workers.config import DistillationLossConfig
from verl.workers.utils.padding import no_padding_2_padding


def main():
    torch.set_default_dtype(torch.float64)
    mask = torch.tensor([[1, 1, 1], [1, 1, 0]], dtype=torch.bool)
    data = {
        "prompts": torch.tensor([[11, 12], [0, 21]]),
        "responses": torch.tensor([[31, 32, 99], [41, 99, 0]]),
        "attention_mask": torch.tensor([[1, 1, 1, 1, 1], [0, 1, 1, 1, 0]]),
        "response_mask": mask,
        "dp_size": 1,
        "batch_num_tokens": 5,
        "global_batch_size": 2,
    }
    # Packed positions: prompt1 prompt2 r1 r2 eos | prompt r1 eos.
    student = torch.tensor([-7.0, -2.0, -4.0, -0.1, -8.0, -25.0, -0.4, -9.0], requires_grad=True)
    teacher = torch.tensor([-3.0, -1.0, -6.0, -0.2, -6.0, -1.0, -0.3, -2.0], requires_grad=True)
    expected_positions = torch.tensor([[1, 2, 3], [5, 6, 0]])
    sliced = no_padding_2_padding(torch.arange(8.0), data)
    assert torch.equal(sliced, expected_positions)
    data["teacher_logprobs"] = teacher[:, None]
    actor = SimpleNamespace(loss_agg_mode="token-mean", global_batch_info={}, loss_scale_factor=None)
    config = SimpleNamespace(
        enabled=True,
        distillation_loss=DistillationLossConfig(loss_mode="k1", use_policy_gradient=True, use_task_rewards=False),
    )
    controls = []
    for offset in [0.0, 0.5, -0.5, 2.0]:
        current = no_padding_2_padding(student, data)
        data["old_log_probs"] = current.detach() - offset
        loss, _ = distillation_loss(actor, config, {"log_probs": student}, data)
        actual_grad = torch.autograd.grad(loss, student, retain_graph=True)[0]
        reference_s = student.detach().clone().requires_grad_(True)
        # Independent explicit indexing, no VERL padding/aggregation utilities.
        q = torch.stack([reference_s[[1, 2, 3]], torch.stack([reference_s[5], reference_s[6], reference_s[0] * 0])])
        p = torch.stack([teacher.detach()[[1, 2, 3]], torch.tensor([-1.0, -0.3, 0.0])])
        advantage = -(q.detach() - p).clamp(-10, 10)
        ratio = (q - data["old_log_probs"]).clamp(-20, 20).exp()
        unclipped = -advantage * ratio
        clipped = -advantage * ratio.clamp(0.8, 1.2)
        upper = torch.maximum(unclipped, clipped)
        objective = torch.where(advantage < 0, torch.minimum(-3 * advantage, upper), upper)
        reference_loss = objective[mask].sum() / 5
        reference_grad = torch.autograd.grad(reference_loss, reference_s)[0]
        value_error = abs(float(loss.detach() - reference_loss.detach()))
        grad_error = float((actual_grad - reference_grad).abs().max())
        assert value_error < 1e-8 and grad_error < 1e-8
        assert torch.equal(actual_grad[[0, 4, 7]], torch.zeros(3))
        assert torch.autograd.grad(loss, teacher, allow_unused=True, retain_graph=True)[0] is None
        if offset == 0:
            assert actual_grad[1] < 0 and actual_grad[2] > 0
        controls.append({"log_ratio": offset, "loss_error": value_error, "gradient_error": grad_error})
    data["old_log_probs"] = no_padding_2_padding(student, data).detach()
    first, _ = distillation_loss(actor, config, {"log_probs": student}, data)
    config.distillation_loss = DistillationLossConfig(
        loss_mode="k1", use_policy_gradient=True, use_task_rewards=False, log_prob_min_clamp=-0.01
    )
    second, _ = distillation_loss(actor, config, {"log_probs": student}, data)
    assert torch.equal(first, second)
    result = {
        "status": "passed",
        "scope": "synthetic boundary controls invoking actual deployed VERL loss; not historical tensors",
        "controls": controls,
        "response_first_last_eos_coordinate_check": True,
        "ignored_positions_zero_gradient": True,
        "teacher_detached": True,
        "k1_log_prob_min_clamp_not_applied": True,
        "update_direction_check": "teacher-preferred sampled token gradient negative; opposite preference positive",
    }
    Path(sys.argv[1]).write_text(json.dumps(result, indent=2))
    print(json.dumps(result))


if __name__ == "__main__":
    main()
