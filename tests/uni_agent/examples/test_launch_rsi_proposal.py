"""CPU launcher tests; GPU and model subprocesses are never started."""

import json
import shutil
from pathlib import Path

import pytest

from examples.dsh.rsi_closed import launch_proposal as launcher
from tests.uni_agent.examples.test_rsi_proposal_registration import parent_inputs, proposal_run  # noqa: F401


@pytest.fixture
def prepared(request, monkeypatch):
    path, sha, _, _, episode, baseline = request.getfixturevalue("proposal_run")
    manifest = json.loads(path.read_text())
    shutil.rmtree(manifest["run_root"])
    monkeypatch.setattr(launcher, "check_launcher_source", lambda: None)
    monkeypatch.setattr(launcher, "check_sdk", lambda *args: None)
    return path, sha, episode, baseline


def test_cpu_preflight_fixed_command_no_gpu(prepared, monkeypatch):
    path, sha, _, _ = prepared
    monkeypatch.setenv("DSH_UA_PATCHES", "unrelated")
    monkeypatch.setenv("RAY_ADDRESS", "unrelated")

    def forbidden():
        raise AssertionError("CPU preflight cannot query/start GPU")

    monkeypatch.setattr(launcher, "_gpu_idle", forbidden)
    value = launcher.preflight(path, sha)
    assert "DSH_UA_PATCHES" not in value["environment"]
    assert "RAY_ADDRESS" not in value["environment"]
    assert len(value["environment"]["RAY_TMPDIR"]) < 60
    assert not value["run"].exists()


@pytest.mark.parametrize("fault", ["hash", "command", "environment", "budget", "existing-run", "parquet"])
def test_preflight_rejects_changed_contract(prepared, fault):
    path, sha, _, _ = prepared
    value = json.loads(path.read_text())
    if fault == "hash":
        sha = "sha256:" + "0" * 64
    elif fault == "command":
        value["command"] = ["other-model"]
    elif fault == "environment":
        value["environment"]["DSH_UA_PATCHES"] = "unbound"
    elif fault == "budget":
        value["wall_seconds"] = 100000
    elif fault == "existing-run":
        Path(value["run_root"]).mkdir()
    else:
        (path.parent / "eval.parquet").write_bytes(b"changed")
    if fault in {"command", "environment", "budget"}:
        path.write_text(json.dumps(value))
        sha = launcher.worker.digest(path)
    with pytest.raises((ValueError, RuntimeError)):
        launcher.preflight(path, sha)


def test_busy_gpu_refuses_before_creating_run(prepared, monkeypatch):
    path, sha, _, _ = prepared

    def busy():
        raise RuntimeError("busy")

    monkeypatch.setattr(launcher, "_gpu_idle", busy)
    with pytest.raises(RuntimeError, match="busy"):
        launcher.launch(path, sha)
    assert not Path(json.loads(path.read_text())["run_root"]).exists()


def test_supervised_failure_never_registers_or_claims_audit(prepared, monkeypatch):
    path, sha, _, _ = prepared
    monkeypatch.setattr(launcher, "_gpu_idle", lambda: None)

    def supervisor(command, cwd, env, run, health, **kwargs):
        health()
        return {"exit_code": 7}

    monkeypatch.setattr(launcher, "supervise", supervisor)
    assert launcher.launch(path, sha)["exit_code"] == 7
    run = Path(json.loads(path.read_text())["run_root"])
    assert (run / "launch-manifest.json").exists()
    assert not (run / "proposal-audit.json").exists()


