import json

import pyarrow.parquet as pq
import pytest
import yaml
from hydra.core.override_parser.overrides_parser import OverridesParser

from examples.harbor.prepare_m2_training import prepare_training, task_digest
from examples.harbor.train_m2_online_rl import build_overrides
from examples.harbor_opd_rl.launch import build_overrides as native_overrides
from tests.uni_agent.examples import test_harbor_m2_training_entry as training_fixtures
from tests.uni_agent.tasks.test_mimo_binding import binding_value
from uni_agent.tasks.harbor_dsh.mimo import digest

pytestmark = [pytest.mark.cpu, pytest.mark.level0]
inputs = training_fixtures.inputs


def mimo_inputs(inputs):
    task_dir = inputs["task_dir"]
    binding = binding_value()
    path = task_dir / "mimo-binding.json"
    path.write_text(json.dumps(binding))
    (task_dir / "task.toml").write_text(
        '[environment]\ndocker_image="' + binding["image_binding"]["dsh_image"] + '"\n'
        '[verifier]\nenvironment_mode="separate"\n[verifier.environment]\ndocker_image="'
        + binding["image_binding"]["original_image"]
        + '"\n'
    )
    spec = json.loads(inputs["run_spec_path"].read_bytes())
    spec["policy_template"]["task_refs"][0].update(id="mimo-code-code-1", sha256=task_digest(task_dir))
    spec["policy_template"]["dsh_release"]["image_digest"] = "sha256:" + "b" * 64
    inputs["run_spec_path"].write_text(json.dumps(spec))
    return {**inputs, "mimo_binding": path}


def test_existing_preparer_binds_mimo_to_task_and_postprocessor(inputs):
    args = mimo_inputs(inputs)
    launch = json.loads(prepare_training(**args).read_text())
    task = yaml.safe_load(inputs["task_config_path"].read_text())
    assert task["mimo_binding"]["path"] == str(args["mimo_binding"].resolve())
    assert task["mimo_binding"]["sha256"] == digest(args["mimo_binding"].read_bytes())
    assert launch["postprocessor"]["mimo_binding"] == task["mimo_binding"]
    assert launch["environment"]["MAX_CONCURRENT_SESSIONS"] == "1"
    assert launch["evaluation_scope"] == "same-task-engineering-evaluation-not-generalization"
    rows = pq.read_table(inputs["output_dir"] / "train.parquet").to_pylist()
    assert rows[0]["data_source"] == "harbor/mimo-code-code-1/train"


@pytest.mark.parametrize("mode", ["missing", "other-path", "legacy-binding"])
def test_mimo_preparation_requires_exact_independent_binding(inputs, mode):
    args = mimo_inputs(inputs)
    if mode == "missing":
        args.pop("mimo_binding")
    elif mode == "other-path":
        other = args["mimo_binding"].parent.parent / "other.json"
        other.write_bytes(args["mimo_binding"].read_bytes())
        args["mimo_binding"] = other
    else:
        args["t2_fixture_binding"] = args["mimo_binding"]
    with pytest.raises(ValueError):
        prepare_training(**args)
    assert not inputs["output_dir"].exists()


def test_single_worker_concurrency_contract_is_explicit_in_existing_launcher(inputs):
    launch = json.loads(prepare_training(**mimo_inputs(inputs), max_concurrent_sessions=2).read_text())
    parsed = OverridesParser.create().parse_overrides(build_overrides(launch))
    values = {item.key_or_group: item.value() for item in parsed if not item.is_delete()}
    assert values["actor_rollout_ref.rollout.custom.agent_framework.agent_runners.task.max_concurrent_sessions"] == 2


def test_native_recipe_honors_serial_prepared_default_and_manual_override(inputs):
    launch = json.loads(prepare_training(**mimo_inputs(inputs)).read_text())
    environment = {"STUDENT_MODEL_PATH": "/models/student", "TOOL_PARSER": "qwen3"}
    for extra, expected in [({}, 1), ({"MAX_CONCURRENT_SESSIONS": "2"}, 2)]:
        parsed = OverridesParser.create().parse_overrides(native_overrides("rl", launch, {**environment, **extra}))
        values = {item.key_or_group: item.value() for item in parsed}
        framework = values["actor_rollout_ref.rollout.custom"]["agent_framework"]
        assert framework["agent_runners"]["task"]["max_concurrent_sessions"] == expected


@pytest.mark.parametrize("concurrency", [0, True, 65])
def test_preparer_rejects_invalid_concurrency_before_output(inputs, concurrency):
    with pytest.raises(ValueError, match="concurrent"):
        prepare_training(**mimo_inputs(inputs), max_concurrent_sessions=concurrency)
    assert not inputs["output_dir"].exists()
