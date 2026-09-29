"""Stage reviewed r13 operator scripts only; stage never prepares or starts a run."""

import argparse
import ast
import hashlib
import json
import math
import os
import re
from pathlib import Path

ROOT = Path("/workspace/mimo-dsh-rl-20260928")
# r10 needed about 46 minutes including startup. Require at least 45 minutes;
# this is an admission estimate, never a promise or an extension of the deadline.
# User extended the previous absolute stop by six hours. Generic controllers
# retain a six-hour per-run cap, making this run eligible at 13:16:41 UTC.
DEADLINE = 1790709401  # 2026-09-29 19:16:41 UTC; never reset on restart.
MAX_RUN_SECONDS = 21600
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
    "examples/harbor_opd_rl/launch.py",
    "examples/mimo_dsh_rl/mimo-9b-dual-colocate-observed.yaml",
    "verl/verl/workers/engine/fsdp/transformer_impl.py",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate_runtime(root, mode, source_commit, now):
    require(mode == "fresh", "Explicit fresh mode required; rank-one resume is forbidden")
    require(isinstance(source_commit, str) and re.fullmatch(r"[0-9a-f]{40}", source_commit), "Full commit required")
    require(type(now) in (int, float) and math.isfinite(now), "Invalid clock")
    require(2700 <= DEADLINE - now <= MAX_RUN_SECONDS, "Insufficient or unauthorized absolute run window")
    source = root / "run-src-r13"
    manifest = json.loads((root / "integration-check/source-r13-manifest.json").read_bytes())
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
    checkpoint_root = root / "runs/r13/rl-training/checkpoints"
    require(not checkpoint_root.exists(), "Fresh run refuses existing checkpoint directory")
    flags = ["--total-training-steps", "2", "--save-freq", "1"]
    return {
        "mode": mode,
        "source_commit": source_commit,
        "deadline_unix": DEADLINE,
        "controller_max_run_seconds": MAX_RUN_SECONDS,
        "wall_clock_seconds": int(DEADLINE - now - 180),
        "training_flags": flags,
    }


def runtime_gate():
    import time

    return validate_runtime(
        ROOT, os.environ.get("MIMO_R13_MODE"), os.environ.get("MIMO_R13_SOURCE_COMMIT"), time.time()
    )


def validate_ipc_evidence(root):
    """Two isolated native IPC lanes prove transport only, not FSDP training."""
    source = root / "run-src-r13"
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
    source = root / "run-src-r13"
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
        "WANDB_NAME": "mimo9b-001661-r13",
        "WANDB_RUN_ID": "mimo9b001661r13",
        "WANDB_RESUME": "never",
        "WANDB_DIR": "/root/mimo-private/wandb-r13",
        "VERL_RL_INSIGHT_ENABLE": "1",
        "RL_INSIGHT_SERVER_URL": "http://127.0.0.1:18080",
        "MIMO_PROMETHEUS_URL": "http://127.0.0.1:9090",
    }


def render_scripts(templates):
    for name, expected in TEMPLATE_SHA.items():
        require(hashlib.sha256(templates[name].encode()).hexdigest() == expected, f"Unreviewed {name} template")
    counts = {"prepare": 34, "driver": 21, "wrapper": 5}
    edited = {name: replace_checked(text, "r12", "r13", counts[name]) for name, text in templates.items()}
    prepare = replace_checked(edited["prepare"], "R12", "R13", 4)
    for old, new, count in ((38680, 38690, 2), (38681, 38691, 2), (38682, 38692, 1), (38683, 38693, 1)):
        prepare = replace_checked(prepare, str(old), str(new), count)
    old_gate = """ipc = json.loads((root/'gpu-preflight-r10/status.json').read_text())
assert ipc['status'] == 'passed' and ipc['tests'] == 2
assert ipc['mode'] == 'separate_async' and ipc['backend'] == 'nccl'
assert all(ipc[key] == 0 for key in ('skipped','errors','failures'))"""
    new_gate = (
        "runpy.run_path(str(root/'audit-code/r13-preparation/mimo_r13_preparation.py'))['validate_ipc_evidence'](root)"
    )
    driver = replace_checked(edited["driver"], old_gate, new_gate)
    wrapper = replace_checked(edited["wrapper"], "mimo-9b-observed.yaml", "mimo-9b-dual-colocate-observed.yaml")
    result = {
        "prepare-r13.py": prepare,
        "launch-r13-driver.py": driver,
        "mimo-supervised-native-r13.py": wrapper,
    }
    for name, text in result.items():
        ast.parse(text, filename=name)
    return result


def stage(output, templates):
    scripts = render_scripts(templates)
    scripts["mimo_r13_preparation.py"] = Path(__file__).read_text()
    scripts["preflight-r13.py"] = Path(__file__).with_name("mimo_r13_preflight.py").read_text()
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    hashes = {}
    for name, text in scripts.items():
        descriptor = os.open(output / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            stream.write(text)
        hashes[name] = hashlib.sha256(text.encode()).hexdigest()
    manifest = dict(
        schema="mimo.r13-script-preparation.v1", files=hashes, training_started=False, templates=TEMPLATE_SHA
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
