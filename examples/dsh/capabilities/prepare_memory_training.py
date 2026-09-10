"""Prepare/check/launch one fixed diagnostic memory family with the existing sync trainer."""

import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import yaml

ROOT = Path(__file__).resolve().parents[3]
AF = "actor_rollout_ref.rollout.custom.agent_framework."


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return "sha256:" + value.hexdigest()


def checkpoint_origin(resume_from, mother_run, *, family, model_revision, runtime_sha, verl_head, course_id=None):
    course_id = _resolve_course(family, course_id)
    checkpoint, mother = Path(resume_from), Path(mother_run)
    if not checkpoint.is_absolute() or not mother.is_absolute():
        raise ValueError("Checkpoint and mother run must be absolute")
    match = re.fullmatch(r"global_step_(0|[1-9][0-9]*)", checkpoint.name)
    if not match or checkpoint.resolve() != checkpoint or mother.resolve() != mother:
        raise ValueError("Invalid canonical checkpoint path")
    run_file, plan_file = mother / "run-manifest.json", mother / "memory-launch-plan.json"
    run, plan = json.loads(run_file.read_text()), json.loads(plan_file.read_text())
    dataset = Path(run["paths"]["dataset_manifest"])
    if (
        run.get("status") != "completed"
        or run.get("exit_code") != 0
        or run.get("run_root") != str(mother)
        or plan.get("mode") != "train"
        or plan["environment"]["RUN_ROOT"] != str(mother)
        or checkpoint.parent != Path(plan["environment"]["CKPTS_DIR"])
        or run.get("uni_agent_sha") != plan["integration_head"]
        or not re.fullmatch(r"[0-9a-f]{40}", plan["integration_head"])
        or run.get("verl_sha") != plan["verl_head"]
        or plan["verl_head"] != verl_head
        or plan.get("verl_effective_source") != verl_source_identity()
        or run.get("verl_effective_source") != plan.get("verl_effective_source")
        or plan["model_revision_declared"] != model_revision
        or plan["runtime"]["sha256"] != runtime_sha
        or f'++{AF}memory_operator.family="{family}"' not in plan["command"]
        or digest(dataset) != run["sha256"]["dataset_manifest"]
        or json.loads(dataset.read_text()) != plan
    ):
        raise ValueError("Mother evidence/config does not bind this checkpoint")
    if _resolve_course(family, plan.get("course_id")) != course_id:
        raise ValueError("Mother course does not match requested course")
    required = [checkpoint / "actor" / f"{name}_world_size_1_rank_0.pt" for name in ("model", "optim", "extra_state")]
    if any(not p.is_file() or p.is_symlink() for p in required):
        raise ValueError("Missing regular model/optimizer/extra checkpoint")
    paths = sorted(checkpoint.rglob("*"))
    if any(p.is_symlink() for p in paths):
        raise ValueError("Checkpoint symlinks are not supported")
    files = {
        str(p.relative_to(checkpoint)): dict(sha256=digest(p), size=p.stat().st_size) for p in paths if p.is_file()
    }
    body = dict(
        schema="dsh.memory-checkpoint-origin.v1",
        course_id=course_id,
        mother_run=str(mother),
        mother_source_head=plan["integration_head"],
        verl_effective_source=plan["verl_effective_source"],
        checkpoint_path=str(checkpoint),
        step=int(match[1]),
        evidence={str(p): digest(p) for p in (run_file, plan_file, dataset)},
        files=files,
    )
    identity = "sha256:" + hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {**body, "identity": identity}


def revision(root):
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()


def deployment_lock():
    return json.loads((ROOT / "deployment/versions/g1-deployment-lock.json").read_text())


def verl_source_identity():
    from deployment.checks.verl_source_overlay import verify_verl_source

    return verify_verl_source(ROOT / "verl", require_patched=True)


