"""Validated native Harbor MOPD launch and explicit checkpoint continuation."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

DOMAINS = {"swe", "terminal"}
RECIPES = {
    "native-pg": "k1",
    "pg-sequence": "mopd_pg_sequence",
    "top64-reverse": "mopd_top64_reverse",
    "flash-orm": "mopd_flash_orm",
}


def recipe_overlay(recipe, *, orm_alpha=None, is_lower=None, is_upper=None):
    """Explicit research parameters; no unpublished Flash defaults."""
    import math

    from omegaconf import OmegaConf

    if recipe not in RECIPES:
        raise ValueError(f"Unknown MOPD recipe: {recipe}")
    parameters = (orm_alpha, is_lower, is_upper)
    if recipe == "flash-orm":
        if any(value is None for value in parameters):
            raise ValueError("Flash requires explicit orm_alpha, is_lower and is_upper experimental parameters")
        if any(isinstance(v, bool) or not isinstance(v, int | float) or not math.isfinite(v) for v in parameters):
            raise ValueError("Flash parameters must be finite numbers")
        if not (orm_alpha >= 0 and 0 < is_lower <= 1 <= is_upper):
            raise ValueError("Flash requires alpha >= 0 and 0 < IS lower <= 1 <= upper")
    elif any(value is not None for value in parameters):
        raise ValueError("ORM/IS parameters apply only to flash-orm")
    if recipe == "native-pg":
        return OmegaConf.create({})
    overlay = OmegaConf.load(Path(__file__).with_name("recipes") / f"{recipe}.yaml")
    if recipe == "flash-orm":
        loss = overlay.distillation.distillation_loss
        loss.mopd_orm_alpha, loss.mopd_is_lower, loss.mopd_is_upper = parameters
    return overlay


def validate_recipe(config, recipe):
    """Reject execution paths that silently change the MiMo objective."""
    from omegaconf import OmegaConf

    if recipe not in RECIPES:
        raise ValueError(f"Unknown MOPD recipe: {recipe}")
    if recipe == "native-pg":
        return
    expected = {
        "distillation.distillation_loss.loss_mode": RECIPES[recipe],
        "distillation.distillation_loss.use_policy_gradient": False,
        "distillation.distillation_loss.use_task_rewards": recipe == "flash-orm",
        "distillation.distillation_loss.distillation_loss_coef": 1.0,
        "distillation.distillation_loss.loss_max_clamp": None,
        "distillation.distillation_loss.log_prob_min_clamp": None,
        "actor_rollout_ref.actor.loss_agg_mode": "seq-mean-token-mean",
        "actor_rollout_ref.actor.strategy": "fsdp",
        "actor_rollout_ref.actor.ulysses_sequence_parallel_size": 1,
        "actor_rollout_ref.actor.fsdp_config.ulysses_sequence_parallel_size": 1,
        "actor_rollout_ref.actor.fsdp_config.pad_to_length": False,
        "actor_rollout_ref.model.use_fused_kernels": False,
        "actor_rollout_ref.actor.ppo_epochs": 1,
        "actor_rollout_ref.actor.use_kl_loss": False,
        "actor_rollout_ref.actor.entropy_coeff": 0.0,
        "actor_rollout_ref.rollout.n": 4 if recipe == "flash-orm" else 1,
        "actor_rollout_ref.rollout.temperature": 1.0,
        "actor_rollout_ref.rollout.top_p": 1.0,
        "actor_rollout_ref.rollout.top_k": -1,
        "actor_rollout_ref.rollout.calculate_log_probs": True,
        "actor_rollout_ref.rollout.custom.agent_framework.require_single_policy_version": True,
        "algorithm.rollout_correction.rollout_is": None,
        "algorithm.rollout_correction.rollout_rs": None,
        "algorithm.rollout_correction.bypass_mode": False,
        "algorithm.use_kl_in_reward": False,
        "algorithm.adv_estimator": "grpo",
        "trainer.v1.trainer_mode": "sync",
    }
    if recipe == "top64-reverse":
        expected["distillation.distillation_loss.topk"] = 64
    for key, value in expected.items():
        if OmegaConf.select(config, key) != value:
            raise ValueError(f"{recipe} requires {key}={value!r}")
    if config.actor_rollout_ref.actor.ppo_mini_batch_size != config.data.train_batch_size:
        raise ValueError("MiMo smoke requires one full optimizer minibatch per rollout batch")
    if recipe == "flash-orm":
        loss = config.distillation.distillation_loss
        recipe_overlay(recipe, orm_alpha=loss.mopd_orm_alpha, is_lower=loss.mopd_is_lower, is_upper=loss.mopd_is_upper)


def file_sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def model_identity(path: Path) -> dict:
    """Hash a local HF export; existence is not a successful inference-load test."""
    if not path.is_absolute() or not path.is_dir():
        raise ValueError("model_path must be an absolute local HF directory")
    required = ("config.json", "tokenizer.json")
    weights = sorted(path.glob("*.safetensors"))
    if not weights or any(not (path / name).is_file() for name in required):
        raise ValueError("Expected HF config.json, tokenizer.json and safetensors; export FSDP checkpoints first")
    index = path / "model.safetensors.index.json"
    if index.exists():
        shards = set(json.loads(index.read_text())["weight_map"].values())
        if not shards or any(Path(name).name != name or not (path / name).is_file() for name in shards):
            raise ValueError("HF weight index references a missing or invalid shard")
    # Transformers may store rendering templates separately from tokenizer JSON.
    files = {
        str(file.relative_to(path)): file_sha256(file)
        for file in sorted([*path.glob("*.json"), *path.rglob("*.jinja"), *weights])
    }
    return {"sha256": digest(files), "files": files, "tokenizer_sha256": files["tokenizer.json"]}


def validate_registry(registry: dict) -> dict:
    if registry.get("schema") != "harbor-mopd-registry-v1":
        raise ValueError("Expected harbor-mopd-registry-v1 registry")
    if set(registry.get("teachers", {})) != DOMAINS:
        raise ValueError("First recipe requires exactly swe and terminal teachers")
    identities = {}
    for name, spec in {"student": registry["student"], **registry["teachers"]}.items():
        identity = model_identity(Path(spec["model_path"]))
        if identity["sha256"] != spec["sha256"]:
            raise ValueError(f"{name}: model digest mismatch")
        identities[name] = identity
    tokenizers = {identity["tokenizer_sha256"] for identity in identities.values()}
    if len(tokenizers) != 1:
        raise ValueError(
            "Exact token scoring requires matching tokenizer.json; verify compatibility before changing this"
        )
    return {"student": identities.pop("student"), "teachers": identities}


def checkpoint_receipt(path: Path, *, world_size: int) -> dict:
    match = re.fullmatch(r"global_step_(\d+)", path.name)
    if not match or world_size < 1:
        raise ValueError("Expected global_step_N and positive actor world size")
    required = [path / "data.pt"]
    for rank in range(world_size):
        for kind in ("model", "optim", "extra_state"):
            required.append(path / "actor" / f"{kind}_world_size_{world_size}_rank_{rank}.pt")
    for file in required:
        if not file.is_file() or file.stat().st_size == 0:
            raise ValueError(f"Missing or empty checkpoint component: {file.name}")
    return {"step": int(match[1]), "files": {str(file.relative_to(path)): file_sha256(file) for file in required}}


def verify_resume(state, contract_sha256, checkpoint, *, target_step, max_steps, world_size):
    if state.get("status") != "process_succeeded":
        raise ValueError("Previous update outcome is uncertain; explicit reconciliation required, no automatic replay")
    if state.get("contract_sha256") != contract_sha256:
        raise ValueError("Resume contract changed (models, data, algorithm, source or allocation)")
    receipt = checkpoint_receipt(checkpoint, world_size=world_size)
    if receipt != state.get("checkpoint") or receipt["step"] != state.get("target_step"):
        raise ValueError("Resume checkpoint differs from the recorded completed update")
    if not receipt["step"] < target_step <= max_steps:
        raise ValueError("Resume target step must advance within the authorized step limit")


def validate_allocation(allocation: dict, *, target_step: int) -> None:
    """A recorded allocation is required; this does not grant a new cloud budget."""
    import math

    if allocation.get("schema") != "harbor-mopd-allocation-v1":
        raise ValueError("Expected harbor-mopd-allocation-v1 allocation")
    devices = allocation.get("gpu_uuids", [])
    if (
        not isinstance(devices, list)
        or len(devices) != 3
        or any(not isinstance(d, str) or not re.fullmatch(r"GPU-[A-Za-z0-9-]+", d) for d in devices)
        or len(set(devices)) != 3
    ):
        raise ValueError("First native recipe requires three distinct GPU UUIDs on one host")
    for key in ("owner", "schedule_reference"):
        if not isinstance(allocation.get(key), str) or not allocation[key].strip():
            raise ValueError(f"Allocation requires {key}")
    maximum = allocation.get("max_steps")
    if type(maximum) is not int or type(target_step) is not int or not 1 <= target_step <= maximum:
        raise ValueError("target step must be positive and within allocation.max_steps")
    budget = allocation.get("budget_usd")
    if isinstance(budget, bool) or not isinstance(budget, int | float) or not math.isfinite(budget) or budget <= 0:
        raise ValueError("Allocation requires a finite positive budget_usd; external cost accounting remains required")


def build_overrides(
    launch,
    registry,
    receipt,
    allocation,
    *,
    run_root,
    tool_parser,
    target_step,
    resume=None,
    recipe="native-pg",
    orm_alpha=None,
    is_lower=None,
    is_upper=None,
):
    from omegaconf import OmegaConf

    from examples.harbor_opd_rl.launch import FRAMEWORK, RECIPE, _overrides

    validate_allocation(allocation, target_step=target_step)
    if launch.get("schema") != "dsh.harbor-m2-launch.v1":
        raise ValueError("Expected prepared Harbor launch")
    if not isinstance(tool_parser, str) or not tool_parser.strip():
        raise ValueError("Explicit tool parser is required")
    config = OmegaConf.merge(
        OmegaConf.load(RECIPE / "base.yaml"),
        OmegaConf.load(Path(__file__).with_name("mopd.yaml")),
        recipe_overlay(recipe, orm_alpha=orm_alpha, is_lower=is_lower, is_upper=is_upper),
    )
    values = {
        "trainer.nnodes": 1,
        "trainer.n_gpus_per_node": 1,
        "trainer.experiment_name": run_root.name,
        "trainer.total_training_steps": target_step,
        "trainer.default_local_dir": str(run_root / "checkpoints"),
        "trainer.rollout_data_dir": str(run_root / "rollout"),
        "trainer.validation_data_dir": str(run_root / "validation"),
        "data.train_files": receipt["files"]["train"]["path"],
        "data.val_files": receipt["files"]["validation"]["path"],
        "actor_rollout_ref.model.path": registry["student"]["model_path"],
        "actor_rollout_ref.rollout.multi_turn.format": tool_parser,
        "distillation.nnodes": 1,
        "distillation.n_gpus_per_node": 2,
        f"{FRAMEWORK}.log_dir": str(run_root / "agent"),
        f"{FRAMEWORK}.trajectory_postprocessor_kwargs": launch["postprocessor"],
        f"{FRAMEWORK}.agent_runners.task.runner_kwargs.task_config_path": launch["environment"]["TASK_CONFIG"],
        f"{FRAMEWORK}.agent_runners.task.runner_kwargs.model_name": launch["environment"]["MODEL_ID"],
        f"{FRAMEWORK}.agent_runners.task.runner_kwargs.harbor_route_registration": launch["registration"],
    }
    for domain, spec in registry["teachers"].items():
        values[f"distillation.teacher_models.teacher_{domain}.model_path"] = spec["model_path"]
    if resume is not None:
        values.update({"trainer.resume_mode": "resume_path", "trainer.resume_from_path": str(resume)})
    for key, value in values.items():
        OmegaConf.update(config, key, value, force_add=True)
    validate_recipe(config, recipe)
    # Resolve interpolation only after all required inputs have been supplied.
    result = list(_overrides(OmegaConf.to_container(config, resolve=True)))
    result = [
        "++" + value
        if value.startswith(
            (
                "distillation.teacher_models.teacher_",
                "distillation.distillation_loss.mopd_",
                "distillation.distillation_loss.chunked_topk_chunk_size=",
                "actor_rollout_ref.actor.fsdp_config.pad_to_length=",
            )
        )
        else value
        for value in result
    ]
    # The empty placeholder adds no override; native ppo_trainer supplies it.
    return result


def validate_data(receipt: dict) -> dict:
    import pyarrow.parquet as pq

    from examples.harbor_mopd.prepare import IDENTITY_FIELDS, fingerprint_task, prepare_rows

    if receipt.get("schema") != "harbor-mopd-data-receipt" or receipt.get("schema_version") != 1:
        raise ValueError("Expected versioned MOPD data receipt")
    rows, tasks, fingerprints = {}, [], {}
    for split in ("train", "validation"):
        spec = receipt["files"][split]
        path = Path(spec["path"])
        if not path.is_absolute() or file_sha256(path) != spec["sha256"]:
            raise ValueError(f"{split} parquet digest mismatch")
        rows[split] = pq.read_table(path).to_pylist()
        for row in rows[split]:
            identity = row["mopd_task"]
            entry = {key: identity[key] for key in IDENTITY_FIELDS}
            if identity.get("leakage_group") is not None:
                entry["leakage_group"] = identity["leakage_group"]
            tasks.append(entry)
            metadata = row["extra_info"]["tools_kwargs"]["task"]["metadata"]
            fingerprints[metadata["instance_id"]] = fingerprint_task(metadata["task_path"])
    # Re-run the authoritative join checks, including task changes since preparation.
    _, actual = prepare_rows(
        rows, {"schema_version": 1, "tasks": tasks}, allowed_domains=DOMAINS, task_fingerprints=fingerprints
    )
    for split in rows:
        for key in ("rows", "domain_counts", "instance_ids"):
            if actual["splits"][split][key] != receipt["splits"][split][key]:
                raise ValueError(f"{split} receipt metadata mismatch")
    if set(actual["splits"]["train"]["domain_counts"]) != DOMAINS:
        raise ValueError("Training data must cover both teacher domains")
    if len(rows["train"]) % 2:
        raise ValueError("Two-task smoke batches require an even training row count; no dropped tail")
    if {row["teacher_domain"] for row in rows["train"][:2]} != DOMAINS:
        raise ValueError("First engineering batch must exercise both teacher domains")
    return {"train_rows": len(rows["train"]), "validation_rows": len(rows["validation"])}


def semantic_config(config) -> dict:
    from omegaconf import OmegaConf

    result = OmegaConf.to_container(config, resolve=True)
    for key in ("total_training_steps", "total_epochs", "resume_mode", "resume_from_path"):
        result["trainer"].pop(key, None)
    return result


def source_identity(root: Path) -> str:
    """Bind executable source, including the actual pinned/submodule working files."""
    paths = []
    for directory in ("uni_agent", "verl/verl", "examples/harbor_mopd", "examples/harbor_opd_rl"):
        paths.extend(p for p in (root / directory).rglob("*") if p.suffix in {".py", ".yaml"} and p.is_file())
    paths.extend((root / "patches/verl").glob("*.patch"))
    paths.append(root / "examples/harbor/train_m2_online_rl.py")
    return digest({str(path.relative_to(root)): file_sha256(path) for path in sorted(paths)})


def check_gpu_allocation(allocation: dict) -> None:
    """Read-only physical device check, never kill or replace another operator's job."""
    import subprocess

    inventory = subprocess.check_output(
        ["nvidia-smi", "--query-gpu=uuid,memory.used", "--format=csv,noheader,nounits"], text=True
    )
    actual = {row.split(",")[0].strip(): int(row.split(",")[1]) for row in inventory.splitlines() if row.strip()}
    for device in allocation["gpu_uuids"]:
        if device not in actual or actual[device] >= 2048:
            raise ValueError(f"Allocated GPU absent or occupied: {device}")
    processes = subprocess.check_output(
        ["nvidia-smi", "--query-compute-apps=gpu_uuid,pid", "--format=csv,noheader"], text=True
    )
    if any(row.split(",")[0].strip() in allocation["gpu_uuids"] for row in processes.splitlines()):
        raise ValueError("Allocated GPU has an existing compute process")


