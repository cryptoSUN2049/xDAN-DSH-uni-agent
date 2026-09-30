import copy
import hashlib
import json

import numpy as np
import pytest

from deployment.checks.token_journal_audit import audit, main, replay
from tests.uni_agent.gateway.test_session_multiple_chains_on_cpu import _run, _session
from uni_agent.gateway.session.token_journal import TokenJournal
from verl.workers.rollout.replica import TokenOutput


class Backend:
    async def generate(self, **kwargs):
        return TokenOutput(
            token_ids=[65, 66],
            log_probs=[-0.1, -0.2],
            stop_reason="completed",
            extra_fields={"min_global_steps": 3, "max_global_steps": 3},
        )


async def recorded(tmp_path, monkeypatch, *, rollback=False):
    monkeypatch.setenv("UNI_AGENT_TOKEN_JOURNAL_DIR", str(tmp_path / "journal"))
    session = _session("actual-hook", sampling_params={"logprobs": True}, enable_last_assistant_rollback=rollback)
    messages = [{"role": "user", "content": "task"}]
    first = await _run(session, Backend(), messages)
    messages += [first.assistant_msg, {"role": "user", "content": "tool observation"}]
    await _run(session, Backend(), messages)
    if rollback:
        await _run(session, Backend(), messages + [{"role": "user", "content": "replace previous assistant"}])
    trajectories = await session.finalize()
    path = session._token_journal.path
    return json.loads("[" + ",".join(path.read_text().splitlines()) + "]"), trajectories, path


@pytest.mark.asyncio
@pytest.mark.parametrize("rollback", [False, True])
async def test_actual_session_hooks_and_npz(tmp_path, monkeypatch, rollback):
    events, trajectories, path = await recorded(tmp_path, monkeypatch, rollback=rollback)
    final, _, summary = replay(events)
    assert summary["commits"] == (3 if rollback else 2)
    assert summary["context_tokens"] > 0
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700
    arrays = {}
    for i, t in enumerate(final):
        for key, value in t["state"].items():
            arrays[f"traj{i}_{key}"] = np.asarray(value, dtype=np.float32 if key == "response_logprobs" else np.int32)
    np.savez(tmp_path / "trajectory.npz", **arrays)
    meta = {
        "gateway_session_id": "actual-hook",
        "trajectory_npz_sha256": "sha256:" + hashlib.sha256((tmp_path / "trajectory.npz").read_bytes()).hexdigest(),
        "trajectories": [{"chain_id": t.chain_id, **t.extra_fields} for t in trajectories],
    }
    metadata = tmp_path / "trajectory.json"
    metadata.write_text(json.dumps(meta))
    assert audit(path, metadata)["passed"]
    report = tmp_path / "report.json"
    monkeypatch.setattr(
        "sys.argv",
        [
            "audit",
            "--journal-dir",
            str(path.parent),
            "--agent-dir",
            str(tmp_path),
            "--output",
            str(report),
            "--session-id",
            "actual-hook",
        ],
    )
    with pytest.raises(SystemExit) as success:
        main()
    assert success.value.code == 0
    assert json.loads(report.read_text())["selection"] == "explicit_session_ids"
    arrays["traj0_response_mask"][-1] = 0
    np.savez(tmp_path / "trajectory.npz", **arrays)
    meta["trajectory_npz_sha256"] = "sha256:" + hashlib.sha256((tmp_path / "trajectory.npz").read_bytes()).hexdigest()
    metadata.write_text(json.dumps(meta))
    with pytest.raises(ValueError, match="NPZ differs"):
        audit(path, metadata)
    with pytest.raises(SystemExit) as failed:
        main()
    assert failed.value.code == 1
    assert json.loads(report.read_text())["passed"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation",
    [
        "mask",
        "ids",
        "logprob",
        "contextmask",
        "contextlogprob",
        "session",
        "seq",
        "missingbackend",
        "missingfinal",
        "nan",
        "version",
        "chain",
        "finalstate",
        "duplicatecommit",
        "retainedprefix",
    ],
)
async def test_rejects_corrupted_evidence(tmp_path, monkeypatch, mutation):
    events, _, _ = await recorded(tmp_path, monkeypatch)
    events = copy.deepcopy(events)
    if mutation in {"mask", "ids", "logprob"}:
        key = {"mask": "response_mask", "ids": "response_ids", "logprob": "response_logprobs"}[mutation]
        events[2]["state"][key][-1] += 1
    elif mutation in {"contextmask", "contextlogprob"}:
        key = "response_mask" if mutation == "contextmask" else "response_logprobs"
        events[3]["prepared"][key][-1] = 1
    elif mutation == "session":
        events[1]["session_id"] = "wrong"
    elif mutation == "seq":
        events[1]["seq"] = 12
    elif mutation == "missingbackend":
        events[1]["kind"] = "denied"
    elif mutation == "missingfinal":
        events.pop()
    elif mutation == "nan":
        events[1]["log_probs"][0] = float("nan")
    elif mutation == "version":
        events[1]["min_global_steps"] = 9
    elif mutation == "chain":
        events[5]["chain_id"] = 99
    elif mutation == "finalstate":
        events[-1]["trajectories"][0]["state"]["response_ids"][-1] += 1
    elif mutation == "duplicatecommit":
        events[3] = {**events[2], "seq": 3}
    elif mutation == "retainedprefix":
        events[3]["prepared"]["response_mask"][0] = 0
    with pytest.raises(ValueError):
        replay(events)


