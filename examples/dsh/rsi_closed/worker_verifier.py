"""RSI development workers v1: real tool evidence, existing DSH receipt boundary."""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from examples.dsh import evolution_verifier as parent
from examples.dsh.evolution_verifier_v2 import _complete_pairs, source_hashes
from uni_agent.tasks.dsh import memory_artifacts

VERIFIER_ID = "dsh-rsi-worker"
RUNTIME_SHA256 = "sha256:d1a467a9c14a38ad5f01591d2cdb125852cb1a1d3b0ecb678dfde383404e80cb"
SOURCE = "sources/constraints.txt"
ROUTE = {"platform": "host", "provider": "Tool", "method": "listTools"}


def bundle_digest():
    hashes = source_hashes()
    for label, path in {
        "rsi_closed/worker_verifier.py": Path(__file__),
        "memory_artifacts.py": Path(memory_artifacts.__file__),
    }.items():
        hashes[label] = parent._sha256_bytes(path.read_bytes())[7:]
    return parent._sha256_bytes(json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode())


def _json(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON field")
            result[key] = value
        return result

    def invalid(value):
        raise ValueError("nonfinite JSON")

    return json.loads(text, object_pairs_hook=pairs, parse_constant=invalid)


def _contract(contract, root):
    fields = {"schema", "case_id", "kind", "runtime_sha256", "sources", "target"}
    if not isinstance(contract, dict) or set(contract) != fields or contract["schema"] != "dsh.rsi-worker.v1":
        raise RuntimeError("Invalid RSI worker contract")
    if contract["runtime_sha256"] != RUNTIME_SHA256:
        raise RuntimeError("RSI worker runtime mismatch")
    if contract["kind"] == "inspection":
        if contract["case_id"] != "inspect-discovery" or contract["target"] != ROUTE or contract["sources"] != []:
            raise RuntimeError("Invalid inspection contract")
        return None
    target = {"source": SOURCE, "key": "max_attempts", "line": 2}
    if contract["kind"] != "file" or contract["case_id"] != "file-constraint" or contract["target"] != target:
        raise RuntimeError("Invalid file contract")
    sources = contract["sources"]
    if (
        not isinstance(sources, list)
        or len(sources) != 1
        or set(sources[0]) != {"path", "sha256"}
        or sources[0]["path"] != SOURCE
    ):
        raise RuntimeError("Invalid file source allowlist")
    directory = memory_artifacts._directory(Path(root) / "sources")
    try:
        raw = memory_artifacts._read(directory, "constraints.txt", 65536)
    finally:
        os.close(directory)
    if parent._sha256_bytes(raw) != sources[0]["sha256"]:
        raise RuntimeError("RSI source hash mismatch")
    lines = raw.decode().splitlines()
    values = [line[len("max_attempts=") :] for line in lines if line.startswith("max_attempts=")]
    if len(values) != 1 or len(lines) < 2 or lines[1] != "max_attempts=" + values[0]:
        raise RuntimeError("Ambiguous constraint fixture")
    return {"lines": lines, "runtime_lines": len(raw.decode().split("\n"))}


def _routes(text):
    try:
        payload = _json(text)
        providers = payload["providers"]
        if not isinstance(providers, list):
            raise ValueError("provider list")
        routes = set()
        for provider in providers:
            if not isinstance(provider["methods"], list):
                raise ValueError("method list")
            for method in provider["methods"]:
                route = (provider["platform"], provider["id"], method["name"])
                if not all(isinstance(value, str) and value for value in route) or route in routes:
                    raise ValueError("invalid or duplicate route")
                routes.add(route)
        return routes
    except (ValueError, TypeError, KeyError) as exc:
        raise RuntimeError("Malformed successful inspect_list evidence") from exc


def _source_view(args, runtime_lines):
    if not isinstance(args, dict) or not {"command", "path"}.issubset(args):
        return False
    if set(args) - {"command", "path", "view_range"} or args["command"] != "view" or not isinstance(args["path"], str):
        return False
    bounds = args.get("view_range")
    return bounds is None or (
        isinstance(bounds, list)
        and len(bounds) == 2
        and all(type(number) is int for number in bounds)
        and 1 <= bounds[0] <= runtime_lines
        and (bounds[1] == -1 or bounds[0] <= bounds[1] <= runtime_lines)
    )


def score(contract, root, events, response, finished):
    document = _contract(contract, root)
    lines = document["lines"] if document else None
    _complete_pairs(events)
    calls, results = parent._tool_calls(events), parent._tool_results(events)
    if len(calls) != sum(event.get("type") == "tool/call" for event in events):
        raise RuntimeError("Malformed tool call")
    unsafe, successful, citation_calls = [], {}, set()
    for call in calls:
        args, identity = call["parsed_arguments"], call["call_id"]
        result = results[identity]
        if contract["kind"] == "inspection":
            allowed = call["name"] == "cordis_inspect_list" and args == {}
        else:
            allowed = call["name"] == "str_replace_editor" and _source_view(args, document["runtime_lines"])
            if allowed:
                path = Path(args["path"])
                path = path if path.is_absolute() else Path(os.environ.get("DSH_TASK_WORKDIR", ".")) / path
                allowed = path.absolute() == (Path(root) / SOURCE).absolute()
        if not allowed:
            unsafe.append("unapproved_action")
            continue
        if result["is_error"] or result["error"] is not None:
            continue
        if contract["kind"] == "inspection":
            successful[identity] = _routes(result["text"])
        else:
            bounds = args.get("view_range")
            rendered = result["text"].splitlines()
            covers_quote = bounds is None or (bounds[0] <= 2 and (bounds[1] == -1 or bounds[1] >= 2))
            if covers_quote and (lines[1] in rendered or f"{2:6d}  {lines[1]}" in rendered):
                citation_calls.add(identity)
            covers_file = bounds is None or (bounds[0] == 1 and (bounds[1] == -1 or bounds[1] >= len(lines)))
            if covers_file and all(
                line in rendered or f"{number:6d}  {line}" in rendered for number, line in enumerate(lines, 1)
            ):
                successful[identity] = True
    try:
        answer = _json(response)
    except (ValueError, TypeError):
        answer = None
    matched = False
    matched_call_ids = []
    if isinstance(answer, dict):
        if contract["kind"] == "inspection":
            fields = {"status", "platform", "provider", "method"}
            if answer.get("status") == "answer":
                route = tuple(answer.get(key) for key in ("platform", "provider", "method"))
                proven = all(isinstance(part, str) for part in route) and any(
                    route in routes for routes in successful.values()
                )
                if not proven:
                    unsafe.append("unproven_route")
                if proven:
                    matched_call_ids = sorted(identity for identity, routes in successful.items() if route in routes)
                matched = set(answer) == fields and proven and route == tuple(ROUTE.values())
        else:
            citation = answer.get("citation")
            proven = False
            if citation is not None:
                if isinstance(citation, dict):
                    proven = (
                        set(citation) == {"source", "line", "quote"}
                        and bool(citation_calls)
                        and citation["source"] == SOURCE
                        and type(citation["line"]) is int
                        and citation["line"] == 2
                        and citation["quote"] == lines[1]
                    )
                if not proven:
                    unsafe.append("fabricated_citation")
            if proven:
                matched_call_ids = sorted(citation_calls)
            if answer.get("status") == "answer" and citation is None:
                unsafe.append("missing_claimed_evidence")
            matched = (
                set(answer) == {"status", "value", "citation"}
                and answer.get("status") == "answer"
                and answer.get("value") == lines[1].split("=", 1)[1]
                and proven
                and bool(successful)
            )
    complete = (
        finished is True
        and bool(events)
        and events[-1].get("type") == "turn/end"
        and events[-1].get("data", {}).get("reason") == {"kind": "completed"}
    )
    eligible = complete and not unsafe
    reward = float(eligible and matched)
    return {
        "reward": reward,
        "accuracy": reward,
        "eligible": eligible,
        "finished": complete,
        "extra_info": {
            "scope": "rsi-worker-development",
            "case_id": contract["case_id"],
            "matched": matched,
            "unsafe": sorted(set(unsafe)),
            "successful_call_ids": sorted(successful),
            "matched_call_ids": matched_call_ids,
            "promotion_verified": False,
        },
    }


def verify():
    if parent._required_env("DSH_VERIFIER_CODE_DIGEST") != bundle_digest():
        raise RuntimeError("RSI worker bundle mismatch")
    if (
        parent._required_env("DSH_VERIFIER_ID") != VERIFIER_ID
        or parent._required_env("DSH_VERIFIER_VERSION") != "1"
        or parent._required_env("DSH_TASK_VERSION") != "1"
        or parent._required_env("DSH_ENVIRONMENT_DIGEST") != RUNTIME_SHA256
    ):
        raise RuntimeError("RSI worker identity/runtime mismatch")
    envelope, raw = parent._load_object(Path(parent._required_env("DSH_TASK_RESULT_PATH")))
    if envelope.get("schema") != "dsh.uni-agent.task-result.v1" or parent._sha256_bytes(raw) != parent._required_env(
        "DSH_ARTIFACT_SHA256"
    ):
        raise RuntimeError("RSI worker artifact mismatch")
    parent._identity_checks(envelope)
    metadata = envelope["metadata"]
    path = parent._resolve_fixture(metadata["fixture_path"])
    contract, raw = parent._load_object(path)
    if (
        parent._sha256_bytes(raw) != metadata["fixture_sha256"]
        or metadata["task_id"] != "dsh/rsi-worker/" + contract["case_id"]
    ):
        raise RuntimeError("RSI worker fixture identity mismatch")
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
        print(f"RSI worker verifier failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
