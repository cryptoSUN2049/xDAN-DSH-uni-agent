from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pyarrow.parquet as parquet
import pytest
import yaml

from examples.dsh.evolution_v3_catalog import FAMILY_IDS, canonical_json_bytes
from examples.dsh.evolution_v3_live import load_live_scenarios, write_live_contract_bundle
from examples.dsh.ops import run_v3_live_smoke as smoke
from examples.dsh.ops.run_v3_live_smoke import load_prepared_run, prepare_run

REPOSITORY = Path(__file__).resolve().parents[3]
SCENARIOS = Path("examples/dsh/evolution_v3_live_scenarios.jsonl")
ENVIRONMENT = "sha256:" + "e" * 64
_REAL_RUNTIME_PROBE = smoke._runtime_probe


@pytest.fixture
def prepared_inputs(tmp_path: Path) -> tuple[Path, Path]:
    repository = tmp_path / "repository"
    shutil.copytree(REPOSITORY / "examples/dsh", repository / "examples/dsh")
    bundle = tmp_path / "bundle"
    scenarios = load_live_scenarios(repository / SCENARIOS, repository_root=repository)
    write_live_contract_bundle(
        scenarios,
        scenario_path=SCENARIOS,
        repository_root=repository,
        output_dir=bundle,
        environment_digest=ENVIRONMENT,
        profile="sdk-minimal",
        patches=["examples/dsh/evolution.patch.yml"],
    )
    return repository, bundle


def test_prepare_freezes_eight_rows_and_pinned_config_without_upgrading_bundle(prepared_inputs, tmp_path):
    repository, bundle = prepared_inputs
    original = {path.name: path.read_bytes() for path in bundle.iterdir()}
    run_root = tmp_path / "run"

    manifest = prepare_run(bundle, run_root, repository_root=repository)

    assert manifest["schema"] == "dsh.evolution.live-smoke-run.v1"
    assert manifest["status"] == "prepared"
    assert manifest["training_eligible"] is False
    assert [sample["sample_index"] for sample in manifest["samples"]] == list(range(8))
    assert [sample["metadata"]["family_id"] for sample in manifest["samples"]] == list(FAMILY_IDS)
    rows = parquet.read_table(manifest["paths"]["data_path"]).to_pylist()
    assert len(rows) == 8
    assert rows[0]["extra_info"]["tools_kwargs"]["task"]["metadata"] == manifest["samples"][0]["metadata"]
    config = yaml.safe_load(Path(manifest["paths"]["task_config"]).read_text())[0]
    assert config["environment_digest"] == ENVIRONMENT
    assert config["verifier_code_digest"] == manifest["verifier_bundle"]["sha256"]
    assert config["agent"]["profile"] == "sdk-minimal"
    assert config["agent"]["patches"] == ["examples/dsh/evolution.patch.yml"]
    assert config["workdir"] == str(repository)
    assert config["agent"]["artifact_root"] == manifest["paths"]["trace_root"]
    assert config["result_root"] == manifest["paths"]["result_root"]
    assert all(Path(path).is_absolute() and Path(path).is_relative_to(run_root) for path in manifest["paths"].values())
    assert manifest["patch_files"][0]["path"] == "examples/dsh/evolution.patch.yml"
    assert load_prepared_run(run_root, repository_root=repository) == manifest
    assert original == {path.name: path.read_bytes() for path in bundle.iterdir()}


def test_prepare_refuses_existing_run_root_without_changing_it(prepared_inputs, tmp_path):
    repository, bundle = prepared_inputs
    run_root = tmp_path / "run"
    run_root.mkdir()
    marker = run_root / "keep"
    marker.write_text("existing")

    with pytest.raises(ValueError, match="already exists"):
        prepare_run(bundle, run_root, repository_root=repository)
    assert marker.read_text() == "existing"


@pytest.mark.parametrize("filename", ["manifest.json", "live-task-rows.jsonl"])
def test_prepare_rejects_tampered_bundle(prepared_inputs, tmp_path, filename):
    repository, bundle = prepared_inputs
    path = bundle / filename
    path.write_bytes(path.read_bytes().replace(b"runtime-grounding", b"runtime-forgery"))

    with pytest.raises(ValueError):
        prepare_run(bundle, tmp_path / "run", repository_root=repository)
    assert not (tmp_path / "run").exists()


