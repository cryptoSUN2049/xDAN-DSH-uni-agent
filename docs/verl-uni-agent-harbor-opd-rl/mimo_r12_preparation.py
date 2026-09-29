"""Stage reviewed r12 operator scripts only; stage never prepares or starts a run."""

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
NATIVE_ENGINE = "verl/verl/checkpoint_engine/nccl_checkpoint_engine.py"
TEMPLATE_SHA = {
    "prepare": "f3bd1afdd9278035498cced4e1e5427c862af94af1baa7b851039ca555d8867d",
    "driver": "1963a32cc654b69b3bfc6ee0f54459860cdafe85b76e5dc1126fa46663c79f21",
    "wrapper": "36b26c4b5cec6af589bc8d75b34b8498e77dd89a121fe83974b16ffecb4a424f",
}
REQUIRED_SOURCE = {
    NATIVE_ENGINE,
    "docs/verl-uni-agent-harbor-opd-rl/mimo_observability.py",
    "deployment/services/harbor_run_controller.py",
    "examples/harbor_opd_rl/launch.py",
    "examples/mimo_dsh_rl/mimo-9b-observed.yaml",
    "verl/verl/workers/engine/fsdp/transformer_impl.py",
}

CHECKPOINT_FILES = (
    "data.pt",
    "actor/model_world_size_1_rank_0.pt",
    "actor/optim_world_size_1_rank_0.pt",
    "actor/extra_state_world_size_1_rank_0.pt",
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate_runtime(root, mode, source_commit, now):
    require(mode in ("resume",), "Explicit resume mode required; no fresh fallback")
    require(isinstance(source_commit, str) and re.fullmatch(r"[0-9a-f]{40}", source_commit), "Full commit required")
    require(type(now) in (int, float) and math.isfinite(now), "Invalid clock")
    require(2700 <= DEADLINE - now <= MAX_RUN_SECONDS, "Insufficient or unauthorized absolute run window")
    source = root / "run-src-r12"
    manifest = json.loads((root / "integration-check/source-r12-manifest.json").read_bytes())
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
    flags = ["--total-training-steps", "4", "--save-freq", "1"]
    checkpoint = root / "runs/r10/rl-training/checkpoints/global_step_3"
    for name in CHECKPOINT_FILES:
        path = checkpoint / name
        require(
            path.is_file()
            and not path.is_symlink()
            and path.stat().st_size > 0
            and path.resolve().is_relative_to(checkpoint.resolve()),
            "Incomplete r10 C3 checkpoint",
        )
    latest = checkpoint.parent / "latest_checkpointed_iteration.txt"
    require(latest.is_file() and latest.read_text().strip() == "3", "Uncommitted r10 C3 checkpoint")
    flags += ["--resume-from-path", str(checkpoint)]
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
        ROOT, os.environ.get("MIMO_R12_MODE"), os.environ.get("MIMO_R12_SOURCE_COMMIT"), time.time()
    )


def training_environment(root):
    """Require native two-GPU evidence and the exact isolated dependency overlay."""
    source = root / "run-src-r12"
    overlay = root / "env-overlays/r10-cupy"
    packages = overlay / "packages"
    status = json.loads((root / "gpu-preflight-r10/status.json").read_bytes())
    require(
        status["status"] == "passed"
        and status["mode"] == "separate_async"
        and status["backend"] == "nccl"
        and status["tests"] == 2
        and status["versions_per_test"] == 3
        and all(status[key] == 0 for key in ("skipped", "errors", "failures")),
        "Native NCCL preflight not passed",
    )
    results = status["results"]
    require(len(results) == 2 and [row["rebuild_group"] for row in results] == [False, True], "Missing NCCL cases")
    for row in results:
        identities = row["identities"]
        require(len(identities) == 2 and len({item["uuid"] for item in identities}) == 2, "Distinct GPUs required")
        require(len(row["rounds"]) == 3, "Missing weight versions")
        for version, pair in zip((2, 3, 4), row["rounds"], strict=True):
            require(
                len(pair) == 2
                and all(item["version"] == version for item in pair)
                and pair[1]["exact_equal"] is True
                and pair[0]["sent"] == pair[1]["tensors"] == 3,
                "Weight transport mismatch",
            )
    require(
        hashlib.sha256((source / NATIVE_ENGINE).read_bytes()).hexdigest() == status["native_source_sha256"],
        "Native NCCL source changed",
    )
    raw = (overlay / "manifest.json").read_bytes()
    require(hashlib.sha256(raw).hexdigest() == status["overlay_manifest_sha256"], "Overlay manifest changed")
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
        "WANDB_NAME": "mimo9b-001661-r12",
        "WANDB_RUN_ID": "mimo9b001661r12",
        "WANDB_RESUME": "never",
        "WANDB_DIR": "/root/mimo-private/wandb-r12",
        "VERL_RL_INSIGHT_ENABLE": "1",
        "RL_INSIGHT_SERVER_URL": "http://127.0.0.1:18080",
        "MIMO_PROMETHEUS_URL": "http://127.0.0.1:9090",
    }


def render_scripts(templates):
    for name, expected in TEMPLATE_SHA.items():
        require(hashlib.sha256(templates[name].encode()).hexdigest() == expected, f"Unreviewed {name} template")
    # Full SHA and checked counts keep parent identities reviewable. Historical
    # r10 checkpoint/CuPy/NCCL probe and r8 SSH identity are intentionally reused.
    counts = {"prepare": 34, "driver": 21, "wrapper": 5}
    edited = {name: replace_checked(text, "r11", "r12", counts[name]) for name, text in templates.items()}
    bundle_counts = {"prepare": 2, "driver": 4, "wrapper": 1}
    edited = {
        name: replace_checked(
            text, "audit-code/r12-preparation-v2/", "audit-code/r12-preparation/", bundle_counts[name]
        )
        for name, text in edited.items()
    }
    prepare = replace_checked(edited["prepare"], "R11", "R12", 4)
    for old, new, count in ((38670, 38680, 2), (38671, 38681, 2), (38672, 38682, 1), (38673, 38683, 1)):
        prepare = replace_checked(prepare, str(old), str(new), count)
    driver = edited["driver"]
    wrapper = edited["wrapper"]
    result = {
        "prepare-r12.py": prepare,
        "launch-r12-driver.py": driver,
        "mimo-supervised-native-r12.py": wrapper,
    }
    for name, text in result.items():
        ast.parse(text, filename=name)
    return result


def stage(output, templates):
    scripts = render_scripts(templates)
    scripts["mimo_r12_preparation.py"] = Path(__file__).read_text()
    scripts["preflight-r12.py"] = Path(__file__).with_name("mimo_r12_preflight.py").read_text()
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    hashes = {}
    for name, text in scripts.items():
        descriptor = os.open(output / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            stream.write(text)
        hashes[name] = hashlib.sha256(text.encode()).hexdigest()
    manifest = dict(
        schema="mimo.r12-script-preparation.v1", files=hashes, training_started=False, templates=TEMPLATE_SHA
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
