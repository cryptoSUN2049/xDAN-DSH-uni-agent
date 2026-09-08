import hashlib
import json

import pytest

from tests.uni_agent.examples.test_log_tool_verifier import valid as valid

pytestmark = [pytest.mark.cpu, pytest.mark.level0]


def digest(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


@pytest.fixture
def inputs(tmp_path, request):
    from uni_agent.agents.dsh.harbor_release import T2_PATCH_PATH

    events, fixture = request.getfixturevalue("valid")
    source = tmp_path / "input"
    source.mkdir()
    trace = ("\n".join(json.dumps(event) for event in events) + "\n").encode()
    helper = dict(
        schema="dsh.uni-agent.dsh-run.v1",
        dsh_session_id="dsh-session-1",
        finish_reason="completed",
        trace_persisted=True,
        trace_sha256=digest(trace),
        event_count=len(events),
        profile="sdk-minimal",
        trace_path="/tmp/uni-agent-dsh/artifacts/" + hashlib.sha256(b"session-1").hexdigest()[:24] + "/session.jsonl",
        patches_sha256=digest(json.dumps([T2_PATCH_PATH], separators=(",", ":")).encode()),
    )
    raw = json.dumps(helper).encode()
    status = dict(
        schema="dsh.harbor-agent-execution.v1",
        status="completed",
        finished=True,
        finish_reason="completed",
        gateway_session_id="session-1",
        dsh_session_id="dsh-session-1",
        trace_sha256=digest(trace),
        run_sha256=digest(raw),
        event_count=len(events),
        harbor_context_id="trial-1",
        harbor_agent_session_id="trial-1__agent",
    )
    (source / "session.jsonl").write_bytes(trace)
    (source / "run.json").write_bytes(raw)
    (source / "status.json").write_text(json.dumps(status))
    fixture_path = tmp_path / "fixture.json"
    fixture_path.write_text(json.dumps(fixture))
    return dict(input_dir=source, fixture_path=fixture_path, output_dir=tmp_path / "output")


def test_success_writes_harbor_reward_and_report(inputs):
    from examples.harbor.t2_verifier import run_verifier

    report = run_verifier(**inputs)
    assert report["reward"] == 1.0
    assert (inputs["output_dir"] / "reward.txt").read_text() == "1\n"
    assert report["hidden_inputs_verified"] is False


@pytest.mark.parametrize("corrupt", ["trace", "session", "finished"])
def test_untrusted_input_never_writes_zero_reward(inputs, corrupt):
    from examples.harbor.t2_verifier import run_verifier

    source = inputs["input_dir"]
    if corrupt == "trace":
        (source / "session.jsonl").write_bytes(b"changed")
    else:
        status = json.loads((source / "status.json").read_text())
        status["gateway_session_id" if corrupt == "session" else "finished"] = (
            "wrong" if corrupt == "session" else False
        )
        (source / "status.json").write_text(json.dumps(status))
    with pytest.raises((ValueError, RuntimeError)):
        run_verifier(**inputs)
    assert not (inputs["output_dir"] / "reward.txt").exists()


@pytest.mark.parametrize("duplicate", [False, True])
def test_trusted_business_zero_versus_untrusted_duplicate(inputs, duplicate):
    from examples.harbor.t2_verifier import run_verifier
    from tests.uni_agent.tasks.test_dsh_evolution_v3_live_verifier import _result

    source = inputs["input_dir"]
    events = [json.loads(line) for line in (source / "session.jsonl").read_bytes().splitlines()]
    if duplicate:
        events[2:2] = events[:2]
    else:
        events[13] = _result("12", [])
    trace = ("\n".join(json.dumps(event) for event in events) + "\n").encode()
    (source / "session.jsonl").write_bytes(trace)
    helper = json.loads((source / "run.json").read_text())
    helper.update(trace_sha256=digest(trace), event_count=len(events))
    raw = json.dumps(helper).encode()
    (source / "run.json").write_bytes(raw)
    status = json.loads((source / "status.json").read_text())
    status.update(trace_sha256=digest(trace), run_sha256=digest(raw), event_count=len(events))
    (source / "status.json").write_text(json.dumps(status))
    if duplicate:
        with pytest.raises(ValueError, match="Untrusted"):
            run_verifier(**inputs)
        assert not (inputs["output_dir"] / "reward.txt").exists()
    else:
        report = run_verifier(**inputs)
        assert report["reward"] == 0.0
        assert report["evaluation"]["eligible"] is True
        assert (inputs["output_dir"] / "reward.txt").read_text() == "0\n"
