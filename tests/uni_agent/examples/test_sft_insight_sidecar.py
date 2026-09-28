import importlib.util
import json
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[3] / "examples/performance_9b/sft_insight_sidecar.py"
spec = importlib.util.spec_from_file_location("sidecar", SOURCE)
sidecar = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sidecar)


def row(step=1, **data):
    return json.dumps({"step": step, "data": data or {"train/loss": 1.2}}).encode() + b"\n"


@pytest.fixture
def files(tmp_path):
    return tmp_path / "metrics.jsonl", tmp_path / "cursor.json"


def test_half_line_and_same_step(files):
    metrics, state = files
    first, second = row(), row(**{"val/loss": 0.4})
    metrics.write_bytes(first + second[:-2])
    sent = []
    cursor = sidecar.Cursor(*files)
    assert cursor.drain(sent.append) == 1
    assert cursor.value["offset"] == len(first)
    with metrics.open("ab") as handle:
        handle.write(second[-2:])
    assert cursor.drain(sent.append) == 1
    assert sent[-1]["train/loss"] == 1.2
    assert sent[-1]["val/loss"] == 0.4
    assert sidecar.Cursor(*files).drain(sent.append) == 0
    cursor.assert_complete()


@pytest.mark.parametrize("mutation", ["truncate", "prefix", "replace", "remove"])
def test_reject_source_mutation(files, mutation):
    metrics, state = files
    metrics.write_bytes(row())
    cursor = sidecar.Cursor(*files)
    cursor.drain(lambda value: None)
    if mutation == "truncate":
        metrics.write_bytes(b"")
    elif mutation == "prefix":
        metrics.write_bytes(row().replace(b"1.2", b"9.2"))
    elif mutation == "replace":
        other = metrics.with_suffix(".new")
        other.write_bytes(row())
        other.replace(metrics)
    else:
        metrics.unlink()
    with pytest.raises(ValueError):
        sidecar.Cursor(*files).drain(lambda value: None)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, "1"])
def test_invalid_metric(files, value):
    metrics, state = files
    metrics.write_bytes(row(**{"train/loss": value}))
    with pytest.raises(ValueError):
        sidecar.Cursor(*files).drain(lambda value: None)
    assert not state.exists()


@pytest.mark.parametrize("step", [True, -1, 1.2, "1", None])
def test_invalid_step(step):
    with pytest.raises(ValueError):
        sidecar.parse_record(row(step=step))


def test_failed_send_retries_without_cursor_advance(files):
    metrics, state = files
    metrics.write_bytes(row())
    cursor = sidecar.Cursor(*files)

    def fail(value):
        raise ConnectionError("transport unavailable")

    with pytest.raises(ConnectionError):
        cursor.drain(fail)
    assert not state.exists()
    assert cursor.value["offset"] == 0
    assert cursor.drain(lambda value: None) == 1


def test_allowlist_and_step_regression(files):
    metrics, state = files
    metrics.write_bytes(row(step=3, **{"secret_prompt": "do not export"}) + row(step=2))
    sent = []
    with pytest.raises(ValueError, match="regressed"):
        sidecar.Cursor(*files).drain(sent.append)
    assert "secret_prompt" not in sent[0]
    assert json.loads(state.read_text())["records"] == 1


def test_missing_and_partial_terminal(files):
    metrics, state = files
    cursor = sidecar.Cursor(*files)
    assert cursor.drain(lambda value: None) == 0
    with pytest.raises(ValueError, match="without metrics"):
        cursor.assert_complete()
    metrics.write_bytes(row() + b"{")
    cursor.drain(lambda value: None)
    with pytest.raises(ValueError, match="incomplete"):
        cursor.assert_complete()


def test_mismatched_cursor(files):
    metrics, state = files
    state.write_text('{"version":2}')
    with pytest.raises(ValueError):
        sidecar.Cursor(*files)


