import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path

import pytest

pytestmark = [pytest.mark.cpu, pytest.mark.level0]
MODULE = Path(__file__).resolve().parents[3] / "docs/verl-uni-agent-harbor-opd-rl/mimo_r10_preparation.py"


def module():
    spec = importlib.util.spec_from_file_location("r10_preparation", MODULE)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


@pytest.fixture
def frozen(tmp_path):
    m = module()
    files = {}
    for name in m.REQUIRED_SOURCE:
        path = tmp_path / "run-src-r10" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"frozen\n")
        files[name] = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size}
    manifest = tmp_path / "integration-check/source-r10-manifest.json"
    manifest.parent.mkdir()
    manifest.write_text(json.dumps({"git_commit": "a" * 40, "files": files}))
    checkpoint = tmp_path / "runs/r9/rl-training/checkpoints/global_step_2"
    for name in m.CHECKPOINT_FILES:
        path = checkpoint / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"checkpoint")
    (checkpoint.parent / "latest_checkpointed_iteration.txt").write_text("2\n")
    return tmp_path


def test_resume_c2_to_absolute_step_three_and_fixed_deadline(frozen):
    m = module()
    plan = m.validate_runtime(frozen, "resume", "a" * 40, m.DEADLINE - 2000)
    assert plan["training_flags"] == [
        "--total-training-steps",
        "3",
        "--save-freq",
        "1",
        "--resume-from-path",
        str(frozen / "runs/r9/rl-training/checkpoints/global_step_2"),
    ]
    assert plan["wall_clock_seconds"] == 1820
    assert m.validate_runtime(frozen, "resume", "a" * 40, m.DEADLINE - 1000)["wall_clock_seconds"] == 820


@pytest.mark.parametrize("mode", [None, "fresh", "auto", ""])
def test_never_silently_falls_back_to_fresh(frozen, mode):
    m = module()
    with pytest.raises(ValueError, match="resume"):
        m.validate_runtime(frozen, mode, "a" * 40, m.DEADLINE - 2000)


@pytest.mark.parametrize(
    "attack", ["commit", "hash", "traversal", "late", "early", "missing", "symlink", "c2", "latest"]
)
def test_rejects_unbound_source_or_incomplete_checkpoint(frozen, attack):
    m = module()
    commit, now = "a" * 40, m.DEADLINE - 2000
    path = frozen / "integration-check/source-r10-manifest.json"
    data = json.loads(path.read_text())
    source = frozen / "run-src-r10" / next(iter(data["files"]))
    if attack == "commit":
        commit = "b" * 40
    elif attack == "hash":
        source.write_bytes(b"changed")
    elif attack == "traversal":
        data["files"]["../outside"] = next(iter(data["files"].values()))
    elif attack == "late":
        now = m.DEADLINE - 779
    elif attack == "early":
        now = m.DEADLINE - 18001
    elif attack == "missing":
        data["files"].pop(next(iter(m.REQUIRED_SOURCE)))
    elif attack == "symlink":
        target = frozen / "outside"
        source.rename(target)
        source.symlink_to(target)
    elif attack == "c2":
        (frozen / "runs/r9/rl-training/checkpoints/global_step_2/actor/optim_world_size_1_rank_0.pt").unlink()
    else:
        (frozen / "runs/r9/rl-training/checkpoints/latest_checkpointed_iteration.txt").write_text("1")
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        m.validate_runtime(frozen, "resume", commit, now)


@pytest.mark.parametrize("now", [True, float("nan"), float("inf"), "1790685801"])
def test_invalid_clock(frozen, now):
    with pytest.raises(ValueError, match="clock"):
        module().validate_runtime(frozen, "resume", "a" * 40, now)


def test_runtime_gate_requires_explicit_environment(frozen, monkeypatch):
    m = module()
    monkeypatch.setattr(m, "ROOT", frozen)
    monkeypatch.setattr("time.time", lambda: m.DEADLINE - 2000)
    monkeypatch.setenv("MIMO_R10_MODE", "resume")
    monkeypatch.setenv("MIMO_R10_SOURCE_COMMIT", "a" * 40)
    assert m.runtime_gate()["mode"] == "resume"
    monkeypatch.delenv("MIMO_R10_MODE")
    with pytest.raises(ValueError):
        m.runtime_gate()


def test_unreviewed_template_rejected():
    m = module()
    with pytest.raises(ValueError, match="template"):
        m.render_scripts({name: "tampered" for name in m.TEMPLATE_SHA})


