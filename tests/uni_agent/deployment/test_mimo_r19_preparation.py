import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path

import pytest

pytestmark = [pytest.mark.cpu, pytest.mark.level0]
MODULE = Path(__file__).resolve().parents[3] / "docs/verl-uni-agent-harbor-opd-rl/mimo_r19_preparation.py"


def module():
    spec = importlib.util.spec_from_file_location("r19_preparation", MODULE)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def runtime(m, root, mode, commit, now):
    manifest = root / "integration-check/r17-c3-resume-manifest.json"
    sha = hashlib.sha256(manifest.read_bytes()).hexdigest() if manifest.exists() else "0" * 64
    return m.validate_runtime(root, mode, commit, now, deadline_unix=m.AUTHORIZED_DEADLINE, resume_manifest_sha256=sha)


@pytest.fixture
def frozen(tmp_path):
    m = module()
    files = {}
    for name in m.REQUIRED_SOURCE:
        path = tmp_path / "run-src-r19" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"frozen\n")
        files[name] = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size}
    manifest = tmp_path / "integration-check/source-r19-manifest.json"
    manifest.parent.mkdir()
    manifest.write_text(json.dumps({"git_commit": "a" * 40, "files": files}))
    checkpoint = tmp_path / "runs/r17/rl-training/checkpoints/global_step_3"
    identities = {}
    for name in m.CHECKPOINT_FILES:
        file = checkpoint / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(
            b'{"FSDP_version":1,"world_size":2}' if name == "actor/fsdp_config.json" else b"trusted checkpoint"
        )
        identities[name] = {"bytes": file.stat().st_size, "sha256": hashlib.sha256(file.read_bytes()).hexdigest()}
    (checkpoint.parent / "latest_checkpointed_iteration.txt").write_text("3\n")
    (tmp_path / "integration-check/r17-c3-resume-manifest.json").write_text(
        json.dumps(
            {
                "schema": "mimo.native-checkpoint-manifest.v1",
                "run_id": "mimo9b-001661-r17",
                "source_commit": m.R17_SOURCE_COMMIT,
                "run_spec_sha256": m.R17_RUN_SPEC,
                "step": 3,
                "world_size": 2,
                "checkpoint": str(checkpoint),
                "files": identities,
            }
        )
    )
    return tmp_path


def test_resume_world_two_c3_to_absolute_step_four_and_fixed_deadline(frozen):
    m = module()
    plan = runtime(m, frozen, "resume", "a" * 40, m.AUTHORIZED_DEADLINE - 3600)
    assert plan["training_flags"] == [
        "--total-training-steps",
        "4",
        "--save-freq",
        "1",
        "--observability-deadline-unix",
        "1790752269",
        "--token-journal-dir",
        "/root/mimo-private/launch-r19/token-journal",
        "--resume-from-path",
        str(frozen / "runs/r17/rl-training/checkpoints/global_step_3"),
    ]
    assert plan["wall_clock_seconds"] == 3420
    assert runtime(m, frozen, "resume", "a" * 40, m.AUTHORIZED_DEADLINE - 3000)["wall_clock_seconds"] == 2820


@pytest.mark.parametrize("mode", [None, "fresh", "auto", ""])
def test_never_silently_falls_back_to_fresh(frozen, mode):
    m = module()
    with pytest.raises(ValueError, match="resume"):
        runtime(m, frozen, mode, "a" * 40, m.AUTHORIZED_DEADLINE - 3600)


@pytest.mark.parametrize("attack", ["commit", "hash", "traversal", "late", "early", "missing", "symlink", "checkpoint"])
def test_rejects_unbound_source_or_incomplete_checkpoint(frozen, attack):
    m = module()
    commit, now = "a" * 40, m.AUTHORIZED_DEADLINE - 3600
    path = frozen / "integration-check/source-r19-manifest.json"
    data = json.loads(path.read_text())
    source = frozen / "run-src-r19" / next(iter(data["files"]))
    if attack == "commit":
        commit = "b" * 40
    elif attack == "hash":
        source.write_bytes(b"changed")
    elif attack == "traversal":
        data["files"]["../outside"] = next(iter(data["files"].values()))
    elif attack == "late":
        now = m.AUTHORIZED_DEADLINE - 2699
    elif attack == "early":
        now = m.AUTHORIZED_DEADLINE - 25201
    elif attack == "missing":
        data["files"].pop(next(iter(m.REQUIRED_SOURCE)))
    elif attack == "symlink":
        target = frozen / "outside"
        source.rename(target)
        source.symlink_to(target)
    elif attack == "checkpoint":
        (frozen / "runs/r19/rl-training/checkpoints").mkdir(parents=True)
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        runtime(m, frozen, "resume", commit, now)


