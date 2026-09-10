"""Bounded, paired reader diagnostics. Never submits trajectories to training."""


def diagnostic_schedule():
    schedule = []
    for repetition in range(4):
        order = ("original", "revised") if repetition % 2 == 0 else ("revised", "original")
        for variant in order:
            schedule.append(dict(branch_id=f"b{len(schedule):03d}", variant=variant, repetition=repetition))
    return schedule


def summarize_pairs(tasks, *, planned_tasks):
    if len({t["task_id"] for t in tasks}) != len(tasks) or not 0 <= len(tasks) <= planned_tasks:
        raise ValueError("Duplicate tasks or invalid planned denominator")
    expected = {(s["variant"], s["repetition"]) for s in diagnostic_schedule()}
    paired = []
    for task in tasks:
        keys = [(r["variant"], r["repetition"]) for r in task["readers"]]
        if len(keys) != len(set(keys)) or not set(keys) <= expected:
            raise ValueError("Duplicate or invalid reader repetition")
        if task["writer"]["eligible"] and set(keys) == expected:
            paired.append(task)
    variants = {}
    for variant in ("original", "revised"):
        successes = sum(
            r["eligible"] and r["finished"] and r["reward"] == 1
            for task in paired
            for r in task["readers"]
            if r["variant"] == variant
        )
        variants[variant] = dict(
            successes=successes,
            conditional_success_rate=successes / (4 * len(paired)) if paired else None,
            end_to_end_success_rate=successes / (4 * planned_tasks)
            if planned_tasks
            and len(tasks) == planned_tasks
            and all(not t["writer"]["eligible"] or len(t["readers"]) == 8 for t in tasks)
            else None,
        )
    return dict(
        planned_tasks=planned_tasks,
        observed_tasks=len(tasks),
        paired_tasks=len(paired),
        writer_rejected_tasks=sum(not t["writer"]["eligible"] for t in tasks),
        variants=variants,
        task_paired_difference=(
            variants["revised"]["conditional_success_rate"] - variants["original"]["conditional_success_rate"]
        )
        if paired
        else None,
        training_consumed=False,
        learning_verified=False,
        limitation=(
            "Conditional rates require all eight B outcomes; unfinished task pairs are not evidence of zero ability."
        ),
    )


async def run_diagnostic(operator, *, run_id, task_ids, execute, report_path):
    """Run one A then eight B per task via an injected real stage executor.

    There is intentionally no training/framework.generate_sequences entry here.
    Evidence failure aborts; trustworthy rejected A is recorded without a fake B.
    """
    import asyncio
    import json
    from pathlib import Path
    from uuid import uuid4

    from examples.dsh.capabilities.memory_training_stage import GroupContext, _name
    from examples.dsh.capabilities.reader_diagnostic_evidence import audit_diagnostic_stage
    from examples.dsh.capabilities.work_state.stage import (
        freeze_writer_memory,
        prepare_reader_branch,
        prepare_writer_stage,
    )

    _name(run_id)
    if not task_ids or len(task_ids) != len(set(task_ids)):
        raise ValueError("Task identities must be unique and nonempty")
    report_path = Path(report_path)
    report = dict(
        schema="dsh.core-reader-diagnostic.v1",
        run_id=run_id,
        status="running",
        tasks=[],
        planned_task_ids=list(task_ids),
        training_consumed=False,
    )
    with report_path.open("x") as stream:
        json.dump(report, stream)

    def persist():
        report["summary"] = summarize_pairs(report["tasks"], planned_tasks=len(task_ids))
        temporary = report_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
        temporary.replace(report_path)

    try:
        for task_id in task_ids:
            fields = {"tools_kwargs": {"task": {"metadata": {"work_state_task_id": task_id}}}}
            context = GroupContext(run_id, "val", "pair-" + uuid4().hex, 0, 0)
            writer = prepare_writer_stage(
                operator,
                context,
                chain_id="memory-" + uuid4().hex,
                gateway_session_id="memory-A-" + uuid4().hex,
                sample_fields=fields,
            )
            execution = await execute(writer)
            audit = audit_diagnostic_stage(writer, execution)
            task = dict(task_id=task_id, writer_session_id=writer.gateway_session_id, writer=audit, readers=[])
            report["tasks"].append(task)
            persist()
            if not audit["eligible"] or not audit["finished"]:
                continue
            frozen = freeze_writer_memory(writer, execution)
            task["frozen_content_sha256"] = frozen.artifact.content_sha256
            for item in diagnostic_schedule():
                reader = prepare_reader_branch(
                    writer,
                    frozen,
                    reader_gateway_session_id="memory-B-" + uuid4().hex,
                    branch_id=item["branch_id"],
                    prompt_variant=item["variant"],
                )
                execution = await execute(reader)
                result = audit_diagnostic_stage(reader, execution)
                task["readers"].append(
                    {
                        **item,
                        **result,
                        "gateway_session_id": reader.gateway_session_id,
                        "bundle_sha256": frozen.artifact.content_sha256,
                    }
                )
                persist()
        report["status"] = "complete"
    except (Exception, asyncio.CancelledError) as exc:
        report["status"] = "aborted"
        report["error_type"] = type(exc).__name__
        # Do not serialize arbitrary exception text that might contain credentials.
        raise
    finally:
        persist()
    return report


