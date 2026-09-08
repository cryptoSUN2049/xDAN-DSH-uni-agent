import json

from examples.dsh.capabilities.memory_denial_budget import repeated_denials
from tests.uni_agent.tasks.test_dsh_evolution_verifier import _call, _result


def pair(index, command="str_replace", denied=True):
    return [
        _call(str(index), "str_replace_editor", {"command": command, "path": "/source"}, seq=index),
        _result(str(index), "Error: MEMORY_POLICY_DENIED. read-only source" if denied else "ok", error=denied),
    ]


def lines(events):
    return b"".join((json.dumps(event) + "\n").encode() for event in events)


def test_three_confirmed_denials():
    result = repeated_denials(lines(pair(1) + pair(2) + pair(3)))
    assert result["count"] == 3
    assert result["action_sha256"].startswith("sha256:")


def test_recovery_changed_action_and_truncated_tail():
    events = pair(1) + pair(2)
    assert repeated_denials(lines(events) + b'{"type":"tool/result"')["count"] == 2
    assert repeated_denials(lines(events + pair(3, denied=False)))["count"] == 0
    assert repeated_denials(lines(events + pair(3, command="create")))["count"] == 1
    assert repeated_denials(lines(events + pair(3)[:1]))["count"] == 2


def test_unpaired_or_successful_denial_text_never_counts():
    assert repeated_denials(lines([_result("orphan", "MEMORY_POLICY_DENIED", error=True)]))["count"] == 0
    events = pair(1)
    events[-1] = _result("1", "MEMORY_POLICY_DENIED", error=False)
    assert repeated_denials(lines(events))["count"] == 0


def test_malformed_complete_text_is_not_confirmed_evidence():
    events = pair(1)
    events[-1]["data"]["message"]["content"][0]["content"][0]["text"] = 7
    assert repeated_denials(lines(events))["count"] == 0


def test_sessions_are_independent_and_recovery_clears_current_streak(tmp_path):
    from examples.dsh.capabilities.memory_denial_budget import RepeatedMemoryDenial, denial_health

    paths = [tmp_path / "homes" / name / "sessions/cwd/session/session.v2.jsonl" for name in ("A", "B")]
    for path in paths:
        path.parent.mkdir(parents=True)
        path.write_bytes(lines(pair(1) + pair(2)))
    check = denial_health(tmp_path)
    check()  # Two+two from different sessions must not become four.
    paths[0].write_bytes(lines(pair(1) + pair(2) + pair(3, denied=False)))
    check()
    paths[1].write_bytes(lines(pair(1) + pair(2) + pair(3)))
    import pytest

    with pytest.raises(RepeatedMemoryDenial):
        check()
    report = json.loads((tmp_path / "repeated-denial.json").read_text())
    assert report["count"] == 3 and report["threshold"] == 3
    assert "/source" not in json.dumps(report)


def test_confirmed_denial_ends_real_owned_cpu_process(tmp_path):
    import os
    import sys

    from deployment.services.harbor_training_supervisor import supervise
    from examples.dsh.capabilities.memory_denial_budget import denial_health

    path = tmp_path / "homes/A/sessions/cwd/session/session.v2.jsonl"
    path.parent.mkdir(parents=True)
    raw = lines(pair(1) + pair(2) + pair(3))
    command = [
        sys.executable,
        "-c",
        f"from pathlib import Path;import time;Path({str(path)!r}).write_bytes({raw!r});time.sleep(10)",
    ]
    result = supervise(
        command,
        tmp_path,
        os.environ.copy(),
        tmp_path,
        denial_health(tmp_path),
        wall_seconds=3,
        interval=0.02,
        grace=0.2,
    )
    assert result["reason"] == "controller-health-failed" and result["exit_code"] != 0
    assert result["health_failure"]["exception_type"] == "RepeatedMemoryDenial"
    import pytest

    with pytest.raises(ProcessLookupError):
        os.kill(result["pid"], 0)