@pytest.mark.parametrize("field", ["data_path", "task_config"])
def test_load_rejects_modified_frozen_inputs(prepared_inputs, tmp_path, field):
    repository, bundle = prepared_inputs
    root = tmp_path / "run"
    manifest = prepare_run(bundle, root, repository_root=repository)
    path = Path(manifest["paths"][field])
    path.write_bytes(path.read_bytes() + b"tamper")

    with pytest.raises(ValueError, match="digest"):
        load_prepared_run(root, repository_root=repository)


def test_load_rejects_patch_bytes_changed_after_prepare(prepared_inputs, tmp_path):
    repository, bundle = prepared_inputs
    root = tmp_path / "run"
    prepare_run(bundle, root, repository_root=repository)
    patch = repository / "examples/dsh/evolution.patch.yml"
    patch.write_bytes(patch.read_bytes() + b"\n# changed\n")

    with pytest.raises(ValueError, match="patch"):
        load_prepared_run(root, repository_root=repository)


def test_load_ignores_mutable_outputs_but_rejects_output_path_escape(prepared_inputs, tmp_path):
    repository, bundle = prepared_inputs
    root = tmp_path / "run"
    manifest = prepare_run(bundle, root, repository_root=repository)
    Path(manifest["paths"]["result_path"]).write_text("running output")
    assert load_prepared_run(root, repository_root=repository) == manifest
    manifest["paths"]["result_path"] = str(tmp_path / "outside.json")
    (root / "run-manifest.json").write_text(json.dumps(manifest))

    with pytest.raises(ValueError, match="path"):
        load_prepared_run(root, repository_root=repository)


def test_prepare_rejects_nonfinite_manifest(prepared_inputs, tmp_path):
    repository, bundle = prepared_inputs
    path = bundle / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["invalid"] = float("nan")
    path.write_text(json.dumps(manifest))

    with pytest.raises(ValueError, match="non-finite"):
        prepare_run(bundle, tmp_path / "run", repository_root=repository)


@pytest.mark.parametrize(
    "relative",
    [
        SCENARIOS,
        Path("examples/dsh/verifier.py"),
        Path("examples/dsh/fixtures/evolution-v3-live/runtime-grounding.json"),
    ],
)
def test_prepare_rejects_changed_trusted_files(prepared_inputs, tmp_path, relative):
    repository, bundle = prepared_inputs
    source = repository / relative
    source.write_bytes(source.read_bytes() + b"\n")

    with pytest.raises(ValueError, match="digest"):
        prepare_run(bundle, tmp_path / "run", repository_root=repository)


@pytest.mark.parametrize("target", ["fixture", "rows"])
def test_prepare_rejects_symlink_to_external_file(prepared_inputs, tmp_path, target):
    repository, bundle = prepared_inputs
    original = (
        repository / "examples/dsh/fixtures/evolution-v3-live/runtime-grounding.json"
        if target == "fixture"
        else bundle / "live-task-rows.jsonl"
    )
    external = tmp_path / "outside"
    original.rename(external)
    original.symlink_to(external)

    with pytest.raises(ValueError, match="symlink|escapes"):
        prepare_run(bundle, tmp_path / "run", repository_root=repository)


def test_prepare_rejects_traversal_in_rehashed_manifest(prepared_inputs, tmp_path):
    import hashlib

    repository, bundle = prepared_inputs
    path = bundle / "manifest.json"
    value = json.loads(path.read_text())
    value["scenario_source"]["path"] = "../outside.jsonl"
    body = {key: item for key, item in value.items() if key != "release_id"}
    value["release_id"] = "sha256:" + hashlib.sha256(canonical_json_bytes(body)).hexdigest()
    path.write_bytes(canonical_json_bytes(value))

    with pytest.raises(ValueError, match="traversal"):
        prepare_run(bundle, tmp_path / "run", repository_root=repository)


