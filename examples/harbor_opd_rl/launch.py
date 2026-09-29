"""Experimental native VERL V1 LoRA RL/OPD launcher over Uni-Agent Harbor tasks."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Mapping
from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from hydra import compose, initialize_config_dir
from omegaconf import OmegaConf
from packaging.version import InvalidVersion, Version

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
        if name in {
            "actor_rollout_ref.model.override_config",
            "actor_rollout_ref.rollout.custom",
            "actor_rollout_ref.rollout.engine_kwargs",
        }:
            yield f"++{name}={_hydra(value)}"
        elif name == "actor_rollout_ref.rollout.agent.agent_loop_manager_class":
            yield f"++{name}={_hydra(value)}"
        elif isinstance(value, dict):
            yield from _overrides(value, name)
        else:
            yield f"{name}={_hydra(value)}"


def _validate_termination_recipe(mode: str, config, postprocessor: dict) -> None:
    """Bind the opt-in finite-budget objective to independently prepared inputs."""
    framework = OmegaConf.select(config, FRAMEWORK)
    policy = framework.get("termination_policy", "completed-only")
    template = postprocessor.get("policy_template", {})
    if not isinstance(template, Mapping):
        raise ValueError("Prepared termination policy template must be a mapping")
    declarations = (
        policy,
        postprocessor.get("termination_policy", "completed-only"),
        template.get("termination_policy", "completed-only"),
    )
    if policy not in ("completed-only", "budget-terminal-v1") or any(value != policy for value in declarations):
        raise ValueError("Recipe and prepared termination policies must match")
    if policy == "completed-only":
        return
    if mode != "rl" or config.algorithm.adv_estimator != "grpo" or config.distillation.enabled is not False:
        raise ValueError("Budget-terminal requires RL with GRPO and no distillation")
    if not postprocessor.get("mimo_binding"):
        raise ValueError("Budget-terminal currently requires a prepared MiMo binding")
    limits = postprocessor.get("budget_limits")
    template_limits = template.get("budget_limits")
    for value in (limits, template_limits):
        if (
            not isinstance(value, Mapping)
            or set(value) != {"max_generated_tokens", "trajectory_capacity"}
            or any(type(item) is not int or item <= 0 for item in value.values())
        ):
            raise ValueError("Prepared budget limits must be exact positive integer limits")
    if limits != template_limits:
        raise ValueError("Prepared budget limits differ from the registered policy template")
    rollout, actor = config.actor_rollout_ref.rollout, config.actor_rollout_ref.actor
    generated = framework.get("max_generated_tokens_per_episode")
    if type(generated) is not int or generated != limits["max_generated_tokens"]:
        raise ValueError("Recipe generated budget differs from prepared operator limits")
    data_prompt, data_response = config.data.max_prompt_length, config.data.max_response_length
    prompt = rollout.get("prompt_length", data_prompt)
    response = rollout.get("response_length", data_response)
    capacity = limits["trajectory_capacity"]
    values = (data_prompt, data_response, prompt, response, rollout.max_model_len)
    if (
        any(type(value) is not int or value <= 0 for value in values)
        or data_prompt + data_response != capacity
        or prompt + response != capacity
        or rollout.max_model_len != capacity
    ):
        raise ValueError("Recipe context capacity differs from prepared budget limits")
    for value in (actor.ppo_max_token_len_per_gpu, rollout.log_prob_max_token_len_per_gpu):
        if type(value) is not int or value < capacity:
            raise ValueError("Training and logprob capacity must cover the prepared context budget")
    for name in (
        "fail_on_rollout_error",
        "require_finished_episode",
        "require_verifier_reward",
        "require_trajectory_dump",
        "require_version_evidence",
    ):
        if framework.get(name) is not True:
            raise ValueError(f"Budget-terminal requires {name}=true")
    if framework.get("mask_unfinished_episode", False) is not False:
        raise ValueError("Budget-terminal requires mask_unfinished_episode=false")


def build_overrides(
    mode: str,
    launch: dict,
    environment: Mapping[str, str],
    *,
    recipe_config: str | Path | None = None,
    experiment_name: str | None = None,
) -> list[str]:
    """Keep prepared controller registration/receipt policy and native config fields."""
    if mode not in MODES:
        raise ValueError(f"Unsupported mode: {mode}")
    if launch.get("schema") != "dsh.harbor-m2-launch.v1":
        raise ValueError("Expected prepared dsh.harbor-m2-launch.v1 schema")
    student = _required(environment, "STUDENT_MODEL_PATH")
    prepared = launch["environment"]
    run_root = Path(_required(prepared, "RUN_ROOT")) / f"{mode}-training"
    cfg = OmegaConf.merge(OmegaConf.load(RECIPE / "base.yaml"), OmegaConf.load(RECIPE / f"{mode}.yaml"))
    if recipe_config is not None:
        cfg = OmegaConf.merge(cfg, OmegaConf.load(recipe_config))
    cfg.actor_rollout_ref.model.path = student
    cfg.actor_rollout_ref.rollout.multi_turn.format = _required(environment, "TOOL_PARSER")
    if mode != "rl":
        cfg.distillation.teacher_models.teacher_model.model_path = _required(environment, "TEACHER_MODEL_PATH")
    # Explicit environment overrides permit independently prepared train/holdout files.
    cfg.data.train_files = environment.get("TRAIN_FILE") or _required(prepared, "TRAIN_FILE")
    cfg.data.val_files = environment.get("TEST_FILE") or _required(prepared, "TEST_FILE")
    name = experiment_name if experiment_name is not None else cfg.trainer.get("experiment_name", f"harbor-{mode}")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("experiment_name must be a non-empty string")
    cfg.trainer.experiment_name = name
    cfg.trainer.default_local_dir = str(run_root / "checkpoints")
    cfg.trainer.rollout_data_dir = str(run_root / "rollout")
    cfg.trainer.validation_data_dir = str(run_root / "validation")
    framework = OmegaConf.select(cfg, FRAMEWORK)
    framework.log_dir = str(run_root / "agent")
    framework.trajectory_postprocessor_kwargs = launch["postprocessor"]
    concurrency = environment.get("MAX_CONCURRENT_SESSIONS", prepared.get("MAX_CONCURRENT_SESSIONS"))
    if concurrency is not None:
        if not isinstance(concurrency, str) or not concurrency.isdecimal() or not 1 <= int(concurrency) <= 64:
            raise ValueError("MAX_CONCURRENT_SESSIONS must be between one and sixty-four")
        framework.agent_runners.task.max_concurrent_sessions = int(concurrency)
    kwargs = framework.agent_runners.task.runner_kwargs
    kwargs.task_config_path = environment.get("TASK_CONFIG") or _required(prepared, "TASK_CONFIG")
    kwargs.model_name = _required(prepared, "MODEL_ID")
    kwargs.harbor_route_registration = launch["registration"]
    _validate_termination_recipe(mode, cfg, launch["postprocessor"])
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


def _validate_attention_backend(config) -> list[dict[str, str]]:
    """Check dependencies/interfaces; CPU admission does not validate GPU execution."""
    selected = OmegaConf.select(
        config, "actor_rollout_ref.model.override_config.attn_implementation", default="flash_attention_2"
    )
    backends = selected.values() if isinstance(selected, Mapping) else [selected]
    checks = []
    for backend in backends:
        if backend is None or backend == "eager":
            import_module("torch")
            checks.append({"backend": backend or "auto", "validation": "torch_import"})
            continue
        if backend == "sdpa":
            import torch.nn.functional as functional

            if not callable(getattr(functional, "scaled_dot_product_attention", None)):
                raise ValueError("Attention backend sdpa unavailable: PyTorch SDPA operator is missing")
            checks.append({"backend": backend, "validation": "torch_sdpa_operator"})
            continue
        if backend == "flash_attention_2":
            # Transformers 5.8's public availability predicate also requires
            # visible CUDA. Check its dependency minimum and ABI import instead,
            # so a CPU preflight with CUDA_VISIBLE_DEVICES='' is not misclassified.
            try:
                installed = Version(version("flash-attn"))
            except (PackageNotFoundError, InvalidVersion) as error:
                raise ValueError(
                    "Attention backend flash_attention_2 unavailable: flash-attn>=2.3.3 required"
                ) from error
            if installed < Version("2.3.3"):
                raise ValueError("Attention backend flash_attention_2 unavailable: flash-attn>=2.3.3 required")
            try:
                import_module("flash_attn")
            except Exception as error:
                raise ValueError(f"Attention backend flash_attention_2 import failed: {error}") from error
            checks.append({"backend": backend, "validation": "distribution_and_import"})
            continue
        from transformers.modeling_utils import ALL_ATTENTION_FUNCTIONS

        if not isinstance(backend, str) or backend not in ALL_ATTENTION_FUNCTIONS:
            raise ValueError(f"Cannot validate attention backend {backend!r}: no registered interface")
        if not callable(ALL_ATTENTION_FUNCTIONS[backend]):
            raise ValueError(f"Cannot validate attention backend {backend!r}: interface is not callable")
        checks.append({"backend": backend, "validation": "registered_interface_only"})
    return checks


def _validate_checkpoint_backend(config) -> str:
    """Mirror native plugin registration and lookup without constructing a backend."""
    from verl.checkpoint_engine import CheckpointEngineRegistry
    from verl.utils.import_utils import import_external_libs

    selected = OmegaConf.select(config, "actor_rollout_ref.rollout.checkpoint_engine.backend", default="naive")
    plugin = OmegaConf.select(config, "actor_rollout_ref.rollout.checkpoint_engine.custom_backend_module")
    if OmegaConf.is_config(plugin):
        plugin = OmegaConf.to_container(plugin, resolve=True)
    import_external_libs(plugin or None)
    CheckpointEngineRegistry.get(selected)
    return selected


def preflight_training(config) -> dict:
    """Validate dependencies, tokenizer/processor and filtered data before starting Ray."""

    sampling_subset = any(config.data.get(f"{part}_max_samples", -1) > 0 for part in ("train", "val"))
    if sampling_subset and config.data.shuffle and config.data.get("seed") is None:
        raise ValueError("A fixed data.seed is required when preflight randomly selects a dataset subset")
    attention_checks = _validate_attention_backend(config)
    checkpoint_backend = _validate_checkpoint_backend(config)
    from verl.trainer.ppo.utils import create_rl_dataset
    from verl.utils.config import omega_conf_to_dataclass

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
    report = finalize_training_plan(config, train_rows=counts["train"], validation_rows=counts["val"])
    report["backend_validation"] = {
        "attention": attention_checks,
        "checkpoint_backend": checkpoint_backend,
        "gpu_execution_validated": False,
    }
    return report


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


def _training_entrypoint(config, *, observability_wrapper: bool) -> list[str]:
    if not observability_wrapper:
        return ["-m", "verl.trainer.main_ppo"]
    if "rl_insight" not in config.trainer.logger:
        raise ValueError("The observability wrapper requires the rl_insight logger")
    wrapper = ROOT / "docs/verl-uni-agent-harbor-opd-rl/mimo_observability.py"
    if not wrapper.is_file():
        raise ValueError("The fixed observability wrapper is missing from the prepared source")
    return [str(wrapper)]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", required=True, choices=MODES)
    parser.add_argument("--launch", required=True, type=Path, help="Private prepared Harbor launch.json")
    parser.add_argument("--recipe-config", type=Path, help="Optional YAML overlay before prepared task/model bindings")
    parser.add_argument(
        "--experiment-name", help="Explicit run identity; overrides recipe name or harbor-<mode> default"
    )
    parser.add_argument(
        "--observability-wrapper", action="store_true", help="Use the fixed MiMo native monitoring lifecycle wrapper"
    )
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
    overrides = build_overrides(
        args.mode,
        json.loads(args.launch.read_bytes()),
        os.environ,
        recipe_config=args.recipe_config,
        experiment_name=args.experiment_name,
    )
    # Hydra writes logs/metadata before entering the trainer; source may be read-only.
    hydra_run_dir = args.launch.resolve().parent / "hydra"
    overrides.append(f"hydra.run.dir={_hydra(str(hydra_run_dir))}")
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
    entrypoint = _training_entrypoint(config, observability_wrapper=args.observability_wrapper)
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
        [sys.executable, *entrypoint, "--config-name=ppo_trainer", *overrides],
        cwd=ROOT,
        env=environment,
        check=True,
    )


if __name__ == "__main__":
    main()
