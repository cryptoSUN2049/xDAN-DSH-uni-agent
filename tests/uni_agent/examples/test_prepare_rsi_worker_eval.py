import sys
from pathlib import Path

import pyarrow.parquet as pq
import pytest
import yaml

from examples.dsh.rsi_closed import prepare_worker_eval as prep
from examples.dsh.rsi_closed.worker_tasks import prepare as prepare_cases
from uni_agent.tasks.dsh.rsi_candidates import Registry, initialize


@pytest.fixture
def parent_inputs(tmp_path, monkeypatch):
    # Development tests run before commit; production preparation must pass the real Git gate.
    monkeypatch.setattr(prep, "require_clean_sources", lambda: None)
    monkeypatch.setattr(
        prep,
        "verl_source_identity",
        lambda: {
            "overlay_id": "preserve-finish-reason-v1",
            "state": "patched",
            "manifest_sha256": "sha256:" + "1" * 64,
        },
    )
    cases = tmp_path / "cases"
    prepare_cases(cases)
    model = tmp_path / "model"
    model.mkdir()
    for name in ("config.json", "tokenizer_config.json", "tokenizer.json"):
        (model / name).write_text("{}")
    (model / "model.safetensors").write_bytes(b"unit-test-model-not-loadable")
    runtime = tmp_path / "dsh"
    runtime.write_bytes(b"unit-test-runtime-not-executed")
    runtime.chmod(0o700)
    monkeypatch.setattr(
        prep,
        "runtime_info",
        lambda python, exe: {
            "path": str(exe),
            "sha256": prep.RUNTIME_SHA256,
            "python": str(python),
            "sdk": "0.1.3a2",
            "version": "0.1.3a2",
        },
    )
    spec = {"schema": "dsh.rsi-profile.v1", "profile": "sdk-minimal", "allowed_tools": ["str_replace_editor"]}
    pins = prep.input_pins(cases, model, "pair-test", 4096, spec)
    registry = tmp_path / "registry"
    ids = initialize(registry, spec, pins)
    return dict(
        cases_root=cases,
        model_path=model,
        pair_id="pair-test",
        registry_root=registry,
        pins_sha256=ids["pins_sha256"],
        parent_active_sha256=ids["active_sha256"],
        runner_python=Path(sys.executable),
        runtime_executable=runtime,
        output_dir=tmp_path / "prepared",
        run_root=tmp_path / "runs",
    )


@pytest.fixture
def inputs(parent_inputs):
    args = dict(parent_inputs)
    registry = Registry(args["registry_root"], args["pins_sha256"])
    active = registry.load_active(args["parent_active_sha256"])
    args["candidate_sha256"] = registry.register(
        {**active["spec"], "allowed_tools": ["str_replace_editor", "cordis_inspect_list"]},
        active["candidate_sha256"],
    )
    return args


def test_parent_baseline_requires_no_registered_candidate(parent_inputs, monkeypatch):
    from examples.dsh.rsi_closed.launch_worker_eval import preflight

    def forbidden(*args, **kwargs):
        raise AssertionError("Baseline must not consume or register a child")

    monkeypatch.setattr(Registry, "load_registered", forbidden)
    monkeypatch.setattr(Registry, "register", forbidden)
    root = parent_inputs["registry_root"]
    before = {p.name: p.read_bytes() for p in root.iterdir()}
    manifest = prep.prepare(**parent_inputs, mode="parent-baseline")
    assert manifest["candidate_sha256"] is None
    assert set(manifest["sides"]) == {"H0"}
    path = parent_inputs["output_dir"] / "preparation-manifest.json"
    prepared = preflight(path, prep.digest(path), "H0")
    assert len(prepared["rows"]) == 2
    assert "--dsh-strict-audit" in prepared["command"]
    assert before == {p.name: p.read_bytes() for p in root.iterdir()}
    with pytest.raises(ValueError):
        preflight(path, prep.digest(path), "H1")


@pytest.mark.parametrize("mode", ["paired", "unknown"])
def test_missing_candidate_invalid_outside_baseline(parent_inputs, mode):
    with pytest.raises(ValueError):
        prep.prepare(**parent_inputs, mode=mode)
    assert not parent_inputs["output_dir"].exists()


