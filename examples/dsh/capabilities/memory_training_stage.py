"""Trusted resident-backend stage preparation and evidence validation; no model launch."""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from examples.dsh.capabilities import memory_training_verifier as verifier
from examples.dsh.capabilities.memory_chain import new_dir, runtime_digest, write_new
from examples.dsh.capabilities.memory_tasks import reader_prompt, writer_fixture, writer_prompt
from examples.dsh.capabilities.memory_verifier import canonical, loads, read_regular, score, sha
from examples.dsh.memory_closed.profile import build_memory_patch
from uni_agent.tasks.base import build_reward_info
from uni_agent.tasks.dsh.memory_artifacts import freeze_memory_artifact
from uni_agent.tasks.dsh.trajectory_audit import validate_trajectories


@dataclass(frozen=True)
class OperatorSpec:
    root: Path
    runner_python: Path
    runtime_executable: Path
    environment_digest: str
    checkpoint_identity: str
    family: str


@dataclass(frozen=True)
class GroupContext:
    run_id: str
    partition: str
    group_uid: str
    sibling: int
    global_steps: int


@dataclass(frozen=True)
class StageSpec:
    operator: OperatorSpec
    context: GroupContext
    chain_id: str
    role: str
    gateway_session_id: str
    root: Path
    run_root: Path
    trace_root: Path
    result_root: Path
    task_config_path: Path
    fixture_path: Path
    raw_prompt: list[dict]
    metadata: dict
    file_hashes: dict[str, str]


