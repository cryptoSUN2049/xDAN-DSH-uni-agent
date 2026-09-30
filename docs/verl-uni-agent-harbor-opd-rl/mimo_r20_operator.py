"""Bounded sequential MiMo stages over a separately assembled R20 runtime.

Stage plans and credentials stay on the cloud host. All admission and preparation
commands are CPU-only. ``supervise`` is the sole command that may start training.
"""

import argparse
import hashlib
import json
import math
import os
import re
import runpy
import time
import urllib.request
from pathlib import Path

ROOT = Path("/workspace/mimo-dsh-rl-20260928")
PRIVATE = Path("/root/mimo-private")
DEADLINE = 1790759992
RESERVE = 180
SOURCE_COMMIT = "1ccc1640c0f34ba5f515d3613fac6a278bd38f4c"
SOURCE_MANIFEST_SHA = "99ac03f55d4eaeebc63d2ba466452fef2af7a51af289fc135d5051dadca0591f"
SOURCE_DIR = "run-src-r20"
BASE_COMMIT = "4dbd87ad4f6123f99a1f715a6637322a44cff6a5"
BASE_MANIFEST_SHA = "04fb0fcd1eb0b62aa89dce193211080ce4b6000f8df6a97a225a027c946564af"
OLD_C4_MANIFEST_SHA = "40f25db06843bc9400f7f4fbe82eea46e7dcae8fffa9c5d383cf1ded40bb1270"
PRODUCTION_BLOBS = {
    "examples/mimo_dsh_rl/verifier.py": "12a6f9d3a849ff66168269f800f63325077d76a61942e9315d8335eb6d63c371",
    "uni_agent/tasks/harbor_dsh/mimo_workspace.py": "faba54386d324f0fc25b76bed6f0d81aa8f03cf926ad9c542214a6ae71b4409d",
}
FREEZE_SHA = "e9f87349997a81b7fbc31ef1ce74f9abb078c37600282d4684c63c75514c4dc7"
MODEL = "/workspace/models/MiMo-V2.6-Distill-Qwen-9B"
MODEL_REVISION = "2367e865d009c13ac81713a2878291d33ab28177"
DATA_REVISION = "639865fd3374018d6cb29b9fb82dd531406fcf5f"
DSH_SOURCE = "b2369692ea530007075ebcd18d39fdba0bbd3982"
SDK_SHA = "sha256:6c6a1a8f26b9030326447a8ed41c3ae6261a6b78e7fe61d72c7bf3ae21f03d6e"
RUNTIME_SHA = "sha256:59cc8ec59946afa572bfd0b9e6268d7380a4d00d1157d7dce6d2b2df86cf51ad"
DATASET_HELPER_SHA = "228457d8796a6f5f0ad7f2067f6d1073f7326ebffdb235e761a064ba0edad7ec"
PYTHON = "/workspace/verl-uni-agent-harbor-opd-rl/envs/ua-verl-py312-vllm023-ws1/bin/python"
CHECKPOINT_FILES = {
    "data.pt",
    "actor/fsdp_config.json",
    "actor/lora_train_meta.json",
    *(f"actor/{kind}_world_size_2_rank_{rank}.pt" for kind in ("model", "optim", "extra_state") for rank in (0, 1)),
    *(
        f"actor/huggingface/{name}"
        for name in (
            "processor_config.json",
            "tokenizer.json",
            "tokenizer_config.json",
            "chat_template.jinja",
            "config.json",
            "generation_config.json",
        )
    ),
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def source_directory():
    return ROOT / SOURCE_DIR


def file_identity(path):
    """Stream files and detect mutation; never deserialize checkpoint tensors."""
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), "Unsafe or missing file")
    before = path.stat()
    with path.open("rb") as source:
        sha = hashlib.file_digest(source, "sha256").hexdigest()
    after = path.stat()
    require(
        (before.st_ino, before.st_size, before.st_mtime_ns) == (after.st_ino, after.st_size, after.st_mtime_ns),
        "File changed during hashing",
    )
    return {"bytes": before.st_size, "sha256": sha}


def read_bound(path, expected):
    require(isinstance(expected, str) and re.fullmatch(r"[0-9a-f]{64}", expected), "Explicit SHA256 required")
    require(file_identity(path)["sha256"] == expected, "Bound input hash differs")
    return json.loads(Path(path).read_bytes())


def write_new(path, value):
    path = Path(path)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as output:
        json.dump(value, output, indent=2, sort_keys=True, allow_nan=False)
        output.write("\n")


