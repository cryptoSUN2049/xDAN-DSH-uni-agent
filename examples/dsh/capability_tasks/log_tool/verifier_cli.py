"""Existing DSH Task envelope adapter; the task owns receipt issuance."""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from examples.dsh.capability_tasks.log_tool.task_bundle import CODE_PATHS, DIRECTORY, VERIFIER_ID, load_case
from examples.dsh.evolution_v3_live import _bundle_identity
from examples.dsh.evolution_verifier import _identity_checks, _resolve_fixture
from examples.dsh.verifier import _load_object, _require_digest, _required_env, _sha256_bytes
from uni_agent.agents.dsh.runner import _patches_digest


def verify():
    from examples.dsh.capability_tasks.log_tool.verifier import verify_trace

    envelope, raw = _load_object(Path(_required_env("DSH_TASK_RESULT_PATH")))
    if envelope.get("schema") != "dsh.uni-agent.task-result.v1":
        raise RuntimeError("Wrong T2 task envelope schema")
    if _sha256_bytes(raw) != _require_digest(_required_env("DSH_ARTIFACT_SHA256"), label="artifact hash"):
        raise RuntimeError("T2 task envelope hash mismatch")
    _identity_checks(envelope)
    metadata = envelope["metadata"]
    root = Path(_required_env("DSH_TASK_WORKDIR")).resolve()
    patch = root / "examples/dsh/evolution.patch.yml"
    expected_patch_digest = _patches_digest((str(patch),))
    if (
        envelope["dsh"].get("profile") != "sdk-minimal"
        or metadata.get("profile") != "sdk-minimal"
        or envelope["dsh"].get("patches_sha256") != expected_patch_digest
        or metadata.get("patches_sha256") != expected_patch_digest
        or metadata.get("patch_files") != {str(patch): _sha256_bytes(patch.read_bytes())}
    ):
        raise RuntimeError("T2 runtime profile or patch identity mismatch")
    if metadata.get("verifier_id") != VERIFIER_ID or metadata.get("verifier_version") != "1":
        raise RuntimeError("Wrong T2 verifier identity")
    if _bundle_identity(CODE_PATHS, repository_root=root)["sha256"] != metadata["verifier_code_digest"]:
        raise RuntimeError("T2 verifier installed code differs from pin")
    fixture_path = _resolve_fixture(metadata.get("fixture_path"))
    if fixture_path.parent != (root / DIRECTORY / "fixtures").resolve():
        raise RuntimeError("T2 fixture outside trusted registry")
    case, fixture_raw = load_case(fixture_path)
    if _sha256_bytes(fixture_raw) != metadata.get("fixture_digest"):
        raise RuntimeError("T2 fixture hash mismatch")
    split = "train" if case["split"] == "train" else "validation"
    if (
        metadata.get("task_id") != case["case_id"]
        or metadata.get("task_version") != "1"
        or metadata.get("split") != split
        or _required_env("DSH_TASK_SPLIT") != split
    ):
        raise RuntimeError("T2 fixture/task identity mismatch")
    evaluation = verify_trace(Path(_required_env("DSH_TRACE_PATH")), _required_env("DSH_TRACE_SHA256"), fixture=case)
    finished = envelope.get("finished") is True
    passed = evaluation["passed"] is True and finished
    return dict(
        reward=float(passed),
        accuracy=float(passed),
        eligible=evaluation["eligible"],
        finished=finished,
        fresh=True,
        issued_at=datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        evidence=[
            "fixture_digest:" + metadata["fixture_digest"],
            "trace_sha256:" + _required_env("DSH_TRACE_SHA256"),
            "result:" + ("passed" if passed else "failed"),
        ],
        extra_info={"task_evaluation": evaluation, "evaluation_visibility": "public"},
    )


def main():
    try:
        result = verify()
    except Exception as exc:  # noqa: BLE001 - machine-readable stdout is reserved for valid scores
        print(f"T2 verifier trusted-input failure: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