def test_default_off_and_private_paths(tmp_path, monkeypatch):
    monkeypatch.delenv("UNI_AGENT_TOKEN_JOURNAL_DIR", raising=False)
    assert TokenJournal.from_env("none") is None
    root = tmp_path / "private"
    journal = TokenJournal(root, "session")
    with pytest.raises(FileExistsError):
        TokenJournal(root, "session")
    link = tmp_path / "link"
    link.symlink_to(root)
    with pytest.raises(ValueError):
        TokenJournal(link, "different")
    root.chmod(0o755)
    with pytest.raises(ValueError):
        TokenJournal(root, "different")
    with pytest.raises(ValueError):
        journal.write("bad", number=float("nan"))


def test_run_budget_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setattr("uni_agent.gateway.session.token_journal.MAX_EVENTS", 1)
    first = TokenJournal(tmp_path / "private", "one")
    second = TokenJournal(tmp_path / "private", "two")
    first.write("prepare")
    with pytest.raises(RuntimeError, match="budget"):
        second.write("prepare")


@pytest.mark.asyncio
async def test_decode_failure_never_committed(tmp_path, monkeypatch):
    monkeypatch.setenv("UNI_AGENT_TOKEN_JOURNAL_DIR", str(tmp_path / "private"))
    session = _session("decode-failure", sampling_params={"logprobs": True})

    async def fail(*args, **kwargs):
        raise ValueError("decode failed")

    monkeypatch.setattr(session._codec, "decode_response", fail)
    with pytest.raises(ValueError, match="decode failed"):
        await _run(session, Backend(), [{"role": "user", "content": "task"}])
    events = [json.loads(line) for line in session._token_journal.path.read_text().splitlines()]
    assert [e["kind"] for e in events] == ["prepare", "backend", "failure"]
    assert session.active_chains == []
    with pytest.raises(ValueError, match="completed"):
        replay(events)


@pytest.mark.asyncio
@pytest.mark.parametrize("first,denied", [(True, False), (True, True), (False, True)])
async def test_real_rollback_and_capacity_close(tmp_path, monkeypatch, first, denied):
    monkeypatch.setenv("UNI_AGENT_TOKEN_JOURNAL_DIR", str(tmp_path / "private"))
    session = _session("rollback", sampling_params={"logprobs": True}, enable_last_assistant_rollback=True)
    messages = [{"role": "user", "content": "start"}]
    one = await _run(session, Backend(), messages)
    if not first:
        messages += [one.assistant_msg, {"role": "user", "content": "observation"}]
        await _run(session, Backend(), messages)
    rewritten = messages + [{"role": "user", "content": "replace failed assistant"}]
    if denied:
        session._trajectory_capacity = len(session.active_chains[0].buffer.prompt_ids) + 1
    await _run(session, Backend(), rewritten)
    actual = await session.finalize()
    events = [json.loads(line) for line in session._token_journal.path.read_text().splitlines()]
    final, _, _ = replay(events)
    assert len(final) == len(actual)
    assert any(e.get("rollback") for e in events)
    assert bool([e for e in events if e["kind"] == "denied"]) == denied
