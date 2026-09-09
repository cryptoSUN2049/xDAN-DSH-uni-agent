import json
from pathlib import Path

import pytest

from examples.dsh.capabilities import evaluate_work_state_tasks as suite


@pytest.fixture
def scenario(tmp_path, monkeypatch):
    calls = []
    modes = {}
    inputs = dict(
        root=tmp_path / "suite",
        suite_id="cpu-suite",
        runtime_executable="/runtime",
        runner_python="/python",
        model_path="/model",
        model_revision="a" * 40,
        mother_run="/mother",
        resume_from="/checkpoint/global_step_8",
    )

    def prepare(**kwargs):
        calls.append(kwargs)
        kwargs["output_dir"].mkdir()
        manifest = dict(
            integration_head="b" * 40,
            verl_head="c" * 40,
            verl_effective_source={"pin": "fixed"},
            model_revision_declared=kwargs["model_revision"],
            model_files={},
            runtime={"pin": "fixed"},
            checkpoint_origin={"identity": "same"},
            wall_seconds=3600,
            environment={
                "RUN_ROOT": str(kwargs["run_root"]),
                "EXP_NAME": kwargs["run_id"],
                **{key: "1" for key in suite.SAMPLING_FIELDS},
            },
        )
        (kwargs["output_dir"] / "manifest.json").write_text(json.dumps(manifest))
        return manifest

    def launch(path):
        index = len(calls) - 1
        action = modes.get(index, "success")
        if action == "cancel":
            raise KeyboardInterrupt
        if action == "launch-error":
            raise RuntimeError("private parameter must not be copied")
        Path(calls[-1]["run_root"]).mkdir()
        return dict(exit_code=1 if action == "failure" else 0, reason="training-exited")

    def audit(run, **kwargs):
        action = modes.get(len(calls) - 1, "success")
        valid = action not in ("failure", "missing", "corrupt")
        report = dict(
            passed=valid,
            consumption_verified=valid,
            run_id=kwargs["expected_run_id"],
            errors=["corrupt"] if action == "corrupt" else [],
            groups=[],
            unknown_or_unadmitted_consumption=[],
            duplicate_consumption=[],
            overlapping_crosswalk_keys=[],
            summary={"consumed_groups": 1 if valid else 0, "consumed_rows": 2 if valid else 0},
        )

        if valid:
            run = Path(run)
            group = run / "chains" / "groups" / "g"
            group.mkdir(parents=True)
            items = []
            for role in ("A", "B"):
                stage = run / "chains" / "chain" / role
                stage.mkdir(parents=True)
                fixture = stage / "fixture.json"
                fixture.write_text(json.dumps({"task": {"task_id": calls[-1]["evaluation_task_ids"][0]}}))
                envelope = {"metadata": {"fixture_path": str(fixture), "fixture_sha256": suite.recipe.digest(fixture)}}
                (stage / "agent-result.json").write_text(json.dumps(envelope))
                items.append({"role": role, "stage_receipt_path": str(stage / "receipt.json")})
            crosswalk = group / "crosswalk.json"
            crosswalk.write_text(json.dumps({"run_id": kwargs["expected_run_id"], "partition": "val", "items": items}))
            report["groups"] = [
                {"path": str(crosswalk), "crosswalk_sha256": suite.recipe.digest(crosswalk), "reasons": []}
            ]
        return report

    monkeypatch.setattr(suite.recipe, "prepare", prepare)
    monkeypatch.setattr(suite.recipe, "check", lambda path, **kwargs: json.loads(path.read_text()))
    monkeypatch.setattr(suite.recipe, "launch", launch)
    monkeypatch.setattr(suite, "audit_memory_training", audit)
    monkeypatch.setattr(suite, "require_idle_gpu", lambda: None)
    return inputs, calls, modes


def test_failure_kept_and_remaining_singletons_run(scenario):
    inputs, calls, modes = scenario
    modes[1] = "failure"
    result = suite.evaluate(**inputs)
    assert len(calls) == 4
    assert [c["evaluation_task_ids"] for c in calls] == [[t] for t in suite.TASK_IDS]
    assert all(c["mode"] == "reload" and c["resume_from"] == inputs["resume_from"] for c in calls)
    assert len({str(c["run_root"]) for c in calls}) == 4
    assert result["all_attempted"] and not result["all_verified"] and result["exit_code"] == 1
    assert [r["status"] for r in result["tasks"]] == ["verified", "execution_failed", "verified", "verified"]
    assert json.loads((inputs["root"] / "summary.json").read_text()) == result
    assert len(list(inputs["root"].glob("*/consumption-audit.json"))) == 4


def test_all_success(scenario):
    inputs, _, _ = scenario
    result = suite.evaluate(**inputs)
    assert result["all_verified"] and result["all_attempted"] and result["exit_code"] == 0


