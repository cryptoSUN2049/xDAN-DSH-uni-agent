import json

import pytest

from examples.performance_9b.verl_sft_export import convert


def row(messages, tools="[]"):
    return {
        "messages": messages,
        "tools_json": tools,
        "source_repo": "test/source",
        "domain": "code",
        "id": "r1",
        "task_group_id": "g1",
        "split": "train",
        "teacher_family": "qwen38",
        "schema_version": "apus-sft-v1",
        "source_revision": "rev",
        "content_sha256": "sha",
        "supervision": {"target_message_index": 1},
    }


def test_export_preserves_multiturn_tool_messages():
    result = convert(
        row(
            [
                {"role": "user", "content": "Run it"},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "function": {"name": "run", "arguments": '{"x": 1}'},
                        }
                    ],
                },
                {"role": "tool", "tool_call_id": "call-1", "content": "ok"},
                {"role": "assistant", "content": "done"},
            ],
            tools=json.dumps([{"type": "function", "function": {"name": "run"}}]),
        )
    )
    messages = json.loads(result["messages"])
    assert messages[1]["tool_calls"][0]["function"]["arguments"] == {"x": 1}
    assert result["enable_thinking"] is False
    assert result["ability"] == "code"


def test_final_assistant_tool_call_can_be_target_action():
    result = convert(
        row(
            [
                {"role": "user", "content": "Run it"},
                {
                    "role": "assistant",
                    "tool_calls": [{"id": "c", "function": {"name": "run", "arguments": {}}}],
                },
            ]
        )
    )
    assert json.loads(result["messages"])[-1]["tool_calls"][0]["id"] == "c"


def test_orphan_tool_result_is_rejected():
    with pytest.raises(ValueError, match="orphan tool result"):
        convert(row([{"role": "user", "content": "x"}, {"role": "tool", "tool_call_id": "missing", "content": "y"}]))
