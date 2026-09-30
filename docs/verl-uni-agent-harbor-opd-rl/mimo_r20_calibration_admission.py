"""Reuse immutable-task historical calibration honestly; this executes no verifier."""

import argparse
import hashlib
import json
import os
from pathlib import Path

CALIBRATION_SHA = "4e4f3832b73dfb2abce4d490ea419cc6e1274ab4a1348964f70ef13bb7d9e10f"
NATIVE_SHA = "112dfbbb86fe99fd27ac5b48b089eae50b00743636615ecd64116a1c111b7ff1"
CURRENT_COMMIT = "1ccc1640c0f34ba5f515d3613fac6a278bd38f4c"
CURRENT_MANIFEST = "99ac03f55d4eaeebc63d2ba466452fef2af7a51af289fc135d5051dadca0591f"
WORKSPACE_SHA = "faba54386d324f0fc25b76bed6f0d81aa8f03cf926ad9c542214a6ae71b4409d"
VERIFIER_SHA = "12a6f9d3a849ff66168269f800f63325077d76a61942e9315d8335eb6d63c371"
DATA_REVISION = "639865fd3374018d6cb29b9fb82dd531406fcf5f"
MEASURED_DSH = {
    "dsh_revision": "b2369692ea530007075ebcd18d39fdba0bbd3982",
    "source_commit": "c51f6fc7dad24fd03fdc090741bc30d07488b574",
    "profile": "sdk-minimal",
    "python_distribution_version": "0.1.3a2",
    "runner_sha256": "a122de903b1775231f6ff6f70762b78500819d6c9ce8a3323b729dac64468732",
    "runtime_binary_sha256": "d1a467a9c14a38ad5f01591d2cdb125852cb1a1d3b0ecb678dfde383404e80cb",
    "runtime_rg_sha256": "193906679498de4d939345b937fa24e0e69a03c244bd70c859f5e41232713f21",
}


def bound(path, sha):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("Unsafe historical calibration path")
    raw = path.read_bytes()
    if not isinstance(sha, str) or hashlib.sha256(raw).hexdigest() != sha.removeprefix("sha256:"):
        raise ValueError("Historical calibration changed")
    return json.loads(raw)


def matches_bindings(actual, expected):
    return all(
        (isinstance(actual.get(key), str) and actual[key].removeprefix("sha256:") == value)
        if key.endswith("_sha256")
        else actual.get(key) == value
        for key, value in expected.items()
    )


def admission(spec, package, calibration_path, native_path):
    calibration = bound(calibration_path, CALIBRATION_SHA)
    native = bound(native_path, NATIVE_SHA)
    template = spec["policy_template"]
    refs = template["task_refs"]
    release = template["dsh_release"]
    if len(refs) != 1 or refs[0] != package["task_ref"] or package["task_id"] != "format-code-task-001661":
        raise ValueError("Historical evidence only admits the identical original anchor task")
    if not (
        calibration["status"] == "calibration_passed"
        and calibration["baseline_calibration"] == "passed"
        and calibration["positive_control"] == "passed"
        and calibration["task_id"] == package["task_id"]
        and calibration["dsh_image"] == package["dsh_image"]
        and calibration["original_image"] == package["original_image"]
        and calibration["test_patch_sha256"].removeprefix("sha256:")
        == package["test_patch_sha256"].removeprefix("sha256:")
        and release["image_digest"] == package["dsh_derived_image_digest"]
        and all(item["terminated"] is True for item in calibration["resources"])
        and len(calibration["resources"]) == 3
        and native["status"] == "passed"
        and native["model_requests"] == 0
        and len(native["cases"]) == 2
    ):
        raise ValueError("Historical task/image/test/calibration/cleanup identity differs")
    rewards = []
    resources = []
    for case in native["cases"]:
        if not (
            case["task_sha256"] == refs[0]["sha256"]
            and case["cleanup_confirmed"] is True
            and case["native_skip_tests_upload"] is True
            and case["agent_tests_absent_before"] is True
            and case["agent_tests_absent_after"] is True
            and case["receipt"]["test_patch_sha256"] == package["test_patch_sha256"]
            and case["reward"]["reward"] == case["receipt"]["reward"]
            and len(case["resources"]) == 2
            and all(type(item["returncode"]) is int and item["returncode"] == 137 for item in case["resources"])
        ):
            raise ValueError("Historical native verifier receipt or cleanup differs")
        for name, sha in case["verifier_test_sha256"].items():
            if package["files"]["task/tests/" + name] != "sha256:" + sha:
                raise ValueError("Historical independent verifier files differ")
        rewards.append(case["reward"]["reward"])
        resources.extend(case["resources"])
    if rewards != [0.0, 1.0]:
        raise ValueError("Historical native baseline and positive control differ")
    return {
        "schema": "mimo.r20-task-calibration-admission.v1",
        "status": "passed",
        "task_ref": refs[0],
        "dsh_release": release,
        "rewards": rewards,
        "model_requests": 0,
        "cleanup_confirmed": True,
        "historical_evidence_reused": True,
        "new_calibration_executed": False,
        "scope": "Identical frozen task, immutable images and verifier files; historical native calibration reused",
        "original_calibration": {"path": str(calibration_path), "sha256": CALIBRATION_SHA},
        "native_verifier_calibration": {"path": str(native_path), "sha256": NATIVE_SHA},
        "historical_native_resources": resources,
        "historical_source_resources": calibration["resources"],
        "resource_returncode_137_means": "terminated, not an OOM claim",
    }


