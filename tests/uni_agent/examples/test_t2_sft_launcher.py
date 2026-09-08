"""The native SFT launcher pins topology and forwards the declared dataset contract."""

import os
import shlex
import subprocess
from pathlib import Path

from hydra import compose, initialize_config_dir

ROOT = Path(__file__).resolve().parents[3]


def test_sft_launch_command_and_step_bound(tmp_path):
    env = {
        **os.environ,
        "PRINT_COMMAND": "1",
        "MODEL_PATH": "/models/fixed-qwen3-4b",
        "SFT_TRAIN": "/data/train.parquet",
        "SFT_DEV": "/data/dev.parquet",
        "SFT_RUN": str(tmp_path / "run"),
        "SFT_MAX_LENGTH": "16384",
        "SFT_STEPS": "1",
        "PYTHON_BIN": "python3",
    }
    command = ["bash", str(ROOT / "examples/dsh/ops/train_t2_lora_sft.sh")]
    result = subprocess.run(command, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "verl.trainer.sft_trainer" in result.stdout
    assert "data.custom_cls.name=DshDecisionSFTDataset" in result.stdout
    assert "model.lora_rank=16" in result.stdout
    assert "trainer.resume_mode=disable" in result.stdout
    assert "trainer.total_training_steps=1" in result.stdout
    assert not (tmp_path / "run").exists()
    argv = shlex.split(result.stdout)
    with initialize_config_dir(config_dir=str(ROOT / "verl/verl/trainer/config"), version_base=None):
        config = compose(config_name="sft_trainer_engine", overrides=argv[argv.index("verl.trainer.sft_trainer") + 1 :])
    assert config.engine.strategy == "fsdp"
    assert config.model.override_config.attn_implementation == "sdpa"
    assert config.data.custom_cls.name == "DshDecisionSFTDataset"
    assert config.model.lora_rank == 16 and config.trainer.total_training_steps == 1
    env["SFT_STEPS"] = "0"
    result = subprocess.run(command, env=env, capture_output=True, text=True)
    assert result.returncode != 0
