import asyncio
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from examples.dsh.capabilities import memory_training_verifier as verifier
from examples.dsh.capabilities.memory_tasks import writer_fixture
from examples.dsh.capabilities.memory_verifier import canonical, sha
from tests.uni_agent.tasks.test_dsh_evolution_verifier import _call, _result
from tests.uni_agent.tasks.test_dsh_task import _config, _HarnessTask
from uni_agent.agents.base import AgentResult
from uni_agent.gateway.session import Trajectory
from uni_agent.sandbox.base import ExecResult
from uni_agent.tasks.base import build_reward_info
from uni_agent.tasks.dsh.trajectory_audit import validate_trajectories


class DiskSandbox:
    def __init__(self, env_overrides=None):
        self.env_overrides = env_overrides or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def write_file(self, path, content):
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content if isinstance(content, bytes) else content.encode())

    async def read_file(self, path):
        return Path(path).read_bytes()

    async def exec(self, argv, *, timeout=None, workdir=None, env=None):
        repo = Path(__file__).resolve().parents[3]
        process = subprocess.run(
            argv,
            cwd=workdir,
            timeout=timeout,
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONPATH": f"{repo}:{repo / 'verl'}", **(env or {}), **self.env_overrides},
        )
        return ExecResult(exit_code=process.returncode, stdout=process.stdout, stderr=process.stderr)


def run_stage(tmp_path, split="train", *, fixture_split=None, unsafe=False, finished=True, env_overrides=None):
    fixture, source = writer_fixture(tmp_path, "chain", "constraints")
    binding = {
        "schema": "dsh.memory-training-stage.v1",
        "split": fixture_split or split,
        "run_id": "run",
        "group_uid": "group",
        "sibling": 0,
        "checkpoint_identity": "checkpoint",
    }
    fixture["training_stage"] = binding
    Path(fixture["source_path"]).write_bytes(source)
    Path(fixture["memory_path"]).write_bytes(canonical(fixture["expected_memory"]))
    fixture_path = tmp_path / "fixture.json"
    fixture_path.write_bytes(canonical(fixture))
    gateway = "memory-training-A"
    traces = tmp_path / "traces"
    trace = traces / hashlib.sha256(gateway.encode()).hexdigest()[:24] / "session.jsonl"
    trace.parent.mkdir(parents=True)
    events = [
        _call("r", "str_replace_editor", {"command": "view", "path": fixture["source_path"]}, seq=0),
        _result("r", source.decode()),
        _call(
            "w",
            "str_replace_editor",
            {
                "command": "create",
                "path": fixture["memory_path"],
                "file_text": canonical(fixture["expected_memory"]).decode(),
            },
            seq=1,
        ),
        _result("w", "created"),
        {"type": "turn/end", "data": {"reason": {"kind": "completed"}}},
    ]
    if unsafe:
        args = json.loads(events[2]["data"]["arguments"])
        args["path"] = fixture["source_path"]
        events[2]["data"]["arguments"] = json.dumps(args)
    raw = b"".join(canonical(x) for x in events)
    trace.write_bytes(raw)

    class Agent:
        async def run(self, **_):
            return AgentResult(
                output={"response": "done"},
                finished=finished,
                info={
                    "adapter": "uni-agent-dsh",
                    "dsh_session_id": "dsh-" + gateway,
                    "gateway_session_id": gateway,
                    "trace_sha256": sha(raw),
                    "trace_path": str(trace),
                    "event_count": len(events),
                    "finish_reason": "completed" if finished else "length",
                    "keep_trace": True,
                },
            )

    config = _config(
        verifier_command=[sys.executable, "-m", "examples.dsh.capabilities.memory_training_verifier"],
        environment_digest=sha(b"runtime"),
        verifier_id=verifier.VERIFIER_ID,
        verifier_version="1",
        verifier_code_digest=verifier.bundle_digest(),
        result_root=str(tmp_path / "results"),
        workdir=str(tmp_path),
        metadata={
            "environment_digest": sha(b"runtime"),
            "verifier_id": verifier.VERIFIER_ID,
            "verifier_version": "1",
            "verifier_code_digest": verifier.bundle_digest(),
            "task_id": "dsh/memory-training/chain/writer",
            "task_version": "1",
            "split": split,
            "fixture_path": str(fixture_path),
            "fixture_sha256": sha(fixture_path.read_bytes()),
            "training_stage": {**binding, "split": split},
        },
    )
    result = asyncio.run(_HarnessTask(config, DiskSandbox(env_overrides), Agent()).run())
    trajectory = Trajectory(
        prompt_ids=[1],
        response_ids=[2],
        response_mask=[1],
        response_logprobs=[-0.1],
        finished=result.finished,
        reward_score=result.reward,
        extra_fields={"dsh_reward_info": build_reward_info(result)},
    )
    return result, trajectory, traces


