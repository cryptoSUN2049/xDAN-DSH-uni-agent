"""Fail-closed admission for original-Python production calibration and raw cases."""

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.cpu, pytest.mark.level0]


@pytest.fixture
def module():
    path = Path(
        os.environ.get(
            "MIMO_R20_ADMISSION_PATH",
            str(
                Path(__file__).resolve().parents[3]
                / "docs/verl-uni-agent-harbor-opd-rl/mimo_r20_calibration_admission.py"
            ),
        )
    )
    spec = importlib.util.spec_from_file_location("r20_admission_test", path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


@pytest.fixture
def inputs(module, tmp_path):
    ref = {"id": "mimo-code-format-code-task-002549", "version": "v1", "sha256": "sha256:" + "a" * 64}
    release = {
        "image_digest": "sha256:" + "b" * 64,
        "source_sha": "b2369692ea530007075ebcd18d39fdba0bbd3982",
        "profile": "sdk-minimal",
    }
    package = {
        "task_ref": ref,
        "dsh_image": "registry.example/dsh@sha256:" + "b" * 64,
        "original_image": "registry.example/original@sha256:" + "c" * 64,
        "dsh_derived_image_digest": release["image_digest"],
        "test_patch_sha256": "sha256:" + "d" * 64,
        "files": {"task/tests/verifier.py": "sha256:" + module.VERIFIER_SHA},
    }
    spec = {"policy_template": {"task_refs": [ref], "dsh_release": release}}
    manifest_sha = "e" * 64
    runtime = {
        "current_runtime_commit": module.CURRENT_COMMIT,
        "source_manifest_sha256": module.CURRENT_MANIFEST,
        "workspace_helper_sha256": module.WORKSPACE_SHA,
        "packaged_verifier_sha256": module.VERIFIER_SHA,
        "no_shim": True,
        "private_compatibility_injection": False,
        "task_ref": ref,
        "immutable_package_manifest_sha256": manifest_sha,
    }
    names = ("baseline-direct", "baseline-restored", "candidate-restored")
    results = {
        name: {
            "status": "graded",
            "reward": reward,
            "resolved": bool(reward),
            "verifier_returncode": 0 if reward else 1,
            "test_duration": 0.25,
        }
        for name, reward in zip(names, [0.0, 0.0, 1.0], strict=True)
    }
    base = Path("/workspace/mimo-dsh-rl-20260928/run-src-r20")
    raw = {
        **runtime,
        "results": results,
        "source_hashes": {
            str(base / "uni_agent/tasks/harbor_dsh/mimo_workspace.py"): "sha256:" + module.WORKSPACE_SHA,
            str(base / "examples/mimo_dsh_rl/verifier.py"): "sha256:" + module.VERIFIER_SHA,
        },
        "packaged_file_readback": {
            name: {
                "files": {"verifier.py": "sha256:" + module.VERIFIER_SHA},
                "version": "3.10.18",
                "executable": "/usr/local/bin/python3",
            }
            for name in names
        },
    }
    for name, case in raw["results"].items():
        case.update(
            schema="dsh.mimo-verifier-receipt.v1",
            test_patch_sha256=package["test_patch_sha256"],
            base_ref="1" * 40,
            gateway_session_id="operator-production-calibration-002549",
            snapshot_sha256="sha256:" + ("2" if name == "candidate-restored" else "3") * 64,
        )
    raw_path = tmp_path / "raw.json"
    raw_path.write_text(json.dumps(raw))
    import hashlib

    sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    public = {
        **runtime,
        "schema": "mimo.r20-production-task-calibration.v1",
        "status": "passed",
        "task_calibration_gate_passed": True,
        "baseline": "passed",
        "positive_control": "passed",
        "data_revision": module.DATA_REVISION,
        "dsh_image": package["dsh_image"],
        "original_image": package["original_image"],
        "dsh_release": dict(module.MEASURED_DSH),
        "packaged_test_patch_sha256": package["test_patch_sha256"],
        "candidate_patch_sha256": "sha256:" + "f" * 64,
        "results": results,
        "cleanup_api": {
            "all_terminated": True,
            "resources": [
                {"sandbox_id": f"synthetic-case-{i}", "termination_confirmed": True, "returncode": 137}
                for i in range(3)
            ],
        },
        "original_python_version": "3.10.18",
        "raw_report_private_path": str(raw_path),
        "raw_report_sha256": sha(raw_path),
        "package_test_files_sha256": package["files"],
        "packaged_file_readback": raw["packaged_file_readback"],
    }
    public_path = tmp_path / "public.json"
    public_path.write_text(json.dumps(public))
    return spec, package, public_path, manifest_sha, raw_path, sha


def test_real_raw_case_binding_and_current_production_identity(module, inputs):
    spec, package, path, manifest_sha, _, sha = inputs
    report = module.current_admission(spec, package, path, sha(path), manifest_sha)
    assert report["status"] == "passed" and report["rewards"] == [0.0, 1.0]
    assert report["production_verifier_compatibility_verified_by_this_adapter"] is True
    assert report["gpu_start_authorized_by_this_report"] is False
    assert report["runtime_bindings"]["no_shim"] is True
    assert report["raw_receipts_verified"] == ["baseline-direct", "baseline-restored", "candidate-restored"]


@pytest.mark.parametrize(
    "fault",
    [
        "old-runtime",
        "shim",
        "missing-shim-field",
        "wrong-package",
        "active-resource",
        "zero-candidate",
        "bool-reward",
        "public-raw-disagree",
        "raw-hash-mismatch",
        "raw-identity-mismatch",
        "old-source-bytes",
        "receipt-test-patch",
        "receipt-session",
        "candidate-equals-baseline",
    ],
)
def test_public_success_cannot_replace_actual_production_receipts(module, inputs, fault):
    spec, package, path, manifest_sha, raw_path, sha = inputs
    public = json.loads(path.read_text())
    raw = json.loads(raw_path.read_text())
    if fault == "old-runtime":
        public["current_runtime_commit"] = "4dbd87ad4f6123f99a1f715a6637322a44cff6a5"
    elif fault == "shim":
        public["private_compatibility_injection"] = True
    elif fault == "missing-shim-field":
        public.pop("no_shim")
    elif fault == "wrong-package":
        public["immutable_package_manifest_sha256"] = "0" * 64
    elif fault == "active-resource":
        public["cleanup_api"]["resources"][0]["returncode"] = None
    elif fault == "zero-candidate":
        public["results"]["candidate-restored"]["reward"] = 0.0
    elif fault == "bool-reward":
        public["results"]["candidate-restored"]["reward"] = True
    elif fault == "public-raw-disagree":
        raw["results"]["candidate-restored"]["reward"] = 0.0
    elif fault == "raw-identity-mismatch":
        raw["no_shim"] = False
    elif fault == "old-source-bytes":
        raw["source_hashes"][
            str(Path("/workspace/mimo-dsh-rl-20260928/run-src-r20/examples/mimo_dsh_rl/verifier.py"))
        ] = "sha256:" + "0" * 64
    elif fault == "receipt-test-patch":
        raw["results"]["candidate-restored"]["test_patch_sha256"] = "sha256:" + "0" * 64
    elif fault == "receipt-session":
        raw["results"]["candidate-restored"]["gateway_session_id"] = "claimed-native-training-session"
    elif fault == "candidate-equals-baseline":
        raw["results"]["candidate-restored"]["snapshot_sha256"] = raw["results"]["baseline-direct"]["snapshot_sha256"]
    else:
        raw["unbound_mutation"] = True
    raw_path.write_text(json.dumps(raw))
    if fault != "raw-hash-mismatch":
        public["raw_report_sha256"] = sha(raw_path)
    path.write_text(json.dumps(public))
    with pytest.raises((ValueError, KeyError)):
        module.current_admission(spec, package, path, sha(path), manifest_sha)


@pytest.mark.parametrize("fault", [None, "gpu-visible", "existing-output"])
def test_cli_cpu_boundary_and_exclusive_private_output(module, inputs, tmp_path, monkeypatch, fault):
    spec, package, path, _, raw_path, sha = inputs
    spec_path, package_path = tmp_path / "spec.json", tmp_path / "manifest.json"
    spec_path.write_text(json.dumps(spec))
    package_path.write_text(json.dumps(package))
    public, raw = json.loads(path.read_text()), json.loads(raw_path.read_text())
    public["immutable_package_manifest_sha256"] = raw["immutable_package_manifest_sha256"] = sha(package_path)
    raw_path.write_text(json.dumps(raw))
    public["raw_report_sha256"] = sha(raw_path)
    path.write_text(json.dumps(public))
    output = tmp_path / "admission.json"
    if fault == "existing-output":
        output.write_bytes(b"preserve existing admission")
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0" if fault == "gpu-visible" else "")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(module.__file__),
            "current",
            "--spec",
            str(spec_path),
            "--spec-sha256",
            sha(spec_path),
            "--package",
            str(package_path),
            "--package-sha256",
            sha(package_path),
            "--calibration",
            str(path),
            "--calibration-sha256",
            sha(path),
            "--output",
            str(output),
        ],
    )
    if fault:
        with pytest.raises(ValueError if fault == "gpu-visible" else FileExistsError):
            module.main()
        if fault == "existing-output":
            assert output.read_bytes() == b"preserve existing admission"
        else:
            assert not output.exists()
    else:
        module.main()
        report = json.loads(output.read_text())
        assert report["status"] == "passed" and report["adapter_sha256"] == sha(Path(module.__file__))
        assert output.stat().st_mode & 0o777 == 0o600