def atomic_json(path: Path, value: dict):
    temporary = path.with_suffix(".tmp")
    with temporary.open("w") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
        stream.flush()
        import os

        os.fsync(stream.fileno())
    temporary.replace(path)


def execute_run(command, *, run_root, contract, allocation, target_step, resume, environment):
    """Process success is only a checkpoint receipt, never a capability pass."""
    import fcntl
    import os
    import subprocess
    from contextlib import ExitStack

    run_root.mkdir(parents=True, exist_ok=resume is not None)
    contract_hash = digest(contract)
    with ExitStack() as stack:
        locks = [run_root / "operator.lock"]
        # All invocations of this launcher coordinate on physical UUIDs as well.
        locks.extend(Path("/tmp") / f"harbor-mopd-{device}.lock" for device in allocation["gpu_uuids"])
        handles = []
        for path in locks:
            handle = stack.enter_context(path.open("a+"))
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            handles.append(handle.fileno())
        if resume is not None:
            previous = json.loads((run_root / "state.json").read_text())
            verify_resume(
                previous,
                contract_hash,
                resume,
                target_step=target_step,
                max_steps=allocation["max_steps"],
                world_size=1,
            )
            expected = run_root / "checkpoints" / f"global_step_{previous['target_step']}"
            if resume.resolve() != expected.resolve():
                raise ValueError("Resume checkpoint must belong to this run")
        check_gpu_allocation(allocation)
        if resume is None:
            atomic_json(run_root / "contract.json", contract)
        attempt_dir = run_root / f"attempt-to-step-{target_step}"
        attempt_dir.mkdir(exist_ok=False)
        state = {
            "status": "started",
            "contract_sha256": contract_hash,
            "target_step": target_step,
            "pid": os.getpid(),
            "capability_accepted": False,
            "resources_released_verified": False,
        }
        atomic_json(run_root / "state.json", state)
        try:
            with (attempt_dir / "trainer.log").open("w") as log:
                result = subprocess.run(
                    command, env=environment, stdout=log, stderr=subprocess.STDOUT, pass_fds=tuple(handles), check=False
                )
            state["returncode"] = result.returncode
            if result.returncode != 0:
                raise RuntimeError(f"Native trainer exited {result.returncode}; inspect the private trainer log")
            checkpoint = run_root / "checkpoints" / f"global_step_{target_step}"
            state["checkpoint"] = checkpoint_receipt(checkpoint, world_size=1)
            state["status"] = "process_succeeded"
        except BaseException:
            state["status"] = "failed"
            atomic_json(run_root / "state.json", state)
            atomic_json(attempt_dir / "result.json", state)
            raise
        atomic_json(run_root / "state.json", state)
        atomic_json(attempt_dir / "result.json", state)
        return state


