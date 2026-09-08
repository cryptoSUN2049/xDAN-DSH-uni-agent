"""Independent single-session memory evaluation; no cross-session training credit."""

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from examples.dsh import evolution_verifier as parent
from examples.dsh.evolution_verifier_v2 import _complete_pairs, source_hashes
from uni_agent.tasks.dsh import memory_artifacts

VERIFIER_ID = "dsh-memory-file-chain-eval"


def sha(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def canonical(value):
    return (
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode()


def loads(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError("Duplicate JSON field")
            value[key] = item
        return value

    def invalid(_value):
        raise ValueError("Non-finite JSON")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)


def read_regular(path, limit=1_000_000):
    path = Path(path)
    fd = memory_artifacts._directory(path.parent)
    try:
        return memory_artifacts._read(fd, path.name, limit)
    finally:
        os.close(fd)


def bundle_digest():
    hashes = source_hashes()
    hashes["capabilities/memory_verifier.py"] = sha(Path(__file__).read_bytes())
    hashes["memory_artifacts.py"] = sha(Path(memory_artifacts.__file__).read_bytes())
    return sha(canonical(hashes))


def _visible_text(text, raw):
    lines = raw.decode().splitlines()
    return all(
        line in text.splitlines() or f"{number:6d}  {line}" in text.splitlines() for number, line in enumerate(lines, 1)
    )


def score(fixture, events, response, finished, session_id):
    if fixture.get("schema") != "dsh.memory-stage.v1" or fixture.get("role") not in {"writer", "reader"}:
        raise ValueError("Invalid memory stage fixture")
    if not isinstance(session_id, str) or not session_id:
        raise ValueError("Missing actual DSH session identity")
    _complete_pairs(events)
    role = fixture["role"]
    if role == "writer":
        raw = read_regular(fixture["source_path"])
        if sha(raw) != fixture["source_sha256"]:
            raise ValueError("Writer source changed")
        read_inputs = {fixture["source_path"]: raw}
    else:
        binding = fixture["writer_binding"]
        loaded = memory_artifacts.load_memory_artifact(
            directory=Path(fixture["frozen_dir"]),
            expected_manifest_sha256=binding["manifest_sha256"],
            chain_id=fixture["chain_id"],
            writer_session_id=binding["dsh_session_id"],
            source_version=fixture["source_version"],
            reader_session_id=session_id,
            max_bytes=fixture["max_bytes"],
        )
        if loaded.content_sha256 != binding["content_sha256"]:
            raise ValueError("Reader content binding mismatch")
        question = read_regular(fixture["question_path"])
        if sha(question) != fixture["question_sha256"]:
            raise ValueError("Reader question changed")
        read_inputs = {fixture["memory_path"]: loaded.content, fixture["question_path"]: question}
    calls, results = parent._tool_calls(events), parent._tool_results(events)
    if len(calls) != sum(e.get("type") == "tool/call" for e in events):
        raise ValueError("Malformed tool call")
    seen, writes, unsafe = set(), 0, []
    for call in calls:
        args = call["parsed_arguments"]
        if call["name"] != "str_replace_editor" or not isinstance(args, dict):
            unsafe.append("unapproved_tool")
            continue
        command, target = args.get("command"), args.get("path")
        readable = target in read_inputs or (role == "writer" and target == fixture["memory_path"])
        writing = (
            role == "writer" and target == fixture["memory_path"] and command in {"create", "str_replace", "insert"}
        )
        if not ((command == "view" and readable) or writing):
            unsafe.append("unapproved_action")
            continue
        result = results.get(call["call_id"])
        if not result or result["is_error"] or result["error"]:
            continue
        if command == "view" and target in read_inputs and _visible_text(result["text"], read_inputs[target]):
            seen.add(target)
        if writing:
            writes += 1
    complete = (
        finished is True
        and bool(events)
        and events[-1].get("type") == "turn/end"
        and events[-1].get("data", {}).get("reason") == {"kind": "completed"}
    )
    eligible = complete and not unsafe
    memory_sha = None
    try:
        if role == "writer":
            raw = read_regular(fixture["memory_path"], fixture["max_bytes"])
            memory_sha = sha(raw)
            matched = loads(raw) == fixture["expected_memory"] and writes > 0 and seen == set(read_inputs)
        else:
            matched = loads(response) == fixture["expected_answer"] and seen == set(read_inputs)
    except (ValueError, OSError, UnicodeError, TypeError):
        matched = False
    reward = float(eligible and matched)
    return {
        "reward": reward,
        "accuracy": reward,
        "eligible": bool(eligible),
        "finished": bool(complete),
        "extra_info": {
            "chain_id": fixture["chain_id"],
            "role": role,
            "training": False,
            "credit_assignment": "none",
            "matched": matched,
            "unsafe": unsafe,
            "memory_sha256": memory_sha,
            "reads": sorted(seen),
        },
    }


def verify():
    if parent._required_env("DSH_VERIFIER_CODE_DIGEST") != bundle_digest():
        raise ValueError("Memory verifier bundle mismatch")
    if (
        parent._required_env("DSH_VERIFIER_ID") != VERIFIER_ID
        or parent._required_env("DSH_VERIFIER_VERSION") != "1"
        or parent._required_env("DSH_TASK_VERSION") != "1"
    ):
        raise ValueError("Memory verifier identity mismatch")
    envelope_raw = read_regular(Path(parent._required_env("DSH_TASK_RESULT_PATH")), 8_000_000)
    if sha(envelope_raw) != parent._required_env("DSH_ARTIFACT_SHA256"):
        raise ValueError("Memory envelope hash mismatch")
    envelope = loads(envelope_raw)
    parent._identity_checks(envelope)
    if envelope.get("schema") != "dsh.uni-agent.task-result.v1" or envelope["metadata"].get("split") != "test":
        raise ValueError("Memory chain only supports evaluation envelopes")
    metadata = envelope["metadata"]
    fixture_raw = read_regular(parent._resolve_fixture(metadata["fixture_path"]))
    if sha(fixture_raw) != metadata["fixture_sha256"]:
        raise ValueError("Memory fixture hash mismatch")
    fixture = loads(fixture_raw)
    if metadata["task_id"] != f"dsh/memory/{fixture['chain_id']}/{fixture['role']}":
        raise ValueError("Memory task identity mismatch")
    events = parent._load_trace(Path(parent._required_env("DSH_TRACE_PATH")), parent._required_env("DSH_TRACE_SHA256"))
    result = score(fixture, events, envelope["response"], envelope["finished"], envelope["dsh"]["dsh_session_id"])
    evidence = [metadata["fixture_sha256"], parent._required_env("DSH_TRACE_SHA256")]
    if fixture["role"] == "reader":
        evidence.extend([fixture["writer_binding"]["receipt_id"], fixture["writer_binding"]["manifest_sha256"]])
    result.update(fresh=True, issued_at=datetime.now(timezone.utc).isoformat(), evidence=evidence)
    return result


def main():
    try:
        print(json.dumps(verify(), allow_nan=False))
    except (ValueError, RuntimeError, OSError, KeyError, TypeError, UnicodeError) as exc:
        print(f"memory verifier rejected: {type(exc).__name__}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
