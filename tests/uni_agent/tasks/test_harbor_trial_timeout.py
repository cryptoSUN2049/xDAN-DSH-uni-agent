"""run_harbor_cli enforces a whole-trial wall clock and reports exit code 124 on expiry."""

import asyncio
import sys

import pytest

from uni_agent.tasks.harbor import task as harbor_task


def test_trial_timeout_kills_process_and_reports_124():
    command = [sys.executable, "-c", "import time; time.sleep(30)"]
    result = asyncio.run(harbor_task.run_harbor_cli(command, timeout=0.5))
    assert result.exit_code == harbor_task.HARBOR_TRIAL_TIMEOUT_EXIT_CODE
    assert "trial_timeout_sec=0.5" in result.stderr


def test_no_timeout_keeps_normal_exit():
    command = [sys.executable, "-c", "print('ok')"]
    result = asyncio.run(harbor_task.run_harbor_cli(command, timeout=None))
    assert result.exit_code == 0
    assert result.stdout.strip() == "ok"


def test_config_accepts_trial_timeout(tmp_path):
    task_dir = tmp_path / "t"
    task_dir.mkdir()
    (task_dir / "task.toml").write_text("")
    config = harbor_task.HarborTaskConfig(
        agent={"name": "terminus-2"},
        trial_timeout_sec=2400,
        metadata={"instance_id": "x", "task_path": str(task_dir)},
    )
    assert config.trial_timeout_sec == 2400
    with pytest.raises(ValueError):
        harbor_task.HarborTaskConfig(
            agent={"name": "terminus-2"},
            trial_timeout_sec=0,
            metadata={"instance_id": "x", "task_path": str(task_dir)},
        )
