import json

import pytest
import yaml

from examples.harbor.prepare_m2_training import prepare_training
from tests.uni_agent.examples import test_harbor_m2_training_entry as fixtures

pytestmark = [pytest.mark.cpu, pytest.mark.level0]
inputs = fixtures.inputs


def test_operator_policy_is_bound_in_task_and_postprocessor(inputs):
    spec = json.loads(inputs["run_spec_path"].read_bytes())
    spec["policy_template"]["termination_policy"] = "budget-terminal-v1"
    spec["policy_template"]["budget_limits"] = {"max_generated_tokens": 14336, "trajectory_capacity": 32768}
    inputs["run_spec_path"].write_text(json.dumps(spec))
    launch = json.loads(prepare_training(**inputs).read_bytes())
    task = yaml.safe_load(inputs["task_config_path"].read_bytes())
    assert task["policy"]["termination_policy"] == "budget-terminal-v1"
    assert launch["postprocessor"]["termination_policy"] == "budget-terminal-v1"
    assert launch["postprocessor"]["budget_limits"] == spec["policy_template"]["budget_limits"]


def test_default_prepared_contract_still_omits_policy(inputs):
    launch = json.loads(prepare_training(**inputs).read_bytes())
    task = yaml.safe_load(inputs["task_config_path"].read_bytes())
    assert "termination_policy" not in task["policy"]
    assert "termination_policy" not in launch["postprocessor"]
