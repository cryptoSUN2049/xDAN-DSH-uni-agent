"""Bounded host bridge snapshot for the independent T2 verifier; never student paths."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import stat
import tempfile
from pathlib import Path

from harbor.trial.artifact_handler import ArtifactHandler

from uni_agent.agents.dsh.agent import _require_result, _run_key
from uni_agent.agents.dsh.harbor_release import T2_PATCH_PATH
from uni_agent.tasks.harbor_dsh.evolution_scoring import SOURCES, EvolutionBinding
from uni_agent.tasks.harbor_dsh.evolution_scoring_v2 import (
    EVOLUTION_V2_KIND,
    SOURCE_HASHES,
    VERIFIER_BUNDLE_SHA256,
    EvolutionV2Binding,
)


def _digest(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _json(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError("Duplicate bridge JSON key")
            value[key] = item
        return value

    def invalid(_value):
        raise ValueError("Nonfinite bridge JSON")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)


def _read_private(directory, name, limit):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_mode & 0o077
            or before.st_uid != os.getuid()
        ):
            raise ValueError("Bridge evidence must be a private owned regular file")
        if before.st_size > limit:
            raise ValueError("Bridge evidence exceeds upload budget")
        raw = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
        if len(raw) > limit or (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            raise ValueError("Bridge evidence changed during read")
        return raw


def validate_evolution_binding(raw):
    if type(raw) is not bytes or not raw or len(raw) > 65536:
        raise ValueError("Evolution binding must be immutable bounded bytes")
    value = _json(raw)
    is_v2 = isinstance(value, dict) and value.get("kind") == EVOLUTION_V2_KIND
    binding = (EvolutionV2Binding if is_v2 else EvolutionBinding).model_validate(value)
    sources = {"examples/dsh/" + name: "sha256:" + sha for name, sha in SOURCE_HASHES.items()} if is_v2 else None
    if is_v2 and (
        binding.source_sha256s != sources
        or binding.verifier_bundle_sha256 != VERIFIER_BUNDLE_SHA256
        or binding.task_ref.version != "v2"
    ):
        raise ValueError("Evolution v2 binding source/version/bundle mismatch")
    if (
        binding.fixture_path != "/tests/fixture.json"
        or binding.metadata_path != "/tests/metadata.json"
        or set(binding.source_sha256s) != set(sources if is_v2 else SOURCES)
    ):
        raise ValueError("Evolution binding requires fixed verifier paths and sources")
    return binding


class TraceArtifacts(ArtifactHandler):
    def __init__(
        self, *, agent_dir, gateway_session_id, trial_id, trial_name, max_trace_bytes, logger, evolution_binding=None
    ):
        super().__init__(artifacts=[], logger=logger)
        if not gateway_session_id or type(max_trace_bytes) is not int or max_trace_bytes <= 0:
            raise ValueError("Explicit session and positive trace budget required")
        self.agent_dir = Path(agent_dir)
        self.session = gateway_session_id
        self.trial_id = str(trial_id)
        self.trial_name = trial_name
        self.max_trace_bytes = max_trace_bytes
        if evolution_binding is not None:
            validate_evolution_binding(evolution_binding)
        self._evolution_binding = evolution_binding
        self._uploaded = False

    def snapshot(self):
        root = os.open(self.agent_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            directory = os.open("dsh", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root)
            try:
                files = {}
                budget = self.max_trace_bytes
                for name in ("session.jsonl", "run.json", "status.json", "agent-result.json"):
                    files[name] = _read_private(directory, name, budget)
                    budget -= len(files[name])
            finally:
                os.close(directory)
        finally:
            os.close(root)
        trace_path = f"/tmp/uni-agent-dsh/artifacts/{_run_key(self.session)}/session.jsonl"
        helper = _require_result(
            _json(files["run.json"]),
            expected_trace_path=trace_path,
            expected_dsh_session_id=f"dsh-{self.session}",
            require_trace=True,
        )
        status = _json(files["status.json"])
        agent = _json(files["agent-result.json"])
        events = [_json(line) for line in files["session.jsonl"].splitlines()]
        expected = dict(
            schema="dsh.harbor-agent-execution.v1",
            status="completed",
            finished=True,
            finish_reason="completed",
            gateway_session_id=self.session,
            dsh_session_id=f"dsh-{self.session}",
            harbor_context_id=self.trial_id,
            harbor_agent_session_id=self.trial_name + "__agent",
            trace_sha256=_digest(files["session.jsonl"]),
            run_sha256=_digest(files["run.json"]),
            agent_result_sha256=_digest(files["agent-result.json"]),
            event_count=len(events),
        )
        expected_info = dict(
            gateway_session_id=self.session,
            dsh_session_id=f"dsh-{self.session}",
            trace_path=trace_path,
            trace_sha256=expected["trace_sha256"],
            event_count=len(events),
        )
        if (
            not isinstance(status, dict)
            or any(status.get(key) != value for key, value in expected.items())
            or status.get("finished") is not True
            or agent.get("finished") is not True
            or any(agent.get("info", {}).get(key) != value for key, value in expected_info.items())
            or helper.get("finish_reason") != "completed"
            or helper.get("profile") != "sdk-minimal"
            or helper.get("patches_sha256") != _digest(json.dumps([T2_PATCH_PATH], separators=(",", ":")).encode())
            or helper["trace_sha256"] != expected["trace_sha256"]
            or helper["event_count"] != len(events)
            or not events
            or any(not isinstance(event, dict) for event in events)
            or events[-1].get("type") != "turn/end"
            or events[-1].get("data", {}).get("reason") != {"kind": "completed"}
            or agent.get("output", {}).get("response") != helper["final_response"]
        ):
            raise ValueError("Bridge trace/status/session identity mismatch")
        return files

    async def download_artifacts(
        self, source_env, artifacts_dir, *, source_artifacts_dir, artifacts=None, services=None
    ):
        # No student artifact, including Harbor's implicit convention directory,
        # participates in this lane. Preserve an honestly empty Harbor manifest.
        if artifacts:
            raise ValueError("T2 forbids student artifact overrides")
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        return self._write_manifest(artifacts_dir, [])

    async def upload_artifacts(
        self, target_env, artifacts_dir, *, source_artifacts_dir, target_artifacts_dir, artifacts=None
    ):
        if self._uploaded or artifacts:
            raise ValueError("T2 upload is single-use with no student artifact overrides")
        self._uploaded = True
        files = self.snapshot()
        names = ["session.jsonl", "run.json", "status.json"]
        if self._evolution_binding is not None:
            files["evolution-binding.json"] = self._evolution_binding
            names.append("evolution-binding.json")
        # Upload immutable private copies, never reopen the checked original paths.
        with tempfile.TemporaryDirectory(prefix="t2-audit-") as folder:
            async with asyncio.timeout(60):
                result = await target_env.exec(command="mkdir -p -- /audit-input", timeout_sec=30, user="root")
                if result.return_code != 0:
                    raise RuntimeError("Cannot create independent verifier input directory")
                for name in names:
                    path = Path(folder) / name
                    path.write_bytes(files[name])
                    path.chmod(0o600)
                    await target_env.upload_file(source_path=path, target_path="/audit-input/" + name)
