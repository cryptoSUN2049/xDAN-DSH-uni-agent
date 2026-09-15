"""Experimental native VERL V1 LoRA RL/OPD launcher over Uni-Agent Harbor tasks."""

from __future__ import annotations

import argparse
import json
import os
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", required=True, choices=MODES)
    parser.add_argument("--launch", required=True, type=Path, help="Private prepared Harbor launch.json")
    parser.add_argument("--print-config", action="store_true", help="Compose only; no Ray/GPU/controller requests")
    args = parser.parse_args()
    overrides = build_overrides(args.mode, json.loads(args.launch.read_bytes()), os.environ)
    config = compose_config(overrides)
    if args.print_config:
        print(OmegaConf.to_yaml(config))
        return
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
