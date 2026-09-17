"""Incomplete Harbor trials are split into agent failures (scored 0) and infrastructure failures (excluded)."""

import json

import pytest

from uni_agent.tasks.harbor import reward as harbor_reward
from uni_agent.tasks.harbor import task as harbor_task

REPO_SYNTAX_ERROR = """aiohttp/web_middlewares.py:9: in <module>
    from .web_urldispatcher import SystemRoute
E     File "/aiohttp/aiohttp/web_urldispatcher.py", line 1276
E   SyntaxError: invalid syntax
no tests collected, 1 error in 0.29s
"""
PLUGIN_ERROR = """  File "/usr/local/lib/python3.10/site-packages/_pytest/config/__init__.py", line 879, in x
    __import__(importspec)
  File "/usr/local/lib/python3.10/site-packages/pytest_asyncio/plugin.py", line 12, in <module>
ImportError: cannot import name 'x'
"""


def _result(tmp_path, *, exception_type=None, cli_exit_code=0, stdout_text=None, grade=None):
    trial_dir = tmp_path / "trial"
    (trial_dir / "verifier").mkdir(parents=True)
    if stdout_text is not None:
        (trial_dir / "verifier" / "test-stdout.txt").write_text(stdout_text)
    if grade is not None:
        (trial_dir / "verifier" / "grade.json").write_text(json.dumps(grade))
    payload = {"id": "t", "verifier_result": None}
    if exception_type is not None:
        payload["exception_info"] = {"exception_type": exception_type, "exception_message": "boom"}
    return harbor_reward.task_result_from_harbor_trial(
        payload, trial_dir=trial_dir, cli_exit_code=cli_exit_code, stdout="", stderr="", elapsed=1.0
    )


def test_completed_trial_has_no_failure_kind(tmp_path):
    trial_dir = tmp_path / "trial"
    trial_dir.mkdir()
    payload = {"id": "t", "verifier_result": {"rewards": {"reward": 1.0}}}
    result = harbor_reward.task_result_from_harbor_trial(
        payload, trial_dir=trial_dir, cli_exit_code=0, stdout="", stderr="", elapsed=1.0
    )
    assert result.extra_info["failure_kind"] is None
    harbor_task.raise_if_infra_failure(result, "x")


@pytest.mark.parametrize("exception_type", ["AgentTimeoutError", "harbor.llms.base.OutputLengthExceededError"])
def test_agent_exceptions_are_scored_zero(tmp_path, exception_type):
    result = _result(tmp_path, exception_type=exception_type)
    assert result.reward == 0.0
    assert result.extra_info["failure_kind"] == "agent"
    harbor_task.raise_if_infra_failure(result, "x")


def test_reward_file_missing_after_agent_broke_repo_is_agent_failure(tmp_path):
    result = _result(tmp_path, exception_type="RewardFileNotFoundError", stdout_text=REPO_SYNTAX_ERROR)
    assert result.extra_info["failure_kind"] == "agent"
    harbor_task.raise_if_infra_failure(result, "x")


def test_grade_json_collection_tail_is_used(tmp_path):
    tail = (
        '  File "/earthkit-data/src/earthkit/data/core/select.py", line 70\n'
        "    def sel(...): ...\nSyntaxError: invalid syntax\n"
    )
    result = _result(
        tmp_path,
        exception_type="RewardFileNotFoundError",
        stdout_text="infra: none of the expected tests could be collected\n",
        grade={"collected": 0, "collect_rc": 1, "collect_stderr_tail": PLUGIN_ERROR + tail},
    )
    assert result.extra_info["failure_kind"] == "agent"


@pytest.mark.parametrize(
    ("exception_type", "stdout_text", "cli_exit_code"),
    [
        ("RewardFileNotFoundError", PLUGIN_ERROR, 0),
        ("RewardFileNotFoundError", None, 0),
        ("modal.exception.ImageBuildError", None, 0),
        ("NotFoundError", None, 0),
        (None, None, harbor_task.HARBOR_TRIAL_TIMEOUT_EXIT_CODE),
    ],
)
def test_infrastructure_failures_are_excluded_by_default(
    tmp_path, monkeypatch, exception_type, stdout_text, cli_exit_code
):
    monkeypatch.delenv("HARBOR_INFRA_FAILURE", raising=False)
    result = _result(tmp_path, exception_type=exception_type, stdout_text=stdout_text, cli_exit_code=cli_exit_code)
    assert result.extra_info["failure_kind"] == "infra"
    assert result.extra_info["eval_report"]["failure_kind"] == "infra"
    with pytest.raises(harbor_task.HarborInfraFailure, match="infrastructure failure for x"):
        harbor_task.raise_if_infra_failure(result, "x")


def test_zero_policy_keeps_legacy_scoring(tmp_path, monkeypatch):
    monkeypatch.setenv("HARBOR_INFRA_FAILURE", "zero")
    result = _result(tmp_path, exception_type="ImageBuildError")
    assert result.reward == 0.0
    harbor_task.raise_if_infra_failure(result, "x")


def test_unknown_policy_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("HARBOR_INFRA_FAILURE", "bogus")
    result = _result(tmp_path, exception_type="ImageBuildError")
    with pytest.raises(ValueError, match="HARBOR_INFRA_FAILURE"):
        harbor_task.raise_if_infra_failure(result, "x")
