"""Translate Harbor verifier output into Uni-Agent rewards."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from ..base import TaskResult

_OUTPUT_TAIL_CHARS = 8000
_REWARD_MODE_ENV = "HARBOR_REWARD_MODE"
_REWARD_MODES = ("binary", "pass_ratio")
_INFRA_FAILURE_ENV = "HARBOR_INFRA_FAILURE"
_INFRA_FAILURE_POLICIES = ("exclude", "zero")
# Harbor exceptions that mean the agent itself failed: they are scored 0.
_AGENT_FAILURE_EXCEPTIONS = frozenset({"AgentTimeoutError", "OutputLengthExceededError"})
# Python traceback frames (`File "path", line N`) and pytest's short frames
# (`path.py:N: in <module>`, possibly after pytest's `E ` prefix), in text order.
_TRACEBACK_FRAME = re.compile(r'File "([^"]+)", line \d+|^[ \t]*(?:E[ \t]+)?(\S+\.py):\d+:', re.MULTILINE)
_NON_WORKSPACE_PATH_MARKERS = ("site-packages", "dist-packages", "/usr/lib/python", "/usr/local/lib/python")


def infra_failure_policy() -> str:
    """How an incomplete trial caused by infrastructure is surfaced to training.

    ``exclude`` (default) makes the Harbor task raise, so the framework drops that one
    session and the rest of its GRPO group still trains. ``zero`` keeps the legacy
    behaviour of scoring it 0, which hands a potentially good trajectory the most
    negative advantage in its group for a sandbox failure it did not cause.
    """
    policy = os.environ.get(_INFRA_FAILURE_ENV, "exclude").strip() or "exclude"
    if policy not in _INFRA_FAILURE_POLICIES:
        raise ValueError(f"{_INFRA_FAILURE_ENV} must be one of {_INFRA_FAILURE_POLICIES}, got {policy!r}")
    return policy


def _verifier_blames_workspace(trial_dir: Path) -> bool:
    """True when the verifier's last Python traceback frame is in the task workspace.

    Relative frames (pytest prints paths relative to its rootdir, the workdir) count
    as workspace frames unless they point into site-packages or the interpreter.

    Verifiers such as swe-rebench's run_tests.py treat "no tests collected" as an
    infrastructure failure and write no reward, even when collection crashed on a
    SyntaxError the agent wrote into the repository. On audited tasks the untouched
    repository collects cleanly, so a final frame outside site-packages and the
    interpreter means the agent broke the code: a task failure, not infrastructure.
    """
    verifier_dir = trial_dir / "verifier"
    texts: list[str] = []
    stdout_path = verifier_dir / "test-stdout.txt"
    if stdout_path.is_file():
        texts.append(stdout_path.read_text(encoding="utf-8", errors="replace"))
    grade_path = verifier_dir / "grade.json"
    if grade_path.is_file():
        try:
            grade = json.loads(grade_path.read_text(encoding="utf-8", errors="replace"))
        except json.JSONDecodeError:
            grade = None
        if isinstance(grade, dict):
            for key in ("collect_stdout_tail", "collect_stderr_tail"):
                if isinstance(grade.get(key), str):
                    texts.append(grade[key])
    frames = [quoted or short for quoted, short in _TRACEBACK_FRAME.findall("\n".join(texts))]
    if not frames:
        return False
    last = frames[-1]
    return not last.startswith("<") and not any(marker in last for marker in _NON_WORKSPACE_PATH_MARKERS)


def _failure_kind(exception: dict[str, Any] | None, cli_exit_code: int, trial_dir: Path) -> str:
    """Classify an incomplete trial as ``agent`` (scored 0) or ``infra`` (excludable)."""
    if cli_exit_code != 0 or exception is None:
        return "infra"
    exception_type = str(exception.get("exception_type") or "").rsplit(".", 1)[-1]
    if exception_type in _AGENT_FAILURE_EXCEPTIONS:
        return "agent"
    if exception_type == "RewardFileNotFoundError" and _verifier_blames_workspace(trial_dir):
        return "agent"
    return "infra"


def reward_mode() -> str:
    """Operator-selected reward shaping; ``binary`` keeps Harbor's primary reward as-is.

    ``pass_ratio`` replaces a non-passing binary reward with passed/total from the
    verifier's CTRF report when one exists, giving GRPO a dense signal on tasks the
    policy cannot yet fully solve. A full pass stays 1.0 and ``resolved`` still
    means the binary verifier reward was 1.0.
    """
    mode = os.environ.get(_REWARD_MODE_ENV, "binary").strip() or "binary"
    if mode not in _REWARD_MODES:
        raise ValueError(f"{_REWARD_MODE_ENV} must be one of {_REWARD_MODES}, got {mode!r}")
    return mode


def _ctrf_pass_ratio(trial_dir: Path) -> tuple[float | None, dict[str, Any] | None]:
    """Return (passed/tests, summary) from verifier/ctrf.json, or (None, None) when unavailable."""
    report = trial_dir / "verifier" / "ctrf.json"
    if not report.is_file():
        return None, None
    try:
        summary = json.loads(report.read_text(encoding="utf-8"))["results"]["summary"]
        tests = int(summary["tests"])
        passed = int(summary["passed"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None, None
    if tests <= 0 or passed < 0 or passed > tests:
        return None, None
    return passed / tests, {"tests": tests, "passed": passed, "failed": summary.get("failed")}


def _primary_reward(rewards: Any) -> tuple[float | None, str | None]:
    if not isinstance(rewards, dict) or not rewards:
        return None, "Harbor trial produced no verifier rewards"

    if "reward" in rewards:
        value = rewards["reward"]
        key = "reward"
    elif len(rewards) == 1:
        key, value = next(iter(rewards.items()))
    else:
        return None, "Harbor verifier returned multiple metrics without a primary 'reward' key"

    if isinstance(value, bool) or not isinstance(value, int | float):
        return None, f"Harbor verifier reward {key!r} is not numeric"
    return float(value), None


def _exception_summary(exception: Any) -> dict[str, Any] | None:
    if not isinstance(exception, dict) or not exception:
        return None
    return {
        key: exception.get(key)
        for key in ("exception_type", "exception_message", "occurred_at")
        if exception.get(key) is not None
    }


def _step_summaries(steps: Any) -> list[dict[str, Any]] | None:
    if not isinstance(steps, list):
        return None

    summaries = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        verifier_result = step.get("verifier_result")
        summaries.append(
            {
                "step_name": step.get("step_name"),
                "rewards": verifier_result.get("rewards") if isinstance(verifier_result, dict) else None,
                "exception": _exception_summary(step.get("exception_info")),
            }
        )
    return summaries


def task_result_from_harbor_trial(
    payload: dict[str, Any],
    *,
    trial_dir: Path,
    cli_exit_code: int,
    stdout: str,
    stderr: str,
    elapsed: float,
) -> TaskResult:
    """Translate Harbor's persisted TrialResult into Uni-Agent's result shape."""
    verifier_result = payload.get("verifier_result")
    rewards = verifier_result.get("rewards") if isinstance(verifier_result, dict) else None
    score, reward_error = _primary_reward(rewards)
    exception = _exception_summary(payload.get("exception_info"))

    error: str | None = None
    if cli_exit_code != 0:
        detail = (stderr or stdout).strip()[-2000:]
        error = f"Harbor CLI exited with code {cli_exit_code}" + (f": {detail}" if detail else "")
    elif exception is not None:
        exception_type = exception.get("exception_type", "HarborTrialError")
        exception_message = exception.get("exception_message", "trial failed")
        error = f"{exception_type}: {exception_message}"
    elif reward_error is not None:
        error = reward_error

    completed = error is None and score is not None
    failure_kind = None if completed else _failure_kind(exception, cli_exit_code, trial_dir)
    binary_reward = score if completed and score is not None else 0.0
    resolved = completed and binary_reward == 1.0
    scalar_reward = binary_reward
    mode = reward_mode()
    shaping: dict[str, Any] | None = None
    if mode == "pass_ratio" and completed and not resolved:
        ratio, ctrf_summary = _ctrf_pass_ratio(trial_dir)
        if ratio is not None:
            scalar_reward = ratio
            shaping = {"mode": mode, "binary_reward": binary_reward, "ctrf": ctrf_summary}
    timings = {
        key: payload.get(key)
        for key in (
            "started_at",
            "finished_at",
            "environment_setup",
            "agent_setup",
            "agent_execution",
            "verifier",
        )
        if payload.get(key) is not None
    }

    eval_report = {
        "trial_id": payload.get("id"),
        "trial_name": payload.get("trial_name"),
        "trial_uri": payload.get("trial_uri"),
        "trial_path": str(trial_dir),
        "artifact_path": str(trial_dir / "artifacts"),
        "cli_exit_code": cli_exit_code,
        "rewards": rewards,
        "exception": exception,
        "steps": _step_summaries(payload.get("step_results")),
        "timings": timings,
        "stdout_tail": stdout[-_OUTPUT_TAIL_CHARS:],
        "stderr_tail": stderr[-_OUTPUT_TAIL_CHARS:],
        "error": error,
        "failure_kind": failure_kind,
        "reward_mode": mode,
        "reward_shaping": shaping,
    }
    extra_info = {
        "resolved": resolved,
        "eval_completed": completed,
        "failure_kind": failure_kind,
        "eval_execution_time": elapsed,
        "eval_report": eval_report,
        "agent": payload.get("agent_info"),
    }
    return TaskResult(
        reward=scalar_reward,
        accuracy=scalar_reward,
        finished=None,
        extra_info=extra_info,
    )
