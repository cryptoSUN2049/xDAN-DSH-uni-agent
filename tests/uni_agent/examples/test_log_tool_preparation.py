"""Preparation must verify the actual runtime before producing deployable data."""

import json
import subprocess
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from examples.dsh.capability_tasks.log_tool import prepare_training as preparation
from examples.dsh.verifier import _sha256_bytes

ROOT = Path(__file__).resolve().parents[3]


def test_prepare_checks_runtime_and_separates_public_splits(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    runtime.write_bytes(b"test runtime executable")
    installed = dict(path=str(runtime), sdk="0.1.3a2", runtime="0.1.3a2")
    monkeypatch.setattr(
        preparation.subprocess,
        "run",
        lambda *a, **kw: subprocess.CompletedProcess([], 0, stdout=json.dumps(installed)),
    )
    target = tmp_path / "run"
    with pytest.raises(RuntimeError, match="runtime hash"):
        preparation.prepare(ROOT, target, "/test/python", "sha256:" + "a" * 64)
    assert not target.exists()
    manifest = preparation.prepare(ROOT, target, "/test/python", _sha256_bytes(runtime.read_bytes()))
    assert manifest["counts"] == {"train": 4, "validation": 2}
    assert manifest["environment"]["VAL_ONLY"] == "True"
    assert manifest["environment"]["LOW_VRAM"] == "1"
    assert pq.read_table(target / "train.parquet").num_rows == 4
    assert pq.read_table(target / "validation.parquet").num_rows == 2
    assert target.stat().st_mode & 0o777 == 0o700
    assert (target / "task.yaml").stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError, match="must be new"):
        preparation.prepare(ROOT, target, "/test/python", _sha256_bytes(runtime.read_bytes()))