@pytest.mark.parametrize("now", [True, float("nan"), float("inf"), "1790685801"])
def test_invalid_clock(frozen, now):
    with pytest.raises(ValueError, match="clock"):
        runtime(module(), frozen, "resume", "a" * 40, now)


def test_runtime_gate_requires_explicit_environment(frozen, monkeypatch):
    m = module()
    monkeypatch.setattr(m, "ROOT", frozen)
    monkeypatch.setattr("time.time", lambda: m.AUTHORIZED_DEADLINE - 3600)
    monkeypatch.setenv("MIMO_R19_MODE", "resume")
    monkeypatch.setenv("MIMO_R19_SOURCE_COMMIT", "a" * 40)
    monkeypatch.setenv("MIMO_R19_DEADLINE_UNIX", str(m.AUTHORIZED_DEADLINE))
    monkeypatch.setenv(
        "MIMO_R19_RESUME_MANIFEST_SHA256",
        hashlib.sha256((frozen / "integration-check/r17-c3-resume-manifest.json").read_bytes()).hexdigest(),
    )
    assert m.runtime_gate()["mode"] == "resume"
    monkeypatch.delenv("MIMO_R19_MODE")
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
    driver = (tmp_path / "bundle/launch-r19-driver.py").read_text()
    assert "'CUDA_VISIBLE_DEVICES':'0,1'" in driver
    assert "ray-r19" in driver
    assert "validate_ipc_evidence" in driver
    assert "gpu-preflight-r10" not in driver
    assert "separate_async" not in driver
    assert "spec['deadline_unix'] - time.time() - 180" in driver
    prepare = (tmp_path / "bundle/prepare-r19.py").read_text()
    assert "private / 'run-spec-r18.json'" in prepare
    assert "private / 'run-spec-r1.json'" not in prepare
    assert all(str(port) in prepare for port in (38860, 38861, 38862, 38863, 38760, 38761))
    assert "max_concurrent_sessions=2,train_count=1,heldout_count=1" in prepare
    assert "max_concurrent_sessions=1,train_count=1,heldout_count=1" not in prepare
    assert "assert value['environment']['MAX_CONCURRENT_SESSIONS'] == '2'" in prepare
    assert "gpu-known-hosts-r8" not in prepare
    assert "cohost-r19/known_hosts" in prepare
    assert "gpu-discovery-r8" not in prepare
    assert "cohost-r19/loopback-key" in prepare
    assert "subprocess.run(shlex.split(command)," in prepare
    assert "subprocess.run(['ssh'" not in prepare
    assert "subprocess.run(['scp'" not in prepare
    assert prepare.count("manifest = prepare_task(") == 1
    assert "prepare_task(json.loads" not in prepare
    assert "mimo9b-001661-r19" in prepare
    assert "MIMO_R19_SOURCE_COMMIT" in prepare
    assert "MIMO_R19_DEADLINE_UNIX=" in prepare
    assert "MIMO_R19_RESUME_MANIFEST_SHA256=" in prepare
    assert "'PYTHONDONTWRITEBYTECODE=1', 'OMP_NUM_THREADS=2', 'MKL_NUM_THREADS=2'" in prepare
    assert "timeout=300, check=True)" in prepare
    assert "value.update(max_concurrent_jobs=2," in prepare
    wrapper = (tmp_path / "bundle/mimo-supervised-native-r19.py").read_text()
    assert "mimo-9b-dual-colocate-observed.yaml" in wrapper
    assert "r19_plan['training_flags']" in wrapper
    assert "'--experiment-name', 'mimo9b-001661-r19'" in wrapper
    assert "'--observability-wrapper'" in wrapper
    assert "'WANDB_MODE':'online'" in driver
    assert "observability_environment" in driver
    assert "audit-code/r19-preparation/" in driver
    assert "audit-code/r12-preparation/" not in driver
    assert "audit-code/r19-preparation/" in prepare
    assert "audit-code/r19-preparation/" in wrapper
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
        {name: hashlib.sha256((frozen / "run-src-r19" / name).read_bytes()).hexdigest() for name in m.NATIVE_SOURCE},
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
            (frozen / "run-src-r19/docs/verl-uni-agent-harbor-opd-rl/mimo_dual_colocate_probe.py").read_bytes()
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
        + str(frozen / "run-src-r19")
        + ":"
        + str(frozen / "run-src-r19/verl"),
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
    assert env["WANDB_RUN_ID"] == "mimo9b001661r19"
    assert env["WANDB_RESUME"] == "never"
    assert env["WANDB_MODE"] == "online"
    assert env["WANDB_ENTITY"] == "xdan-ai"
    assert env["WANDB_PROJECT"] == "xDAN-Verl-Uni-agent-Harbor-rl-opd"
    assert env["WANDB_NAME"] == "mimo9b-001661-r19"
    assert env["VERL_RL_INSIGHT_ENABLE"] == "1"
    assert env["RL_INSIGHT_SERVER_URL"] == "http://127.0.0.1:18080"
    assert env["MIMO_PROMETHEUS_URL"] == "http://127.0.0.1:9090"
    assert env["WANDB_DIR"].startswith("/root/mimo-private/")
    assert not any("KEY" in key or "TOKEN" in key for key in env)