@pytest.mark.parametrize("relative", ["agent-logs", "artifacts", "smoke.parquet"])
def test_load_rejects_symlinked_artifact_paths(prepared_inputs, tmp_path, relative):
    repository, bundle = prepared_inputs
    root = tmp_path / "run"
    prepare_run(bundle, root, repository_root=repository)
    original = root / relative
    outside = tmp_path / "outside"
    original.rename(outside)
    original.symlink_to(outside, target_is_directory=outside.is_dir())

    with pytest.raises(ValueError, match="path"):
        load_prepared_run(root, repository_root=repository)


@pytest.mark.parametrize(
    "field", ["samples", "runtime", "verifier_bundle", "bundle", "training_eligible", "repository_root"]
)
def test_load_rejects_altered_identity_fields(prepared_inputs, tmp_path, field):
    repository, bundle = prepared_inputs
    root = tmp_path / "run"
    manifest = prepare_run(bundle, root, repository_root=repository)
    if field == "samples":
        manifest[field] = manifest[field][:-1]
    elif field == "runtime":
        manifest[field]["profile"] = "different"
    elif field == "verifier_bundle":
        manifest[field]["sha256"] = "sha256:" + "0" * 64
    elif field == "bundle":
        manifest[field]["release_id"] = "sha256:" + "0" * 64
    elif field == "training_eligible":
        manifest[field] = True
    else:
        manifest[field] = str(tmp_path)
    (root / "run-manifest.json").write_bytes(canonical_json_bytes(manifest))

    with pytest.raises(ValueError):
        load_prepared_run(root, repository_root=repository)


def test_prepare_rejects_invalid_task_config(prepared_inputs, tmp_path):
    repository, bundle = prepared_inputs
    (repository / "examples/dsh/evolution_task_config_v3_live.yaml").write_text("- not-a-task\n")

    with pytest.raises(ValueError, match="config"):
        prepare_run(bundle, tmp_path / "run", repository_root=repository)


def test_prepare_parquet_is_deterministic(prepared_inputs, tmp_path):
    repository, bundle = prepared_inputs
    first = prepare_run(bundle, tmp_path / "first", repository_root=repository)
    second = prepare_run(bundle, tmp_path / "second", repository_root=repository)

    assert first["sha256"]["data_path"] == second["sha256"]["data_path"]
    assert first["samples"] == second["samples"]


def test_prepare_accepts_bundle_authored_with_absolute_scenario_path(prepared_inputs, tmp_path):
    repository, _bundle = prepared_inputs
    absolute_bundle = tmp_path / "absolute-bundle"
    source = repository / SCENARIOS
    write_live_contract_bundle(
        load_live_scenarios(source, repository_root=repository),
        scenario_path=source,
        repository_root=repository,
        output_dir=absolute_bundle,
        environment_digest=ENVIRONMENT,
        profile="sdk-minimal",
        patches=["examples/dsh/evolution.patch.yml"],
    )

    manifest = prepare_run(absolute_bundle, tmp_path / "run", repository_root=repository)
    assert len(manifest["samples"]) == 8


def test_cli_prepare_uses_current_repository_without_running_inference(prepared_inputs, tmp_path):
    repository, bundle = prepared_inputs
    root = tmp_path / "run"
    script = REPOSITORY / "examples/dsh/ops/run_v3_live_smoke.py"
    result = subprocess.run(
        [sys.executable, str(script), "prepare", "--bundle-dir", str(bundle), "--run-root", str(root)],
        cwd=repository,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"samples": 8, "status": "prepared"}
    assert not (root / "inference-results.json").exists()


