"""supervise_run.sh relaunches a crashed driver until the run is complete, and gives up on a loop."""

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "examples/harbor_opd_rl/supervise_run.sh"


def stub_launcher(tmp_path: Path) -> Path:
    # Stands in for launch-detached.sh: runs the command in the foreground and records the
    # exit line the supervisor waits for.
    stub = tmp_path / "launch.sh"
    stub.write_text('#!/usr/bin/env bash\nbash -c "$2" >> "$1" 2>&1; echo "[detached] exit=$? now" >> "$1"\n')
    return stub


def run(tmp_path: Path, launch: str, max_relaunches: str = "3") -> subprocess.CompletedProcess:
    run_dir = tmp_path / "run"
    (run_dir / "train").mkdir(parents=True, exist_ok=True)
    driver_log = tmp_path / "driver.log"
    driver_log.write_text("[detached] exit=1 first attempt crashed\n")
    (run_dir / "train" / "train.log").write_text("attempt 1 log\n")
    env = {
        **os.environ,
        "LAUNCHER": str(stub_launcher(tmp_path)),
        "RUN_DIRS": str(run_dir),
        "POLL": "0.05",
        "TRAINER_WAIT_POLLS": "1",
    }
    done = f"[ -f {run_dir}/train/PASSED ]"
    return subprocess.run(
        ["bash", str(SCRIPT), str(driver_log), done, launch, max_relaunches],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_relaunches_until_complete_and_keeps_the_old_logs(tmp_path):
    run_dir = tmp_path / "run"
    result = run(tmp_path, f"touch {run_dir}/train/PASSED")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "relaunch 1/3" in result.stdout and "run complete" in result.stdout
    kept = list((run_dir / "train").glob("train.attempt-*.log"))
    assert len(kept) == 1 and kept[0].read_text() == "attempt 1 log\n"
    assert len(list(tmp_path.glob("driver.attempt-*.log"))) == 1


def test_gives_up_after_max_relaunches(tmp_path):
    result = run(tmp_path, "exit 1", max_relaunches="2")
    assert result.returncode == 1
    assert "relaunch 2/2" in result.stdout and "giving up" in result.stdout


def test_stops_at_once_when_already_complete(tmp_path):
    run_dir = tmp_path / "run"
    (run_dir / "train").mkdir(parents=True)
    (run_dir / "train" / "PASSED").write_text("x")
    result = run(tmp_path, "exit 1")
    assert result.returncode == 0 and "relaunch" not in result.stdout
