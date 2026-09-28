import json

import pytest

from tests.uni_agent.tasks.test_harbor_dsh_isolated_trial import close, config
from tests.uni_agent.tasks.test_mimo_binding import binding_value
from uni_agent.tasks.harbor_dsh.isolated_trial import create_isolated_trial
from uni_agent.tasks.harbor_dsh.mimo import MIMO_STRATEGY, MimoBinding
from uni_agent.tasks.harbor_dsh.mimo_artifacts import MimoWorkspaceArtifacts

pytestmark = [pytest.mark.cpu, pytest.mark.level0]


@pytest.fixture
def task_dir(tmp_path):
    path = tmp_path / "task"
    path.mkdir()
    (path / "tests").mkdir()
    binding = binding_value()
    (path / "mimo-binding.json").write_text(json.dumps(binding))
    (path / "instruction.md").write_text("Fix the issue")
    (path / "tests/test.sh").write_text("#!/bin/sh\nexit 0\n")
    (path / "task.toml").write_text(
        'schema_version="1.3"\nartifacts=[]\n'
        '[environment]\nworkdir="/testbed"\ndocker_image="' + binding["image_binding"]["dsh_image"] + '"\n'
        '[verifier]\nenvironment_mode="separate"\n[verifier.environment]\n'
        'network_mode="no-network"\nworkdir="/testbed"\ndocker_image="'
        + binding["image_binding"]["original_image"]
        + '"\n'
    )
    return path


def test_mimo_trial_uses_explicit_workspace_strategy_without_t2_patch(task_dir):
    binding = MimoBinding.model_validate(binding_value())
    trial = create_isolated_trial(
        config(
            task_dir,
            agent={
                "import_path": "uni_agent.agents.dsh.harbor_agent:DshHarborAgent",
                "model_name": "student",
                "kwargs": {
                    "gateway_base_url": "http://localhost:8000/sessions/session-1/v1",
                    "workdir": "/testbed",
                    "runner_python": "/opt/dsh/bin/python",
                    "profile": "sdk-minimal",
                    "patches": [],
                },
            },
        ),
        allowed_task_dir=task_dir,
        strategy=MIMO_STRATEGY,
        gateway_session_id="session-1",
        mimo_binding=binding,
    )
    try:
        assert isinstance(trial._artifact_handler, MimoWorkspaceArtifacts)
        assert trial._agent_env_mounts == []
        assert trial.config.agent.kwargs["workdir"] == "/testbed"
    finally:
        close(trial)


def test_mimo_requires_explicit_binding_and_does_not_enable_old_lane(task_dir):
    with pytest.raises(ValueError):
        create_isolated_trial(config(task_dir), allowed_task_dir=task_dir)
    with pytest.raises(ValueError):
        create_isolated_trial(config(task_dir), allowed_task_dir=task_dir, strategy=MIMO_STRATEGY)