def _sha_file(path):
    import hashlib

    with open(path, "rb") as stream:
        digest = hashlib.sha256()
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def _repository():
    from pathlib import Path

    return Path(__file__).resolve().parents[3]


def _head():
    import subprocess

    return subprocess.check_output(["git", "-C", str(_repository()), "rev-parse", "HEAD"], text=True).strip()


def prepare(*, root, model_path, model_revision, runtime_executable, runner_python, cuda_visible_devices, canary=False):
    import json
    import re
    from pathlib import Path

    if not re.fullmatch(r"[0-9a-f]{40}", model_revision):
        raise ValueError("Model revision must be a full SHA")
    if not re.fullmatch(r"(?:[0-9]+|MIG-[A-Za-z0-9-]+)", cuda_visible_devices):
        raise ValueError("Select exactly one GPU or MIG device explicitly")
    root, model_path = Path(root).absolute(), Path(model_path).resolve()
    runtime, runner = Path(runtime_executable).absolute(), Path(runner_python).absolute()
    repo = _repository()
    dataset = repo / "examples/dsh/data/work-state-memory-core-v1/task-index.json"
    data = json.loads(dataset.read_text())
    ids = [
        f"work-state-memory-core-v1-{family.lower()}-v1-s{seed}"
        for family in ("WS01", "WS03", "WS05", "WS06")
        for seed in range(2001, 2005)
    ]
    if canary:
        ids = ids[:1]
    rows = {identity: data["tasks"][identity] for identity in ids}
    if any(
        row["split"] != "validation" or row.get("generation") != "work-state-memory-core-v1" for row in rows.values()
    ):
        raise ValueError("Diagnostic tasks must be public core development tasks")
    model_files = sorted(p for p in model_path.rglob("*") if p.is_file())
    if not (model_path / "config.json").is_file() or not any(p.suffix == ".safetensors" for p in model_files):
        raise ValueError("Local model config and safetensors required")
    sources = list((repo / "uni_agent").rglob("*.py"))
    sources += [p for p in (repo / "examples/dsh/capabilities").rglob("*") if p.suffix in (".py", ".mjs")]
    sources += [
        repo / "examples/gateway/debug_launcher.py",
        repo / "deployment/versions/g1-deployment-lock.json",
        dataset,
    ]
    hashes = {str(p): _sha_file(p) for p in [*sources, *model_files, runtime, runner]}
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    task_manifest = root / "task-index.json"
    task_manifest.write_text(json.dumps({"schema": data["schema"], "tasks": rows}, indent=2) + "\n")
    hashes[str(task_manifest)] = _sha_file(task_manifest)
    manifest = dict(
        schema="dsh.core-reader-preparation.v1",
        root=str(root),
        repository_root=str(repo),
        integration_head=_head(),
        model_path=str(model_path),
        model_revision=model_revision,
        model_name="Qwen/Qwen3-4B",
        runtime_executable=str(runtime),
        runner_python=str(runner),
        cuda_visible_devices=cuda_visible_devices,
        environment_digest=hashes[str(runtime)],
        task_manifest=str(task_manifest),
        task_ids=ids,
        files=hashes,
        training=False,
        stage_timeout_seconds=1800,
        scope="public-canary" if canary else "public-development",
        model_files=[str(p) for p in model_files],
        sampling={"temperature": 0.7, "top_p": 0.9, "max_tokens": 4096},
        max_generated_tokens=8192,
    )
    path = root / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    path.with_suffix(".sha256").write_text(_sha_file(path) + "\n")
    return path


