"""Quality flags must not fabricate provenance or repair broken tool traces."""

import importlib.util
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parents[3] / "examples/performance_9b/quality.py"
spec = importlib.util.spec_from_file_location("performance_9b_quality", PATH)
quality = importlib.util.module_from_spec(spec)


def load():
    spec.loader.exec_module(quality)
    return quality


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Qwen/Qwen3.8-27B", "qwen38"),
        ("qwen3.8-max-preview", "qwen38"),
        ("claude-fable-5.1", "fable"),
        ("Fable5", "fable"),
        ("gpt-5.6-sol", "gpt56"),
        ("Gemini-3.1-Pro", "gemini31"),
        ("qwen3.7", "other"),
        ("qwen3.80", "other"),
        ("gpt5.60", "other"),
        ("gpt5.5", "other"),
        ("Mythos5", "other"),
        ("Fable GPT5.6 mixture", "unknown"),
        (None, "unknown"),
        ("unknown", "unknown"),
    ],
)
def test_teacher(value, expected):
    assert load().classify_teacher(value) == expected


def call(name="bash", args='{"command":"pwd"}', call_id="a"):
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [{"id": call_id, "function": {"name": name, "arguments": args}}],
    }


def inspect(messages):
    return load().inspect_record({"messages": messages})


def test_valid_tool_loop():
    assert inspect([call(), {"role": "tool", "tool_call_id": "a", "content": "/tmp"}]) == []


def test_broken_tools_are_flagged_not_repaired():
    flags = inspect([call("unknown_tool", "malformed")])
    assert {"unknown_tool", "invalid_tool_arguments", "missing_tool_result"} <= set(flags)


def test_tool_ids():
    assert "duplicate_tool_call_id" in inspect([call(), call()])
    assert "orphan_tool_result" in inspect([call(), {"role": "tool", "tool_call_id": "b", "content": "x"}])
    assert "missing_tool_call_id" in inspect([call(call_id=None)])


def test_text_tool_transcript_is_not_parsed_as_structured_calls():
    assert inspect([{"role": "assistant", "content": "<tool_call>bash('pwd')</tool_call>"}]) == []
    assert inspect([{"role": "tool", "content": "legacy transcript"}]) == ["orphan_tool_result"]


def test_assistant_and_thinking():
    assert "empty_assistant" in inspect([{"role": "assistant", "content": " "}])
    assert "unclosed_think" in inspect([{"role": "assistant", "content": "<think>unfinished"}])
    assert inspect([{"role": "assistant", "content": "<think>done</think>answer"}]) == []


def test_cyrillic_is_review_not_russian_language_claim():
    assert inspect([{"role": "assistant", "content": "Author: Александр Пушкин."}]) == []
    for field in ["content", "reasoning", "reasoning_content"]:
        message = {
            "role": "assistant",
            "content": "Answer",
            field: "Це українська мова яка має власні особливості та потребує уважного розгляду",
        }
        flags = inspect([message])
        assert "cyrillic_language_review" in flags
        assert "russian_text_detected" not in flags


def test_malformed_record():
    assert "invalid_messages" in load().inspect_record({"messages": None})


def test_next_action_final_tool_target_does_not_require_future_result():
    record = {"messages": [call()], "supervision": {"mode": "target_message", "target_message_index": 0}}
    assert load().inspect_record(record) == []
    record["messages"] = [call(call_id="history"), call(call_id="target")]
    record["supervision"]["target_message_index"] = 1
    assert "missing_tool_result" in load().inspect_record(record)


def test_next_action_exception_requires_actual_final_message_and_integer_index():
    record = {
        "messages": [call(), {"role": "assistant", "content": "done"}],
        "supervision": {"mode": "target_message", "target_message_index": 0},
    }
    assert "missing_tool_result" in load().inspect_record(record)
    record = {"messages": [call()], "supervision": {"mode": "target_message", "target_message_index": False}}
    assert "missing_tool_result" in load().inspect_record(record)


def test_null_tool_fields_are_safe():
    assert (
        load().inspect_record({"messages": [{"role": "assistant", "content": "ok", "tool_calls": None}], "tools": None})
        == []
    )


def test_orphan_tool_without_any_calls_is_rejected():
    record = {
        "messages": [
            {"role": "user", "content": "run"},
            {"role": "tool", "tool_call_id": "missing", "content": "ok"},
            {"role": "assistant", "content": "done"},
        ]
    }
    assert "orphan_tool_result" in load().inspect_record(record)
