import asyncio
import json
import logging
import shlex
import shutil
import sys
from types import SimpleNamespace

import pytest

from tests.uni_agent.tasks.test_mimo_binding import binding_value
from tests.uni_agent.tasks.test_mimo_workspace import repository
from uni_agent.tasks.harbor_dsh.mimo import MimoBinding
from uni_agent.tasks.harbor_dsh.mimo_artifacts import MimoWorkspaceArtifacts

pytestmark = [pytest.mark.cpu, pytest.mark.level0]


class Environment:
    def __init__(self, root):
        self.root = root

    def path(self, value):
        return self.root / value.lstrip("/")

    async def ensure_dirs(self, paths, *, chmod):
        for path in paths:
            self.path(path).mkdir(parents=True, exist_ok=True)

    async def exec(self, *, command, timeout_sec, user):
        argv = shlex.split(command)
        argv[0] = sys.executable
        argv[4] = str(self.path(argv[4]))
        if "--archive" in argv:
            index = argv.index("--archive") + 1
            argv[index] = str(self.path(argv[index]))
            self.path("/tmp").mkdir(exist_ok=True)
        process = await asyncio.create_subprocess_exec(
            *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout_sec)
        return SimpleNamespace(return_code=process.returncode, stdout=stdout.decode(), stderr=stderr.decode())

    async def download_file(self, source_path, target_path):
        shutil.copyfile(self.path(source_path), target_path)

    async def upload_file(self, source_path, target_path):
        destination = self.path(target_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_path, destination)


@pytest.mark.asyncio
async def test_operator_baseline_and_workspace_are_replayed_into_independent_environment(tmp_path):
    student = Environment(tmp_path / "student")
    verifier = Environment(tmp_path / "verifier")
    student.root.mkdir()
    verifier.root.mkdir()
    repository(student.path("/testbed"))
    shutil.copytree(student.path("/testbed"), verifier.path("/testbed"))
    handler = MimoWorkspaceArtifacts(
        binding=MimoBinding.model_validate(binding_value()),
        agent_dir=tmp_path / "agent",
        gateway_session_id="session-1",
        logger=logging.getLogger(__name__),
    )

    await handler.capture_base(student)
    (student.path("/testbed") / "old.txt").unlink()
    (student.path("/testbed") / "new.txt").write_text("agent solution")
    artifacts = tmp_path / "artifacts"
    await handler.download_artifacts(student, artifacts, source_artifacts_dir="/artifacts", services={"main"})
    await handler.upload_artifacts(
        verifier, artifacts, source_artifacts_dir="/artifacts", target_artifacts_dir="/artifacts"
    )
    assert not verifier.path("/testbed/old.txt").exists()
    assert verifier.path("/testbed/new.txt").read_text() == "agent solution"
    state = json.loads(verifier.path("/audit-input/mimo-state.json").read_text())
    assert state["gateway_session_id"] == "session-1"
    assert state["snapshot_sha256"].startswith("sha256:")
    assert (tmp_path / "agent/dsh/mimo-state.json").read_bytes() == verifier.path(
        "/audit-input/mimo-state.json"
    ).read_bytes()


@pytest.mark.asyncio
async def test_snapshot_requires_operator_baseline(tmp_path):
    handler = MimoWorkspaceArtifacts(
        binding=MimoBinding.model_validate(binding_value()),
        agent_dir=tmp_path,
        gateway_session_id="session-1",
        logger=logging.getLogger(__name__),
    )
    with pytest.raises(ValueError, match="baseline"):
        await handler.download_artifacts(None, tmp_path / "artifacts", source_artifacts_dir="/artifacts")