def runtime_probe(python, runtime):
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONHOME", "PYTHONPATH", "RAY_ADDRESS")}
    env["CUDA_VISIBLE_DEVICES"] = ""
    probe = subprocess.run(
        [
            str(python),
            "-c",
            "import json;from importlib.metadata import version;"
            "from deepseek_harness_runtime import bundled_runtime_path;"
            "print(json.dumps(dict(path=str(bundled_runtime_path()),"
            "sdk=version('deepseek-harness-sdk'),runtime=version('deepseek-harness-runtime-bin'))))",
        ],
        cwd="/tmp",
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    installed = json.loads(probe.stdout)
    if Path(installed["path"]).resolve() != runtime or any(installed[k] != "0.1.3a2" for k in ("sdk", "runtime")):
        raise ValueError("Requires selected SDK/runtime 0.1.3a2")
    return installed


COURSES = ("work-state-v1", "work-state-short-fact-v1", "work-state-memory-core-v1")


def _resolve_course(family, course_id):
    if family == "work-state-v1":
        resolved = "work-state-v1" if course_id is None else course_id
        if resolved not in COURSES:
            raise ValueError("Unknown work-state course")
        return resolved
    if family not in ("constraints", "updates") or course_id is not None:
        raise ValueError("Explicit course is only supported for work-state family")
    return None


def _task_from_row(row):
    from examples.dsh.capabilities.work_state.tasks import make_task

    if "generation" not in row:
        return make_task(row["family"], row["variant"], row["seed"])
    if row["generation"] != "work-state-memory-core-v1":
        raise ValueError("Unknown task generation")
    from examples.dsh.capabilities.work_state.core_tasks import make_core_task

    return make_core_task(row["family"], row["variant"], row["seed"])


def _core_artifacts(dataset):
    full = {key: _task_from_row(row) for key, row in dataset["tasks"].items()}
    visible = {
        key: {field: task[field] for field in ("writer_files", "reader_files", "writer_goal", "reader_goal")}
        for key, task in full.items()
    }
    return {"controller-tasks.json": full, "model-visible-inputs.json": visible}


def _course_coverage(dataset, course_id, evaluation_ids=None):
    structures = {"train": set(), "validation": set()}
    visible = {"train": set(), "validation": set()}
    values = {"train": set(), "validation": set()}
    for task_id, row in dataset["tasks"].items():
        split = row["split"]
        if split == "validation" and evaluation_ids is not None and task_id not in evaluation_ids:
            continue
        task = _task_from_row(row)
        structures[split].add((row["family"], row["variant"]))
        observed = {name: task[name] for name in ("writer_files", "reader_files")}
        visible[split].add(hashlib.sha256(json.dumps(observed, sort_keys=True).encode()).hexdigest())
        if course_id == "work-state-short-fact-v1":
            values[split].add(task["truth"]["expected_config"]["capacity"])
    coverage = dict(
        family_count=len({row["family"] for row in dataset["tasks"].values()}),
        structures={k: len(v) for k, v in structures.items()},
        distinct_visible_inputs={k: len(v) for k, v in visible.items()},
        visibility="public-development-not-sealed",
        note="Seed or task ID multiplicity is not structural diversity.",
    )
    if course_id == "work-state-short-fact-v1":
        coverage["distinct_fact_values"] = {k: len(v) for k, v in values.items()}
    return coverage


def _dataset_for_course(course_id):
    if course_id == "work-state-v1":
        schedule = [
            (family, variant, seed, split)
            for family in ("WS01", "WS03", "WS05", "WS06")
            for variant, seed, split in ((0, 101, "train"), (0, 202, "train"), (1, 303, "validation"))
        ]
    elif course_id == "work-state-short-fact-v1":
        schedule = [("WS07", 0, seed, "train") for seed in range(101, 109)] + [
            ("WS07", 1, seed, "validation") for seed in (901, 902)
        ]
    elif course_id == "work-state-memory-core-v1":
        # Seed-major ordering keeps the bounded diagnostic prefix interleaved.
        schedule = [
            (family, 0, seed, "train")
            for seed in range(1001, 1161)
            for family in ("WS01", "WS03", "WS05", "WS06")
            if family != "WS06" or seed <= 1040
        ] + [
            (family, 1, seed, "validation") for seed in range(2001, 2041) for family in ("WS01", "WS03", "WS05", "WS06")
        ]
    else:
        raise ValueError("Unknown dataset course")
    rows = {}
    for family, variant, seed, split in schedule:
        row = dict(family=family, variant=variant, seed=seed, split=split)
        if course_id == "work-state-memory-core-v1":
            row["generation"] = course_id
        task = _task_from_row(row)
        rows[task["task_id"]] = row
    dataset = dict(schema="dsh.work-state-dataset.v1", tasks=rows)
    return dataset, _course_coverage(dataset, course_id)


def _work_state_dataset():
    return _dataset_for_course("work-state-v1")


def _evaluation_ids(dataset, requested, mode):
    available = [key for key, value in dataset["tasks"].items() if value["split"] == "validation"] if dataset else []
    if requested is None:
        return available
    if (
        mode not in ("val", "reload")
        or dataset is None
        or not isinstance(requested, list)
        or not requested
        or any(not isinstance(key, str) or key not in available for key in requested)
        or len(requested) != len(set(requested))
    ):
        raise ValueError("Invalid evaluation task selection; requires unique validation IDs in work-state val/reload")
    return list(requested)


def _task_rows(run_id, family, split, identities, work_state):
    rows = []
    for identity in identities:
        metadata = (
            dict(work_state_task_id=identity) if work_state else dict(family=family, split=split, diagnostic_only=True)
        )
        rows.append(
            dict(
                data_source="dsh/work-state/v1" if work_state else "dsh/memory-fixed-diagnostic/" + family,
                uid=run_id + "-" + identity,
                agent_name="task",
                prompt=[dict(role="user", content="Execute the trusted memory chain.")],
                extra_info=dict(tools_kwargs=dict(task=dict(name="dsh_architecture", metadata=metadata))),
            )
        )
    return rows


def _selection_body(run_id, mode, requested, resolved, task_hash):
    return dict(
        schema="dsh.work-state-evaluation-selection.v1",
        run_id=run_id,
        mode=mode,
        task_manifest_sha256=task_hash,
        requested_task_ids=requested,
        resolved_task_ids=resolved,
    )


def prepare(
    *,
    output_dir,
    run_root,
    run_id,
    runtime_executable,
    runner_python,
    model_path,
    model_revision,
    family="constraints",
    mode="val",
    resume_from=None,
    mother_run=None,
    evaluation_task_ids=None,
    course_id=None,
):
    if mode not in ("val", "train", "reload") or family not in ("constraints", "updates", "work-state-v1"):
        raise ValueError("Only val/train/reload and fixed diagnostic families are supported")
    work_state = family == "work-state-v1"
    course_id = _resolve_course(family, course_id)
    dataset, coverage = _dataset_for_course(course_id) if work_state else (None, None)
    evaluation_ids = _evaluation_ids(dataset, evaluation_task_ids, mode)
    if work_state:
        coverage = _course_coverage(dataset, course_id, evaluation_ids)
    if (mode == "reload" and (not resume_from or not mother_run)) or (
        mode != "reload" and (resume_from is not None or mother_run is not None)
    ):
        raise ValueError("Reload requires resume_from and mother_run; other modes forbid them")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,59}", run_id):
        raise ValueError("Invalid run identity")
    if not re.fullmatch(r"[0-9a-f]{40}", model_revision):
        raise ValueError("Model revision must be an explicit commit identity")
    output, run = Path(output_dir).absolute(), Path(run_root).absolute()
    runtime, python, model = (
        Path(runtime_executable).resolve(),
        Path(runner_python).absolute(),
        Path(model_path).resolve(),
    )
    checkpoint = Path("/workspace/uni-agent-g1/checkpoint") / run_id
    ray = Path("/tmp") / ("dsh-m-" + hashlib.sha256(run_id.encode()).hexdigest()[:12])
    for path in (output, run, checkpoint, ray):
        if path.exists() or path.is_symlink():
            raise ValueError("Requires new private paths")
    if run.resolve().is_relative_to(output.resolve()) or output.resolve().is_relative_to(run.resolve()):
        raise ValueError("Output and run must be independent")
    lock = deployment_lock()
    if model_revision != lock["student"]["revision"]:
        raise ValueError("Student revision must match deployment lock")
    if not os.access(runtime, os.X_OK) or digest(runtime) != lock["dsh"]["runtime_binary_sha256"]:
        raise ValueError("Runtime pin mismatch")
    head, verl_head = revision(ROOT), revision(ROOT / "verl")
    if verl_head != lock["integration"]["verl_revision"]:
        raise ValueError("VERL pin mismatch")
    effective_verl = verl_source_identity()
    installed = runtime_probe(python, runtime)
    model_hashes = {str(model / name): digest(model / name) for name in ("config.json", "tokenizer_config.json")}
    origin = None
    if mode == "reload":
        for new in (output, run, checkpoint, ray):
            for old in (Path(resume_from), Path(mother_run)):
                if new.resolve().is_relative_to(old.resolve()) or old.resolve().is_relative_to(new.resolve()):
                    raise ValueError("Reload outputs must not overlap mother/checkpoint")
        origin = checkpoint_origin(
            resume_from,
            mother_run,
            family=family,
            course_id=course_id,
            model_revision=model_revision,
            runtime_sha=digest(runtime),
            verl_head=verl_head,
        )
    output.mkdir(parents=True, mode=0o700)
    if origin:
        (output / "checkpoint-origin.json").write_text(json.dumps(origin, indent=2) + "\n")
    if dataset:
        (output / "work-state-tasks.json").write_text(json.dumps(dataset, sort_keys=True, indent=2) + "\n")
    if course_id == "work-state-memory-core-v1":
        for name, value in _core_artifacts(dataset).items():
            (output / name).write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")
    selection_ref = None
    if work_state and mode in ("val", "reload"):
        selection_path = output / "eval-selection.json"
        selection_path.write_text(
            json.dumps(
                _selection_body(
                    run_id, mode, evaluation_task_ids, evaluation_ids, digest(output / "work-state-tasks.json")
                ),
                indent=2,
            )
            + "\n"
        )
        selection_ref = dict(path=str(selection_path), sha256=digest(selection_path))
    counts = {}
    # Only trusted task IDs reach actors; truth and task generation remain controller-side.
    for split in ("train", "validation"):
        records = (
            {key: value for key, value in dataset["tasks"].items() if value["split"] == split}
            if dataset
            else {split: {}}
        )
        identities = evaluation_ids if work_state and split == "validation" else list(records)
        rows = _task_rows(run_id, family, split, identities, work_state)
        counts[split] = len(rows)
        pq.write_table(pa.Table.from_pylist(rows), output / (split + ".parquet"))
    # Ops requires a task file; actual execution always substitutes a private StageSpec file.
    template = ROOT / "examples/dsh/evolution_task_config_v3_live.yaml"
    (output / "task.yaml").write_text(yaml.safe_dump(yaml.safe_load(template.read_text()), sort_keys=False))
    env = dict(
        HOME="/root",
        LANG="C.UTF-8",
        PATH=f"{python.parent}:/usr/local/bin:/usr/bin:/bin",
        PYTHONPATH=f"{ROOT}:{ROOT / 'verl'}",
        PYTHON_BIN=str(python),
        DSH_VENV=str(python.parent.parent),
        CUDA_VISIBLE_DEVICES="0",
        DSH_RUNTIME_MODE="exe",
        HF_HUB_OFFLINE="1",
        WANDB_MODE="disabled",
        PYTHONUNBUFFERED="1",
        OMP_NUM_THREADS="2",
        MKL_NUM_THREADS="2",
        RAY_TMPDIR=str(ray),
        MODEL_PATH=str(model),
        MODEL_ID="Qwen/Qwen3-4B",
        MODEL_LICENSE_APPROVED="1",
        VAL_ONLY="False" if mode == "train" else "True",
        RESUME_MODE="resume_path" if origin else "disable",
        RESUME_FROM_PATH=str(resume_from) if origin else "",
        TRAINER_MODE="sync",
        DATA_ROOT=str(output),
        TRAIN_FILE=str(output / "train.parquet"),
        TEST_FILE=str(output / "validation.parquet"),
        TASK_CONFIG=str(output / "task.yaml"),
        RUN_ROOT=str(run),
        CKPTS_DIR=str(checkpoint),
        TRAIN_MAX_SAMPLES="1",
        VAL_MAX_SAMPLES="1",
        TRAIN_BATCH_SIZE="1",
        PPO_MINI_BATCH_SIZE="1",
        ROLLOUT_N="4",
        VAL_ROLLOUT_N="1",
        TOTAL_TRAINING_STEPS="1",
        SAVE_FREQ="1",
        TEST_FREQ="1",
        DATA_SHUFFLE="False",
        LOW_VRAM="1",
        LORA_RANK="16",
        LORA_ALPHA="16",
        SAVE_LORA_ONLY="False",
        ROLLOUT_CPU_OFFLOAD_GB="0",
        ROLLOUT_LAYERED_SUMMON="False",
        ACTOR_PARAM_OFFLOAD="True",
        ACTOR_OPTIMIZER_OFFLOAD="True",
        MAX_PROMPT_LENGTH="8192",
        MAX_RESPONSE_LENGTH="8192",
        PPO_MAX_TOKEN_LEN_PER_GPU="16384",
        GPU_MEMORY_UTILIZATION="0.30",
        ROLLOUT_MAX_NUM_SEQS="1",
        GATEWAY_COUNT="1",
        CONCURRENCY="1",
        AGENT_LOG_DIR=str(run / "agent-logs"),
        DSH_TRACE_ROOT=str(run / "unused-global-traces"),
        DSH_RESULT_ROOT=str(run / "unused-global-results"),
        ROLLOUT_DATA_DIR=str(run / "rollouts"),
        VALIDATION_DATA_DIR=str(run / "validation"),
        PROJECT_NAME="dsh-memory-resident",
        EXP_NAME=run_id,
    )
    operator = dict(
        root=str(run / "chains"),
        runner_python=str(python),
        runtime_executable=str(runtime),
        environment_digest=digest(runtime),
        checkpoint_identity=origin["identity"] if origin else model_revision,
        family=family,
    )
    if work_state:
        operator.update(
            task_manifest=str(output / "work-state-tasks.json"),
            task_manifest_sha256=digest(output / "work-state-tasks.json"),
        )
        env.update(
            TRAIN_MAX_SAMPLES="520" if course_id == "work-state-memory-core-v1" else "8",
            VAL_MAX_SAMPLES=str(counts["validation"]),
            TOTAL_TRAINING_STEPS=("16" if course_id == "work-state-memory-core-v1" else "8")
            if mode == "train"
            else "1",
            SAVE_FREQ="8" if course_id == "work-state-memory-core-v1" else "4",
            TEST_FREQ="0" if mode == "train" else "1",
            PROJECT_NAME="dsh-work-state",
        )
    overrides = {
        AF + "framework_class_fqn": "uni_agent.framework.work_state.NativeWorkStateFramework"
        if work_state
        else "uni_agent.framework.memory_chain.NativeMemoryFramework",
        AF + "memory_run_id": run_id,
        AF + "memory_operator": operator,
        AF + "agent_runners.task.trajectory_selection": "all",
        AF + "trajectory_postprocessor_fqn": None,
        AF + "trajectory_postprocessor_kwargs": None,
        AF + "trajectory_postprocessor_pass_context": False,
    }
    if course_id == "work-state-memory-core-v1":
        operator["max_generated_tokens"] = 8192
    if work_state:
        adapter = "uni_agent.framework.entry.StrictSyncValidationRolloutAdapter"
        overrides.update(
            {
                "actor_rollout_ref.rollout.agent.agent_loop_manager_class": adapter,
                AF + "strict_validation_timeout_seconds": 3600,
            }
        )
    # JSON objects are not Hydra dictionaries (quoted keys are illegal); emit leaves instead.
    tail = []
    for key, value in overrides.items():
        if key.endswith("memory_operator"):
            tail.extend("++" + key + "." + k + "=" + json.dumps(v) for k, v in value.items())
        else:
            tail.append("++" + key + "=" + json.dumps(value))
    tail.extend(
        [
            "trainer.total_epochs=1",
            "trainer.test_freq=" + env["TEST_FREQ"],
            "trainer.default_local_dir=" + str(checkpoint),
        ]
    )
    if work_state and mode == "train":
        tail.append("trainer.val_before_train=False")
    if course_id == "work-state-memory-core-v1":
        tail.append("transfer_queue.backend.SimpleStorage.num_data_storage_units=1")
    if origin:
        tail.extend(
            [
                "trainer.val_only=True",
                "trainer.val_before_train=True",
                "trainer.del_local_ckpt_after_load=False",
                "actor_rollout_ref.actor.checkpoint.load_contents=[model,optimizer,extra]",
            ]
        )
    command = ["bash", str(ROOT / "examples/dsh/ops/launch_qwen3_4b_online_rl.sh"), "--foreground", *tail]
    sources = set((ROOT / "examples/dsh/capabilities").glob("memory*.py")) | {Path(__file__), template}
    sources.update((ROOT / "examples/dsh").glob("*.py"))
    if work_state:
        sources.update(
            p
            for p in (ROOT / "examples/dsh/capabilities/work_state").iterdir()
            if p.suffix in (".py", ".mjs") and not p.name.endswith(".test.mjs")
        )
    for directory in (
        "uni_agent/framework",
        "uni_agent/tasks/dsh",
        "uni_agent/agents/dsh",
        "examples/dsh/memory_closed",
    ):
        sources.update((ROOT / directory).glob("*.py"))
    sources.update((ROOT / "uni_agent/gateway").rglob("*.py"))
    sources.update((ROOT / "deployment/patches/verl").glob("*.patch"))
    sources.update(
        ROOT / p
        for p in (
            "examples/dsh/train_qwen3_4b_online_rl.sh",
            "examples/dsh/ops/launch_qwen3_4b_online_rl.sh",
            "deployment/versions/g1-deployment-lock.json",
            "deployment/services/harbor_training_supervisor.py",
            "deployment/versions/verl-runtime-patches.json",
            "deployment/checks/verl_source_overlay.py",
            "examples/dsh/ops/write_run_manifest.py",
        )
    )
    (output / "training.env").write_text("".join(f"export {k}={shlex.quote(v)}\n" for k, v in env.items()))
    manifest = dict(
        schema="dsh.memory-resident-preparation.v1",
        status="prepared-not-run",
        mode=mode,
        course_id=course_id,
        dataset_kind="public-structural-development" if work_state else "fixed-diagnostic-not-heldout",
        counts=counts,
        coverage=coverage,
        evaluation_selection=selection_ref,
        evaluation_task_ids=evaluation_task_ids,
        training=False,
        learning_signal_verified=False,
        repository_root=str(ROOT),
        integration_head=head,
        integration_branch=subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip(),
        verl_head=verl_head,
        verl_effective_source=effective_verl,
        model_revision_declared=model_revision,
        model_files=model_hashes,
        checkpoint_origin=origin,
        runtime=dict(path=str(runtime), sha256=digest(runtime), installed=installed),
        sources={str(p): digest(p) for p in sorted(sources)},
        files={str(p): digest(p) for p in sorted(output.iterdir())},
        environment=env,
        command=command,
        wall_seconds=7200 if mode == "train" else 3600,
        caveats=[
            "Public dev uses variant1; train uses variant0. Neither is a sealed holdout."
            if work_state
            else "Train/val are the same fixed family, not independently held out.",
            "All-equal B rewards imply zero GRPO signal; never manufacture failures.",
            "Model revision is declared identity; only listed model files are hashed.",
            "Legacy DSH v2 consumption auditor is not the memory-chain auditor.",
        ],
    )
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    for path in output.iterdir():
        path.chmod(0o600)
    return manifest


