"""Exercise real private MiMo preparation before native recipe composition."""

import importlib.util
import json

import pytest

from examples.harbor.prepare_m2_training import prepare_training
from examples.harbor_opd_rl import launch
from tests.uni_agent.examples import test_mimo_training_entry as training_fixtures
from tests.uni_agent.examples.test_mimo_budget_recipe import LIMITS, POLICY, ROOT

pytestmark = [pytest.mark.cpu, pytest.mark.level0]
inputs = training_fixtures.inputs
RECIPE = ROOT / "examples/mimo_dsh_rl/mimo-9b-dual-colocate-observed.yaml"


def preflight():
    path = ROOT / "docs/verl-uni-agent-harbor-opd-rl/mimo_r14_preflight.py"
    spec = importlib.util.spec_from_file_location("r14_real_prepare_preflight", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("requested,expected", [(None, 1), (1, 1), (2, 2)])
def test_real_prepared_concurrency_reaches_native_dual_admission(inputs, requested, expected):
    args = training_fixtures.mimo_inputs(inputs)
    spec = json.loads(args["run_spec_path"].read_text())
    spec["policy_template"].update(termination_policy=POLICY, budget_limits=dict(LIMITS))
    args["run_spec_path"].write_text(json.dumps(spec))
    kwargs = {} if requested is None else {"max_concurrent_sessions": requested}
    # Generate the real private task YAML, parquet, registration and launch.json.
    prepared = json.loads(prepare_training(**args, **kwargs).read_text())
    assert prepared["environment"]["MAX_CONCURRENT_SESSIONS"] == str(expected)
    cfg = launch.compose_config(
        launch.build_overrides(
            "rl",
            prepared,
            {
                "STUDENT_MODEL_PATH": "/workspace/models/MiMo-V2.6-Distill-Qwen-9B",
                "TOOL_PARSER": "qwen3_coder",
            },
            recipe_config=RECIPE,
            experiment_name="mimo9b-001661-r14",
        )
    )
    framework = cfg.actor_rollout_ref.rollout.custom.agent_framework
    assert framework.agent_runners.task.max_concurrent_sessions == expected
    assert framework.trajectory_postprocessor_kwargs == prepared["postprocessor"]
    if expected == 2:
        preflight().validate_training_config(cfg)
    else:
        # Prepared concurrency has precedence over recipe=2; admission must expose it.
        with pytest.raises(ValueError, match="two sessions"):
            preflight().validate_training_config(cfg)
