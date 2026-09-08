import pytest
import torch

from deployment.checks.checkpoint_delta import compare_states


def test_lora_update_requires_finite_change_and_frozen_base():
    before = {"layer.weight": torch.ones(2), "layer.lora_B.weight": torch.zeros(2)}
    after = {k: v.clone() for k, v in before.items()}
    assert not compare_states(before, after)["passed"]
    after["layer.lora_B.weight"][0] = 0.01
    assert compare_states(before, after)["passed"]
    after["layer.weight"][0] = 2
    assert not compare_states(before, after)["passed"]
    after["layer.lora_B.weight"][0] = float("nan")
    assert not compare_states(before, after)["passed"]


def test_checkpoint_mismatch_and_missing_adapter_rejected():
    with pytest.raises(ValueError, match="keys"):
        compare_states({"x": torch.zeros(1)}, {})
    with pytest.raises(ValueError, match="shape"):
        compare_states({"x": torch.zeros(1)}, {"x": torch.zeros(2)})
    assert not compare_states({"x": torch.zeros(1)}, {"x": torch.zeros(1)})["passed"]
