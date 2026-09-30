"""Stage reviewed r19 operator scripts only; stage never prepares or starts a run."""

import argparse
import ast
import hashlib
import json
import math
import os
import re
from pathlib import Path

ROOT = Path("/workspace/mimo-dsh-rl-20260928")
# Explicit authorization is required on every process boundary; never now + budget.
AUTHORIZED_DEADLINE = 1790752269  # 2026-09-30 07:11:09 UTC, fixed user authorization.
MAX_RUN_SECONDS = 25200
COHOST_FIELDS = {
    "ssh_host": "127.0.0.1",
    "ssh_port": 22,
    "ssh_user": "root",
    "ssh_key": "/root/mimo-private/cohost-r19/loopback-key",
    "known_hosts": "/root/mimo-private/cohost-r19/known_hosts",
    "control_port": 38860,
    "worker_port": 38861,
    "model_port": 38862,
    "remote_control_port": 38760,
    "remote_worker_port": 38761,
}
GATEWAY_HOST = "172.24.0.2"
R17_SOURCE_COMMIT = "4a499cfcf8e5fa361b20f009d2c1472e7b49dd73"
R17_RUN_SPEC = "sha256:cba3a3b4dfb5454b0533169588be1b4ef7b11aaedff01f3c1a7a5fb1ca07cf8c"
CHECKPOINT_FILES = (
    "data.pt",
    "actor/fsdp_config.json",
    "actor/model_world_size_2_rank_0.pt",
    "actor/optim_world_size_2_rank_0.pt",
    "actor/extra_state_world_size_2_rank_0.pt",
    "actor/model_world_size_2_rank_1.pt",
    "actor/optim_world_size_2_rank_1.pt",
    "actor/extra_state_world_size_2_rank_1.pt",
)
PYTHON = "/workspace/verl-uni-agent-harbor-opd-rl/envs/ua-verl-py312-vllm023-ws1/bin/python"
NCCL_LIB = str(Path(PYTHON).parents[1] / "lib/python3.12/site-packages/nvidia/nccl/lib")
NATIVE_SOURCE = {
    "verl/verl/checkpoint_engine/base.py": "cdbfccaf6aca586e250ce25327ca181d53ff3acaa1f3f0ebef0651b815fc05b1",
    "verl/verl/trainer/ppo/v1/trainer_colocate_async.py": (
        "efc3fa946cfb24ce4727b5ad92d6ac7ecffd961c5afd0d9d605436c7dbf7a025"
    ),
    "verl/verl/trainer/ppo/v1/trainer_base.py": "e2ca9b9af567fbd0c99224475fafec7c881bc3e3ff730fdc6e8825c844b34e58",
}
OVERLAY_SHA = "ef5fb1393db7aa8ee8d80fb2e2d4484650790adb15cd527e8778845aeb281967"
TEMPLATE_SHA = {
    "prepare": "9cf593482a12aceb24c0bcbe7c051429482da3fcd0e3d322dac6e3a20b004074",
    "driver": "575d5e4a91378cb23522b4411dbbbe116940b5173cca4eddb361671b13a40196",
    "wrapper": "5a90973107bf13f9ab97273aa504844702b1db836192d899bbc8bdd5fc551600",
}
REQUIRED_SOURCE = {
    *NATIVE_SOURCE,
    "docs/verl-uni-agent-harbor-opd-rl/mimo_dual_colocate_probe.py",
    "docs/verl-uni-agent-harbor-opd-rl/mimo_observability.py",
    "deployment/services/harbor_run_controller.py",
    "uni_agent/tasks/harbor_dsh/ledger.py",
    "uni_agent/tasks/harbor_dsh/worker.py",
    "uni_agent/gateway/session/session.py",
    "uni_agent/gateway/session/token_journal.py",
    "examples/harbor_opd_rl/launch.py",
    "examples/mimo_dsh_rl/mimo-9b-dual-colocate-observed.yaml",
    "verl/verl/workers/engine/fsdp/transformer_impl.py",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate_cohost_spec(value):
    """An existing SSH transport on one host still needs six noncolliding ports."""
    for key, expected in COHOST_FIELDS.items():
        require(value.get(key) == expected, "Cohost spec differs: " + key)
    require(value["modal_ingress"]["listen_port"] == 38863, "Cohost ingress differs")
    require(value["policy_template"]["gateway_host"] == GATEWAY_HOST, "Native Gateway host differs")
    require("gateway_port" not in value["policy_template"], "Native Gateway port must remain dynamic")
    ports = [value[key] for key in COHOST_FIELDS if key.endswith("_port") and key != "ssh_port"]
    ports.append(value["modal_ingress"]["listen_port"])
    require(len(set(ports)) == 6, "Cohost forwarding ports collide")
    return {**COHOST_FIELDS, "ingress_port": 38863, "gateway_host": GATEWAY_HOST}


def validate_resume_checkpoint(root, expected_sha256):
    """Only an explicitly sealed, complete same-world-two C3 can be restored."""
    checkpoint = root / "runs/r17/rl-training/checkpoints/global_step_3"
    manifest_path = root / "integration-check/r17-c3-resume-manifest.json"
    require(manifest_path.is_file() and not manifest_path.is_symlink(), "Stable C3 manifest missing")
    manifest_raw = manifest_path.read_bytes()
    require(
        isinstance(expected_sha256, str) and re.fullmatch(r"[0-9a-f]{64}", expected_sha256),
        "Explicit checkpoint manifest hash required",
    )
    require(hashlib.sha256(manifest_raw).hexdigest() == expected_sha256, "Checkpoint manifest hash mismatch")
    manifest = json.loads(manifest_raw)
    require(
        manifest["schema"] == "mimo.native-checkpoint-manifest.v1"
        and manifest["run_id"] == "mimo9b-001661-r17"
        and manifest["source_commit"] == R17_SOURCE_COMMIT
        and manifest["run_spec_sha256"] == R17_RUN_SPEC
        and type(manifest["step"]) is int
        and manifest["step"] == 3
        and type(manifest["world_size"]) is int
        and manifest["world_size"] == 2
        and manifest["checkpoint"] == str(checkpoint),
        "C3 manifest identity or world size mismatch",
    )
    files = manifest["files"]
    require(set(CHECKPOINT_FILES) <= files.keys(), "Missing native world-two checkpoint component")
    for name, item in files.items():
        relative = Path(name)
        require(not relative.is_absolute() and ".." not in relative.parts, "Invalid checkpoint path")
        path = checkpoint / relative
        require(
            path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(checkpoint.resolve()),
            "Incomplete or unsafe world-two checkpoint",
        )
        before = path.stat()
        require(
            type(item["bytes"]) is int and item["bytes"] > 0 and path.stat().st_size == item["bytes"],
            "Checkpoint size mismatch",
        )
        with path.open("rb") as stream:
            require(hashlib.file_digest(stream, "sha256").hexdigest() == item["sha256"], "Checkpoint hash mismatch")
        after = path.stat()
        require(
            (before.st_size, before.st_mtime_ns, before.st_ino) == (after.st_size, after.st_mtime_ns, after.st_ino),
            "Checkpoint changed during hashing",
        )
    config = json.loads((checkpoint / "actor/fsdp_config.json").read_bytes())
    require(
        type(config["world_size"]) is int
        and config["world_size"] == 2
        and type(config.get("FSDP_version")) is int
        and config["FSDP_version"] == 1,
        "Checkpoint FSDP version or world size differs",
    )
    latest = checkpoint.parent / "latest_checkpointed_iteration.txt"
    require(latest.is_file() and not latest.is_symlink() and latest.read_text().strip() == "3", "C3 not committed")
    require(manifest_path.read_bytes() == manifest_raw, "Checkpoint manifest changed during validation")
    return checkpoint, hashlib.sha256(manifest_raw).hexdigest()


def validate_runtime(root, mode, source_commit, now, *, deadline_unix=None, resume_manifest_sha256=None):
    require(mode == "resume", "Explicit resume mode required; no fresh fallback")
    require(isinstance(source_commit, str) and re.fullmatch(r"[0-9a-f]{40}", source_commit), "Full commit required")
    require(type(now) in (int, float) and math.isfinite(now), "Invalid clock")
    require(
        type(deadline_unix) is int and deadline_unix == AUTHORIZED_DEADLINE, "Explicit authorized deadline required"
    )
    require(2700 <= deadline_unix - now <= MAX_RUN_SECONDS, "Insufficient or unauthorized absolute run window")
    source = root / "run-src-r19"
    manifest = json.loads((root / "integration-check/source-r19-manifest.json").read_bytes())
    require(manifest["git_commit"] == source_commit, "Frozen source commit mismatch")
    files = manifest["files"]
    require(REQUIRED_SOURCE <= files.keys(), "Required source file missing from freeze")
    for name, identity in files.items():
        relative = Path(name)
        require(not relative.is_absolute() and ".." not in relative.parts, "Invalid source path")
        path = source / relative
        require(
            path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(source.resolve()),
            "Invalid frozen source file",
        )
        raw = path.read_bytes()
        require(
            len(raw) == identity["bytes"] and hashlib.sha256(raw).hexdigest() == identity["sha256"],
            "Source hash mismatch",
        )
    checkpoint_root = root / "runs/r19/rl-training/checkpoints"
    require(not checkpoint_root.exists(), "Independent resume refuses an existing R19 checkpoint directory")
    checkpoint, checkpoint_sha = validate_resume_checkpoint(root, resume_manifest_sha256)
    flags = [
        "--total-training-steps",
        "4",
        "--save-freq",
        "1",
        "--observability-deadline-unix",
        str(deadline_unix),
        "--token-journal-dir",
        "/root/mimo-private/launch-r19/token-journal",
        "--resume-from-path",
        str(checkpoint),
    ]
    return {
        "mode": mode,
        "source_commit": source_commit,
        "deadline_unix": deadline_unix,
        "controller_max_run_seconds": MAX_RUN_SECONDS,
        "wall_clock_seconds": int(deadline_unix - now - 180),
        "training_flags": flags,
        "resume_manifest_sha256": checkpoint_sha,
    }


def runtime_gate():
    import time

    deadline = os.environ.get("MIMO_R19_DEADLINE_UNIX", "")
    require(re.fullmatch(r"[0-9]{10}", deadline), "Explicit authorized deadline environment required")
    return validate_runtime(
        ROOT,
        os.environ.get("MIMO_R19_MODE"),
        os.environ.get("MIMO_R19_SOURCE_COMMIT"),
        time.time(),
        deadline_unix=int(deadline),
        resume_manifest_sha256=os.environ.get("MIMO_R19_RESUME_MANIFEST_SHA256"),
    )


def validate_ipc_evidence(root):
    """Two isolated native IPC lanes prove transport only, not FSDP training."""
    source = root / "run-src-r19"
    historical = json.loads((root / "gpu-preflight-r9/status.json").read_bytes())
    require(
        historical["status"] == "passed"
        and historical["exit_code"] == 0
        and historical["tests"] == 1
        and all(historical[key] == 0 for key in ("skipped", "errors", "failures")),
        "Historical naive IPC baseline did not pass",
    )
    status = json.loads((root / "integration-check/dual-colocate-r13-v2/status.json").read_bytes())
    operator = source / "docs/verl-uni-agent-harbor-opd-rl/mimo_dual_colocate_probe.py"
    require(
        operator.is_file()
        and not operator.is_symlink()
        and hashlib.sha256(operator.read_bytes()).hexdigest() == status["operator_sha256"],
        "Dual IPC operator source changed",
    )
    require(
        status["schema"] == "mimo.dual-colocate-ipc.v1"
        and status["status"] == "passed"
        and status["mode"] == "colocate_async"
        and status["backend"] == "naive"
        and status["gpu_indexes"] == [0, 1]
        and status["tests"] == 4
        and all(status[key] == 0 for key in ("skipped", "errors", "failures")),
        "Dual GPU naive IPC preflight not passed",
    )
    lanes = status["lanes"]
    require(
        len(lanes) == 2
        and [row["gpu_index"] for row in lanes] == [0, 1]
        and len({row["gpu_uuid"] for row in lanes}) == 2
        and all(row["gpu_uuid"] and row["tests"] == 2 for row in lanes)
        and all(row[key] == 0 for row in lanes for key in ("skipped", "errors", "failures")),
        "Distinct dual GPU IPC lanes required",
    )
    hashes = status["source_sha256"]
    require(NATIVE_SOURCE.items() <= hashes.items(), "Native colocate source identity changed")
    for name, expected in hashes.items():
        relative = Path(name)
        require(not relative.is_absolute() and ".." not in relative.parts, "Invalid IPC source path")
        path = source / relative
        require(
            path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(source.resolve()),
            "Invalid IPC source file",
        )
        require(hashlib.sha256(path.read_bytes()).hexdigest() == expected, "IPC source changed")
    return status


def training_environment(root):
    """Bind native dual-GPU naive IPC evidence; the retained overlay is not transport proof."""
    source = root / "run-src-r19"
    overlay = root / "env-overlays/r10-cupy"
    packages = overlay / "packages"
    validate_ipc_evidence(root)
    raw = (overlay / "manifest.json").read_bytes()
    require(hashlib.sha256(raw).hexdigest() == OVERLAY_SHA, "Overlay manifest changed")
    manifest = json.loads(raw)
    require(
        manifest["schema_version"] == 1
        and manifest["overlay_path"] == str(packages)
        and manifest["python"] == PYTHON
        and manifest["env"] == {"PYTHONPATH_PREFIX": str(packages), "LD_LIBRARY_PATH_PREFIX": NCCL_LIB},
        "Unreviewed overlay environment",
    )
    require(bool(manifest["files"]), "Empty overlay")
    for item in manifest["files"]:
        relative = Path(item["path"])
        require(not relative.is_absolute() and ".." not in relative.parts, "Invalid overlay path")
        path = packages / relative
        require(
            path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(packages.resolve()),
            "Invalid overlay file",
        )
        raw = path.read_bytes()
        require(len(raw) == item["bytes"] and hashlib.sha256(raw).hexdigest() == item["sha256"], "Overlay file changed")
    return {"PYTHONPATH": f"{packages}:{source}:{source / 'verl'}", "LD_LIBRARY_PATH": NCCL_LIB}


def replace_checked(text, old, new, count=1):
    require(text.count(old) == count, "Reviewed template fragment changed")
    return text.replace(old, new)


def observability_environment():
    """Only nonsecret identities; authentication remains in the existing private netrc/env."""
    return {
        "WANDB_MODE": "online",
        "WANDB_ENTITY": "xdan-ai",
        "WANDB_PROJECT": "xDAN-Verl-Uni-agent-Harbor-rl-opd",
        "WANDB_NAME": "mimo9b-001661-r19",
        "WANDB_RUN_ID": "mimo9b001661r19",
        "WANDB_RESUME": "never",
        "WANDB_DIR": "/root/mimo-private/wandb-r19",
        "VERL_RL_INSIGHT_ENABLE": "1",
        "RL_INSIGHT_SERVER_URL": "http://127.0.0.1:18080",
        "MIMO_PROMETHEUS_URL": "http://127.0.0.1:9090",
    }


def render_scripts(templates):
    for name, expected in TEMPLATE_SHA.items():
        require(hashlib.sha256(templates[name].encode()).hexdigest() == expected, f"Unreviewed {name} template")
    counts = {"prepare": 34, "driver": 21, "wrapper": 5}
    edited = {name: replace_checked(text, "r12", "r19", counts[name]) for name, text in templates.items()}
    prepare = replace_checked(edited["prepare"], "R12", "R19", 4)
    prepare = replace_checked(prepare, "private / 'run-spec-r1.json'", "private / 'run-spec-r18.json'")
    for old, new in (
        (
            "control_port=38680, worker_port=38681, model_port=38682",
            "control_port=38860, worker_port=38861, model_port=38862",
        ),
        ("remote_control_port=38680, remote_worker_port=38681", "remote_control_port=38760, remote_worker_port=38761"),
        ("listen_port'] = 38683", "listen_port'] = 38863"),
    ):
        prepare = replace_checked(prepare, old, new)
    prepare = replace_checked(
        prepare,
        "value.update(run_id=",
        "value.update(max_concurrent_jobs=2,run_id=",
    )
    prepare = replace_checked(
        prepare,
        "spec_raw = spec.model_dump(mode='json')",
        (
            "spec_raw = spec.model_dump(mode='json')\n"
            "assert spec.max_concurrent_jobs == spec_raw['max_concurrent_jobs'] == 2"
        ),
    )
    prepare = replace_checked(
        prepare,
        "max_concurrent_sessions=1,train_count=1,heldout_count=1",
        "max_concurrent_sessions=2,train_count=1,heldout_count=1",
    )
    prepare = replace_checked(
        prepare,
        "value=json.loads(path.read_text())",
        "value=json.loads(path.read_text())\nassert value['environment']['MAX_CONCURRENT_SESSIONS'] == '2'",
    )
    prepare = replace_checked(
        prepare,
        "'MIMO_R19_SOURCE_COMMIT=' + os.environ['MIMO_R19_SOURCE_COMMIT'],",
        "'MIMO_R19_SOURCE_COMMIT=' + os.environ['MIMO_R19_SOURCE_COMMIT'], "
        "'MIMO_R19_DEADLINE_UNIX=' + os.environ['MIMO_R19_DEADLINE_UNIX'], "
        "'MIMO_R19_RESUME_MANIFEST_SHA256=' + os.environ['MIMO_R19_RESUME_MANIFEST_SHA256'],",
    )
    prepare = replace_checked(
        prepare,
        "['env', 'CUDA_VISIBLE_DEVICES=',",
        "['env', 'CUDA_VISIBLE_DEVICES=', 'PYTHONDONTWRITEBYTECODE=1', 'OMP_NUM_THREADS=2', 'MKL_NUM_THREADS=2',",
    )
    # The cohost CPU child hashes a real 19 GB checkpoint before imports.
    # This only bounds the child; it cannot extend the absolute run deadline.
    prepare = replace_checked(prepare, "timeout=120, check=True)", "timeout=300, check=True)")
    discovery = """discovery = json.loads((private / 'gpu-discovery-r8.json').read_text())
# Reuse verified SSH host identity, never the expired r8 lease.
value['ssh_host'] = discovery['ssh_host']
value['ssh_port'] = discovery['ssh_port']
value['policy_template']['gateway_host'] = discovery['gateway_host']"""
    prepare = replace_checked(
        prepare,
        discovery,
        "value.update(" + repr(COHOST_FIELDS) + ")\nvalue['policy_template']['gateway_host'] = " + repr(GATEWAY_HOST),
    )
    prepare = replace_checked(
        prepare,
        "value['known_hosts'] = str(private / 'gpu-known-hosts-r8')",
        "runpy.run_path(str(root/'audit-code/r19-preparation/mimo_r19_preparation.py'))['validate_cohost_spec'](value)",
    )
    transfer = """ssh_options = ['-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15', '-o', 'StrictHostKeyChecking=yes',
               '-o', 'UserKnownHostsFile=' + str(private / 'gpu-known-hosts-r8'),
               '-i', str(private / 'controller-key')]
target = spec.ssh_user + '@' + spec.ssh_host
for name in ('run-spec-r19.json', 'registration-token-r19', 'worker-token-r19'):
    subprocess.run(['scp', '-q', *ssh_options, '-P', str(spec.ssh_port), str(private / name),
                    target + ':' + str(private / name)], check=True, timeout=45)
"""
    prepare = replace_checked(prepare, transfer, "# Cohost preparation uses the existing private files directly.\n")
    second_task = """prepare_task(json.loads((root/'audit-code/selected/format-code-task-001661.row.json').read_text()),
    output=task_root,image_mapping=load_image_mapping(root/'source/image-mapping.jsonl'),
    image_binding=json.loads((root/'image-verify-20260928-r1/image-binding.json').read_text()),
    source_revision='639865fd3374018d6cb29b9fb82dd531406fcf5f',gateway_origin='https://mimo9b-rl.xdan.work')"""
    prepare = replace_checked(
        prepare, second_task, "# The parent prepared this exact local task once; verify its digest below."
    )
    prepare = replace_checked(
        prepare,
        "subprocess.run(['ssh', *ssh_options, '-p', str(spec.ssh_port), target, command],",
        "subprocess.run(shlex.split(command),",
    )
    old_gate = """ipc = json.loads((root/'gpu-preflight-r10/status.json').read_text())
assert ipc['status'] == 'passed' and ipc['tests'] == 2
assert ipc['mode'] == 'separate_async' and ipc['backend'] == 'nccl'
assert all(ipc[key] == 0 for key in ('skipped','errors','failures'))"""
    new_gate = (
        "runpy.run_path(str(root/'audit-code/r19-preparation/mimo_r19_preparation.py'))['validate_ipc_evidence'](root)"
    )
    driver = replace_checked(edited["driver"], old_gate, new_gate)
    wrapper = replace_checked(edited["wrapper"], "mimo-9b-observed.yaml", "mimo-9b-dual-colocate-observed.yaml")
    result = {
        "prepare-r19.py": prepare,
        "launch-r19-driver.py": driver,
        "mimo-supervised-native-r19.py": wrapper,
    }
    for name, text in result.items():
        ast.parse(text, filename=name)
    return result


def stage(output, templates):
    scripts = render_scripts(templates)
    scripts["mimo_r19_preparation.py"] = Path(__file__).read_text()
    scripts["preflight-r19.py"] = Path(__file__).with_name("mimo_r19_preflight.py").read_text()
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    hashes = {}
    for name, text in scripts.items():
        descriptor = os.open(output / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            stream.write(text)
        hashes[name] = hashlib.sha256(text.encode()).hexdigest()
    manifest = dict(
        schema="mimo.r19-script-preparation.v1", files=hashes, training_started=False, templates=TEMPLATE_SHA
    )
    descriptor = os.open(output / "scripts-manifest.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        stream.write(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-template", type=Path, required=True)
    parser.add_argument("--driver-template", type=Path, required=True)
    parser.add_argument("--wrapper-template", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    templates = {name: getattr(args, name + "_template").read_text() for name in TEMPLATE_SHA}
    print(json.dumps(stage(args.output, templates), sort_keys=True))


if __name__ == "__main__":
    main()
