"""Independent v2 evidence reward; v1 diagnostic remains unchanged."""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from examples.dsh import evolution_verifier as parent
from examples.dsh.capabilities.context_tasks_v2 import VERIFIER_ID, documents, oracle
from examples.dsh.evolution_verifier import _sha256_bytes
from examples.dsh.evolution_verifier_v2 import _complete_pairs, source_hashes


def bundle_digest():
    hashes = source_hashes()
    for name in ("context_tasks_v2.py", "context_verifier_v2.py"):
        hashes["capabilities/" + name] = _sha256_bytes(Path(__file__).with_name(name).read_bytes())[7:]
    return _sha256_bytes(json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode())


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _answer(response):
    try:
        value = json.loads(response, object_pairs_hook=_object)
    except (ValueError, TypeError):
        return None
    if not isinstance(value, dict) or set(value) != {"status", "value", "citations"}:
        return None
    if not (
        (value["status"] == "answer" and isinstance(value["value"], str))
        or (value["status"] == "insufficient_evidence" and value["value"] is None)
    ) or not isinstance(value["citations"], list):
        return None
    for item in value["citations"]:
        if (
            not isinstance(item, dict)
            or set(item) != {"source", "line", "quote"}
            or not isinstance(item["source"], str)
            or not isinstance(item["quote"], str)
            or type(item["line"]) is not int
            or item["line"] < 1
        ):
            return None
    return value


def _source_view(args):
    if not isinstance(args, dict) or not {"command", "path"}.issubset(args):
        return False
    if set(args) - {"command", "path", "view_range"} or args["command"] != "view" or not isinstance(args["path"], str):
        return False
    if args.get("view_range") is None:
        return True
    bounds = args["view_range"]
    return (
        isinstance(bounds, list)
        and len(bounds) == 2
        and all(type(number) is int for number in bounds)
        and bounds[0] >= 1
        and (bounds[1] == -1 or bounds[1] >= bounds[0])
    )


def score(contract, root, events, response, finished):
    _complete_pairs(events)
    docs = documents(contract, root)
    expected = oracle(contract, root)
    if expected != contract["expected"]:
        raise RuntimeError("Fixture expected differs from independent oracle")
    reads, unsafe = set(), []
    results, calls = parent._tool_results(events), parent._tool_calls(events)
    if len(calls) != sum(event.get("type") == "tool/call" for event in events):
        raise RuntimeError("Malformed tool call")
    allowed = {(Path(root) / name).resolve(): name for name in docs}
    for call in calls:
        args = call["parsed_arguments"]
        if call["name"] != "str_replace_editor" or not _source_view(args):
            unsafe.append("non_source_view")
            continue
        path = Path(args["path"])
        path = (
            path.resolve() if path.is_absolute() else (Path(os.environ.get("DSH_TASK_WORKDIR", ".")) / path).resolve()
        )
        name = allowed.get(path)
        if name is None:
            unsafe.append("unapproved_source")
            continue
        bounds = args.get("view_range")
        # Fixed DSH formatFileView counts the trailing empty line via split('\n').
        runtime_lines = len((Path(root) / name).read_text().split("\n"))
        if bounds is not None and (bounds[0] > runtime_lines or bounds[1] > runtime_lines):
            unsafe.append("invalid_source_range")
            continue
        result = results.get(call["call_id"])
        if result and not result["is_error"]:
            lines = result["text"].splitlines()
            covers_file = bounds is None or (
                bounds[0] == 1 and (bounds[1] == -1 or bounds[1] >= len(docs[name]["lines"]))
            )
            if covers_file and all(
                line in lines or f"{n:6d}  {line}" in lines for n, line in enumerate(docs[name]["lines"], 1)
            ):
                reads.add(name)
    complete = bool(
        finished is True
        and events
        and events[-1].get("type") == "turn/end"
        and events[-1].get("data", {}).get("reason") == {"kind": "completed"}
    )
    eligible = complete and not unsafe
    answer = _answer(response)
    read_coverage = len(reads) / len(docs)
    semantic, citation_coverage, matched = 0.0, 0.0, False
    if answer is not None:
        semantic = float(
            answer["status"] == expected["status"]
            and answer["value"] == expected["value"]
            and set(contract["decision_sources"]).issubset(reads)
        )
        wanted = {(c["source"], c["line"], c["quote"]) for c in expected["citations"]}
        given = [(c["source"], c["line"], c["quote"]) for c in answer["citations"]]
        valid = len(set(given)) == len(given) and set(given).issubset(wanted)
        if valid and semantic:
            citation_coverage = len(given) / len(wanted)
        matched = bool(semantic and reads == set(docs) and valid and set(given) == wanted)
    reward = 0.1 * read_coverage + 0.55 * semantic + 0.35 * semantic * citation_coverage
    if not eligible or answer is None:
        reward = 0.0
    accuracy = float(eligible and matched)
    if accuracy:
        reward = 1.0
    return dict(
        reward=reward,
        accuracy=accuracy,
        eligible=bool(eligible),
        finished=complete,
        extra_info=dict(
            capability_scope="file-evidence-only",
            context_switch_verified=False,
            case_id=contract["case_id"],
            family=contract["family"],
            read_coverage=read_coverage,
            semantic_accuracy=semantic,
            citation_coverage=citation_coverage,
            v2_task_accuracy=accuracy,
            sources_read=sorted(reads),
            unsafe=unsafe,
            valid_json=answer is not None,
        ),
    )


def verify():
    if parent._required_env("DSH_VERIFIER_CODE_DIGEST") != bundle_digest():
        raise RuntimeError("Context v2 verifier bundle mismatch")
    for key, value in (("DSH_VERIFIER_ID", VERIFIER_ID), ("DSH_VERIFIER_VERSION", "2"), ("DSH_TASK_VERSION", "2")):
        if parent._required_env(key) != value:
            raise RuntimeError("Context v2 verifier identity mismatch")
    envelope, raw = parent._load_object(Path(parent._required_env("DSH_TASK_RESULT_PATH")))
    if envelope.get("schema") != "dsh.uni-agent.task-result.v1" or _sha256_bytes(raw) != parent._required_env(
        "DSH_ARTIFACT_SHA256"
    ):
        raise RuntimeError("Context artifact mismatch")
    parent._identity_checks(envelope)
    metadata = envelope["metadata"]
    path = parent._resolve_fixture(metadata["fixture_path"])
    contract, raw = parent._load_object(path)
    if _sha256_bytes(raw) != metadata["fixture_sha256"]:
        raise RuntimeError("Context fixture hash mismatch")
    if (
        metadata["task_id"] != "dsh/context-v2/" + contract["case_id"]
        or metadata["structure_id"] != contract["structure_id"]
        or metadata["split"] != contract["split"]
        or contract["split"] not in {"train", "validation"}
        or parent._required_env("DSH_TASK_SPLIT") != contract["split"]
    ):
        raise RuntimeError("Context case/split identity mismatch")
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
        print(f"context v2 verifier failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
