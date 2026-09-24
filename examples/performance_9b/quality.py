"""Conservative provenance classification and non-mutating SFT quality flags.

Cyrillic detection is a review heuristic, NOT Russian language identification.
Names or brief quotations alone do not trigger it; Ukrainian and other Cyrillic
languages may trigger review. The caller decides quarantine/exclusion policy.
"""

import json
import re

_TEACHERS = {
    "qwen38": r"(?<![a-z0-9])qwen[-_ ]?3\.8(?![0-9.])",
    "fable": r"(?<![a-z0-9])fable(?:[-_ ]?5(?:\.\d+)?)?(?![a-z0-9.])",
    "gpt56": r"(?<![a-z0-9])gpt[-_ ]?5\.6(?![0-9.])",
    "gemini31": r"(?<![a-z0-9])gemini[-_ ]?3\.1(?![0-9.])",
}


def classify_teacher(value):
    """Classify a claimed model string; classification is not attestation."""
    if not isinstance(value, str) or value.strip().lower() in {"", "unknown", "none", "null"}:
        return "unknown"
    matches = [name for name, pattern in _TEACHERS.items() if re.search(pattern, value, re.I)]
    return matches[0] if len(matches) == 1 else ("unknown" if matches else "other")


def _text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(_text(item) for item in value)
    if isinstance(value, dict):
        return "\n".join(_text(value.get(key)) for key in ("text", "content", "thinking"))
    return ""


def inspect_record(record):
    """Return deterministic unique flags without changing data or executing tools."""
    messages = record.get("messages") if isinstance(record, dict) else None
    if not isinstance(messages, list) or not messages or any(not isinstance(m, dict) for m in messages):
        return ["invalid_messages"]
    flags, pending, seen = set(), {}, set()
    supervision = record.get("supervision") or {}
    target = supervision.get("target_message_index")
    final_prediction = (
        supervision.get("mode") == "target_message"
        and type(target) is int
        and target == len(messages) - 1
        and messages[target].get("role") == "assistant"
    )
    for index, message in enumerate(messages):
        text = "\n".join(_text(message.get(k)) for k in ("content", "reasoning_content", "reasoning"))
        words = re.findall(r"[\u0400-\u052f]+", text)
        if len(words) >= 6 and sum(map(len, words)) >= 40:
            flags.add("cyrillic_language_review")
        calls = message.get("tool_calls") or []
        if not isinstance(calls, list):
            flags.add("invalid_tool_calls")
            calls = []
        if message.get("role") == "assistant":
            if not text.strip() and not calls:
                flags.add("empty_assistant")
            depth = 0
            for tag in re.findall(r"</?think>", text):
                depth += 1 if tag == "<think>" else -1
                if depth < 0 or depth > 1:
                    flags.add("unclosed_think")
            if depth:
                flags.add("unclosed_think")
        for call in calls:
            if not isinstance(call, dict) or not isinstance(call.get("function"), dict):
                flags.add("invalid_tool_calls")
                continue
            function = call["function"]
            if function.get("name") == "unknown_tool":
                flags.add("unknown_tool")
            if not isinstance(function.get("name"), str) or not function.get("name"):
                flags.add("invalid_tool_name")
            arguments = function.get("arguments")
            try:
                parsed = json.loads(arguments) if isinstance(arguments, str) else arguments
                if not isinstance(parsed, dict):
                    flags.add("invalid_tool_arguments")
            except (TypeError, ValueError):
                flags.add("invalid_tool_arguments")
            call_id = call.get("id")
            if not isinstance(call_id, str) or not call_id:
                flags.add("missing_tool_call_id")
            else:
                if call_id in seen:
                    flags.add("duplicate_tool_call_id")
                seen.add(call_id)
                pending[call_id] = index
        if message.get("role") == "tool":
            call_id = message.get("tool_call_id")
            if not isinstance(call_id, str) or call_id not in pending:
                flags.add("orphan_tool_result")
            else:
                del pending[call_id]
    if any(not final_prediction or origin != target for origin in pending.values()):
        flags.add("missing_tool_result")
    return sorted(flags)
