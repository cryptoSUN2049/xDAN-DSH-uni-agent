"""Prepare offline scripted demonstrations from trusted, hash-bound real DSH evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from examples.dsh.capability_tasks.log_tool import verifier
from examples.dsh.capability_tasks.log_tool.task_bundle import CODE_PATHS
from examples.dsh.evolution_v3_live import _bundle_identity

TOKENIZER_REVISION = "1cfa9a7208912126459214e8b04321603b3df60c"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def digest(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def parse(raw):
    return verifier._json(raw)


def verifier_bundle_digest():
    return _bundle_identity(CODE_PATHS, repository_root=Path(__file__).resolve().parents[4])["sha256"]


def normalize_message(message):
    require(isinstance(message, dict), "Invalid message")
    role = message.get("role")
    require(role in {"system", "user", "assistant", "tool"}, "Unsupported role")
    allowed = {"role", "content", "tool_calls", "tool_call_id", "reasoning_content"}
    require(not (set(message) - allowed), "Unsupported message fields")
    require(not message.get("reasoning_content"), "Thinking content is unsupported")
    content = message.get("content")
    require(content is None or isinstance(content, str), "Unsupported non-text content")
    result = {"role": role, "content": content or ""}
    if "tool_call_id" in message:
        require(role == "tool" and isinstance(message["tool_call_id"], str), "Invalid tool result identity")
        result["tool_call_id"] = message["tool_call_id"]
    if "tool_calls" in message:
        calls = message["tool_calls"]
        require(role == "assistant" and isinstance(calls, list) and calls, "Invalid assistant calls")
        converted = []
        for call in calls:
            require(set(call) == {"id", "type", "function"} and call["type"] == "function", "Unsupported call")
            function = call["function"]
            require(set(function) == {"name", "arguments"}, "Unsupported function")
            args = parse(function["arguments"]) if isinstance(function["arguments"], str) else function["arguments"]
            require(isinstance(args, dict), "Arguments must be object")
            require(
                isinstance(call["id"], str) and call["id"] and isinstance(function["name"], str), "Invalid call ID/name"
            )
            converted.append(
                {"id": call["id"], "type": "function", "function": {"name": function["name"], "arguments": args}}
            )
        result["tool_calls"] = converted
    require(role != "tool" or "tool_call_id" in result, "Missing tool call identity")
    return result


def event_target(event):
    data = event["data"]
    message = data["message"]
    require(message["role"] == "assistant", "Target must be assistant")
    text, calls = [], []
    for block in message["content"]:
        if block["type"] == "text":
            require(isinstance(block["text"], str), "Invalid text")
            text.append(block["text"])
        elif block["type"] == "tool-call":
            calls.append(
                {
                    "id": block["id"],
                    "type": "function",
                    "function": {"name": block["name"], "arguments": block["arguments"]},
                }
            )
        else:
            raise ValueError("Unsupported assistant block")
    require(not (text and calls), "Mixed ordered text/tool blocks are unsupported")
    target = {"role": "assistant", "content": "".join(text)}
    if calls:
        target["tool_calls"] = calls
    finishes = [
        part["chunk"]["reason"]["kind"]
        for part in data.get("stream", [])
        if part.get("chunk", {}).get("type") == "finish"
    ]
    require(finishes == ["tool-calls" if calls else "stop"], "Incomplete or failed assistant attempt")
    require(text or calls, "Empty assistant")
    return normalize_message(target)


def associate_decisions(requests, events, initial_prompt):
    require(isinstance(requests, list) and requests and isinstance(events, list) and events, "Empty evidence")
    seqs = [event["seq"] for event in events]
    require(all(type(seq) is int for seq in seqs) and seqs == sorted(set(seqs)), "Invalid event sequence")
    require(not any(event.get("surfaceOp") not in {None, "append"} for event in events), "Unsupported context edit")
    assistants = [event for event in events if event["type"] == "assistant/message"]
    require(len(assistants) == len(requests), "Ambiguous request/response count")
    turns = [event for event in events if event["type"] == "turn/end"]
    require(len(turns) == 1 and turns[0]["data"]["reason"] == {"kind": "completed"}, "Incomplete session")
    require(turns[0]["seq"] > assistants[-1]["seq"], "Invalid terminal order")
    user = [event["data"] for event in events if event["type"] == "user/message"]
    require(
        len(user) == 1 and user[0]["content"] == [{"type": "text", "text": initial_prompt}], "Prompt event mismatch"
    )
    normalized = []
    for request in requests:
        messages = [normalize_message(message) for message in request["messages"]]
        tools = request.get("tools")
        require(tools is None or isinstance(tools, list), "Unsupported tools")
        normalized.append({"messages": messages, "tools": tools})
    first = normalized[0]["messages"]
    require(
        len(first) in {1, 2} and first[-1] == {"role": "user", "content": initial_prompt}, "Initial request mismatch"
    )
    require(len(first) == 1 or first[0]["role"] == "system", "Unsupported initial history")
    rows, seen_calls, coordinates = [], set(), []
    for index, event in enumerate(assistants):
        data = event["data"]
        coordinates.append((data["turn"], data["step"]))
        target = event_target(event)
        boundary = assistants[index + 1]["seq"] if index + 1 < len(assistants) else turns[0]["seq"]
        between = [item for item in events if event["seq"] < item["seq"] < boundary]
        calls = target.get("tool_calls", [])
        available = normalized[index]["tools"] or []
        names = [tool.get("function", {}).get("name") for tool in available]
        require(
            all(
                tool.get("type") == "function" and isinstance(name, str)
                for tool, name in zip(available, names, strict=True)
            ),
            "Unsupported tool schema",
        )
        require(len(names) == len(set(names)), "Duplicate tool schema name")
        require(all(call["function"]["name"] in names for call in calls), "Target tool absent from request schema")
        actual_calls = [item for item in between if item["type"] == "tool/call"]
        actual_results = [item for item in between if item["type"] == "tool/result"]
        require(len(calls) == len(actual_calls) == len(actual_results), "Call/result count mismatch")
        results = []
        for call, actual, result in zip(calls, actual_calls, actual_results, strict=True):
            call_id = call["id"]
            require(call_id not in seen_calls, "Repeated call identity")
            seen_calls.add(call_id)
            values = actual["data"]
            require((values["turn"], values["step"]) == coordinates[-1], "Call coordinates mismatch")
            require(
                values["callId"] == call_id
                and values["name"] == call["function"]["name"]
                and parse(values["arguments"]) == call["function"]["arguments"],
                "Call differs from assistant",
            )
            message = result["data"]["message"]
            require(
                result["seq"] > actual["seq"] and result.get("sourceEventSeqs") == [actual["seq"]],
                "Result lineage mismatch",
            )
            require(
                message["role"] == "user" and message["source"] == {"kind": "tool", "callId": call_id},
                "Result source mismatch",
            )
            require(len(message["content"]) == 1, "Unsupported result blocks")
            block = message["content"][0]
            require(
                block["type"] == "tool-result" and block["toolCallId"] == call_id and block["isError"] is False,
                "Failed result",
            )
            require(
                all(part["type"] == "text" and isinstance(part["text"], str) for part in block["content"]),
                "Unsupported result content",
            )
            results.append(
                {"role": "tool", "tool_call_id": call_id, "content": "".join(part["text"] for part in block["content"])}
            )
        if index + 1 < len(requests):
            require(
                normalized[index + 1]["messages"] == normalized[index]["messages"] + [target] + results,
                "Request history/target/result mismatch",
            )
        else:
            require(not calls, "Last response must be complete text")
        rows.append(
            {
                "request": normalized[index],
                "target": target,
                "assistant_event_seq": event["seq"],
                "turn": data["turn"],
                "step": data["step"],
                "tool_call_ids": [call["id"] for call in calls],
            }
        )
    require(
        len({turn for turn, _ in coordinates}) == 1 and coordinates == sorted(set(coordinates)),
        "Multiple sessions or repeated steps",
    )
    return rows


def checked_bytes(path, expected):
    require(isinstance(expected, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", expected), "Missing trusted hash")
    raw = path.read_bytes()
    require(digest(raw) == expected, f"Hash mismatch: {path.name}")
    return raw


def verify_report_identity(report, events, runtime_identity):
    require(report.get("sdk_version") == runtime_identity["version"], "SDK version mismatch")
    require(report.get("runtime_mode") == "installed-sdk-runtime", "Unverified runtime mode")
    definitions = [
        event["data"]
        for event in events
        if event["type"] == "tool/call" and event["data"].get("name") == "cordis_define"
    ]
    require(len(definitions) == 1, "Expected one actual tool definition")
    arguments = parse(definitions[0]["arguments"])
    host = arguments.get("code", {}).get("host")
    require(isinstance(host, str) and host, "Missing actual host code")
    require(report.get("host_code_sha256") == digest(host.encode("utf-8")), "Host code identity mismatch")


def prepare(manifest_path: Path, manifest_sha256: str, output: Path):
    manifest = parse(checked_bytes(manifest_path, manifest_sha256))
    require(manifest.get("schema") == "dsh.t2-sft-sources.v1", "Invalid source manifest")
    require(re.fullmatch(r"[0-9a-f]{40}", manifest.get("collector_commit", "")), "Missing collector commit")
    require(manifest.get("tokenizer_revision") == TOKENIZER_REVISION, "Tokenizer revision mismatch")
    require(manifest.get("verifier_bundle_sha256") == verifier_bundle_digest(), "Verifier bundle mismatch")
    identity = manifest.get("runtime_identity", {})
    require(
        identity.get("source_revision") == "b2369692ea530007075ebcd18d39fdba0bbd3982"
        and identity.get("version") == "0.1.3a2",
        "Runtime identity mismatch",
    )
    for field in ("runtime_binary_sha256", "sdk_wheel_sha256", "runtime_wheel_sha256"):
        require(
            re.fullmatch(r"sha256:[0-9a-f]{64}", identity.get(field, "")), "Missing deployed runtime/wheel identity"
        )
    rows = {"train": [], "dev": []}
    seen_cases, seen_sessions = set(), set()
    for case in manifest["cases"]:
        folder = Path(case["directory"])
        fixture_path = Path(case["fixture"])
        fixture = parse(checked_bytes(fixture_path, case["fixture_sha256"]))
        report = parse(checked_bytes(folder / "report.json", case["report_sha256"]))
        requests = parse(checked_bytes(folder / "requests.json", case["requests_sha256"]))
        events = [parse(line) for line in checked_bytes(folder / "events.jsonl", case["trace_sha256"]).splitlines()]
        prompt = checked_bytes(Path(case["prompt_file"]), case["initial_prompt_sha256"]).decode("utf-8")
        require(
            prompt.strip()
            and report.get("initial_prompt") == prompt
            and report.get("initial_prompt_sha256") == case["initial_prompt_sha256"],
            "Prompt identity mismatch",
        )
        require(
            report.get("prompt_source") == "file" and report.get("policy_origin") == "scripted",
            "Not an explicit business demonstration",
        )
        require(
            report.get("fixture_sha256") == case["fixture_sha256"]
            and report.get("trace_sha256") == case["trace_sha256"],
            "Report binding mismatch",
        )
        require(
            report.get("session_id") == case["session_id"] and case["session_id"] not in seen_sessions,
            "Duplicate/mismatched session",
        )
        require(report.get("finish_reason") == "completed", "Incomplete report")
        split, case_id = case["split"], fixture["case_id"]
        require(
            split in rows and fixture["split"] == split and case_id not in seen_cases, "Case split overlap/mismatch"
        )
        seen_cases.add(case_id)
        seen_sessions.add(case["session_id"])
        verdict = verifier.verify_trace(folder / "events.jsonl", case["trace_sha256"], fixture=fixture)
        require(verdict["passed"], "Business/lifecycle verifier failed")
        verify_report_identity(report, events, identity)
        decisions = associate_decisions(requests, events, prompt)
        for index, decision in enumerate(decisions):
            provenance = {
                key: case[key]
                for key in (
                    "trace_sha256",
                    "requests_sha256",
                    "report_sha256",
                    "fixture_sha256",
                    "initial_prompt_sha256",
                )
            }
            provenance.update(
                {
                    key: manifest[key]
                    for key in ("runtime_identity", "collector_commit", "verifier_bundle_sha256", "tokenizer_revision")
                }
            )
            provenance.update({key: decision[key] for key in ("assistant_event_seq", "turn", "step", "tool_call_ids")})
            provenance["source_manifest_sha256"] = manifest_sha256
            rows[split].append(
                dict(
                    schema="dsh.t2-sft-decision.v1",
                    sample_id=f"{case_id}:{index}",
                    case_id=case_id,
                    split=split,
                    session_id=case["session_id"],
                    request_index=index,
                    request_json=canonical(decision["request"]),
                    target_json=canonical(decision["target"]),
                    enable_thinking=False,
                    provenance_json=canonical(provenance),
                )
            )
    require(rows["train"] and rows["dev"], "Both case-separated splits required")
    import pyarrow as pa
    import pyarrow.parquet as pq

    output.mkdir(parents=True, mode=0o700, exist_ok=False)
    artifacts = {}
    for split, items in rows.items():
        path = output / f"{split}.parquet"
        pq.write_table(pa.Table.from_pylist(items), path)
        artifacts[path.name] = {"sha256": digest(path.read_bytes()), "rows": len(items)}
    result = {
        "schema": "dsh.t2-sft-dataset.v1",
        "policy_origin": "scripted",
        "source_manifest_sha256": manifest_sha256,
        "artifacts": artifacts,
    }
    (output / "manifest.json").write_text(canonical(result) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(canonical(prepare(args.manifest, args.manifest_sha256, args.output_dir)))


if __name__ == "__main__":
    main()
