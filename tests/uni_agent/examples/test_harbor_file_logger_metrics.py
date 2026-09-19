"""Step metrics rebuilt from per-attempt VERL file-logger files (40_train.sh fallback)."""

import importlib.util
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
_SPEC = importlib.util.spec_from_file_location(
    "file_logger_metrics", ROOT / "examples/harbor_opd_rl/stages/file_logger_metrics.py"
)
file_logger_metrics = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(file_logger_metrics)


def write_attempt(path, rows, tail=""):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows) + tail)


def train_row(step, score):
    return {"step": step, "data": {"training/global_step": step, "critic/score/mean": score, "actor/lr": 1e-4}}


def test_a_resumed_run_keeps_both_attempts_and_the_later_one_wins(tmp_path):
    validation = {"step": 0, "data": {"val-aux/tasks-validation/reward/mean@4": 0.4}}
    write_attempt(tmp_path / "metrics-20260918T192629Z.jsonl", [validation, train_row(1, 0.5), train_row(2, 0.6)])
    # The resumed attempt repeats step 2 (a crash after logging), then continues;
    # a killed process can leave a cut line at the end.
    write_attempt(
        tmp_path / "metrics-20260919T060000Z.jsonl", [train_row(2, 0.7), train_row(3, 0.8)], tail='{"step": 4, "da'
    )
    lines = file_logger_metrics.console_lines(file_logger_metrics.step_rows(str(tmp_path)))
    assert [line.split(" - ")[0] for line in lines] == ["step:1", "step:2", "step:3"]
    assert "critic/score/mean:0.7" in lines[1]


def test_lines_parse_like_console_lines(tmp_path):
    row = train_row(5, 0.25)
    row["data"].update({"flag": True, "note": "text"})
    write_attempt(tmp_path / "metrics-20260919T000000Z.jsonl", [row])
    (line,) = file_logger_metrics.console_lines(file_logger_metrics.step_rows(str(tmp_path)))
    # The same regex metrics_json (stages/common.sh) applies to console lines.
    parsed = dict(re.findall(r"([\w/\-]+):(-?[0-9.]+(?:e-?\d+)?)", line))
    assert parsed["training/global_step"] == "5"
    assert float(parsed["actor/lr"]) == 1e-4
    assert "flag" not in line and "note" not in line


def test_no_files_gives_no_lines(tmp_path):
    assert file_logger_metrics.console_lines(file_logger_metrics.step_rows(str(tmp_path))) == []
