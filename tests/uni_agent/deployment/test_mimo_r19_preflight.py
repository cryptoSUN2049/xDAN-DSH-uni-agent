"""Same-world-two independent resume admission."""

import importlib.util
from pathlib import Path

import pytest
from omegaconf import OmegaConf

from examples.harbor_opd_rl import launch
from tests.uni_agent.examples import test_mimo_training_entry as training_fixtures
from tests.uni_agent.examples.test_mimo_budget_recipe import ENV, ROOT, prepared_budget_launch

pytestmark = [pytest.mark.cpu, pytest.mark.level0]
inputs = training_fixtures.inputs


def module():
    path = Path(__file__).resolve().parents[3] / "docs/verl-uni-agent-harbor-opd-rl/mimo_r19_preflight.py"
    spec = importlib.util.spec_from_file_location("r19_preflight", path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


@pytest.fixture
def config():
    env = {**ENV, "STUDENT_MODEL_PATH": "/workspace/models/MiMo-V2.6-Distill-Qwen-9B"}
    config = launch.compose_config(
        launch.build_overrides(
            "rl",
            prepared_budget_launch(),
            env,
            recipe_config=ROOT / "examples/mimo_dsh_rl/mimo-9b-dual-colocate-observed.yaml",
            experiment_name="mimo9b-001661-r19",
        )
    )

    OmegaConf.update(
        config,
        "ray_kwargs.ray_init.runtime_env.env_vars.UNI_AGENT_TOKEN_JOURNAL_DIR",
        "/root/mimo-private/launch-r19/token-journal",
        force_add=True,
    )
    OmegaConf.update(config, "trainer.observability_deadline_unix", 1790752269, force_add=True)
    OmegaConf.update(config, "trainer.total_training_steps", 4)
    OmegaConf.update(config, "trainer.resume_mode", "resume_path")
    OmegaConf.update(
        config,
        "trainer.resume_from_path",
        "/workspace/mimo-dsh-rl-20260928/runs/r17/rl-training/checkpoints/global_step_3",
    )
    return config


def test_actual_resume_composition_passes_without_cuda(config):
    import torch

    assert not torch.cuda.is_initialized()
    module().validate_training_config(config)
    assert not torch.cuda.is_initialized()


@pytest.mark.parametrize(
    "key,value",
    [
        ("trainer.resume_mode", "disable"),
        ("trainer.resume_from_path", "/old/global_step_4"),
        ("trainer.total_training_steps", 5),
        ("trainer.observability_deadline_unix", 1790709401),
        ("ray_kwargs.ray_init.runtime_env.env_vars.UNI_AGENT_TOKEN_JOURNAL_DIR", "/tmp/old-journal"),
        ("trainer.n_gpus_per_node", 1),
        ("trainer.v1.trainer_mode", "separate_async"),
        ("actor_rollout_ref.rollout.nnodes", 1),
        ("actor_rollout_ref.rollout.n_gpus_per_node", 1),
        ("actor_rollout_ref.rollout.tensor_model_parallel_size", 2),
        ("actor_rollout_ref.rollout.checkpoint_engine.backend", "nccl"),
        ("actor_rollout_ref.rollout.max_num_seqs", 1),
        ("actor_rollout_ref.rollout.agent.num_workers", 2),
        ("actor_rollout_ref.rollout.custom.agent_framework.gateway_count", 2),
        ("actor_rollout_ref.rollout.agent.agent_loop_manager_class", "other.Adapter"),
        ("actor_rollout_ref.rollout.custom.agent_framework.agent_runners.task.max_concurrent_sessions", 1),
        ("actor_rollout_ref.model.path", "/old/merged-adapter"),
        ("trainer.experiment_name", "mimo9b-001661-r12"),
    ],
)
def test_rejects_wrong_resume_topology_or_identity(config, key, value):
    OmegaConf.update(config, key, value)
    with pytest.raises(ValueError, match="contract failed"):
        module().validate_training_config(config)


@pytest.fixture
def actual_prepared(inputs):
    import json

    from examples.harbor.prepare_m2_training import prepare_training, task_digest
    from tests.uni_agent.examples import test_mimo_training_entry as fixtures
    from tests.uni_agent.examples.test_mimo_budget_recipe import LIMITS, POLICY

    args = fixtures.mimo_inputs(inputs)
    task_path = args["task_dir"] / "task.toml"
    task_path.write_text(
        task_path.read_text()
        .replace("[environment]\n", '[environment]\nnetwork_mode="allowlist"\nallowed_hosts=["mimo9b-rl.xdan.work"]\n')
        .replace("[verifier.environment]\n", '[verifier.environment]\nnetwork_mode="no-network"\n')
    )
    spec = json.loads(args["run_spec_path"].read_text())
    spec["policy_template"]["task_refs"][0]["sha256"] = task_digest(args["task_dir"])
    spec.update(run_id="mimo9b-001661-r19", max_concurrent_jobs=2, deadline_unix=1790752269)
    spec.update(
        ssh_host="127.0.0.1",
        ssh_port=22,
        ssh_user="root",
        ssh_key="/root/mimo-private/cohost-r19/loopback-key",
        known_hosts="/root/mimo-private/cohost-r19/known_hosts",
        control_port=38860,
        worker_port=38861,
        model_port=38862,
        remote_control_port=38760,
        remote_worker_port=38761,
    )
    spec["modal_ingress"] = {
        "listen_port": 38863,
        "origin": "https://mimo9b-rl.xdan.work",
        "tunnel_id": "04729718-0000-4000-8000-000000000000",
        "credentials_file": "/root/mimo-private/cloudflared.json",
    }
    spec["policy_template"].update(termination_policy=POLICY, budget_limits=dict(LIMITS), gateway_host="172.24.0.2")
    args["run_spec_path"].write_text(json.dumps(spec))
    prepared = json.loads(prepare_training(**args, max_concurrent_sessions=2).read_text())
    cfg = launch.compose_config(
        launch.build_overrides(
            "rl",
            prepared,
            {**ENV, "STUDENT_MODEL_PATH": "/workspace/models/MiMo-V2.6-Distill-Qwen-9B"},
            recipe_config=ROOT / "examples/mimo_dsh_rl/mimo-9b-dual-colocate-observed.yaml",
            experiment_name="mimo9b-001661-r19",
        )
        + [
            "trainer.total_training_steps=4",
            "++trainer.observability_deadline_unix=1790752269",
            "++ray_kwargs.ray_init.runtime_env.env_vars.UNI_AGENT_TOKEN_JOURNAL_DIR=/root/mimo-private/launch-r19/token-journal",
            "trainer.resume_mode=resume_path",
            "trainer.resume_from_path=/workspace/mimo-dsh-rl-20260928/runs/r17/rl-training/checkpoints/global_step_3",
        ]
    )
    return spec, prepared, cfg


def test_real_prepare_spec_and_framework_capacity_agree(actual_prepared):
    spec, prepared, config = actual_prepared
    module().validate_training_config(config)
    report = module().validate_capacity(spec, prepared, config)
    assert report["max_concurrent_jobs"] == report["max_concurrent_sessions"] == 2
    assert report["run_spec_sha256"] == prepared["registration"]["run_spec_sha256"]


@pytest.mark.parametrize(
    "fault", ["default", "wrong-run", "digest", "composed", "prepared", "framework", "bool", "too-many"]
)
def test_real_capacity_rejects_unbound_or_serial_path(actual_prepared, fault):
    spec, prepared, config = actual_prepared
    if fault == "default":
        spec.pop("max_concurrent_jobs")
    elif fault == "wrong-run":
        spec["run_id"] = "old-run"
    elif fault == "digest":
        prepared["postprocessor"]["run_spec_sha256"] = "sha256:" + "0" * 64
    elif fault == "composed":
        config.actor_rollout_ref.rollout.custom.agent_framework.trajectory_postprocessor_kwargs.run_spec_sha256 = (
            "sha256:" + "0" * 64
        )
    elif fault == "prepared":
        prepared["environment"]["MAX_CONCURRENT_SESSIONS"] = "1"
    elif fault == "framework":
        config.actor_rollout_ref.rollout.custom.agent_framework.agent_runners.task.max_concurrent_sessions = 1
    elif fault == "bool":
        spec["max_concurrent_jobs"] = True
    else:
        spec["max_concurrent_jobs"] = 3
    with pytest.raises(ValueError):
        module().validate_capacity(spec, prepared, config)


@pytest.fixture
def cohost_evidence(tmp_path):
    import hashlib
    import json

    sources = {}
    for name in ("deployment/services/harbor_tunnel.py", "deployment/services/harbor_modal_ingress.py"):
        path = tmp_path / "run-src-r19" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"reviewed cohost source")
        sources[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    proof = dict(
        schema="mimo.r19-cohost-http-probe.v1",
        status="passed",
        gateway_host="172.24.0.2",
        ssh_host="127.0.0.1",
        ssh_port=22,
        cleaned_up=True,
        cleanup_ports_free=True,
        owned_processes_terminated=True,
        training_started=False,
        jobs_submitted=0,
        ports=dict(control=38860, worker=38861, model=38862, ingress=38863, remote_control=38760, remote_worker=38761),
        checks={
            key: True
            for key in (
                "public_model_forward",
                "reverse_control_auth",
                "reverse_worker_auth",
                "bad_token_rejected",
                "unknown_session_rejected",
                "disabled_path_rejected",
            )
        },
        source_sha256=sources,
    )
    path = tmp_path / "integration-check/r19-cohost-http-probe.json"
    path.parent.mkdir()
    path.write_text(json.dumps(proof))
    return tmp_path, path, proof


def test_real_cohost_proof_hash_and_production_sources_are_bound(cohost_evidence):
    import hashlib

    root, path, _ = cohost_evidence
    assert module().validate_cohost_evidence(root, hashlib.sha256(path.read_bytes()).hexdigest())["status"] == "passed"


@pytest.mark.parametrize(
    "attack",
    [
        "missing-sha",
        "fake-sha",
        "pending",
        "dirty",
        "training",
        "ports",
        "gateway",
        "auth",
        "missing-check",
        "source-hash",
        "missing-source",
        "traversal",
        "symlink",
    ],
)
def test_cohost_proof_rejects_unverified_or_changed_paths(cohost_evidence, attack):
    import hashlib
    import json

    root, path, proof = cohost_evidence
    if attack == "pending":
        proof["status"] = "pending"
    elif attack == "dirty":
        proof["cleaned_up"] = False
    elif attack == "training":
        proof["training_started"] = True
    elif attack == "ports":
        proof["ports"]["remote_control"] = 38860
    elif attack == "gateway":
        proof["gateway_host"] = "127.0.0.1"
    elif attack == "auth":
        proof["checks"]["bad_token_rejected"] = False
    elif attack == "missing-check":
        del proof["checks"]["public_model_forward"]
    elif attack == "source-hash":
        proof["source_sha256"]["deployment/services/harbor_tunnel.py"] = "0" * 64
    elif attack == "missing-source":
        del proof["source_sha256"]["deployment/services/harbor_tunnel.py"]
    elif attack == "traversal":
        proof["source_sha256"]["../escape"] = "0" * 64
    path.write_text(json.dumps(proof))
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    if attack == "missing-sha":
        sha = None
    elif attack == "fake-sha":
        sha = "0" * 64
    elif attack == "symlink":
        target = path.with_suffix(".target")
        path.rename(target)
        path.symlink_to(target)
    with pytest.raises(ValueError):
        module().validate_cohost_evidence(root, sha)