def check(manifest_path, *, after_run=False):
    manifest = json.loads(Path(manifest_path).read_text())
    if manifest["schema"] != "dsh.memory-resident-preparation.v1" or Path(manifest["repository_root"]) != ROOT:
        raise ValueError("Wrong manifest/checkout")
    if revision(ROOT) != manifest["integration_head"] or revision(ROOT / "verl") != manifest["verl_head"]:
        raise ValueError("Checkout changed; prepare a new run")
    if manifest.get("verl_effective_source") != verl_source_identity():
        raise ValueError("VERL effective source changed; prepare a new run")
    for collection in ("sources", "files", "model_files"):
        for path, expected in manifest[collection].items():
            if digest(path) != expected:
                raise ValueError("Input/source/model changed: " + path)
    if digest(manifest["runtime"]["path"]) != manifest["runtime"]["sha256"]:
        raise ValueError("Runtime changed")
    env = manifest["environment"]
    overrides = dict(x.lstrip("+").split("=", 1) for x in manifest["command"][3:] if "=" in x)
    family = json.loads(overrides[AF + "memory_operator.family"])
    work_state = family == "work-state-v1"
    course_id = _resolve_course(family, manifest.get("course_id"))
    if work_state:
        task_path = Path(json.loads(overrides[AF + "memory_operator.task_manifest"]))
        expected_task_path = Path(env["DATA_ROOT"]) / "work-state-tasks.json"
        if (
            task_path != expected_task_path
            or digest(task_path) != json.loads(overrides[AF + "memory_operator.task_manifest_sha256"])
            or json.loads(task_path.read_text()) != _dataset_for_course(course_id)[0]
        ):
            raise ValueError("Work-state task manifest identity changed")
        dataset = _dataset_for_course(course_id)[0]
        if course_id == "work-state-memory-core-v1":
            for name, expected in _core_artifacts(dataset).items():
                if json.loads((Path(env["DATA_ROOT"]) / name).read_text()) != expected:
                    raise ValueError("Core controller/model-visible artifact changed")
        run_id = env["EXP_NAME"]
        requested = None
        if manifest["mode"] in ("val", "reload"):
            selection_path = Path(env["DATA_ROOT"]) / "eval-selection.json"
            ref = dict(path=str(selection_path), sha256=digest(selection_path))
            if manifest.get("evaluation_selection") != ref:
                raise ValueError("Work-state evaluation selection digest/location changed")
            selection = json.loads(selection_path.read_text())
            requested = manifest["evaluation_task_ids"]
            resolved = _evaluation_ids(dataset, requested, manifest["mode"])
            if selection != _selection_body(run_id, manifest["mode"], requested, resolved, digest(task_path)):
                raise ValueError("Work-state evaluation selection changed")
        elif manifest.get("evaluation_selection") is not None:
            raise ValueError("Training cannot select evaluation tasks")
        selected = _evaluation_ids(dataset, requested, manifest["mode"])
        expected_coverage = _course_coverage(dataset, course_id, selected)
        if manifest["coverage"] != expected_coverage:
            raise ValueError("Work-state evaluation coverage changed")
        expected_counts = {}
        for split in ("train", "validation"):
            ids = (
                selected
                if split == "validation"
                else [key for key, value in dataset["tasks"].items() if value["split"] == split]
            )
            expected_counts[split] = len(ids)
            actual = pq.read_table(Path(env["DATA_ROOT"]) / (split + ".parquet")).to_pylist()
            if actual != _task_rows(run_id, "work-state-v1", split, ids, True):
                raise ValueError("Work-state parquet rows/order/identity changed")
        if manifest["counts"] != expected_counts or env["VAL_MAX_SAMPLES"] != str(len(selected)):
            raise ValueError("Work-state evaluation counts/limit changed")
    if course_id == "work-state-memory-core-v1":
        if overrides.get("transfer_queue.backend.SimpleStorage.num_data_storage_units") != "1":
            raise ValueError("Core course storage CPU budget changed")
        if overrides.get(AF + "memory_operator.max_generated_tokens") != "8192":
            raise ValueError("Core course generation budget changed")
        expected_budget = {
            "TRAIN_MAX_SAMPLES": "520",
            "TOTAL_TRAINING_STEPS": "16" if manifest["mode"] == "train" else "1",
            "SAVE_FREQ": "8",
            "TRAINER_MODE": "sync",
            "ROLLOUT_N": "4",
        }
        if any(env.get(key) != value for key, value in expected_budget.items()):
            raise ValueError("Core course diagnostic budget changed")
        budget_overrides = {
            "data.train_max_samples": "TRAIN_MAX_SAMPLES",
            "trainer.total_training_steps": "TOTAL_TRAINING_STEPS",
            "trainer.save_freq": "SAVE_FREQ",
            "trainer.v1.trainer_mode": "TRAINER_MODE",
            "actor_rollout_ref.rollout.n": "ROLLOUT_N",
        }
        if any(
            key in overrides and overrides[key] != expected_budget[env_key] for key, env_key in budget_overrides.items()
        ):
            raise ValueError("Core course command budget changed")
    if work_state and manifest["mode"] == "train":
        if (
            env["TEST_FREQ"] != "0"
            or overrides.get("trainer.test_freq") != "0"
            or overrides.get("trainer.val_before_train") != "False"
        ):
            raise ValueError("Work-state training must use independent evaluation")
    if manifest["mode"] == "reload" and not manifest.get("checkpoint_origin"):
        raise ValueError("Reload requires checkpoint origin")
    if manifest.get("checkpoint_origin"):
        origin = manifest["checkpoint_origin"]
        actual = checkpoint_origin(
            origin["checkpoint_path"],
            origin["mother_run"],
            family=next(
                json.loads(x.split("=", 1)[1])
                for x in manifest["command"]
                if x.startswith("++" + AF + "memory_operator.family=")
            ),
            course_id=course_id,
            model_revision=manifest["model_revision_declared"],
            runtime_sha=manifest["runtime"]["sha256"],
            verl_head=manifest["verl_head"],
        )
        if actual != origin or json.loads((Path(env["DATA_ROOT"]) / "checkpoint-origin.json").read_text()) != origin:
            raise ValueError("Checkpoint or mother evidence changed")
        if (
            manifest["mode"] != "reload"
            or env["VAL_ONLY"] != "True"
            or env["RESUME_MODE"] != "resume_path"
            or env["RESUME_FROM_PATH"] != origin["checkpoint_path"]
        ):
            raise ValueError("Invalid reload-only configuration")
        expected = {
            "trainer.val_only": "True",
            "trainer.val_before_train": "True",
            "trainer.del_local_ckpt_after_load": "False",
            "actor_rollout_ref.actor.checkpoint.load_contents": "[model,optimizer,extra]",
            AF + "memory_operator.checkpoint_identity": json.dumps(origin["identity"]),
        }
        if any(overrides.get(k) != v for k, v in expected.items()):
            raise ValueError("Reload protected overrides changed")
    runtime_probe(Path(env["PYTHON_BIN"]), Path(manifest["runtime"]["path"]))
    for key in ("RUN_ROOT", "CKPTS_DIR", "RAY_TMPDIR"):
        path = Path(env[key])
        if not after_run and (path.exists() or path.is_symlink()):
            raise ValueError("Run path already exists")
    subprocess.run(
        [
            env["PYTHON_BIN"],
            "-c",
            "from uni_agent.framework.memory_chain import NativeMemoryFramework;"
            "from examples.dsh.capabilities.memory_training_stage import validate_stage_execution;"
            + ("from uni_agent.framework.work_state import NativeWorkStateFramework" if work_state else ""),
        ],
        cwd=env["DATA_ROOT"],
        env={**env, "CUDA_VISIBLE_DEVICES": ""},
        check=True,
        timeout=60,
    )
    return manifest


