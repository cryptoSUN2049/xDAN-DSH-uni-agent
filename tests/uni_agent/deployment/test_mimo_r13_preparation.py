import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path

import pytest

pytestmark = [pytest.mark.cpu, pytest.mark.level0]
MODULE = Path(__file__).resolve().parents[3] / "docs/verl-uni-agent-harbor-opd-rl/mimo_r13_preparation.py"


def module():
    spec = importlib.util.spec_from_file_location("r13_preparation", MODULE)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


@pytest.fixture
def frozen(tmp_path):
    m = module()
    files = {}
    for name in m.REQUIRED_SOURCE:
        path = tmp_path / "run-src-r13" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"frozen\n")
        files[name] = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size}
    manifest = tmp_path / "integration-check/source-r13-manifest.json"
    manifest.parent.mkdir()
    manifest.write_text(json.dumps({"git_commit": "a" * 40, "files": files}))
    return tmp_path


def test_fresh_dual_to_absolute_step_two_and_fixed_deadline(frozen):
    m = module()
    plan = m.validate_runtime(frozen, "fresh", "a" * 40, m.DEADLINE - 3600)
    assert plan["training_flags"] == [
        "--total-training-steps",
        "2",
        "--save-freq",
        "1",
    ]
    assert plan["wall_clock_seconds"] == 3420
    assert m.validate_runtime(frozen, "fresh", "a" * 40, m.DEADLINE - 3000)["wall_clock_seconds"] == 2820


@pytest.mark.parametrize("mode", [None, "resume", "auto", ""])
def test_never_accepts_rank_one_resume(frozen, mode):
    m = module()
    with pytest.raises(ValueError, match="fresh"):
        m.validate_runtime(frozen, mode, "a" * 40, m.DEADLINE - 3600)


@pytest.mark.parametrize("attack", ["commit", "hash", "traversal", "late", "early", "missing", "symlink", "checkpoint"])
def test_rejects_unbound_source_or_incomplete_checkpoint(frozen, attack):
    m = module()
    commit, now = "a" * 40, m.DEADLINE - 3600
    path = frozen / "integration-check/source-r13-manifest.json"
    data = json.loads(path.read_text())
    source = frozen / "run-src-r13" / next(iter(data["files"]))
    if attack == "commit":
        commit = "b" * 40
    elif attack == "hash":
        source.write_bytes(b"changed")
    elif attack == "traversal":
        data["files"]["../outside"] = next(iter(data["files"].values()))
    elif attack == "late":
        now = m.DEADLINE - 2699
    elif attack == "early":
        now = m.DEADLINE - 21601
    elif attack == "missing":
        data["files"].pop(next(iter(m.REQUIRED_SOURCE)))
    elif attack == "symlink":
        target = frozen / "outside"
        source.rename(target)
        source.symlink_to(target)
    elif attack == "checkpoint":
        (frozen / "runs/r13/rl-training/checkpoints").mkdir(parents=True)
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        m.validate_runtime(frozen, "fresh", commit, now)


@pytest.mark.parametrize("now", [True, float("nan"), float("inf"), "1790685801"])
def test_invalid_clock(frozen, now):
    with pytest.raises(ValueError, match="clock"):
        module().validate_runtime(frozen, "fresh", "a" * 40, now)


def test_runtime_gate_requires_explicit_environment(frozen, monkeypatch):
    m = module()
    monkeypatch.setattr(m, "ROOT", frozen)
    monkeypatch.setattr("time.time", lambda: m.DEADLINE - 3600)
    monkeypatch.setenv("MIMO_R13_MODE", "fresh")
    monkeypatch.setenv("MIMO_R13_SOURCE_COMMIT", "a" * 40)
    assert m.runtime_gate()["mode"] == "fresh"
    monkeypatch.delenv("MIMO_R13_MODE")
    with pytest.raises(ValueError):
        m.runtime_gate()


