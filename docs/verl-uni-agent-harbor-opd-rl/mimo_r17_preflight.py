"""Read-only cloud preflight for the exact r17 fresh dual-colocate command; no GPU allocation."""

import hashlib
import importlib.metadata as metadata
import json
import os
import runpy
import time
from pathlib import Path

from packaging.requirements import Requirement

ROOT = Path("/workspace/mimo-dsh-rl-20260928")


def validate_training_config(config):
    """Check the exact composed fresh topology without initializing CUDA."""
    trainer, rollout = config.trainer, config.actor_rollout_ref.rollout
    checks = {
        "native loggers": list(trainer.logger) == ["console", "wandb", "rl_insight"],
        "experiment": trainer.experiment_name == "mimo9b-001661-r17",
        "project": trainer.project_name == "xDAN-Verl-Uni-agent-Harbor-rl-opd",
        "mode": trainer.v1.trainer_mode == "colocate_async",
        "actor world two": trainer.nnodes == 1 and trainer.n_gpus_per_node == 2,
        "shared rollout pool": rollout.nnodes == 0 and rollout.n_gpus_per_node == 2,
        "two TP1 replicas": rollout.tensor_model_parallel_size == 1
        and rollout.data_parallel_size == 1
        and rollout.pipeline_model_parallel_size == 1,
        "naive IPC": rollout.checkpoint_engine.backend == "naive",
        "original MiMo SFT": config.actor_rollout_ref.model.path == "/workspace/models/MiMo-V2.6-Distill-Qwen-9B",
        "fresh only": trainer.resume_mode == "disable" and trainer.resume_from_path is None,
        "three steps": trainer.total_training_steps == 3 and trainer.save_freq == 1,
        "n four": rollout.n == 4,
        "two sequences": rollout.max_num_seqs == 2,
        "two sessions": rollout.custom.agent_framework.agent_runners.task.max_concurrent_sessions == 2,
        "one runner": set(rollout.custom.agent_framework.agent_runners) == {"task"},
        "framework adapter": rollout.agent.agent_loop_manager_class
        == "uni_agent.framework.entry.AgentFrameworkRolloutAdapter",
        "one loop worker": rollout.agent.num_workers == 1,
        "one gateway": rollout.custom.agent_framework.gateway_count == 1,
        "one tool": rollout.multi_turn.max_parallel_calls == 1,
        "generation budget": rollout.custom.agent_framework.max_generated_tokens_per_episode == 20480,
        "context budget": rollout.max_model_len == 32768,
        "entropy chunking": config.actor_rollout_ref.actor.fsdp_config.entropy_from_logits_with_chunking is True
        and config.actor_rollout_ref.actor.fsdp_config.entropy_from_logits_chunk_size == 256,
    }
    for name, passed in checks.items():
        if not passed:
            raise ValueError("Fresh dual colocate contract failed: " + name)


def validate_capacity(spec_value, launch, config):
    """Bind actual controller capacity to the prepared run and composed framework."""
    from deployment.services.harbor_run_controller import RunSpec, digest

    spec = RunSpec.model_validate(spec_value)
    canonical_sha = digest(spec.model_dump(mode="json"))
    framework = config.actor_rollout_ref.rollout.custom.agent_framework
    if spec.run_id != "mimo9b-001661-r17":
        raise ValueError("Capacity admission run identity differs")
    if spec.max_concurrent_jobs != 2 or framework.agent_runners.task.max_concurrent_sessions != 2:
        raise ValueError("Controller and framework capacity must both be two")
    post = launch["postprocessor"]
    if post["run_id"] != spec.run_id or post["run_spec_sha256"] != canonical_sha:
        raise ValueError("Capacity admission launch/spec digest differs")
    if launch["environment"]["MAX_CONCURRENT_SESSIONS"] != "2":
        raise ValueError("Prepared sessions must be two")
    if framework.trajectory_postprocessor_kwargs.run_spec_sha256 != canonical_sha:
        raise ValueError("Capacity admission composed spec digest differs")
    return {"max_concurrent_jobs": 2, "max_concurrent_sessions": 2, "run_spec_sha256": canonical_sha}


def main():
    helper = runpy.run_path(str(ROOT / "audit-code/r17-preparation/mimo_r17_preparation.py"))
    plan = helper["runtime_gate"]()
    transport = helper["training_environment"](ROOT)
    assert os.environ["PYTHONPATH"] == transport["PYTHONPATH"]
    assert os.environ["LD_LIBRARY_PATH"] == transport["LD_LIBRARY_PATH"]
    assert os.environ.get("PYTHONDONTWRITEBYTECODE") == "1"
    for key, value in helper["observability_environment"]().items():
        assert os.environ.get(key) == value, f"Observability identity differs: {key}"
    source = ROOT / "run-src-r17"
    probe_path = Path("/root/mimo-private/observability-hydra-bootstrap-20260929/status.json")
    probe_raw = probe_path.read_bytes()
    probe_sha = hashlib.sha256(probe_raw).hexdigest()
    assert probe_sha == "34857367db5137a88b56e6f382d16c332adc944ecabaed84a1615529d9072013"
    probe = json.loads(probe_raw)
    assert probe["status"] == "passed" and probe["source_mode"] == "0o555"
    assert probe["hydra_metadata_created"] is True and probe["native_ray_not_started"] is True
    assert probe["gpu_training_started"] is False
    assert probe["observed_guard_error"] == probe["expected_error"]
    assert (
        hashlib.sha256((source / "docs/verl-uni-agent-harbor-opd-rl/mimo_observability.py").read_bytes()).hexdigest()
        == probe["helper_sha256"]
    )
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
    launch_path = Path("/root/mimo-private/launch-r17/launch.json")
    launch = json.loads(launch_path.read_bytes())
    hydra_run_dir = launch_path.resolve().parent / "hydra"
    assert hydra_run_dir.is_absolute() and not hydra_run_dir.is_relative_to(source.resolve())
    overrides = build_overrides(
        "rl",
        launch,
        os.environ,
        recipe_config=source / "examples/mimo_dsh_rl/mimo-9b-dual-colocate-observed.yaml",
        experiment_name="mimo9b-001661-r17",
    )
    overrides += [
        "trainer.total_training_steps=3",
        "trainer.save_freq=1",
        "trainer.resume_mode=disable",
        "trainer.resume_from_path=null",
        "hydra.run.dir=" + json.dumps(str(hydra_run_dir)),
    ]
    config = compose_config(overrides)
    validate_training_config(config)
    capacity = validate_capacity(json.loads(Path("/root/mimo-private/run-spec-r17.json").read_bytes()), launch, config)
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
        "resume_from_path": None,
        "resume_mode": "disable",
        "total_training_steps": 3,
        "mode": "colocate_async",
        "backend": "naive",
        "actor_world_size": 2,
        "capacity": capacity,
        "rollout_replicas": 2,
        "gpu_transport_scope": "two native IPC lanes; FSDP training remains unverified until actual run",
        "training_started": False,
        "observability_entrypoint": entrypoint,
        "hydra_run_dir": str(hydra_run_dir),
        "hydra_entry_executed": False,
        "hydra_readonly_entry_probe": {
            "path": str(probe_path),
            "sha256": probe_sha,
            "helper_sha256": probe["helper_sha256"],
            "status": "passed",
            "scope": "Actual entry reached deliberate guard after private Hydra metadata creation",
            "training_acceptance": False,
        },
        "observability_environment": helper["observability_environment"](),
    }
    (ROOT / "integration-check/preflight-r17-result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
