"""Reuse the complete evidence gate against an isolated parent-SHA compatibility tool."""

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from tests.uni_agent.deployment import test_mimo_world2_acceptance as legacy

pytestmark = [pytest.mark.cpu, pytest.mark.level0]
ROOT = Path(__file__).resolve().parents[3]
OLD_SHA = "33cd6593eb0982a232db49bc8889e28047f691c314994d000508895e160f9558"
PARENT_SPEC = "5951ccbe2ab4c29705bed8655a949efafa598c16cd26670c2791b0544e6e1e33"


def module():
    path = ROOT / "docs/verl-uni-agent-harbor-opd-rl/mimo_world2_acceptance_r21.py"
    spec = importlib.util.spec_from_file_location("world2_acceptance_r21", path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


@pytest.fixture(autouse=True)
def use_isolated_auditor(monkeypatch):
    monkeypatch.setattr(legacy, "module", module)


# Preserve every existing evidence attack and parametrization against the new tool.
for _name, _function in vars(legacy).items():
    if _name.startswith("test_"):
        globals()["test_legacy_" + _name[5:]] = _function


def parent_fixture(tmp_path, *, prefixed=False):
    m, args, parent = legacy.cross_run_fixture(tmp_path)
    manifest = json.loads(args["resume_manifest"].read_text())
    manifest["run_spec_sha256"] = ("sha256:" if prefixed else "") + PARENT_SPEC
    legacy.write(args["resume_manifest"], manifest)
    args["resume_manifest_sha256"] = m.digest(args["resume_manifest"])
    return m, args, parent


def test_only_parent_representation_contract_changes():
    old = ROOT / "docs/verl-uni-agent-harbor-opd-rl/mimo_world2_acceptance.py"
    new = old.with_name("mimo_world2_acceptance_r21.py")
    raw = old.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == OLD_SHA
    before = b're.fullmatch(r"sha256:[0-9a-f]{64}", manifest["run_spec_sha256"])'
    after = b're.fullmatch(r"(?:sha256:)?[0-9a-f]{64}", manifest["run_spec_sha256"])'
    assert raw.count(before) == 1
    assert new.read_bytes() == raw.replace(before, after)


@pytest.mark.parametrize("prefixed", [False, True])
def test_full_cross_run_preserves_original_manifest_representation(tmp_path, prefixed):
    m, args, parent = parent_fixture(tmp_path, prefixed=prefixed)
    before = args["resume_manifest"].read_bytes()
    result = m.audit(**args)
    assert result["passed"], result["errors"]
    assert result["parent_checkpoint"]["checkpoint"] == str(parent)
    assert result["parent_checkpoint"]["run_spec_sha256"] == ("sha256:" if prefixed else "") + PARENT_SPEC
    assert result["parent_checkpoint"]["manifest"]["sha256"] == args["resume_manifest_sha256"]
    assert args["resume_manifest"].read_bytes() == before
    assert result["effective_update_verified"] and not result["resume_verified"]


@pytest.mark.parametrize(
    "value",
    [
        "sha256:sha256:" + PARENT_SPEC,
        "sha512:" + PARENT_SPEC,
        PARENT_SPEC.upper(),
        PARENT_SPEC[:-1],
        PARENT_SPEC + "0",
        " " + PARENT_SPEC,
        PARENT_SPEC + "\n",
        "sha256:" + PARENT_SPEC + "\n",
        "g" * 64,
        "",
        None,
        42,
        True,
    ],
)
def test_invalid_parent_identity_representation_fails_full_gate(tmp_path, value):
    m, args, _ = parent_fixture(tmp_path)
    manifest = json.loads(args["resume_manifest"].read_text())
    manifest["run_spec_sha256"] = value
    legacy.write(args["resume_manifest"], manifest)
    args["resume_manifest_sha256"] = m.digest(args["resume_manifest"])
    result = m.audit(**args)
    assert not result["passed"]
    assert any("Parent source/spec identity malformed" in error for error in result["errors"])


@pytest.mark.parametrize(
    "attack",
    [
        "manifest-sha",
        "file-sha",
        "step",
        "world",
        "fsdp",
        "source",
        "rank",
        "data",
        "reward",
        "gradient",
        "base",
        "moment",
        "current-spec",
    ],
)
def test_bare_parent_does_not_bypass_evidence_or_learning_gates(tmp_path, attack):
    m, args, parent = parent_fixture(tmp_path)
    manifest = json.loads(args["resume_manifest"].read_text())
    delta = json.loads(args["sharded_delta"].read_text())
    if attack == "manifest-sha":
        args["resume_manifest_sha256"] = "0" * 64
    elif attack == "file-sha":
        manifest["files"]["data.pt"]["sha256"] = "0" * 64
    elif attack == "step":
        manifest["step"] -= 1
    elif attack == "world":
        manifest["world_size"] = 1
    elif attack == "fsdp":
        path = legacy.write(parent / "actor/fsdp_config.json", {"FSDP_version": 2, "world_size": 2})
        manifest["files"]["actor/fsdp_config.json"] = {k: v for k, v in legacy.file_info(path).items() if k != "path"}
    elif attack == "source":
        manifest["source_commit"] = "x" * 40
    elif attack == "rank":
        manifest["files"].pop("actor/model_world_size_2_rank_1.pt")
    elif attack == "data":
        (parent / "data.pt").write_bytes(b"changed dataloader state")
    elif attack == "reward":
        batch = json.loads(args["batch_audit"].read_text())
        batch["groups"][0]["rewards"] = [1] * 4
        legacy.write(args["batch_audit"], batch)
    elif attack == "gradient":
        metrics = args["console_metrics"]
        metrics.write_text(metrics.read_text().replace("grad_norm:0.25", "grad_norm:0"))
    elif attack == "base":
        delta["ranks"][0]["model"]["base.weight"]["local"][0].update(changed=True, max_abs_delta=1.0)
    elif attack == "moment":
        delta["ranks"][1]["optimizer"]["after"]["nonzero_moment_tensors"] = 0
    elif attack == "current-spec":
        args["expected_spec"] = args["expected_spec"].removeprefix("sha256:")
    legacy.write(args["sharded_delta"], delta)
    legacy.write(args["resume_manifest"], manifest)
    if attack != "manifest-sha":
        args["resume_manifest_sha256"] = m.digest(args["resume_manifest"])
    result = m.audit(**args)
    assert not result["passed"] and not result["effective_update_verified"] and result["errors"]
