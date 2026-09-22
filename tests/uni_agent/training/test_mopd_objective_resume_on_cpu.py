"""CPU native-loss/optimizer/cursor replay; no teacher service or GPU claims."""

import pytest
import torch
from torchdata.stateful_dataloader import StatefulDataLoader

from tests.uni_agent.examples.test_harbor_mopd_resume import assert_state_equal
from tests.uni_agent.training.test_mopd_native_on_cpu import configs, data_batch, topk_data
from verl.trainer.distillation.losses import distillation_ppo_loss
from verl.utils import tensordict_utils as tu
from verl.utils.torch_functional import get_constant_schedule_with_warmup


def components():
    model = torch.nn.Linear(3, 80, dtype=torch.float64)
    with torch.no_grad():
        model.weight.copy_(torch.linspace(-0.4, 0.4, 240).reshape(80, 3))
        model.bias.copy_(torch.linspace(-0.1, 0.1, 80))
    optim = torch.optim.AdamW(model.parameters(), lr=1e-3)
    schedule = get_constant_schedule_with_warmup(optim, num_warmup_steps=0)
    loader = StatefulDataLoader([0, 1, 2, 3], batch_size=2, shuffle=False, num_workers=0)
    return model, optim, schedule, loader


def update(mode, objects, ids):
    model, optim, schedule, _ = objects
    actor, distill = configs(mode)
    data, _ = topk_data() if mode == "mopd_top64_reverse" else (data_batch(), None)
    # Distinct task batches change features; fixed teacher/sampling evidence is
    # independent of restored/current student weights.
    features = torch.arange(36, dtype=torch.float64).reshape(12, 3) / 36 + float(ids[0]) / 10
    logits = model(features)
    optim.zero_grad(set_to_none=True)
    if mode == "mopd_top64_reverse":
        output = distillation_ppo_loss(actor, distill, data=data, student_logits=logits[None])
        output = {key: value.squeeze(0) for key, value in output.items()}
    else:
        logp = logits.log_softmax(-1)[:, 7]
        q = torch.full((12, 1), -3.5, dtype=torch.float64)
        data["teacher_logprobs"] = tu.nested_tensor_from_tensor_list([q[:5], q[5:]], ragged_idx=1)
        with torch.no_grad():
            frozen_sampling = components()[0](features).log_softmax(-1)[:, 7]
        data["rollout_log_probs"] = tu.nested_tensor_from_tensor_list([frozen_sampling[1:4], frozen_sampling[7:11]])
        output = {"log_probs": logp}
    loss, _ = distillation_ppo_loss(actor, distill, output, data)
    loss.backward()
    assert sum(parameter.grad.abs().sum().item() for parameter in model.parameters()) > 0
    optim.step()
    schedule.step()
    return loss.detach()


@pytest.mark.parametrize("mode", ["mopd_pg_sequence", "mopd_top64_reverse", "mopd_flash_orm"])
def test_native_objective_two_updates_equal_disk_restore(mode, tmp_path):
    continuous = components()
    expected_losses = [update(mode, continuous, ids) for ids in continuous[3]]
    partial = components()
    first = next(iter(partial[3]))
    first_loss = update(mode, partial, first)
    path = tmp_path / "state.pt"
    torch.save(
        {
            "model": partial[0].state_dict(),
            "optim": partial[1].state_dict(),
            "schedule": partial[2].state_dict(),
            "cursor": partial[3].state_dict(),
            "mode": mode,
        },
        path,
    )
    state = torch.load(path, weights_only=False)
    assert state["mode"] == mode
    resumed = components()
    for item, key in zip(resumed, ("model", "optim", "schedule", "cursor"), strict=True):
        item.load_state_dict(state[key])
    remaining = list(resumed[3])
    assert len(remaining) == 1 and remaining[0].tolist() == [2, 3]
    assert first.tolist() == [0, 1]
    second_loss = update(mode, resumed, remaining[0])
    assert_state_equal([first_loss, second_loss], expected_losses)
    for actual, expected in zip(resumed[:3], continuous[:3], strict=True):
        assert_state_equal(actual.state_dict(), expected.state_dict())
