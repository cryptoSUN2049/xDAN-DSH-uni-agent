"""Sequential OPD then RL (run_opd_then_rl.sh) and the checkpoint load-contents knob, without a GPU.

run_opd_round.sh is replaced by a stub (ROUND_SCRIPT) that records the environment each phase
receives and, for phase A, leaves the files a passed train stage leaves.
"""

import os
import re
import shlex
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = ROOT / "examples/harbor_opd_rl"
SCRIPT = EXAMPLES / "run_opd_then_rl.sh"
TRAIN_SCRIPT = EXAMPLES / "train_tb21_lora_smoke.sh"

STUB_ROUND = """#!/usr/bin/env bash
set -euo pipefail
mkdir -p "${PIPE_ROOT}"
env > "${PIPE_ROOT}/round-env.txt"
if [[ "${ROUND}" == *-opd && "${STUB_A_PASSES:-1}" == 1 ]]; then
  ck="${PIPE_ROOT}/train/checkpoints/project/pipe-train/global_step_${TRAIN_STEPS}"
  mkdir -p "${ck}" "${PIPE_ROOT}/data"
  echo /data/train.parquet > "${PIPE_ROOT}/data/train-parquet.txt"
  echo /data/validation.parquet > "${PIPE_ROOT}/data/full-parquet.txt"
  echo "${ck}" > "${PIPE_ROOT}/train/final-checkpoint.txt"
  date > "${PIPE_ROOT}/train/PASSED"
fi
exit "${STUB_EXIT:-0}"
"""


@pytest.mark.parametrize(
    "script", [SCRIPT, TRAIN_SCRIPT, EXAMPLES / "run_opd_round.sh", EXAMPLES / "stages/40_train.sh"]
)
def test_scripts_parse(script):
    subprocess.run(["bash", "-n", str(script)], check=True)


def train_command(**env):
    result = subprocess.run(
        ["bash", str(TRAIN_SCRIPT)],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PRINT_COMMAND": "1",
            "TRAIN_FILE": "/data/train.parquet",
            "TEST_FILE": "/data/validation.parquet",
            "RUN_ROOT": "/runs/unit",
            **env,
        },
    )
    return result


def load_contents(argv):
    return [arg for arg in argv if arg.startswith("actor_rollout_ref.actor.checkpoint.load_contents=")]


def test_load_contents_is_unchanged_without_the_knob():
    result = train_command(CKPT_LOAD_CONTENTS="")
    assert result.returncode == 0, result.stderr
    assert load_contents(shlex.split(result.stdout)) == [
        "actor_rollout_ref.actor.checkpoint.load_contents=['model','optimizer','extra']"
    ]


@pytest.mark.parametrize(
    "value,expected",
    [("model,extra", "['model','extra']"), ("model, optimizer ,extra", "['model','optimizer','extra']")],
)
def test_load_contents_follows_the_knob(value, expected):
    result = train_command(CKPT_LOAD_CONTENTS=value)
    assert result.returncode == 0, result.stderr
    # Replaced in place: one load_contents override, never a second conflicting one.
    assert load_contents(shlex.split(result.stdout)) == [f"actor_rollout_ref.actor.checkpoint.load_contents={expected}"]


@pytest.mark.parametrize("value", ["extra", "optimizer,extra", "model,,extra", "model,hf_model"])
def test_load_contents_rejects_lists_without_model_or_with_unknown_items(value):
    result = train_command(CKPT_LOAD_CONTENTS=value)
    assert result.returncode == 2
    assert "CKPT_LOAD_CONTENTS" in result.stderr


def test_train_stage_freezes_the_distillation_and_load_knobs():
    text = (EXAMPLES / "stages/40_train.sh").read_text()
    frozen = re.search(r"for v in (.*?); do", text, re.S).group(1).split()
    for knob in ("DISTILL_USE_TASK_REWARDS", "DISTILL_LOSS_COEF", "DISTILL_LOSS_MODE", "CKPT_LOAD_CONTENTS"):
        assert knob in frozen


KNOBS = {"NAME", "OPD_STEPS", "RL_STEPS", "PHASE", "CKPT_LOAD_CONTENTS", "DATA_DIR", "A_SKIP_STAGES", "B_SKIP_STAGES"}


def run(tmp_path, **env):
    stub = tmp_path / "stub_round.sh"
    stub.write_text(STUB_ROUND)
    settings = {"NAME": "pipe-t", "OPD_STEPS": "3", "RL_STEPS": "5", "LANE_ROOT": str(tmp_path / "lane")}
    settings.update(ROUND_SCRIPT=str(stub), **env)
    base = {k: v for k, v in os.environ.items() if k not in KNOBS | {"B_VAL_BEFORE_TRAIN"}}
    base.update({k: v for k, v in settings.items() if v is not None})
    return subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True, env=base)