def test_baseline_rejects_supplied_candidate(inputs):
    with pytest.raises(ValueError):
        prep.prepare(**inputs, mode="parent-baseline")


@pytest.mark.parametrize("fault", ["active", "paired-artifact", "wrong-side"])
def test_baseline_rejects_changed_identity(parent_inputs, fault):
    import json

    from examples.dsh.rsi_closed.launch_worker_eval import preflight

    manifest = prep.prepare(**parent_inputs, mode="parent-baseline")
    path = parent_inputs["output_dir"] / "preparation-manifest.json"
    if fault == "active":
        manifest["parent_active_sha256"] = "sha256:" + "0" * 64
    elif fault == "wrong-side":
        manifest["sides"]["H1"] = manifest["sides"].pop("H0")
    else:
        data = parent_inputs["output_dir"] / "H0/eval.parquet"
        rows = pq.read_table(data).to_pylist()
        for row in rows:
            row["extra_info"]["tools_kwargs"]["task"]["metadata"]["rsi_evaluation_mode"] = "paired"
        pq.write_table(prep.pa.Table.from_pylist(rows), data)
        manifest["files"]["H0/eval.parquet"] = prep.digest(data)
    path.write_text(json.dumps(manifest))
    with pytest.raises((ValueError, RuntimeError)):
        preflight(path, prep.digest(path), "H0")


def test_prepare_pair_same_fixtures_separate_runs_no_promotion(inputs):
    before = {p.name: p.read_bytes() for p in inputs["registry_root"].iterdir()}
    manifest = prep.prepare(**inputs)
    assert manifest["status"] == "prepared-not-run"
    output = inputs["output_dir"]
    h0, h1 = [pq.read_table(output / side / "eval.parquet").to_pylist() for side in ("H0", "H1")]
    assert [row["prompt"] for row in h0] == [row["prompt"] for row in h1]
    for a, b in zip(h0, h1, strict=True):
        am, bm = [row["extra_info"]["tools_kwargs"]["task"]["metadata"] for row in (a, b)]
        assert am["fixture_path"] == bm["fixture_path"]
        assert am["fixture_sha256"] == bm["fixture_sha256"]
        assert am["rsi_candidate_sha256"] != bm["rsi_candidate_sha256"]
    configs = [yaml.safe_load((output / side / "task.yaml").read_text())[0] for side in ("H0", "H1")]
    assert configs[0]["agent"]["model"] == configs[1]["agent"]["model"]
    assert configs[0]["result_root"] != configs[1]["result_root"]
    assert "--dsh-strict-audit" in manifest["sides"]["H0"]["command"]
    assert before == {p.name: p.read_bytes() for p in inputs["registry_root"].iterdir()}
    assert not inputs["run_root"].exists()
    assert manifest["sides"]["H1"]["selection"]["promoted"] is False


@pytest.mark.parametrize("fault", ["model", "source", "pins", "existing-output"])
def test_prepare_rejects_bad_identity_or_reuse(inputs, fault):
    if fault == "model":
        (inputs["model_path"] / "model.safetensors").write_bytes(b"changed")
    elif fault == "source":
        (inputs["cases_root"] / "file-constraint/sources/constraints.txt").write_text("changed")
    elif fault == "pins":
        inputs["pins_sha256"] = "sha256:" + "0" * 64
    else:
        inputs["output_dir"].mkdir()
    with pytest.raises((ValueError, RuntimeError, FileExistsError)):
        prep.prepare(**inputs)
    assert not inputs["run_root"].exists()


@pytest.fixture
def prepared(inputs):
    manifest = prep.prepare(**inputs)
    path = inputs["output_dir"] / "preparation-manifest.json"
    return inputs, manifest, path, prep.digest(path)