def test_run_dry_run_is_cpu_only_and_does_not_consume_prepared_run(prepared_inputs, tmp_path, monkeypatch):
    repository, bundle = prepared_inputs
    root = tmp_path / "run"
    before = prepare_run(bundle, root, repository_root=repository)
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: pytest.fail("dry-run spawned a process"))
    result = smoke.run_prepared(
        root,
        model_path=tmp_path / "missing-model",
        runtime_manifest=None,
        timeout_seconds=20,
        repository_root=repository,
        dry_run=True,
    )

    command = result["command"]
    assert result["status"] == "dry-run"
    for flag, value in {
        "--limit": "8",
        "--n": "1",
        "--concurrency": "1",
        "--n-gpus-per-node": "1",
        "--tensor-parallel-size": "1",
        "--gateway-count": "1",
        "--tool-parser": "hermes",
        "--gpu-memory-utilization": "0.5",
    }.items():
        assert command[command.index(flag) + 1] == value
    assert "--require-reward-post" in command
    assert "--dsh-strict-audit" in command
    assert "--dsh-episode-files" in command
    assert "parallel_infer_verl.py" in command[1]
    assert load_prepared_run(root, repository_root=repository) == before
    assert not (root / "run-started.json").exists()


def test_run_requires_runtime_evidence_before_spawning(prepared_inputs, tmp_path, monkeypatch):
    repository, bundle = prepared_inputs
    root = tmp_path / "run"
    prepare_run(bundle, root, repository_root=repository)
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: pytest.fail("missing preflight spawned a process"))

    with pytest.raises(ValueError, match="runtime"):
        smoke.run_prepared(
            root, model_path=tmp_path / "model", runtime_manifest=None, timeout_seconds=20, repository_root=repository
        )


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf"), 7201])
def test_run_rejects_invalid_deadline(prepared_inputs, tmp_path, timeout):
    repository, bundle = prepared_inputs
    root = tmp_path / "run"
    prepare_run(bundle, root, repository_root=repository)

    with pytest.raises(ValueError, match="timeout"):
        smoke.run_prepared(
            root,
            model_path=tmp_path,
            runtime_manifest=None,
            timeout_seconds=timeout,
            repository_root=repository,
            dry_run=True,
        )


def _fake_runtime(monkeypatch):
    monkeypatch.setattr(smoke, "_runtime_preflight", lambda *a, **kw: {"schema": "synthetic-test-runtime"})
    monkeypatch.setattr(smoke, "_execution_environment", lambda *a, **kw: dict(os.environ))


def test_run_records_success_and_refuses_second_execution(prepared_inputs, tmp_path, monkeypatch):
    repository, bundle = prepared_inputs
    root = tmp_path / "run"
    prepare_run(bundle, root, repository_root=repository)
    _fake_runtime(monkeypatch)
    monkeypatch.setattr(smoke, "build_inference_command", lambda *a, **kw: [sys.executable, "-c", "print('cpu-child')"])
    monkeypatch.setattr(smoke, "_audit_run", lambda *a, **kw: {"live_contract_passed": True})

    result = smoke.run_prepared(
        root,
        model_path=tmp_path,
        runtime_manifest=tmp_path / "runtime.json",
        timeout_seconds=20,
        repository_root=repository,
    )

    assert result["status"] == "completed"
    assert result["exit_code"] == 0
    assert result["timed_out"] is False
    assert result["started_at"] <= result["finished_at"]
    assert result["pid"] > 0
    assert (root / "run.log").read_text().strip() == "cpu-child"
    assert result["audit"]["live_contract_passed"] is True
    assert json.loads((root / "smoke-report.json").read_bytes()) == result["audit"]
    inventory = json.loads((root / "artifact-sha256.json").read_bytes())
    assert inventory["schema"] == "dsh.evolution.live-smoke-artifacts.v1"
    assert inventory["training_eligible"] is False
    assert {entry["path"] for entry in inventory["files"]} >= {"run-manifest.json", "run.log", "smoke-report.json"}
    for entry in inventory["files"]:
        assert smoke._digest((root / entry["path"]).read_bytes()) == entry["sha256"]
    with pytest.raises(ValueError, match="already|prepared"):
        smoke.run_prepared(
            root,
            model_path=tmp_path,
            runtime_manifest=tmp_path / "runtime.json",
            timeout_seconds=20,
            repository_root=repository,
        )


