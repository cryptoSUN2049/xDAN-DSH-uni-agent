"""Fresh world-size-two admission rejects accidental rank-one restoration."""

import importlib.util
from pathlib import Path

import pytest
from omegaconf import OmegaConf

from examples.harbor_opd_rl import launch
from tests.uni_agent.examples.test_mimo_budget_recipe import ENV, ROOT, prepared_budget_launch

pytestmark = [pytest.mark.cpu, pytest.mark.level0]


def module():
    path = Path(__file__).resolve().parents[3] / "docs/verl-uni-agent-harbor-opd-rl/mimo_r15_preflight.py"
    spec = importlib.util.spec_from_file_location("r15_preflight", path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


@pytest.fixture
def config():
    env = {**ENV, "STUDENT_MODEL_PATH": "/workspace/models/MiMo-V2.6-Distill-Qwen-9B"}
    return launch.compose_config(
        launch.build_overrides(
            "rl",
            prepared_budget_launch(),
            env,
            recipe_config=ROOT / "examples/mimo_dsh_rl/mimo-9b-dual-colocate-observed.yaml",
            experiment_name="mimo9b-001661-r15",
        )
    )


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
        ("actor_rollout_ref.rollout.custom.agent_framework.agent_runners.task.max_concurrent_sessions", 1),
        ("actor_rollout_ref.model.path", "/old/merged-adapter"),
        ("trainer.experiment_name", "mimo9b-001661-r12"),
    ],
)
def test_rejects_wrong_fresh_topology_or_identity(config, key, value):
    OmegaConf.update(config, key, value)
    with pytest.raises(ValueError, match="contract failed"):
        module().validate_training_config(config)