def test_authorized_fixed_seven_hour_window_never_rolls(frozen):
    m = module()
    assert m.AUTHORIZED_DEADLINE == 1790752269
    assert m.MAX_RUN_SECONDS == 25200
    first = runtime(m, frozen, "resume", "a" * 40, m.AUTHORIZED_DEADLINE - 25200)
    later = runtime(m, frozen, "resume", "a" * 40, m.AUTHORIZED_DEADLINE - 24900)
    assert first["deadline_unix"] == later["deadline_unix"] == 1790752269
    assert first["wall_clock_seconds"] == 25020
    assert later["wall_clock_seconds"] == 24720


@pytest.mark.parametrize("deadline", [None, True, "1790752269", 1790709401, 1790733089, 1790752270, float("inf")])
def test_explicit_authorized_deadline_required(frozen, deadline):
    m = module()
    with pytest.raises(ValueError, match="deadline"):
        m.validate_runtime(
            frozen,
            "resume",
            "a" * 40,
            m.AUTHORIZED_DEADLINE - 3600,
            deadline_unix=deadline,
            resume_manifest_sha256="0" * 64,
        )


def test_checkpoint_manifest_expected_hash_is_required(frozen):
    m = module()
    for expected in (None, "", "0" * 64):
        with pytest.raises(ValueError, match="manifest"):
            m.validate_runtime(
                frozen,
                "resume",
                "a" * 40,
                m.AUTHORIZED_DEADLINE - 3600,
                deadline_unix=m.AUTHORIZED_DEADLINE,
                resume_manifest_sha256=expected,
            )