def round_env(tmp_path, phase):
    path = tmp_path / f"lane/runs/pipe-t-{phase}/round-env.txt"
    return dict(line.split("=", 1) for line in path.read_text().splitlines() if "=" in line)


def test_requires_a_name(tmp_path):
    result = run(tmp_path, NAME=None)
    assert result.returncode != 0
    assert "NAME" in result.stderr
    assert not (tmp_path / "lane").exists()


def test_phase_a_is_pure_opd_and_phase_b_continues_from_its_checkpoint(tmp_path):
    result = run(tmp_path, LR="1e-4")
    assert result.returncode == 0, result.stdout + result.stderr
    a, b = round_env(tmp_path, "opd"), round_env(tmp_path, "rl")
    a_ckpt = tmp_path / "lane/runs/pipe-t-opd/train/checkpoints/project/pipe-train/global_step_3"

    assert a["ROUND"] == "pipe-t-opd" and a["PIPE_ROOT"] == str(tmp_path / "lane/runs/pipe-t-opd")
    assert (a["TEACHER"], a["DISTILL_USE_TASK_REWARDS"], a["TRAIN_STEPS"]) == ("1", "False", "3")
    assert a["SKIP_STAGES"] == "resume acceptance" and a["FROM_STAGE"] == ""
    # A relaunch of A continues A with its own optimizer state.
    assert (a["RESUME_MODE"], a["CKPT_LOAD_CONTENTS"]) == ("auto", "")

    assert b["ROUND"] == "pipe-t-rl" and b["PIPE_ROOT"] == str(tmp_path / "lane/runs/pipe-t-rl")
    assert (b["TEACHER"], b["FROM_STAGE"], b["TRAIN_STEPS"]) == ("0", "train", "8")
    assert (b["RESUME_MODE"], b["RESUME_FROM_PATH"]) == ("resume_path", str(a_ckpt))
    assert b["CKPT_LOAD_CONTENTS"] == "model"
    assert (b["SKIP_STAGES"], b["VAL_BEFORE_TRAIN"]) == ("resume acceptance", "False")
    # Same task copy for both phases, and ordinary round knobs reach both unchanged.
    assert a["DATA_DIR"] == b["DATA_DIR"] == str(tmp_path / "lane/data-pipe-t-opd")
    assert a["LR"] == b["LR"] == "1e-4"
    b_data = tmp_path / "lane/runs/pipe-t-rl/data"
    assert (b_data / "train-parquet.txt").read_text() == "/data/train.parquet\n"
    assert (b_data / "full-parquet.txt").read_text() == "/data/validation.parquet\n"


def test_load_contents_for_phase_b_can_be_overridden(tmp_path):
    assert run(tmp_path, CKPT_LOAD_CONTENTS="model").returncode == 0
    assert round_env(tmp_path, "rl")["CKPT_LOAD_CONTENTS"] == "model"
    assert round_env(tmp_path, "opd")["CKPT_LOAD_CONTENTS"] == ""


def test_phase_b_refuses_when_phase_a_did_not_pass(tmp_path):
    result = run(tmp_path, STUB_A_PASSES="0", STUB_EXIT="1")
    assert result.returncode == 1
    assert "refusing phase B" in result.stdout
    assert not (tmp_path / "lane/runs/pipe-t-rl").exists()


def test_phase_b_only_refuses_without_phase_a(tmp_path):
    result = run(tmp_path, PHASE="b")
    assert result.returncode == 1
    assert "phase A has not passed" in result.stdout
    assert not (tmp_path / "lane/runs").exists()


def test_phase_b_refuses_when_a_stopped_at_another_step(tmp_path):
    assert run(tmp_path, PHASE="a").returncode == 0
    result = run(tmp_path, PHASE="b", OPD_STEPS="4")
    assert result.returncode == 1
    assert "global_step_4" in result.stdout


def test_phase_a_post_training_failure_does_not_block_phase_b(tmp_path):
    # e.g. the cost stage failing after train passed: A's checkpoint is still valid.
    result = run(tmp_path, STUB_EXIT="1", PHASE="all")
    assert result.returncode == 1  # the stub fails for B as well
    assert "phase A exited 1" in result.stdout
    assert (tmp_path / "lane/runs/pipe-t-rl/round-env.txt").exists()


def test_phase_b_relaunch_continues_from_its_own_checkpoint(tmp_path):
    assert run(tmp_path, PHASE="a").returncode == 0
    own = tmp_path / "lane/runs/pipe-t-rl/train/checkpoints/project/pipe-train"
    own.mkdir(parents=True)
    (own / "latest_checkpointed_iteration.txt").write_text("6")
    assert run(tmp_path, PHASE="b").returncode == 0
    b = round_env(tmp_path, "rl")
    assert (b["RESUME_MODE"], b["RESUME_FROM_PATH"], b["CKPT_LOAD_CONTENTS"]) == ("auto", "", "")
    assert "own newest checkpoint" in (tmp_path / "lane/runs/pipe-t-rl/handover.log").read_text()