def check(path):
    import json
    from pathlib import Path

    path = Path(path).absolute()
    if path.with_suffix(".sha256").read_text().strip() != _sha_file(path):
        raise ValueError("Prepared manifest changed")
    manifest = json.loads(path.read_text())
    if path != Path(manifest["root"]) / "manifest.json":
        raise ValueError("Prepared manifest moved")
    model_files = sorted(str(p) for p in Path(manifest["model_path"]).rglob("*") if p.is_file())
    if model_files != manifest["model_files"]:
        raise ValueError("Prepared model file inventory changed")
    if manifest["schema"] != "dsh.core-reader-preparation.v1" or manifest["integration_head"] != _head():
        raise ValueError("Diagnostic schema or checkout changed")
    if manifest["repository_root"] != str(_repository()) or manifest["training"] is not False:
        raise ValueError("Diagnostic checkout/scope changed")
    for name, expected in manifest["files"].items():
        if _sha_file(name) != expected:
            raise ValueError("Prepared source/input changed: " + name)
    if (
        manifest["sampling"] != {"temperature": 0.7, "top_p": 0.9, "max_tokens": 4096}
        or manifest["max_generated_tokens"] != 8192
    ):
        raise ValueError("Diagnostic sampling contract changed")
    return manifest


def check_execution_environment(manifest):
    """Check actual inline runner imports and installed executable before any GPU launch."""
    import json
    import os
    import subprocess
    import sys
    from pathlib import Path

    from deployment.checks.verl_source_overlay import verify_verl_source

    repo = _repository()
    lock = json.loads((repo / "deployment/versions/g1-deployment-lock.json").read_text())
    if manifest["environment_digest"] != lock["dsh"]["runtime_binary_sha256"]:
        raise ValueError("Runtime binary does not match deployment pin")
    if manifest["model_revision"] != lock["student"]["revision"]:
        raise ValueError("Model revision does not match deployment pin")
    if Path(sys.executable).absolute() != Path(manifest["runner_python"]).absolute():
        raise ValueError("Run this command with the prepared runner Python")
    if os.environ.get("DSH_RUNTIME_MODE") != "exe":
        raise ValueError("Launch with DSH_RUNTIME_MODE=exe so actual DSH children inherit it")
    raw_search = [Path(p) for p in os.environ.get("PYTHONPATH", "").split(os.pathsep) if p]
    if any(not p.is_absolute() for p in raw_search):
        raise ValueError("PYTHONPATH entries must be absolute for DSH branch working directories")
    search = [p.resolve() for p in raw_search]
    if not all(p in search for p in (repo, repo / "verl")):
        raise ValueError("PYTHONPATH must contain absolute checkout and paired verl paths")
    probe = subprocess.run(
        [
            manifest["runner_python"],
            "-c",
            "import json; from importlib.metadata import version; "
            "from deepseek_harness_runtime import resolve_bundled_launch_args; "
            "import uni_agent, verl; print(json.dumps({"
            "'runtime':resolve_bundled_launch_args()[0],"
            "'sdk':version('deepseek-harness-sdk'),"
            "'runtime_version':version('deepseek-harness-runtime-bin'),"
            "'uni_agent':uni_agent.__file__, 'verl':verl.__file__}))",
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    identity = json.loads(probe.stdout)
    if identity != {
        "runtime": manifest["runtime_executable"],
        "sdk": "0.1.3a2",
        "runtime_version": "0.1.3a2",
        "uni_agent": str(repo / "uni_agent/__init__.py"),
        "verl": str(repo / "verl/verl/__init__.py"),
    }:
        raise ValueError("Actual SDK/runtime or imported checkout differs from pin")
    identity["verl_effective_source"] = verify_verl_source(repo / "verl")
    return identity


def launch(path):
    import asyncio
    import json
    from datetime import datetime, timezone
    from pathlib import Path

    from examples.dsh.capabilities.prepare_memory_training import check_gpu_available

    manifest = check(path)
    identity = check_execution_environment(manifest)
    admission = check_gpu_available()
    root = Path(manifest["root"])
    # Only launch reserves execution directories. Prepare/check never consume them.
    execution_path = root / "execution.json"
    execution = dict(
        status="running",
        started_at=datetime.now(timezone.utc).isoformat(),
        identity=identity,
        gpu_admission=admission,
        manifest_sha256=_sha_file(path),
    )
    with execution_path.open("x") as stream:
        json.dump(execution, stream, indent=2)

    async def run():
        from examples.dsh.capabilities.reader_diagnostic_runtime import open_executor
        from examples.dsh.capabilities.work_state.stage import WorkStateOperator

        chains = root / "chains"
        chains.mkdir(mode=0o700)
        operator = WorkStateOperator(
            chains,
            Path(manifest["runner_python"]),
            Path(manifest["runtime_executable"]),
            manifest["environment_digest"],
            manifest["model_revision"],
            "work-state-v1",
            Path(manifest["task_manifest"]),
            manifest["files"][manifest["task_manifest"]],
            8192,
        )
        async with open_executor(manifest) as execute:
            return await run_diagnostic(
                operator,
                run_id=root.name,
                task_ids=manifest["task_ids"],
                execute=execute,
                report_path=root / "report.json",
            )

    try:
        result = asyncio.run(run())
        # Catch drift during execution too; never call a drifted experiment complete.
        check(path)
        execution["status"] = "complete"
        return result
    except BaseException as exc:
        execution["status"] = "aborted"
        execution["error_type"] = type(exc).__name__
        raise
    finally:
        execution["ended_at"] = datetime.now(timezone.utc).isoformat()
        temporary = execution_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(execution, indent=2) + "\n")
        temporary.replace(execution_path)


def main(argv=None):
    import argparse
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    pre = sub.add_parser("prepare", help="Freeze local inputs; no model launch")
    for key in ("root", "model-path", "model-revision", "runtime-executable", "runner-python", "cuda-visible-devices"):
        pre.add_argument("--" + key, required=True)
    pre.add_argument(
        "--canary", action="store_true", help="One public development task, separate from formal comparison"
    )
    for command in ("check", "run"):
        sub.add_parser(command).add_argument("--manifest", required=True)
    args = vars(parser.parse_args(argv))
    command = args.pop("command")
    if command == "prepare":
        print(prepare(**args))
    elif command == "check":
        manifest = check(args["manifest"])
        print(json.dumps(dict(status="inputs-unchanged", task_count=len(manifest["task_ids"]), gpu_started=False)))
    else:
        print(json.dumps(launch(args["manifest"])["summary"], indent=2))


if __name__ == "__main__":
    main()
