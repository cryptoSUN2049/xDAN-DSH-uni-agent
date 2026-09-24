import json

from examples.performance_9b.export_contract import convert
from examples.performance_9b.repair_and_gate import annotate
from tests.uni_agent.examples.test_performance_9b_export_contract import record


def test_source_claims_do_not_become_verified_or_ready():
    item = convert(record(1), "train.jsonl")
    result = annotate(
        item,
        {
            "teacher_attested": True,
            "teacher_model": "gpt-5.6",
            "teacher_claims": ["gpt-5.6"],
            "language": "en",
            "source_split": "train",
            "source_license": "cc-by-4.0",
        },
    )
    assert result["quality_status"] == "unreviewed"
    assert result["language"] == "en"
    assert json.loads(result["teacher_evidence_json"])["status"] == "row_claim"
    assert "teacher_provenance_review_pending" in result["quality_flags"]
    assert "semantic_quality_pending" in result["quality_flags"]


def test_missing_reasoning_is_not_resolved_by_assumption():
    result = annotate(convert(record(1), "train.jsonl"), {})
    assert result["supervision"]["reasoning_policy"] == "unresolved"
    assert "reasoning_policy_unresolved" in result["quality_flags"]


def test_markup_does_not_automatically_resolve_mask():
    result = annotate(convert(record(1), "train.jsonl"), {"thinking_markup": True})
    assert result["supervision"]["reasoning_policy"] == "unresolved"
    assert "thinking_markup_mask_review" in result["quality_flags"]


def test_missing_source_and_heldout_remain_blocked():
    result = annotate(convert(record(1), "train.jsonl"), None)
    assert "source_row_not_found" in result["quality_flags"]
    result = annotate(convert(record(1), "train.jsonl"), {"source_split": "test"})
    assert "source_split_not_train" in result["quality_flags"]


def test_next_action_tool_call_may_end_at_supervision_target():
    item = record(1)
    item["messages"][1]["tool_calls"] = [
        {"id": "call-1", "type": "function", "function": {"name": "exec", "arguments": {"source": "x"}}}
    ]
    result = annotate(
        convert(item, "train.jsonl"),
        {
            "teacher_attested": True,
            "teacher_model": "gpt-5.6",
            "teacher_claims": ["gpt-5.6"],
            "language": "en",
            "source_split": "train",
            "source_license": "cc-by-4.0",
        },
    )
    assert "missing_tool_result" not in result["quality_flags"]


def test_language_script_conflict_is_hard_quarantined():
    item = record(1)
    item["messages"][0]["content"] = "请处理这个任务 " * 40
    result = annotate(
        convert(item, "train.jsonl"),
        {
            "teacher_attested": True,
            "teacher_model": "gpt-5.6",
            "teacher_claims": ["gpt-5.6"],
            "language": "en",
            "source_split": "train",
            "source_license": "cc-by-4.0",
        },
    )
    assert "language_content_conflict:cjk" in result["quality_flags"]
