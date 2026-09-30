"""Read-only cloud preflight for the exact r19 same-world-two resume command; no GPU allocation."""

import hashlib
import importlib.metadata as metadata
import json
import os
import re
import runpy
import time
from pathlib import Path

from packaging.requirements import Requirement

ROOT = Path("/workspace/mimo-dsh-rl-20260928")


def validate_cohost_evidence(root, expected_sha256):
    """Bind a completed real public HTTP/SSH forwarding proof to this exact source."""
    path = root / "integration-check/r19-cohost-http-probe.json"
    if not isinstance(expected_sha256, str) or re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None:
        raise ValueError("Explicit cohost HTTP proof hash required")
    raw = path.read_bytes()
    if path.is_symlink() or hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("Cohost HTTP proof hash differs")
    proof = json.loads(raw)
    expected = {
        "schema": "mimo.r19-cohost-http-probe.v1",
        "status": "passed",
        "gateway_host": "172.24.0.2",
        "ssh_host": "127.0.0.1",
        "ssh_port": 22,
        "cleaned_up": True,
        "cleanup_ports_free": True,
        "owned_processes_terminated": True,
        "training_started": False,
        "jobs_submitted": 0,
        "ports": {
            "control": 38860,
            "worker": 38861,
            "model": 38862,
            "ingress": 38863,
            "remote_control": 38760,
            "remote_worker": 38761,
        },
    }
    for key, value in expected.items():
        if proof.get(key) != value or (isinstance(value, bool) and proof.get(key) is not value):
            raise ValueError("Cohost HTTP proof differs: " + key)
    required = {
        "public_model_forward",
        "reverse_control_auth",
        "reverse_worker_auth",
        "bad_token_rejected",
        "unknown_session_rejected",
        "disabled_path_rejected",
    }
    if not required <= proof["checks"].keys() or not all(proof["checks"][key] is True for key in required):
        raise ValueError("Cohost forwarding/authentication proof incomplete")
    native = {"deployment/services/harbor_tunnel.py", "deployment/services/harbor_modal_ingress.py"}
    if not native <= proof["source_sha256"].keys():
        raise ValueError("Cohost production source proof incomplete")
    for name, sha in proof["source_sha256"].items():
        relative = Path(name)
        source = root / "run-src-r19" / relative
        if relative.is_absolute() or ".." in relative.parts or source.is_symlink():
            raise ValueError("Unsafe cohost production source path")
        if hashlib.sha256(source.read_bytes()).hexdigest() != sha:
            raise ValueError("Cohost production source changed")
    return {"path": str(path), "sha256": expected_sha256, "status": "passed"}


