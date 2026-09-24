"""Lossless adapter from apus-sft-v1 messages to the Qwen3.5 template shape."""

import copy
import json


def to_qwen_template_messages(messages):
    """Convert canonical function calls without changing the mother record.

    Qwen3.5's native template expects assistant tool calls as
    ``{name, arguments: object}``, while apus-sft-v1 intentionally stores the
    wire-compatible OpenAI shape and JSON-string arguments. IDs remain in the
    mother record and are retained in a private side map by the exporter.
    """
    converted = []
    call_ids = {}
    for message in messages:
        item = copy.deepcopy(message)
        calls = []
        for call in item.get("tool_calls") or []:
            function = call["function"]
            arguments = function["arguments"]
            if isinstance(arguments, str):
                arguments = json.loads(arguments)
            if not isinstance(arguments, dict):
                raise ValueError("Qwen template arguments must be an object")
            calls.append({"name": function["name"], "arguments": arguments})
            call_ids[function["name"]] = call["id"]
        if calls:
            item["tool_calls"] = calls
        converted.append(item)
    return converted, call_ids
