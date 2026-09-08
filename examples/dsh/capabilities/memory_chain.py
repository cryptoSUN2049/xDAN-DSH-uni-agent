"""Prepare/admit/finalize two independent evaluation sessions; never invokes training."""

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from deployment.services.harbor_training_supervisor import supervise
from examples.dsh.capabilities.memory_denial_budget import denial_health
from examples.dsh.capabilities.memory_tasks import reader_prompt, writer_fixture, writer_prompt
from examples.dsh.capabilities.memory_verifier import (
    VERIFIER_ID,
    bundle_digest,
    canonical,
    loads,
    read_regular,
    score,
    sha,
)
from examples.dsh.memory_closed.profile import build_memory_patch
from uni_agent.tasks.dsh.memory_artifacts import freeze_memory_artifact


def runtime_digest(path):
    """Read-only executable pin; package-cache hardlinks are allowed, unlike memory."""
    path = Path(path)
    if path.resolve() != path:
        raise ValueError("Runtime path must be canonical")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("Runtime must be a regular executable")
        digest = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
        after = os.fstat(stream.fileno())
        keys = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        identity = lambda info: tuple(getattr(info, key) for key in keys)
        if identity(before) != identity(after) or identity(after) != identity(path.stat()):
            raise ValueError("Runtime changed while hashing")
    return "sha256:" + digest.hexdigest()


def write_new(path, value):
    raw = value if isinstance(value, bytes) else canonical(value)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def new_dir(path):
    path = Path(path).absolute()
    if path.parent.resolve() != path.parent:
        raise ValueError("Use a canonical private parent")
    path.mkdir(mode=0o700)
    if stat.S_IMODE(path.stat().st_mode) != 0o700:
        raise ValueError("Private directory permissions not supported")
    return path


def _stage(root, manifest, fixture, prompt):
    import pyarrow as pa
    import pyarrow.parquet as pq
    import yaml

    role = fixture["role"]
    stage = new_dir(root / role)
    run = new_dir(stage / "run")
    fixture_path = stage / "fixture.json"
    write_new(fixture_path, fixture)
    reads = (
        [fixture["source_path"], fixture["memory_path"]]
        if role == "writer"
        else [fixture["memory_path"], fixture["question_path"]]
    )
    overlay = build_memory_patch(
        role=role,
        chain_id=manifest["chain_id"],
        session_id="composition-" + role + "-" + manifest["chain_id"],
        source_version=fixture["source_version"],
        read_files=reads,
        write_file=fixture["memory_path"] if role == "writer" else None,
    )
    patch_path = stage / "closed.patch.json"
    write_new(patch_path, overlay)
    metadata = {
        "task_id": f"dsh/memory/{manifest['chain_id']}/{role}",
        "task_version": "1",
        "split": "test",
        "environment_digest": manifest["environment_digest"],
        "verifier_id": VERIFIER_ID,
        "verifier_version": "1",
        "verifier_code_digest": bundle_digest(),
        "fixture_path": str(fixture_path),
        "fixture_sha256": sha(read_regular(fixture_path)),
    }
    config = {
        "name": "dsh_architecture",
        "sandbox": {"provider": "local", "runtime_timeout": 1800},
        "agent": {
            "name": "dsh",
            "model": {"max_total_tokens": 8192, "max_tokens_per_turn": 4096, "temperature": 0.0, "top_p": 1.0},
            "runner_python": manifest["runner_python"],
            "runner_module": "uni_agent.agents.dsh.runner",
            "profile": "sdk-minimal",
            "provider": "deepseek-official",
            "reasoning_effort": "off",
            "default_workdir": str(root),
            "dsh_home_root": str(run / "homes"),
            "artifact_root": str(run / "artifacts/traces"),
            "patches": [str(patch_path)],
            "keep_trace": True,
        },
        "verifier_command": [manifest["runner_python"], "-m", "examples.dsh.capabilities.memory_verifier"],
        "verifier_timeout": 60,
        "require_trace": True,
        "workdir": str(root),
        "result_root": str(run / "artifacts/results"),
        **{
            key: metadata[key]
            for key in ("environment_digest", "verifier_id", "verifier_version", "verifier_code_digest")
        },
    }
    config_path = stage / "task.yaml"
    write_new(config_path, yaml.safe_dump([config], sort_keys=False).encode())
    row = {
        "data_source": "dsh/memory-eval",
        "uid": manifest["chain_id"] + "-" + role,
        "agent_name": "task",
        "prompt": [{"role": "user", "content": prompt}],
        "extra_info": {"tools_kwargs": {"task": {"name": "dsh_architecture", "metadata": metadata}}},
    }
    sink = pa.BufferOutputStream()
    pq.write_table(pa.Table.from_pylist([row]), sink)
    data = stage / "eval.parquet"
    write_new(data, sink.getvalue().to_pybytes())
    argv = [
        manifest["runner_python"],
        "-m",
        "examples.inference.parallel_infer_verl",
        "--data-path",
        str(data),
        "--task-config",
        str(config_path),
        "--model-path",
        manifest["model_path"],
        "--n",
        "1",
        "--limit",
        "1",
        "--n-gpus-per-node",
        "1",
        "--tensor-parallel-size",
        "1",
        "--gateway-count",
        "1",
        "--concurrency",
        "1",
        "--gpu-memory-utilization",
        "0.6",
        "--tool-parser",
        "hermes",
        "--max-model-len",
        "16384",
        "--dsh-strict-audit",
        "--require-result",
        "--dsh-trace-root",
        str(run / "artifacts/traces"),
        "--dsh-result-root",
        str(run / "artifacts/results"),
        "--log-dir",
        str(run / "agent-logs"),
        "--result-path",
        str(run / "result.json"),
        "--inference-evidence-path",
        str(run / "inference-evidence.json"),
    ]
    write_new(stage / "inference.argv.json", argv)
    return {
        "chain_id": manifest["chain_id"],
        "role": role,
        "manifest_path": manifest["manifest_path"],
        "fixture_path": str(fixture_path),
        "metadata": metadata,
        "run_root": str(run),
        "argv_path": str(stage / "inference.argv.json"),
        "files": {
            str(p): sha(read_regular(p))
            for p in (fixture_path, patch_path, config_path, data, stage / "inference.argv.json")
        },
    }