def current_admission(spec, package, calibration_path, expected_sha256, package_manifest_sha256):
    """Bind raw, task-specific production CLI calibration; reject old private shims."""
    calibration = bound(calibration_path, expected_sha256)
    template = spec["policy_template"]
    refs, release = template["task_refs"], template["dsh_release"]
    results = calibration["results"]
    names = ("baseline-direct", "baseline-restored", "candidate-restored")
    ordered = [results[name] for name in names]
    cleanup = calibration["cleanup_api"]
    resources = cleanup["resources"]
    runtime = {
        "current_runtime_commit": CURRENT_COMMIT,
        "source_manifest_sha256": CURRENT_MANIFEST,
        "workspace_helper_sha256": WORKSPACE_SHA,
        "packaged_verifier_sha256": VERIFIER_SHA,
        "no_shim": True,
        "private_compatibility_injection": False,
        "task_ref": package["task_ref"],
        "immutable_package_manifest_sha256": package_manifest_sha256,
    }
    if not (
        len(refs) == 1
        and refs[0] == package["task_ref"]
        and calibration["schema"] == "mimo.r20-production-task-calibration.v1"
        and calibration["status"] in ("passed", "calibration_passed")
        and calibration["task_calibration_gate_passed"] is True
        and calibration["baseline"] == calibration["positive_control"] == "passed"
        and matches_bindings(calibration, runtime)
        and calibration.get("no_shim") is True
        and calibration.get("private_compatibility_injection") is False
        and calibration["data_revision"] == DATA_REVISION
        and calibration["dsh_image"] == package["dsh_image"]
        and calibration["original_image"] == package["original_image"]
        and calibration["dsh_release"] == MEASURED_DSH
        and calibration["dsh_release"]["dsh_revision"] == release["source_sha"]
        and calibration["dsh_release"]["profile"] == release["profile"]
        and calibration["dsh_release"]["python_distribution_version"] == "0.1.3a2"
        and calibration["packaged_test_patch_sha256"] == package["test_patch_sha256"]
        and calibration["candidate_patch_sha256"].removeprefix("sha256:")
        != package["test_patch_sha256"].removeprefix("sha256:")
        and release["image_digest"] == package["dsh_derived_image_digest"]
        and [item["reward"] for item in ordered] == [0.0, 0.0, 1.0]
        and [item["resolved"] for item in ordered] == [False, False, True]
        and all(item["status"] == "graded" for item in ordered)
        and all(type(item["reward"]) in (int, float) for item in ordered)
        and all(type(item["resolved"]) is bool for item in ordered)
        and all(type(item["verifier_returncode"]) is int for item in ordered)
        and all(type(item["test_duration"]) in (int, float) and item["test_duration"] > 0 for item in ordered)
        and ordered[0]["verifier_returncode"] != 0
        and ordered[1]["verifier_returncode"] != 0
        and ordered[2]["verifier_returncode"] == 0
        and cleanup["all_terminated"] is True
        and len(resources) == 3
        and len({item["sandbox_id"] for item in resources}) == 3
        and all(
            item["termination_confirmed"] is True and type(item["returncode"]) is int and item["returncode"] == 137
            for item in resources
        )
        and isinstance(calibration["original_python_version"], str)
        and calibration["original_python_version"].startswith("3.")
    ):
        raise ValueError("Actual current runtime/task/no-shim/test/independent cleanup differs")
    raw_path, raw_sha = calibration["raw_report_private_path"], calibration["raw_report_sha256"]
    raw = bound(raw_path, raw_sha)
    if not (
        matches_bindings(raw, runtime)
        and raw.get("no_shim") is True
        and raw.get("private_compatibility_injection") is False
    ):
        raise ValueError("Raw execution report does not carry the authorized production identity")
    hashes = raw["source_hashes"]
    base = Path("/workspace/mimo-dsh-rl-20260928/run-src-r20")
    if not (
        hashes[str(base / "uni_agent/tasks/harbor_dsh/mimo_workspace.py")] == "sha256:" + WORKSPACE_SHA
        and hashes[str(base / "examples/mimo_dsh_rl/verifier.py")] == "sha256:" + VERIFIER_SHA
    ):
        raise ValueError("Raw execution source hashes differ from the two reviewed production blobs")
    expected_tests = {name: sha for name, sha in package["files"].items() if name.startswith("task/tests/")}
    if not expected_tests or calibration["package_test_files_sha256"] != expected_tests:
        raise ValueError("Public uploaded verifier files differ from the actual immutable task package")
    expected_readback = {name.removeprefix("task/tests/"): sha for name, sha in expected_tests.items()}
    for name in names:
        public_readback = calibration["packaged_file_readback"][name]
        actual_readback = raw["packaged_file_readback"][name]
        if not (
            public_readback == actual_readback
            and actual_readback["files"] == expected_readback
            and actual_readback["version"] == calibration["original_python_version"]
            and actual_readback["executable"].endswith("/python3")
        ):
            raise ValueError("Actual original-Python per-phase packaged file readback differs")
    raw_results = raw["results"]
    for name in names:
        receipt, summary = raw_results[name], results[name]
        if not (
            all(receipt.get(key) == summary[key] for key in ("status", "reward", "resolved"))
            and type(receipt["reward"]) in (int, float)
            and type(receipt["resolved"]) is bool
        ):
            raise ValueError("Public results differ from actual raw verifier receipts")
        if receipt.get("verifier_returncode", receipt.get("returncode")) != summary["verifier_returncode"]:
            raise ValueError("Public verifier returncode differs from actual raw receipt")
        if not (
            receipt.get("schema") == "dsh.mimo-verifier-receipt.v1"
            and receipt.get("test_patch_sha256") == package["test_patch_sha256"]
            and receipt.get("test_duration") == summary["test_duration"]
            and isinstance(receipt.get("base_ref"), str)
            and len(receipt["base_ref"]) == 40
            and receipt.get("gateway_session_id")
            == "operator-production-calibration-" + refs[0]["id"].rsplit("-", 1)[-1]
        ):
            raise ValueError("Actual per-case verifier receipt identity differs")
    baseline, restored, candidate = [raw_results[name] for name in names]
    if not (
        baseline["base_ref"] == restored["base_ref"] == candidate["base_ref"]
        and baseline["snapshot_sha256"] == restored["snapshot_sha256"]
        and baseline["snapshot_sha256"] != candidate["snapshot_sha256"]
    ):
        raise ValueError("Actual independent baseline/candidate workspaces differ from calibration contract")
    return {
        "schema": "mimo.r20-task-calibration-admission.v1",
        "status": "passed",
        "task_ref": refs[0],
        "dsh_release": release,
        "rewards": [ordered[0]["reward"], ordered[2]["reward"]],
        "model_requests": 0,
        "model_request_count_scope": "Verifier-only operator path; no model runner invoked",
        "cleanup_confirmed": True,
        "historical_evidence_reused": False,
        "calibration_executed_in_current_window": True,
        "actual_calibration": {"path": str(calibration_path), "sha256": expected_sha256},
        "actual_calibration_results": results,
        "actual_resources": resources,
        "runtime_bindings": runtime,
        "raw_execution_report": {"path": raw_path, "sha256": raw_sha.removeprefix("sha256:")},
        "raw_receipts_verified": list(names),
        "actual_raw_verifier_receipts": raw_results,
        "original_python_version": calibration["original_python_version"],
        "packaged_file_readback": raw["packaged_file_readback"],
        "production_verifier_compatibility_verified_by_this_adapter": True,
        "gpu_start_authorized_by_this_report": False,
        "scope": "Task-specific original-Python packaged production CLI, raw receipts and independent cleanup",
        "resource_returncode_137_means": "terminated, not an OOM claim",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("historical", "current"))
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--spec-sha256", required=True)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--package-sha256", required=True)
    parser.add_argument("--calibration", type=Path, required=True)
    parser.add_argument("--calibration-sha256")
    parser.add_argument("--native", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if os.environ.get("CUDA_VISIBLE_DEVICES") != "":
        raise ValueError("Calibration admission must execute on explicit CPU-only environment")
    spec = bound(args.spec, args.spec_sha256)
    package = bound(args.package, args.package_sha256)
    if args.action == "historical":
        report = admission(spec, package, args.calibration, args.native)
    else:
        report = current_admission(spec, package, args.calibration, args.calibration_sha256, args.package_sha256)
    report["adapter_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as output:
        json.dump(report, output, indent=2, sort_keys=True, allow_nan=False)
        output.write("\n")
    print(json.dumps({"status": report["status"], "output": str(args.output), "training_started": False}))


if __name__ == "__main__":
    main()