def test_unreviewed_template_rejected():
    m = module()
    with pytest.raises(ValueError, match="template"):
        m.render_scripts({name: "tampered" for name in m.TEMPLATE_SHA})


@pytest.mark.skipif(
    not os.environ.get("MIMO_R12_REVIEWED_TEMPLATES"), reason="Requires the SHA-bound cloud operator templates"
)
def test_actual_reviewed_templates_stage_without_starting(tmp_path, monkeypatch, capsys):
    m = module()
    root = Path(os.environ["MIMO_R12_REVIEWED_TEMPLATES"])
    names = {"prepare": "prepare-r12.py", "driver": "launch-r12-driver.py", "wrapper": "mimo-supervised-native-r12.py"}
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
    driver = (tmp_path / "bundle/launch-r13-driver.py").read_text()
    assert "'CUDA_VISIBLE_DEVICES':'0,1'" in driver
    assert "ray-r13" in driver
    assert "validate_ipc_evidence" in driver
    assert "gpu-preflight-r10" not in driver
    assert "separate_async" not in driver
    assert "spec['deadline_unix'] - time.time() - 180" in driver
    prepare = (tmp_path / "bundle/prepare-r13.py").read_text()
    assert all(str(port) in prepare for port in range(38690, 38694))
    assert "gpu-known-hosts-r8" in prepare
    assert "gpu-discovery-r8" in prepare
    assert "mimo9b-001661-r13" in prepare
    assert "MIMO_R13_SOURCE_COMMIT" in prepare
    wrapper = (tmp_path / "bundle/mimo-supervised-native-r13.py").read_text()
    assert "mimo-9b-dual-colocate-observed.yaml" in wrapper
    assert "r13_plan['training_flags']" in wrapper
    assert "'--experiment-name', 'mimo9b-001661-r13'" in wrapper
    assert "'--observability-wrapper'" in wrapper
    assert "'WANDB_MODE':'online'" in driver
    assert "observability_environment" in driver
    assert "audit-code/r13-preparation/" in driver
    assert "audit-code/r12-preparation/" not in driver
    assert "audit-code/r13-preparation/" in prepare
    assert "audit-code/r13-preparation/" in wrapper
    with pytest.raises(FileExistsError):
        m.stage(tmp_path / "bundle", templates)


def test_checked_replacements_reject_missing_or_duplicate_fragments():
    m = module()
    for text in ("absent", "repeat repeat"):
        with pytest.raises(ValueError, match="fragment"):
            m.replace_checked(text, "repeat", "new", 1)


@pytest.fixture
def preflight(frozen, monkeypatch):
    m = module()
    monkeypatch.setattr(
        m,
        "NATIVE_SOURCE",
        {name: hashlib.sha256((frozen / "run-src-r13" / name).read_bytes()).hexdigest() for name in m.NATIVE_SOURCE},
    )
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
    monkeypatch.setattr(m, "OVERLAY_SHA", hashlib.sha256((overlay / "manifest.json").read_bytes()).hexdigest())
    baseline = frozen / "gpu-preflight-r9/status.json"
    baseline.parent.mkdir()
    baseline.write_text(json.dumps(dict(status="passed", exit_code=0, tests=1, skipped=0, errors=0, failures=0)))
    status = {
        "operator_sha256": hashlib.sha256(
            (frozen / "run-src-r13/docs/verl-uni-agent-harbor-opd-rl/mimo_dual_colocate_probe.py").read_bytes()
        ).hexdigest(),
        "schema": "mimo.dual-colocate-ipc.v1",
        "status": "passed",
        "mode": "colocate_async",
        "backend": "naive",
        "gpu_indexes": [0, 1],
        "tests": 4,
        "skipped": 0,
        "errors": 0,
        "failures": 0,
        "source_sha256": m.NATIVE_SOURCE,
        "lanes": [
            dict(gpu_index=i, gpu_uuid="GPU-" + str(i), tests=2, skipped=0, errors=0, failures=0) for i in range(2)
        ],
    }
    status_path = frozen / "integration-check/dual-colocate-r13-v2/status.json"
    status_path.parent.mkdir()
    status_path.write_text(json.dumps(status))
    return m, frozen, status_path, overlay