def test_preflight_and_real_strict_parser(prepared, monkeypatch):
    from examples.dsh.rsi_closed.launch_worker_eval import preflight
    from examples.inference import parallel_infer_verl as cli

    inputs, manifest, path, sha = prepared
    monkeypatch.setenv("RAY_ADDRESS", "ray://unrelated")
    monkeypatch.setenv("DSH_UA_PATCHES", "unrelated")
    for side in ("H0", "H1"):
        value = preflight(path, sha, side)
        args = cli._parse_args(value["command"][2:])
        cli._validate_evidence_args(args)
        registered = cli._registered_samples(
            value["rows"],
            [row["uid"] for row in value["rows"]],
            cli.TaskConfigResolver.from_file(args.task_config),
            strict=True,
        )
        assert len(registered) == 2 and args.n == 1
        assert all(row["metadata"]["rsi_side"] == side for row in registered)
        config = cli.init_config(
            args,
            task_configs=yaml.safe_load((inputs["output_dir"] / side / "task.yaml").read_text()),
            served_model_name="unit-test",
        )
        framework = config.actor_rollout_ref.rollout.custom.agent_framework
        assert (
            framework.require_verifier_reward and framework.require_finished_episode and framework.fail_on_rollout_error
        )
        assert "RAY_ADDRESS" not in value["environment"] and "DSH_UA_PATCHES" not in value["environment"]
        assert value["environment"]["RAY_TMPDIR"].startswith("/tmp/rsi-worker-")
    assert not inputs["run_root"].exists()


@pytest.mark.parametrize(
    "fault", ["overlay", "fixture", "model", "extra-file", "active", "manifest-sha", "existing-run"]
)
def test_preflight_rejects_changes_without_starting(prepared, fault):
    from examples.dsh.rsi_closed.launch_worker_eval import preflight

    inputs, manifest, path, sha = prepared
    if fault == "overlay":
        (inputs["output_dir"] / "H1/overlay.json").write_text("[]")
    elif fault == "fixture":
        (inputs["cases_root"] / "file-constraint/sources/constraints.txt").write_text("changed")
    elif fault == "model":
        (inputs["model_path"] / "model.safetensors").write_bytes(b"changed")
    elif fault == "extra-file":
        (inputs["output_dir"] / "extra.txt").write_text("unexpected")
    elif fault == "active":
        (inputs["registry_root"] / "active.json").write_text("{}")
    elif fault == "manifest-sha":
        sha = "sha256:" + "0" * 64
    else:
        (inputs["run_root"] / "H1").mkdir(parents=True)
    with pytest.raises((ValueError, RuntimeError)):
        preflight(path, sha, "H1")


def test_supervisor_failure_does_not_claim_execution(prepared, monkeypatch):
    from examples.dsh.rsi_closed import launch_worker_eval as launcher

    inputs, manifest, path, sha = prepared
    calls = []
    monkeypatch.setattr(launcher, "_gpu_idle", lambda: None)

    def failure(command, cwd, env, run, health, **kwargs):
        health()
        calls.append((command, run, kwargs))
        return {"exit_code": 7}

    monkeypatch.setattr(launcher, "supervise", failure)
    result = launcher.launch(path, sha, "H0")
    assert result["exit_code"] == 7
    assert calls[0][0] == manifest["sides"]["H0"]["command"]
    assert calls[0][2]["wall_seconds"] == manifest["wall_seconds"]
    assert not (inputs["run_root"] / "H0/runtime-binding.json").exists()
    assert not (inputs["run_root"] / "H1").exists()


