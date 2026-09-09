import sys
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from examples.dsh.capabilities.memory_training_stage import GroupContext
from examples.dsh.capabilities.memory_verifier import canonical, loads, sha
from examples.dsh.capabilities.work_state.stage import WorkStateOperator, prepare_writer_stage
from examples.dsh.capabilities.work_state.tasks import make_task


@pytest.fixture
def inputs(tmp_path):
    runtime = tmp_path / "runtime"
    runtime.write_bytes(b"runtime")
    runtime.chmod(0o700)
    task = make_task("WS01", 1, 2)
    manifest = tmp_path / "dataset.json"
    manifest.write_bytes(
        canonical(
            {
                "schema": "dsh.work-state-dataset.v1",
                "tasks": {task["task_id"]: {"family": "WS01", "variant": 1, "seed": 2, "split": "train"}},
            }
        )
    )
    operator = WorkStateOperator(
        tmp_path,
        Path(sys.executable),
        runtime,
        sha(b"runtime"),
        "base",
        "work-state-v1",
        manifest,
        sha(manifest.read_bytes()),
    )
    context = GroupContext("run", "train", "group", 0, 1)
    sample = {"tools_kwargs": {"task": {"metadata": {"work_state_task_id": task["task_id"]}}}}
    return operator, context, sample


def prep(inputs, **kw):
    operator, context, sample = inputs
    return prepare_writer_stage(
        operator, context, chain_id="chain", gateway_session_id="GA", sample_fields=sample, **kw
    )


def test_manifest_bound_writer_private_sources_no_truth_leak(inputs):
    spec = prep(inputs)
    fixture = loads(spec.fixture_path.read_bytes())
    assert fixture["task"] == make_task("WS01", 1, 2)
    assert fixture["contract_id"] == "work-state-v1"
    assert "expected_config" not in str(spec.raw_prompt)
    config = yaml.safe_load(spec.task_config_path.read_text())[0]
    assert config["agent"]["name"] == "dsh" and config["verifier_id"] == "dsh-work-state-training-stage"
    assert spec.metadata["training_stage"]["split"] == "train"
    assert spec.root.name == "chain"
    assert not set(fixture["read_files"]) & set(fixture["write_files"])
    for name, digest in spec.file_hashes.items():
        assert sha(Path(name).read_bytes()) == digest


@pytest.mark.parametrize("kind", ["hash", "split", "unknown", "sample_override", "family"])
def test_untrusted_sample_or_manifest_rejected_before_root(inputs, kind):
    op, context, sample = inputs
    if kind == "hash":
        op = replace(op, task_manifest_sha256=sha(b"other"))
    if kind == "split":
        context = replace(context, partition="val")
    if kind == "unknown":
        sample["tools_kwargs"]["task"]["metadata"]["work_state_task_id"] = "unknown"
    if kind == "sample_override":
        sample["tools_kwargs"]["task"]["metadata"]["family"] = "WS06"
    if kind == "family":
        op = replace(op, family="constraints")
    with pytest.raises((ValueError, KeyError)):
        prep((op, context, sample))
    assert not (op.root / "chain").exists()


def execute_synthetic_stage(spec, *, bad_memory=False, transform_events=None):
    """Actual Task/subprocess/audit artifacts from synthetic CPU actions, no model."""
    import asyncio
    import hashlib

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
    from examples.dsh.capabilities.work_state.tasks import oracle_memory, oracle_outputs

    selected = oracle_memory(fixture["task"]) if spec.role == "writer" else oracle_outputs(fixture["task"])
    if bad_memory:
        selected = {} if spec.role == "writer" else {"config.json": b"{}", "plan.json": b"[]"}
    base = Path(fixture["memory_root"] if spec.role == "writer" else fixture["output_root"])
    events = []
    for i, (name, raw) in enumerate(selected.items()):
        target = base / name
        target.write_bytes(raw)
        events.extend(
            [
                _call(
                    str(i),
                    "str_replace_editor",
                    {"command": "create", "path": str(target), "file_text": raw.decode()},
                    seq=i,
                ),
                _result(str(i), "created"),
            ]
        )
    if transform_events is not None:
        events = transform_events(fixture, events)
    response = "done"
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
            "min_global_steps": (
                spec.context.global_steps - 1 if spec.context.partition == "train" else spec.context.global_steps
            ),
            "max_global_steps": (
                spec.context.global_steps - 1 if spec.context.partition == "train" else spec.context.global_steps
            ),
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


