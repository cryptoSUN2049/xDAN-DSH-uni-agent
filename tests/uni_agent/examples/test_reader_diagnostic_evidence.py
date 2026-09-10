from unittest.mock import patch

import pytest

from examples.dsh.capabilities.memory_verifier import loads
from tests.uni_agent.examples.test_work_state_stage import execute_synthetic_stage, inputs, prep

__all__ = ["inputs"]


def run_stage(inputs, *, unfinished=False, unsafe=False):
    from tests.uni_agent.tasks.test_dsh_evolution_verifier import _call, _result
    from uni_agent.agents.base import AgentResult

    spec = prep(inputs)

    def agent_result(**kwargs):
        return AgentResult(**{**kwargs, "finished": not unfinished})

    def events(fixture, original):
        return original + (
            [_call("unsafe", "bash", {"command": "true"}, seq=99), _result("unsafe", "")] if unsafe else []
        )

    with patch("uni_agent.agents.base.AgentResult", side_effect=agent_result):
        execution = execute_synthetic_stage(spec, bad_memory=True, transform_events=events)
    execution.trajectories[0].finished = execution.task_result.finished
    return spec, execution


@pytest.mark.parametrize("unfinished,unsafe", [(False, False), (True, False), (False, True)])
def test_original_zero_and_negative_receipts_are_diagnostic_only(inputs, unfinished, unsafe):
    from examples.dsh.capabilities.reader_diagnostic_evidence import audit_diagnostic_stage

    spec, execution = run_stage(inputs, unfinished=unfinished, unsafe=unsafe)
    before = next(spec.result_root.rglob("verifier-receipt.json")).read_bytes()
    result = audit_diagnostic_stage(spec, execution)
    assert result["reward"] == 0
    assert result["finished"] is (not unfinished)
    assert result["eligible"] is (not unfinished and not unsafe)
    assert result["training_consumed"] is False
    assert result["model_tokens"] == 1
    assert result["receipt_id"] == loads(before)["receipt_id"]
    assert next(spec.result_root.rglob("verifier-receipt.json")).read_bytes() == before


@pytest.mark.parametrize(
    "kind",
    [
        "receipt",
        "trace",
        "metadata",
        "prompt",
        "fixture",
        "context",
        "runtime",
        "mask",
        "token",
        "logprob",
        "reward",
        "fake_b",
    ],
)
def test_corruption_cannot_be_reported_as_valid_diagnostics(inputs, kind):
    from examples.dsh.capabilities.reader_diagnostic_evidence import audit_diagnostic_stage

    spec, execution = run_stage(inputs)
    t = execution.trajectories[0]
    if kind == "receipt":
        next(spec.result_root.rglob("verifier-receipt.json")).write_text("{}")
    elif kind == "trace":
        next(spec.trace_root.rglob("session.jsonl")).write_text("{}")
    elif kind == "metadata":
        spec.metadata["task_id"] = "fake"
    elif kind == "prompt":
        spec.raw_prompt[0]["content"] = "tampered"
    elif kind == "fixture":
        spec.fixture_path.write_text("{}")
    elif kind == "context":
        execution.context["group_uid"] = "fake"
    elif kind == "runtime":
        spec.operator.runtime_executable.write_bytes(b"changed")
    elif kind == "mask":
        t.response_mask = [0]
    elif kind == "token":
        t.response_ids = [-1]
    elif kind == "logprob":
        t.response_logprobs = [float("nan")]
    elif kind == "reward":
        t.reward_score = 1
    elif kind == "fake_b":
        execution.trajectories.clear()
    with pytest.raises(ValueError):
        audit_diagnostic_stage(spec, execution)


@pytest.mark.parametrize("tamper", [False, True])
def test_reader_counts_and_output_snapshot_binding(inputs, tamper):
    from pathlib import Path

    from examples.dsh.capabilities.reader_diagnostic_evidence import audit_diagnostic_stage
    from examples.dsh.capabilities.work_state.stage import freeze_and_prepare_reader
    from tests.uni_agent.tasks.test_dsh_evolution_verifier import _call, _result

    writer = prep(inputs)
    reader = freeze_and_prepare_reader(writer, execute_synthetic_stage(writer), reader_gateway_session_id="GB")

    def with_read(fixture, events):
        path = str(Path(fixture["memory_root"]) / "index.md")
        return [
            _call("read", "str_replace_editor", {"command": "view", "path": path}, seq=99),
            _result("read", "index"),
        ] + events

    execution = execute_synthetic_stage(reader, bad_memory=True, transform_events=with_read)
    if tamper:
        fixture = loads(reader.fixture_path.read_bytes())
        (Path(fixture["output_root"]) / "config.json").write_text('{"different":true}')
        with pytest.raises(ValueError):
            audit_diagnostic_stage(reader, execution)
    else:
        result = audit_diagnostic_stage(reader, execution)
        assert result["reward"] == 0 and result["eligible"] is True
        assert result["memory_view_attempt_count"] == result["index_view_attempt_count"] == 1
        assert result["tool_call_count"] == 3


@pytest.mark.parametrize("field,value", [("eligible", False), ("finished", False), ("reward", 1)])
def test_rehashed_forged_receipt_still_requires_original_verifier_score(inputs, field, value):
    from examples.dsh.capabilities.memory_verifier import canonical, sha
    from examples.dsh.capabilities.reader_diagnostic_evidence import audit_diagnostic_stage
    from uni_agent.tasks.base import build_reward_info

    spec, execution = run_stage(inputs)
    path = next(spec.result_root.rglob("verifier-receipt.json"))
    receipt = loads(path.read_bytes())
    receipt[field] = value
    receipt["receipt_id"] = sha(canonical({k: v for k, v in receipt.items() if k != "receipt_id"}))
    path.write_bytes(canonical(receipt))
    result = execution.task_result
    result.reward_info["dsh"]["receipt_sha256"] = receipt["receipt_id"]
    if field == "eligible":
        result.reward_info["dsh"]["eligible"] = value
    elif field == "finished":
        result.finished = value
        execution.trajectories[0].finished = value
    else:
        result.reward = result.verifier_reward = value
        execution.trajectories[0].reward_score = value
    execution.trajectories[0].extra_fields["dsh_reward_info"] = build_reward_info(result)
    with pytest.raises(ValueError, match="rescored"):
        audit_diagnostic_stage(spec, execution)


def test_failed_view_of_missing_index_counts_attempt_only(inputs):
    from pathlib import Path

    from examples.dsh.capabilities.reader_diagnostic_evidence import audit_diagnostic_stage
    from examples.dsh.capabilities.work_state.stage import freeze_and_prepare_reader
    from tests.uni_agent.tasks.test_dsh_evolution_verifier import _call, _result

    writer = prep(inputs)
    reader = freeze_and_prepare_reader(
        writer, execute_synthetic_stage(writer, bad_memory=True), reader_gateway_session_id="GB"
    )

    def failed_view(fixture, events):
        path = Path(fixture["memory_root"]) / "index.md"
        assert not path.exists()
        return [
            _call("missing-index", "str_replace_editor", {"command": "view", "path": str(path)}, seq=99),
            _result("missing-index", "No such file", error=True),
        ] + events

    execution = execute_synthetic_stage(reader, bad_memory=True, transform_events=failed_view)
    result = audit_diagnostic_stage(reader, execution)
    assert result["memory_view_attempt_count"] == result["index_view_attempt_count"] == 1
    assert result["read_metric_scope"] == "view attempts, including failed calls; not evidence of successful reads"
    assert "memory_read_count" not in result and "index_read_count" not in result
