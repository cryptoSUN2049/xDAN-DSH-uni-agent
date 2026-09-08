import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from examples.dsh import evolution_verifier_v2 as v2
from tests.uni_agent.tasks.test_dsh_evolution_verifier import _digest, _episode


def episode(tmp_path, *, completed=True, unsafe=False):
    envelope, _, env = _episode(tmp_path, candidate_output="a b")
    path = Path(env["DSH_TRACE_PATH"])
    events = [json.loads(line) for line in path.read_text().splitlines()]
    events = events[:4] + events[-1:]
    if unsafe:
        events[2]["data"]["name"] = "cordis_undefined"
    if not completed:
        events[-1]["data"]["reason"]["kind"] = "max_steps"
    raw = b"".join((json.dumps(e) + "\n").encode() for e in events)
    path.write_bytes(raw)
    envelope["dsh"]["trace_sha256"] = env["DSH_TRACE_SHA256"] = _digest(raw)
    envelope["metadata"].update(verifier_version="2", task_version="2", verifier_code_digest=v2.bundle_digest())
    for key in ["verifier_version", "task_version", "verifier_code_digest"]:
        env["DSH_" + key.upper()] = envelope["metadata"][key]
    raw = (json.dumps(envelope) + "\n").encode()
    Path(env["DSH_TASK_RESULT_PATH"]).write_bytes(raw)
    env["DSH_ARTIFACT_SHA256"] = _digest(raw)
    return envelope, env


def cli(env):
    return subprocess.run(
        [sys.executable, "-m", "examples.dsh.evolution_verifier_v2"],
        env={**os.environ, **env},
        capture_output=True,
        text=True,
        timeout=20,
    )


def test_real_cli_admits_only_completed_zero_policy_failure(tmp_path):
    _, env = episode(tmp_path)
    result = cli(env)
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert value["eligible"] is True and value["reward"] == value["accuracy"] == 0
    assert value["extra_info"]["original_eligible"] is False
    assert value["extra_info"]["hard_veto"] == ["missing_pre_define_inspection"]
    assert value["extra_info"]["admission_kind"] == "completed-policy-failure"


@pytest.mark.parametrize("kwargs", [{"completed": False}, {"unsafe": True}])
def test_other_rejections_remain(tmp_path, kwargs):
    _, env = episode(tmp_path, **kwargs)
    result = cli(env)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["eligible"] is False


@pytest.mark.parametrize("kind", ["trace", "envelope", "bundle", "fixture", "session"])
def test_tamper_fails_closed(tmp_path, kind):
    _, env = episode(tmp_path)
    if kind in {"trace", "envelope"}:
        p = Path(env["DSH_TRACE_PATH" if kind == "trace" else "DSH_TASK_RESULT_PATH"])
        p.write_bytes(p.read_bytes() + b" ")
    elif kind == "fixture":
        (tmp_path / "fixture.json").write_text("{}")
    elif kind == "session":
        env["DSH_DSH_SESSION_ID"] = "wrong"
    else:
        env["DSH_VERIFIER_CODE_DIGEST"] = "sha256:" + "0" * 64
    assert cli(env).returncode == 2


