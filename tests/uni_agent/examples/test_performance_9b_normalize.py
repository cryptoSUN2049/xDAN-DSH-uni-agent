import copy
import json

import pytest

from examples.performance_9b.normalize import normalize_record


def normalize(raw, **kwargs):
    return normalize_record(raw, "org/source", "abc123", 7, **kwargs)


@pytest.mark.parametrize("field", ["messages", "messages_json"])
@pytest.mark.parametrize("serialized", [False, True])
def test_message_views_preserve_semantics(field, serialized):
    messages = [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "world"}]
    result = normalize({field: json.dumps(messages) if serialized else messages})
    assert result["messages"] == messages
    assert result["supervision"] == {"mode": "all_assistant", "target_message_index": None}


@pytest.mark.parametrize("answer_field", ["answer", "output", "response"])
def test_prompt_reasoning_not_folded_into_answer(answer_field):
    result = normalize({"prompt": "question", "reasoning": "analysis", answer_field: "answer"})
    assert result["messages"][-1] == {"role": "assistant", "content": "answer", "reasoning_content": "analysis"}
    assert result["reasoning_source_field"] == "reasoning"


def test_instruction_input_and_publisher_hint():
    result = normalize({"instruction": "Translate", "input": "hello", "output": "bonjour"}, teacher_hint="Fable")
    assert result["messages"][0]["content"] == "Translate\n\nhello"
    assert result["teacher_evidence"]["status"] == "publisher_claim"


def test_tools_target_and_input_immutability():
    raw = {
        "messages": [
            {"role": "user", "content": "run"},
            {
                "role": "assistant",
                "content": None,
                "reasoning_content": "plan",
                "tool_calls": [
                    {"id": "t1", "type": "function", "function": {"name": "bash", "arguments": '{"cmd":"ls"}'}}
                ],
            },
            {"role": "tool", "tool_call_id": "t1", "tool_id": "original", "content": "file"},
            {"role": "assistant", "content": "done"},
        ],
        "target_message_index": 3,
        "tools_json": '[{"type":"function","function":{"name":"bash"}}]',
    }
    before = copy.deepcopy(raw)
    result = normalize(raw)
    assert raw == before
    assert result["messages"][1]["tool_calls"][0]["function"]["arguments"] == {"cmd": "ls"}
    assert result["messages"][2] == raw["messages"][2]
    assert result["supervision"] == {"mode": "target_message", "target_message_index": 3}
    assert result["tools"][0]["function"]["name"] == "bash"


def test_identity_group_and_conflicting_claims():
    raw = {
        "prompt": "same",
        "answer": "a",
        "task_id": "task1",
        "session_id": "session2",
        "model": "Fable",
        "metadata": {"teacher_model": "Gemini", "domain": "code"},
    }
    a = normalize(raw)
    b = normalize_record({**raw, "answer": "b", "session_id": "other"}, "org/source", "abc123", 8)
    assert a["task_group"] == b["task_group"]
    assert a["id"] != b["id"]
    assert a["prompt_hash"] == b["prompt_hash"]
    assert a["content_hash"] != b["content_hash"]
    assert a["teacher_evidence"]["conflict"] is True
    assert a["domain"] == "code"


@pytest.mark.parametrize(
    "raw",
    [
        {"messages": "{"},
        {"messages": [{"role": "user", "content": "hi"}]},
        {"prompt": "p", "answer": "a", "target_message_index": 0},
        {"prompt": "p", "answer": "a", "target_message_index": True},
        {"prompt": "p", "answer": "a", "target_message_index": 100},
        {"prompt": "p", "answer": "a", "tools": "invalid"},
        {
            "messages": [
                {"role": "user", "content": "p"},
                {"role": "assistant", "tool_calls": [{"function": {"name": "bash", "arguments": "not json"}}]},
            ]
        },
    ],
)
def test_reject_invalid_records(raw):
    with pytest.raises(ValueError):
        normalize(raw)


def test_ambiguous_reasoning_alignment_rejected():
    raw = {
        "messages": [
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": "a"},
            {"role": "assistant", "content": "b"},
        ],
        "reasoning": "unknown turn",
    }
    with pytest.raises(ValueError, match="ambiguous"):
        normalize(raw)
