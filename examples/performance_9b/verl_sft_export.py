"""Export the neutral APUS contract to VERL MultiTurnSFTDataset parquet.

The neutral contract remains the audit record.  This exporter only selects the
columns consumed by VERL's ``MultiTurnSFTDataset`` and keeps audit metadata in
scalar JSON columns.  VERL itself builds the token-level loss mask from the
messages and tokenizer chat template.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _tool_call(call):
    function = call.get("function") or {}
    arguments = function.get("arguments")
    if isinstance(arguments, str):
        arguments = json.loads(arguments)
    if not isinstance(arguments, dict):
        raise ValueError("tool call arguments must be an object")
    return {
        "id": call.get("id"),
        "type": "function",
        "function": {"name": function.get("name"), "arguments": arguments},
    }


def _message(message):
    role = message.get("role")
    if role not in {"system", "user", "assistant", "tool"}:
        raise ValueError(f"invalid role: {role}")
    output = {"role": role, "content": message.get("content")}
    if message.get("reasoning_content") is not None:
        output["reasoning_content"] = message["reasoning_content"]
    if message.get("name") is not None:
        output["name"] = message["name"]
    if message.get("tool_call_id") is not None:
        output["tool_call_id"] = message["tool_call_id"]
    calls = message.get("tool_calls") or []
    if calls:
        if role != "assistant":
            raise ValueError("tool_calls are only valid on assistant messages")
        output["tool_calls"] = [_tool_call(call) for call in calls]
    return output


def _validate_messages(messages):
    if not isinstance(messages, list) or not messages:
        raise ValueError("messages must be a non-empty list")
    converted = [_message(item) for item in messages]
    pending = set()
    for item in converted:
        for call in item.get("tool_calls", []):
            call_id = call.get("id")
            if not call_id:
                raise ValueError("tool call id is required")
            pending.add(call_id)
        if item["role"] == "tool":
            call_id = item.get("tool_call_id")
            if not call_id or call_id not in pending:
                raise ValueError("orphan tool result")
            pending.remove(call_id)
    # A final assistant tool call may be the target action and have no result.
    if pending and converted[-1]["role"] != "assistant":
        raise ValueError("unfinished tool call before non-assistant termination")
    if not any(item["role"] == "assistant" for item in converted):
        raise ValueError("at least one assistant message is required")
    return converted


def convert(record):
    messages = _validate_messages(record["messages"])
    tools = json.loads(record.get("tools_json") or "[]")
    if not isinstance(tools, list):
        raise ValueError("tools_json must contain a list")
    return {
        # Keep dynamic tool arguments JSON-encoded in Parquet.  Arrow cannot
        # represent a column of heterogeneous nested structs reliably; the
        # APUS VERL dataset adapter decodes these fields before tokenization.
        "messages": _json(messages),
        "tools": _json(tools),
        "enable_thinking": any(item.get("reasoning_content") for item in messages),
        "data_source": record.get("source_repo", "unknown"),
        "ability": record.get("domain", "unknown"),
        "record_id": record.get("id"),
        "task_group_id": record.get("task_group_id"),
        "split": record.get("split", "train"),
        "teacher_family": record.get("teacher_family", "unknown"),
        "audit_json": _json(
            {
                "schema_version": record.get("schema_version"),
                "source_revision": record.get("source_revision"),
                "content_sha256": record.get("content_sha256"),
                "supervision": record.get("supervision", {}),
            }
        ),
    }


def export(input_path: Path, output_path: Path):
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover - exercised on the CPU pod
        raise RuntimeError("pyarrow is required for VERL parquet export") from exc

    rows, rejected = [], {}
    with input_path.open() as source:
        for line_number, line in enumerate(source, 1):
            try:
                rows.append(convert(json.loads(line)))
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                key = f"{type(exc).__name__}:{str(exc)[:120]}"
                rejected[key] = rejected.get(key, 0) + 1
    if not rows:
        raise ValueError("no VERL rows exported")
    table = pa.Table.from_pylist(rows)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, output_path, compression="zstd")
    return {
        "schema_version": "apus-sft-v1-verl",
        "input": sum(1 for _ in input_path.open()),
        "exported": len(rows),
        "rejected": sum(rejected.values()),
        "rejection_reasons": rejected,
        "columns": table.column_names,
        "training_ready": False,
        "note": "Format export only; tokenizer and loss-mask smoke test is required.",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = export(args.input, args.output)
    args.output.with_suffix(".manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    main()
