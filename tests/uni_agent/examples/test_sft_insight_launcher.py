"""Execute the real shell launcher with CPU process substitutes, without Ray/GPU."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

LAUNCHER = Path(__file__).resolve().parents[3] / "examples/performance_9b/run_verl_sft.sh"
FAKE_PYTHON = r"""
import json
import os
import sys
import time
from pathlib import Path

arguments = sys.argv[1:]
if arguments[0] == "-c":
    os.execv(sys.executable, [sys.executable, *arguments])
root = Path(os.environ["RUN_ROOT"])
mode = os.environ["FAKE_MODE"]
if arguments[0].endswith("sft_insight_sidecar.py"):
    status = Path(arguments[arguments.index("--status") + 1])
    if mode == "init_failure":
        status.write_text(json.dumps({"status": "failed"}))
        raise SystemExit(17)
    time.sleep(0.15)
    # Any GPU launch before status readiness violates the launcher contract.
    if (root / "train-started").exists():
        (root / "ordering-error").touch()
        raise SystemExit(18)
    status.write_text(json.dumps({"status": "running"}))
    deadline = time.monotonic() + 12
    while not (root / "exit-code").exists():
        if time.monotonic() > deadline:
            raise SystemExit(19)
        time.sleep(0.02)
    if mode in ("monitor_failure", "both_failure"):
        raise SystemExit(9)
    raise SystemExit(0)
if arguments[1] == "torch.distributed.run":
    status = json.loads((root / "insight-status.json").read_text())
    assert status["status"] == "running"
    assert os.environ["VERL_RL_INSIGHT_ENABLE"] == "0"
    assert "trainer.logger=[console,file,wandb]" in arguments
    (root / "train-started").touch()
    Path(os.environ["VERL_FILE_LOGGER_PATH"]).write_text(
        json.dumps({"step": 1, "data": {"train/loss": 1.0}}) + "\n"
    )
    print("CPU fake train completed", flush=True)
    raise SystemExit(7 if mode in ("train_failure", "both_failure") else 0)
raise SystemExit("unexpected python invocation")
"""


@pytest.fixture
def run_launcher(tmp_path):
    python = tmp_path / "fake-python"
    python.write_text(f"#!{sys.executable}\n" + FAKE_PYTHON)
    python.chmod(0o755)
    model = tmp_path / "model"
    model.mkdir()
    data = tmp_path / "data"
    data.mkdir()
    (data / "train.parquet").touch()
    (data / "validation.parquet").touch()
    run = tmp_path / "runs" / "test"

    def invoke(mode):
        env = {
            **os.environ,
            "WORKSPACE_ROOT": str(tmp_path),
            "PYTHON_BIN": str(python),
            "MODEL_PATH": str(model),
            "DATA_ROOT": str(data),
            "RUN_ROOT": str(run),
            "RUN_ID": "test",
            "SFT_INSIGHT_ENABLE": "1",
            "VERL_RL_INSIGHT_ENABLE": "1",
            "RL_INSIGHT_SERVER_URL": "http://127.0.0.1:18080",
            "NPROC_PER_NODE": "2",
            "TRAIN_BATCH_SIZE": "2",
            "LOGGER_BACKENDS": "console,file,wandb",
            "FAKE_MODE": mode,
        }
        result = subprocess.run(["bash", str(LAUNCHER)], env=env, capture_output=True, text=True, timeout=15)
        return result, run

    return invoke


def test_waits_for_ready_then_preserves_success_codes(run_launcher):
    result, run = run_launcher("success")
    assert result.returncode == 0, result.stderr
    assert (run / "train-started").exists()
    assert not (run / "ordering-error").exists()
    assert (run / "exit-code").read_text().strip() == "0"
    assert (run / "insight-exit-code").read_text().strip() == "0"
    assert "CPU fake train completed" in (run / "train.log").read_text()


def test_initialization_failure_prevents_training(run_launcher):
    result, run = run_launcher("init_failure")
    assert result.returncode == 3
    assert not (run / "train-started").exists()
    assert not (run / "exit-code").exists()
    assert (run / "insight-exit-code").read_text().strip() == "17"
    assert json.loads((run / "insight-status.json").read_text())["status"] == "failed"


@pytest.mark.parametrize(
    "mode,train,monitor,wrapper", [("train_failure", 7, 0, 7), ("both_failure", 7, 9, 7), ("monitor_failure", 0, 9, 3)]
)
def test_independent_exit_codes_and_training_failure_priority(run_launcher, mode, train, monitor, wrapper):
    result, run = run_launcher(mode)
    assert result.returncode == wrapper, result.stderr
    assert int((run / "exit-code").read_text()) == train
    assert int((run / "insight-exit-code").read_text()) == monitor
