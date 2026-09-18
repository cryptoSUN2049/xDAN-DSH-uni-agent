"""environment_kwargs reach Harbor as --environment-kwarg, which is how a Modal sandbox gets a server-side lifetime."""

import json

from uni_agent.tasks.harbor import task as harbor_task


def _command(tmp_path, **config_kwargs):
    task_dir = tmp_path / "t"
    task_dir.mkdir()
    (task_dir / "task.toml").write_text("")
    config = harbor_task.HarborTaskConfig(
        agent={"name": "terminus-2", "model": {"model_name": "hosted_vllm/m"}},
        metadata={"instance_id": "x", "task_path": str(task_dir)},
        **config_kwargs,
    )
    return harbor_task.build_harbor_trial_command(config, trial_name="t1", trials_dir=tmp_path / "trials")


def test_no_environment_kwargs_by_default(tmp_path):
    assert "--environment-kwarg" not in _command(tmp_path)


def test_sandbox_lifetime_and_app_are_forwarded(tmp_path):
    command = _command(tmp_path, environment_kwargs={"sandbox_timeout_secs": 2700, "app_name": "verl-harbor"})
    pairs = [command[i + 1] for i, tok in enumerate(command) if tok == "--environment-kwarg"]
    assert pairs == ['app_name="verl-harbor"', "sandbox_timeout_secs=2700"]
    # Harbor parses each value as JSON, so the int stays an int and the name stays a string.
    assert json.loads(pairs[1].split("=", 1)[1]) == 2700
    assert json.loads(pairs[0].split("=", 1)[1]) == "verl-harbor"
