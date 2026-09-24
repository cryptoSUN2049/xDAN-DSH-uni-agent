import json

from examples.performance_9b.export_contract import convert
from examples.performance_9b.qwen_chat_adapter import to_qwen_template_messages
from tests.uni_agent.examples.test_performance_9b_export_contract import record


def test_qwen_adapter_changes_only_tool_wire_shape():
    item = record(1)
    item["messages"][1]["tool_calls"] = [
        {"id": "call-1", "type": "function", "function": {"name": "exec", "arguments": {"source": "x"}}}
    ]
    canonical = convert(item, "train.jsonl")
    messages, ids = to_qwen_template_messages(canonical["messages"])
    assert messages[1]["tool_calls"] == [{"name": "exec", "arguments": {"source": "x"}}]
    assert ids == {"exec": "call-1"}
    assert json.loads(canonical["messages"][1]["tool_calls"][0]["function"]["arguments"]) == {"source": "x"}