def checkpoint_files(checkpoint):
    checkpoint = Path(checkpoint)
    require(checkpoint.is_dir() and not checkpoint.is_symlink(), "Checkpoint directory missing")
    require(not (checkpoint / "transfer_queue").exists(), "Native task boundary cannot restore TransferQueue state")
    names = {str(path.relative_to(checkpoint)) for path in checkpoint.rglob("*") if path.is_file()}
    require(names == CHECKPOINT_FILES, "Exact fifteen native checkpoint files required; no TQ state accepted")
    result = {}
    for name in sorted(names):
        path = checkpoint / name
        require(path.resolve().is_relative_to(checkpoint.resolve()), "Checkpoint path escapes root")
        result[name] = file_identity(path)
        require(result[name]["bytes"] > 0, "Empty checkpoint component")
    fsdp = json.loads((checkpoint / "actor/fsdp_config.json").read_bytes())
    require(
        type(fsdp.get("world_size")) is int
        and fsdp["world_size"] == 2
        and type(fsdp.get("FSDP_version")) is int
        and fsdp["FSDP_version"] == 1,
        "Native world2 FSDP1 required",
    )
    match = re.fullmatch(r"global_step_([0-9]+)", checkpoint.name)
    require(match is not None, "Absolute checkpoint step required")
    step = int(match[1])
    marker = checkpoint.parent / "latest_checkpointed_iteration.txt"
    require(
        marker.is_file() and not marker.is_symlink() and marker.read_text().strip() == str(step),
        "Parent checkpoint is not committed",
    )
    return step, result


def seal_parent(checkpoint, output, provenance):
    for key in ("run_id", "task_id", "source_commit", "run_spec_sha256", "evidence_sha256"):
        require(key in provenance, "Parent provenance incomplete")
    require(provenance["source_commit"] == SOURCE_COMMIT, "New seals require current reviewed source")
    validate_source()
    require(re.fullmatch(r"[0-9a-f]{64}", provenance["run_spec_sha256"]), "Parent spec SHA required")
    require(bool(provenance["evidence_sha256"]), "Actual native acceptance evidence required")
    for path, sha in provenance["evidence_sha256"].items():
        require(
            Path(path).is_absolute() and file_identity(path)["sha256"] == sha,
            "Actual parent acceptance evidence differs",
        )
    step, files = checkpoint_files(checkpoint)
    report = {
        "schema": "mimo.native-checkpoint-manifest.v1",
        **provenance,
        "checkpoint": str(Path(checkpoint).resolve()),
        "step": step,
        "world_size": 2,
        "fsdp_version": 1,
        "source_manifest_sha256": SOURCE_MANIFEST_SHA,
        "files": files,
        "inflight_tq_replay_available": False,
        "sealed_at": time.time(),
        "training_started": False,
    }
    validate_parent_evidence(report)
    write_new(output, report)
    return report


def validate_window(deadline, now):
    require(type(deadline) is int and deadline == DEADLINE, "Fixed four-hour authorization required")
    require(type(now) in (int, float) and math.isfinite(now), "Invalid clock")
    require(2400 <= deadline - now - RESERVE <= 14400, "Insufficient or unauthorized remaining window")
    return int(deadline - now - RESERVE)


def validate_plan(plan, *, now=None):
    require(plan.get("schema") == "mimo.r20-stage-plan.v1", "Stage plan schema differs")
    stage, task_id = plan["stage"], plan["task_id"]
    require(isinstance(stage, str) and re.fullmatch(r"r20[a-z]", stage), "Independent stage identity required")
    require(isinstance(task_id, str) and re.fullmatch(r"[0-9]{6}", task_id), "Real MiMo task ID required")
    require(plan["run_id"] == f"mimo9b-{task_id}-{stage}", "Stage run identity differs")
    require(
        plan["model_revision"] == MODEL_REVISION and plan["data_revision"] == DATA_REVISION,
        "Fixed model/data revisions required",
    )
    wall = validate_window(plan["deadline_unix"], time.time() if now is None else now)
    require(
        isinstance(SOURCE_MANIFEST_SHA, str)
        and re.fullmatch(r"[0-9a-f]{64}", SOURCE_MANIFEST_SHA)
        and plan["source_commit"] == SOURCE_COMMIT
        and plan["source_manifest_sha256"] == SOURCE_MANIFEST_SHA,
        "Frozen production source identity differs",
    )
    for key in (
        "spec_path",
        "parent_manifest_path",
        "parent_manifest_sha256",
        "http_proof_path",
        "http_proof_sha256",
        "calibration_path",
        "calibration_sha256",
        "task_manifest_path",
        "task_manifest_sha256",
    ):
        require(isinstance(plan.get(key), str) and bool(plan[key]), "Stage input missing: " + key)
    require(Path(plan["spec_path"]) == PRIVATE / f"run-spec-{stage}.json", "Independent private spec required")
    return {
        "stage": stage,
        "task_id": task_id,
        "run_id": plan["run_id"],
        "wall_clock_seconds": wall,
        "launch_root": str(PRIVATE / f"launch-{stage}"),
        "run_root": str(ROOT / "runs" / stage),
        "journal": str(PRIVATE / f"launch-{stage}/token-journal"),
    }