def main(argv=None):
    import argparse
    import os
    import sys
    from importlib.metadata import PackageNotFoundError, version

    from examples.harbor_opd_rl.launch import ROOT, compose_config, preflight_training

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inspect-model", type=Path, help="Hash a local HF export without any GPU calls")
    for name in ("launch", "registry", "data-receipt", "allocation", "run-root", "resume-from-path"):
        parser.add_argument(f"--{name}", type=Path)
    parser.add_argument("--tool-parser")
    parser.add_argument("--recipe", choices=tuple(RECIPES), default="native-pg")
    parser.add_argument("--orm-alpha", type=float)
    parser.add_argument("--is-lower", type=float)
    parser.add_argument("--is-upper", type=float)
    parser.add_argument("--target-step", type=int, default=1)
    parser.add_argument("--execute", action="store_true", help="Run after full preflight; default only validates")
    args = parser.parse_args(argv)
    if args.inspect_model is not None:
        print(json.dumps(model_identity(args.inspect_model.resolve()), indent=2))
        return
    for name in ("launch", "registry", "data_receipt", "allocation", "run_root", "tool_parser"):
        if getattr(args, name) is None:
            parser.error(f"--{name.replace('_', '-')} is required")
    launch, registry, receipt, allocation = (
        json.loads(path.read_text()) for path in (args.launch, args.registry, args.data_receipt, args.allocation)
    )
    validate_allocation(allocation, target_step=args.target_step)
    identities = validate_registry(registry)
    counts = validate_data(receipt)
    if counts["train_rows"] < 2 * allocation["max_steps"]:
        raise ValueError("No-repeat acceptance requires two unique training tasks per authorized step")
    run_root = args.run_root.resolve()
    resume = args.resume_from_path.resolve() if args.resume_from_path is not None else None
    overrides = build_overrides(
        launch,
        registry,
        receipt,
        allocation,
        run_root=run_root,
        tool_parser=args.tool_parser,
        target_step=args.target_step,
        resume=resume,
        recipe=args.recipe,
        orm_alpha=args.orm_alpha,
        is_lower=args.is_lower,
        is_upper=args.is_upper,
    )
    config = compose_config(overrides)
    validate_recipe(config, args.recipe)
    from verl.utils.config import omega_conf_to_dataclass

    omega_conf_to_dataclass(config.distillation)  # validates actual native pool/route semantics
    preflight = preflight_training(config)
    if preflight["train_rows"] != counts["train_rows"] or preflight["validation_rows"] != counts["validation_rows"]:
        raise ValueError("Native dataset filtering changed the frozen prepared task set")
    overrides.append(f"trainer.total_epochs={config.trainer.total_epochs}")
    config = compose_config(overrides)
    dependencies = {}
    for name in ("torch", "ray", "transformers", "tensordict", "vllm"):
        try:
            dependencies[name] = version(name)
        except PackageNotFoundError:
            dependencies[name] = None
    if args.execute and any(value is None for value in dependencies.values()):
        raise ValueError(
            "Execution requires all native training/serving dependencies; inspect CPU preflight separately"
        )
    contract = {
        "schema": "harbor-mopd-run-contract-v1",
        "recipe": args.recipe,
        "config_sha256": digest(semantic_config(config)),
        "registry": registry,
        "local_model_identity": identities,
        "data_receipt_sha256": digest(receipt),
        "allocation": allocation,
        "prepared_launch_sha256": digest(launch),
        "task_config_sha256": file_sha256(Path(launch["environment"]["TASK_CONFIG"])),
        "source_sha256": source_identity(ROOT),
        "dependencies": dependencies,
    }
    if resume is not None:
        verify_resume(
            json.loads((run_root / "state.json").read_text()),
            digest(contract),
            resume,
            target_step=args.target_step,
            max_steps=allocation["max_steps"],
            world_size=1,
        )
    elif run_root.exists():
        raise FileExistsError("Fresh run requires an unused output directory")
    report = {
        "preflight": preflight,
        "contract_sha256": digest(contract),
        "required_gpu_roles": 3,
        "training_started": False,
        "teacher_weight_load_verified": False,
        "budget_enforcement": "external_operator_accounting",
    }
    if not args.execute:
        print(json.dumps(report, indent=2))
        return
    environment = dict(os.environ)
    environment.update(
        CUDA_VISIBLE_DEVICES=",".join(allocation["gpu_uuids"]), KEEP_GPU_PROCESS="1", RAY_ADDRESS="local"
    )
    environment["PYTHONPATH"] = os.pathsep.join([str(ROOT), str(ROOT / "verl")])
    command = [sys.executable, "-m", "verl.trainer.main_ppo", "--config-name=ppo_trainer", *overrides]
    state = execute_run(
        command,
        run_root=run_root,
        contract=contract,
        allocation=allocation,
        target_step=args.target_step,
        resume=resume,
        environment=environment,
    )
    print(json.dumps({"status": state["status"], "target_step": state["target_step"], "capability_accepted": False}))


if __name__ == "__main__":
    main()
