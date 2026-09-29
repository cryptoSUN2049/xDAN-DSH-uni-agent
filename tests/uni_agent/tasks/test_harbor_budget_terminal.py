"""Worker admission is only a candidate; Gateway budget proof stays separate."""

import json

import pytest

from tests.uni_agent.deployment.test_harbor_run_controller import make_spec
from tests.uni_agent.tasks import test_harbor_dsh_task as fixtures
from tests.uni_agent.tasks.test_harbor_dsh_protocol import payload, policy
from uni_agent.tasks.harbor_dsh.protocol import JobRequest, RequestPolicy, request_sha256, validate_request
from uni_agent.tasks.harbor_dsh.task import HarborDshTask, verify_downloaded_evidence

pytestmark = [pytest.mark.cpu, pytest.mark.level0]
transport = fixtures.transport
MODE = "budget-terminal-v1"
LIMITS = {"max_generated_tokens": 14336, "trajectory_capacity": 32768}


def budget_request(data=None):
    data = dict(data or payload())
    data.update(schema="dsh.harbor-job-request.v2", termination_policy=MODE, budget_limits=LIMITS)
    data["request_sha256"] = request_sha256(data)
    return JobRequest.model_validate(data)


def budget_policy(data=None):
    return RequestPolicy.model_validate(
        {**policy(data or payload()).model_dump(), "termination_policy": MODE, "budget_limits": LIMITS}
    )


def terminal_contents(contents, *, reason="max-tokens", trace_reason=None, finished=False):
    trace = fixtures.raw({"type": "turn/end", "data": {"reason": {"kind": trace_reason or reason}}})
    helper = json.loads(contents["dsh_result"])
    helper.update(finish_reason=reason, trace_sha256=fixtures.digest(trace))
    contents.update(dsh_trace=trace, dsh_result=fixtures.raw(helper))
    harbor = json.loads(contents["harbor_result"])
    harbor["agent_result"]["metadata"]["dsh"].update(
        status="completed" if finished else "unfinished",
        finished=finished,
        finish_reason=reason,
        trace_sha256=fixtures.digest(trace),
        run_sha256=fixtures.digest(contents["dsh_result"]),
    )
    contents["harbor_result"] = fixtures.raw(harbor)


def test_default_policy_does_not_change_v1_wire_or_hash(tmp_path):
    data = payload()
    assert request_sha256({**data, "termination_policy": "completed-only"}) == data["request_sha256"]
    assert JobRequest.model_validate(data).model_dump(mode="json", by_alias=True) == data
    original = policy(data).model_dump(mode="json")
    assert "termination_policy" not in original
    assert (
        RequestPolicy.model_validate({**original, "termination_policy": "completed-only"}).model_dump(mode="json")
        == original
    )
    spec = make_spec(tmp_path)
    assert "termination_policy" not in spec.policy_template
    altered = spec.model_dump()
    altered["policy_template"]["termination_policy"] = MODE
    altered["policy_template"]["budget_limits"] = LIMITS
    assert type(spec).model_validate(altered).policy_template["termination_policy"] == MODE


def test_new_policy_requires_v2_and_frozen_operator_match():
    request = budget_request()
    data = request.model_dump(mode="json", by_alias=True)
    assert validate_request(data, policy=budget_policy(), now_unix=1000).termination_policy == MODE
    with pytest.raises(ValueError, match="termination"):
        validate_request(data, policy=policy(payload()), now_unix=1000)
    with pytest.raises(ValueError):
        request_sha256({**data, "schema": "dsh.harbor-job-request.v1"})
    with pytest.raises(ValueError):
        request_sha256({**payload(), "schema": "dsh.harbor-job-request.v2"})


def test_budget_amounts_are_bound_to_operator_request_and_not_metadata():
    data = budget_request().model_dump(mode="json", by_alias=True)
    data["budget_limits"]["max_generated_tokens"] += 1
    data["request_sha256"] = request_sha256(data)
    with pytest.raises(ValueError, match="budget"):
        validate_request(data, policy=budget_policy(), now_unix=1000)
    with pytest.raises(ValueError):
        RequestPolicy.model_validate({**policy(payload()).model_dump(), "budget_limits": LIMITS})
    with pytest.raises(ValueError):
        RequestPolicy.model_validate({**policy(payload()).model_dump(), "termination_policy": MODE})


@pytest.mark.parametrize("score", [0.0, 1.0])
@pytest.mark.asyncio
async def test_task_preserves_unfinished_candidate_and_verifier_reward(tmp_path, transport, score):
    calls, edit = transport
    edit.update(score=score, fn=lambda request, contents: terminal_contents(contents))
    result = await HarborDshTask(fixtures.config(tmp_path, policy=budget_policy())).run()
    assert result.finished is False
    assert result.reward == result.verifier_reward == score
    request = calls[0]
    assert request.termination_policy == MODE
    receipt = json.loads((tmp_path / "private" / request.job_id / "receipt.json").read_bytes())
    assert receipt["schema"] == "dsh.harbor-verifier-receipt.v2"
    assert receipt["termination_policy"] == MODE
    assert receipt["termination_kind"] == "budget_exhausted"
    assert receipt["finished"] is False
    assert "gateway_budget_proof" not in receipt


@pytest.mark.parametrize(
    "changes",
    [
        {"reason": "cancelled"},
        {"reason": "timeout"},
        {"reason": "error"},
        {"trace_reason": "completed"},
        {"finished": True},
    ],
)
def test_budget_mode_rejects_non_budget_or_inconsistent_terminal(changes):
    request = budget_request()
    contents = fixtures.evidence(request)
    terminal_contents(contents, **changes)
    with pytest.raises((RuntimeError, ValueError)):
        verify_downloaded_evidence(request, fixtures.downloaded(request, contents), worker_id="worker-1")


def test_legacy_policy_still_rejects_max_tokens():
    request = JobRequest.model_validate(payload())
    contents = fixtures.evidence(request)
    terminal_contents(contents)
    with pytest.raises((RuntimeError, ValueError)):
        verify_downloaded_evidence(request, fixtures.downloaded(request, contents), worker_id="worker-1")


@pytest.mark.asyncio
async def test_budget_mode_natural_completion_stays_finished(tmp_path, transport):
    result = await HarborDshTask(fixtures.config(tmp_path, policy=budget_policy())).run()
    assert result.finished is True
    request = transport[0][0]
    receipt = json.loads((tmp_path / "private" / request.job_id / "receipt.json").read_bytes())
    assert receipt["schema"] == "dsh.harbor-verifier-receipt.v2"
    assert receipt["termination_kind"] == "completed"


@pytest.mark.parametrize("mismatch", ["policy", "limits"])
def test_registered_postprocessor_rejects_mismatched_operator_contract(monkeypatch, mismatch):
    from uni_agent.tasks.harbor_dsh import registration

    monkeypatch.setattr(registration, "load_registered_policy", lambda **kwargs: budget_policy())
    kwargs = {"termination_policy": MODE, "budget_limits": LIMITS}
    if mismatch == "policy":
        kwargs["termination_policy"] = "completed-only"
    else:
        kwargs["budget_limits"] = {**LIMITS, "max_generated_tokens": 1}
    with pytest.raises(ValueError, match="policy|limits"):
        registration.validate_registered_trajectories(
            (),
            context={},
            artifact_root="/unused",
            run_id="run-1",
            worker_id="worker-1",
            task_ref={},
            policy_template={},
            instruction="task",
            registration_root="/unused",
            controller_id="controller-1",
            run_spec_sha256="sha256:" + "a" * 64,
            **kwargs,
        )
