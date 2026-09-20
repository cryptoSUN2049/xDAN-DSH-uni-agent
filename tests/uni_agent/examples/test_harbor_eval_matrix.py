import importlib.util
import json
import zipfile
from pathlib import Path

MODULE = Path(__file__).resolve().parents[3] / "examples/harbor_opd_rl/eval_checkpoint_matrix.py"
spec = importlib.util.spec_from_file_location("matrix", MODULE)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def test_rejects_truncated_checkpoint(tmp_path):
    p = tmp_path / "model.pt"
    p.write_bytes(b"PK broken")
    assert m.archive_error(p)


def test_accepts_archive_directory(tmp_path):
    p = tmp_path / "model.pt"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("archive/data.pkl", b"weights")
    assert m.archive_error(p) is None


def test_requires_success_receipt_and_complete_samples(tmp_path):
    (tmp_path / "summary.json").write_text(json.dumps({"per_task": {"a": [1, 0, 1, 0]}}))
    assert not m.is_complete(tmp_path, ["a"], 4)
    (tmp_path / "validation.json").write_text(json.dumps({"status": "complete"}))
    assert m.is_complete(tmp_path, ["a"], 4)
    assert not m.is_complete(tmp_path, ["a", "b"], 4)
    assert not m.is_complete(tmp_path, ["a"], 2)


def test_busy_gpu_never_admitted():
    assert not m.gpu_available("8123\n")
    assert m.gpu_available("3\n")
    assert not m.gpu_available("")


def test_queue_stops_on_zero_sample_failure(tmp_path, monkeypatch):
    import subprocess
    import sys

    import pytest

    base = tmp_path / "base"
    base.mkdir()
    tasks = {f"t{i}": [0, 1, 0, 1] for i in range(78)}
    (base / "summary.json").write_text(json.dumps({"per_task": tasks}))
    ck = tmp_path / "checkpoint/actor"
    ck.mkdir(parents=True)
    with zipfile.ZipFile(ck / "model_world_size_1_rank_0.pt", "w") as archive:
        archive.writestr("archive/data.pkl", b"weights")
    cfg = {
        "output": str(tmp_path / "out"),
        "base": str(base),
        "gpu": 0,
        "env": {},
        "python": sys.executable,
        "versions": [
            {"label": label, "checkpoint": str(ck.parent), "run": str(tmp_path)} for label in ["first", "second"]
        ],
    }
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(cfg))
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if command[0] == "nvidia-smi":
            return subprocess.CompletedProcess(command, 0, stdout="3\n")
        dest = Path(kwargs["env"]["EVAL_ROOT"])
        dest.mkdir()
        (dest / "summary.json").write_text(json.dumps({"samples": 0}))
        return subprocess.CompletedProcess(command, 1)

    monkeypatch.setattr(m.subprocess, "run", run)
    monkeypatch.setattr(sys, "argv", ["queue", str(manifest)])
    with pytest.raises(SystemExit, match="Zero-sample"):
        m.main()
    assert len(calls) == 2
    assert not (tmp_path / "out/second-attempt1").exists()
    assert json.loads((tmp_path / "out/status.json").read_text())[0]["status"] == "failed_or_incomplete"