def validate_source(root=None):
    root = ROOT if root is None else root
    manifest = read_bound(root / "integration-check/source-r20-manifest.json", SOURCE_MANIFEST_SHA)
    require(
        manifest["git_commit"] == SOURCE_COMMIT
        and manifest["compatibility_git_commit"] == SOURCE_COMMIT
        and manifest["assembly_mode"] == "verified-r19-runtime-plus-two-git-blobs"
        and manifest["parent_git_commit"] == BASE_COMMIT
        and manifest["parent_manifest_sha256"] == BASE_MANIFEST_SHA
        and manifest["compatibility_git_blob_sha256"] == PRODUCTION_BLOBS
        and len(manifest["files"]) == 1003,
        "Frozen runtime manifest identity differs",
    )
    base = read_bound(root / "integration-check/source-r19-manifest.json", BASE_MANIFEST_SHA)
    require(
        base["git_commit"] == BASE_COMMIT and manifest["files"].keys() == base["files"].keys(),
        "Runtime assembly must preserve the exact reviewed base file set",
    )
    for name, identity in manifest["files"].items():
        relative = Path(name)
        require(not relative.is_absolute() and ".." not in relative.parts, "Invalid source relative path")
        path = root / SOURCE_DIR / relative
        require(path.resolve().is_relative_to((root / SOURCE_DIR).resolve()), "Source path escapes freeze")
        require(
            file_identity(path) == {"bytes": identity["bytes"], "sha256": identity["sha256"]},
            "Frozen runtime file changed",
        )
        if name not in PRODUCTION_BLOBS:
            require(identity == base["files"][name], "Runtime assembly changed an unapproved base file")
    for name, sha in PRODUCTION_BLOBS.items():
        require(manifest["files"][name]["sha256"] == sha, "Reviewed compatibility production blob differs")
    return SOURCE_MANIFEST_SHA


def validate_parent_evidence(parent):
    """A new parent must have actual effective-update and native W&B acceptance."""
    proofs = [read_bound(path, sha) for path, sha in parent["evidence_sha256"].items()]
    updates = [proof for proof in proofs if proof.get("schema") == "mimo.world2-effective-update.v1"]
    wandb = [proof for proof in proofs if "native-wandb-final" in proof.get("schema", "")]
    require(len(updates) == len(wandb) == 1, "Actual native update and W&B parent evidence required")
    identity = updates[0].get("identity", {})
    require(
        updates[0].get("passed") is True
        and identity.get("run_id") == parent["run_id"]
        and identity.get("step") == parent["step"]
        and identity.get("run_spec_sha256", "").removeprefix("sha256:") == parent["run_spec_sha256"],
        "Parent effective-update evidence identity differs",
    )
    remote = wandb[0]
    rows = [row for row in remote.get("native_history_rows", []) if row.get("training/global_step") == parent["step"]]
    require(
        remote.get("passed") is True
        and remote.get("source_commit") == SOURCE_COMMIT
        and remote.get("run_name") == parent["run_id"]
        and remote.get("run_state") == "finished"
        and remote.get("read_only") is True
        and remote.get("history_mutated") is False
        and remote.get("backfilled") is False
        and len(rows) == 1
        and rows[0].get("actor/grad_norm", 0) > 0,
        "Parent native W&B acceptance differs",
    )


def validate_parent(plan):
    parent = read_bound(plan["parent_manifest_path"], plan["parent_manifest_sha256"])
    require(
        parent.get("schema") == "mimo.native-checkpoint-manifest.v1"
        and type(parent.get("world_size")) is int
        and parent["world_size"] == 2
        and parent.get("source_commit") in (SOURCE_COMMIT, BASE_COMMIT),
        "Parent native identity differs",
    )
    if parent["source_commit"] == BASE_COMMIT:
        require(
            plan["parent_manifest_sha256"] == OLD_C4_MANIFEST_SHA
            and Path(plan["parent_manifest_path"]) == ROOT / "integration-check/r19-c4-resume-manifest-r20.json"
            and parent["checkpoint"] == str(ROOT / "runs/r19/rl-training/checkpoints/global_step_4")
            and parent["step"] == 4
            and parent["task_id"] == "001661"
            and parent["run_id"] == "mimo9b-001661-r19"
            and parent["run_spec_sha256"] == "5951ccbe2ab4c29705bed8655a949efafa598c16cd26670c2791b0544e6e1e33",
            "Only the exact accepted R19 C4 may cross this source boundary",
        )
    else:
        require(
            parent.get("source_manifest_sha256") == SOURCE_MANIFEST_SHA,
            "New parent runtime manifest differs",
        )
        validate_parent_evidence(parent)
    step, files = checkpoint_files(Path(parent["checkpoint"]))
    require(parent["files"] == files and parent["step"] == step, "Parent checkpoint changed after sealing")
    require(parent.get("inflight_tq_replay_available") is False, "No exact TQ replay is claimed")
    if parent["task_id"] != plan["task_id"]:
        probe = read_bound(plan["dataset_mechanism_proof_path"], plan["dataset_mechanism_proof_sha256"])
        require(
            probe["schema"] == "mimo.curriculum-data-resume-probe.v1"
            and probe["passed"] is True
            and probe["data_sha256"] == files["data.pt"]["sha256"]
            and probe.get("checkpoint") == parent["checkpoint"]
            and probe.get("parent_step") == parent["step"]
            and probe.get("plan", {}).get("first_training_step") == parent["step"] + 1
            and probe["native"]["cuda_initialized"] is False
            and probe["model_loaded"] is False
            and probe["original_parent_unchanged"] is True
            and probe["transfer_queue_exists"] is False
            and probe["full_bitwise_data_replay_claimed"] is False
            and probe["scope"]
            == "Synthetic distinct-task mechanism probe using real parent data.pt; "
            "not training consumption or full model resume",
            "Cross-task mechanism proof required; actual prepared dataset is checked after preparation",
        )
    return parent