@pytest.mark.parametrize("kind", ["missing", "corrupt", "launch-error"])
def test_integrity_error_stops_dispatch(scenario, kind):
    inputs, calls, modes = scenario
    modes[0] = kind
    result = suite.evaluate(**inputs)
    assert len(calls) == 1 and not result["all_attempted"] and not result["all_verified"]
    assert all(row["status"] == "not_run" for row in result["tasks"][1:])
    if kind == "launch-error":
        assert result["stop_reason"]["message"] == "private parameter must not be copied"


def test_cancellation_persists_and_propagates(scenario):
    inputs, calls, modes = scenario
    modes[0] = "cancel"
    with pytest.raises(KeyboardInterrupt):
        suite.evaluate(**inputs)
    result = json.loads((inputs["root"] / "summary.json").read_text())
    assert result["tasks"][0]["status"] == "cancelled" and len(calls) == 1
    assert not result["all_attempted"]


def test_existing_root_rejected(scenario):
    inputs, calls, _ = scenario
    inputs["root"].mkdir()
    with pytest.raises(FileExistsError):
        suite.evaluate(**inputs)
    assert not calls


def test_cleanup_unknown_stops_dispatch(scenario, monkeypatch):
    inputs, calls, _ = scenario
    probes = []

    def idle():
        probes.append(1)
        if len(probes) == 2:
            raise RuntimeError("GPU still occupied")

    monkeypatch.setattr(suite, "require_idle_gpu", idle)
    result = suite.evaluate(**inputs)
    assert len(calls) == 1 and result["stop_reason"]["phase"] == "cleanup"
    assert not result["all_attempted"]


def test_prepare_failure_stops_dispatch(scenario, monkeypatch):
    inputs, calls, _ = scenario
    monkeypatch.setattr(suite.recipe, "prepare", lambda **kwargs: (_ for _ in ()).throw(ValueError("bad pin")))
    result = suite.evaluate(**inputs)
    assert not calls and result["stop_reason"]["phase"] == "prepare"
    assert result["exit_code"] == 1


def test_effective_identity_drift_blocks_second_launch(scenario, monkeypatch):
    inputs, calls, _ = scenario
    original = suite.recipe.check

    def changed(path, **kwargs):
        result = original(path, **kwargs)
        if len(calls) == 2:
            result["checkpoint_origin"] = {"identity": "different"}
        return result

    monkeypatch.setattr(suite.recipe, "check", changed)
    result = suite.evaluate(**inputs)
    assert len(calls) == 2
    assert result["tasks"][0]["status"] == "verified"
    assert "execution" not in result["tasks"][1]
    assert result["stop_reason"]["phase"] == "check"


def test_missing_dump_after_failed_execution_is_not_corruption(scenario, monkeypatch):
    inputs, calls, modes = scenario
    modes[0] = "failure"
    original = suite.audit_memory_training

    def audit(*args, **kwargs):
        report = original(*args, **kwargs)
        if len(calls) == 1:
            report["groups"] = [{"reasons": ["missing_consumed_keys"], "consumption_verified": False}]
        return report

    monkeypatch.setattr(suite, "audit_memory_training", audit)
    result = suite.evaluate(**inputs)
    assert len(calls) == 4 and result["tasks"][0]["status"] == "execution_failed"
    assert result["tasks"][0]["audit"]["consumption_verified"] is False


def test_rejected_stage_evidence_is_not_treated_as_missing_dump(scenario, monkeypatch):
    inputs, calls, modes = scenario
    modes[0] = "failure"
    original = suite.audit_memory_training

    def audit(*args, **kwargs):
        report = original(*args, **kwargs)
        report["groups"] = [{"reasons": ["ValueError: frozen hash changed"]}]
        return report

    monkeypatch.setattr(suite, "audit_memory_training", audit)
    result = suite.evaluate(**inputs)
    assert len(calls) == 1 and result["tasks"][0]["status"] == "audit_failed"


def test_gpu_probe_bounded_and_fails_closed(monkeypatch):
    calls = []

    def probe(command, **kwargs):
        calls.append((command, kwargs))
        return type("Result", (), {"stdout": "12345\n"})()

    monkeypatch.setattr(suite.subprocess, "run", probe)
    with pytest.raises(RuntimeError, match="cleanup"):
        suite.require_idle_gpu()
    assert calls[0][1]["timeout"] == 15 and calls[0][1]["check"] is True


@pytest.mark.parametrize("mutation", ["wrong-task", "rows", "groups"])
def test_success_must_bind_single_requested_task(scenario, monkeypatch, mutation):
    inputs, calls, _ = scenario
    original = suite.audit_memory_training

    def audit(*args, **kwargs):
        report = original(*args, **kwargs)
        if mutation == "rows":
            report["summary"]["consumed_rows"] = 4
        elif mutation == "groups":
            report["summary"]["consumed_groups"] = 2
        else:
            crosswalk = json.loads(Path(report["groups"][0]["path"]).read_text())
            stage = Path(crosswalk["items"][0]["stage_receipt_path"]).parent
            fixture = stage / "fixture.json"
            fixture.write_text(json.dumps({"task": {"task_id": "wrong-task"}}))
            envelope = {"metadata": {"fixture_path": str(fixture), "fixture_sha256": suite.recipe.digest(fixture)}}
            (stage / "agent-result.json").write_text(json.dumps(envelope))
        return report

    monkeypatch.setattr(suite, "audit_memory_training", audit)
    result = suite.evaluate(**inputs)
    assert len(calls) == 1 and result["tasks"][0]["status"] == "audit_failed"