@pytest.mark.parametrize("reward", [0, 1])
def test_successful_supervised_audit_does_not_register(prepared, monkeypatch, reward):
    path, sha, episode, baseline = prepared
    monkeypatch.setattr(launcher, "_gpu_idle", lambda: None)

    def forbidden(*args, **kwargs):
        raise AssertionError("Launcher cannot register/promote")

    monkeypatch.setattr(launcher.Registry, "register", forbidden)
    monkeypatch.setattr(launcher.Registry, "promote", forbidden)
    if reward == 0:
        spec = launcher.Registry(baseline["registry_root"], baseline["pins_sha256"]).load_active(
            baseline["parent_active_sha256"]
        )["spec"]
        raw = json.dumps(spec)
        episode["envelope"]["response"] = episode["events"][0]["data"]["response"] = raw
        episode["reward"] = 0

    def supervisor(command, cwd, env, run, health, **kwargs):
        health()
        launcher.worker.write_json(run / "inference-evidence.json", {"samples": [{}]})
        launcher.worker.write_json(run / "supervisor-result.json", {"exit_code": 0})
        return {"exit_code": 0}

    monkeypatch.setattr(launcher, "supervise", supervisor)
    assert launcher.launch(path, sha)["exit_code"] == 0
    manifest = json.loads(path.read_text())
    run = Path(manifest["run_root"])
    launch = json.loads((run / "launch-manifest.json").read_text())
    assert launch == {
        "schema": "dsh.rsi-proposal-launch.v1",
        "prepared_manifest_sha256": sha,
        "command": manifest["command"],
        "environment": manifest["environment"],
        "wall_seconds": manifest["wall_seconds"],
    }
    audit = json.loads((run / "proposal-audit.json").read_text())
    assert audit["registration_ready"] is bool(reward)
    assert audit["registered"] is False and audit["promoted"] is False


def test_active_mutation_in_supervisor_health_rejected(prepared, monkeypatch):
    path, sha, _, baseline = prepared
    monkeypatch.setattr(launcher, "_gpu_idle", lambda: None)

    def supervisor(command, cwd, env, run, health, **kwargs):
        (Path(baseline["registry_root"]) / "active.json").write_text("{}")
        health()
        raise AssertionError("Mutated active must fail health")

    monkeypatch.setattr(launcher, "supervise", supervisor)
    with pytest.raises((ValueError, RuntimeError)):
        launcher.launch(path, sha)
    run = Path(json.loads(path.read_text())["run_root"])
    assert not (run / "proposal-audit.json").exists()


def test_owned_short_ray_collision_refuses_reuse(prepared):
    path, sha, _, _ = prepared
    value = launcher.preflight(path, sha)
    ray = Path(value["environment"]["RAY_TMPDIR"])
    ray.mkdir(exist_ok=False)
    try:
        with pytest.raises(ValueError, match="Ray"):
            launcher.preflight(path, sha)
    finally:
        ray.rmdir()


def test_sdk_probe_failure_stops_before_gpu(prepared, monkeypatch):
    path, sha, _, _ = prepared

    def bad_sdk(*args):
        raise RuntimeError("fixed SDK source mismatch")

    def forbidden():
        raise AssertionError("GPU must not be touched after failed SDK preflight")

    monkeypatch.setattr(launcher, "check_sdk", bad_sdk)
    monkeypatch.setattr(launcher, "_gpu_idle", forbidden)
    with pytest.raises(RuntimeError, match="SDK"):
        launcher.launch(path, sha)


def test_exit_zero_without_valid_raw_evidence_is_not_completion(prepared, monkeypatch):
    path, sha, _, _ = prepared
    monkeypatch.setattr(launcher, "_gpu_idle", lambda: None)

    def supervisor(command, cwd, env, run, health, **kwargs):
        launcher.worker.write_json(run / "inference-evidence.json", {"samples": [{}]})
        return {"exit_code": 0}

    def reject(*args, **kwargs):
        raise ValueError("raw NPZ invalid")

    monkeypatch.setattr(launcher, "supervise", supervisor)
    monkeypatch.setattr(launcher.registration, "audit_episode", reject)
    with pytest.raises(ValueError, match="NPZ"):
        launcher.launch(path, sha)
    assert not (Path(json.loads(path.read_text())["run_root"]) / "proposal-audit.json").exists()


@pytest.mark.parametrize("inherited", ["", "7"])
def test_single_gpu_child_selection_ignores_parent_cpu_visibility(prepared, monkeypatch, inherited):
    path, sha, _, _ = prepared
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", inherited)
    value = launcher.preflight(path, sha)
    assert value["environment"]["CUDA_VISIBLE_DEVICES"] == "0"


def test_sdk_probe_always_hides_gpu(monkeypatch):
    calls = []
    monkeypatch.setattr(launcher.subprocess, "run", lambda *a, **k: calls.append(k))
    launcher.check_sdk("python", {"CUDA_VISIBLE_DEVICES": "0"})
    assert calls[0]["env"]["CUDA_VISIBLE_DEVICES"] == ""
