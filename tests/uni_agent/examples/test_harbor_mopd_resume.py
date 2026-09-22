"""Real CPU component checkpoint replay test; not a Harbor/GPU acceptance run.

Use VERL's scheduler factory and the same stateful sequential dataloader pattern
as its sync trainer. A tiny regression loss isolates optimizer/cursor restoration
from model-server, teacher, sandbox and distributed-training dependencies.
"""

import torch
from torch.utils.data import SequentialSampler
from torchdata.stateful_dataloader import StatefulDataLoader

from verl.utils.torch_functional import get_constant_schedule_with_warmup


def components():
    rows = [
        {"task_id": domain, "features": torch.tensor(values, dtype=torch.float64), "target": target}
        for domain, values, target in [
            ("swe-1", [1.0, 0.5], 0.2),
            ("terminal-1", [0.1, 2.0], -0.3),
            ("swe-2", [2.0, -1.0], 0.9),
            ("terminal-2", [-0.5, 1.0], 0.6),
        ]
    ]
    loader = StatefulDataLoader(
        rows,
        sampler=SequentialSampler(rows),
        batch_size=2,
        drop_last=True,
        num_workers=0,
    )
    model = torch.nn.Linear(2, 1, dtype=torch.float64)
    with torch.no_grad():
        model.weight.copy_(torch.tensor([[0.2, -0.4]], dtype=torch.float64))
        model.bias.fill_(0.05)
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=0.01)
    scheduler = get_constant_schedule_with_warmup(optimizer, num_warmup_steps=0)
    return model, optimizer, scheduler, loader


def update(model, optimizer, scheduler, batch):
    optimizer.zero_grad(set_to_none=True)
    prediction = model(batch["features"]).squeeze(-1)
    loss = (prediction - batch["target"]).square().mean()
    loss.backward()
    optimizer.step()
    scheduler.step()
    return loss.detach()


def assert_state_equal(actual, expected):
    if isinstance(expected, torch.Tensor):
        torch.testing.assert_close(actual, expected, rtol=0, atol=0)
    elif isinstance(expected, dict):
        assert actual.keys() == expected.keys()
        for key in expected:
            assert_state_equal(actual[key], expected[key])
    elif isinstance(expected, list | tuple):
        assert len(actual) == len(expected)
        for left, right in zip(actual, expected, strict=True):
            assert_state_equal(left, right)
    else:
        assert actual == expected


def test_two_updates_equal_save_restore_and_no_task_replay(tmp_path):
    continuous, continuous_optim, continuous_lr, continuous_data = components()
    baseline_ids, baseline_losses = [], []
    for batch in continuous_data:
        baseline_ids.extend(batch["task_id"])
        baseline_losses.append(update(continuous, continuous_optim, continuous_lr, batch))
    assert baseline_ids == ["swe-1", "terminal-1", "swe-2", "terminal-2"]

    first, first_optim, first_lr, first_data = components()
    first_batch = next(iter(first_data))
    first_loss = update(first, first_optim, first_lr, first_batch)
    # Use actual disk serialization, after the first update has consumed its
    # batch, just as the sync trainer saves model/optimizer/extra and data.pt.
    torch.save(first.state_dict(), tmp_path / "model.pt")
    torch.save(first_optim.state_dict(), tmp_path / "optim.pt")
    torch.save({"lr_scheduler": first_lr.state_dict()}, tmp_path / "extra_state.pt")
    torch.save(first_data.state_dict(), tmp_path / "data.pt")

    resumed, resumed_optim, resumed_lr, resumed_data = components()
    resumed.load_state_dict(torch.load(tmp_path / "model.pt", weights_only=True))
    resumed_optim.load_state_dict(torch.load(tmp_path / "optim.pt", weights_only=True))
    resumed_lr.load_state_dict(torch.load(tmp_path / "extra_state.pt", weights_only=True)["lr_scheduler"])
    resumed_data.load_state_dict(torch.load(tmp_path / "data.pt", weights_only=False))

    remaining_batches = list(resumed_data)
    assert len(remaining_batches) == 1
    second_batch = remaining_batches[0]
    assert second_batch["task_id"] == ["swe-2", "terminal-2"]
    assert set(first_batch["task_id"]).isdisjoint(second_batch["task_id"])
    assert first_batch["task_id"] + second_batch["task_id"] == baseline_ids
    second_loss = update(resumed, resumed_optim, resumed_lr, second_batch)

    assert_state_equal([first_loss, second_loss], baseline_losses)
    assert_state_equal(resumed.state_dict(), continuous.state_dict())
    assert_state_equal(resumed_optim.state_dict(), continuous_optim.state_dict())
    assert_state_equal(resumed_lr.state_dict(), continuous_lr.state_dict())
    assert resumed_lr.last_epoch == 2
    assert resumed_lr.get_last_lr() == [1e-3]
    assert all(state["step"].item() == 2 for state in resumed_optim.state.values())
