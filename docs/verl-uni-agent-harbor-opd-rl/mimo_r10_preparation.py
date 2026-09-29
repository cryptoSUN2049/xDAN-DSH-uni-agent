"""Stage reviewed r10 operator scripts only; stage never prepares or starts a run."""

import argparse
import ast
import hashlib
import json
import math
import os
import re
from pathlib import Path

ROOT = Path("/workspace/mimo-dsh-rl-20260928")
DEADLINE = 1790687801  # 2026-09-29 13:16:41 UTC; fixed user-authorized stop.
PYTHON = "/workspace/verl-uni-agent-harbor-opd-rl/envs/ua-verl-py312-vllm023-ws1/bin/python"
NCCL_LIB = str(Path(PYTHON).parents[1] / "lib/python3.12/site-packages/nvidia/nccl/lib")
NATIVE_ENGINE = "verl/verl/checkpoint_engine/nccl_checkpoint_engine.py"
TEMPLATE_SHA = {
    "prepare": "548fcb17c01665b3f49b06f8a626bc9edeb72193577710f72733efc71f757d44",
    "driver": "76da14b7c58695b144dcb2e7a2cbc9d5ce13206f27e3c411c51b494638642561",
    "wrapper": "6404ff6a74ba3cc70ab57fb69b95554705896791c2e380c504de06acde5d372d",
}
REQUIRED_SOURCE = {
    NATIVE_ENGINE,
    "deployment/services/harbor_run_controller.py",
    "examples/harbor_opd_rl/launch.py",
    "examples/mimo_dsh_rl/mimo-9b-separate-async.yaml",
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
    require(780 <= DEADLINE - now <= 18000, "Insufficient or unauthorized absolute run window")
    source = root / "run-src-r10"
    manifest = json.loads((root / "integration-check/source-r10-manifest.json").read_bytes())
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
    flags = ["--total-training-steps", "3", "--save-freq", "1"]
    checkpoint = root / "runs/r9/rl-training/checkpoints/global_step_2"
    for name in CHECKPOINT_FILES:
        path = checkpoint / name
        require(
            path.is_file()
            and not path.is_symlink()
            and path.stat().st_size > 0
            and path.resolve().is_relative_to(checkpoint.resolve()),
            "Incomplete r9 C2 checkpoint",
        )
    latest = checkpoint.parent / "latest_checkpointed_iteration.txt"
    require(latest.is_file() and latest.read_text().strip() == "2", "Uncommitted r9 C2 checkpoint")
    flags += ["--resume-from-path", str(checkpoint)]
    return {
        "mode": mode,
        "source_commit": source_commit,
        "deadline_unix": DEADLINE,
        "wall_clock_seconds": int(DEADLINE - now - 180),
        "training_flags": flags,
    }


def runtime_gate():
    import time

    return validate_runtime(
        ROOT, os.environ.get("MIMO_R10_MODE"), os.environ.get("MIMO_R10_SOURCE_COMMIT"), time.time()
    )


def training_environment(root):
    """Require native two-GPU evidence and the exact isolated dependency overlay."""
    source = root / "run-src-r10"
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


def render_scripts(templates):
    for name, expected in TEMPLATE_SHA.items():
        require(hashlib.sha256(templates[name].encode()).hexdigest() == expected, f"Unreviewed {name} template")
    # Counts are pinned to the full reviewed template hashes above. r9 only denotes
    # this run's identities and paths; r8 host discovery/known-hosts remain intact.
    counts = {"prepare": 34, "driver": 18, "wrapper": 4}
    edited = {name: replace_checked(text, "r9", "r10", counts[name]) for name, text in templates.items()}
    prepare = replace_checked(edited["prepare"], "R9", "R10", 4)
    for old, new, count in ((38650, 38660, 2), (38651, 38661, 2), (38652, 38662, 1), (38653, 38663, 1)):
        prepare = replace_checked(prepare, str(old), str(new), count)
    driver = replace_checked(edited["driver"], "'CUDA_VISIBLE_DEVICES':'0'", "'CUDA_VISIBLE_DEVICES':'0,1'")
    driver = replace_checked(
        driver,
        "assert ipc['status'] == 'passed' and ipc['tests'] == 1",
        "assert ipc['status'] == 'passed' and ipc['tests'] == 2\n"
        "assert ipc['mode'] == 'separate_async' and ipc['backend'] == 'nccl'",
    )
    driver = replace_checked(
        driver,
        "env.pop('RAY_EXPERIMENTAL_NOSET_CUDA_VISIBLE_DEVICES', None)",
        "transport_env = runpy.run_path('/workspace/mimo-dsh-rl-20260928/audit-code/r10-preparation/"
        "mimo_r10_preparation.py')['training_environment'](root)\n"
        "env.update(transport_env)\n"
        "env.pop('RAY_EXPERIMENTAL_NOSET_CUDA_VISIBLE_DEVICES', None)",
    )
    driver = replace_checked(
        driver, "'OMP_NUM_THREADS','RAY_TMPDIR')", "'OMP_NUM_THREADS','RAY_TMPDIR','LD_LIBRARY_PATH')"
    )
    wrapper = replace_checked(edited["wrapper"], "mimo-9b-budget-terminal.yaml", "mimo-9b-separate-async.yaml")
    result = {
        "prepare-r10.py": prepare,
        "launch-r10-driver.py": driver,
        "mimo-supervised-native-r10.py": wrapper,
    }
    for name, text in result.items():
        ast.parse(text, filename=name)
    return result


def stage(output, templates):
    scripts = render_scripts(templates)
    scripts["mimo_r10_preparation.py"] = Path(__file__).read_text()
    scripts["preflight-r10.py"] = Path(__file__).with_name("mimo_r10_preflight.py").read_text()
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    hashes = {}
    for name, text in scripts.items():
        descriptor = os.open(output / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            stream.write(text)
        hashes[name] = hashlib.sha256(text.encode()).hexdigest()
    manifest = dict(
        schema="mimo.r10-script-preparation.v1", files=hashes, training_started=False, templates=TEMPLATE_SHA
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
