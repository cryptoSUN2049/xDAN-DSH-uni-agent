import importlib.util
import json
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.cpu, pytest.mark.level0]
MODULE = Path(__file__).resolve().parents[3] / "docs/verl-uni-agent-harbor-opd-rl/mimo_gpu_timeline.py"
spec = importlib.util.spec_from_file_location("timeline", MODULE)
timeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(timeline)


@pytest.mark.parametrize("seconds", [1, 21600, 25200])
def test_absolute_seven_hour_boundary(tmp_path, monkeypatch, seconds):
    status = tmp_path / "status.json"
    status.write_text(json.dumps({"run_id": "r18", "status": "exited"}))
    output = tmp_path / "timeline.jsonl"
    monkeypatch.setattr(timeline.time, "time", lambda: 1000)
    monkeypatch.setattr(timeline, "query", lambda fields, kind: [])
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "timeline",
            "--run-id",
            "r18",
            "--status",
            str(status),
            "--output",
            str(output),
            "--deadline",
            str(1000 + seconds),
        ],
    )
    timeline.main()
    row = json.loads(output.read_text())
    assert row["operator_status"] == "exited"
    assert row["gpus"] == row["compute_processes"] == []


@pytest.mark.parametrize("seconds", [0, -1, 25201, float("inf"), float("nan")])
def test_reject_outside_window_before_creating_output(tmp_path, monkeypatch, seconds):
    output = tmp_path / "timeline.jsonl"
    monkeypatch.setattr(timeline.time, "time", lambda: 1000)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "timeline",
            "--run-id",
            "r18",
            "--status",
            str(tmp_path / "status"),
            "--output",
            str(output),
            "--deadline",
            str(1000 + seconds),
        ],
    )
    with pytest.raises(ValueError, match="deadline"):
        timeline.main()
    assert not output.exists()


def test_mismatched_run_is_recorded_and_stops(tmp_path, monkeypatch):
    status = tmp_path / "status.json"
    status.write_text(json.dumps({"run_id": "another-run", "status": "running"}))
    output = tmp_path / "timeline.jsonl"
    monkeypatch.setattr(timeline.time, "time", lambda: 1000)
    monkeypatch.setattr(
        sys,
        "argv",
        ["timeline", "--run-id", "r18", "--status", str(status), "--output", str(output), "--deadline", "26200"],
    )
    timeline.main()
    assert json.loads(output.read_text())["error_type"] == "ValueError"


def test_process_names_and_query_failure_preserve_terminal_snapshot(tmp_path, monkeypatch):
    import os

    status = tmp_path / "status.json"
    status.write_text(json.dumps({"run_id": "r18", "status": "exited"}))
    output = tmp_path / "timeline.jsonl"
    monkeypatch.setattr(timeline.time, "time", lambda: 1000)
    monkeypatch.setattr(
        timeline, "query", lambda fields, kind: [f"{os.getpid()}, GPU-fixture, 0"] if kind == "compute-apps" else []
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["timeline", "--run-id", "r18", "--status", str(status), "--output", str(output), "--deadline", "26200"],
    )
    timeline.main()
    assert json.loads(output.read_text())["process_names"][str(os.getpid())]
    monkeypatch.setattr(timeline, "query", lambda *args: (_ for _ in ()).throw(OSError("GPU query failed")))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "timeline",
            "--run-id",
            "r18",
            "--status",
            str(status),
            "--output",
            str(tmp_path / "failed.jsonl"),
            "--deadline",
            "26200",
        ],
    )
    timeline.main()
    row = json.loads((tmp_path / "failed.jsonl").read_text())
    assert row["operator_status"] == "exited" and row["error_type"] == "OSError"


def test_query_is_read_only_and_filters_blank_lines(monkeypatch):
    from types import SimpleNamespace

    def run(command, **kwargs):
        assert command == ["nvidia-smi", "--query-gpu=index", "--format=csv,noheader,nounits"]
        assert kwargs == {"capture_output": True, "text": True, "timeout": 10, "check": True}
        return SimpleNamespace(stdout=" 0 \n\n1\n")

    monkeypatch.setattr(timeline.subprocess, "run", run)
    assert timeline.query("index", "gpu") == ["0", "1"]