def check_gpu_available():
    """Fail closed on busy/unknown GPUs; resolve permission-hidden MIG via NVML."""
    try:
        output = subprocess.check_output(
            ["nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader"], text=True, timeout=15
        ).strip()
        if not output:
            return {"available": True, "method": "nvidia-smi-empty-compute-query"}
        if any(line.strip() != "[Insufficient Permissions]" for line in output.splitlines()):
            raise ValueError("GPU is in use or process visibility is unknown; identify its owner first")
        listing = subprocess.check_output(["nvidia-smi", "-L"], text=True, timeout=15)
        uuids = re.findall(r"\(UUID: (MIG-[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})\)", listing)
        if len(uuids) != 1 or listing.count("MIG ") != 1:
            raise ValueError("Permission-hidden GPU requires exactly one visible MIG instance")
        import pynvml

        pynvml.nvmlInit()
        try:
            handle = pynvml.nvmlDeviceGetHandleByUUID(uuids[0])
            actual_uuid = pynvml.nvmlDeviceGetUUID(handle)
            if isinstance(actual_uuid, bytes):
                actual_uuid = actual_uuid.decode("ascii")
            if actual_uuid != uuids[0]:
                raise ValueError("NVML MIG UUID does not match the visible instance")
            compute = pynvml.nvmlDeviceGetComputeRunningProcesses(handle)
            graphics = pynvml.nvmlDeviceGetGraphicsRunningProcesses(handle)
            if compute != [] or graphics != []:
                raise ValueError("MIG has active or unknown compute/graphics processes")
            info = pynvml.nvmlDeviceGetMemoryInfo(handle)
            memory = {key: getattr(info, key) for key in ("total", "used", "free")}
            if (
                any(type(value) is not int or value < 0 for value in memory.values())
                or memory["total"] <= 0
                or memory["used"] + memory["free"] > memory["total"]
            ):
                raise ValueError("MIG memory visibility is invalid")
            return {
                "available": True,
                "method": "nvml-unique-mig",
                "mig_uuid": actual_uuid,
                "compute_process_count": 0,
                "graphics_process_count": 0,
                "memory": memory,
            }
        finally:
            pynvml.nvmlShutdown()
    except Exception as exc:
        raise ValueError("GPU admission failed; no training process was launched") from exc