def validate_inputs(plan):
    """CPU admission binds source, native parent, actual RunSpec, and independent probes."""
    from deployment.services.harbor_run_controller import RunSpec, digest
    from examples.harbor.prepare_m2_training import task_digest

    info = validate_plan(plan)
    validate_source()
    parent = validate_parent(plan)
    require(
        file_identity(plan["spec_path"])["sha256"] == plan["spec_raw_sha256"],
        "Actual authorized RunSpec bytes differ",
    )
    spec = RunSpec.model_validate_json(Path(plan["spec_path"]).read_bytes())
    require(
        spec.run_id == plan["run_id"] and spec.deadline_unix == DEADLINE and spec.max_concurrent_jobs == 2,
        "Actual RunSpec identity/deadline/capacity differs",
    )
    expected = {
        "ssh_host": "127.0.0.1",
        "ssh_port": 22,
        "ssh_user": "root",
        "ssh_key": str(PRIVATE / "cohost-r20/loopback-key"),
        "known_hosts": str(PRIVATE / "cohost-r20/known_hosts"),
        "control_port": 38880,
        "worker_port": 38881,
        "model_port": 38882,
        "remote_control_port": 38780,
        "remote_worker_port": 38781,
    }
    value = spec.model_dump(mode="json")
    require(all(str(value[k]) == str(v) for k, v in expected.items()), "R20 cohost contract differs")
    require(spec.modal_ingress is not None and spec.modal_ingress.listen_port == 38883, "R20 ingress port differs")
    template = spec.policy_template
    require(
        template["gateway_host"] == "172.24.0.2" and "gateway_port" not in template,
        "Native dynamic Gateway port required",
    )
    refs = template["task_refs"]
    require(
        len(refs) == 1
        and refs[0]["id"] == f"mimo-code-format-code-task-{plan['task_id']}"
        and task_digest(spec.task_dir) == refs[0]["sha256"],
        "Actual frozen task differs",
    )
    release = template["dsh_release"]
    require(
        release["source_sha"] == DSH_SOURCE
        and release["sdk_sha256"] == SDK_SHA
        and release["runtime_sha256"] == RUNTIME_SHA
        and release["patch_sha256s"] == []
        and release["platform"] == "linux/amd64"
        and release["profile"] == "sdk-minimal",
        "Fixed DSH release differs",
    )
    package = read_bound(plan["task_manifest_path"], plan["task_manifest_sha256"])
    require(
        package["schema"] == "dsh.mimo-code-task-package.v1"
        and package["task_ref"] == refs[0]
        and package["source_repo"] == "XiaomiMiMo/MiMo-V2.6-RL-oss"
        and package["source_revision"] == DATA_REVISION
        and package["task_id"] == f"format-code-task-{plan['task_id']}"
        and package["task_dir"] == str(spec.task_dir)
        and package["dsh_derived_image_digest"] == release["image_digest"],
        "Actual task/data/image package differs",
    )
    for name, sha in package["files"].items():
        relative = Path(name)
        require(
            not relative.is_absolute() and ".." not in relative.parts and relative.parts[0] == "task",
            "Unsafe task package path",
        )
        require(
            file_identity(spec.task_dir / Path(*relative.parts[1:]))["sha256"] == sha.removeprefix("sha256:"),
            "Actual task package file changed",
        )
    for name in ("config.json", "chat_template.jinja", "model.safetensors.index.json"):
        path = Path(MODEL) / ".cache/huggingface/download" / f"{name}.metadata"
        require(
            path.is_file() and not path.is_symlink() and path.read_text().splitlines()[0] == MODEL_REVISION,
            "Actual model revision metadata differs",
        )
    proof = read_bound(plan["http_proof_path"], plan["http_proof_sha256"])
    require(
        proof["status"] == "passed"
        and proof["cleaned_up"] is True
        and proof["training_started"] is False
        and proof["jobs_submitted"] == 0,
        "Actual clean transport proof required",
    )
    required = {
        "public_model_forward",
        "reverse_control_auth",
        "reverse_worker_auth",
        "bad_token_rejected",
        "unknown_session_rejected",
        "disabled_path_rejected",
    }
    require(
        required <= proof["checks"].keys() and all(proof["checks"][k] is True for k in required),
        "Transport/authentication checks incomplete",
    )
    require(
        proof["gateway_host"] == "172.24.0.2"
        and proof["ssh_host"] == "127.0.0.1"
        and proof["ports"]
        == dict(control=38880, worker=38881, model=38882, ingress=38883, remote_control=38780, remote_worker=38781),
        "Transport proof ports differ",
    )
    calibration = read_bound(plan["calibration_path"], plan["calibration_sha256"])
    require(
        calibration["status"] == "passed"
        and calibration["task_ref"] == refs[0]
        and calibration["dsh_release"] == release
        and calibration["rewards"] == [0.0, 1.0]
        and calibration["model_requests"] == 0
        and calibration["cleanup_confirmed"] is True,
        "Real task-specific independent verifier calibration required",
    )
    runtime_bindings = {
        "current_runtime_commit": SOURCE_COMMIT,
        "source_manifest_sha256": SOURCE_MANIFEST_SHA,
        "workspace_helper_sha256": PRODUCTION_BLOBS["uni_agent/tasks/harbor_dsh/mimo_workspace.py"],
        "packaged_verifier_sha256": PRODUCTION_BLOBS["examples/mimo_dsh_rl/verifier.py"],
        "no_shim": True,
        "private_compatibility_injection": False,
        "task_ref": refs[0],
        "immutable_package_manifest_sha256": plan["task_manifest_sha256"],
    }
    require(
        calibration.get("runtime_bindings") == runtime_bindings
        and calibration.get("production_verifier_compatibility_verified_by_this_adapter") is True
        and calibration.get("historical_evidence_reused") is False
        and calibration.get("raw_receipts_verified") == ["baseline-direct", "baseline-restored", "candidate-restored"],
        "Current task-specific production no-shim/raw-receipt calibration required",
    )
    raw_binding = calibration["raw_execution_report"]
    raw = read_bound(raw_binding["path"], raw_binding["sha256"])
    require(
        all(
            (isinstance(raw.get(key), str) and raw[key].removeprefix("sha256:") == value)
            if key.endswith("_sha256")
            else raw.get(key) == value
            for key, value in runtime_bindings.items()
        )
        and raw.get("no_shim") is True
        and raw.get("private_compatibility_injection") is False,
        "Actual raw production calibration identity differs",
    )
    cases = [raw["results"][name] for name in calibration["raw_receipts_verified"]]
    hashes = raw["source_hashes"]
    require(
        all(hashes.get(str(source_directory() / name)) == "sha256:" + sha for name, sha in PRODUCTION_BLOBS.items()),
        "Actual raw calibration did not bind the two current production source paths",
    )
    require(
        all(item["status"] == "graded" and type(item["reward"]) in (int, float) for item in cases)
        and [item["reward"] for item in cases] == [0.0, 0.0, 1.0]
        and all(type(item["resolved"]) is bool for item in cases)
        and [item["resolved"] for item in cases] == [False, False, True],
        "Actual raw verifier cases failed the independent baseline/positive gate",
    )
    require(
        "sha256:" + runtime_bindings["packaged_verifier_sha256"] in package["files"].values(),
        "Actual task package lacks the reviewed production verifier bytes",
    )
    require(
        not (ROOT / "runs" / plan["stage"] / "rl-training/checkpoints").exists(),
        "Stage refuses existing training outputs",
    )
    return info, spec, parent, digest(value)


