import json

import pytest

from tests.uni_agent.tasks import test_harbor_dsh_executor as fixtures
from tests.uni_agent.tasks.test_harbor_budget_terminal import budget_request, terminal_contents
from uni_agent.tasks.harbor_dsh.execution_outcome import CleanExecutionRejected

pytestmark = [pytest.mark.cpu, pytest.mark.level0]
task_dir = fixtures.task_dir
harness = fixtures.harness


def rewrite_terminal(trial, *, reason="max-tokens", bad_agent=False, bad_reward=False):
    paths = {
        "dsh_trace": trial.dsh_dir / "session.jsonl",
        "dsh_result": trial.dsh_dir / "run.json",
        "harbor_result": trial.paths.result_path,
    }
    contents = {name: path.read_bytes() for name, path in paths.items()}
    terminal_contents(contents, reason=reason)
    helper = json.loads(contents["dsh_result"])
    agent_path = trial.dsh_dir / "agent-result.json"
    agent = json.loads(agent_path.read_bytes())
    agent["finished"] = bad_agent
    agent["info"]["trace_sha256"] = helper["trace_sha256"]
    agent_path.write_text(json.dumps(agent))
    harbor = json.loads(contents["harbor_result"])
    status = harbor["agent_result"]["metadata"]["dsh"]
    status["agent_result_sha256"] = fixtures.digest(agent_path.read_bytes())
    trial.result.agent_result.metadata["dsh"] = status
    (trial.dsh_dir / "status.json").write_text(json.dumps(status))
    contents["harbor_result"] = json.dumps(harbor).encode()
    for name, path in paths.items():
        path.write_bytes(contents[name])
    if bad_reward:
        trial.paths.reward_text_path.write_text("nan")


def test_executor_accepts_only_verified_unfinished_candidate_after_cleanup(task_dir, harness):
    harness.edit = lambda trial: setattr(trial, "rewrite", lambda: rewrite_terminal(trial))
    request = budget_request(fixtures.request_for(task_dir).model_dump(mode="json", by_alias=True))
    result = fixtures.run(request, task_dir)
    assert result.cleanup_confirmed is True
    status = json.loads(result.artifacts["harbor_result"])["agent_result"]["metadata"]["dsh"]
    assert status["finished"] is False
    assert status["finish_reason"] == "max-tokens"
    assert {call.args[0] for call in harness.inventory.await_args_list} == {
        harness.trial.config.trial_name.lower() + "__env",
        harness.trial.config.trial_name.lower() + "__verifier__trial",
    }


@pytest.mark.parametrize("change", [{"reason": "cancelled"}, {"bad_agent": True}, {"bad_reward": True}])
def test_executor_budget_candidate_keeps_auxiliary_and_reward_gates(task_dir, harness, change):
    harness.edit = lambda trial: setattr(trial, "rewrite", lambda: rewrite_terminal(trial, **change))
    request = budget_request(fixtures.request_for(task_dir).model_dump(mode="json", by_alias=True))
    with pytest.raises(CleanExecutionRejected):
        fixtures.run(request, task_dir)
    assert {call.args[0] for call in harness.inventory.await_args_list} == {
        harness.trial.config.trial_name.lower() + "__env",
        harness.trial.config.trial_name.lower() + "__verifier__trial",
    }