def test_run_timeout_kills_process_group_and_preserves_artifacts(prepared_inputs, tmp_path, monkeypatch):
    repository, bundle = prepared_inputs
    root = tmp_path / "run"
    prepare_run(bundle, root, repository_root=repository)
    _fake_runtime(monkeypatch)
    code = (
        "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); print('partial',flush=True); time.sleep(60)"
    )
    monkeypatch.setattr(smoke, "build_inference_command", lambda *a, **kw: [sys.executable, "-c", code])
    monkeypatch.setattr(smoke, "_audit_run", lambda *a, **kw: {"live_contract_passed": False})
    monkeypatch.setattr(smoke, "_TERM_GRACE_SECONDS", 0.1)

    result = smoke.run_prepared(
        root,
        model_path=tmp_path,
        runtime_manifest=tmp_path / "runtime.json",
        timeout_seconds=0.4,
        repository_root=repository,
    )

    assert result["status"] == "timed_out"
    assert result["timed_out"] is True
    assert result["exit_code"] < 0
    assert (root / "run.log").read_text().strip() == "partial"
    with pytest.raises(ProcessLookupError):
        os.kill(result["pid"], 0)


def test_run_marks_postexecution_input_tampering_as_integrity_failure(prepared_inputs, tmp_path, monkeypatch):
    repository, bundle = prepared_inputs
    root = tmp_path / "run"
    manifest = prepare_run(bundle, root, repository_root=repository)
    _fake_runtime(monkeypatch)
    code = "from pathlib import Path; import sys; Path(sys.argv[1]).write_text('tamper')"
    monkeypatch.setattr(
        smoke,
        "build_inference_command",
        lambda *a, **kw: [sys.executable, "-c", code, manifest["paths"]["task_config"]],
    )
    monkeypatch.setattr(smoke, "_audit_run", lambda *a, **kw: {"live_contract_passed": False})

    result = smoke.run_prepared(
        root,
        model_path=tmp_path,
        runtime_manifest=tmp_path / "runtime.json",
        timeout_seconds=20,
        repository_root=repository,
    )

    assert result["status"] == "integrity_failed"
    assert result["exit_code"] == 0
    assert result["input_integrity_verified"] is False
    assert Path(manifest["paths"]["task_config"]).read_text() == "tamper"


def _inventory(root):
    return [
        {"path": path.relative_to(root).as_posix(), "sha256": smoke._digest(path.read_bytes())}
        for path in sorted(root.rglob("*"))
        if path.is_file()
    ]


