import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path("examples/dsh/train_qwen3_4b_online_rl.sh")


def test_async_mode_and_tail_are_printed_without_losing_literal_arguments():
    tail = [
        "trainer.v1.trainer_mode=colocate_async",
        "trainer.v1.colocate_async.num_warmup_batches=2",
        "++custom.note='literal $HOME with spaces'",
    ]
    result = subprocess.run(
        ["bash", str(SCRIPT), *tail], capture_output=True, text=True, env={**os.environ, "PRINT_COMMAND": "1"}
    )
    assert result.returncode == 0, result.stderr
    assert shlex.split(result.stdout)[-len(tail) :] == tail


def test_async_mode_environment_is_explicit():
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        capture_output=True,
        text=True,
        env={**os.environ, "PRINT_COMMAND": "1", "TRAINER_MODE": "colocate_async", "NUM_WARMUP_BATCHES": "2"},
    )
    assert result.returncode == 0, result.stderr
    argv = shlex.split(result.stdout)
    assert "trainer.v1.trainer_mode=colocate_async" in argv
    assert "trainer.v1.colocate_async.num_warmup_batches=2" in argv


def test_actual_exec_matches_printed_async_and_tail_overrides(tmp_path):
    model = tmp_path / "model"
    model.mkdir()
    for name in ("config.json", "tokenizer_config.json"):
        (model / name).write_text("{}")
    data = tmp_path / "data"
    data.write_text("fixture")
    capture = tmp_path / "argv.json"
    fake_python = tmp_path / "python"
    fake_python.write_text(
        f"#!{sys.executable}\nimport json, os, sys\nfrom pathlib import Path\n"
        "if sys.argv[1] == '-m':\n"
        "    Path(os.environ['CAPTURE_ARGV']).write_text(json.dumps(sys.argv[1:]))\n"
    )
    fake_python.chmod(0o755)
    env = {
        **os.environ,
        "PYTHON_BIN": str(fake_python),
        "CAPTURE_ARGV": str(capture),
        "MODEL_PATH": str(model),
        "TRAIN_FILE": str(data),
        "TEST_FILE": str(data),
        "TASK_CONFIG": str(data),
        "RUN_ROOT": str(tmp_path / "run"),
        "MODEL_LICENSE_APPROVED": "1",
        "TRAINER_MODE": "colocate_async",
        "NUM_WARMUP_BATCHES": "2",
    }
    tail = ["trainer.v1.colocate_async.num_warmup_batches=3", "++custom.note='literal $HOME with spaces'"]
    printed = subprocess.run(
        ["bash", str(SCRIPT), *tail], env={**env, "PRINT_COMMAND": "1"}, capture_output=True, text=True
    )
    actual = subprocess.run(
        ["bash", str(SCRIPT), *tail], env={**env, "PRINT_COMMAND": "0"}, capture_output=True, text=True
    )
    assert actual.returncode == printed.returncode == 0, actual.stderr
    actual_args = json.loads(capture.read_text())
    printed_args = shlex.split(printed.stdout)
    assert actual_args[-len(tail) :] == printed_args[-len(tail) :] == tail
    for args in (actual_args, printed_args):
        assert "trainer.v1.trainer_mode=colocate_async" in args
        assert "trainer.v1.colocate_async.num_warmup_batches=3" in args


@pytest.mark.parametrize(
    "settings,tail",
    [
        ({"TRAINER_MODE": "separate_async"}, []),
        ({"NUM_WARMUP_BATCHES": "0"}, []),
        ({"NUM_WARMUP_BATCHES": "1.5"}, []),
        ({}, ["trainer.v1.trainer_mode=unknown"]),
        ({}, ["trainer.v1.colocate_async.num_warmup_batches=-1"]),
        ({}, ["++trainer.v1.trainer_mode=separate_async"]),
        ({}, ["~trainer.v1.trainer_mode"]),
    ],
)
def test_invalid_async_configuration_rejected_before_any_launch(settings, tail):
    result = subprocess.run(
        ["bash", str(SCRIPT), *tail],
        capture_output=True,
        text=True,
        env={**os.environ, "PRINT_COMMAND": "1", **settings},
    )
    assert result.returncode == 2
    assert not result.stdout