def validate_training_config(config):
    """Check the exact composed resume topology without initializing CUDA."""
    trainer, rollout = config.trainer, config.actor_rollout_ref.rollout
    checks = {
        "observability deadline": trainer.observability_deadline_unix == 1790752269,
        "private token journal": config.ray_kwargs.ray_init.runtime_env.env_vars.UNI_AGENT_TOKEN_JOURNAL_DIR
        == "/root/mimo-private/launch-r19/token-journal",
        "native loggers": list(trainer.logger) == ["console", "wandb", "rl_insight"],
        "experiment": trainer.experiment_name == "mimo9b-001661-r19",
        "project": trainer.project_name == "xDAN-Verl-Uni-agent-Harbor-rl-opd",
        "mode": trainer.v1.trainer_mode == "colocate_async",
        "actor world two": trainer.nnodes == 1 and trainer.n_gpus_per_node == 2,
        "shared rollout pool": rollout.nnodes == 0 and rollout.n_gpus_per_node == 2,
        "two TP1 replicas": rollout.tensor_model_parallel_size == 1
        and rollout.data_parallel_size == 1
        and rollout.pipeline_model_parallel_size == 1,
        "naive IPC": rollout.checkpoint_engine.backend == "naive",
        "original MiMo SFT": config.actor_rollout_ref.model.path == "/workspace/models/MiMo-V2.6-Distill-Qwen-9B",
        "same-world-two resume": trainer.resume_mode == "resume_path"
        and trainer.resume_from_path == str(ROOT / "runs/r17/rl-training/checkpoints/global_step_3"),
        "absolute step four": trainer.total_training_steps == 4 and trainer.save_freq == 1,
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
            raise ValueError("Resume dual colocate contract failed: " + name)


def validate_capacity(spec_value, launch, config):
    """Bind actual controller capacity to the prepared run and composed framework."""
    from deployment.services.harbor_run_controller import RunSpec, digest

    spec = RunSpec.model_validate(spec_value)
    cohost = runpy.run_path(str(Path(__file__).with_name("mimo_r19_preparation.py")))["validate_cohost_spec"](
        spec_value
    )
    canonical_sha = digest(spec.model_dump(mode="json"))
    if spec.deadline_unix != config.trainer.observability_deadline_unix:
        raise ValueError("Observability deadline must equal the actual run spec")
    framework = config.actor_rollout_ref.rollout.custom.agent_framework
    if spec.run_id != "mimo9b-001661-r19":
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
    return {"max_concurrent_jobs": 2, "max_concurrent_sessions": 2, "run_spec_sha256": canonical_sha, "cohost": cohost}


def main():
    helper = runpy.run_path(str(ROOT / "audit-code/r19-preparation/mimo_r19_preparation.py"))
    plan = helper["runtime_gate"]()
    cohost_proof = validate_cohost_evidence(ROOT, os.environ.get("MIMO_R19_COHOST_HTTP_PROBE_SHA256"))
    transport = helper["training_environment"](ROOT)
    assert os.environ["PYTHONPATH"] == transport["PYTHONPATH"]
    assert os.environ["LD_LIBRARY_PATH"] == transport["LD_LIBRARY_PATH"]
    assert os.environ.get("PYTHONDONTWRITEBYTECODE") == "1"
    for key, value in helper["observability_environment"]().items():
        assert os.environ.get(key) == value, f"Observability identity differs: {key}"
    source = ROOT / "run-src-r19"
    probe_path = Path("/root/mimo-private/observability-hydra-bootstrap-r19-20260930/status.json")
    probe_raw = probe_path.read_bytes()
    probe_sha = hashlib.sha256(probe_raw).hexdigest()
    assert probe_sha == "a4e778be3300e22430c036badbfc1c9d46441184b1aefaf22649b40402b84795"
    probe = json.loads(probe_raw)
    assert probe["status"] == "passed" and probe["source_mode"] == "0o555"
    assert probe["hydra_metadata_created"] is True and probe["native_ray_not_started"] is True
    assert probe["gpu_training_started"] is False
    assert probe["observed_guard_error"] == probe["expected_error"]
    assert probe["observability_deadline_unix"] == plan["deadline_unix"]
    assert probe["token_journal_dir"] == "/root/mimo-private/launch-r19/token-journal"
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
    launch_path = Path("/root/mimo-private/launch-r19/launch.json")
    launch = json.loads(launch_path.read_bytes())
    hydra_run_dir = launch_path.resolve().parent / "hydra"
    assert hydra_run_dir.is_absolute() and not hydra_run_dir.is_relative_to(source.resolve())
    overrides = build_overrides(
        "rl",
        launch,
        os.environ,
        recipe_config=source / "examples/mimo_dsh_rl/mimo-9b-dual-colocate-observed.yaml",
        experiment_name="mimo9b-001661-r19",
    )
    overrides += [
        "trainer.total_training_steps=4",
        "++trainer.observability_deadline_unix=" + str(plan["deadline_unix"]),
        "++ray_kwargs.ray_init.runtime_env.env_vars.UNI_AGENT_TOKEN_JOURNAL_DIR="
        + json.dumps("/root/mimo-private/launch-r19/token-journal"),
        "trainer.save_freq=1",
        "trainer.resume_mode=resume_path",
        "trainer.resume_from_path=" + json.dumps(plan["training_flags"][-1]),
        "hydra.run.dir=" + json.dumps(str(hydra_run_dir)),
    ]
    config = compose_config(overrides)
    validate_training_config(config)
    capacity = validate_capacity(json.loads(Path("/root/mimo-private/run-spec-r19.json").read_bytes()), launch, config)
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
        "resume_from_path": plan["training_flags"][-1],
        "resume_manifest_sha256": plan["resume_manifest_sha256"],
        "checkpoint_world_size": 2,
        "checkpoint_fsdp_version": 1,
        "deadline_unix": plan["deadline_unix"],
        "token_journal_dir": config.ray_kwargs.ray_init.runtime_env.env_vars.UNI_AGENT_TOKEN_JOURNAL_DIR,
        "resume_mode": "resume_path",
        "total_training_steps": 4,
        "mode": "colocate_async",
        "backend": "naive",
        "actor_world_size": 2,
        "capacity": capacity,
        "cohost_http_proof": cohost_proof,
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
    (ROOT / "integration-check/preflight-r19-result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
