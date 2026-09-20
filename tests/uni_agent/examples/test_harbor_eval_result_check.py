"""Exercise the real shell entry using a fake GPU/trainer, never a real model."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[3]


def run_eval(tmp_path, events, trainer_code=0, resumed=False, load=True):
    scripts = tmp_path / "examples/harbor_opd_rl"
    scripts.mkdir(parents=True)
    for name in ("eval_val_only.sh", "eval_result_check.py"):
        source = ROOT / "examples/harbor_opd_rl" / name
        if source.exists():
            shutil.copy(source, scripts / name)
    (scripts / "train_tb21_lora_smoke.sh").write_text(
        'mkdir -p "$RUN_ROOT/agent-logs/session"\n'
        + "cat > \"$RUN_ROOT/agent-logs/session/task.log\" <<'EVENTS'\n"
        + events
        + "\nEVENTS\n"
        + ('echo "Loaded model from $RESUME_FROM_PATH/actor/model_world_size_1_rank_0.pt"\n' if load else "")
        + f"exit {trainer_code}\n"
    )
    bindir = tmp_path / "bin"
    bindir.mkdir()
    gpu = bindir / "nvidia-smi"
    gpu.write_text("#!/bin/sh\necho 0\n")
    gpu.chmod(0o755)
    data = tmp_path / "tasks.parquet"
    pd.DataFrame(
        [
            {"extra_info": {"tools_kwargs": {"task": {"metadata": {"instance_id": f"eval/{name}"}}}}}
            for name in ("a", "b")
        ]
    ).to_parquet(data)
    (tmp_path / "config.json").write_text("{}")
    checkpoint = tmp_path / "checkpoint"
    (checkpoint / "actor").mkdir(parents=True)
    output = tmp_path / "result"
    env = os.environ | {
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "LANE_PY": sys.executable,
        "EVAL_ROOT": str(output),
        "EVAL_DATA": str(data),
        "TRAIN_DATA": str(data),
        "TASK_CONFIG": str(tmp_path / "config.json"),
        "MODEL_PATH": str(tmp_path),
        "CUDA_VISIBLE_DEVICES": "0",
        "EVAL_N": "2",
        "RESUME_FROM": str(checkpoint) if resumed else "",
        "EVAL_RUN": "",
        "EVAL_LIMIT": "0",
    }
    result = subprocess.run(["bash", str(scripts / "eval_val_only.sh")], env=env, capture_output=True, text=True)
    return result, json.loads((output / "summary.json").read_text())


def done(name):
    return f"Harbor trial done: instance_id=eval/{name} reward=1.000 resolved=True"


@pytest.mark.parametrize(
    "events",
    [
        "",
        "\n".join([done("a")] * 2),
        "\n".join([done("a")] * 2 + [done("b")]),
        "\n".join([done("a")] * 2 + [done("c")] * 2),
        "\n".join([done("a")] * 3 + [done("b")]),
        "\n".join([done("a"), done("b")] * 2).replace("eval/", "other/"),
    ],
)
def test_rejects_empty_missing_sample_and_wrong_identity(tmp_path, events):
    result, summary = run_eval(tmp_path, events)
    assert result.returncode != 0
    assert summary["status"] == "incomplete"


def test_failed_trainer_preserves_summary_and_exit(tmp_path):
    result, summary = run_eval(tmp_path, "\n".join([done("a"), done("b")] * 2), trainer_code=17)
    assert result.returncode == 17
    assert summary["status"] == "failed"
    assert summary["samples"] == 4


def test_checkpoint_requires_load_evidence(tmp_path):
    result, summary = run_eval(tmp_path, "\n".join([done("a"), done("b")] * 2), resumed=True, load=False)
    assert result.returncode != 0
    assert summary["status"] == "failed"


def test_complete_resumed_eval(tmp_path):
    result, summary = run_eval(tmp_path, "\n".join([done("a"), done("b")] * 2), resumed=True)
    assert result.returncode == 0, result.stderr
    assert summary["status"] == "complete"
    assert summary["checkpoint_loaded"] is True
    assert summary["per_task"] == {"a": [1.0, 1.0], "b": [1.0, 1.0]}

    receipt = json.loads((tmp_path / "result/validation.json").read_text())
    assert receipt["status"] == "complete"
    assert receipt["expected_n"] == 2
    assert receipt["process_exit"] == 0
