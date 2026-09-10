"""CPU launch checks; no GPU backend, model load, or network access."""

import asyncio
import json
import os
import subprocess
import sys
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from deployment.checks import verl_source_overlay
from examples.dsh.capabilities import diagnose_core_reader as diagnostic
from examples.dsh.capabilities import prepare_memory_training, reader_diagnostic_runtime


@pytest.fixture
def pinned_environment(monkeypatch):
    repo = diagnostic._repository()
    lock = json.loads((repo / "deployment/versions/g1-deployment-lock.json").read_text())
    manifest = dict(
        environment_digest=lock["dsh"]["runtime_binary_sha256"],
        model_revision=lock["student"]["revision"],
        runner_python=sys.executable,
        runtime_executable="/pinned/runtime/dsh",
    )
    identity = dict(
        runtime=manifest["runtime_executable"],
        sdk="0.1.3a2",
        runtime_version="0.1.3a2",
        uni_agent=str(repo / "uni_agent/__init__.py"),
        verl=str(repo / "verl/verl/__init__.py"),
    )
    probes = []

    def probe(*args, **kwargs):
        probes.append((args, kwargs))
        return SimpleNamespace(stdout=json.dumps(identity))

    monkeypatch.setenv("DSH_RUNTIME_MODE", "exe")
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join((str(repo), str(repo / "verl"))))
    monkeypatch.setattr(subprocess, "run", probe)
    monkeypatch.setattr(verl_source_overlay, "verify_verl_source", lambda path: {"verified": True})
    return manifest, identity, probes


def test_execution_environment_rejects_actual_runtime_path_mismatch(pinned_environment):
    manifest, identity, probes = pinned_environment
    identity["runtime"] = "/another/runtime/dsh"
    with pytest.raises(ValueError, match="Actual SDK/runtime"):
        diagnostic.check_execution_environment(manifest)
    assert len(probes) == 1


def test_execution_environment_requires_inherited_exe_mode(pinned_environment, monkeypatch):
    manifest, _, probes = pinned_environment
    monkeypatch.delenv("DSH_RUNTIME_MODE")
    with pytest.raises(ValueError, match="DSH_RUNTIME_MODE=exe"):
        diagnostic.check_execution_environment(manifest)
    assert probes == []


def test_execution_environment_records_actual_import_identity(pinned_environment):
    manifest, identity, probes = pinned_environment
    result = diagnostic.check_execution_environment(manifest)
    assert result == {**identity, "verl_effective_source": {"verified": True}}
    assert probes[0][1]["check"] is True
    assert probes[0][1]["timeout"] == 60


@pytest.fixture
def prepared_launch(tmp_path, monkeypatch):
    path = tmp_path / "manifest.json"
    task_manifest = tmp_path / "task-index.json"
    task_manifest.write_text("{}")
    manifest = dict(
        root=str(tmp_path),
        runner_python=sys.executable,
        runtime_executable="/pinned/runtime/dsh",
        environment_digest="sha256:" + "a" * 64,
        model_revision="b" * 40,
        task_manifest=str(task_manifest),
        task_ids=["public-task"],
        files={str(task_manifest): diagnostic._sha_file(task_manifest)},
    )
    path.write_text(json.dumps(manifest))
    state = dict(opens=0, closes=0, calls=0, checks=0, gpu_checks=0, failure=None)

    def check(path):
        state["checks"] += 1
        if state["failure"] == "drift" and state["checks"] > 1:
            raise ValueError("source drift")
        return manifest

    def gpu_check():
        state["gpu_checks"] += 1
        return {"device": "mock-gpu", "available": True}

    async def execute(stage):
        raise AssertionError("The launch test must not execute a real stage")

    @asynccontextmanager
    async def executor(actual_manifest):
        assert actual_manifest == manifest
        state["opens"] += 1
        if state["failure"] == "backend":
            raise RuntimeError("backend failure with secret-value")
        try:
            yield execute
        finally:
            state["closes"] += 1

    async def run(operator, **kwargs):
        state["calls"] += 1
        assert operator.root == tmp_path / "chains"
        assert operator.max_generated_tokens == 8192
        assert kwargs == dict(
            run_id=tmp_path.name,
            task_ids=manifest["task_ids"],
            execute=execute,
            report_path=tmp_path / "report.json",
        )
        if state["failure"] == "diagnostic":
            raise RuntimeError("diagnostic failure with secret-value")
        if state["failure"] == "cancelled":
            raise asyncio.CancelledError("cancelled with secret-value")
        return {"summary": {"training_consumed": False}}

    monkeypatch.setattr(diagnostic, "check", check)
    monkeypatch.setattr(diagnostic, "check_execution_environment", lambda manifest: {"runtime": "verified"})
    monkeypatch.setattr(prepare_memory_training, "check_gpu_available", gpu_check)
    monkeypatch.setattr(reader_diagnostic_runtime, "open_executor", executor)
    monkeypatch.setattr(diagnostic, "run_diagnostic", run)
    return path, state


def test_launch_records_complete_execution_and_closes_backend(prepared_launch):
    path, state = prepared_launch
    result = diagnostic.launch(path)
    execution = json.loads((path.parent / "execution.json").read_text())
    assert result == {"summary": {"training_consumed": False}}
    assert execution["status"] == "complete"
    assert execution["identity"] == {"runtime": "verified"}
    assert execution["gpu_admission"] == {"device": "mock-gpu", "available": True}
    assert execution["manifest_sha256"] == diagnostic._sha_file(path)
    assert execution["started_at"] <= execution["ended_at"]
    assert state["opens"] == state["closes"] == state["calls"] == 1
    assert state["checks"] == 2


@pytest.mark.parametrize("failure", ["backend", "diagnostic", "drift", "cancelled"])
def test_launch_records_aborted_without_secret_exception_text(prepared_launch, failure):
    path, state = prepared_launch
    state["failure"] = failure
    error = {"drift": ValueError, "cancelled": asyncio.CancelledError}.get(failure, RuntimeError)
    with pytest.raises(error):
        diagnostic.launch(path)
    raw = (path.parent / "execution.json").read_text()
    execution = json.loads(raw)
    assert execution["status"] == "aborted"
    assert execution["error_type"] == error.__name__
    assert execution["started_at"] <= execution["ended_at"]
    assert "secret-value" not in raw
    assert state["opens"] == 1
    assert state["closes"] == (0 if failure == "backend" else 1)


def test_repeated_launch_does_not_start_another_backend_or_overwrite_evidence(prepared_launch):
    path, state = prepared_launch
    diagnostic.launch(path)
    original = (path.parent / "execution.json").read_bytes()
    with pytest.raises(FileExistsError):
        diagnostic.launch(path)
    assert state["opens"] == state["calls"] == 1
    assert (path.parent / "execution.json").read_bytes() == original


def test_execution_environment_rejects_relative_import_paths(pinned_environment, monkeypatch):
    manifest, _, probes = pinned_environment
    monkeypatch.setenv("PYTHONPATH", ".:verl")
    with pytest.raises(ValueError, match="must be absolute"):
        diagnostic.check_execution_environment(manifest)
    assert probes == []
