"""Versioned admission fix only; the pinned v1 seven-component reward is unchanged."""

import hashlib
import json
import os
import sys
from pathlib import Path

from examples.dsh import evolution_verifier as parent

PARENT_SHA256 = {
    "evolution_verifier.py": "067668803e5f6fdb5f64cd44a17e2f4baef8835e4681a02cdf35d9f6bb4e3748",
    "verifier.py": "eb5e0d68779739d04e1038534e5f2799a44cf299e7325ba2f6bef5c793ecf2cd",
}


def source_hashes():
    root = Path(__file__).parent
    hashes = {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in [*PARENT_SHA256, Path(__file__).name]
    }
    if any(hashes[name] != digest for name, digest in PARENT_SHA256.items()):
        raise RuntimeError("Pinned parent verifier source changed")
    return hashes


def bundle_digest():
    raw = json.dumps(source_hashes(), sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _complete_pairs(events):
    seen, pending = set(), set()
    for event in events:
        data = event.get("data", {})
        if event.get("type") == "tool/call":
            call_id = data.get("callId")
            if not isinstance(call_id, str) or not call_id or call_id in seen:
                raise RuntimeError("Invalid or duplicate tool call identity")
            seen.add(call_id)
            pending.add(call_id)
        elif event.get("type") == "tool/result":
            message = data.get("message", {})
            call_id = message.get("source", {}).get("callId")
            blocks = message.get("content", [])
            if (
                call_id not in pending
                or len(blocks) != 1
                or blocks[0].get("toolCallId") != call_id
                or type(blocks[0].get("isError")) is not bool
            ):
                raise RuntimeError("Invalid tool result identity")
            pending.remove(call_id)
    if pending:
        raise RuntimeError("Missing tool result evidence")


def verify():
    if os.environ.get("DSH_VERIFIER_VERSION") != "2" or os.environ.get("DSH_TASK_VERSION") != "2":
        raise RuntimeError("Version 2 requires a new task and verifier identity")
    if os.environ.get("DSH_VERIFIER_CODE_DIGEST") != bundle_digest():
        raise RuntimeError("Verifier source bundle hash mismatch")
    value = parent.verify()  # Original fixture/envelope/hash/identity validation and scoring.
    details = value["extra_info"]
    original = value["eligible"]
    admitted = False
    if (
        details.get("hard_veto") == ["missing_pre_define_inspection"]
        and value["reward"] == value["accuracy"] == 0
        and value["finished"] is True
    ):
        # Re-read under the same expected hashes; never accept a modified snapshot.
        envelope, raw = parent._load_object(Path(parent._required_env("DSH_TASK_RESULT_PATH")))
        if parent._sha256_bytes(raw) != parent._required_env("DSH_ARTIFACT_SHA256"):
            raise RuntimeError("Envelope changed during admission")
        parent._identity_checks(envelope)
        events = parent._load_trace(
            Path(parent._required_env("DSH_TRACE_PATH")), parent._required_env("DSH_TRACE_SHA256")
        )
        if (
            envelope.get("finished") is True
            and events[-1].get("type") == "turn/end"
            and events[-1].get("data", {}).get("reason") == {"kind": "completed"}
        ):
            _complete_pairs(events)
            admitted = True
    value["eligible"] = original or admitted
    details.update(
        original_eligible=original,
        eligible=value["eligible"],
        admission_kind="completed-policy-failure"
        if admitted
        else "original-v1-eligible"
        if original
        else "original-v1-rejected",
    )
    value["evidence"].append("admission_kind:" + details["admission_kind"])
    return value


def main():
    try:
        value = verify()
    except Exception as exc:
        print(f"dsh evolution verifier v2 failed: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False))


if __name__ == "__main__":
    main()