def test_main_restores_sigterm_handler_on_cancellation(monkeypatch, tmp_path):
    import signal
    import sys

    previous = signal.getsignal(signal.SIGTERM)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "suite",
            "--root",
            str(tmp_path / "new"),
            "--suite-id",
            "cpu",
            "--runtime-executable",
            "/runtime",
            "--runner-python",
            sys.executable,
            "--model-path",
            "/model",
            "--model-revision",
            "a" * 40,
            "--mother-run",
            "/mother",
            "--resume-from",
            "/checkpoint/global_step_8",
        ],
    )

    def cancel(**kwargs):
        handler = signal.getsignal(signal.SIGTERM)
        assert callable(handler)
        handler(signal.SIGTERM, None)

    monkeypatch.setattr(suite, "evaluate", cancel)
    with pytest.raises(SystemExit) as caught:
        suite.main()
    assert caught.value.code == 143
    assert signal.getsignal(signal.SIGTERM) == previous


def test_sigterm_cleans_owned_child_and_persists_cancellation(tmp_path):
    import os
    import signal
    import subprocess
    import sys
    import time

    driver = tmp_path / "driver.py"
    driver.write_text("""
import json, sys
from pathlib import Path
from examples.dsh.capabilities import evaluate_work_state_tasks as suite
from deployment.services.harbor_training_supervisor import supervise
root = Path(sys.argv[1])
def prepare(**kwargs):
    kwargs['output_dir'].mkdir()
    value = {key: 'fixed' for key in suite.IDENTITY_FIELDS}
    value['environment'] = {key: '1' for key in suite.SAMPLING_FIELDS}
    value['environment']['RUN_ROOT'] = str(kwargs['run_root'])
    (kwargs['output_dir']/'manifest.json').write_text(json.dumps(value))
    return value
def launch(path):
    run = Path(json.loads(path.read_text())['environment']['RUN_ROOT'])
    run.mkdir()
    code = ("import os,time;from pathlib import Path;Path("
            + repr(str(root/'child.pid')) + ").write_text(str(os.getpid()));time.sleep(120)")
    return supervise([sys.executable, '-c', code], root, {}, run, lambda: None,
                     wall_seconds=60, interval=.05, grace=.2)
suite.recipe.prepare = prepare
suite.recipe.check = lambda path, **kwargs: json.loads(path.read_text())
suite.recipe.launch = launch
suite.require_idle_gpu = lambda: None
sys.argv = ['suite', '--root', str(root), '--suite-id', 'sigterm-cpu',
            '--runtime-executable', '/runtime', '--runner-python', sys.executable,
            '--model-path', '/model', '--model-revision', 'a'*40,
            '--mother-run', '/mother', '--resume-from', '/checkpoint/global_step_8']
raise SystemExit(suite.main())
""")
    root = tmp_path / "run"
    with (tmp_path / "driver.log").open("w") as output:
        process = subprocess.Popen([sys.executable, str(driver), str(root)], stdout=output, stderr=output)
        try:
            deadline = time.monotonic() + 45
            while not (root / "child.pid").exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.05)
            assert (root / "child.pid").exists(), (tmp_path / "driver.log").read_text()
            child = int((root / "child.pid").read_text())
            process.send_signal(signal.SIGTERM)
            assert process.wait(timeout=15) == 143
            report = json.loads((root / "summary.json").read_text())
            assert report["tasks"][0]["status"] == "cancelled"
            assert report["stop_reason"]["phase"] == "launch"
            assert all(row["status"] == "not_run" for row in report["tasks"][1:])
            with pytest.raises(ProcessLookupError):
                os.kill(child, 0)
        finally:
            if process.poll() is None:
                process.send_signal(signal.SIGINT)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


def test_last_task_post_run_checkpoint_drift_prevents_success(scenario, monkeypatch):
    inputs, calls, _ = scenario
    original = suite.recipe.check
    checked_after = []

    def check(path, **kwargs):
        result = original(path, **kwargs)
        if kwargs.get("after_run"):
            checked_after.append(len(calls))
            if len(calls) == 4:
                result["checkpoint_origin"] = {"identity": "changed-after-last-launch"}
        return result

    monkeypatch.setattr(suite.recipe, "check", check)
    result = suite.evaluate(**inputs)
    assert checked_after == [1, 2, 3, 4]
    assert result["all_attempted"] and not result["all_verified"]
    assert result["stop_reason"]["phase"] == "post-run-check"