def prepare_writer(
    *,
    output_dir,
    chain_id,
    family,
    runtime_executable,
    environment_digest,
    runner_python,
    model_path,
    checkpoint_identity,
):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", chain_id):
        raise ValueError("Invalid chain identity")
    runtime = Path(runtime_executable).absolute()
    if not os.access(runtime, os.X_OK) or runtime_digest(runtime) != environment_digest:
        raise ValueError("Pinned runtime mismatch")
    if not model_path or not checkpoint_identity or not Path(runner_python).is_file():
        raise ValueError("Explicit model/checkpoint/runner identities required")
    root = new_dir(output_dir)
    data = new_dir(root / "writer-data")
    fixture, raw = writer_fixture(data, chain_id, family)
    write_new(data / "source.json", raw)
    module_root = Path(__file__).resolve().parents[3]
    sources = [
        Path(__file__),
        Path(__file__).with_name("memory_tasks.py"),
        Path(__file__).with_name("memory_denial_budget.py"),
        Path(__file__).with_name("memory_verifier.py"),
        module_root / "examples/dsh/memory_closed/policy.mjs",
        module_root / "examples/dsh/memory_closed/profile.py",
        module_root / "uni_agent/agents/dsh/agent.py",
        module_root / "uni_agent/agents/dsh/runner.py",
        module_root / "uni_agent/tasks/dsh/task.py",
        module_root / "examples/inference/parallel_infer_verl.py",
        module_root / "deployment/services/harbor_training_supervisor.py",
        module_root / "deployment/versions/g1-source-lock.json",
        module_root / "deployment/versions/g1-deployment-lock.json",
    ]
    manifest = {
        "schema": "dsh.memory-chain-preparation.v1",
        "root": str(root),
        "chain_id": chain_id,
        "family": family,
        "training": False,
        "credit_assignment": "none",
        "checkpoint_identity": checkpoint_identity,
        "model_path": model_path,
        "environment_digest": environment_digest,
        "runtime_executable": str(runtime),
        "runner_python": str(runner_python),
        "verifier_bundle": bundle_digest(),
        "source_hashes": {str(p): sha(read_regular(p)) for p in sources},
        "manifest_path": str(root / "chain.json"),
    }
    manifest["writer"] = _stage(root, manifest, fixture, writer_prompt(fixture))
    write_new(root / "chain.json", manifest)
    return manifest


