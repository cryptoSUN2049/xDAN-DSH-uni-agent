import json

import pytest

from examples.dsh.capabilities.launch_context_inference import preflight


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    from examples.dsh.capabilities.prepare_context_training_v2 import prepare
    from tests.uni_agent.examples.test_prepare_capability_eval import inputs

    args = inputs.__wrapped__(tmp_path, monkeypatch)
    args["run_id"] = args.pop("eval_id")
    args["run_root"] = tmp_path / "run"
    manifest = prepare(**args)
    model = tmp_path / "model"
    model.mkdir()
    (model / "config.json").write_text(json.dumps(dict(model_type="qwen3", hidden_size=2560, num_hidden_layers=36)))
    (model / "tokenizer_config.json").write_text("{}")
    (model / "tokenizer.json").write_text("{}")
    (model / "model.safetensors").write_bytes(b"test-weights")
    monkeypatch.undo()
    return args, manifest, model


def test_cross_cwd_import_and_absolute_environment(prepared, monkeypatch):
    import subprocess

    args, manifest, model = prepared
    seen = []
    original_run = subprocess.run

    def probe(command, **kwargs):
        if command[0] == "git":
            return original_run(command, **kwargs)
        seen.append(kwargs)
        return subprocess.CompletedProcess(
            command,
            0,
            json.dumps(
                {
                    "bundle": manifest["verifier_bundle"]["sha256"],
                    "module": str(args["repository_root"] / "examples/dsh/capabilities/context_verifier_v2.py"),
                    "runtime": str(args["runtime_executable"]),
                    "sdk": "0.1.3a2",
                    "runtime_version": "0.1.3a2",
                }
            ),
            "",
        )

    monkeypatch.setattr(subprocess, "run", probe)
    monkeypatch.setenv("PYTHONPATH", ".:verl")
    monkeypatch.setenv("RAY_ADDRESS", "ray://another-cluster:10001")
    monkeypatch.setenv("RAY_TMPDIR", "/tmp/shared-ray")
    monkeypatch.setenv("PYTHONHOME", "/another-python")
    monkeypatch.setenv("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
    result = preflight(args["output_dir"] / "manifest.json", model)
    assert seen[0]["cwd"] == args["output_dir"]
    assert seen[0]["env"]["PYTHONPATH"] == manifest["environment"]["PYTHONPATH"]
    assert not args["run_root"].exists()
    assert "--dsh-strict-audit" in result["command"]
    assert result["record"]["model"]["files"]["model.safetensors"]
    actual = result["environment"]
    inherited_unwanted = {"RAY_ADDRESS", "PYTHONHOME", "PYTORCH_CUDA_ALLOC_CONF"}.intersection(actual)
    assert not inherited_unwanted
    assert actual["RAY_TMPDIR"].startswith("/tmp/dsh-context-")
    assert actual["RAY_TMPDIR"] != "/tmp/shared-ray"
    assert result["record"]["environment"]["PATH"] == actual["PATH"]
    assert result["record"]["environment"]["RAY_TMPDIR"] == actual["RAY_TMPDIR"]
    assert len(result["record"]["checkout"]["integration"]["head"]) == 40
    assert len(result["record"]["checkout"]["verl"]["head"]) == 40
    assert "branch" in result["record"]["checkout"]["integration"]


@pytest.mark.parametrize("mutation", ["input", "source", "argv", "env", "reuse", "model"])
def test_preflight_refuses_corruption_before_launch(prepared, mutation):
    args, manifest, model = prepared
    file = args["output_dir"] / "manifest.json"
    if mutation == "input":
        (args["output_dir"] / "validation.parquet").write_bytes(b"tampered")
    if mutation == "source":
        manifest["sources"]["examples/dsh/capabilities/context_verifier_v2.py"] = "sha256:" + "0" * 64
    if mutation == "argv":
        manifest["inference_arguments"] += ["--log-dir", "/tmp/escape"]
    if mutation == "env":
        manifest["environment"]["PYTHONPATH"] = ".:verl"
    if mutation == "reuse":
        args["run_root"].mkdir()
    if mutation == "model":
        (model / "config.json").write_text('{"model_type":"wrong"}')
    file.write_text(json.dumps(manifest))
    with pytest.raises((ValueError, RuntimeError)):
        preflight(file, model)


def test_real_wrong_cwd_import_blocks_before_run(prepared):
    args, _, model = prepared
    # /usr/bin/python3 in the preparation fixture lacks the selected SDK; real
    # subprocess import must fail before run creation, not after loading a model.
    with pytest.raises((ValueError, RuntimeError)):
        preflight(args["output_dir"] / "manifest.json", model)
    assert not args["run_root"].exists()


def test_existing_ray_directory_cannot_be_reused(prepared, monkeypatch):
    import hashlib
    from pathlib import Path

    args, _, model = prepared
    ray_tmp = Path("/tmp") / ("dsh-context-" + hashlib.sha256(str(args["run_root"]).encode()).hexdigest()[:12])
    original_exists = Path.exists
    monkeypatch.setattr(Path, "exists", lambda path: path == ray_tmp or original_exists(path))
    with pytest.raises(ValueError, match="Ray temporary directory already exists"):
        preflight(args["output_dir"] / "manifest.json", model)
    assert not args["run_root"].exists()


def test_actual_verl_checkout_must_match_deployment_pin(prepared, monkeypatch):
    from examples.dsh.capabilities import launch_context_inference as launcher

    args, _, model = prepared
    monkeypatch.setattr(launcher, "git_state", lambda root: {"head": "0" * 40, "branch": "unexpected"})
    with pytest.raises(ValueError, match="VERL checkout differs from deployment pin"):
        preflight(args["output_dir"] / "manifest.json", model)
    assert not args["run_root"].exists()


def test_launch_records_fixed_command_and_owned_deadline(tmp_path, monkeypatch):
    from examples.dsh.capabilities import launch_context_inference as launcher

    root = tmp_path / "new-run"
    prepared = dict(
        run_root=root,
        command=["python", "fixed-entry"],
        environment={"PYTHONPATH": "/fixed:/fixed/verl"},
        record={"schema": "test", "sources": {"verifier": "digest"}},
    )
    monkeypatch.setattr(launcher, "preflight", lambda *args, **kwargs: prepared)
    seen = []

    def supervise(command, cwd, environment, run, health, **kwargs):
        assert (run / "launch-manifest.json").is_file()
        assert health() is None
        seen.append((command, environment, kwargs))
        return {"exit_code": 0}

    monkeypatch.setattr(launcher, "supervise", supervise)
    assert launcher.launch("manifest", "model", wall_seconds=123) == {"exit_code": 0}
    assert seen == [(prepared["command"], prepared["environment"], {"wall_seconds": 123})]
    record = json.loads((root / "launch-manifest.json").read_text())
    assert record["wall_seconds"] == 123
    with pytest.raises(FileExistsError):
        launcher.launch("manifest", "model")


def test_real_owned_supervisor_wall_clock_without_gpu(tmp_path):
    import os
    import sys

    from deployment.services.harbor_training_supervisor import supervise

    result = supervise(
        [sys.executable, "-c", "import time;time.sleep(10)"],
        tmp_path,
        dict(os.environ),
        tmp_path,
        lambda: None,
        wall_seconds=0.05,
        interval=0.01,
        grace=0.1,
    )
    assert result["reason"] == "wall-clock-deadline" and result["exit_code"] != 0
    assert (tmp_path / "supervisor-result.json").is_file()