def _name(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", value):
        raise ValueError("Invalid controller identity")


def _binding(context, operator):
    return {
        "schema": "dsh.memory-training-stage.v1",
        "split": "train" if context.partition == "train" else "validation",
        "run_id": context.run_id,
        "group_uid": context.group_uid,
        "sibling": context.sibling,
        "checkpoint_identity": operator.checkpoint_identity,
    }


def _prepare(operator, context, chain_id, gateway_session_id, root, fixture, prompt):
    role = fixture["role"]
    stage = new_dir(root / role)
    run = new_dir(stage / "run")
    fixture = {**fixture, "training_stage": _binding(context, operator)}
    fixture_path = stage / "fixture.json"
    write_new(fixture_path, fixture)
    patch = build_memory_patch(
        role=role,
        chain_id=chain_id,
        session_id="dsh-" + gateway_session_id,
        source_version=fixture["source_version"],
        read_files=[fixture["source_path"], fixture["memory_path"]]
        if role == "writer"
        else [fixture["memory_path"], fixture["question_path"]],
        write_file=fixture["memory_path"] if role == "writer" else None,
    )
    patch_path = stage / "closed.patch.json"
    write_new(patch_path, patch)
    metadata = {
        "task_id": f"dsh/memory-training/{chain_id}/{role}",
        "task_version": "1",
        "split": fixture["training_stage"]["split"],
        "training_stage": fixture["training_stage"],
        "environment_digest": operator.environment_digest,
        "verifier_id": verifier.VERIFIER_ID,
        "verifier_version": verifier.VERIFIER_VERSION,
        "verifier_code_digest": verifier.bundle_digest(),
        "fixture_path": str(fixture_path),
        "fixture_sha256": sha(read_regular(fixture_path)),
    }
    trace_root, result_root = run / "traces", run / "results"
    config = {
        "name": "dsh_architecture",
        "sandbox": {"provider": "local", "runtime_timeout": 1800},
        "agent": {
            "name": "dsh",
            "model": {"max_total_tokens": 8192, "max_tokens_per_turn": 4096},
            "runner_python": str(operator.runner_python),
            "runner_module": "uni_agent.agents.dsh.runner",
            "profile": "sdk-minimal",
            "provider": "deepseek-official",
            "reasoning_effort": "off",
            "default_workdir": str(root),
            "dsh_home_root": str(run / "homes"),
            "artifact_root": str(trace_root),
            "patches": [str(patch_path)],
            "keep_trace": True,
        },
        "verifier_command": [str(operator.runner_python), "-m", "examples.dsh.capabilities.memory_training_verifier"],
        "verifier_timeout": 60,
        "require_trace": True,
        "workdir": str(root),
        "result_root": str(result_root),
        **{k: metadata[k] for k in ("environment_digest", "verifier_id", "verifier_version", "verifier_code_digest")},
    }
    config_path = stage / "task.yaml"
    write_new(config_path, yaml.safe_dump([config], sort_keys=False).encode())
    prompt_path = stage / "prompt.json"
    raw_prompt = [{"role": "user", "content": prompt}]
    write_new(prompt_path, raw_prompt)
    paths = [
        fixture_path,
        patch_path,
        config_path,
        prompt_path,
        Path(__file__),
        Path(verifier.__file__),
        Path(__file__).with_name("memory_tasks.py"),
        Path(__file__).with_name("memory_chain.py"),
        Path(__file__).parents[1] / "memory_closed/profile.py",
        Path(__file__).parents[1] / "memory_closed/policy.mjs",
    ]
    return StageSpec(
        operator,
        context,
        chain_id,
        role,
        gateway_session_id,
        root,
        run,
        trace_root,
        result_root,
        config_path,
        fixture_path,
        raw_prompt,
        metadata,
        {str(p): sha(read_regular(p)) for p in paths},
    )


def prepare_writer_stage(operator, context, *, chain_id, gateway_session_id):
    for value in (chain_id, gateway_session_id, context.run_id, context.group_uid):
        _name(value)
    if (
        context.partition not in ("train", "val")
        or type(context.sibling) is not int
        or not 0 <= context.sibling < 4
        or type(context.global_steps) is not int
        or context.global_steps < 0
        or not operator.checkpoint_identity
    ):
        raise ValueError("Invalid trusted stage context")
    if runtime_digest(operator.runtime_executable) != operator.environment_digest:
        raise ValueError("Runtime pin mismatch")
    root = new_dir(operator.root / chain_id)
    data = new_dir(root / "writer-data")
    fixture, source = writer_fixture(data, chain_id, operator.family)
    write_new(Path(fixture["source_path"]), source)
    return _prepare(operator, context, chain_id, gateway_session_id, root, fixture, writer_prompt(fixture))


def validate_stage_execution(spec, execution):
    for name, expected in spec.file_hashes.items():
        if sha(read_regular(name)) != expected:
            raise ValueError("Stage input or source changed")
    if runtime_digest(spec.operator.runtime_executable) != spec.operator.environment_digest:
        raise ValueError("Runtime changed")
    context = execution.context
    expected = {
        "partition_id": spec.context.partition,
        "gateway_session_id": spec.gateway_session_id,
        "group_uid": spec.context.group_uid,
        "session_index": spec.context.sibling,
        "global_steps": spec.context.global_steps,
    }
    if execution.session_id != spec.gateway_session_id or any(context.get(k) != v for k, v in expected.items()):
        raise ValueError("Stage execution context mismatch")
    if not execution.trajectories:
        raise ValueError("Missing actual trajectories")
    validate_trajectories(
        tuple(execution.trajectories),
        context=context,
        trace_root=str(spec.trace_root),
        result_root=str(spec.result_root),
    )
    reward_info = build_reward_info(execution.task_result)
    if any(t.extra_fields.get("dsh_reward_info") != reward_info for t in execution.trajectories):
        raise ValueError("TaskResult differs from audited trajectories")
    dsh = reward_info["dsh"]
    key = hashlib.sha256(f"{dsh['dsh_session_id']}\0{dsh['trace_sha256']}".encode()).hexdigest()[:24]
    result_dir = spec.result_root / key
    receipt = loads(read_regular(result_dir / "verifier-receipt.json"))
    envelope = loads(read_regular(result_dir / "agent-result.json"))
    fixture = loads(read_regular(spec.fixture_path))
    stored_prompt = loads(read_regular(spec.task_config_path.parent / "prompt.json"))
    if envelope.get("prompt") != stored_prompt or spec.raw_prompt != stored_prompt:
        raise ValueError("Stage prompt changed or does not match execution")
    if envelope["metadata"] != spec.metadata or sha(canonical(fixture)) != spec.metadata["fixture_sha256"]:
        raise ValueError("Stage metadata or fixture mismatch")
    if fixture["training_stage"] != _binding(spec.context, spec.operator) or fixture["chain_id"] != spec.chain_id:
        raise ValueError("Stage group/source identity mismatch")
    events = [
        loads(line)
        for line in read_regular(
            spec.trace_root / hashlib.sha256(spec.gateway_session_id.encode()).hexdigest()[:24] / "session.jsonl",
            8_000_000,
        ).splitlines()
        if line
    ]
    scored = score(fixture, events, envelope["response"], envelope["finished"], dsh["dsh_session_id"])
    if any(scored[k] != receipt[k] for k in ("reward", "finished", "eligible")) or scored["eligible"] is not True:
        raise ValueError("Stage score or admission mismatch")
    if spec.role == "writer" and scored["reward"] != 1:
        raise ValueError("Writer failed quality gate")
    if verifier.bundle_digest() != spec.metadata["verifier_code_digest"]:
        raise ValueError("Verifier bundle changed")
    return receipt, envelope, scored, fixture


def freeze_and_prepare_reader(writer_spec, execution, *, reader_gateway_session_id):
    receipt, envelope, scored, fixture = validate_stage_execution(writer_spec, execution)
    _name(reader_gateway_session_id)
    if writer_spec.role != "writer" or reader_gateway_session_id == writer_spec.gateway_session_id:
        raise ValueError("Reader must have a new independent session")
    frozen = freeze_memory_artifact(
        source_root=Path(fixture["memory_path"]).parent,
        relative_path=Path(fixture["memory_path"]).name,
        expected_source_sha256=scored["extra_info"]["memory_sha256"],
        source_version=fixture["source_version"],
        chain_id=writer_spec.chain_id,
        writer_session_id=receipt["dsh_session_id"],
        max_bytes=fixture["max_bytes"],
        output_dir=writer_spec.root / "frozen",
    )
    question = writer_spec.root / "reader-question.txt"
    write_new(
        question, b"What are the current deployment region and forbidden action? Include the saved source_version.\n"
    )
    reader = {
        "schema": "dsh.memory-stage.v1",
        "role": "reader",
        "chain_id": writer_spec.chain_id,
        "family": fixture["family"],
        "source_version": fixture["source_version"],
        "writer_binding": {
            "dsh_session_id": receipt["dsh_session_id"],
            "gateway_session_id": envelope["dsh"]["gateway_session_id"],
            "receipt_id": receipt["receipt_id"],
            "trace_sha256": receipt["trace_sha256"],
            "manifest_sha256": frozen.manifest_sha256,
            "content_sha256": frozen.content_sha256,
        },
        "frozen_dir": str(writer_spec.root / "frozen"),
        "memory_path": str(writer_spec.root / "frozen/memory.bin"),
        "question_path": str(question),
        "question_sha256": sha(read_regular(question)),
        "max_bytes": fixture["max_bytes"],
        "expected_answer": {"status": "answer", **fixture["expected_memory"]},
    }
    return _prepare(
        writer_spec.operator,
        writer_spec.context,
        writer_spec.chain_id,
        reader_gateway_session_id,
        writer_spec.root,
        reader,
        reader_prompt(reader),
    )