def _load_manifest(path):
    manifest = loads(read_regular(path))
    if manifest.get("schema") != "dsh.memory-chain-preparation.v1" or manifest.get("training") is not False:
        raise ValueError("Invalid memory chain manifest")
    if manifest["verifier_bundle"] != bundle_digest():
        raise ValueError("Verifier code changed")
    for name, expected in manifest["source_hashes"].items():
        if sha(read_regular(name)) != expected:
            raise ValueError("Preparation source changed")
    if runtime_digest(manifest["runtime_executable"]) != manifest["environment_digest"]:
        raise ValueError("Runtime changed")
    return manifest


def _stage_result(stage):
    for name, expected in stage["files"].items():
        if sha(read_regular(name)) != expected:
            raise ValueError("Stage input changed")
    run = Path(stage["run_root"])
    process = loads(read_regular(run / "process-exit.json"))
    if (
        process.get("exit_code") != 0
        or process.get("argv_sha256") != stage["files"][stage["argv_path"]]
        or process.get("chain_id") != stage["chain_id"]
        or process.get("role") != stage["role"]
        or process.get("run_root") != str(run)
        or process.get("manifest_sha256") != sha(read_regular(stage["manifest_path"]))
        or process.get("supervisor_sha256") != sha(read_regular(run / "supervision/supervisor-result.json"))
    ):
        raise ValueError("Stage process did not exit cleanly with pinned command")
    inference = loads(read_regular(run / "inference-evidence.json"))
    if inference.get("status") != "completed" or len(inference.get("samples", [])) != 1:
        raise ValueError("Inference did not complete one sample")
    sample = inference["samples"][0]
    if sample["metadata"] != stage["metadata"]:
        raise ValueError("Inference sample identity mismatch")
    paths = list((run / "artifacts/results").glob("*/verifier-receipt.json"))
    if len(paths) != 1:
        raise ValueError("Expected one independent receipt")
    receipt = loads(read_regular(paths[0]))
    body = {key: value for key, value in receipt.items() if key != "receipt_id"}
    if receipt["receipt_id"] != sha(canonical(body)):
        raise ValueError("Receipt hash mismatch")
    envelope_raw = read_regular(paths[0].with_name("agent-result.json"), 8_000_000)
    envelope = loads(envelope_raw)
    metadata = stage["metadata"]
    dsh = envelope["dsh"]
    if (
        receipt.get("schema") != "dsh.verifier-receipt.v1"
        or receipt.get("issuer") != {"kind": "trusted-verifier", "id": "uni-agent-dsh"}
        or envelope.get("schema") != "dsh.uni-agent.task-result.v1"
        or envelope["metadata"] != metadata
        or receipt["artifact_sha256"] != sha(envelope_raw)
        or receipt["dsh_session_id"] != dsh["dsh_session_id"]
        or dsh["dsh_session_id"] != "dsh-" + dsh["gateway_session_id"]
        or receipt["trace_sha256"] != dsh["trace_sha256"]
        or receipt["task_id"] != metadata["task_id"]
        or receipt["task_version"] != "1"
        or receipt["environment_digest"] != metadata["environment_digest"]
        or receipt["verifier"] != {"id": VERIFIER_ID, "version": "1", "code_digest": bundle_digest()}
        or receipt.get("fresh") is not True
    ):
        raise ValueError("Receipt/envelope identity mismatch")
    started, issued, ended = [
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        for value in (inference["started_at"], receipt["issued_at"], inference["finished_at"])
    ]
    if not (started.tzinfo and issued.tzinfo and ended.tzinfo and started <= issued <= ended):
        raise ValueError("Receipt not fresh within this inference")
    trace_path = Path(dsh["trace_path"])
    if not trace_path.is_relative_to(run / "artifacts/traces"):
        raise ValueError("Trace not under independent run")
    trace_raw = read_regular(trace_path, 32_000_000)
    if sha(trace_raw) != receipt["trace_sha256"]:
        raise ValueError("Trace changed")
    events = [loads(line) for line in trace_raw.splitlines() if line.strip()]
    fixture = loads(read_regular(stage["fixture_path"]))
    result = score(fixture, events, envelope["response"], envelope["finished"], dsh["dsh_session_id"])
    if stage["metadata"]["fixture_sha256"] not in receipt.get("evidence", []) or dsh["trace_sha256"] not in receipt.get(
        "evidence", []
    ):
        raise ValueError("Receipt missing fixture/trace evidence")
    if any(receipt.get(key) != result[key] for key in ("reward", "accuracy", "eligible", "finished")):
        raise ValueError("Independent rescore mismatch")
    readback = inference["readback"]
    if (
        readback["scores"] != [result["reward"]]
        or readback["uid_status"] != {sample["uid"]: "finished"}
        or len(readback["final_keys"]) != 1
        or readback["final_keys"][0].rsplit("_", 2)[:2] != [sample["uid"], "0"]
    ):
        raise ValueError("Inference readback mismatch")
    if receipt.get("eligible") is not True or receipt.get("finished") is not True:
        raise ValueError("Stage is unfinished or ineligible")
    return receipt, envelope, result, fixture