@pytest.mark.skipif(
    not os.environ.get("MIMO_R9_REVIEWED_TEMPLATES"), reason="Requires the SHA-bound cloud operator templates"
)
def test_actual_reviewed_templates_stage_without_starting(tmp_path, monkeypatch, capsys):
    m = module()
    root = Path(os.environ["MIMO_R9_REVIEWED_TEMPLATES"])
    names = {"prepare": "prepare-r9.py", "driver": "launch-r9-driver.py", "wrapper": "mimo-supervised-native-r9.py"}
    templates = {name: (root / filename).read_text() for name, filename in names.items()}
    argv = ["stage", "--output", str(tmp_path / "bundle")]
    for name, filename in names.items():
        argv += ["--" + name + "-template", str(root / filename)]
    monkeypatch.setattr("sys.argv", argv)
    m.main()
    report = json.loads(capsys.readouterr().out)
    assert report["training_started"] is False
    for name, sha in report["files"].items():
        path = tmp_path / "bundle" / name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == sha
        ast.parse(path.read_text())
        assert path.stat().st_mode & 0o777 == 0o600
    driver = (tmp_path / "bundle/launch-r10-driver.py").read_text()
    assert "'CUDA_VISIBLE_DEVICES':'0,1'" in driver
    assert "ray-r10" in driver
    assert "gpu-preflight-r10" in driver
    assert "'separate_async'" in driver
    assert "spec['deadline_unix'] - time.time() - 180" in driver
    prepare = (tmp_path / "bundle/prepare-r10.py").read_text()
    assert all(str(port) in prepare for port in range(38660, 38664))
    assert "gpu-known-hosts-r8" in prepare
    assert "gpu-discovery-r8" in prepare
    assert "mimo9b-001661-r10" in prepare
    assert "MIMO_R10_SOURCE_COMMIT" in prepare
    wrapper = (tmp_path / "bundle/mimo-supervised-native-r10.py").read_text()
    assert "mimo-9b-separate-async.yaml" in wrapper
    assert "r10_plan['training_flags']" in wrapper
    with pytest.raises(FileExistsError):
        m.stage(tmp_path / "bundle", templates)


def test_checked_replacements_reject_missing_or_duplicate_fragments():
    m = module()
    for text in ("absent", "repeat repeat"):
        with pytest.raises(ValueError, match="fragment"):
            m.replace_checked(text, "repeat", "new", 1)


@pytest.fixture
def preflight(frozen):
    m = module()
    overlay = frozen / "env-overlays/r10-cupy"
    packages = overlay / "packages"
    packages.mkdir(parents=True)
    (packages / "cupy.py").write_bytes(b"fake test fixture")
    manifest = {
        "schema_version": 1,
        "overlay_path": str(packages),
        "python": m.PYTHON,
        "env": {"PYTHONPATH_PREFIX": str(packages), "LD_LIBRARY_PATH_PREFIX": m.NCCL_LIB},
        "files": [{"path": "cupy.py", "bytes": 17, "sha256": hashlib.sha256(b"fake test fixture").hexdigest()}],
    }
    (overlay / "manifest.json").write_text(json.dumps(manifest))
    status = {
        "status": "passed",
        "mode": "separate_async",
        "backend": "nccl",
        "tests": 2,
        "skipped": 0,
        "errors": 0,
        "failures": 0,
        "versions_per_test": 3,
        "overlay_manifest_sha256": hashlib.sha256((overlay / "manifest.json").read_bytes()).hexdigest(),
        "native_source_sha256": hashlib.sha256((frozen / "run-src-r10" / m.NATIVE_ENGINE).read_bytes()).hexdigest(),
        "results": [
            {
                "rebuild_group": rebuild,
                "identities": [{"uuid": "GPU-a"}, {"uuid": "GPU-b"}],
                "rounds": [
                    [{"version": version, "sent": 3}, {"version": version, "exact_equal": True, "tensors": 3}]
                    for version in (2, 3, 4)
                ],
            }
            for rebuild in (False, True)
        ],
    }
    status_path = frozen / "gpu-preflight-r10/status.json"
    status_path.parent.mkdir()
    status_path.write_text(json.dumps(status))
    return frozen, status_path, overlay


def test_training_environment_binds_real_preflight_overlay_and_source(preflight):
    frozen, _, overlay = preflight
    m = module()
    assert m.training_environment(frozen) == {
        "PYTHONPATH": str(overlay / "packages")
        + ":"
        + str(frozen / "run-src-r10")
        + ":"
        + str(frozen / "run-src-r10/verl"),
        "LD_LIBRARY_PATH": m.NCCL_LIB,
    }


@pytest.mark.parametrize(
    "attack", ["failed", "same-gpu", "old-version", "different-source", "changed-overlay", "bad-hash", "symlink"]
)
def test_training_environment_rejects_unproven_transport(preflight, attack):
    frozen, status_path, overlay = preflight
    status = json.loads(status_path.read_text())
    if attack == "failed":
        status["status"] = "failed"
    elif attack == "same-gpu":
        status["results"][0]["identities"][1]["uuid"] = "GPU-a"
    elif attack == "old-version":
        status["results"][0]["rounds"][1][1]["version"] = 2
    elif attack == "different-source":
        status["native_source_sha256"] = "0" * 64
    elif attack == "changed-overlay":
        (overlay / "packages/cupy.py").write_bytes(b"changed")
    elif attack == "bad-hash":
        status["overlay_manifest_sha256"] = "0" * 64
    else:
        path = overlay / "packages/cupy.py"
        target = overlay / "outside"
        path.rename(target)
        path.symlink_to(target)
    status_path.write_text(json.dumps(status))
    with pytest.raises(ValueError):
        module().training_environment(frozen)
