"""Operator-owned episode directories, without a model or real Gateway server."""

import hashlib
from pathlib import Path

import pytest
import yaml

from uni_agent.framework import task_runner
from uni_agent.gateway.session import SessionHandle
from uni_agent.tasks import TaskResult


@pytest.fixture
def episode(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "fixtures").mkdir()
    data = b'{"fixture": true}\n'
    (source / "fixtures/input.json").write_bytes(data)
    (source / "unlisted-secret.txt").write_text("must not be copied")
    return {
        "task": {
            "name": "dsh_architecture",
            "sandbox": {"provider": "local"},
            "agent": {"name": "dsh"},
            "metadata": {"workdir": "/untrusted"},
        },
        "session": SessionHandle(session_id="gateway-1", base_url="http://gateway/sessions/gateway-1/v1"),
        "workdir_root": str(tmp_path / "episodes"),
        "source_root": str(source),
        "files": [{"path": "fixtures/input.json", "sha256": "sha256:" + hashlib.sha256(data).hexdigest()}],
    }


def test_fresh_workspace_copies_only_frozen_files_and_overrides_metadata(episode):
    task = episode.pop("task")
    prepared = task_runner._prepare_dsh_episode_workdir(task, **episode)
    workspace = Path(episode["workdir_root"]) / "gateway-1"
    assert prepared["workdir"] == str(workspace)
    assert prepared["agent"]["default_workdir"] == str(workspace)
    assert prepared["metadata"] == task["metadata"]
    assert (workspace / "fixtures/input.json").read_bytes() == (
        Path(episode["source_root"]) / "fixtures/input.json"
    ).read_bytes()
    assert not (workspace / "unlisted-secret.txt").exists()
    assert "workdir" not in task
    with pytest.raises(FileExistsError):
        task_runner._prepare_dsh_episode_workdir(task, **episode)


@pytest.mark.parametrize("mutation", ["source", "copy"])
def test_changed_trusted_files_are_detected_after_episode(episode, mutation):
    task = task_runner._prepare_dsh_episode_workdir(episode.pop("task"), **episode)
    root = episode["source_root"] if mutation == "source" else task["workdir"]
    (Path(root) / "fixtures/input.json").write_text("changed")
    with pytest.raises(ValueError, match="digest mismatch"):
        task_runner._verify_dsh_episode_files(task["workdir"], episode["source_root"], episode["files"])


@pytest.mark.parametrize("path", [".", "../escape", "/absolute", ".git/config", "verl/code.py", "fixtures//input.json"])
def test_episode_manifest_rejects_unsafe_or_unintended_paths(episode, path):
    episode["files"][0]["path"] = path
    with pytest.raises(ValueError, match="file path"):
        task_runner._prepare_dsh_episode_workdir(episode.pop("task"), **episode)
    assert not Path(episode["workdir_root"]).exists()


def test_source_digest_mismatch_prevents_workspace_creation(episode):
    (Path(episode["source_root"]) / "fixtures/input.json").write_text("tampered")
    with pytest.raises(ValueError, match="digest mismatch"):
        task_runner._prepare_dsh_episode_workdir(episode.pop("task"), **episode)
    assert not Path(episode["workdir_root"]).exists()


def test_gateway_handle_and_url_must_agree(episode):
    episode["session"].session_id = "different-session"
    with pytest.raises(ValueError, match="session"):
        task_runner._prepare_dsh_episode_workdir(episode.pop("task"), **episode)


def test_symlinked_source_file_is_rejected(episode, tmp_path):
    source = Path(episode["source_root"]) / "fixtures/input.json"
    target = tmp_path / "elsewhere.json"
    source.rename(target)
    source.symlink_to(target)
    with pytest.raises(ValueError, match="symlink"):
        task_runner._prepare_dsh_episode_workdir(episode.pop("task"), **episode)


@pytest.mark.asyncio
@pytest.mark.parametrize("tamper", [False, True])
async def test_runner_checks_episode_files_before_reward_post(episode, monkeypatch, tmp_path, tamper):
    repository = Path(__file__).resolve().parents[3]
    config_path = tmp_path / "task.yaml"
    config = yaml.safe_load((repository / "examples/dsh/evolution_task_config_v3_live.yaml").read_text())
    config_path.write_text(yaml.safe_dump(config))

    class TamperingTask:
        def __init__(self, task):
            self.task = task

        async def run(self):
            if tamper:
                (Path(self.task["workdir"]) / "fixtures/input.json").write_text("tampered by candidate")
            return TaskResult(reward=1.0, finished=True)

    async def post(*args):
        assert not tamper, "tampered episode cannot post verifier reward"
        return True

    monkeypatch.setattr(task_runner, "get_task", TamperingTask)
    monkeypatch.setattr(task_runner, "_post_reward_info", post)
    episode["session"].reward_info_url = "http://gateway/sessions/gateway-1/reward"

    async def run():
        return await task_runner.run_task(
            session=episode["session"],
            task_config_path=str(config_path),
            tools_kwargs={"task": {"name": "dsh_architecture", "metadata": {}}},
            raw_prompt=[{"role": "user", "content": "test"}],
            report_reward=True,
            require_reward_post=True,
            dsh_episode_workdir_root=episode["workdir_root"],
            dsh_episode_source_root=episode["source_root"],
            dsh_episode_files=episode["files"],
        )

    if tamper:
        with pytest.raises(ValueError, match="digest mismatch"):
            await run()
    else:
        assert (await run()).reward == 1.0


@pytest.mark.parametrize(
    "files", [[], {}, [None], [{"path": ""}], [{"path": "", "sha256": "bad"}], [{"path": "file", "sha256": "bad"}]]
)
def test_malformed_file_lists_fail_closed(episode, files):
    episode["files"] = files
    with pytest.raises(ValueError):
        task_runner._prepare_dsh_episode_workdir(episode.pop("task"), **episode)
    assert not Path(episode["workdir_root"]).exists()


def test_missing_frozen_file_is_rejected(episode):
    (Path(episode["source_root"]) / "fixtures/input.json").unlink()
    with pytest.raises(ValueError, match="missing"):
        task_runner._prepare_dsh_episode_workdir(episode.pop("task"), **episode)


@pytest.mark.parametrize("field", ["workdir_root", "source_root", "files"])
def test_episode_options_must_be_complete(episode, field):
    episode[field] = None
    with pytest.raises(ValueError, match="together"):
        task_runner._prepare_dsh_episode_workdir(episode.pop("task"), **episode)


def test_episode_workspace_requires_local_sandbox(episode):
    episode["task"]["sandbox"]["provider"] = "remote"
    with pytest.raises(ValueError, match="local"):
        task_runner._prepare_dsh_episode_workdir(episode.pop("task"), **episode)


@pytest.mark.parametrize("value", ["relative", "/tmp/../source", None])
def test_episode_roots_must_be_absolute_without_traversal(value):
    with pytest.raises(ValueError, match="absolute"):
        task_runner._dsh_episode_path(value)