def admit_writer_and_freeze(manifest_path):
    manifest = _load_manifest(manifest_path)
    root = Path(manifest["root"])
    if (root / "frozen").exists() or (root / "reader").exists():
        raise ValueError("Chain transition cannot be reused")
    receipt, envelope, result, fixture = _stage_result(manifest["writer"])
    if result["reward"] != 1:
        raise ValueError("Writer failed quality gate; do not freeze")
    frozen = freeze_memory_artifact(
        source_root=Path(fixture["memory_path"]).parent,
        relative_path=Path(fixture["memory_path"]).name,
        expected_source_sha256=result["extra_info"]["memory_sha256"],
        source_version=fixture["source_version"],
        chain_id=manifest["chain_id"],
        writer_session_id=receipt["dsh_session_id"],
        max_bytes=fixture["max_bytes"],
        output_dir=root / "frozen",
    )
    question = root / "reader-question.txt"
    write_new(
        question, b"What are the current deployment region and forbidden action? Include the saved source_version.\n"
    )
    binding = {
        "dsh_session_id": receipt["dsh_session_id"],
        "gateway_session_id": envelope["dsh"]["gateway_session_id"],
        "receipt_id": receipt["receipt_id"],
        "trace_sha256": receipt["trace_sha256"],
        "manifest_sha256": frozen.manifest_sha256,
        "content_sha256": frozen.content_sha256,
    }
    reader = {
        "schema": "dsh.memory-stage.v1",
        "role": "reader",
        "chain_id": manifest["chain_id"],
        "family": fixture["family"],
        "source_version": fixture["source_version"],
        "writer_binding": binding,
        "frozen_dir": str(root / "frozen"),
        "memory_path": str(root / "frozen/memory.bin"),
        "question_path": str(question),
        "question_sha256": sha(read_regular(question)),
        "max_bytes": fixture["max_bytes"],
        "expected_answer": {"status": "answer", **fixture["expected_memory"]},
    }
    stage = _stage(root, manifest, reader, reader_prompt(reader))
    write_new(root / "reader-stage.json", stage)
    return stage


def finalize_chain(manifest_path):
    manifest = _load_manifest(manifest_path)
    root = Path(manifest["root"])
    a, ae, _, _ = _stage_result(manifest["writer"])
    stage = loads(read_regular(root / "reader-stage.json"))
    b, be, result, fixture = _stage_result(stage)
    binding = fixture["writer_binding"]
    if (
        binding["receipt_id"] != a["receipt_id"]
        or binding["trace_sha256"] != a["trace_sha256"]
        or binding["dsh_session_id"] != a["dsh_session_id"]
    ):
        raise ValueError("Reader is bound to a different writer")
    if ae["dsh"]["gateway_session_id"] == be["dsh"]["gateway_session_id"]:
        raise ValueError("Reader reused writer gateway")
    report = {
        "schema": "dsh.memory-chain-evaluation.v1",
        "chain_id": manifest["chain_id"],
        "training": False,
        "credit_assignment": "none",
        "checkpoint_identity": manifest["checkpoint_identity"],
        "model_path": manifest["model_path"],
        "environment_digest": manifest["environment_digest"],
        "writer": binding,
        "reader": {
            "dsh_session_id": b["dsh_session_id"],
            "gateway_session_id": be["dsh"]["gateway_session_id"],
            "receipt_id": b["receipt_id"],
            "trace_sha256": b["trace_sha256"],
        },
        "reward": result["reward"],
        "status": "passed" if result["reward"] == 1 else "reader_failed_quality",
        "scope": "one diagnostic chain, not capability improvement",
    }
    write_new(root / "chain-result.json", report)
    return report


