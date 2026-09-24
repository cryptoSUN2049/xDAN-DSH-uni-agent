"""Export screened neutral records to the auditable apus-sft-v1 contract."""

import argparse
import hashlib
import json
from pathlib import Path

SCHEMA = "apus-sft-v1"
FAMILIES = {"qwen38", "fable", "gpt56", "gemini31", "other", "unknown"}
DOMAINS = {"code", "reasoning", "office", "data", "translation", "writing", "general", "unknown"}
SPLITS = {"train", "validation", "quarantine", "excluded"}


def digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def json_text(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def message_id(record_id, index):
    return digest([record_id, index])


def convert_message(record, index, message):
    if not isinstance(message, dict) or message.get("role") not in {"system", "user", "assistant", "tool"}:
        raise ValueError("invalid message role")
    calls = []
    for call in message.get("tool_calls") or []:
        if not isinstance(call, dict) or not isinstance(call.get("function"), dict):
            raise ValueError("invalid tool call")
        function = call["function"]
        name, arguments = function.get("name"), function.get("arguments")
        if not isinstance(call.get("id"), str) or not call["id"] or not isinstance(name, str) or not name:
            raise ValueError("tool call needs id and name")
        if not isinstance(arguments, dict):
            raise ValueError("tool arguments must be an object before export")
        json.loads(json_text(arguments))
        calls.append(
            {"id": call["id"], "type": "function", "function": {"name": name, "arguments": json_text(arguments)}}
        )
    content = message.get("content")
    if content is not None and not isinstance(content, str):
        raise ValueError("v1 only accepts text content")
    return {
        "message_id": message_id(record["id"], index),
        "role": message["role"],
        "content": content,
        "reasoning_content": message.get("reasoning_content"),
        "name": message.get("name"),
        "tool_call_id": message.get("tool_call_id"),
        "tool_calls": calls,
    }


def convert(record, source_file):
    required = {"id", "source_repo", "source_revision", "source_row", "messages", "supervision", "content_hash"}
    missing = required - set(record)
    if missing:
        raise ValueError(f"missing screened fields: {sorted(missing)}")
    family = record.get("teacher_family", "unknown")
    domain = record.get("domain", "unknown")
    split = "validation" if record.get("split") == "dev" else record.get("split", "train")
    if family not in FAMILIES or domain not in DOMAINS or split not in SPLITS:
        raise ValueError("invalid family/domain/split")
    messages = [convert_message(record, i, m) for i, m in enumerate(record["messages"])]
    assistants = [m["message_id"] for m in messages if m["role"] == "assistant"]
    target = record["supervision"].get("target_message_index")
    if target is not None:
        if type(target) is not int or target < 0 or target >= len(messages) or messages[target]["role"] != "assistant":
            raise ValueError("invalid target assistant")
        targets = [messages[target]["message_id"]]
        mode = "selected_assistant"
    else:
        targets, mode = assistants, "all_assistant"
    if not targets:
        raise ValueError("no assistant supervision target")
    tools = record.get("tools")
    if not isinstance(tools, list):
        raise ValueError("tools must be a list")
    provenance = dict(record.get("provenance") or {})
    provenance.update(
        {"source_scoped_group": record.get("task_group"), "release_task_group": record.get("release_task_group")}
    )
    output = {
        "schema_version": SCHEMA,
        "id": record["id"],
        "task_group_id": record.get("release_task_group", record.get("task_group")),
        "split": split,
        "domain": domain,
        "capabilities": [record["source_domain"]] if isinstance(record.get("source_domain"), str) else [],
        "language": "unknown",
        "teacher_model": record.get("teacher_claimed"),
        "teacher_family": family,
        "teacher_evidence_json": json_text(record.get("teacher_evidence") or {}),
        "source_repo": record["source_repo"],
        "source_revision": record["source_revision"],
        "source_file": source_file,
        "source_row": record.get("source_row"),
        "source_record_id": None,
        "source_task_id": None,
        "source_split": None,
        "source_license": None,
        "source_file_sha256": record.get("source_file_sha256"),
        "messages": messages,
        "tools_json": json_text(tools),
        "supervision": {
            "mode": mode,
            "message_ids": targets,
            "reasoning_policy": "include" if any(m.get("reasoning_content") for m in messages) else "unresolved",
        },
        "quality_status": "structurally_screened",
        "quality_flags": [],
        "provenance_json": json_text(provenance),
        "stats_json": json_text({"source_row": record.get("source_row"), "token_count": None, "tokenizer": None}),
        "content_sha256": record["content_hash"],
    }
    flags = output["quality_flags"]
    if output["supervision"]["reasoning_policy"] == "unresolved":
        flags.append("reasoning_policy_unresolved")
    if not record.get("teacher_evidence") or record.get("teacher_evidence", {}).get("status") != "verified":
        flags.append("teacher_identity_unresolved")
    if output["language"] == "unknown":
        flags.append("language_unresolved")
    if output["source_split"] is None:
        flags.append("source_split_unresolved")
    if output["source_license"] is None:
        flags.append("source_license_unresolved")
    if output["source_file"] == "unknown":
        flags.append("source_file_unresolved")
    return output


def export(input_path, output_path, source_files):
    counts = {"input": 0, "exported": 0, "rejected": 0}
    reasons = {}
    with input_path.open() as src, output_path.open("w") as dst:
        for line in src:
            counts["input"] += 1
            try:
                record = json.loads(line)
                source_file = source_files.get(record["source_repo"], "unknown")
                item = convert(record, source_file)
                dst.write(json.dumps(item, ensure_ascii=False) + "\n")
                counts["exported"] += 1
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                counts["rejected"] += 1
                key = type(exc).__name__ + ":" + str(exc)[:120]
                reasons[key] = reasons.get(key, 0) + 1
    return {
        "schema_version": SCHEMA,
        "status": "structurally_screened_not_training_ready",
        "counts": counts,
        "rejection_reasons": reasons,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-files", type=Path, required=True)
    args = parser.parse_args()
    source_files = json.loads(args.source_files.read_text())
    result = export(args.input, args.output, source_files)
    args.output.with_suffix(".manifest.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
