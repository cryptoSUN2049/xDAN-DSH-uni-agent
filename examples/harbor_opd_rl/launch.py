"""Experimental native VERL V1 LoRA RL/OPD launcher over Uni-Agent Harbor tasks."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

from hydra import compose, initialize_config_dir
from omegaconf import OmegaConf

from examples.harbor.train_m2_online_rl import _hydra

RECIPE = Path(__file__).resolve().parent
ROOT = RECIPE.parents[1]
FRAMEWORK = "actor_rollout_ref.rollout.custom.agent_framework"
MODES = ("rl", "opd", "hybrid")


def _required(values: Mapping[str, str], key: str) -> str:
    value = values.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be explicitly supplied")
    return value


def _overrides(values: dict, prefix: str = ""):
    for key, value in values.items():
        name = f"{prefix}.{key}" if prefix else key
        if name == "actor_rollout_ref.rollout.custom":
            yield f"++{name}={_hydra(value)}"
        elif name == "actor_rollout_ref.rollout.agent.agent_loop_manager_class":
            yield f"++{name}={_hydra(value)}"
        elif isinstance(value, dict):
            yield from _overrides(value, name)
        else:
            yield f"{name}={_hydra(value)}"


def build_overrides(mode: str, launch: dict, environment: Mapping[str, str]) -> list[str]:
    """Keep prepared controller registration/receipt policy and native config fields."""
    if mode not in MODES:
        raise ValueError(f"Unsupported mode: {mode}")
    if launch.get("schema") != "dsh.harbor-m2-launch.v1":
        raise ValueError("Expected prepared dsh.harbor-m2-launch.v1 schema")
    student = _required(environment, "STUDENT_MODEL_PATH")
    prepared = launch["environment"]
    run_root = Path(_required(prepared, "RUN_ROOT")) / f"{mode}-training"
    cfg = OmegaConf.merge(OmegaConf.load(RECIPE / "base.yaml"), OmegaConf.load(RECIPE / f"{mode}.yaml"))
    cfg.actor_rollout_ref.model.path = student
    cfg.actor_rollout_ref.rollout.multi_turn.format = _required(environment, "TOOL_PARSER")
    if mode != "rl":
        cfg.distillation.teacher_models.teacher_model.model_path = _required(environment, "TEACHER_MODEL_PATH")
    # Explicit environment overrides permit independently prepared train/holdout files.
    cfg.data.train_files = environment.get("TRAIN_FILE") or _required(prepared, "TRAIN_FILE")
    cfg.data.val_files = environment.get("TEST_FILE") or _required(prepared, "TEST_FILE")
    cfg.trainer.experiment_name = f"harbor-{mode}"
    cfg.trainer.default_local_dir = str(run_root / "checkpoints")
    cfg.trainer.rollout_data_dir = str(run_root / "rollout")
    cfg.trainer.validation_data_dir = str(run_root / "validation")
    framework = OmegaConf.select(cfg, FRAMEWORK)
    framework.log_dir = str(run_root / "agent")
    framework.trajectory_postprocessor_kwargs = launch["postprocessor"]
    kwargs = framework.agent_runners.task.runner_kwargs
    kwargs.task_config_path = environment.get("TASK_CONFIG") or _required(prepared, "TASK_CONFIG")
    kwargs.model_name = _required(prepared, "MODEL_ID")
    kwargs.harbor_route_registration = launch["registration"]
    return list(_overrides(OmegaConf.to_container(cfg, resolve=True)))


def compose_config(overrides: list[str]):
    with initialize_config_dir(config_dir=str(ROOT / "verl/verl/trainer/config"), version_base=None):
        return compose(config_name="ppo_trainer", overrides=overrides)


def finalize_training_plan(config, *, train_rows: int, validation_rows: int) -> dict:
    """Make the explicit outer-step budget reachable with the native epoch loop."""
    batch = config.data.train_batch_size
    steps = config.trainer.total_training_steps
    save_freq = config.trainer.save_freq
    for name, value in [("train_batch_size", batch), ("total_training_steps", steps), ("save_freq", save_freq)]:
        if type(value) is not int or value < 1:
            raise ValueError(f"{name} must be a positive integer")
    if type(train_rows) is not int or train_rows < batch:
        raise ValueError(f"Effective training dataset has {train_rows} rows, fewer than one batch of {batch}")
    if type(validation_rows) is not int or validation_rows < 1:
        raise ValueError("Effective validation dataset must contain at least one row")
    steps_per_epoch = train_rows // batch
    # VERL checks both limits. Its final-step branch saves even off the save interval.
    config.trainer.total_epochs = (steps + steps_per_epoch - 1) // steps_per_epoch
    return {
        "train_rows": train_rows,
        "validation_rows": validation_rows,
        "steps_per_epoch": steps_per_epoch,
        "total_training_steps": steps,
        "total_epochs": config.trainer.total_epochs,
        "save_freq": save_freq,
    }


def preflight_training(config) -> dict:
    """Use the trainer's tokenizer/processor and filtered datasets before starting Ray."""
    from verl.trainer.ppo.utils import create_rl_dataset
    from verl.utils.config import omega_conf_to_dataclass

    sampling_subset = any(config.data.get(f"{part}_max_samples", -1) > 0 for part in ("train", "val"))
    if sampling_subset and config.data.shuffle and config.data.get("seed") is None:
        raise ValueError("A fixed data.seed is required when preflight randomly selects a dataset subset")
    model = omega_conf_to_dataclass(config.actor_rollout_ref.model)
    counts = {}
    for partition, is_train in [("train", True), ("val", False)]:
        dataset = create_rl_dataset(
            config.data[f"{partition}_files"],
            config.data,
            model.tokenizer,
            model.processor,
            is_train=is_train,
            max_samples=config.data.get(f"{partition}_max_samples", -1),
        )
        counts[partition] = len(dataset)
    return finalize_training_plan(config, train_rows=counts["train"], validation_rows=counts["val"])


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _validate_resume(config) -> None:
    if config.trainer.resume_mode == "disable":
        return
    checkpoint = Path(config.trainer.resume_from_path)
    match = re.fullmatch(r"global_step_(\d+)", checkpoint.name)
    if not match or not (checkpoint / "actor").is_dir() or not (checkpoint / "data.pt").is_file():
        raise ValueError("Resume checkpoint requires global_step_N/actor and global_step_N/data.pt")
    if int(match[1]) >= config.trainer.total_training_steps:
        raise ValueError("total_training_steps must exceed the checkpoint step when resuming")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", required=True, choices=MODES)
    parser.add_argument("--launch", required=True, type=Path, help="Private prepared Harbor launch.json")
    parser.add_argument("--print-config", action="store_true", help="Compose only; no Ray/GPU/controller requests")
    parser.add_argument("--preflight-only", action="store_true", help="Check tokenizer and filtered data; no training")
    parser.add_argument(
        "--total-training-steps", type=_positive_int, help="Absolute outer-step target, including resume"
    )
    parser.add_argument(
        "--save-freq", type=_positive_int, help="Checkpoint interval; final target step is always saved"
    )
    parser.add_argument("--resume-from-path", type=Path, help="Explicit native global_step_N checkpoint to restore")
    args = parser.parse_args()
    overrides = build_overrides(args.mode, json.loads(args.launch.read_bytes()), os.environ)
    for key, value in [("total_training_steps", args.total_training_steps), ("save_freq", args.save_freq)]:
        if value is not None:
            overrides.append(f"trainer.{key}={value}")
    if args.resume_from_path is not None:
        overrides.extend(
            [
                "trainer.resume_mode=resume_path",
                f"trainer.resume_from_path={_hydra(str(args.resume_from_path.resolve()))}",
            ]
        )
    config = compose_config(overrides)
    if args.print_config:
        print(OmegaConf.to_yaml(config))
        return
    _validate_resume(config)
    report = preflight_training(config)
    overrides.append(f"trainer.total_epochs={config.trainer.total_epochs}")
    # Recompose the exact command, rather than validating a config the child never sees.
    compose_config(overrides)
    report.update(resume_mode=config.trainer.resume_mode, resume_from_path=config.trainer.resume_from_path)
    if args.preflight_only:
        print(json.dumps(report, indent=2))
        return
    run_root = Path(config.trainer.default_local_dir).parent
    run_root.mkdir(parents=True, exist_ok=True)
    (run_root / "training-preflight.json").write_text(json.dumps(report, indent=2) + "\n")
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(ROOT), str(ROOT / "verl"), *filter(None, [environment.get("PYTHONPATH")])]
    )
    # Execute precisely the overrides that passed native Hydra composition.
    subprocess.run(
        [sys.executable, "-m", "verl.trainer.main_ppo", "--config-name=ppo_trainer", *overrides],
        cwd=ROOT,
        env=environment,
        check=True,
    )


if __name__ == "__main__":
    main()