def run_stage(manifest_path, role):
    """Explicit operator entry: executes inference only and records its process exit."""
    manifest = _load_manifest(manifest_path)
    root = Path(manifest["root"])
    stage = manifest["writer"] if role == "writer" else loads(read_regular(root / "reader-stage.json"))
    for name, expected in stage["files"].items():
        if sha(read_regular(name)) != expected:
            raise ValueError("Stage input changed before launch")
    run = Path(stage["run_root"])
    if any(run.iterdir()):
        raise ValueError("Stage run directory must be empty; no retry/reuse")
    argv = loads(read_regular(stage["argv_path"]))
    repository = Path(__file__).resolve().parents[3]
    env = {**os.environ, "DSH_RUNTIME_MODE": "exe", "PYTHONPATH": f"{repository}:{repository / 'verl'}"}
    probe = subprocess.run(
        [
            manifest["runner_python"],
            "-c",
            "import json; from importlib.metadata import version; "
            "from deepseek_harness_runtime import resolve_bundled_launch_args; "
            "print(json.dumps([resolve_bundled_launch_args()[0],version('deepseek-harness-sdk'),"
            "version('deepseek-harness-runtime-bin')]))",
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
        env=env,
        cwd=repository,
    )
    if loads(probe.stdout) != [manifest["runtime_executable"], "0.1.3a2", "0.1.3a2"]:
        raise ValueError("Runner SDK/runtime does not match pin")
    started = datetime.now(timezone.utc).isoformat()
    supervision = new_dir(run / "supervision")
    result = supervise(argv, repository, env, supervision, denial_health(run), wall_seconds=1800, interval=2, grace=30)
    report = {
        "exit_code": result["exit_code"],
        "chain_id": stage["chain_id"],
        "role": role,
        "run_root": str(run),
        "manifest_sha256": sha(read_regular(stage["manifest_path"])),
        "supervisor_sha256": sha(read_regular(supervision / "supervisor-result.json")),
        "repeated_policy_denial_limit": 3,
        "wall_seconds": 1800,
        "termination_grace_seconds": 30,
        "argv_sha256": stage["files"][stage["argv_path"]],
        "started_at": started,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "training": False,
        "checkpoint_identity": manifest["checkpoint_identity"],
    }
    write_new(run / "process-exit.json", report)
    if result["exit_code"]:
        raise RuntimeError("Inference failed; see private stage supervision/train.log")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare-writer")
    for name in (
        "output-dir",
        "chain-id",
        "family",
        "runtime-executable",
        "environment-digest",
        "runner-python",
        "model-path",
        "checkpoint-identity",
    ):
        prep.add_argument("--" + name, required=True)
    for command in ("freeze-and-prepare-reader", "finalize"):
        sub.add_parser(command).add_argument("--manifest", type=Path, required=True)
    launch = sub.add_parser("run-stage")
    launch.add_argument("--manifest", type=Path, required=True)
    launch.add_argument("--role", choices=["writer", "reader"], required=True)
    args = vars(parser.parse_args())
    command = args.pop("command")
    if command == "prepare-writer":
        result = prepare_writer(**args)
    elif command == "run-stage":
        result = run_stage(args["manifest"], args["role"])
    elif command == "freeze-and-prepare-reader":
        result = admit_writer_and_freeze(args["manifest"])
    else:
        result = finalize_chain(args["manifest"])
    print(json.dumps(result, allow_nan=False, indent=2))


if __name__ == "__main__":
    main()
