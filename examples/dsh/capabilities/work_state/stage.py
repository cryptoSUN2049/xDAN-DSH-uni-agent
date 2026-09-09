"""Pinned work-state A/B preparation. DSH remains the only model execution loop."""

import hashlib
from dataclasses import dataclass
from pathlib import Path

import yaml

from examples.dsh.capabilities.memory_chain import new_dir, runtime_digest, write_new
from examples.dsh.capabilities.memory_training_stage import OperatorSpec, StageSpec, _binding, _name
from examples.dsh.capabilities.memory_verifier import canonical, loads, read_regular, sha
from examples.dsh.capabilities.work_state import verifier
from examples.dsh.capabilities.work_state.bundle import pack_bundle, unpack_bundle
from examples.dsh.capabilities.work_state.profile import build_work_state_patch
from examples.dsh.capabilities.work_state.tasks import make_task
from examples.dsh.capabilities.work_state.verifier import score
from uni_agent.tasks.base import build_reward_info
from uni_agent.tasks.dsh.memory_artifacts import freeze_memory_artifact
from uni_agent.tasks.dsh.trajectory_audit import validate_trajectories


@dataclass(frozen=True)
class WorkStateOperator(OperatorSpec):
    task_manifest: Path
    task_manifest_sha256: str


def _task(operator, context, sample_fields):
    if not isinstance(operator, WorkStateOperator) or operator.family != "work-state-v1":
        raise ValueError("Requires work-state operator")
    raw = read_regular(operator.task_manifest)
    if sha(raw) != operator.task_manifest_sha256:
        raise ValueError("Dataset manifest hash changed")
    data = loads(raw)
    if set(data) != {"schema", "tasks"} or data["schema"] != "dsh.work-state-dataset.v1":
        raise ValueError("Invalid work-state dataset manifest")
    metadata = sample_fields["tools_kwargs"]["task"]["metadata"]
    if set(metadata) != {"work_state_task_id"}:
        raise ValueError("Sample may select only a pinned task identity")
    identity = metadata["work_state_task_id"]
    row = data["tasks"].get(identity)
    if not isinstance(row, dict) or set(row) != {"family", "variant", "seed", "split"}:
        raise ValueError("Unknown or malformed task manifest entry")
    split = "train" if context.partition == "train" else "validation"
    if row["split"] != split:
        raise ValueError("Task split mismatch")
    task = make_task(row["family"], row["variant"], row["seed"])
    if task["task_id"] != identity:
        raise ValueError("Task identity does not match manifest recipe")
    return task


def _sources(directory, files):
    result = {}
    for relative, text in files.items():
        path = directory / relative
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        write_new(path, text.encode())
        result[str(path)] = sha(read_regular(path))
    return result


