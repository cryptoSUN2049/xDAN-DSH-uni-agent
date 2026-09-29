"""Fresh world-size-two admission rejects accidental rank-one restoration."""

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
    path = Path(__file__).resolve().parents[3] / "docs/verl-uni-agent-harbor-opd-rl/mimo_r17_preflight.py"
    spec = importlib.util.spec_from_file_location("r17_preflight", path)
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
            experiment_name="mimo9b-001661-r17",
        )
    )

    OmegaConf.update(config, "trainer.total_training_steps", 3)
    return config


def test_actual_fresh_composition_passes_without_cuda(config):
    import torch

    assert not torch.cuda.is_initialized()
    module().validate_training_config(config)
    assert not torch.cuda.is_initialized()


@pytest.mark.parametrize(
    "key,value",
    [
        ("trainer.resume_mode", "resume_path"),
        ("trainer.resume_from_path", "/old/global_step_4"),
        ("trainer.total_training_steps", 5),
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
def test_rejects_wrong_fresh_topology_or_identity(config, key, value):
    OmegaConf.update(config, key, value)
    with pytest.raises(ValueError, match="contract failed"):
        module().validate_training_config(config)


@pytest.fixture
def actual_prepared(inputs):
    import json

    from examples.harbor.prepare_m2_training import prepare_training
    from tests.uni_agent.examples import test_mimo_training_entry as fixtures
    from tests.uni_agent.examples.test_mimo_budget_recipe import LIMITS, POLICY

    args = fixtures.mimo_inputs(inputs)
    spec = json.loads(args["run_spec_path"].read_text())
    spec.update(run_id="mimo9b-001661-r17", max_concurrent_jobs=2)
    spec["policy_template"].update(termination_policy=POLICY, budget_limits=dict(LIMITS))
    args["run_spec_path"].write_text(json.dumps(spec))
    prepared = json.loads(prepare_training(**args, max_concurrent_sessions=2).read_text())
    cfg = launch.compose_config(
        launch.build_overrides(
            "rl",
            prepared,
            {**ENV, "STUDENT_MODEL_PATH": "/workspace/models/MiMo-V2.6-Distill-Qwen-9B"},
            recipe_config=ROOT / "examples/mimo_dsh_rl/mimo-9b-dual-colocate-observed.yaml",
            experiment_name="mimo9b-001661-r17",
        )
        + ["trainer.total_training_steps=3"]
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