def test_qwen3_4b_launcher_has_valid_shell_syntax():
    result = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)

    assert result.returncode == 0, result.stderr


def test_qwen3_4b_launcher_prints_strict_online_rl_contract():
    env = {
        **os.environ,
        "PRINT_COMMAND": "1",
        "MODEL_PATH": "/models/Qwen3-4B-snapshot",
        "TRAIN_FILE": "/data/dsh-train.parquet",
        "TEST_FILE": "/data/dsh-validation.parquet",
        "RUN_ROOT": "/runs/dsh-test",
    }
    result = subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True, env=env)

    assert result.returncode == 0, result.stderr
    command = result.stdout
    for expected in (
        "Qwen/Qwen3-4B",
        "trainer.use_v1=True",
        "trainer.v1.trainer_mode=sync",
        "trainer.v1.sampler.sync_refill_failed_groups=True",
        "algorithm.adv_estimator=grpo",
        "actor_rollout_ref.model.lora_rank=32",
        "++actor_rollout_ref.model.override_config.attn_implementation=sdpa",
        "actor_rollout_ref.rollout.n=2",
        "actor_rollout_ref.rollout.val_kwargs.n=1",
        "actor_rollout_ref.rollout.multi_turn.format=hermes",
        "data.apply_chat_template_kwargs.enable_thinking=False",
        "uni_agent.framework.entry.AgentFrameworkRolloutAdapter",
        "runner_kwargs.require_result=True",
        "fail_on_rollout_error=True",
        "require_finished_episode=True",
        "require_verifier_reward=True",
        "require_trajectory_dump=True",
        "trajectory_postprocessor_fqn=uni_agent.tasks.dsh.trajectory_audit.validate_trajectories",
        "trajectory_postprocessor_pass_context=True",
        "runner_kwargs.dsh_trace_root=/runs/dsh-test/artifacts/traces",
        "runner_kwargs.dsh_result_root=/runs/dsh-test/artifacts/results",
        "trajectory_postprocessor_kwargs.trace_root=/runs/dsh-test/artifacts/traces",
        "trajectory_postprocessor_kwargs.result_root=/runs/dsh-test/artifacts/results",
        "trainer.save_freq=1",
        "trainer.total_training_steps=1",
        "data.train_max_samples=1",
        "data.val_max_samples=1",
        "data.shuffle=False",
    ):
        assert expected in command


def test_qwen3_4b_launcher_prints_4090_low_vram_profile():
    env = {
        **os.environ,
        "PRINT_COMMAND": "1",
        "LOW_VRAM": "1",
        "MODEL_PATH": "/models/Qwen3-4B-snapshot",
        "TRAIN_FILE": "/data/dsh-train.parquet",
        "TEST_FILE": "/data/dsh-validation.parquet",
    }
    result = subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True, env=env)

    assert result.returncode == 0, result.stderr
    command = result.stdout
    for expected in (
        "data.max_prompt_length=1024",
        "data.max_response_length=256",
        "actor_rollout_ref.model.lora_rank=4",
        "actor_rollout_ref.model.lora_alpha=8",
        "actor_rollout_ref.actor.fsdp_config.model_dtype=bfloat16",
        "actor_rollout_ref.actor.fsdp_config.param_offload=True",
        "actor_rollout_ref.rollout.enforce_eager=True",
        "actor_rollout_ref.rollout.free_cache_engine=True",
        "actor_rollout_ref.rollout.layered_summon=False",
        "++actor_rollout_ref.rollout.engine_kwargs.vllm.cpu_offload_gb=8",
        "++actor_rollout_ref.actor.checkpoint.save_lora_only=True",
    ):
        assert expected in command