def environment(plan, *, cpu):
    helper = runpy.run_path(str(ROOT / "audit-code/r19-preparation/mimo_r19_preparation.py"))
    proven = helper["training_environment"](ROOT)
    packages = ROOT / "env-overlays/r10-cupy/packages"
    old_source = ROOT / "run-src-r19"
    require(
        proven["PYTHONPATH"] == f"{packages}:{old_source}:{old_source / 'verl'}",
        "Retained validated overlay/source structure differs",
    )
    proven["PYTHONPATH"] = f"{packages}:{source_directory()}:{source_directory() / 'verl'}"
    value = {
        **os.environ,
        **proven,
        "CUDA_VISIBLE_DEVICES": "" if cpu else "0,1",
        "PYTHON_BIN": PYTHON,
        "STUDENT_MODEL_PATH": MODEL,
        "TOOL_PARSER": "qwen3_coder",
        "VLLM_USE_FLASHINFER_SAMPLER": "0",
        "OMP_NUM_THREADS": "2" if cpu else "4",
        "MKL_NUM_THREADS": "2",
        "PYTHONDONTWRITEBYTECODE": "1",
        "RAY_TMPDIR": str(PRIVATE / f"ray-{plan['stage']}"),
        "RAY_ADDRESS": "local",
        "WANDB_MODE": "online",
        "WANDB_ENTITY": "xdan-ai",
        "WANDB_PROJECT": "xDAN-Verl-Uni-agent-Harbor-rl-opd",
        "WANDB_NAME": plan["run_id"],
        "WANDB_RUN_ID": plan["run_id"].replace("-", ""),
        "WANDB_RESUME": "never",
        "WANDB_DIR": str(PRIVATE / f"wandb-{plan['stage']}"),
        "VERL_RL_INSIGHT_ENABLE": "1",
        "RL_INSIGHT_SERVER_URL": "http://127.0.0.1:18080",
        "MIMO_PROMETHEUS_URL": "http://127.0.0.1:9090",
    }
    for key in (
        "WANDB_DISABLED",
        "RAY_EXPERIMENTAL_NOSET_CUDA_VISIBLE_DEVICES",
        "TRAIN_FILE",
        "TEST_FILE",
        "TASK_CONFIG",
        "MAX_CONCURRENT_SESSIONS",
    ):
        value.pop(key, None)
    return value