def make_unit_results(prepared, side):
    """Synthetic CPU artifacts only: never student evaluation or GPU admission evidence."""
    import json
    from types import SimpleNamespace

    from examples.dsh.rsi_closed.launch_worker_eval import preflight
    from uni_agent.tasks.dsh.task import _task_result
    from uni_agent.tasks.dsh.trajectory_audit import _canonical_json_bytes

    _, manifest, path, sha = prepared
    value = preflight(path, sha, side)
    samples, keys, scores, statuses = [], [], [], {}
    for i, row in enumerate(value["rows"]):
        meta = row["extra_info"]["tools_kwargs"]["task"]["metadata"]
        uid, session = f"uid-{i}", f"dsh-unit-{i}"
        target = value["run"] / "artifacts/results" / str(i)
        target.mkdir(parents=True)
        dsh = {
            "dsh_session_id": session,
            "gateway_session_id": f"unit-{i}",
            "trace_sha256": "sha256:" + "1" * 64,
            "profile": "sdk-minimal",
            "patches_sha256": manifest["sides"][side]["patch_paths_sha256"],
        }
        envelope = {"schema": "dsh.uni-agent.task-result.v1", "finished": True, "metadata": meta, "dsh": dsh}
        prep.write_json(target / "agent-result.json", envelope)
        verifier = {
            "reward": 0,
            "accuracy": 0,
            "eligible": True,
            "finished": True,
            "fresh": True,
            "issued_at": "2026-09-09T00:00:00Z",
            "evidence": [dsh["trace_sha256"]],
        }
        _, receipt = _task_result(
            verifier,
            SimpleNamespace(finished=True, info=dsh),
            identity=meta,
            artifact_sha256=prep.digest(target / "agent-result.json"),
            verifier_command=["python", "-m", prep.MODULE],
            verifier_stdout=json.dumps(verifier),
        )
        (target / "verifier-receipt.json").write_bytes(_canonical_json_bytes(receipt))
        samples.append({"uid": uid, "metadata": meta})
        keys.append(uid + "_0_1")
        scores.append(0)
        statuses[uid] = "finished"
    prep.write_json(
        value["run"] / "inference-evidence.json",
        {
            "status": "completed",
            "samples": samples,
            "readback": {"final_keys": keys, "scores": scores, "uid_status": statuses, "traj_keys": []},
        },
    )
    return value


@pytest.fixture
def unit_results(prepared):
    return make_unit_results(prepared, "H1")


def test_baseline_supervised_launch_failure(parent_inputs, monkeypatch):
    manifest = prep.prepare(**parent_inputs, mode="parent-baseline")
    path = parent_inputs["output_dir"] / "preparation-manifest.json"
    test_supervisor_failure_does_not_claim_execution((parent_inputs, manifest, path, prep.digest(path)), monkeypatch)


@pytest.mark.parametrize("fault", [None, "missing", "wrong-mode"])
def test_baseline_result_gate(parent_inputs, fault):
    import json

    from examples.dsh.rsi_closed.launch_worker_eval import result_binding

    manifest = prep.prepare(**parent_inputs, mode="parent-baseline")
    path = parent_inputs["output_dir"] / "preparation-manifest.json"
    value = make_unit_results((parent_inputs, manifest, path, prep.digest(path)), "H0")
    artifact = value["run"] / "artifacts/results/0/agent-result.json"
    if fault == "missing":
        artifact.unlink()
    elif fault == "wrong-mode":
        data = json.loads(artifact.read_text())
        data["metadata"]["rsi_evaluation_mode"] = "paired"
        artifact.write_text(json.dumps(data))
    if fault is not None:
        with pytest.raises(ValueError):
            result_binding(value, "H0")
    else:
        report = result_binding(value, "H0")
        assert len(report["artifacts"]) == 2
        assert not report["promotion_verified"]


def test_runtime_binding_is_explicitly_not_raw_token_reaudit(unit_results):
    from examples.dsh.rsi_closed.launch_worker_eval import result_binding

    result = result_binding(unit_results, "H1")
    assert len(result["artifacts"]) == 2
    assert result["strict_readback_verified"] is True
    assert result["raw_token_reaudit"] is False
    assert result["promotion_verified"] is False
    assert result["policy_self_attestation"] is False


