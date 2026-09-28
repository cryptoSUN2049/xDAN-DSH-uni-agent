"""Guard reproducible SFT runtime pins and CPU-only acceptance semantics."""

import ast
import subprocess
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LANES = ROOT / "deployment/versions/uv-lanes"
PREFIX = "performance-9b-sft-py312-cu128"
BOOTSTRAP = ROOT / "deployment/bootstrap/setup-performance-9b-sft-cu128.sh"


def test_constraints_preserve_every_noneditable_freeze_entry():
    original = (LANES / f"{PREFIX}.freeze.txt").read_text().splitlines()
    actual = (LANES / f"{PREFIX}.constraints.txt").read_text().splitlines()
    assert [line for line in actual if line and not line.startswith("#")] == [
        line for line in original if not line.startswith("-e ")
    ]
    assert any("transferqueue @ git+" in line for line in actual)
    assert sum(line.startswith("-e ") for line in original) == 2


@pytest.mark.parametrize("minimum,devices,succeeds", [(0, 0, True), (2, 2, True), (2, 1, False)])
def test_cpu_only_acceptance_never_synchronizes_cuda(minimum, devices, succeeds):
    # Execute the actual GPU acceptance branch with an instrumented CUDA object.
    source = BOOTSTRAP.read_text().split("<<'PY'\n", 1)[1].split("\nPY", 1)[0]
    tree = ast.parse(source)
    conditional = next(node for node in tree.body if isinstance(node, ast.If) and ast.unparse(node.test) == "minimum")
    calls = []
    cuda = types.SimpleNamespace(device_count=lambda: devices, synchronize=lambda: calls.append(1))
    code = compile(ast.Module(body=[conditional], type_ignores=[]), str(BOOTSTRAP), "exec")
    context = {"minimum": minimum, "torch": types.SimpleNamespace(cuda=cuda)}
    if succeeds:
        exec(code, context)
        assert calls == ([1] if minimum else [])
    else:
        with pytest.raises(AssertionError):
            exec(code, context)
        assert not calls


def test_invalid_gpu_count_fails_before_environment_mutation():
    result = subprocess.run(
        ["bash", str(BOOTSTRAP)],
        env={"PATH": "/usr/bin:/bin", "MIN_GPU_COUNT": "-1"},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "nonnegative integer" in result.stderr
