"""Prepare a new native N0 course and bounded run plans; never start training."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from examples.dsh.evolution_verifier_v2 import bundle_digest
from examples.dsh.prepare_evolution_dataset import build_evolution_rows, write_parquet
from examples.dsh.prepare_redact_curriculum import prepare as select_course
from examples.dsh.prepare_redact_curriculum_v2 import prepare as version_course

RUNTIME_SHA256 = "sha256:d1a467a9c14a38ad5f01591d2cdb125852cb1a1d3b0ecb678dfde383404e80cb"
BUNDLE_SHA256 = "sha256:60f49dcb519576bbe09839371ec3220775aa42aaf5e780a7f5d843c71552ea82"
DSH_REVISION = "b2369692ea530007075ebcd18d39fdba0bbd3982"
BUDGET = {
    "TOTAL_TRAINING_STEPS": "2",
    "TRAIN_BATCH_SIZE": "2",
    "ROLLOUT_N": "4",
    "VAL_ROLLOUT_N": "1",
    "TRAIN_MAX_SAMPLES": "4",
    "VAL_MAX_SAMPLES": "2",
    "MAX_PROMPT_LENGTH": "8192",
    "MAX_RESPONSE_LENGTH": "1024",
    "LORA_RANK": "16",
    "LORA_ALPHA": "16",
    "VAL_ONLY": "False",
    "RESUME_MODE": "disable",
}


def sha(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def read(path, limit=2 * 1024 * 1024):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise ValueError("Expected a bounded regular input file: " + str(path))
    return path.read_bytes()


def revision(root):
    return subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True, timeout=15).strip()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def write(path, value):
    raw = (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n").encode()
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as out:
        out.write(raw)


def target_path(path, root):
    require(path.is_absolute() and ".." not in path.parts, "Output paths must be absolute and traversal-free")
    require(not path.resolve().is_relative_to(root), "Output must be outside checkout")
    require(not any(p.is_symlink() for p in (path, *path.parents)), "Output path may not traverse symlinks")


def course_rows(data, manifest):
    result = {}
    require(manifest.get("schema") == "dsh.redact-curriculum.v2", "Expected baseline v2 course")
    for split, count in (("train", 4), ("holdout", 2)):
        path = data / (split + ".parquet")
        raw = read(path)
        entry = manifest["files"][path.name]
        require(sha(raw) == entry["sha256"], "Baseline Parquet SHA mismatch")
        rows = pq.read_table(pa.BufferReader(raw)).to_pylist()
        require(len(rows) == count == entry["records"], "Baseline course count mismatch")
        result[split] = rows
    return result


def prepare(
    *,
    repository_root,
    expected_revision,
    venv,
    runtime_executable,
    baseline_manifest,
    baseline_manifest_sha256,
    output_dir,
    run_parent,
    checkpoint_parent,
    run_name,
):
    root = repository_root.resolve()
    require(root == Path(__file__).resolve().parents[3], "Prepare using the target checkout's code")
    require(re.fullmatch(r"[0-9a-f]{40}", expected_revision) is not None, "Expected full commit")
    require(revision(root) == expected_revision, "Checkout revision mismatch")
    require(re.fullmatch(r"[a-z][a-z0-9-]{1,63}", run_name) is not None, "Invalid run name")
    require(venv.is_absolute() and (venv / "bin/python").is_file(), "Missing absolute target venv")
    require(runtime_executable.resolve().is_relative_to(venv.resolve()), "Runtime must come from new venv")
    require(sha(read(runtime_executable, 256 * 1024 * 1024)) == RUNTIME_SHA256, "Runtime SHA mismatch")
    require(bundle_digest() == BUNDLE_SHA256, "Original verifier bundle changed")
    train_root, reload_root = run_parent / run_name, run_parent / (run_name + "-reload")
    checkpoints, reload_checkpoints = checkpoint_parent / run_name, checkpoint_parent / (run_name + "-reload")
    for path in (output_dir, train_root, reload_root, checkpoints, reload_checkpoints):
        target_path(path, root)
        if path.exists():
            raise FileExistsError(path)
    targets = (output_dir, train_root, reload_root, checkpoints, reload_checkpoints)
    require(
        all(not a.is_relative_to(b) for a in targets for b in targets if a != b) and len(set(targets)) == len(targets),
        "Prepare, run and checkpoint directories must not overlap",
    )
    raw_baseline = read(baseline_manifest)
    require(sha(raw_baseline) == baseline_manifest_sha256, "Baseline launch manifest SHA mismatch")
    baseline = json.loads(raw_baseline)
    env = baseline["environment"]
    require(all(env.get(k) == v for k, v in BUDGET.items()), "Baseline differs from two-step r4 budget")
    data = Path(env["DATA_ROOT"])
    require(data.is_absolute(), "Baseline data root must be absolute")
    require(
        Path(env["TRAIN_FILE"]) == data / "train.parquet" and Path(env["TEST_FILE"]) == data / "holdout.parquet",
        "Baseline data path mismatch",
    )
    course_raw = read(data / "manifest.json")
    require(sha(course_raw) == baseline["curriculum_manifest_sha256"], "Baseline course manifest SHA mismatch")
    old_course = json.loads(course_raw)
    old_rows = course_rows(data, old_course)
    old_root = Path(env["PYTHONPATH"].split(":")[0])
    require(old_root.is_absolute() and old_root != root, "Expected distinct baseline checkout root")
    # Validate equivalent desired rows before claiming any successful output.
    metadata = old_course["task"]
    require(
        metadata["environment_digest"] == RUNTIME_SHA256 and metadata["verifier_code_digest"] == BUNDLE_SHA256,
        "Baseline runtime/verifier identity mismatch",
    )
    output_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    require(output_dir.stat().st_mode & 0o777 == 0o700, "Output filesystem must enforce private directory mode")
    full, selected, versioned = (output_dir / name for name in ("course-16-8", "course-4-2-v1", "course-4-2-v2"))
    full.mkdir(mode=0o700)
    parent_digest = sha(read(root / "examples/dsh/evolution_verifier.py"))
    rows = build_evolution_rows(
        root / "examples/dsh/evolution_scenarios_v2.jsonl",
        fixture_root=root,
        environment_digest=RUNTIME_SHA256,
        verifier_id="dsh-harness-evolution-verifier",
        verifier_version="1",
        verifier_code_digest=parent_digest,
        profile="sdk-minimal",
        patches=["examples/dsh/evolution.patch.yml"],
    )
    write_parquet(rows, full)
    # Existing manifest CLI retains historical source labels; the outer plan pins this checkout accurately.
    command = [
        str(venv / "bin/python"),
        str(root / "examples/dsh/ops/write_dataset_manifest.py"),
        "--repo-root",
        str(root),
        "--scenario-file",
        str(root / "examples/dsh/evolution_scenarios_v2.jsonl"),
        "--output-dir",
        str(full),
        "--environment-digest",
        RUNTIME_SHA256,
        "--verifier-code-digest",
        parent_digest,
    ]
    subprocess.run(
        command,
        cwd=root,
        env={**os.environ, "PYTHONPATH": str(root) + ":" + str(root / "verl")},
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    select_course(
        repository_root=root,
        source_dir=full,
        source_manifest_sha256=sha(read(full / "manifest.json")),
        runtime_executable=runtime_executable,
        output_dir=selected,
    )
    current = version_course(
        repository_root=root,
        source_dir=selected,
        source_manifest_sha256=sha(read(selected / "manifest.json")),
        runtime_executable=runtime_executable,
        output_dir=versioned,
    )
    new_rows = course_rows(versioned, current)
    require(old_course["fixtures"] == current["fixtures"], "Course fixture manifest differs")
    compared = 0
    changed_messages = 0
    mapped_occurrences = 0
    path_diffs = []
    for split in ("train", "holdout"):
        for old, new in zip(old_rows[split], new_rows[split], strict=True):
            expected = copy.deepcopy(old)
            fixture = old["extra_info"]["tools_kwargs"]["task"]["metadata"]["fixture_path"]
            old_absolute, new_absolute = str(old_root / fixture), str(root / fixture)
            occurrences = 0
            for message in expected["prompt"]:
                count = message["content"].count(old_absolute)
                occurrences += count
                changed_messages += int(count > 0)
                message["content"] = message["content"].replace(old_absolute, new_absolute)
            require(occurrences > 0, "Baseline prompt must contain the expected absolute fixture path")
            mapped_occurrences += occurrences
            path_diffs.append(
                {
                    "scenario_id": old["extra_info"]["tools_kwargs"]["task"]["metadata"]["scenario_id"],
                    "old_path": old_absolute,
                    "new_path": new_absolute,
                    "occurrences": occurrences,
                }
            )
            require(expected == new, "Course business equivalence failed; only fixture-root mapping is allowed")
            compared += 1
    for file in output_dir.rglob("*"):
        if file.is_file():
            file.chmod(0o600)
    migrated = dict(env)
    for key in ("ALLOW_REUSE", "PRINT_COMMAND", "RESUME_FROM_PATH", "PYTORCH_CUDA_ALLOC_CONF"):
        migrated.pop(key, None)
    migrated.update(
        PYTHON_BIN=str(venv / "bin/python"),
        DSH_VENV=str(venv),
        PATH=str(venv / "bin") + ":/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        PYTHONPATH=str(root) + ":" + str(root / "verl"),
        DATA_ROOT=str(versioned),
        TRAIN_FILE=str(versioned / "train.parquet"),
        TEST_FILE=str(versioned / "holdout.parquet"),
        TASK_CONFIG=str(versioned / "task-config.yaml"),
        DSH_SHA=DSH_REVISION,
        TRAINER_MODE="sync",
    )

    def launch(run, ckpt, name, reload=False):
        values = {
            **migrated,
            "RUN_ROOT": str(run),
            "EXP_NAME": name,
            "CKPTS_DIR": str(ckpt),
            "AGENT_LOG_DIR": str(run / "agent-logs"),
            "ROLLOUT_DATA_DIR": str(run / "rollouts"),
            "VALIDATION_DATA_DIR": str(run / "validation"),
            "DSH_TRACE_ROOT": str(run / "artifacts/traces"),
            "DSH_RESULT_ROOT": str(run / "artifacts/results"),
        }
        command = ["bash", "examples/dsh/ops/launch_qwen3_4b_online_rl.sh", "--foreground"]
        if reload:
            values.update(
                VAL_ONLY="True", RESUME_MODE="resume_path", RESUME_FROM_PATH=str(checkpoints / "global_step_2")
            )
            command = [
                "bash",
                "examples/dsh/ops/reload_qwen3_4b_checkpoint.sh",
                str(checkpoints / "global_step_2"),
                "--foreground",
            ]
        return {
            "schema": "dsh.native-n0-launch.v1",
            "source_commit": expected_revision,
            "cwd": str(root),
            "environment": values,
            "command": command,
            "wall_clock_seconds": 1800 if reload else 2700,
            "curriculum_manifest_sha256": sha(read(versioned / "manifest.json")),
            "verifier_bundle_sha256": BUNDLE_SHA256,
            "status": "prepared-not-run",
        }

    train, reload = (
        launch(train_root, checkpoints, run_name),
        launch(reload_root, reload_checkpoints, run_name + "-reload", True),
    )
    write(output_dir / "train-launch-manifest.json", train)
    write(output_dir / "reload-launch-manifest.json", reload)
    python = str(venv / "bin/python")
    steps = [
        {
            "name": "train",
            "launch_manifest": str(output_dir / "train-launch-manifest.json"),
            "requires": "preflight and GPU idle",
        },
        {
            "name": "train-audit",
            "argv": [
                python,
                "examples/dsh/ops/audit_qwen3_4b_online_rl.py",
                str(train_root),
                "--output",
                str(output_dir / "train-audit.json"),
            ],
        },
        {
            "name": "delta",
            "argv": [
                python,
                "deployment/checks/checkpoint_delta.py",
                str(checkpoints / "global_step_1/actor/model_world_size_1_rank_0.pt"),
                str(checkpoints / "global_step_2/actor/model_world_size_1_rank_0.pt"),
                "--output",
                str(output_dir / "checkpoint-delta.json"),
            ],
        },
        {
            "name": "optimizer-audit",
            "argv": [
                python,
                "deployment/checks/optimizer_delta.py",
                str(checkpoints / "global_step_1/actor/optim_world_size_1_rank_0.pt"),
                str(checkpoints / "global_step_2/actor/optim_world_size_1_rank_0.pt"),
                "--output",
                str(output_dir / "optimizer-delta.json"),
            ],
        },
        {
            "name": "reload",
            "launch_manifest": str(output_dir / "reload-launch-manifest.json"),
            "requires": "train audit and numerical evidence pass; prior GPU process exited",
        },
        {
            "name": "reload-audit",
            "argv": [
                python,
                "examples/dsh/ops/audit_qwen3_4b_online_rl.py",
                str(reload_root),
                "--partition",
                "val",
                "--output",
                str(output_dir / "reload-audit.json"),
            ],
        },
    ]
    plan = {
        "schema": "dsh.native-n0-preparation.v1",
        "status": "prepared-not-run",
        "source_commit": expected_revision,
        "baseline_launch_sha256": baseline_manifest_sha256,
        "baseline_course_sha256": sha(course_raw),
        "equivalence": {
            "rows_compared": compared,
            "changed_prompt_messages": changed_messages,
            "absolute_path_replacements": mapped_occurrences,
            "path_diffs": path_diffs,
            "metadata_equal_without_exclusions": True,
            "fixture_manifest_equal": True,
            "only_prompt_root_mapping": True,
            "old_root": str(old_root),
            "new_root": str(root),
        },
        "steps": steps,
        "model_cache_reused": migrated.get("MODEL_PATH"),
        "fail_closed": "No execution here. Require previous stage evidence before proceeding; never overwrite outputs.",
    }
    write(output_dir / "plan.json", plan)
    return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "repository-root",
        "venv",
        "runtime-executable",
        "baseline-manifest",
        "output-dir",
        "run-parent",
        "checkpoint-parent",
    ):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("expected-revision", "baseline-manifest-sha256", "run-name"):
        parser.add_argument("--" + name, required=True)
    result = prepare(**vars(parser.parse_args()))
    print(json.dumps({"status": result["status"], "equivalence": result["equivalence"]}))


if __name__ == "__main__":
    main()
