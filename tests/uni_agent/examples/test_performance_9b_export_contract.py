import json

from examples.performance_9b.export_contract import convert, export


def record(target=None):
    return {
        "id": "r1",
        "task_group": "g1",
        "release_task_group": "g1",
        "source_repo": "x",
        "source_revision": "a" * 40,
        "source_row": 0,
        "teacher_claimed": "gpt-5.6",
        "teacher_family": "gpt56",
        "domain": "code",
        "source_domain": "coding",
        "teacher_evidence": {"status": "row_claim"},
        "source_file_sha256": "b" * 64,
        "content_hash": "c" * 64,
        "messages": [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "ok", "tool_calls": []}],
        "tools": [],
        "supervision": {"mode": "target_message", "target_message_index": target},
    }


def test_contract_columns_and_json_strings():
    out = convert(record(1), "train.jsonl")
    assert out["schema_version"] == "apus-sft-v1"
    assert out["supervision"]["mode"] == "selected_assistant"
    assert out["tools_json"] == "[]"
    assert isinstance(out["messages"][1]["message_id"], str)
    assert out["quality_status"] == "structurally_screened"
    assert "reasoning_policy_unresolved" in out["quality_flags"]
    assert "teacher_identity_unresolved" in out["quality_flags"]
    assert "language_unresolved" in out["quality_flags"]


def test_invalid_tool_is_rejected(tmp_path):
    r = record(1)
    r["messages"][1]["tool_calls"] = [{"id": "c", "function": {"name": "x", "arguments": "{bad"}}]
    inp = tmp_path / "in.jsonl"
    out = tmp_path / "out.jsonl"
    inp.write_text(json.dumps(r) + "\n")
    manifest = export(inp, out, {"x": "train.jsonl"})
    assert manifest["counts"] == {"input": 1, "exported": 0, "rejected": 1}


def test_split_and_nontext_are_rejected():
    r = record(1)
    r["split"] = "dev"
    r["messages"][1]["content"] = ["bad"]
    try:
        convert(r, "x")
    except ValueError as exc:
        assert "text content" in str(exc)
    else:
        raise AssertionError("expected rejection")