def command(plan, parent):
    stage = plan["stage"]
    return [
        PYTHON,
        "-m",
        "examples.harbor_opd_rl.launch",
        "--mode",
        "rl",
        "--launch",
        str(PRIVATE / f"launch-{stage}/launch.json"),
        "--recipe-config",
        str(source_directory() / "examples/mimo_dsh_rl/mimo-9b-dual-colocate-observed.yaml"),
        "--experiment-name",
        plan["run_id"],
        "--observability-wrapper",
        "--observability-deadline-unix",
        str(DEADLINE),
        "--token-journal-dir",
        str(PRIVATE / f"launch-{stage}/token-journal"),
        "--total-training-steps",
        str(parent["step"] + 1),
        "--save-freq",
        "1",
        "--resume-from-path",
        parent["checkpoint"],
    ]


def prepare(plan):
    from examples.harbor.prepare_m2_training import prepare_training

    info, spec, parent, spec_sha = validate_inputs(plan)
    launch_root = Path(info["launch_root"])
    path = prepare_training(
        run_spec_path=Path(plan["spec_path"]),
        task_dir=spec.task_dir,
        output_dir=launch_root,
        task_config_path=launch_root / "task.yaml",
        registration_token_file=spec.registration_token_file,
        worker_token_file=spec.worker_token_file,
        train_count=1,
        heldout_count=1,
        max_concurrent_sessions=2,
        mimo_binding=spec.task_dir / "mimo-binding.json",
    )
    launch = json.loads(path.read_bytes())
    launch["environment"]["RUN_ROOT"] = info["run_root"]
    path.write_text(json.dumps(launch, indent=2) + "\n")
    return {
        "status": "prepared",
        "run_id": spec.run_id,
        "run_spec_sha256": spec_sha,
        "launch_sha256": file_identity(path)["sha256"],
        "parent_step": parent["step"],
        "total_training_steps": parent["step"] + 1,
        "training_started": False,
        "validation_is_independent_holdout": False,
    }


def preflight(plan):
    import importlib.metadata as metadata

    import torch
    from packaging.requirements import Requirement

    from examples.harbor_opd_rl.launch import _validate_resume, build_overrides, compose_config, preflight_training

    require(
        os.environ.get("CUDA_VISIBLE_DEVICES") == "" and not torch.cuda.is_initialized(), "CPU-only preflight required"
    )
    info, spec, parent, spec_sha = validate_inputs(plan)
    launch_path = Path(info["launch_root"]) / "launch.json"
    launch = json.loads(launch_path.read_bytes())
    require(
        launch["postprocessor"]["run_spec_sha256"] == spec_sha
        and launch["environment"]["RUN_ROOT"] == info["run_root"]
        and launch["environment"]["MAX_CONCURRENT_SESSIONS"] == "2",
        "Prepared actual inputs differ",
    )
    freeze = Path(
        "/workspace/verl-uni-agent-harbor-opd-rl/src/uni-agent/deployment/versions/uv-lanes/ua-verl-py312-vllm023.freeze.txt"
    )
    require(file_identity(freeze)["sha256"] == FREEZE_SHA, "Shared environment lock changed")
    count = 0
    for line in freeze.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "-")) or " @ " in line:
            continue
        requirement = Requirement(line)
        require(metadata.version(requirement.name) in requirement.specifier, "Installed dependency differs")
        count += 1
    require(count == 273, "Shared dependency count differs")
    source = source_directory()
    overrides = build_overrides(
        "rl",
        launch,
        os.environ,
        recipe_config=source / "examples/mimo_dsh_rl/mimo-9b-dual-colocate-observed.yaml",
        experiment_name=plan["run_id"],
    )
    overrides += [
        f"trainer.total_training_steps={parent['step'] + 1}",
        "trainer.save_freq=1",
        "trainer.resume_mode=resume_path",
        "trainer.resume_from_path=" + json.dumps(parent["checkpoint"]),
        f"++trainer.observability_deadline_unix={DEADLINE}",
        "++ray_kwargs.ray_init.runtime_env.env_vars.UNI_AGENT_TOKEN_JOURNAL_DIR=" + json.dumps(info["journal"]),
        "hydra.run.dir=" + json.dumps(str(launch_path.parent / "hydra")),
    ]
    config = compose_config(overrides)
    validate_training_config(config, plan, launch, parent)
    _validate_resume(config)
    report = preflight_training(config)
    actual_dataset = validate_actual_dataset(plan, parent, spec, launch, config)
    require(not torch.cuda.is_initialized(), "CPU preflight initialized CUDA")
    return {
        "schema": "mimo.r20-stage-preflight.v1",
        "status": "passed",
        **info,
        "source_commit": SOURCE_COMMIT,
        "source_manifest_sha256": SOURCE_MANIFEST_SHA,
        "run_spec_sha256": spec_sha,
        "parent_manifest_sha256": plan["parent_manifest_sha256"],
        "parent_step": parent["step"],
        "target_step": parent["step"] + 1,
        "launch_sha256": file_identity(launch_path)["sha256"],
        "command": command(plan, parent),
        "operator_sha256": file_identity(__file__)["sha256"],
        "recipe_sha256": file_identity(source / "examples/mimo_dsh_rl/mimo-9b-dual-colocate-observed.yaml")["sha256"],
        "package_constraints_verified": count,
        "cuda_initialized": False,
        "training_started": False,
        "report": report,
        "actual_prepared_dataset": actual_dataset,
        "inflight_tq_replay_available": False,
        "finished_at": time.time(),
    }


