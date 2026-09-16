"""HARBOR_REWARD_MODE=pass_ratio shapes non-passing Harbor rewards from the CTRF report."""

import json

import pytest

from uni_agent.tasks.harbor import reward as harbor_reward


def _trial(tmp_path, *, binary: float, tests: int | None, passed: int | None):
    trial_dir = tmp_path / "trial"
    (trial_dir / "verifier").mkdir(parents=True)
    if tests is not None:
        (trial_dir / "verifier" / "ctrf.json").write_text(
            json.dumps({"results": {"summary": {"tests": tests, "passed": passed, "failed": tests - passed}}})
        )
    payload = {"id": "t", "verifier_result": {"rewards": {"reward": binary}}}
    return harbor_reward.task_result_from_harbor_trial(
        payload, trial_dir=trial_dir, cli_exit_code=0, stdout="", stderr="", elapsed=1.0
    )


def test_default_binary_mode_ignores_ctrf(tmp_path, monkeypatch):
    monkeypatch.delenv("HARBOR_REWARD_MODE", raising=False)
    result = _trial(tmp_path, binary=0.0, tests=3, passed=1)
    assert result.reward == 0.0
    assert result.extra_info["resolved"] is False
    assert result.extra_info["eval_report"]["reward_mode"] == "binary"
    assert result.extra_info["eval_report"]["reward_shaping"] is None


def test_pass_ratio_shapes_partial_credit(tmp_path, monkeypatch):
    monkeypatch.setenv("HARBOR_REWARD_MODE", "pass_ratio")
    result = _trial(tmp_path, binary=0.0, tests=3, passed=1)
    assert result.reward == pytest.approx(1 / 3)
    assert result.accuracy == pytest.approx(1 / 3)
    assert result.extra_info["resolved"] is False
    assert result.extra_info["eval_completed"] is True
    shaping = result.extra_info["eval_report"]["reward_shaping"]
    assert shaping == {"mode": "pass_ratio", "binary_reward": 0.0, "ctrf": {"tests": 3, "passed": 1, "failed": 2}}


def test_pass_ratio_keeps_full_pass_and_resolved(tmp_path, monkeypatch):
    monkeypatch.setenv("HARBOR_REWARD_MODE", "pass_ratio")
    result = _trial(tmp_path, binary=1.0, tests=3, passed=3)
    assert result.reward == 1.0
    assert result.extra_info["resolved"] is True
    assert result.extra_info["eval_report"]["reward_shaping"] is None


def test_pass_ratio_without_ctrf_falls_back_to_binary(tmp_path, monkeypatch):
    monkeypatch.setenv("HARBOR_REWARD_MODE", "pass_ratio")
    result = _trial(tmp_path, binary=0.0, tests=None, passed=None)
    assert result.reward == 0.0
    assert result.extra_info["eval_report"]["reward_shaping"] is None


def test_unknown_mode_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("HARBOR_REWARD_MODE", "bogus")
    with pytest.raises(ValueError, match="HARBOR_REWARD_MODE"):
        _trial(tmp_path, binary=0.0, tests=3, passed=1)
