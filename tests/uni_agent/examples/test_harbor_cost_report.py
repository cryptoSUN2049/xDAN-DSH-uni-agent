"""The per-run Modal cost check behind stage 90_cost.sh."""

import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
_SPEC = importlib.util.spec_from_file_location("cost_report", ROOT / "examples/harbor_opd_rl/stages/cost_report.py")
cost_report = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(cost_report)


def row(app, hour, resource, cost):
    hour_start = f"2026-09-18T{hour:02d}:00:00"
    return {"description": app, "interval_start": hour_start, "resource": resource, "cost": str(cost)}


def test_sandbox_prices_reproduce_the_2026_09_17_bill():
    # 683 of 698 sandboxes ran at 2 cores / 4 GiB for about 950 sandbox-hours in total.
    assert 267.88 / cost_report.CPU_USD_PER_CORE_HOUR / 2 == pytest.approx(944, abs=5)
    assert 90.20 / cost_report.MEM_USD_PER_GIB_HOUR / 4 == pytest.approx(939, abs=5)


def test_billing_counts_only_the_runs_app_from_its_start_hour():
    rows = [
        row("verl-harbor", 2, "CPU", 1.0),  # an earlier smoke, before this run
        row("verl-harbor", 3, "CPU", 0.5),  # the hour the run started in
        row("verl-harbor", 3, "Memory", 0.1),
        row("verl-harbor", 4, "CPU", 2.0),
        row("verl-harbor", 4, "A10G", 0),
        row("__harbor__", 4, "CPU", 9.0),  # another line's app
    ]
    start = datetime(2026, 9, 18, 3, 26, 58, tzinfo=timezone.utc)
    totals, latest = cost_report.billed_by_resource(rows, "verl-harbor", start)
    assert totals == {"CPU": 2.5, "Memory": 0.1, "A10G": 0.0}
    assert latest == "2026-09-18T04:00:00"


def test_a_leak_like_2026_09_17_breaches_and_a_clean_run_passes():
    one_core_hour = cost_report.CPU_USD_PER_CORE_HOUR
    leaky = cost_report.evaluate(trials=700, used_hours=200, billed={"CPU": 950 * one_core_hour}, leaked=3)
    assert not leaky["passed"]
    assert any(b.startswith("billed_to_used_ratio=4.75") for b in leaky["breaches"])
    assert "leaked_sandboxes=3" in leaky["breaches"]

    clean = cost_report.evaluate(
        trials=640, used_hours=115, billed={"CPU": 120 * one_core_hour, "Memory": 3.0}, leaked=0
    )
    assert clean["passed"], clean["breaches"]
    assert clean["billed_to_used_ratio"] == pytest.approx(1.04, abs=0.01)


def test_a_missing_measurement_is_a_breach_not_a_pass():
    checks = cost_report.evaluate(trials=371, used_hours=66.5, billed=None, leaked=None)
    assert not checks["passed"]
    assert checks["breaches"] == ["unmeasured:billing", "unmeasured:leaked_sandboxes"]


def test_trial_hours_and_run_start_read_the_run_root(tmp_path):
    log = tmp_path / "train/agent-logs/x/task.log"
    log.parent.mkdir(parents=True)
    log.write_text(
        "Harbor trial done: instance_id=a reward=1.000 resolved=True elapsed=1800.0s\n"
        "noise\nHarbor trial done: instance_id=b reward=0.000 resolved=False elapsed=1800.0s\n"
    )
    (tmp_path / "pipeline-summary.jsonl").write_text(
        "\x00\x00\n" + json.dumps({"stage": "driver", "status": "start", "utc": "2026-09-18T03:26:58Z"}) + "\n"
    )
    assert cost_report.trial_hours(tmp_path) == (1.0, 2)
    assert cost_report.run_start(tmp_path) == datetime(2026, 9, 18, 3, 26, 58, tzinfo=timezone.utc)


def test_app_comes_from_the_task_config(tmp_path):
    cfg = tmp_path / "task.yaml"
    cfg.write_text("- name: harbor\n  harbor_env: modal\n  environment_kwargs:\n    app_name: verl-harbor\n")
    assert cost_report.app_from_task_config(cfg) == "verl-harbor"
    cfg.write_text("- name: harbor\n  harbor_env: modal\n")
    assert cost_report.app_from_task_config(cfg) == "__harbor__"
    # Every stage that creates sandboxes must land in the app the cost stage measures.
    for name in ("tb21_terminus2_smoke.yaml", "tb21_oracle.yaml"):
        assert cost_report.app_from_task_config(ROOT / "examples/harbor_opd_rl" / name) == "verl-harbor"