@pytest.fixture
def synthetic_deployment(tmp_path, monkeypatch):
    """Tiny fake artifacts plus stub Git/CUDA boundaries; this is not ML evidence."""
    repository = tmp_path / "synthetic-repository"
    repository.mkdir()
    model = tmp_path / "synthetic-model"
    model.mkdir()
    (model / "config.json").write_text('{"model_type":"qwen3"}')
    (model / "tokenizer.json").write_text("{}")
    (model / "tokenizer_config.json").write_text("{}")
    (model / "model.safetensors").write_bytes(b"SYNTHETIC-NOT-WEIGHTS")
    source = tmp_path / "synthetic-dsh-source"
    source.mkdir()
    (source / "sdk.py").write_text("# SYNTHETIC-NOT-SDK\n")
    carrier = tmp_path / "synthetic-linux-runtime"
    carrier.mkdir()
    executable = carrier / "runtime"
    executable.write_bytes(b"SYNTHETIC-NOT-EXECUTABLE")
    versions = {
        "python": "3.11.99",
        "torch": "2.10.0+cu128",
        "vllm": "0.18.1",
        "transformers": "4.57.6",
        "ray": "2.58.0",
        "tensordict": "0.10.0",
        "transfer-queue": "synthetic-test-version",
    }
    runtime = {
        "schema": smoke.RUNTIME_SCHEMA,
        "environment_digest": ENVIRONMENT,
        "uni_agent_commit": "synthetic-uni-agent-commit",
        "verl_commit": smoke.VERL_COMMIT,
        "model": {
            "path": str(model),
            "repo_id": "Qwen/Qwen3-4B",
            "revision": smoke.MODEL_REVISION,
            "files": _inventory(model),
        },
        "dsh": {
            "source_root": str(source),
            "source_commit": smoke.DSH_COMMIT,
            "source_files": _inventory(source),
            "mode": "exe",
            "runtime_root": str(carrier),
            "runtime_files": _inventory(carrier),
            "launch_args": [str(executable)],
            "launch_files": [{"path": str(executable), "sha256": smoke._digest(executable.read_bytes())}],
        },
        "versions": versions,
    }
    probe = {
        "versions": dict(versions),
        "cuda_available": True,
        "gpu_count": 1,
        "cuda_version": "12.8",
        "launch_args": list(runtime["dsh"]["launch_args"]),
    }

    def synthetic_git(root, *args):
        if args == ("rev-parse", "HEAD"):
            return (
                smoke.DSH_COMMIT
                if root == source
                else smoke.VERL_COMMIT
                if root.name == "verl"
                else runtime["uni_agent_commit"]
            )
        if args == ("ls-files", "-z"):
            return "sdk.py\0"
        return ""

    monkeypatch.setattr(smoke, "_git", synthetic_git)
    monkeypatch.setattr(smoke.platform, "system", lambda: "Linux")
    monkeypatch.setattr(smoke.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(smoke, "_runtime_probe", lambda *a, **kw: probe)
    runtime_path = tmp_path / "synthetic-runtime.json"
    runtime_path.write_bytes(canonical_json_bytes(runtime))
    return repository, model, runtime_path, runtime, probe


def test_runtime_preflight_binds_complete_synthetic_inventory(synthetic_deployment):
    repository, model, path, runtime, probe = synthetic_deployment
    evidence = smoke._runtime_preflight(
        {"runtime": {"environment_digest": ENVIRONMENT}}, model, path, repository_root=repository
    )
    assert evidence["probe"] == probe
    assert evidence["manifest_sha256"] == smoke._digest(path.read_bytes())
    assert evidence["dsh"]["source_files"] == runtime["dsh"]["source_files"]


@pytest.mark.parametrize(
    "change",
    [
        "model_bytes",
        "model_missing",
        "unlisted_model",
        "dsh_bytes",
        "runtime_bytes",
        "runtime_unlisted",
        "model_revision",
        "dsh_revision",
        "verl_revision",
        "environment",
        "versions_missing",
        "wrong_ml_lane",
        "launch_hash",
        "cuda_missing",
        "cuda_old",
        "gpu_count",
        "probe_versions",
        "probe_launch",
        "source_untracked_python",
    ],
)
def test_runtime_preflight_rejects_missing_or_changed_deployment_identity(synthetic_deployment, monkeypatch, change):
    repository, model, path, runtime, probe = synthetic_deployment
    if change == "model_bytes":
        (model / "model.safetensors").write_bytes(b"tamper")
    elif change == "model_missing":
        runtime["model"]["files"].pop()
    elif change == "unlisted_model":
        (model / "extra.py").write_text("# untracked")
    elif change == "dsh_bytes":
        (Path(runtime["dsh"]["source_root"]) / "sdk.py").write_text("# tamper")
    elif change == "runtime_bytes":
        Path(runtime["dsh"]["launch_args"][0]).write_bytes(b"tamper")
    elif change == "runtime_unlisted":
        (Path(runtime["dsh"]["runtime_root"]) / "extra.js").write_text("// extra")
    elif change == "model_revision":
        runtime["model"]["revision"] = "unpinned"
    elif change == "dsh_revision":
        runtime["dsh"]["source_commit"] = "unpinned"
    elif change == "verl_revision":
        runtime["verl_commit"] = "unpinned"
    elif change == "environment":
        runtime["environment_digest"] = "sha256:" + "0" * 64
    elif change == "versions_missing":
        runtime["versions"].pop("ray")
    elif change == "wrong_ml_lane":
        runtime["versions"]["vllm"] = probe["versions"]["vllm"] = "0.23.0"
    elif change == "launch_hash":
        runtime["dsh"]["launch_files"][0]["sha256"] = "sha256:" + "0" * 64
    elif change == "cuda_missing":
        probe["cuda_available"] = False
    elif change == "cuda_old":
        probe["cuda_version"] = "12.6"
    elif change == "gpu_count":
        probe["gpu_count"] = 2
    elif change == "probe_versions":
        probe["versions"]["torch"] = "unexpected"
    elif change == "probe_launch":
        probe["launch_args"] = ["/unverified/exe"]
    elif change == "source_untracked_python":
        original_git = smoke._git
        monkeypatch.setattr(
            smoke, "_git", lambda root, *args: "extra.py\0" if "--others" in args else original_git(root, *args)
        )
    path.write_bytes(canonical_json_bytes(runtime))

    with pytest.raises(ValueError):
        smoke._runtime_preflight(
            {"runtime": {"environment_digest": ENVIRONMENT}}, model, path, repository_root=repository
        )


def test_runtime_environment_uses_absolute_sources_and_does_not_forward_api_secrets(synthetic_deployment, monkeypatch):
    repository, _model, _path, runtime, _probe = synthetic_deployment
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-not-a-secret")
    monkeypatch.setenv("PYTHONPATH", ".:verl")
    environment = smoke._execution_environment(repository, runtime)
    assert "OPENAI_API_KEY" not in environment
    assert all(Path(path).is_absolute() for path in environment["PYTHONPATH"].split(os.pathsep))
    assert environment["HF_HUB_OFFLINE"] == "1"


def test_runtime_preflight_rejects_manifest_changed_during_probe(synthetic_deployment, monkeypatch):
    repository, model, path, _runtime, probe = synthetic_deployment

    def synthetic_probe(*args, **kwargs):
        path.write_text('{"changed":"during-probe"}')
        return probe

    monkeypatch.setattr(smoke, "_runtime_probe", synthetic_probe)
    with pytest.raises(ValueError, match="changed"):
        smoke._runtime_preflight(
            {"runtime": {"environment_digest": ENVIRONMENT}}, model, path, repository_root=repository
        )


@pytest.mark.parametrize("failure", ["spawn", "exit", "audit"])
def test_run_retains_failure_status_and_seals_artifacts(prepared_inputs, tmp_path, monkeypatch, failure):
    repository, bundle = prepared_inputs
    root = tmp_path / "run"
    prepare_run(bundle, root, repository_root=repository)
    _fake_runtime(monkeypatch)
    monkeypatch.setattr(
        smoke, "build_inference_command", lambda *a, **kw: [sys.executable, "-c", "raise SystemExit(7)"]
    )

    def synthetic_audit(*args, **kwargs):
        if failure == "audit":
            raise ImportError("synthetic audit unavailable")
        return {"live_contract_passed": False}

    monkeypatch.setattr(smoke, "_audit_run", synthetic_audit)
    if failure == "spawn":

        def denied_spawn(*args, **kwargs):
            raise OSError("synthetic spawn failure")

        monkeypatch.setattr(subprocess, "Popen", denied_spawn)
    result = smoke.run_prepared(
        root, model_path=tmp_path, runtime_manifest=None, timeout_seconds=20, repository_root=repository
    )
    assert result["status"] == "failed"
    assert result["exit_code"] == (None if failure == "spawn" else 7)
    assert result["execution_started"] is (failure != "spawn")
    assert (root / "artifact-sha256.json").is_file()
    if failure == "audit":
        assert result["audit"]["process_evidence_complete"] is False
        assert result["audit"]["errors"] == ["ImportError"]


def test_run_checks_inputs_again_after_preflight_before_spawning(prepared_inputs, tmp_path, monkeypatch):
    repository, bundle = prepared_inputs
    root = tmp_path / "run"
    manifest = prepare_run(bundle, root, repository_root=repository)

    def synthetic_preflight(*args, **kwargs):
        Path(manifest["paths"]["task_config"]).write_text("tamper-during-preflight")
        return {"schema": "synthetic-runtime"}

    monkeypatch.setattr(smoke, "_runtime_preflight", synthetic_preflight)
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: pytest.fail("tampered inputs spawned inference"))
    with pytest.raises(ValueError, match="digest"):
        smoke.run_prepared(
            root, model_path=tmp_path, runtime_manifest=None, timeout_seconds=20, repository_root=repository
        )
    final = json.loads((root / "run-manifest.json").read_bytes())
    assert final["status"] == "preflight_failed"
    assert final["execution_started"] is False