def launch(manifest_path):
    from deployment.services.harbor_training_supervisor import supervise

    manifest = check(manifest_path)
    gpu_admission = check_gpu_available()
    env = manifest["environment"]
    run = Path(env["RUN_ROOT"])
    run.mkdir(mode=0o700)
    (run / "gpu-admission.json").write_text(json.dumps(gpu_admission, indent=2) + "\n")
    (run / "chains").mkdir(mode=0o700)
    Path(env["RAY_TMPDIR"]).mkdir(mode=0o700)
    (run / "memory-launch-plan.json").write_text(json.dumps(manifest, indent=2) + "\n")
    supervision = run / "supervision"
    supervision.mkdir(mode=0o700)
    result = supervise(
        manifest["command"],
        ROOT,
        env,
        supervision,
        lambda: None,
        wall_seconds=manifest["wall_seconds"],
        interval=5,
        grace=30,
    )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    prep = sub.add_parser("prepare")
    for key in (
        "output-dir",
        "run-root",
        "run-id",
        "runtime-executable",
        "runner-python",
        "model-path",
        "model-revision",
    ):
        prep.add_argument("--" + key, required=True)
    prep.add_argument("--course", dest="course_id", choices=COURSES)
    prep.add_argument("--mode", choices=("val", "train", "reload"), default="val")
    prep.add_argument("--resume-from", type=Path)
    prep.add_argument("--mother-run", type=Path)
    prep.add_argument("--evaluation-task-id", dest="evaluation_task_ids", action="append")
    prep.add_argument("--family", choices=("constraints", "updates", "work-state-v1"), default="constraints")
    for name in ("check", "launch"):
        sub.add_parser(name).add_argument("manifest_path", type=Path)
    args = vars(parser.parse_args())
    action = args.pop("action")
    result = {"prepare": prepare, "check": check, "launch": launch}[action](**args)
    print(json.dumps(result, indent=2))
    if action == "launch" and result["exit_code"] != 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
