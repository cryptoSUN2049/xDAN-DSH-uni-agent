"""Stage 50_delta.sh diffs the earliest checkpoint that still has a model file against the final one."""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
STAGE = ROOT / "examples/harbor_opd_rl/stages/50_delta.sh"


def fake_python(tmp_path: Path) -> Path:
    # Stands in for the lane Python: records which two model files the probe compared and
    # writes a passing delta.json; any other invocation runs the real interpreter.
    stub = tmp_path / "python"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "$1" == deployment/checks/checkpoint_delta.py ]]; then\n'
        f'  echo "$2 $3" > {tmp_path}/compared.txt\n'
        '  out="$5"; echo \'{"passed": true, "adapter_changed": 4, "base_changed": 0}\' > "$out"; exit 0\n'
        "fi\n"
        f'exec {sys.executable} "$@"\n'
    )
    stub.chmod(0o755)
    return stub


def checkpoints(tmp_path: Path, steps_with_model, shells):
    ckdir = tmp_path / "run/train/checkpoints/proj/exp"
    for step in shells:  # rotated out: VERL keeps data.pt, deletes actor/
        (ckdir / f"global_step_{step}").mkdir(parents=True)
        (ckdir / f"global_step_{step}" / "data.pt").write_text("x")
    for step in steps_with_model:
        actor = ckdir / f"global_step_{step}" / "actor"
        actor.mkdir(parents=True)
        (actor / "model_world_size_1_rank_0.pt").write_text("w")
    final = ckdir / f"global_step_{max(steps_with_model)}"
    (tmp_path / "run/train/final-checkpoint.txt").write_text(str(final) + "\n")
    return ckdir


def run_stage(tmp_path: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "PIPE_ROOT": str(tmp_path / "run"), "LANE_PY": str(fake_python(tmp_path))}
    return subprocess.run(["bash", str(STAGE)], env=env, capture_output=True, text=True, timeout=60)


def test_skips_rotated_shells_and_diffs_the_earliest_real_checkpoint(tmp_path):
    ckdir = checkpoints(tmp_path, steps_with_model=[10, 11, 12], shells=[1, 2, 9])
    result = run_stage(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    before, after = (tmp_path / "compared.txt").read_text().split()
    assert before == str(ckdir / "global_step_10/actor/model_world_size_1_rank_0.pt")
    assert after == str(ckdir / "global_step_12/actor/model_world_size_1_rank_0.pt")
    summary = [json.loads(line) for line in (tmp_path / "run/pipeline-summary.jsonl").read_text().splitlines()]
    assert summary[-1]["status"] == "passed"


def test_numeric_order_not_lexical(tmp_path):
    ckdir = checkpoints(tmp_path, steps_with_model=[9, 10, 11], shells=[])
    assert run_stage(tmp_path).returncode == 0
    before, _ = (tmp_path / "compared.txt").read_text().split()
    assert before == str(ckdir / "global_step_9/actor/model_world_size_1_rank_0.pt")


def test_single_surviving_checkpoint_is_skipped(tmp_path):
    checkpoints(tmp_path, steps_with_model=[12], shells=[1, 2])
    result = run_stage(tmp_path)
    assert result.returncode == 0 and not (tmp_path / "compared.txt").exists()
    assert "skipped" in (tmp_path / "run/pipeline-summary.jsonl").read_text()