@pytest.mark.parametrize(
    "fault",
    ["empty", "missing", "missing-receipt", "wrong-patch", "bad-receipt", "score-mismatch", "unfinished-readback"],
)
def test_runtime_binding_refuses_incomplete_or_wrong_actual_artifacts(unit_results, fault):
    import json

    from examples.dsh.rsi_closed.launch_worker_eval import result_binding

    run = unit_results["run"]
    target = run / "artifacts/results/0"
    if fault in ("empty", "missing"):
        (target / "agent-result.json").unlink()
        if fault == "empty":
            (run / "artifacts/results/1/agent-result.json").unlink()
    elif fault == "missing-receipt":
        (target / "verifier-receipt.json").unlink()
    elif fault == "wrong-patch":
        path = target / "agent-result.json"
        value = json.loads(path.read_text())
        value["dsh"]["patches_sha256"] = "sha256:" + "0" * 64
        path.write_text(json.dumps(value))
    elif fault == "bad-receipt":
        (target / "verifier-receipt.json").write_text("{}")
    else:
        path = run / "inference-evidence.json"
        value = json.loads(path.read_text())
        if fault == "score-mismatch":
            value["readback"]["scores"][0] = 1
        else:
            value["readback"]["uid_status"]["uid-0"] = "running"
        path.write_text(json.dumps(value))
    with pytest.raises((ValueError, RuntimeError)):
        result_binding(unit_results, "H1")


def test_runtime_wrong_binary_fails_before_subprocess(tmp_path):
    file = tmp_path / "not-the-runtime"
    file.write_text("wrong")
    file.chmod(0o700)
    with pytest.raises(ValueError, match="binary mismatch"):
        prep.runtime_info(sys.executable, file)


def test_unexpected_nested_manifest_is_not_ignored(inputs):
    (inputs["cases_root"] / "file-constraint/manifest.json").write_text("{}")
    with pytest.raises(ValueError, match="inventory"):
        prep.prepare(**inputs)


def test_generation_configuration_is_part_of_model_pin(inputs):
    (inputs["model_path"] / "generation_config.json").write_text('{"eos_token_id": 999}')
    with pytest.raises(ValueError, match="Registry pins"):
        prep.prepare(**inputs)


def test_required_source_inventory_cannot_be_removed(prepared):
    import json

    from examples.dsh.rsi_closed.launch_worker_eval import preflight

    _, manifest, path, _ = prepared
    manifest["sources"].pop("uni_agent/tasks/dsh/trajectory_audit.py")
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="Source inventory"):
        preflight(path, prep.digest(path), "H0")


def test_dirty_execution_sources_cannot_claim_reproducible_prepare(monkeypatch):
    import subprocess

    def fake_git(command, **kwargs):
        text = " M examples/dsh/rsi_closed/profile.py\n" if command[1] == "status" else ""
        return subprocess.CompletedProcess(command, 0, stdout=text, stderr="")

    monkeypatch.setattr(prep.subprocess, "run", fake_git)
    with pytest.raises(ValueError, match="Commit the execution source"):
        prep.require_clean_sources()


def test_launch_gpu_busy_check_does_not_attach_to_other_process(monkeypatch):
    import subprocess

    from examples.dsh.rsi_closed import launch_worker_eval as launcher

    monkeypatch.setattr(
        launcher.subprocess, "run", lambda command, **kwargs: subprocess.CompletedProcess(command, 0, "1234\n", "")
    )
    with pytest.raises(RuntimeError, match="active compute processes"):
        launcher._gpu_idle()


def test_preparation_binds_effective_verl_source(inputs):
    manifest = prep.prepare(**inputs)
    assert manifest["verl_effective_source"] == prep.verl_source_identity()
    assert {
        "deployment/checks/verl_source_overlay.py",
        "deployment/versions/verl-runtime-patches.json",
        "deployment/patches/verl/fefb080-preserve-finish-reason.patch",
    } <= set(manifest["sources"])


@pytest.mark.parametrize("fault", ["missing", "manifest", "live"])
def test_preflight_rejects_effective_verl_identity_drift(prepared, monkeypatch, fault):
    import json

    from examples.dsh.rsi_closed.launch_worker_eval import preflight

    _, manifest, path, sha = prepared
    changed = {**prep.verl_source_identity(), "manifest_sha256": "sha256:" + "0" * 64}
    if fault == "live":
        monkeypatch.setattr(prep, "verl_source_identity", lambda: changed)
    else:
        if fault == "missing":
            manifest.pop("verl_effective_source", None)
        else:
            manifest["verl_effective_source"] = changed
        path.write_text(json.dumps(manifest))
        sha = prep.digest(path)
    with pytest.raises(ValueError, match="VERL effective source"):
        preflight(path, sha, "H0")
