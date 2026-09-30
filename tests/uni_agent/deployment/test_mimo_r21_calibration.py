"""Cloud CPU contract tests; real fixed inputs are read-only, no Modal allocation."""

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path

import pytest


@pytest.fixture
def subject(monkeypatch):
    path = Path(os.environ["MIMO_R21_CALIBRATION_PATH"])
    spec = importlib.util.spec_from_file_location("r21_calibration_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "")
    config = json.loads(Path(os.environ["MIMO_R21_CALIBRATION_CONFIG"]).read_bytes())
    return module, config


def test_actual_input_contract_is_read_only_and_current(subject):
    module, config = subject
    values = module.validate_inputs(config, 1790792500)
    assert values[0]["pod_id"] == "vo6u0t8x398bnm"
    assert values[1]["instance_id"] == "format-code-task-002549"
    assert values[2]["task_ref"]["sha256"].startswith("sha256:")
    assert not values[-1].exists()


@pytest.mark.parametrize("now", [1790791472, 1790812293, 1790813073, 1790813074])
def test_window_rejects_before_allocation(subject, now):
    module, config = subject
    with pytest.raises(ValueError, match="authorization/window"):
        module.validate_inputs(config, now)


@pytest.mark.parametrize(
    "key,value",
    [
        ("pod_id", "foreign-pod"),
        ("allocated_at_unix", 1790791474),
        ("deadline_unix", 1790813074),
        ("max_run_seconds", 21601),
        ("cleanup_reserve_seconds", 0),
        ("stage", "r20e"),
        ("schema", "legacy"),
    ],
)
def test_wrong_authorization_identity_rejected(subject, monkeypatch, key, value):
    module, config = subject
    original = module.bound

    def changed(path, expected):
        raw = original(path, expected)
        if str(path) == config["authorization_path"]:
            record = json.loads(raw)
            record[key] = value
            return json.dumps(record).encode()
        return raw

    monkeypatch.setattr(module, "bound", changed)
    with pytest.raises(ValueError, match="authorization/window"):
        module.validate_inputs(config, 1790792500)


@pytest.mark.parametrize(
    "target,key,value",
    [
        ("candidate_provenance", "hidden_test_patch_read_for_authorship", True),
        ("candidate_provenance", "hidden_test_files_read_for_authorship", True),
        ("candidate_provenance", "verifier_output_read_for_authorship", True),
        ("candidate_provenance", "patch_sha256", "0" * 64),
        ("candidate_provenance", "public_source_sha256", "0" * 64),
        ("public_source_path", "problem_statement", "another task"),
        ("task_package_manifest", "source_revision", "0" * 40),
        ("task_package_manifest", "task_id", "format-code-task-001661"),
        ("task_package_manifest", "source_row_hash", "sha256:" + "0" * 64),
        ("task_package_manifest", "test_patch_sha256", "sha256:" + "0" * 64),
        ("image_binding", "dsh_image", "foreign-image"),
        ("image_binding", "original_image", "foreign-image"),
    ],
)
def test_input_identity_and_hidden_feedback_fail_closed(subject, monkeypatch, target, key, value):
    module, config = subject
    original = module.bound

    def changed(path, expected):
        raw = original(path, expected)
        if str(path) == config[target]:
            record = json.loads(raw)
            record[key] = value
            return json.dumps(record).encode()
        return raw

    monkeypatch.setattr(module, "bound", changed)
    with pytest.raises(ValueError):
        module.validate_inputs(config, 1790792500)


@pytest.mark.parametrize(
    "key",
    [
        "authorization_sha256",
        "row_sha256",
        "task_package_manifest_sha256",
        "image_binding_sha256",
        "public_source_sha256",
        "candidate_sha256",
        "candidate_provenance_sha256",
    ],
)
def test_actual_bound_input_sha_is_required(subject, key):
    module, config = subject
    wrong = copy.deepcopy(config)
    wrong[key] = "0" * 64
    with pytest.raises(ValueError, match="SHA differs"):
        module.validate_inputs(wrong, 1790792500)


def test_visible_cuda_rejected_before_sdk(subject, monkeypatch):
    module, config = subject
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0,1")
    with pytest.raises(ValueError, match="CPU-only"):
        module.validate_inputs(config, 1790792500)


def test_existing_output_preserved(subject, tmp_path):
    module, config = subject
    output = tmp_path / "prior-attempt"
    output.mkdir()
    sentinel = output / "receipt"
    sentinel.write_bytes(b"prior-original-evidence")
    config["output"] = str(output)
    with pytest.raises(ValueError, match="Output must be new"):
        module.validate_inputs(config, 1790792500)
    assert sentinel.read_bytes() == b"prior-original-evidence"


def test_symlink_and_changed_input_rejected(subject, tmp_path):
    module, _ = subject
    original = tmp_path / "source"
    original.write_bytes(b"fixed")
    sha = hashlib.sha256(b"fixed").hexdigest()
    link = tmp_path / "alias"
    link.symlink_to(original)
    with pytest.raises(ValueError, match="regular file"):
        module.bound(link, sha)
    original.write_bytes(b"changed")
    with pytest.raises(ValueError, match="SHA differs"):
        module.bound(original, sha)


def test_remote_python_snippets_compile_without_loading_sdk(subject):
    import ast

    module, _ = subject
    tree = ast.parse(Path(module.__file__).read_bytes())
    names = {"identity_code", "receipt_code", "measured_code", "history_code", "apply_code", "code"}
    checked = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in names for t in node.targets):
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                compile(node.value.value, "remote-python-snippet", "exec")
                checked += 1
    assert checked >= 5