def validate_actual_dataset(plan, parent, spec, launch, config):
    """Run the reviewed native fetch method on the real prepared Parquet after restore."""
    import pyarrow.parquet as pq
    import torch
    from transformers import AutoTokenizer

    require(
        os.environ.get("CUDA_VISIBLE_DEVICES") == "" and not torch.cuda.is_initialized(),
        "Actual dataset probe must remain CPU-only",
    )
    helper_path = Path(plan["dataset_probe_path"])
    require(file_identity(helper_path)["sha256"] == DATASET_HELPER_SHA, "Reviewed dataset probe differs")
    helper = runpy.run_path(str(helper_path))
    data = Path(parent["checkpoint"]) / "data.pt"
    identity = file_identity(data)
    require(
        identity == parent["files"]["data.pt"] and identity["bytes"] <= 65536,
        "Bounded original parent loader state required",
    )
    state = torch.load(data, map_location="cpu", weights_only=False)
    helper["validate_state"](state)
    parquet = Path(launch["environment"]["TRAIN_FILE"])
    parquet_identity = file_identity(parquet)
    rows = pq.read_table(parquet).to_pylist()
    instruction = (spec.task_dir / "instruction.md").read_text()
    expected_prompt = [{"role": "user", "content": instruction}]
    expected_source = f"harbor/mimo-code-format-code-task-{plan['task_id']}/train"
    require(
        len(rows) == 1
        and rows[0]["prompt"] == expected_prompt
        and rows[0]["data_source"] == expected_source
        and rows[0]["uid"] == plan["run_id"] + "-train-0",
        "Prepared actual task/run identity differs",
    )
    tokenizer = AutoTokenizer.from_pretrained(MODEL, local_files_only=True)
    native = helper["probe_next_batch"](state, parquet, config.data, tokenizer)
    validate_native_dataset_sources(native["native_source_sha256"])
    require(
        native["rows"] == 1
        and native["raw_prompt"] == expected_prompt
        and native["data_source"] == expected_source
        and native["cuda_initialized"] is False,
        "Native restored dataset did not yield the actual current task",
    )
    require(
        file_identity(data) == identity and file_identity(parquet) == parquet_identity,
        "Parent loader state or prepared Parquet changed during native probe",
    )
    return {
        "schema": "mimo.actual-prepared-dataset-resume.v1",
        "status": "passed",
        "task_id": plan["task_id"],
        "run_id": plan["run_id"],
        "rows": 1,
        "data_source": expected_source,
        "uid": rows[0]["uid"],
        "prompt_sha256": hashlib.sha256(instruction.encode()).hexdigest(),
        "parquet": str(parquet),
        "parquet_sha256": parquet_identity["sha256"],
        "parent_data_sha256": identity["sha256"],
        "helper_sha256": DATASET_HELPER_SHA,
        "native_source_sha256": native["native_source_sha256"],
        "parent_unchanged": True,
        "cuda_initialized": False,
        "model_loaded": False,
        "full_bitwise_data_replay_claimed": False,
        "actual_training_consumption_verified": False,
        "epoch_plan": helper["epoch_plan"](parent["step"], parent["step"] + 1),
    }


def validate_native_dataset_sources(origins):
    manifest = read_bound(ROOT / "integration-check/source-r20-manifest.json", SOURCE_MANIFEST_SHA)
    names = (
        "verl/verl/trainer/ppo/v1/trainer_base.py",
        "verl/verl/trainer/ppo/utils.py",
        "verl/verl/utils/dataset/rl_dataset.py",
    )
    expected = {str(source_directory() / name): manifest["files"][name]["sha256"] for name in names}
    torchdata = str(
        Path(PYTHON).parents[1] / "lib/python3.12/site-packages/torchdata/stateful_dataloader/stateful_dataloader.py"
    )
    expected[torchdata] = "426c3ef475481165f9a7d44238040f81de213a4e8ee58ad8fe734e52a2717830"
    require(origins == expected, "Actual native dataset imports do not match current runtime/locked TorchData")
    for path, sha in origins.items():
        require(file_identity(path)["sha256"] == sha, "Actual native dataset source bytes differ")