@pytest.mark.parametrize(
    ("status", "audit", "expected_exit"),
    [
        (
            "completed",
            {"process_evidence_complete": True, "inference_readback_verified": True, "live_contract_passed": True},
            0,
        ),
        (
            "completed",
            {"process_evidence_complete": True, "inference_readback_verified": True, "live_contract_passed": False},
            1,
        ),
        (
            "completed",
            {"process_evidence_complete": False, "inference_readback_verified": True, "live_contract_passed": False},
            2,
        ),
        ("completed", {"live_contract_passed": False, "errors": ["ImportError"]}, 2),
        ("timed_out", {"live_contract_passed": False}, 2),
    ],
)
def test_cli_run_distinguishes_policy_failure_from_missing_evidence(monkeypatch, capsys, status, audit, expected_exit):
    monkeypatch.setattr(
        sys,
        "argv",
        ["smoke", "run", "--run-root", "/synthetic/run", "--model-path", "/synthetic/model", "--timeout-seconds", "20"],
    )
    monkeypatch.setattr(smoke, "run_prepared", lambda *a, **kw: {"status": status, "audit": audit})
    with pytest.raises(SystemExit) as result:
        smoke.main()
    assert result.value.code == expected_exit
    assert json.loads(capsys.readouterr().out)["status"] == status


