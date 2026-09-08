import asyncio
import hashlib
import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("harbor")
from uni_agent.tasks.harbor_dsh.trace_artifacts import TraceArtifacts


def fixture(tmp_path):
    root = tmp_path / "agent"
    folder = root / "dsh"
    folder.mkdir(parents=True, mode=0o700)
    raw = b'{"type":"turn/end","data":{"reason":{"kind":"completed"}}}\n'
    sha = lambda value: "sha256:" + hashlib.sha256(value).hexdigest()
    from uni_agent.agents.dsh.agent import _run_key
    from uni_agent.agents.dsh.harbor_release import T2_PATCH_PATH

    helper = dict(
        schema="dsh.uni-agent.dsh-run.v1",
        dsh_session_id="dsh-session",
        trace_path=f"/tmp/uni-agent-dsh/artifacts/{_run_key('session')}/session.jsonl",
        trace_sha256=sha(raw),
        trace_persisted=True,
        event_count=1,
        finish_reason="completed",
        final_response="done",
        profile="sdk-minimal",
        patches_sha256=sha(json.dumps([T2_PATCH_PATH], separators=(",", ":")).encode()),
    )
    info = {key: helper[key] for key in ("dsh_session_id", "trace_sha256", "trace_path", "event_count")}
    info["gateway_session_id"] = "session"
    agent = dict(finished=True, output={"response": "done"}, info=info)
    raws = {
        "session.jsonl": raw,
        "run.json": json.dumps(helper).encode(),
        "agent-result.json": json.dumps(agent).encode(),
    }
    status = dict(
        schema="dsh.harbor-agent-execution.v1",
        status="completed",
        finished=True,
        finish_reason="completed",
        gateway_session_id="session",
        dsh_session_id="dsh-session",
        harbor_context_id="trial",
        harbor_agent_session_id="name__agent",
        trace_sha256=sha(raw),
        run_sha256=sha(raws["run.json"]),
        agent_result_sha256=sha(raws["agent-result.json"]),
        event_count=1,
    )
    raws["status.json"] = json.dumps(status).encode()
    for name, value in raws.items():
        (folder / name).write_bytes(value)
        (folder / name).chmod(0o600)
    handler = TraceArtifacts(
        agent_dir=root,
        gateway_session_id="session",
        trial_id="trial",
        trial_name="name",
        max_trace_bytes=10000,
        logger=logging.getLogger("test"),
    )
    return handler, folder


def test_upload_uses_frozen_snapshot_and_fixed_destinations(tmp_path):
    handler, folder = fixture(tmp_path)
    seen = {}

    async def upload(source_path, target_path):
        seen[target_path] = source_path.read_bytes()

    env = SimpleNamespace(exec=AsyncMock(return_value=SimpleNamespace(return_code=0)), upload_file=upload)
    asyncio.run(handler.upload_artifacts(env, tmp_path, source_artifacts_dir="/unused", target_artifacts_dir="/unused"))
    assert set(seen) == {"/audit-input/session.jsonl", "/audit-input/run.json", "/audit-input/status.json"}
    assert seen["/audit-input/session.jsonl"] == (folder / "session.jsonl").read_bytes()


@pytest.mark.parametrize("bad", ["hash", "session", "symlink", "oversize", "permissions"])
def test_reject_before_any_upload(tmp_path, bad):
    handler, folder = fixture(tmp_path)
    if bad == "hash":
        (folder / "session.jsonl").write_bytes(b"tampered")
    if bad == "session":
        path = folder / "status.json"
        data = json.loads(path.read_text())
        data["gateway_session_id"] = "other"
        path.write_text(json.dumps(data))
    if bad == "symlink":
        path = folder / "run.json"
        path.rename(folder / "real.json")
        path.symlink_to("real.json")
    if bad == "oversize":
        handler.max_trace_bytes = 1
    if bad == "permissions":
        (folder / "run.json").chmod(0o644)
    env = SimpleNamespace(exec=AsyncMock(), upload_file=AsyncMock())
    with pytest.raises((ValueError, OSError, RuntimeError)):
        asyncio.run(
            handler.upload_artifacts(env, tmp_path, source_artifacts_dir="/unused", target_artifacts_dir="/unused")
        )
    env.upload_file.assert_not_called()


def test_no_candidate_artifact_download_even_convention_directory(tmp_path):
    handler, _ = fixture(tmp_path)
    env = SimpleNamespace(download_dir=AsyncMock(), download_file=AsyncMock())
    asyncio.run(handler.download_artifacts(env, tmp_path / "artifacts", source_artifacts_dir="/logs/artifacts"))
    env.download_dir.assert_not_called()
    env.download_file.assert_not_called()


def test_cancelled_upload_cleans_private_snapshot_and_cannot_retry(tmp_path):
    handler, _ = fixture(tmp_path)
    temporary = []

    async def cancelled(source_path, target_path):
        temporary.append(source_path)
        raise asyncio.CancelledError

    env = SimpleNamespace(exec=AsyncMock(return_value=SimpleNamespace(return_code=0)), upload_file=cancelled)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            handler.upload_artifacts(env, tmp_path, source_artifacts_dir="/unused", target_artifacts_dir="/unused")
        )
    assert temporary and not temporary[0].exists()
    with pytest.raises(ValueError, match="single-use"):
        asyncio.run(
            handler.upload_artifacts(env, tmp_path, source_artifacts_dir="/unused", target_artifacts_dir="/unused")
        )
