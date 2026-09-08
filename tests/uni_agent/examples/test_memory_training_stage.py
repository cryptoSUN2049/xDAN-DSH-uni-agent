import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from examples.dsh.capabilities.memory_training_stage import GroupContext, OperatorSpec, prepare_writer_stage
from examples.dsh.capabilities.memory_verifier import loads, sha


@pytest.fixture
def stage(tmp_path):
    runtime = tmp_path / "runtime"
    runtime.write_bytes(b"runtime")
    runtime.chmod(0o700)
    operator = OperatorSpec(
        root=tmp_path,
        runner_python=Path(sys.executable),
        runtime_executable=runtime,
        environment_digest=sha(b"runtime"),
        checkpoint_identity="checkpoint",
        family="constraints",
    )
    context = GroupContext("run", "train", "group", 0, 7)
    return prepare_writer_stage(operator, context, chain_id="chain", gateway_session_id="GA")


def test_writer_prepares_private_operator_yaml_and_prompt(stage):
    config = yaml.safe_load(stage.task_config_path.read_text())[0]
    assert config["agent"]["name"] == "dsh"
    assert config["sandbox"]["provider"] == "local"
    assert config["agent"]["dsh_home_root"].startswith(str(stage.run_root))
    assert stage.metadata["split"] == "train"
    assert stage.metadata["training_stage"]["group_uid"] == "group"
    assert "read-only" in stage.raw_prompt[0]["content"]
    assert loads(stage.fixture_path.read_bytes())["prompt_revision"] == "2"
    for path, expected in stage.file_hashes.items():
        assert sha(Path(path).read_bytes()) == expected


def test_existing_writer_directory_rejected(stage):
    with pytest.raises(FileExistsError):
        prepare_writer_stage(stage.operator, stage.context, chain_id="chain", gateway_session_id="GA")


def test_changed_stage_refuses_before_execution_audit(stage):
    from examples.dsh.capabilities.memory_training_stage import freeze_and_prepare_reader

    stage.task_config_path.write_text("changed")
    with pytest.raises(ValueError, match="changed"):
        freeze_and_prepare_reader(stage, SimpleNamespace(), reader_gateway_session_id="GB")


def execute_synthetic_stage(spec, *, bad_memory=False):
    """Actual Task/subprocess/audit artifacts from synthetic CPU actions, no model."""
    import asyncio
    import hashlib
    import json

    from examples.dsh.capabilities.memory_verifier import canonical
    from tests.uni_agent.examples.test_memory_training_verifier import DiskSandbox
    from tests.uni_agent.tasks.test_dsh_evolution_verifier import _call, _result
    from tests.uni_agent.tasks.test_dsh_task import _HarnessTask
    from uni_agent.agents.base import AgentResult
    from uni_agent.framework.framework import GatewayStageExecution
    from uni_agent.gateway.session import Trajectory
    from uni_agent.tasks import TaskConfigResolver
    from uni_agent.tasks.base import build_reward_info
    from uni_agent.tasks.dsh.task import DshArchitectureTaskConfig

    fixture = loads(spec.fixture_path.read_bytes())
    if spec.role == "writer":
        memory = {"wrong": True} if bad_memory else fixture["expected_memory"]
        Path(fixture["memory_path"]).write_bytes(canonical(memory))
        events = [
            _call("r", "str_replace_editor", {"command": "view", "path": fixture["source_path"]}, seq=0),
            _result("r", Path(fixture["source_path"]).read_text()),
            _call(
                "w",
                "str_replace_editor",
                {"command": "create", "path": fixture["memory_path"], "file_text": json.dumps(memory)},
                seq=1,
            ),
            _result("w", "created"),
        ]
        response = "done"
    else:
        events = []
        for i, path in enumerate((fixture["memory_path"], fixture["question_path"])):
            events.extend(
                [
                    _call(str(i), "str_replace_editor", {"command": "view", "path": path}, seq=i),
                    _result(str(i), Path(path).read_text()),
                ]
            )
        response = json.dumps(fixture["expected_answer"])
    events.append({"type": "turn/end", "data": {"reason": {"kind": "completed"}}})
    raw = b"".join(canonical(event) for event in events)
    trace = spec.trace_root / hashlib.sha256(spec.gateway_session_id.encode()).hexdigest()[:24] / "session.jsonl"
    trace.parent.mkdir(parents=True)
    trace.write_bytes(raw)

    class Agent:
        async def run(self, **_):
            return AgentResult(
                output={"response": response},
                finished=True,
                info={
                    "adapter": "uni-agent-dsh",
                    "dsh_session_id": "dsh-" + spec.gateway_session_id,
                    "gateway_session_id": spec.gateway_session_id,
                    "trace_sha256": sha(raw),
                    "trace_path": str(trace),
                    "event_count": len(events),
                    "finish_reason": "completed",
                    "keep_trace": True,
                },
            )

    resolved = TaskConfigResolver.from_file(str(spec.task_config_path)).resolve(
        {"name": "dsh_architecture", "metadata": spec.metadata, "prompt": spec.raw_prompt}
    )
    result = asyncio.run(_HarnessTask(DshArchitectureTaskConfig(**resolved), DiskSandbox(), Agent()).run())
    trajectory = Trajectory(
        prompt_ids=[1],
        response_ids=[2],
        response_mask=[1],
        response_logprobs=[-0.1],
        finished=True,
        reward_score=result.reward,
        extra_fields={
            "dsh_reward_info": build_reward_info(result),
            "min_global_steps": spec.context.global_steps,
            "max_global_steps": spec.context.global_steps,
            "generation_count": 1,
            "versioned_generation_count": 1,
            "version_evidence_complete": True,
        },
    )
    context = {
        "partition_id": spec.context.partition,
        "gateway_session_id": spec.gateway_session_id,
        "group_uid": spec.context.group_uid,
        "session_index": spec.context.sibling,
        "global_steps": spec.context.global_steps,
    }
    return GatewayStageExecution(spec.gateway_session_id, context, result, [trajectory], {}, spec.run_root)


