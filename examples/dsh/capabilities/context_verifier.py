"""File-evidence diagnostic; uses the existing DSH receipt boundary, never RL admission."""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from examples.dsh import evolution_verifier as parent
from examples.dsh.evolution_verifier_v2 import _complete_pairs, source_hashes

VERIFIER_ID = "dsh-context-file-evidence"


def bundle_digest():
    hashes = source_hashes()
    hashes["capabilities/context_verifier.py"] = parent._sha256_bytes(Path(__file__).read_bytes())[7:]
    return parent._sha256_bytes(json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode())


def _source(root, relative):
    if not isinstance(relative, str) or Path(relative).is_absolute():
        raise RuntimeError("source must be relative")
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise RuntimeError("source escapes fixture")
    return path


def score(contract, root, events, response, finished):
    if contract.get("schema") != "dsh.context-file-evidence.v1":
        raise RuntimeError("invalid context fixture schema")
    _complete_pairs(events)
    documents = {}
    for source in contract["sources"]:
        path = _source(root, source["path"])
        raw = path.read_bytes()
        if parent._sha256_bytes(raw) != source["sha256"]:
            raise RuntimeError("context source hash mismatch")
        if source["path"] in documents:
            raise RuntimeError("duplicate source")
        documents[source["path"]] = raw.decode().splitlines()
    key = contract["target_key"] + "="
    values = [line[len(key) :] for line in documents[contract["authoritative_source"]] if line.startswith(key)]
    if len(values) > 1:
        raise RuntimeError("ambiguous authoritative fixture")
    value = values[0] if values else None
    citations = []
    for ref in contract["required_evidence"]:
        line = ref["line"]
        if type(line) is not int or line < 1:
            raise RuntimeError("invalid evidence line")
        citations.append({**ref, "quote": documents[ref["source"]][line - 1]})
    expected = {
        "status": "answer" if value is not None else "insufficient_evidence",
        "value": value,
        "citations": citations,
    }
    reads, unsafe = set(), []
    results = parent._tool_results(events)
    calls = parent._tool_calls(events)
    if len(calls) != sum(event.get("type") == "tool/call" for event in events):
        raise RuntimeError("malformed tool call")
    for call in calls:
        args = call["parsed_arguments"]
        if (
            call["name"] != "str_replace_editor"
            or not isinstance(args, dict)
            or set(args) != {"command", "path"}
            or args["command"] != "view"
            or not isinstance(args["path"], str)
        ):
            unsafe.append("non_source_view")
            continue
        path = Path(args["path"])
        # Relative actions resolve from task workdir, matching runtime, not fixture directory.
        path = (
            path.resolve() if path.is_absolute() else (Path(os.environ.get("DSH_TASK_WORKDIR", ".")) / path).resolve()
        )
        matches = [name for name in documents if _source(root, name) == path]
        if not matches:
            unsafe.append("unapproved_source")
            continue
        result = results.get(call["call_id"])
        if (
            result
            and not result["is_error"]
            and all(
                line in result["text"].splitlines() or f"{number:6d}  {line}" in result["text"].splitlines()
                for number, line in enumerate(documents[matches[0]], 1)
            )
        ):
            reads.add(matches[0])
    complete = (
        finished is True
        and events[-1].get("type") == "turn/end"
        and events[-1].get("data", {}).get("reason") == {"kind": "completed"}
    )
    try:
        answer = json.loads(response)
    except (ValueError, TypeError):
        answer = None
    # Citation order is irrelevant; duplicates or additional fields remain wrong.
    if isinstance(answer, dict) and isinstance(answer.get("citations"), list):
        answer = dict(answer)
        answer["citations"] = sorted(answer["citations"], key=lambda item: json.dumps(item, sort_keys=True))
    expected["citations"] = sorted(expected["citations"], key=lambda item: json.dumps(item, sort_keys=True))
    eligible = complete and not unsafe
    matched = answer == expected and reads == set(documents)
    reward = float(eligible and matched)
    return {
        "reward": reward,
        "accuracy": reward,
        "eligible": eligible,
        "finished": complete,
        "extra_info": {
            "capability_scope": "file-evidence-only",
            "context_switch_verified": False,
            "family": contract["family"],
            "case_id": contract["case_id"],
            "matched": matched,
            "sources_read": sorted(reads),
            "unsafe": unsafe,
        },
    }


def verify():
    if parent._required_env("DSH_VERIFIER_CODE_DIGEST") != bundle_digest():
        raise RuntimeError("context verifier bundle mismatch")
    if (
        parent._required_env("DSH_VERIFIER_ID") != VERIFIER_ID
        or parent._required_env("DSH_VERIFIER_VERSION") != "1"
        or parent._required_env("DSH_TASK_VERSION") != "1"
    ):
        raise RuntimeError("context verifier identity mismatch")
    envelope, raw = parent._load_object(Path(parent._required_env("DSH_TASK_RESULT_PATH")))
    if envelope.get("schema") != "dsh.uni-agent.task-result.v1" or parent._sha256_bytes(raw) != parent._required_env(
        "DSH_ARTIFACT_SHA256"
    ):
        raise RuntimeError("context artifact mismatch")
    parent._identity_checks(envelope)
    metadata = envelope["metadata"]
    path = parent._resolve_fixture(metadata["fixture_path"])
    contract, raw = parent._load_object(path)
    if parent._sha256_bytes(raw) != metadata["fixture_sha256"]:
        raise RuntimeError("context fixture hash mismatch")
    if metadata["task_id"] != "dsh/context/" + contract["case_id"]:
        raise RuntimeError("context case identity mismatch")
    events = parent._load_trace(Path(parent._required_env("DSH_TRACE_PATH")), parent._required_env("DSH_TRACE_SHA256"))
    result = score(contract, path.parent, events, envelope.get("response"), envelope.get("finished"))
    result.update(
        fresh=True,
        issued_at=datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        evidence=[metadata["fixture_sha256"], parent._required_env("DSH_TRACE_SHA256")],
    )
    return result


def main():
    try:
        print(json.dumps(verify(), allow_nan=False))
        return 0
    except (RuntimeError, ValueError, KeyError, IndexError, TypeError, OSError) as exc:
        print(f"context verifier failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