@pytest.mark.parametrize(
    ("returncode", "stdout", "succeeds"), [(0, '{"versions": {}}', True), (1, "", False), (0, "", False)]
)
def test_runtime_probe_requires_machine_readable_evidence_without_starting_model(
    synthetic_deployment, monkeypatch, returncode, stdout, succeeds
):
    from types import SimpleNamespace

    repository, _model, _path, runtime, _probe = synthetic_deployment
    probe_function = _REAL_RUNTIME_PROBE

    def synthetic_process(argv, **kwargs):
        assert argv[:2] == [sys.executable, "-c"]
        assert "LLM(" not in argv[2]
        assert "parallel_infer_verl" not in argv[2]
        assert kwargs["timeout"] == 60
        return SimpleNamespace(returncode=returncode, stdout=stdout)

    monkeypatch.setattr(subprocess, "run", synthetic_process)
    if succeeds:
        assert probe_function(repository, runtime) == {"versions": {}}
    else:
        with pytest.raises(ValueError, match="probe"):
            probe_function(repository, runtime)


def test_runtime_probe_uses_installed_transferqueue_distribution_name(synthetic_deployment, monkeypatch):
    import importlib.metadata
    import io
    from contextlib import redirect_stdout
    from types import SimpleNamespace

    repository, _model, _path, runtime, _probe = synthetic_deployment
    fake_torch = SimpleNamespace(
        cuda=SimpleNamespace(is_available=lambda: True, device_count=lambda: 1),
        version=SimpleNamespace(cuda="12.8"),
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    for name in ("vllm", "ray", "tensordict", "transfer_queue", "deepseek_harness"):
        monkeypatch.setitem(sys.modules, name, SimpleNamespace())
    monkeypatch.setitem(
        sys.modules, "deepseek_harness_runtime", SimpleNamespace(resolve_bundled_launch_args=lambda: ())
    )

    def version(distribution):
        if distribution == "transfer-queue":
            raise importlib.metadata.PackageNotFoundError(distribution)
        return "0.1.8" if distribution == "TransferQueue" else "synthetic"

    monkeypatch.setattr(importlib.metadata, "version", version)

    def execute_probe(argv, **kwargs):
        output = io.StringIO()
        with redirect_stdout(output):
            exec(compile(argv[2], "<synthetic-runtime-probe>", "exec"), {})
        return SimpleNamespace(returncode=0, stdout=output.getvalue())

    monkeypatch.setattr(subprocess, "run", execute_probe)
    result = _REAL_RUNTIME_PROBE(repository, runtime)
    assert result["versions"]["transfer-queue"] == "0.1.8"