def test_actual_cpu_task_writer_freeze_reader_and_repeat_rejection(stage):
    from examples.dsh.capabilities.memory_training_stage import freeze_and_prepare_reader, validate_stage_execution

    execution = execute_synthetic_stage(stage)
    reader = freeze_and_prepare_reader(stage, execution, reader_gateway_session_id="GB")
    config = yaml.safe_load(reader.task_config_path.read_text())[0]
    patch = loads(Path(config["agent"]["patches"][0]).read_bytes())
    policy = patch[-1]["insert"][0]["config"]
    assert policy["writeFile"] is None
    assert not any("writer-data" in path for path in policy["readFiles"])
    assert reader.metadata["training_stage"] == stage.metadata["training_stage"]
    result = validate_stage_execution(reader, execute_synthetic_stage(reader))
    assert result[2]["reward"] == 1
    with pytest.raises((ValueError, FileExistsError)):
        freeze_and_prepare_reader(stage, execution, reader_gateway_session_id="GC")


@pytest.mark.parametrize("bad", ["group", "session", "source", "quality"])
def test_wrong_stage_evidence_cannot_freeze(stage, bad):
    from examples.dsh.capabilities.memory_training_stage import freeze_and_prepare_reader

    execution = execute_synthetic_stage(stage, bad_memory=bad == "quality")
    if bad == "group":
        execution.context["group_uid"] = "other"
    elif bad == "session":
        execution.context["gateway_session_id"] = "other"
    elif bad == "source":
        Path(loads(stage.fixture_path.read_bytes())["source_path"]).write_text("changed")
    with pytest.raises((ValueError, RuntimeError)):
        freeze_and_prepare_reader(stage, execution, reader_gateway_session_id="GB")
    assert not (stage.root / "frozen").exists()


def test_changed_prompt_cannot_admit_old_execution(stage):
    from examples.dsh.capabilities.memory_training_stage import validate_stage_execution

    execution = execute_synthetic_stage(stage)
    stage.raw_prompt[0]["content"] = "different prompt"
    with pytest.raises(ValueError, match="prompt"):
        validate_stage_execution(stage, execution)


def test_reader_cannot_reuse_writer_gateway_identity(stage):
    from examples.dsh.capabilities.memory_training_stage import freeze_and_prepare_reader

    with pytest.raises(ValueError, match="independent"):
        freeze_and_prepare_reader(stage, execute_synthetic_stage(stage), reader_gateway_session_id="GA")
    assert not (stage.root / "frozen").exists()