def test_resume_restores_latest_and_holds(files, monkeypatch, tmp_path):
    metrics, state = files
    metrics.write_bytes(row())
    sidecar.Cursor(*files).drain(lambda value: None)
    terminal = tmp_path / "exit-code"
    terminal.write_text("0\n")
    clock = [0]
    monkeypatch.setattr(sidecar.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(sidecar.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    sent = []
    code = sidecar.supervise(sidecar.Cursor(*files), sent.append, terminal, lambda: False, hold=4)
    assert code == 0
    assert clock[0] == 4
    assert sent[0]["train/loss"] == 1.2


def test_signal_reports_interruption(files, tmp_path):
    with pytest.raises(InterruptedError):
        sidecar.supervise(sidecar.Cursor(*files), lambda value: None, tmp_path / "exit", lambda: True)


def args_for(tmp_path):
    result = []
    for key, value in {
        "metrics": tmp_path / "metrics.jsonl",
        "state": tmp_path / "cursor.json",
        "status": tmp_path / "status.json",
        "exit-code": tmp_path / "exit-code",
        "experiment": "test",
        "ray-temp-dir": tmp_path / "ray",
        "server-url": "http://127.0.0.1:18080",
    }.items():
        result.extend(["--" + key, str(value)])
    return result


def test_main_lifecycle(tmp_path, monkeypatch):
    (tmp_path / "metrics.jsonl").write_bytes(row())
    (tmp_path / "exit-code").write_text("0")
    closed = []

    class Sink:
        last_status = {"events_applied": 2}

        def __init__(self, args):
            pass

        def __call__(self, values):
            assert json.loads((tmp_path / "status.json").read_text())["status"] == "running"

        def close(self):
            closed.append(True)

    clock = [0]
    monkeypatch.setattr(sidecar, "InsightSink", Sink)
    monkeypatch.setattr(sidecar.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(sidecar.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    assert sidecar.main(args_for(tmp_path)) == 0
    status = json.loads((tmp_path / "status.json").read_text())
    assert status["status"] == "forwarding_complete"
    assert status["backend_verified"] is False
    assert status["records"] == 1
    assert closed == [True]


def test_init_failure_status(tmp_path, monkeypatch):
    def fail(args):
        raise RuntimeError("disabled")

    monkeypatch.setattr(sidecar, "InsightSink", fail)
    assert sidecar.main(args_for(tmp_path)) == 1
    assert json.loads((tmp_path / "status.json").read_text())["status"] == "failed"


@pytest.mark.parametrize(
    "arg,value", [("poll-seconds", "nan"), ("scrape-seconds", "0"), ("hold-seconds", "-2"), ("metrics-port", "1")]
)
def test_invalid_options(tmp_path, arg, value):
    with pytest.raises(SystemExit):
        sidecar.main(args_for(tmp_path) + ["--" + arg, value])


def test_concurrent_sidecar_rejected(tmp_path):
    with (tmp_path / "cursor.lock").open("a") as handle:
        sidecar.fcntl.flock(handle, sidecar.fcntl.LOCK_EX | sidecar.fcntl.LOCK_NB)
        assert sidecar.main(args_for(tmp_path)) == 2
    assert not (tmp_path / "status.json").exists()


def test_bad_resume_value(files):
    metrics, state = files
    metrics.write_bytes(row())
    sidecar.Cursor(*files).drain(lambda value: None)
    saved = json.loads(state.read_text())
    saved["latest"]["train/loss"] = float("nan")
    state.write_text(json.dumps(saved))
    with pytest.raises(ValueError, match="persisted gauge"):
        sidecar.Cursor(*files)


def test_sink_sanitizes_and_flushes():
    sink = sidecar.InsightSink.__new__(sidecar.InsightSink)
    from types import SimpleNamespace

    calls = []
    sink.insight = SimpleNamespace(metric_gauge=lambda name, value: calls.append((name, value)))
    sink.barrier = lambda: {"events_applied": 2}
    sink({"train/total_tokens(B)": 1.2})
    assert calls == [("train_total_tokens_B_", 1.2)]
    assert sink.last_status["events_applied"] == 2


@pytest.mark.parametrize("disabled", [False, True])
def test_runtime_is_private_and_cleans_up(tmp_path, monkeypatch, disabled):
    import importlib.metadata
    import sys
    from types import SimpleNamespace

    calls = []
    actor = SimpleNamespace(get_status=SimpleNamespace(remote=lambda: "status-handle"))
    ray = SimpleNamespace(
        is_initialized=lambda: False,
        init=lambda **kwargs: calls.append(("init", kwargs)),
        shutdown=lambda: calls.append(("shutdown", None)),
        get=lambda handle, timeout: {"events_applied": 1},
    )
    api = SimpleNamespace(_STATE=SimpleNamespace(enabled=not disabled, client=SimpleNamespace(_actor=actor)))
    insight = SimpleNamespace(
        api=api,
        init=lambda **kwargs: calls.append(("insight", kwargs)),
        finish=lambda: calls.append(("finish", None)),
        metric_gauge=lambda name, value: calls.append((name, value)),
    )
    monkeypatch.setitem(sys.modules, "ray", ray)
    monkeypatch.setitem(sys.modules, "rl_insight", insight)
    monkeypatch.setattr(importlib.metadata, "version", lambda package: "0.3.0")
    args = SimpleNamespace(
        server_url="http://localhost:18080",
        ray_temp_dir=tmp_path / "ray",
        project="test",
        experiment="run",
        metrics_port=19092,
    )
    if disabled:
        with pytest.raises(RuntimeError, match="disabled"):
            sidecar.InsightSink(args)
    else:
        sink = sidecar.InsightSink(args)
        sink({"train/loss": 1})
        sink.close()
    assert calls[0][1]["address"] == "local"
    assert calls[0][1]["num_gpus"] == 0
    assert calls[0][1]["num_cpus"] == 2
    assert calls[-1][0] == "shutdown"
