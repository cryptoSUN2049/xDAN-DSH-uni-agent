"""Read-only cloud preflight for the exact r11 resume command; no GPU allocation."""

import hashlib
import importlib.metadata as metadata
import json
import os
import runpy
import time
from pathlib import Path

from packaging.requirements import Requirement

ROOT = Path("/workspace/mimo-dsh-rl-20260928")


def main():
    helper = runpy.run_path(str(ROOT / "audit-code/r11-preparation-v2/mimo_r11_preparation.py"))
    plan = helper["runtime_gate"]()
    transport = helper["training_environment"](ROOT)
    assert os.environ["PYTHONPATH"] == transport["PYTHONPATH"]
    assert os.environ["LD_LIBRARY_PATH"] == transport["LD_LIBRARY_PATH"]
    assert os.environ.get("PYTHONDONTWRITEBYTECODE") == "1"
    for key, value in helper["observability_environment"]().items():
        assert os.environ.get(key) == value, f"Observability identity differs: {key}"
    source = ROOT / "run-src-r11"
    freeze = Path(
        "/workspace/verl-uni-agent-harbor-opd-rl/src/uni-agent/deployment/versions/uv-lanes/"
        "ua-verl-py312-vllm023.freeze.txt"
    )
    assert hashlib.sha256(freeze.read_bytes()).hexdigest() == (
        "e9f87349997a81b7fbc31ef1ce74f9abb078c37600282d4684c63c75514c4dc7"
    )
    count = 0
    for line in freeze.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "-")) or " @ " in line:
            continue
        requirement = Requirement(line)
        assert metadata.version(requirement.name) in requirement.specifier
        count += 1
    assert count == 273
    import torch

    from examples.harbor_opd_rl.launch import (
        _training_entrypoint,
        _validate_resume,
        build_overrides,
        compose_config,
        preflight_training,
    )

    assert not torch.cuda.is_initialized()
    launch = json.loads(Path("/root/mimo-private/launch-r11/launch.json").read_bytes())
    checkpoint = plan["training_flags"][-1]
    overrides = build_overrides(
        "rl",
        launch,
        os.environ,
        recipe_config=source / "examples/mimo_dsh_rl/mimo-9b-observed.yaml",
        experiment_name="mimo9b-001661-r11",
    )
    overrides += [
        "trainer.total_training_steps=4",
        "trainer.save_freq=1",
        "trainer.resume_mode=resume_path",
        "trainer.resume_from_path=" + json.dumps(checkpoint),
    ]
    config = compose_config(overrides)
    assert list(config.trainer.logger) == ["console", "wandb", "rl_insight"]
    assert config.trainer.experiment_name == "mimo9b-001661-r11"
    assert config.trainer.project_name == "xDAN-Verl-Uni-agent-Harbor-rl-opd"
    assert config.trainer.v1.trainer_mode == "separate_async"
    assert config.trainer.v1.separate_async.parameter_sync_step == 1
    assert config.trainer.n_gpus_per_node == config.trainer.nnodes == 1
    assert config.actor_rollout_ref.rollout.n_gpus_per_node == config.actor_rollout_ref.rollout.nnodes == 1
    assert config.actor_rollout_ref.rollout.tensor_model_parallel_size == 1
    assert config.actor_rollout_ref.rollout.checkpoint_engine.backend == "nccl"
    assert config.actor_rollout_ref.rollout.custom.agent_framework.max_generated_tokens_per_episode == 20480
    assert config.actor_rollout_ref.rollout.max_model_len == 32768
    assert config.actor_rollout_ref.actor.fsdp_config.entropy_from_logits_with_chunking is True
    assert config.actor_rollout_ref.actor.fsdp_config.entropy_from_logits_chunk_size == 256
    assert config.trainer.total_training_steps == 4 and config.trainer.save_freq == 1
    assert config.trainer.resume_from_path == checkpoint
    entrypoint = _training_entrypoint(config, observability_wrapper=True)
    _validate_resume(config)
    report = preflight_training(config)
    assert not torch.cuda.is_initialized()
    result = {
        "status": "passed",
        "source_commit": plan["source_commit"],
        "package_constraints_verified": count,
        "report": report,
        "cuda_initialized": False,
        "finished_at": time.time(),
        "resume_from_path": checkpoint,
        "total_training_steps": 4,
        "mode": "separate_async",
        "backend": "nccl",
        "training_started": False,
        "observability_entrypoint": entrypoint,
        "observability_environment": helper["observability_environment"](),
    }
    (ROOT / "integration-check/preflight-r11-result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