def test_training_environment_binds_real_preflight_overlay_and_source(preflight):
    m, frozen, _, overlay = preflight
    assert m.training_environment(frozen) == {
        "PYTHONPATH": str(overlay / "packages")
        + ":"
        + str(frozen / "run-src-r13")
        + ":"
        + str(frozen / "run-src-r13/verl"),
        "LD_LIBRARY_PATH": m.NCCL_LIB,
    }


@pytest.mark.parametrize(
    "attack",
    [
        "failed",
        "same-gpu",
        "nccl",
        "skipped",
        "different-source",
        "changed-overlay",
        "symlink",
        "traversal",
        "baseline",
    ],
)
def test_training_environment_rejects_unproven_transport(preflight, attack):
    m, frozen, status_path, overlay = preflight
    status = json.loads(status_path.read_text())
    if attack == "failed":
        status["status"] = "failed"
    elif attack == "same-gpu":
        status["lanes"][1]["gpu_uuid"] = "GPU-0"
    elif attack == "nccl":
        status["backend"] = "nccl"
    elif attack == "skipped":
        status["lanes"][1]["skipped"] = 1
    elif attack == "different-source":
        status["source_sha256"] = {**status["source_sha256"], next(iter(m.NATIVE_SOURCE)): "0" * 64}
    elif attack == "changed-overlay":
        (overlay / "packages/cupy.py").write_bytes(b"changed")
    elif attack == "traversal":
        status["source_sha256"]["../outside"] = "0" * 64
    elif attack == "baseline":
        (frozen / "gpu-preflight-r9/status.json").write_text(json.dumps(dict(status="failed")))
    else:
        path = overlay / "packages/cupy.py"
        target = overlay / "outside"
        path.rename(target)
        path.symlink_to(target)
    status_path.write_text(json.dumps(status))
    with pytest.raises(ValueError):
        m.training_environment(frozen)


def test_observability_identity_is_unique_online_and_keeps_secrets_out():
    m = module()
    env = m.observability_environment()
    assert env["WANDB_RUN_ID"] == "mimo9b001661r13"
    assert env["WANDB_RESUME"] == "never"
    assert env["WANDB_MODE"] == "online"
    assert env["WANDB_ENTITY"] == "xdan-ai"
    assert env["WANDB_PROJECT"] == "xDAN-Verl-Uni-agent-Harbor-rl-opd"
    assert env["WANDB_NAME"] == "mimo9b-001661-r13"
    assert env["VERL_RL_INSIGHT_ENABLE"] == "1"
    assert env["RL_INSIGHT_SERVER_URL"] == "http://127.0.0.1:18080"
    assert env["MIMO_PROMETHEUS_URL"] == "http://127.0.0.1:9090"
    assert env["WANDB_DIR"].startswith("/root/mimo-private/")
    assert not any("KEY" in key or "TOKEN" in key for key in env)


def test_authorized_extension_preserves_absolute_stop_and_generic_six_hour_cap(frozen):
    m = module()
    assert m.DEADLINE == 1790709401
    assert m.MAX_RUN_SECONDS == 21600
    eligible_at = 1790687801  # New stop minus six-hour generic controller cap.
    with pytest.raises(ValueError, match="unauthorized absolute run window"):
        m.validate_runtime(frozen, "fresh", "a" * 40, eligible_at - 1)
    first = m.validate_runtime(frozen, "fresh", "a" * 40, eligible_at)
    later = m.validate_runtime(frozen, "fresh", "a" * 40, eligible_at + 300)
    assert first["controller_max_run_seconds"] == 21600
    assert first["deadline_unix"] == later["deadline_unix"] == 1790709401
    assert first["wall_clock_seconds"] == 21420
    assert later["wall_clock_seconds"] == 21120