@pytest.mark.parametrize(
    "attack",
    [
        "unsealed",
        "missing-c2",
        "missing-rank",
        "wrong-world",
        "wrong-config",
        "wrong-fsdp",
        "corrupt",
        "latest",
        "manifest-rank",
        "manifest-traversal",
        "old-source",
        "old-spec",
    ],
)
def test_resume_requires_complete_stable_same_world_two_checkpoint(frozen, attack):
    m = module()
    manifest_path = frozen / "integration-check/r17-c3-resume-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    checkpoint = frozen / "runs/r17/rl-training/checkpoints/global_step_3"
    if attack == "unsealed":
        manifest_path.unlink()
    elif attack == "missing-c2":
        checkpoint.rename(checkpoint.with_name("not-complete"))
    elif attack == "missing-rank":
        (checkpoint / "actor/model_world_size_2_rank_1.pt").unlink()
    elif attack == "wrong-world":
        manifest["world_size"] = 1
    elif attack == "wrong-config":
        path = checkpoint / "actor/fsdp_config.json"
        path.write_bytes(b'{"world_size":1}')
        manifest["files"]["actor/fsdp_config.json"]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    elif attack == "wrong-fsdp":
        path = checkpoint / "actor/fsdp_config.json"
        path.write_bytes(b'{"FSDP_version":2,"world_size":2}')
        manifest["files"]["actor/fsdp_config.json"] = {
            "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    elif attack == "corrupt":
        (checkpoint / "actor/optim_world_size_2_rank_0.pt").write_bytes(b"changed checkpoint")
    elif attack == "latest":
        (checkpoint.parent / "latest_checkpointed_iteration.txt").write_text("1")
    elif attack == "manifest-rank":
        manifest["files"].pop("actor/extra_state_world_size_2_rank_1.pt")
    elif attack == "manifest-traversal":
        manifest["files"]["../outside"] = manifest["files"]["data.pt"]
    elif attack == "old-source":
        manifest["source_commit"] = "0" * 40
    elif attack == "old-spec":
        manifest["run_spec_sha256"] = "sha256:" + "0" * 64
    if attack != "unsealed":
        manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        runtime(m, frozen, "resume", "a" * 40, m.AUTHORIZED_DEADLINE - 3600)


def test_checkpoint_change_during_streamed_hash_is_rejected(frozen, monkeypatch):
    m = module()
    original = m.hashlib.file_digest

    def changed(stream, algorithm):
        digest = original(stream, algorithm)
        path = Path(stream.name)
        stat = path.stat()
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1))
        return digest

    monkeypatch.setattr(m.hashlib, "file_digest", changed)
    with pytest.raises(ValueError, match="changed during hashing"):
        runtime(m, frozen, "resume", "a" * 40, m.AUTHORIZED_DEADLINE - 3600)


@pytest.mark.parametrize("value", [None, "", "1790709401", "1790733089", "1790752269.0", "1790752270"])
def test_runtime_deadline_environment_cannot_fall_back_or_extend(frozen, monkeypatch, value):
    m = module()
    monkeypatch.setattr(m, "ROOT", frozen)
    monkeypatch.setattr("time.time", lambda: m.AUTHORIZED_DEADLINE - 3600)
    monkeypatch.setenv("MIMO_R19_MODE", "resume")
    monkeypatch.setenv("MIMO_R19_SOURCE_COMMIT", "a" * 40)
    if value is None:
        monkeypatch.delenv("MIMO_R19_DEADLINE_UNIX", raising=False)
    else:
        monkeypatch.setenv("MIMO_R19_DEADLINE_UNIX", value)
    with pytest.raises(ValueError, match="deadline"):
        m.runtime_gate()


def cohost_spec():
    return dict(
        module().COHOST_FIELDS, modal_ingress={"listen_port": 38863}, policy_template={"gateway_host": "172.24.0.2"}
    )


def test_cohost_spec_has_six_distinct_forwarding_ports():
    assert module().validate_cohost_spec(cohost_spec())["gateway_host"] == "172.24.0.2"


@pytest.mark.parametrize(
    "field,value",
    [
        ("ssh_host", "157.157.221.177"),
        ("ssh_port", 11403),
        ("ssh_user", "other"),
        ("ssh_key", "/root/mimo-private/controller-key"),
        ("known_hosts", "/old/hosts"),
        ("control_port", 38760),
        ("worker_port", 38761),
        ("model_port", 38863),
        ("remote_control_port", 38860),
        ("remote_worker_port", 38861),
        ("gateway_host", "127.0.0.1"),
        ("gateway_port", 5000),
        ("listen_port", 38862),
    ],
)
def test_cohost_rejects_external_host_old_keys_gateway_or_port_collision(field, value):
    spec = cohost_spec()
    if field.startswith("gateway_"):
        spec["policy_template"][field] = value
    elif field == "listen_port":
        spec["modal_ingress"][field] = value
    else:
        spec[field] = value
    with pytest.raises(ValueError):
        module().validate_cohost_spec(spec)