def validate_training_config(config, plan, launch, parent):
    """Validate what native Hydra actually consumes, including inherited-env overrides."""
    trainer, rollout = config.trainer, config.actor_rollout_ref.rollout
    framework = rollout.custom.agent_framework
    require(
        trainer.n_gpus_per_node == 2
        and trainer.nnodes == 1
        and trainer.v1.trainer_mode == "colocate_async"
        and rollout.nnodes == 0
        and rollout.n_gpus_per_node == 2
        and rollout.tensor_model_parallel_size == 1
        and rollout.data_parallel_size == 1
        and rollout.pipeline_model_parallel_size == 1
        and rollout.checkpoint_engine.backend == "naive"
        and rollout.n == 4
        and rollout.max_num_seqs == 2
        and framework.agent_runners.task.max_concurrent_sessions == 2
        and config.actor_rollout_ref.model.path == MODEL,
        "Actual native world2 topology differs",
    )
    prepared = launch["environment"]
    require(
        config.data.train_files == prepared["TRAIN_FILE"]
        and config.data.val_files == prepared["TEST_FILE"]
        and framework.agent_runners.task.runner_kwargs.task_config_path == prepared["TASK_CONFIG"]
        and trainer.default_local_dir == str(ROOT / "runs" / plan["stage"] / "rl-training/checkpoints"),
        "Actual task/data/output path differs",
    )
    require(
        trainer.resume_mode == "resume_path"
        and trainer.resume_from_path == parent["checkpoint"]
        and trainer.total_training_steps == parent["step"] + 1
        and trainer.save_freq == 1
        and trainer.observability_deadline_unix == DEADLINE
        and trainer.experiment_name == plan["run_id"]
        and list(trainer.logger) == ["console", "wandb", "rl_insight"]
        and config.ray_kwargs.ray_init.runtime_env.env_vars.UNI_AGENT_TOKEN_JOURNAL_DIR
        == str(PRIVATE / f"launch-{plan['stage']}/token-journal"),
        "Actual resume/identity/observability differs",
    )
    require(
        framework.trajectory_postprocessor_kwargs.run_id == plan["run_id"]
        and framework.trajectory_postprocessor_kwargs.run_spec_sha256 == launch["postprocessor"]["run_spec_sha256"],
        "Actual receipt admission differs",
    )


def supervise(plan):
    from deployment.services.harbor_run_controller import read_token
    from deployment.services.harbor_training_supervisor import (
        NoRedirect,
        validate_health,
    )
    from deployment.services.harbor_training_supervisor import (
        supervise as native_supervise,
    )

    info, spec, parent, spec_sha = validate_inputs(plan)
    proof = read_bound(plan["preflight_path"], plan["preflight_sha256"])
    launch_path = Path(info["launch_root"]) / "launch.json"
    actual_command = command(plan, parent)
    require(
        proof["status"] == "passed"
        and proof["run_id"] == plan["run_id"]
        and proof["operator_sha256"] == file_identity(__file__)["sha256"]
        and proof["launch_sha256"] == file_identity(launch_path)["sha256"]
        and proof["run_spec_sha256"] == spec_sha
        and proof["command"] == actual_command
        and proof["parent_manifest_sha256"] == plan["parent_manifest_sha256"],
        "Actual preflight binding differs",
    )
    env = environment(plan, cpu=False)
    Path(env["WANDB_DIR"]).mkdir(mode=0o700, exist_ok=False)
    launch = json.loads(launch_path.read_bytes())
    route = launch["registration"]
    token = read_token(Path(route["token_file"]))
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    request = urllib.request.Request(
        route["controller_url"] + "/v1/runs/" + spec.run_id + "/status", headers={"Authorization": "Bearer " + token}
    )

    def health():
        with opener.open(request, timeout=5) as response:
            validate_health(
                json.loads(response.read(16385)),
                {"run_id": spec.run_id, "controller_id": spec.controller_id, "run_spec_sha256": spec_sha},
            )

    started_at = time.time()
    result = native_supervise(
        actual_command,
        source_directory(),
        env,
        launch_path.parent,
        health,
        wall_seconds=validate_window(plan["deadline_unix"], time.time()),
    )
    return {
        **result,
        "status": "exited",
        "run_id": plan["run_id"],
        "parent_step": parent["step"],
        "target_step": parent["step"] + 1,
        "started_at": started_at,
        "finished_at": time.time(),
        "deadline_unix": DEADLINE,
        "source_commit": SOURCE_COMMIT,
        "source_manifest_sha256": SOURCE_MANIFEST_SHA,
        "parent_manifest_sha256": plan["parent_manifest_sha256"],
        "preflight_sha256": plan["preflight_sha256"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("seal", "prepare", "preflight", "supervise"))
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--provenance", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.action == "seal":
        result = seal_parent(args.checkpoint, args.output, json.loads(args.provenance.read_bytes()))
    else:
        plan = json.loads(args.plan.read_bytes())
        result = {"prepare": prepare, "preflight": preflight, "supervise": supervise}[args.action](plan)
        if args.output is not None:
            write_new(args.output, result)
    print(json.dumps({"status": result.get("status", "sealed"), "training_started": args.action == "supervise"}))
    if args.action == "supervise":
        raise SystemExit(0 if result["exit_code"] == 0 else 1)


if __name__ == "__main__":
    main()
