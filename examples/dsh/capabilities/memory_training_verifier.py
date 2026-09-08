"""Independent training-stage receipt entry; never assigns cross-session credit."""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from examples.dsh import evolution_verifier as parent
from examples.dsh.capabilities import memory_verifier as memory
from examples.dsh.capabilities.memory_verifier import canonical, loads, read_regular, sha

VERIFIER_ID = "dsh-memory-file-chain-training-stage"
VERIFIER_VERSION = "1"


def bundle_digest():
    return sha(
        canonical(
            {"memory_verifier_bundle": memory.bundle_digest(), "training_entry": sha(Path(__file__).read_bytes())}
        )
    )


def verify():
    if (
        parent._required_env("DSH_VERIFIER_CODE_DIGEST") != bundle_digest()
        or parent._required_env("DSH_VERIFIER_ID") != VERIFIER_ID
        or parent._required_env("DSH_VERIFIER_VERSION") != VERIFIER_VERSION
        or parent._required_env("DSH_TASK_VERSION") != "1"
    ):
        raise ValueError("Training-stage verifier identity mismatch")
    raw = read_regular(Path(parent._required_env("DSH_TASK_RESULT_PATH")), 8_000_000)
    if sha(raw) != parent._required_env("DSH_ARTIFACT_SHA256"):
        raise ValueError("Training-stage envelope hash mismatch")
    envelope = loads(raw)
    parent._identity_checks(envelope)
    metadata = envelope["metadata"]
    if metadata.get("split") != parent._required_env("DSH_TASK_SPLIT"):
        raise ValueError("Training-stage split does not match process identity")
    if envelope.get("schema") != "dsh.uni-agent.task-result.v1" or metadata.get("split") not in ("train", "validation"):
        raise ValueError("Training-stage requires train or validation split")
    fixture_raw = read_regular(parent._resolve_fixture(metadata["fixture_path"]))
    if sha(fixture_raw) != metadata["fixture_sha256"]:
        raise ValueError("Training-stage fixture hash mismatch")
    fixture = loads(fixture_raw)
    binding = fixture.get("training_stage")
    if not isinstance(binding, dict) or binding != metadata.get("training_stage"):
        raise ValueError("Training-stage identity mismatch")
    if (
        set(binding) != {"schema", "split", "run_id", "group_uid", "sibling", "checkpoint_identity"}
        or binding["schema"] != "dsh.memory-training-stage.v1"
        or binding["split"] != metadata["split"]
        or type(binding["sibling"]) is not int
        or not 0 <= binding["sibling"] < 4
        or any(
            not isinstance(binding[k], str) or not binding[k].strip()
            for k in ("run_id", "group_uid", "checkpoint_identity")
        )
    ):
        raise ValueError("Invalid training-stage binding")
    if metadata["task_id"] != f"dsh/memory-training/{fixture['chain_id']}/{fixture['role']}":
        raise ValueError("Training-stage task mismatch")
    events = parent._load_trace(Path(parent._required_env("DSH_TRACE_PATH")), parent._required_env("DSH_TRACE_SHA256"))
    result = memory.score(
        fixture, events, envelope["response"], envelope["finished"], envelope["dsh"]["dsh_session_id"]
    )
    result["extra_info"].update(
        training=metadata["split"] == "train",
        credit_assignment="stage-only",
        training_stage=dict(binding),
        scope="training-stage",
    )
    evidence = [metadata["fixture_sha256"], parent._required_env("DSH_TRACE_SHA256"), sha(canonical(binding))]
    if fixture["role"] == "reader":
        evidence.extend([fixture["writer_binding"]["receipt_id"], fixture["writer_binding"]["manifest_sha256"]])
    result.update(fresh=True, issued_at=datetime.now(timezone.utc).isoformat(), evidence=evidence)
    return result


def main():
    try:
        print(json.dumps(verify(), allow_nan=False))
    except (ValueError, RuntimeError, OSError, KeyError, TypeError, UnicodeError) as exc:
        print(f"memory training verifier rejected: {type(exc).__name__}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