@pytest.mark.parametrize("unsafe", [False, True])
def test_cli_to_production_fresh_receipt_and_unchanged_audit(tmp_path, unsafe):
    import hashlib
    from types import SimpleNamespace

    from uni_agent.gateway.session import Trajectory
    from uni_agent.tasks.dsh.task import _canonical_json_bytes, _task_result
    from uni_agent.tasks.dsh.trajectory_audit import TrajectoryAuditError, validate_trajectories

    envelope, env = episode(tmp_path, unsafe=unsafe)
    response = cli(env)
    assert response.returncode == 0, response.stderr
    value = json.loads(response.stdout)
    trace = Path(env["DSH_TRACE_PATH"]).read_bytes()
    gateway = "session-1"
    info = dict(
        dsh_session_id="dsh-" + gateway,
        gateway_session_id=gateway,
        trace_sha256=_digest(trace),
        event_count=len(trace.splitlines()),
    )
    result, receipt = _task_result(
        value,
        SimpleNamespace(info=info, finished=True),
        identity=envelope["metadata"],
        artifact_sha256=env["DSH_ARTIFACT_SHA256"],
        verifier_command=[sys.executable, "-m", "examples.dsh.evolution_verifier_v2"],
        verifier_stdout=response.stdout,
    )
    trace_root, result_root = tmp_path / "traces", tmp_path / "results"
    folder = trace_root / hashlib.sha256(gateway.encode()).hexdigest()[:24]
    folder.mkdir(parents=True)
    (folder / "session.jsonl").write_bytes(trace)
    key = hashlib.sha256((info["dsh_session_id"] + "\0" + info["trace_sha256"]).encode()).hexdigest()[:24]
    folder = result_root / key
    folder.mkdir(parents=True)
    (folder / "agent-result.json").write_bytes(Path(env["DSH_TASK_RESULT_PATH"]).read_bytes())
    (folder / "verifier-receipt.json").write_bytes(_canonical_json_bytes(receipt))
    reward_info = {
        **result.reward_info,
        "reward": result.reward,
        "verifier_reward": result.verifier_reward,
        "finished": result.finished,
    }
    trajectory = Trajectory(
        prompt_ids=[10],
        response_ids=[20],
        response_mask=[1],
        response_logprobs=[-0.1],
        finished=True,
        reward_score=0,
        extra_fields={"dsh_reward_info": reward_info},
        num_turns=1,
    )
    kwargs = dict(
        context={"partition_id": "train", "gateway_session_id": gateway},
        trace_root=str(trace_root),
        result_root=str(result_root),
    )
    if unsafe:
        with pytest.raises(TrajectoryAuditError, match="eligible=true"):
            validate_trajectories([trajectory], **kwargs)
    else:
        assert validate_trajectories([trajectory], **kwargs) == [trajectory]
        assert receipt["reward"] == 0 and receipt["eligible"] is True
        assert "hard_veto:missing_pre_define_inspection" in receipt["evidence"]


@pytest.mark.parametrize("output", ["a b", "wrong"])
def test_original_success_and_partial_scores_unchanged(tmp_path, monkeypatch, output):
    from examples.dsh import evolution_verifier as original

    envelope, _, env = _episode(tmp_path, candidate_output=output)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    before = original.verify()
    envelope["metadata"].update(task_version="2", verifier_version="2", verifier_code_digest=v2.bundle_digest())
    for k in ["task_version", "verifier_version", "verifier_code_digest"]:
        env["DSH_" + k.upper()] = envelope["metadata"][k]
    raw = (json.dumps(envelope) + "\n").encode()
    Path(env["DSH_TASK_RESULT_PATH"]).write_bytes(raw)
    env["DSH_ARTIFACT_SHA256"] = _digest(raw)
    response = cli(env)
    assert response.returncode == 0, response.stderr
    after = json.loads(response.stdout)
    for key in ["reward", "accuracy", "eligible"]:
        assert before[key] == after[key]
    for key in ["components", "weights", "hard_veto"]:
        assert before["extra_info"][key] == after["extra_info"][key]


@pytest.mark.parametrize("kind", ["profile", "patch", "unfinished", "duplicate"])
def test_no_admission_for_other_identity_or_completion_problems(tmp_path, kind):
    envelope, env = episode(tmp_path)
    if kind == "profile":
        envelope["dsh"]["profile"] = "other"
    elif kind == "patch":
        envelope["dsh"]["patches_sha256"] = "sha256:" + "0" * 64
    elif kind == "unfinished":
        envelope["finished"] = False
    else:
        path = Path(env["DSH_TRACE_PATH"])
        events = [json.loads(line) for line in path.read_text().splitlines()]
        events.insert(1, events[0])
        raw = b"".join((json.dumps(e) + "\n").encode() for e in events)
        path.write_bytes(raw)
        envelope["dsh"]["trace_sha256"] = env["DSH_TRACE_SHA256"] = _digest(raw)
    raw = (json.dumps(envelope) + "\n").encode()
    Path(env["DSH_TASK_RESULT_PATH"]).write_bytes(raw)
    env["DSH_ARTIFACT_SHA256"] = _digest(raw)
    response = cli(env)
    if kind == "duplicate":
        assert response.returncode == 2
    else:
        assert response.returncode == 0, response.stderr
        assert json.loads(response.stdout)["eligible"] is False


def test_parent_hash_cannot_silently_drift(monkeypatch):
    monkeypatch.setitem(v2.PARENT_SHA256, "evolution_verifier.py", "0" * 64)
    with pytest.raises(RuntimeError, match="Pinned parent"):
        v2.bundle_digest()
