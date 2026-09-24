"""CPU integration fixture; not evidence of real model training."""

import os
from pathlib import Path
from types import SimpleNamespace

import torch
from replay import replay
from tensordict import TensorDict

from verl.trainer.distillation.losses import distillation_loss
from verl.workers.config import DistillationLossConfig
from verl.workers.utils.padding import no_padding_2_padding


def main():
    destination = Path(os.environ["OPD_LIVE_AUDIT_DIR"])
    for as_nested in (False, True):
        mask = torch.tensor([[1, 1, 1], [1, 1, 0]], dtype=torch.bool)
        data = {
            "prompts": torch.tensor([[11, 12], [0, 21]]),
            "responses": torch.tensor([[31, 32, 99], [41, 99, 0]]),
            "attention_mask": torch.tensor([[1, 1, 1, 1, 1], [0, 1, 1, 1, 0]]),
            "response_mask": mask,
            "dp_size": 1,
            "batch_num_tokens": 5,
            "global_batch_size": 2,
            "temperature": 0.8,
        }
        values = torch.tensor([-7.0, -2.0, -4.0, -0.1, -8.0, -25.0, -0.4, -9.0])
        if as_nested:
            student = torch.nested.nested_tensor_from_jagged(values, offsets=torch.tensor([0, 5, 8]))
            student.requires_grad_(True)
        else:
            student = values.requires_grad_(True)
        data["teacher_logprobs"] = torch.tensor([-3.0, -1.0, -6.0, -0.2, -6.0, -1.0, -0.3, -2.0])[:, None]
        data["teacher_ids"] = torch.tensor([0, 31, 32, 99, 0, 41, 99, 0])[:, None]
        actor = SimpleNamespace(loss_agg_mode="token-mean", global_batch_info={}, loss_scale_factor=None)
        config = SimpleNamespace(
            distillation_loss=DistillationLossConfig(loss_mode="k1", use_policy_gradient=True, use_task_rewards=False)
        )
        data["old_log_probs"] = no_padding_2_padding(student, data).detach()
        # Real worker API supplies NonTensorData scalars in a TensorDict.
        data = TensorDict(data, batch_size=[])
        loss, _ = distillation_loss(actor, config, {"log_probs": student}, data)
        loss.backward()
        assert student.grad is not None, "Audit consumed the original backward graph"
    files = sorted(destination.glob("micro-*.pt"))
    assert len(files) == 2
    for path in files:
        result = replay(path)
        assert result["passed"], result
    print("PASS: dense/nested native loss hook, independent replay, subsequent backward")


if __name__ == "__main__":
    main()
