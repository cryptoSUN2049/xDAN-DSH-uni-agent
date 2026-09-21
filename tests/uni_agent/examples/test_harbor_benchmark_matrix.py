import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "benchmark_matrix", Path(__file__).resolve().parents[3] / "examples/harbor_opd_rl/eval_benchmark_matrix.py"
)
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def test_short_names_unique_with_shared_long_prefix():
    names = [mod.run_name("probe", "benchmark-long-shared-prefix", name) for name in ["base", "opd12", "rl60"]]
    assert len(set(n[:24] for n in names)) == 3
    assert all(len(n) <= 24 for n in names)


def write_result(path, checkpoint=""):
    path.mkdir()
    (path / "validation.json").write_text(
        json.dumps(
            {
                "status": "complete",
                "process_exit": 0,
                "checkpoint_loaded": True,
                "data": "/data.parquet",
                "resume_from": checkpoint,
                "expected_tasks": 2,
                "expected_n": 3,
                "unexpected_task_ids": [],
                "sample_count_mismatches": {},
            }
        )
    )
    (path / "eval-config.json").write_text(
        json.dumps(
            {
                "data": "/data.parquet",
                "resume_from": checkpoint,
                "n": 3,
                "tasks": 2,
                "task_config": "/task.yaml",
                "model_path": "/model",
            }
        )
    )
    (path / "summary.json").write_text(json.dumps({"per_task": {"a": [0] * 3, "b": [0] * 3}}))


def test_zero_score_complete_and_wrong_checkpoint_rejected(tmp_path):
    out = tmp_path / "r"
    write_result(out)
    assert mod.complete(out, ["ds/a", "ds/b"], "/data.parquet", 3, "", "/task.yaml", "/model")
    assert not mod.complete(out, ["ds/a", "ds/b"], "/data.parquet", 3, "/checkpoint", "/task.yaml", "/model")
    assert not mod.complete(out, ["ds/a", "ds/c"], "/data.parquet", 3, "", "/task.yaml", "/model")


def test_stopfile_blocks(tmp_path):
    stop = tmp_path / "STOP"
    stop.touch()
    with pytest.raises(RuntimeError, match="stop file"):
        mod.check_stop({"stop_file": str(stop)})


def test_schedule_all_probes_before_full():
    jobs = mod.jobs({"label": "tb"}, [{"label": x} for x in ["base", "opd12", "rl60"]])
    assert [(x["phase"], x["version"]["label"]) for x in jobs] == [
        (p, v) for p in ["probe", "full"] for v in ["base", "opd12", "rl60"]
    ]


def test_resume_complete_does_not_launch_or_wait(tmp_path, monkeypatch):
    cfg = {"env": {"MODEL_PATH": "/model"}, "python": "/python", "gpu": 1}
    ds = {"label": "tb", "task_config": "/task.yaml"}
    job = mod.jobs(ds, [{"label": "base", "checkpoint": ""}])[1]
    output = tmp_path / job["name"]
    write_result(output)
    monkeypatch.setattr(mod, "launch", lambda *a: pytest.fail("should not launch complete run"))
    monkeypatch.setattr(mod, "wait_gpu", lambda *a: pytest.fail("should not wait on complete run"))
    assert mod.run_job(cfg, ds, job, "/data.parquet", ["ds/a", "ds/b"], 3, tmp_path, tmp_path) == output


def test_existing_failed_attempt_never_relaunched(tmp_path, monkeypatch):
    cfg = {"env": {"MODEL_PATH": "/model"}, "python": "/python", "gpu": 1}
    ds = {"label": "tb", "task_config": "/task.yaml"}
    job = mod.jobs(ds, [{"label": "base", "checkpoint": ""}])[0]
    (tmp_path / job["name"]).mkdir()
    monkeypatch.setattr(mod, "launch", lambda *a: pytest.fail("must not rerun failed attempt"))
    with pytest.raises(RuntimeError, match="no validation evidence"):
        mod.run_job(cfg, ds, job, "/data.parquet", ["ds/a", "ds/b"], 3, tmp_path, tmp_path)


def test_dataset_identity_and_hash(tmp_path):
    import pandas as pd

    data = tmp_path / "tasks.parquet"
    pd.DataFrame(
        [{"extra_info": {"tools_kwargs": {"task": {"metadata": {"instance_id": f"ds/{i}"}}}}} for i in range(3)]
    ).to_parquet(data)
    config = tmp_path / "config.yaml"
    config.write_text("fixed: true")
    ds = {
        "label": "tb",
        "data": str(data),
        "sha256": mod.sha(data),
        "tasks": 3,
        "n": 3,
        "task_config": str(config),
        "task_config_sha256": mod.sha(config),
        "probe_ids": ["ds/0", "ds/1", "ds/2"],
    }
    assert mod.validate_dataset(ds)[1] == ["ds/0", "ds/1", "ds/2"]
    config.write_text("changed: true")
    with pytest.raises(ValueError, match="hash mismatch"):
        mod.validate_dataset(ds)


def test_probe_only_schedule_and_names_reusable():
    versions = [{"label": x} for x in ["base", "opd12", "rl60"]]
    probe = mod.jobs({"label": "tb"}, versions, probe_only=True)
    normal = mod.jobs({"label": "tb"}, versions)
    assert len(probe) == 3
    assert all(job["phase"] == "probe" for job in probe)
    assert [job["name"] for job in probe] == [job["name"] for job in normal[:3]]


def test_report_shows_complete_rates_and_pending_versions(tmp_path):
    state = mod.jobs({"label": "tb"}, [{"label": x} for x in ["base", "opd12", "rl60"]])
    state[3].update(status="complete", rate=0.5)
    state[4].update(status="complete", rate=0.25, comparison={"diff": -0.25, "ci95": [-0.4, -0.1]})
    report = tmp_path / "report.md"
    mod.write_report(report, state)
    text = report.read_text()
    assert "50.00%" in text and "25.00%" in text and "-0.25" in text
    assert "| tb | full | rl60 | pending |" in text


def test_behavior_command_base_and_pair(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(mod.subprocess, "run", lambda command, **kwargs: calls.append(command))
    mod.behavior_report("/python", tmp_path, tmp_path / "base", tmp_path / "base", "base")
    mod.behavior_report("/python", tmp_path, tmp_path / "base", tmp_path / "trained", "rl60")
    assert calls[0].count(f"base={tmp_path / 'base'}") == 1
    assert f"rl60={tmp_path / 'trained'}" in calls[1]
