"""Run Harbor's skip-tests-upload verifier branch through the MiMo-only hook."""

import contextlib
import shutil
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from harbor.trial.single_step import SingleStepTrial

from tests.uni_agent.tasks import test_mimo_harbor_lane
from tests.uni_agent.tasks.test_harbor_dsh_isolated_trial import close
from tests.uni_agent.tasks.test_mimo_harbor_lane import make_trial


@pytest.fixture
def task_dir(tmp_path):
    return test_mimo_harbor_lane.task_dir.__wrapped__(tmp_path)


class VerifierEnvironment:
    def __init__(self, root, task):
        self.root = root
        self.os = task.config.environment.os
        self.capabilities = SimpleNamespace(mounted=False)
        self.uploads = []
        self.closed = False

    def path(self, value):
        return self.root / str(value).lstrip("/")

    def with_default_user(self, user):
        return contextlib.nullcontext()

    async def empty_dirs(self, dirs, *, chmod):
        for item in dirs:
            self.path(item).mkdir(parents=True, exist_ok=True)

    async def upload_dir(self, *, source_dir, target_dir):
        self.uploads.append(target_dir)
        shutil.copytree(source_dir, self.path(target_dir), dirs_exist_ok=True)

    async def download_dir(self, *, source_dir, target_dir):
        shutil.copytree(self.path(source_dir), target_dir, dirs_exist_ok=True)

    async def exec(self, command, **kwargs):
        # Only the environment transport is replaced. Harbor's real verifier
        # resolves the script, performs chmod, downloads logs and parses reward.
        if not self.path("/tests/test.sh").is_file():
            return SimpleNamespace(return_code=127, stdout="", stderr="/tests/test.sh: No such file or directory")
        if not command.startswith("chmod"):
            self.path("/logs/verifier/reward.txt").write_text("1")
        return SimpleNamespace(return_code=0, stdout="", stderr="")


def native_verifier_boundary(trial, tmp_path, monkeypatch):
    environment = VerifierEnvironment(tmp_path / "verifier", trial.task)

    @contextlib.asynccontextmanager
    async def separate(self, *args, **kwargs):
        try:
            yield environment
        finally:
            environment.closed = True

    @contextlib.asynccontextmanager
    async def phase(*args, **kwargs):
        yield

    monkeypatch.setattr(SingleStepTrial, "_separate_verifier_env", separate)
    monkeypatch.setattr(trial, "_phase_network_policy", phase)
    monkeypatch.setattr(trial, "_log_context", lambda *a, **k: contextlib.nullcontext())
    trial._artifact_handler.upload_artifacts = AsyncMock()
    trial.agent_environment.upload_dir = AsyncMock(side_effect=AssertionError("hidden tests reached agent"))
    return environment


async def verify(trial, tmp_path):
    return await trial._run_separate_verifier(
        key="trial", timeout_sec=10, artifacts_dir=tmp_path / "artifacts", user=None
    )


@pytest.mark.asyncio
async def test_native_skip_upload_branch_receives_tests_only_in_verifier(task_dir, tmp_path, monkeypatch):
    trial = make_trial(task_dir)
    environment = native_verifier_boundary(trial, tmp_path, monkeypatch)
    try:
        result = await verify(trial, tmp_path)
        assert result.rewards == {"reward": 1.0}
        assert environment.uploads == ["/tests"]
        assert environment.path("/tests/test.patch").read_bytes() == (task_dir / "tests/test.patch").read_bytes()
        assert environment.closed
        trial.agent_environment.upload_dir.assert_not_called()
        trial._artifact_handler.upload_artifacts.assert_awaited_once()
    finally:
        close(trial)


@pytest.mark.asyncio
async def test_changed_frozen_tests_fail_before_verification_and_close_env(task_dir, tmp_path, monkeypatch):
    trial = make_trial(task_dir)
    environment = native_verifier_boundary(trial, tmp_path, monkeypatch)
    (task_dir / "tests/test.sh").write_text("changed after task digest admission")
    try:
        with pytest.raises(ValueError, match="Frozen MiMo verifier tests changed"):
            await verify(trial, tmp_path)
        assert environment.closed and not environment.uploads
        trial._artifact_handler.upload_artifacts.assert_not_called()
    finally:
        close(trial)


@pytest.mark.asyncio
async def test_failed_test_upload_keeps_parent_environment_cleanup(task_dir, tmp_path, monkeypatch):
    trial = make_trial(task_dir)
    environment = native_verifier_boundary(trial, tmp_path, monkeypatch)
    environment.upload_dir = AsyncMock(side_effect=RuntimeError("injected upload transport failure"))
    try:
        with pytest.raises(RuntimeError, match="upload transport failure"):
            await verify(trial, tmp_path)
        assert environment.closed
        trial._artifact_handler.upload_artifacts.assert_not_called()
    finally:
        close(trial)


@pytest.mark.parametrize("kind", ["link", "extra", "missing", "directory"])
def test_tests_bundle_paths_are_closed_and_regular(task_dir, tmp_path, kind):
    script = task_dir / "tests/test.sh"
    if kind == "link":
        script.unlink()
        script.symlink_to(tmp_path / "outside")
    elif kind == "missing":
        script.unlink()
    elif kind == "directory":
        script.unlink()
        script.mkdir()
    else:
        (task_dir / "tests/unexpected").write_text("not in the MiMo contract")
    with pytest.raises(ValueError, match="MiMo verifier tests"):
        trial = make_trial(task_dir)
        close(trial)