@pytest.mark.parametrize("empty", [False, True])
def test_actual_task_cli_writer_zero_freeze_reader_and_no_repair(inputs, empty):
    from examples.dsh.capabilities.work_state.stage import freeze_and_prepare_reader, validate_stage_execution

    writer = prep(inputs)
    execution = execute_synthetic_stage(writer, bad_memory=empty)
    assert execution.task_result.reward == 0
    reader = freeze_and_prepare_reader(writer, execution, reader_gateway_session_id="GB")
    fixture = loads(reader.fixture_path.read_bytes())
    assert (Path(fixture["memory_root"]) / "index.md").exists() is (not empty)
    assert reader.root == writer.root
    assert "writer-data" not in str(reader.raw_prompt)
    assert "expected_config" not in str(reader.raw_prompt)
    assert "modules.md" not in str(reader.raw_prompt)
    assert not any("writer-data" in p for p in fixture["read_files"])
    scored = validate_stage_execution(reader, execute_synthetic_stage(reader))[2]
    assert scored["eligible"] and scored["reward"] == 1
    with pytest.raises((ValueError, FileExistsError)):
        freeze_and_prepare_reader(writer, execution, reader_gateway_session_id="GC")


@pytest.mark.parametrize("kind", ["source", "manifest", "group", "session", "runtime"])
def test_changed_evidence_refuses_freeze(inputs, kind):
    from examples.dsh.capabilities.work_state.stage import freeze_and_prepare_reader

    writer = prep(inputs)
    execution = execute_synthetic_stage(writer)
    if kind == "source":
        Path(next(iter(loads(writer.fixture_path.read_bytes())["read_files"]))).write_text("changed")
    if kind == "manifest":
        writer.operator.task_manifest.write_text("changed")
    if kind == "runtime":
        writer.operator.runtime_executable.write_bytes(b"changed")
    if kind == "group":
        execution.context["group_uid"] = "other"
    if kind == "session":
        execution.context["gateway_session_id"] = "other"
    with pytest.raises(ValueError):
        freeze_and_prepare_reader(writer, execution, reader_gateway_session_id="GB")


def test_legal_a_zero_to_b_zero_does_not_become_admission_error(inputs):
    from examples.dsh.capabilities.work_state.stage import freeze_and_prepare_reader, validate_stage_execution

    writer = prep(inputs)
    a = execute_synthetic_stage(writer, bad_memory=True)
    reader = freeze_and_prepare_reader(writer, a, reader_gateway_session_id="GB")
    b = execute_synthetic_stage(reader, bad_memory=True)
    receipt, _, scored, _ = validate_stage_execution(reader, b)
    assert a.task_result.reward == b.task_result.reward == 0
    assert receipt["eligible"] and scored["eligible"]


def test_revision3_actual_stage_prompts_keep_transport_separate_from_business(inputs):
    from examples.dsh.capabilities.work_state.stage import freeze_and_prepare_reader

    writer = prep(inputs)
    a_prompt = writer.raw_prompt[0]["content"]
    assert "initially empty" in a_prompt
    assert "command=create" in a_prompt and "file_text" in a_prompt
    assert "final chat response is not transferred" in a_prompt
    reader = freeze_and_prepare_reader(writer, execute_synthetic_stage(writer), reader_gateway_session_id="GB")
    b_prompt = reader.raw_prompt[0]["content"]
    assert "top-level" in b_prompt and "not editor commands" in b_prompt
    assert "output files are initially absent" in b_prompt
    assert "command=create" in b_prompt and "file_text" in b_prompt
    assert "expected_config" not in b_prompt
    assert "writer-data" not in b_prompt