@pytest.mark.parametrize("split,partition", [("train", "train"), ("validation", "val")])
def test_real_task_subprocess_receipt_and_partition_audit(tmp_path, split, partition):
    result, trajectory, traces = run_stage(tmp_path, split)
    assert result.reward == 1
    assert result.extra_info["verifier"]["extra_info"]["credit_assignment"] == "stage-only"
    validate_trajectories(
        (trajectory,),
        context={"partition_id": partition, "gateway_session_id": "memory-training-A"},
        trace_root=str(traces),
        result_root=str(tmp_path / "results"),
    )


@pytest.mark.parametrize("split,fixture_split", [("test", None), ("train", "validation")])
def test_split_mismatch_rejected(tmp_path, split, fixture_split):
    with pytest.raises(RuntimeError, match="verifier exited"):
        run_stage(tmp_path, split, fixture_split=fixture_split)


def test_unfinished_remains_ineligible(tmp_path):
    result, _, _ = run_stage(tmp_path, finished=False)
    assert result.reward == 0 and result.finished is False


def test_unsafe_source_write_remains_ineligible(tmp_path):
    result, trajectory, traces = run_stage(tmp_path, unsafe=True)
    assert result.reward == 0
    assert "unapproved_action" in result.extra_info["verifier"]["extra_info"]["unsafe"]
    with pytest.raises(ValueError):
        validate_trajectories(
            (trajectory,),
            context={"partition_id": "train", "gateway_session_id": "memory-training-A"},
            trace_root=str(traces),
            result_root=str(tmp_path / "results"),
        )


def test_validation_receipt_cannot_be_consumed_as_training(tmp_path):
    _, trajectory, traces = run_stage(tmp_path, "validation")
    with pytest.raises(ValueError, match="split=train"):
        validate_trajectories(
            (trajectory,),
            context={"partition_id": "train", "gateway_session_id": "memory-training-A"},
            trace_root=str(traces),
            result_root=str(tmp_path / "results"),
        )


def test_old_eval_entry_remains_distinct():
    from examples.dsh.capabilities import memory_verifier

    assert verifier.VERIFIER_ID != memory_verifier.VERIFIER_ID
    assert verifier.bundle_digest() != memory_verifier.bundle_digest()


@pytest.mark.parametrize(
    "field,value",
    [
        ("DSH_VERIFIER_VERSION", "2"),
        ("DSH_VERIFIER_CODE_DIGEST", "sha256:" + "0" * 64),
        ("DSH_ARTIFACT_SHA256", "sha256:" + "0" * 64),
        ("DSH_TRACE_SHA256", "sha256:" + "0" * 64),
        ("DSH_TASK_SPLIT", "validation"),
    ],
)
def test_process_identity_and_digest_tampering_rejected(tmp_path, field, value):
    with pytest.raises(RuntimeError, match="verifier exited"):
        run_stage(tmp_path, env_overrides={field: value})
