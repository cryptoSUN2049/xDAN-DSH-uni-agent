"""Lossless structural normalization; provenance claims are not verification."""

import copy
import hashlib
import json
import re
from typing import Any


def _json(value: Any, expected: type, field: str) -> Any:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"{field}: invalid JSON") from exc
    if not isinstance(value, expected):
        raise ValueError(f"{field}: expected {expected.__name__}")
    return copy.deepcopy(value)


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _first(mapping: dict, keys: tuple[str, ...]) -> tuple[Any, str | None]:
    for key in keys:
        value = mapping.get(key)
        if value is not None and value != "":
            return value, key
    return None, None


def normalize_record(raw, source_id, source_revision, source_row, teacher_hint=None) -> dict:
    """Return a neutral record without filtering teachers, truncating, or inventing tools.

    Arguments become JSON objects. Existing reasoning fields remain independent;
    top-level reasoning is attached only to an unambiguous sole assistant message.
    Row-level teacher fields are claims, never authentication. ``task_group`` is
    source-scoped; ``prompt_hash`` independently supports cross-source grouping.
    """
    if not isinstance(raw, dict):
        raise ValueError("record must be an object")
    metadata = _json(raw.get("metadata") or {}, dict, "metadata")
    message_data, _ = _first(raw, ("messages", "messages_json"))
    reasoning, reasoning_field = _first(raw, ("reasoning", "reasoning_content"))
    if message_data is not None:
        messages = _json(message_data, list, "messages")
    else:
        prompt, _ = _first(raw, ("prompt", "instruction"))
        answer, _ = _first(raw, ("answer", "output", "response"))
        if not isinstance(prompt, str) or not isinstance(answer, str):
            raise ValueError("missing messages or text prompt/answer")
        extra = raw.get("input")
        if extra:
            if not isinstance(extra, str):
                raise ValueError("input must be text")
            prompt += "\n\n" + extra
        messages = [{"role": "user", "content": prompt}, {"role": "assistant", "content": answer}]
    assistants = []
    for index, message in enumerate(messages):
        if not isinstance(message, dict) or not isinstance(message.get("role"), str):
            raise ValueError("message must have a string role")
        if message["role"] == "assistant":
            assistants.append(index)
        calls = message.get("tool_calls")
        if calls is not None:
            calls = _json(calls, list, "tool_calls")
            for call in calls:
                if not isinstance(call, dict):
                    raise ValueError("tool call must be an object")
                function = call.get("function")
                if function is not None:
                    if not isinstance(function, dict):
                        raise ValueError("tool function must be an object")
                    if "arguments" in function:
                        function["arguments"] = _json(function["arguments"], dict, "tool arguments")
                if "arguments" in call:
                    call["arguments"] = _json(call["arguments"], dict, "tool arguments")
            message["tool_calls"] = calls
    if not assistants:
        raise ValueError("missing assistant message")
    reasoning_origin = None
    if reasoning is not None:
        if not isinstance(reasoning, str):
            raise ValueError("reasoning must be text")
        if len(assistants) != 1:
            raise ValueError("top-level reasoning has ambiguous assistant alignment")
        assistant = messages[assistants[0]]
        existing = assistant.get("reasoning_content")
        if existing is not None and existing != reasoning:
            raise ValueError("conflicting reasoning fields")
        assistant["reasoning_content"] = reasoning
        reasoning_origin = reasoning_field
    target = raw.get("target_message_index", metadata.get("target_message_index"))
    if target is not None and (type(target) is not int or target not in assistants):
        raise ValueError("target_message_index must identify an assistant")
    supervision = {"mode": "target_message" if target is not None else "all_assistant", "target_message_index": target}
    tools_data, _ = _first(raw, ("tools", "tools_json"))
    tools = _json(tools_data, list, "tools") if tools_data is not None else []
    teacher, _ = _first(raw, ("teacher_model", "model"))
    meta_teacher, _ = _first(metadata, ("teacher_model", "model"))
    claims = []
    for value, field in [
        (mapping.get(key), prefix + key)
        for mapping, prefix in ((raw, ""), (metadata, "metadata."))
        for key in ("teacher_model", "model")
    ]:
        if value is not None:
            if not isinstance(value, str):
                raise ValueError("teacher identity must be text")
            claims.append({"field": field, "value": value})
    if teacher is None:
        teacher = meta_teacher
    status = "row_claim" if teacher is not None else "unknown"
    if teacher is None and teacher_hint is not None:
        if not isinstance(teacher_hint, str):
            raise ValueError("teacher_hint must be text")
        teacher, status = teacher_hint, "publisher_claim"
        claims.append({"field": "teacher_hint", "value": teacher_hint})
    group, _ = _first(raw, ("source_trajectory_id", "task_id", "task", "session_id"))
    if group is None:
        group, _ = _first(metadata, ("source_trajectory_id", "task_id", "task", "session_id"))
    prompt = next((m.get("content") for m in messages if m["role"] == "user"), None)
    if prompt is None:
        raise ValueError("missing user content for task identity")
    normalized_prompt = re.sub(r"\s+", " ", prompt).strip() if isinstance(prompt, str) else prompt
    record = {
        "id": _hash([source_id, source_revision, source_row]),
        "task_group": _hash([source_id, group]) if group is not None else _hash([source_id, normalized_prompt]),
        "source_repo": source_id,
        "source_revision": source_revision,
        "source_row": source_row,
        "teacher_claimed": teacher,
        "teacher_evidence": {"status": status, "claims": claims, "conflict": len({c["value"] for c in claims}) > 1},
        "domain": raw.get("domain", metadata.get("domain")),
        "messages": messages,
        "tools": tools,
        "supervision": supervision,
        "prompt_hash": _hash(normalized_prompt),
        "content_hash": _hash([messages, tools, supervision]),
    }
    if reasoning_origin:
        record["reasoning_source_field"] = reasoning_origin
    return record
