"""Independent work-state stage verifier. Quality zero is not an admission failure."""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from examples.dsh import evolution_verifier as parent
from examples.dsh.capabilities import memory_verifier as memory
from examples.dsh.capabilities.memory_verifier import canonical, loads, read_regular, sha
from examples.dsh.capabilities.work_state.bundle import pack_bundle
from examples.dsh.capabilities.work_state.scoring import score_task
from examples.dsh.evolution_verifier_v2 import _complete_pairs
from uni_agent.tasks.dsh import memory_artifacts

VERIFIER_ID = "dsh-work-state-training-stage"
VERIFIER_VERSION = "1"
CONTRACT_ID = "work-state-v1"


def bundle_digest():
    root = Path(__file__).parent
    return sha(
        canonical(
            {
                "parent_bundle": memory.bundle_digest(),
                **{
                    name: sha((root / name).read_bytes())
                    for name in ("tasks.py", "scoring.py", "bundle.py", "policy.mjs", "profile.py", "verifier.py")
                },
            }
        )
    )


def _reader_binding(fixture, session_id):
    binding = fixture["writer_binding"]
    loaded = memory_artifacts.load_memory_artifact(
        directory=Path(fixture["frozen_dir"]),
        expected_manifest_sha256=binding["manifest_sha256"],
        chain_id=fixture["chain_id"],
        writer_session_id=binding["dsh_session_id"],
        source_version=fixture["source_version"],
        reader_session_id=session_id,
        max_bytes=fixture["max_bytes"] * 2 + 65536,
    )
    if loaded.content_sha256 != binding["content_sha256"]:
        raise ValueError("Frozen content binding mismatch")
    if fixture["bundle_paths"] != fixture["task"]["memory_paths"]:
        raise ValueError("Frozen allowed path inventory mismatch")
    if pack_bundle(Path(fixture["unpacked_root"]), fixture["bundle_paths"], fixture["max_bytes"]) != loaded.content:
        raise ValueError("Unpacked file bytes/missing inventory changed")


def score(fixture, events, response, finished, session_id):
    if (
        fixture.get("schema") != "dsh.work-state-stage.v1"
        or fixture.get("contract_id") != CONTRACT_ID
        or fixture.get("role") not in ("writer", "reader")
        or not isinstance(session_id, str)
        or not session_id
    ):
        raise ValueError("Invalid work-state stage identity")
    if type(fixture.get("max_bytes")) is not int or not 0 < fixture["max_bytes"] <= 65536:
        raise ValueError("Invalid artifact byte budget")
    _complete_pairs(events)
    if fixture["role"] == "reader":
        _reader_binding(fixture, session_id)
    for path, digest in fixture["read_files"].items():
        if sha(read_regular(path, fixture["max_bytes"])) != digest:
            raise ValueError("Immutable stage input changed")
    readable = set(fixture["read_files"]) | set(fixture["read_missing"]) | set(fixture["write_files"])
    writable = set(fixture["write_files"])
    if writable & set(fixture["read_files"]):
        raise ValueError("Immutable inputs cannot be writable")
    calls, results = parent._tool_calls(events), parent._tool_results(events)
    if len(calls) != sum(e.get("type") == "tool/call" for e in events):
        raise ValueError("Malformed tool call")
    unsafe, successful_writes, matched = [], set(), []
    for call in calls:
        args = call["parsed_arguments"]
        if call["name"] != "str_replace_editor" or not isinstance(args, dict):
            unsafe.append("unapproved_tool")
            continue
        command, path = args.get("command"), args.get("path")
        if not isinstance(path, str) or not isinstance(command, str):
            unsafe.append("malformed_action")
            continue
        writing = command in ("create", "str_replace", "insert") and path in writable
        if not (command == "view" and path in readable or writing):
            unsafe.append("unapproved_action")
            continue
        result = results.get(call["call_id"])
        if result and not result["is_error"] and not result["error"]:
            matched.append(call["call_id"])
            if writing:
                successful_writes.add(path)
    complete = (
        finished is True
        and bool(events)
        and events[-1].get("type") == "turn/end"
        and events[-1].get("data", {}).get("reason") == {"kind": "completed"}
    )
    eligible = bool(complete and not unsafe)
    quality = dict(reward=0, checks={}, errors=[], verified_progress=0.0)
    snapshot = None
    if fixture["role"] == "reader":
        snapshot = pack_bundle(Path(fixture["output_root"]), fixture["task"]["result_paths"], fixture["max_bytes"])
        outputs = {}
        for name in fixture["task"]["result_paths"]:
            target = str(Path(fixture["output_root"]) / name)
            if target not in writable:
                raise ValueError("Result target not authorized by stage")
            if target not in successful_writes:
                continue
            try:
                outputs[name] = read_regular(target, fixture["max_bytes"])
            except FileNotFoundError:
                pass
            except ValueError as error:
                # Unsafe file identity is not ordinary malformed JSON.
                raise ValueError("Invalid output file identity/budget") from error
        quality = score_task(fixture["task"], outputs)
        if pack_bundle(Path(fixture["output_root"]), fixture["task"]["result_paths"], fixture["max_bytes"]) != snapshot:
            raise ValueError("Output artifacts changed during scoring")
    reward = int(eligible and quality["reward"] == 1)
    return dict(
        reward=reward,
        accuracy=reward,
        eligible=eligible,
        finished=bool(complete),
        extra_info=dict(
            chain_id=fixture["chain_id"],
            role=fixture["role"],
            contract_id=CONTRACT_ID,
            reward_scope="deferred-to-reader" if fixture["role"] == "writer" else "terminal-business-result",
            checks=quality["checks"],
            errors=quality["errors"],
            verified_progress=quality["verified_progress"],
            unsafe=unsafe,
            matched_call_ids=matched,
            successful_writes=sorted(successful_writes),
            **({"output_snapshot_sha256": sha(snapshot)} if snapshot is not None else {}),
        ),
    )


