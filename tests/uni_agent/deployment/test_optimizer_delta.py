import json
import subprocess
import sys

import pytest
import torch

from deployment.checks.optimizer_delta import compare_optimizers


def checkpoint(step):
    return {
        "state": {
            0: {},
            2: {
                "step": torch.tensor(float(step)),
                "exp_avg": torch.tensor([0.1, 0.0], dtype=torch.bfloat16),
                "exp_avg_sq": torch.tensor([0.01, 0.0], dtype=torch.bfloat16),
            },
            3: {
                "step": torch.tensor(float(step)),
                "exp_avg": torch.zeros(2, dtype=torch.bfloat16),
                "exp_avg_sq": torch.zeros(2, dtype=torch.bfloat16),
            },
        },
        "param_groups": [{"params": [0, 2, 3], "lr": 0.001}],
    }


def test_real_layout_preserves_empty_state_and_allows_some_zero_moments():
    result = compare_optimizers(checkpoint(2), checkpoint(4))
    assert result["passed"]
    assert result["empty_state_count"] == 1
    assert result["active_state_count"] == 2
    assert result["before"]["steps"] == [2]
    assert result["after"]["steps"] == [4]
    assert result["after"]["nonzero_moment_tensors"] == 2


@pytest.mark.parametrize(
    "failure",
    [
        "stalled",
        "backwards",
        "nan_step",
        "fractional_step",
        "nan_moment",
        "all_zero",
        "negative_variance",
        "shape",
        "dtype",
        "empty",
        "group_order",
        "unknown_field",
    ],
)
def test_rejects_invalid_progress_or_checkpoint(failure):
    before, after = checkpoint(2), checkpoint(4)
    state = after["state"][2]
    if failure in ("stalled", "backwards", "nan_step", "fractional_step"):
        state["step"] = torch.tensor(
            {"stalled": 2.0, "backwards": 1.0, "nan_step": float("nan"), "fractional_step": 3.5}[failure]
        )
    elif failure == "nan_moment":
        state["exp_avg"][0] = float("nan")
    elif failure == "all_zero":
        state["exp_avg"].zero_()
        state["exp_avg_sq"].zero_()
    elif failure == "negative_variance":
        state["exp_avg_sq"][0] = -1
    elif failure == "shape":
        state["exp_avg"] = torch.ones(3, dtype=torch.bfloat16)
    elif failure == "dtype":
        state["exp_avg"] = state["exp_avg"].float()
    elif failure == "empty":
        after["state"][2] = {}
    elif failure == "group_order":
        after["param_groups"][0]["params"].reverse()
    else:
        state["unexpected"] = torch.tensor(1)
    assert not compare_optimizers(before, after)["passed"]


def test_cli_writes_fail_closed_report_without_overwrite(tmp_path):
    before, after = tmp_path / "before.pt", tmp_path / "after.pt"
    torch.save(checkpoint(2), before)
    torch.save(checkpoint(2), after)
    output = tmp_path / "report.json"
    command = [
        sys.executable,
        "-m",
        "deployment.checks.optimizer_delta",
        str(before),
        str(after),
        "--output",
        str(output),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=20)
    assert result.returncode == 1
    assert not json.loads(output.read_bytes())["passed"]
    original = output.read_bytes()
    assert subprocess.run(command, capture_output=True, text=True, timeout=20).returncode != 0
    assert output.read_bytes() == original


@pytest.mark.parametrize("corrupt", [False, True])
def test_cli_success_and_corruption_fail_closed(tmp_path, corrupt):
    before, after = tmp_path / "before.pt", tmp_path / "after.pt"
    torch.save(checkpoint(2), before)
    if corrupt:
        after.write_bytes(b"not-a-checkpoint")
    else:
        torch.save(checkpoint(4), after)
    output = tmp_path / "report.json"
    result = subprocess.run(
        [sys.executable, "-m", "deployment.checks.optimizer_delta", str(before), str(after), "--output", str(output)],
        capture_output=True,
        text=True,
        timeout=20,
    )
    report = json.loads(output.read_bytes())
    assert result.returncode == (1 if corrupt else 0)
    assert report["passed"] is (not corrupt)
    if not corrupt:
        assert len(report["files"]["before"]["sha256"]) == 64
