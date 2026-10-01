"""Launch a pinned MiMo recipe without changing the shared uv installation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

RECIPE = Path(__file__).resolve().parent / "recipes"
SOURCE_ENTRY_SHA256 = "7558a2f5a8829f0d86b45d7e03f0c1dbdd117836261d7beed45f89c8a4947f78"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_monitoring(path: Path) -> None:
    """Check the composed native config before allocating model workers."""
    from omegaconf import OmegaConf

    config = OmegaConf.load(path)
    # This launcher enables native RL-Insight for every run.
    if OmegaConf.select(config, "actor_rollout_ref.rollout.disable_log_stats") is not False:
        raise ValueError("RL-Insight requires actor_rollout_ref.rollout.disable_log_stats=false")


def command(args: argparse.Namespace) -> list[str]:
    """Use argument vectors: paths never become shell commands."""
    cfg = RECIPE / f"{args.domain}.yaml"
    if not cfg.is_file():
        raise ValueError(f"No implemented recipe for {args.domain}")
    values = {
        "actor_rollout_ref.model.path": str(args.model.resolve()),
        "data.train_files": [str(args.train.resolve())],
        "data.val_files": [str(args.heldout.resolve())],
        "trainer.experiment_name": args.run_id,
        "trainer.total_training_steps": args.steps,
        "trainer.default_local_dir": str(args.run_dir / "checkpoints"),
        "trainer.rollout_data_dir": str(args.run_dir / "rollout"),
        "trainer.validation_data_dir": str(args.run_dir / "validation"),
        "hydra.run.dir": str(args.run_dir / "hydra"),
    }
    if args.resume is not None:
        if not (args.resume / "data.pt").is_file() or not (args.resume / "actor").is_dir():
            raise ValueError("Resume requires a native checkpoint with actor and data.pt")
        values["trainer.resume_mode"] = "resume_path"
        values["trainer.resume_from_path"] = str(args.resume.resolve())
    wrapper = Path(__file__).resolve().parents[2] / "docs/verl-uni-agent-harbor-opd-rl/mimo_observability.py"
    if not wrapper.is_file():
        raise ValueError("Native monitoring lifecycle wrapper is missing")
    cmd = [
        sys.executable,
        str(wrapper),
        "--config-path",
        str(RECIPE),
        "--config-name",
        args.domain,
    ]
    cmd.extend(f"{key}={json.dumps(value)}" for key, value in values.items())
    cmd.append(f"++trainer.observability_deadline_unix={int(time.time()) + args.runtime_seconds}")
    # Never put authentication tokens in the resolved config or command receipt.
    for key in (
        "PATH",
        "LD_LIBRARY_PATH",
        "ABC2MIDI_BIN",
        "RL_INSIGHT_SERVER_URL",
        "VLLM_USE_FLASHINFER_SAMPLER",
        "WANDB_RUN_ID",
        "WANDB_NAME",
        "WANDB_ENTITY",
        "WANDB_PROJECT",
        "WANDB_RESUME",
        "WANDB_DIR",
    ):
        value = os.environ.get(key)
        if value:
            cmd.append(f"++ray_kwargs.ray_init.runtime_env.env_vars.{key}={json.dumps(value)}")
    cmd.extend(args.override)
    return cmd


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", required=True, choices=("music", "code", "cyber", "general", "webdev"))
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--train", type=Path, required=True)
    parser.add_argument("--heldout", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--steps", type=int, default=1)
    parser.add_argument("--resume", type=Path)
    parser.add_argument("--runtime-seconds", type=int, default=7200)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--override", action="append", default=[])
    args = parser.parse_args()
    if args.steps < 1 or not 60 <= args.runtime_seconds <= 25200:
        parser.error("Positive steps and a 60..25200-second process bound required")
    source = args.source.resolve()
    expected = source / "verl/trainer/main_ppo.py"
    if not expected.is_file() or sha256(expected) != SOURCE_ENTRY_SHA256:
        parser.error("Pinned MiMo source is missing")
    for name in ("train", "heldout"):
        if not getattr(args, name).is_file():
            parser.error(f"Missing {name} parquet")
    args.run_dir = args.run_dir.resolve()
    args.run_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    # Explicitly precede the old editable source. Extra overlays are operator inputs.
    env["PYTHONPATH"] = str(source) + os.pathsep + env.get("MIMO_EXTRA_PYTHONPATH", "")
    env.update(
        WANDB_MODE="online",
        WANDB_ENTITY="xdan-ai",
        WANDB_PROJECT="xDAN-Verl-Uni-agent-Harbor-rl-opd",
        WANDB_RUN_ID=args.run_id,
        WANDB_NAME=args.run_id,
        WANDB_RESUME="never",
        WANDB_DIR=str(args.run_dir),
        VERL_RL_INSIGHT_ENABLE="1",
        RAY_ADDRESS="local",
        PYTHONDONTWRITEBYTECODE="1",
    )
    for key in ("WANDB_RUN_ID", "WANDB_NAME", "WANDB_ENTITY", "WANDB_PROJECT", "WANDB_RESUME", "WANDB_DIR"):
        os.environ[key] = env[key]
    cmd = command(args)
    receipt = {
        "schema": "mimo.multidomain-launch.v1",
        "domain": args.domain,
        "run_id": args.run_id,
        "source_entry_sha256": sha256(expected),
        "recipe_sha256": sha256(RECIPE / f"{args.domain}.yaml"),
        "train_sha256": sha256(args.train),
        "heldout_sha256": sha256(args.heldout),
        "runtime_seconds": args.runtime_seconds,
        "started_at": time.time(),
        "command": cmd,
        "state": "preflight",
    }
    receipt_path = args.run_dir / "launch-receipt.json"
    if receipt_path.exists():
        raise FileExistsError("A run identity cannot overwrite an existing receipt")
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
    # Hydra composition imports the actual source in the child, before GPU launch.
    try:
        with (args.run_dir / "resolved-config.yaml").open("w") as output:
            subprocess.run(cmd + ["--cfg", "job", "--resolve"], env=env, stdout=output, check=True, timeout=600)
        validate_monitoring(args.run_dir / "resolved-config.yaml")
    except (subprocess.SubprocessError, ValueError) as error:
        receipt.update(state="preflight_failed", error_type=type(error).__name__, finished_at=time.time())
        receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
        raise
    if args.preflight_only:
        return
    receipt["state"] = "running"
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
    try:
        with subprocess.Popen(cmd, env=env, start_new_session=True) as process:
            try:
                exit_code = process.wait(timeout=args.runtime_seconds)
            except subprocess.TimeoutExpired:
                # Limit only our child session; never kill an unrelated Ray cluster.
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=60)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                raise
        receipt.update(exit_code=exit_code, state="finished" if exit_code == 0 else "failed")
    except subprocess.TimeoutExpired:
        receipt.update(exit_code=124, state="timeout")
        raise
    finally:
        receipt["finished_at"] = time.time()
        receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
    raise SystemExit(receipt["exit_code"])


if __name__ == "__main__":
    main()