def _prepare(operator, context, chain_id, gateway_session_id, root, fixture, prompt):
    role = fixture["role"]
    stage = new_dir(root / role)
    run = new_dir(stage / "run")
    fixture = {**fixture, "training_stage": _binding(context, operator)}
    fixture_path = stage / "fixture.json"
    write_new(fixture_path, fixture)
    patch = build_work_state_patch(
        role=role,
        chain_id=chain_id,
        session_id="dsh-" + gateway_session_id,
        source_version=fixture["source_version"],
        read_files=list(fixture["read_files"]) + fixture["read_missing"] + fixture["write_files"],
        write_files=fixture["write_files"],
        read_missing=fixture["read_missing"],
    )
    patch_path = stage / "closed.patch.json"
    write_new(patch_path, patch)
    metadata = dict(
        task_id=f"dsh/work-state/{chain_id}/{role}",
        task_version="1",
        split=fixture["training_stage"]["split"],
        training_stage=fixture["training_stage"],
        contract_id="work-state-v1",
        environment_digest=operator.environment_digest,
        verifier_id=verifier.VERIFIER_ID,
        verifier_version=verifier.VERIFIER_VERSION,
        verifier_code_digest=verifier.bundle_digest(),
        fixture_path=str(fixture_path),
        fixture_sha256=sha(read_regular(fixture_path)),
    )
    trace_root, result_root = run / "traces", run / "results"
    config = dict(
        name="dsh_architecture",
        sandbox=dict(provider="local", runtime_timeout=1800),
        agent=dict(
            name="dsh",
            model=dict(max_total_tokens=8192, max_tokens_per_turn=4096),
            runner_python=str(operator.runner_python),
            runner_module="uni_agent.agents.dsh.runner",
            profile="sdk-minimal",
            provider="deepseek-official",
            reasoning_effort="off",
            default_workdir=str(root),
            dsh_home_root=str(run / "homes"),
            artifact_root=str(trace_root),
            patches=[str(patch_path)],
            keep_trace=True,
        ),
        verifier_command=[str(operator.runner_python), "-m", "examples.dsh.capabilities.work_state.verifier"],
        verifier_timeout=60,
        require_trace=True,
        workdir=str(root),
        result_root=str(result_root),
        **{k: metadata[k] for k in ("environment_digest", "verifier_id", "verifier_version", "verifier_code_digest")},
    )
    config_path = stage / "task.yaml"
    write_new(config_path, yaml.safe_dump([config], sort_keys=False).encode())
    raw_prompt = [dict(role="user", content=prompt)]
    prompt_path = stage / "prompt.json"
    write_new(prompt_path, raw_prompt)
    paths = [
        fixture_path,
        patch_path,
        config_path,
        prompt_path,
        operator.task_manifest,
        Path(__file__),
        *map(Path, fixture["read_files"]),
    ]
    paths += [
        Path(__file__).with_name(name)
        for name in ("tasks.py", "scoring.py", "bundle.py", "policy.mjs", "profile.py", "verifier.py")
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


def prepare_writer_stage(operator, context, *, chain_id, gateway_session_id, sample_fields):
    for value in (chain_id, gateway_session_id, context.run_id, context.group_uid):
        _name(value)
    if (
        context.partition not in ("train", "val")
        or type(context.sibling) is not int
        or not 0 <= context.sibling < 4
        or type(context.global_steps) is not int
        or context.global_steps < 0
    ):
        raise ValueError("Invalid group context")
    task = _task(operator, context, sample_fields)
    if runtime_digest(operator.runtime_executable) != operator.environment_digest:
        raise ValueError("Runtime pin mismatch")
    root = new_dir(operator.root / chain_id)
    data = new_dir(root / "writer-data")
    memory = new_dir(data / "memory")
    output = new_dir(data / "outputs")
    read_files = _sources(data, task["writer_files"])
    fixture = dict(
        schema="dsh.work-state-stage.v1",
        contract_id="work-state-v1",
        role="writer",
        chain_id=chain_id,
        source_version=sha(canonical(task)),
        task=task,
        read_files=read_files,
        write_files=[str(memory / p) for p in task["memory_paths"]],
        read_missing=[],
        memory_root=str(memory),
        output_root=str(output),
        max_bytes=65536,
    )
    prompt = (
        task["writer_goal"]
        + "\nRead-only sources: "
        + ", ".join(read_files)
        + "\nThe memory directory is initially empty; these are optional writable destinations, not missing "
        "required inputs. Use command=create with file_text to create a chosen new file.\n"
        "Optional memory files (write only these exact paths): "
        + ", ".join(fixture["write_files"])
        + "\nFor tool calls use the exact absolute paths above. Inside published memory, link to "
        "other published files relative to the memory directory (for example, handoff.md). B will "
        "receive a different memory directory. Source paths are provenance only and are inaccessible "
        "to B: preserve the useful evidence itself, not just links to A's source directory."
    )
    return _prepare(operator, context, chain_id, gateway_session_id, root, fixture, prompt)


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
    if verifier.bundle_digest() != spec.metadata["verifier_code_digest"]:
        raise ValueError("Verifier bundle changed")
    return receipt, envelope, scored, fixture


def freeze_and_prepare_reader(writer_spec, execution, *, reader_gateway_session_id):
    receipt, envelope, _, fixture = validate_stage_execution(writer_spec, execution)
    _name(reader_gateway_session_id)
    if writer_spec.role != "writer" or reader_gateway_session_id == writer_spec.gateway_session_id:
        raise ValueError("Reader must use a new independent session")
    task = fixture["task"]
    root = writer_spec.root
    packed = pack_bundle(Path(fixture["memory_root"]), task["memory_paths"], fixture["max_bytes"])
    packed_path = root / "packed-memory.bin"
    write_new(packed_path, packed)
    frozen = freeze_memory_artifact(
        source_root=root,
        relative_path=packed_path.name,
        expected_source_sha256=sha(packed),
        source_version=fixture["source_version"],
        chain_id=writer_spec.chain_id,
        writer_session_id=receipt["dsh_session_id"],
        max_bytes=fixture["max_bytes"] * 2 + 65536,
        output_dir=root / "frozen",
    )
    data = new_dir(root / "reader-data")
    unpacked = data / "memory"
    inventory = unpack_bundle(packed, unpacked, task["memory_paths"], max_bytes=fixture["max_bytes"])
    outputs = new_dir(data / "outputs")
    read_files = _sources(data, task["reader_files"])
    read_files.update({str(unpacked / name): entry["sha256"] for name, entry in inventory["files"].items()})
    reader = dict(
        schema="dsh.work-state-stage.v1",
        contract_id="work-state-v1",
        role="reader",
        chain_id=writer_spec.chain_id,
        source_version=fixture["source_version"],
        task=task,
        read_files=read_files,
        write_files=[str(outputs / p) for p in task["result_paths"]],
        read_missing=[str(unpacked / p) for p in inventory["missing"]],
        memory_root=str(unpacked),
        output_root=str(outputs),
        max_bytes=fixture["max_bytes"],
        bundle_paths=task["memory_paths"],
        unpacked_root=str(unpacked),
        frozen_dir=str(root / "frozen"),
        writer_binding=dict(
            dsh_session_id=receipt["dsh_session_id"],
            gateway_session_id=envelope["dsh"]["gateway_session_id"],
            receipt_id=receipt["receipt_id"],
            trace_sha256=receipt["trace_sha256"],
            manifest_sha256=frozen.manifest_sha256,
            content_sha256=frozen.content_sha256,
        ),
    )
    sources = [str(data / p) for p in task["reader_files"]]
    prompt = (
        task["reader_goal"]
        + "\nRead-only public sources: "
        + ", ".join(sources)
        + "\nMemory discovery entry: "
        + str(unpacked / "index.md")
        + " (may be missing; do not invent contents)."
        + "\nAll published memory stays beneath "
        + str(unpacked)
        + ".\nWrite final results only to: "
        + ", ".join(reader["write_files"])
        + "\nThese output files are initially absent. Use command=create and put the business JSON text "
        "in file_text; the surrounding tool-call arguments are not part of that file content."
    )
    return _prepare(
        writer_spec.operator, writer_spec.context, writer_spec.chain_id, reader_gateway_session_id, root, reader, prompt
    )
