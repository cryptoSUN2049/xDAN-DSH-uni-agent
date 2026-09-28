"""Operator-captured repository state for an independent MiMo Code verifier."""

from __future__ import annotations

import asyncio
import hashlib
import shlex
import stat
from pathlib import Path
from uuid import uuid4

from harbor.trial.artifact_handler import ArtifactHandler

from . import mimo_workspace
from .mimo import MimoBinding, canonical, decode, digest


class MimoWorkspaceArtifacts(ArtifactHandler):
    def __init__(self, *, binding: MimoBinding, agent_dir, gateway_session_id: str, logger):
        super().__init__(artifacts=[], logger=logger)
        if not gateway_session_id:
            raise ValueError("MiMo artifact transport requires a Gateway session")
        self.binding = binding
        self.agent_dir = Path(agent_dir)
        self.session = gateway_session_id
        self._base = None
        self._state = None
        self._archive = None
        self._uploaded = False
        # Read trusted operator code once; never import source from the task image.
        self._source = Path(mimo_workspace.__file__).read_text()

    async def _helper(self, environment, action, *, archive=None, base_ref=None):
        python = "python3" if action == "restore" else self.binding.runner_python
        argv = [python, "-c", self._source, action, self.binding.cwd]
        if archive is not None:
            argv += ["--archive", str(archive)]
        if base_ref is not None:
            argv += ["--base-ref", base_ref]
        argv += [
            "--max-bytes",
            str(self.binding.max_workspace_bytes),
            "--max-files",
            str(self.binding.max_workspace_files),
        ]
        async with asyncio.timeout(180):
            result = await environment.exec(command=shlex.join(argv), timeout_sec=180, user="root")
        if result.return_code != 0:
            raise RuntimeError(f"MiMo workspace {action} failed: {(result.stderr or '')[-2000:]}")
        if len(result.stdout or "") > 65536:
            raise ValueError("MiMo workspace helper response exceeds budget")
        return decode(result.stdout)

    async def capture_base(self, environment):
        if self._base is not None:
            raise ValueError("MiMo repository baseline is single-use")
        self._base = await self._helper(environment, "capture")

    async def download_artifacts(
        self, source_env, artifacts_dir, *, source_artifacts_dir, artifacts=None, services=None
    ):
        if self._base is None or self._state is not None or artifacts or services not in (None, {"main"}):
            raise ValueError("MiMo snapshot requires a fresh operator baseline and no artifact override")
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        archive = artifacts_dir / "mimo-workspace.tar"
        remote = "/tmp/ua-mimo-" + uuid4().hex + ".tar"
        snapshot = await self._helper(source_env, "snapshot", archive=remote)
        async with asyncio.timeout(180):
            await source_env.download_file(source_path=remote, target_path=archive)
        info = archive.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > self.binding.max_workspace_bytes:
            raise ValueError("MiMo downloaded workspace exceeds budget or is not a file")
        with archive.open("rb") as source:
            sha256 = "sha256:" + hashlib.file_digest(source, "sha256").hexdigest()
        if snapshot.get("snapshot_sha256") != sha256 or snapshot.get("bytes") != info.st_size:
            raise ValueError("MiMo workspace changed during transport")
        state = {
            "schema": "dsh.mimo-workspace-state.v1",
            "cwd": self.binding.cwd,
            "gateway_session_id": self.session,
            "binding_sha256": digest(canonical(self.binding.model_dump(mode="json", by_alias=True))),
            **self._base,
            **snapshot,
        }
        evidence = self.agent_dir / "dsh"
        evidence.mkdir(parents=True, exist_ok=True)
        with (evidence / "mimo-state.json").open("xb") as output:
            output.write(canonical(state))
        (evidence / "mimo-state.json").chmod(0o600)
        archive.chmod(0o600)
        self._archive, self._state = archive, state
        return self._write_manifest(artifacts_dir, [])

    async def upload_artifacts(
        self, target_env, artifacts_dir, *, source_artifacts_dir, target_artifacts_dir, artifacts=None
    ):
        if self._uploaded or self._state is None or artifacts:
            raise ValueError("MiMo verifier transport requires one completed snapshot")
        self._uploaded = True
        archive = self._archive
        with archive.open("rb") as source:
            if "sha256:" + hashlib.file_digest(source, "sha256").hexdigest() != self._state["snapshot_sha256"]:
                raise ValueError("MiMo persisted workspace changed before verifier upload")
        remote = "/tmp/ua-mimo-verifier-" + uuid4().hex + ".tar"
        async with asyncio.timeout(180):
            await target_env.upload_file(source_path=archive, target_path=remote)
        await self._helper(target_env, "restore", archive=remote, base_ref=self._base["base_ref"])
        # ensure_dirs is native to Harbor's environment; the state is operator
        # evidence, uploaded only after a successful workspace restoration.
        state_path = artifacts_dir / "mimo-state.json"
        with state_path.open("xb") as output:
            output.write(canonical(self._state))
        state_path.chmod(0o600)
        await target_env.ensure_dirs(["/audit-input"], chmod=True)
        await target_env.upload_file(source_path=state_path, target_path="/audit-input/mimo-state.json")
