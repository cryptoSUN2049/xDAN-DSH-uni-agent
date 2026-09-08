"""Thin Harbor overrides on the existing Qwen3-4B online RL training recipe."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

PREFIX = "actor_rollout_ref.rollout.custom.agent_framework"
# Carry the single-GPU M1 settings explicitly: layered summon can fall back to
# offload_to_cpu=True, which FSDP1 NO_SHARD rejects before sampling.
SINGLE_GPU_DEFAULTS = {
    "LOW_VRAM": "1",
    "ROLLOUT_LAYERED_SUMMON": "False",
    "ROLLOUT_ENFORCE_EAGER": "True",
    "ROLLOUT_FREE_CACHE_ENGINE": "True",
    "ROLLOUT_CPU_OFFLOAD_GB": "0",
    "ACTOR_PARAM_OFFLOAD": "True",
    "ACTOR_OPTIMIZER_OFFLOAD": "True",
    "LORA_RANK": "16",
    "LORA_ALPHA": "16",
    "SAVE_LORA_ONLY": "False",
    "MAX_RESPONSE_LENGTH": "1024",
}


def _hydra(value):
    if isinstance(value, dict):
        # Source digest maps use relative paths as literal Hydra dictionary keys.
        # Keep delimiters, quoting, escapes, whitespace and interpolation excluded.
        if any(not isinstance(key, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_./-]*", key) for key in value):
            raise ValueError("Unexpected Hydra configuration key")
        return "{" + ",".join(key + ":" + _hydra(item) for key, item in value.items()) + "}"
    if isinstance(value, list):
        return "[" + ",".join(_hydra(item) for item in value) + "]"
    if isinstance(value, str):
        # Hydra quoted values preserve literal newlines, not JSON \n escapes.
        # Only backslashes adjacent to a quote/closing quote need doubling.
        escaped = re.sub(r'(\\*)"', lambda match: match.group(1) * 2 + '\\"', value)
        escaped = re.sub(r"\\+$", lambda match: match.group() * 2, escaped)
        return '"' + escaped + '"'
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def build_overrides(launch: dict) -> list[str]:
    if launch.get("schema") != "dsh.harbor-m2-launch.v1":
        raise ValueError("Unknown prepared launch schema")
    return [
        # Harbor stores its own receipt/artifacts; legacy DSH-only roots are invalid.
        "++" + PREFIX + ".agent_runners.task.runner_kwargs.dsh_trace_root=null",
        "++" + PREFIX + ".agent_runners.task.runner_kwargs.dsh_result_root=null",
        "++"
        + PREFIX
        + ".agent_runners.task.runner_kwargs.task_config_path="
        + _hydra(launch["environment"]["TASK_CONFIG"]),
        "++" + PREFIX + ".agent_runners.task.runner_kwargs.harbor_route_registration=" + _hydra(launch["registration"]),
        "++"
        + PREFIX
        + ".trajectory_postprocessor_fqn=uni_agent.tasks.harbor_dsh.registration.validate_registered_trajectories",
        "~" + PREFIX + ".trajectory_postprocessor_kwargs",
        "++" + PREFIX + ".trajectory_postprocessor_kwargs=" + _hydra(launch["postprocessor"]),
        "++" + PREFIX + ".trajectory_postprocessor_pass_context=True",
        "++" + PREFIX + ".gateway_count=1",
        "++" + PREFIX + ".agent_runners.task.max_concurrent_sessions=1",
    ]


def adapter_identity(path: Path) -> dict:
    """Bind weights and PEFT configuration together; this is not a weights-only hash."""
    if not path.is_absolute() or ".." in path.parts or path.is_symlink() or not path.is_dir():
        raise ValueError("LoRA adapter must be an absolute real directory")
    hashes = {}
    for name in ("adapter_config.json", "adapter_model.safetensors"):
        file = path / name
        if file.is_symlink() or not file.is_file():
            raise ValueError("LoRA adapter requires regular config and safetensors files")
        with file.open("rb") as stream:
            hashes[name] = hashlib.file_digest(stream, "sha256").hexdigest()
    config = json.loads((path / "adapter_config.json").read_bytes())
    if not isinstance(config, dict) or not config:
        raise ValueError("LoRA adapter configuration must be a nonempty JSON object")
    bundle = "sha256:" + hashlib.sha256(json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"bundle_sha256": bundle, "files": hashes}


def adapter_digest(path: Path) -> str:
    return adapter_identity(path)["bundle_sha256"]


def adapter_overrides(path: Path | None, expected_sha256: str | None, environment: dict) -> list[str]:
    if path is None and expected_sha256 is None:
        return []
    if path is None or expected_sha256 is None:
        raise ValueError("LoRA adapter path and hash must be supplied together")
    if environment.get("RESUME_MODE") != "disable" or environment.get("RESUME_FROM_PATH"):
        raise ValueError("SFT warmstart requires explicit RESUME_MODE=disable and no RESUME_FROM_PATH")
    if adapter_digest(path) != expected_sha256:
        raise ValueError("LoRA adapter artifact hash mismatch")
    return ["actor_rollout_ref.model.lora_adapter_path=" + _hydra(str(path))]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--launch", type=Path, required=True)
    parser.add_argument("--print-command", action="store_true")
    parser.add_argument("--lora-adapter-path", type=Path)
    parser.add_argument(
        "--lora-adapter-bundle-sha256",
        help="SHA256 of compact sorted JSON mapping both adapter filenames to file SHA256s",
    )
    args = parser.parse_args()
    launch = json.loads(args.launch.read_bytes())
    overrides = build_overrides(launch)
    environment = {**SINGLE_GPU_DEFAULTS, **os.environ, **launch["environment"]}
    overrides.extend(adapter_overrides(args.lora_adapter_path, args.lora_adapter_bundle_sha256, environment))
    if args.lora_adapter_path is not None:
        identity = adapter_identity(args.lora_adapter_path)
        if identity["bundle_sha256"] != args.lora_adapter_bundle_sha256:
            raise ValueError("LoRA adapter changed before launch")
        print(
            json.dumps(
                {"schema": "dsh.harbor-sft-warmstart.v1", "adapter_path": str(args.lora_adapter_path), **identity},
                sort_keys=True,
            ),
            file=sys.stderr,
        )
    base = Path(__file__).resolve().parents[1] / "dsh" / "train_qwen3_4b_online_rl.sh"
    if args.print_command or os.environ.get("PRINT_COMMAND") == "1":
        # The base print branch omits "$@". Preserve its command and append the
        # exact same overrides used below for real execution.
        output = subprocess.run(
            ["bash", str(base)],
            env={**environment, "PRINT_COMMAND": "1"},
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
        print(output.stdout.rstrip() + " " + shlex.join(overrides))
        return
    os.execvpe("bash", ["bash", str(base), *overrides], environment)


if __name__ == "__main__":
    main()