def verify():
    if (
        parent._required_env("DSH_VERIFIER_CODE_DIGEST") != bundle_digest()
        or parent._required_env("DSH_VERIFIER_ID") != VERIFIER_ID
        or parent._required_env("DSH_VERIFIER_VERSION") != VERIFIER_VERSION
        or parent._required_env("DSH_TASK_VERSION") != "1"
    ):
        raise ValueError("Work-state verifier identity mismatch")
    raw = read_regular(parent._required_env("DSH_TASK_RESULT_PATH"), 8_000_000)
    if sha(raw) != parent._required_env("DSH_ARTIFACT_SHA256"):
        raise ValueError("Envelope hash mismatch")
    envelope = loads(raw)
    parent._identity_checks(envelope)
    metadata = envelope["metadata"]
    if (
        envelope.get("schema") != "dsh.uni-agent.task-result.v1"
        or metadata.get("split") not in ("train", "validation")
        or metadata["split"] != parent._required_env("DSH_TASK_SPLIT")
        or metadata.get("contract_id") != CONTRACT_ID
    ):
        raise ValueError("Stage split/contract mismatch")
    fixture_raw = read_regular(parent._resolve_fixture(metadata["fixture_path"]))
    if sha(fixture_raw) != metadata["fixture_sha256"]:
        raise ValueError("Stage fixture hash mismatch")
    fixture = loads(fixture_raw)
    binding = fixture.get("training_stage")
    if (
        not isinstance(binding, dict)
        or binding != metadata.get("training_stage")
        or set(binding) != {"schema", "split", "run_id", "group_uid", "sibling", "checkpoint_identity"}
        or binding["schema"] != "dsh.memory-training-stage.v1"
        or binding["split"] != metadata["split"]
        or type(binding["sibling"]) is not int
        or not 0 <= binding["sibling"] < 4
        or any(
            not isinstance(binding[k], str) or not binding[k].strip()
            for k in ("run_id", "group_uid", "checkpoint_identity")
        )
    ):
        raise ValueError("Invalid stage binding")
    if metadata["task_id"] != f"dsh/work-state/{fixture['chain_id']}/{fixture['role']}":
        raise ValueError("Work-state task identity mismatch")
    trace_sha = parent._required_env("DSH_TRACE_SHA256")
    events = parent._load_trace(Path(parent._required_env("DSH_TRACE_PATH")), trace_sha)
    result = score(fixture, events, envelope["response"], envelope["finished"], envelope["dsh"]["dsh_session_id"])
    result["extra_info"].update(
        training=metadata["split"] == "train",
        credit_assignment="stage-only",
        training_stage=dict(binding),
        scope="training-stage",
    )
    evidence = [metadata["fixture_sha256"], trace_sha, sha(canonical(binding))]
    if fixture["role"] == "reader":
        evidence.extend(
            [
                fixture["writer_binding"]["receipt_id"],
                fixture["writer_binding"]["manifest_sha256"],
                result["extra_info"]["output_snapshot_sha256"],
            ]
        )
    result.update(fresh=True, issued_at=datetime.now(timezone.utc).isoformat(), evidence=evidence)
    return result


def main():
    try:
        print(json.dumps(verify(), allow_nan=False))
    except (ValueError, RuntimeError, OSError, KeyError, TypeError, UnicodeError) as exc:
        print(f"work-state verifier rejected: {type(exc).__name__}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
