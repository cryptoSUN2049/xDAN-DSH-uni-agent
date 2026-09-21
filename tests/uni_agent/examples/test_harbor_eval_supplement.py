import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "supplement", Path(__file__).resolve().parents[3] / "examples/harbor_opd_rl/eval_supplement.py"
)
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def evidence():
    return {
        "process_exit": 0,
        "checkpoint_loaded": True,
        "expected_n": 4,
        "sample_count_mismatches": {"tasks/a": 3},
        "infra_incomplete": {"a": 1},
        "unexpected_task_ids": [],
    }


def test_plan_only_missing_infra():
    assert mod.plan_missing(evidence(), {"a": [0, 0, 1], "b": [0, 0, 0, 0]}) == {1: ["tasks/a"]}


@pytest.mark.parametrize(
    "change",
    [{"process_exit": 1}, {"checkpoint_loaded": False}, {"infra_incomplete": {}}, {"unexpected_task_ids": ["tasks/c"]}],
)
def test_refuses_noninfra_or_unverified(change):
    with pytest.raises(ValueError):
        mod.plan_missing(evidence() | change, {"a": [0, 0, 1]})


def test_merge_preserves_zero_scores_and_exact_size():
    assert mod.merge_results({"a": [0, 0, 1], "b": [0] * 4}, {"a": [1]}, 4) == {"a": [0, 0, 1, 1], "b": [0] * 4}
    with pytest.raises(ValueError):
        mod.merge_results({"a": [0, 0, 1]}, {"a": [1, 1]}, 4)


def test_link_logs_preserves_source_and_is_discoverable(tmp_path):
    source = tmp_path / "source"
    original = source / "agent-logs/session/task.log"
    original.parent.mkdir(parents=True)
    original.write_text("original evidence")
    target = tmp_path / "aggregate/agent-logs/0"
    mod.link_logs(source, target)
    discovered = list((tmp_path / "aggregate/agent-logs").rglob("task.log"))
    assert len(discovered) == 1
    assert discovered[0].read_text() == original.read_text() == "original evidence"


def test_merge_adds_task_with_all_samples_missing():
    assert mod.merge_results({"b": [0] * 4}, {"a": [0, 1, 0, 1]}, 4) == {"b": [0] * 4, "a": [0, 1, 0, 1]}


def test_coverage_adjusted_framework_rate_counts_missing_as_zero():
    assert mod.coverage_adjusted_rate({"a": [0, 0, 1], "b": [1, 0, 0, 0]}, 2, 4) == 0.25
    assert mod.coverage_adjusted_rate({"a": [0, 0, 1, 1], "b": [1, 0, 0, 0]}, 2, 4) == 0.375


def test_base_identity_allows_no_checkpoint_and_binds_model(tmp_path):
    model = tmp_path / "model"
    model.mkdir()
    (model / "config.json").write_text("{}")
    identity = mod.model_identity({"resume_from": ""}, {"resume_from": "", "model_path": str(model)}, "")
    assert identity["kind"] == "base"
    assert identity["model_path"] == str(model)
    with pytest.raises(ValueError):
        mod.model_identity({"resume_from": ""}, {"resume_from": "/wrong", "model_path": str(model)}, "")
