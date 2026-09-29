"""Stage reviewed r9 operator scripts only; stage never prepares or starts a run."""

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
TEMPLATE_SHA = {
    "prepare": "edd2de0905abe6d3b2aa96e8581dc23272f264b76b5ff70fa77ba4b9175ce565",
    "driver": "6c53a616e3248e09823efd3419059c78ff7a372155d5cd13b93cf3c8ff6c4521",
    "wrapper": "67d393bc04915e92d50fc8a788a2edc7cc678635f6bca56465f849c1b56fdf48",
}
REQUIRED_SOURCE = {
    "deployment/services/harbor_run_controller.py",
    "examples/harbor_opd_rl/launch.py",
    "examples/mimo_dsh_rl/mimo-9b-budget-terminal.yaml",
    "verl/verl/workers/engine/fsdp/transformer_impl.py",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate_runtime(root, mode, source_commit, now):
    require(mode in ("fresh", "resume"), "Explicit mode fresh or resume required")
    require(isinstance(source_commit, str) and re.fullmatch(r"[0-9a-f]{40}", source_commit), "Full commit required")
    require(type(now) in (int, float) and math.isfinite(now), "Invalid clock")
    require(780 <= DEADLINE - now <= 18000, "Insufficient or unauthorized absolute run window")
    source = root / "run-src-r9"
    manifest = json.loads((root / "integration-check/source-r9-manifest.json").read_bytes())
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
    flags = ["--total-training-steps", "2" if mode == "fresh" else "3", "--save-freq", "1"]
    if mode == "resume":
        checkpoint = root / "runs/r8/rl-training/checkpoints/global_step_2"
        for name in (
            "data.pt",
            "actor/model_world_size_1_rank_0.pt",
            "actor/optim_world_size_1_rank_0.pt",
            "actor/extra_state_world_size_1_rank_0.pt",
        ):
            path = checkpoint / name
            require(path.is_file() and not path.is_symlink() and path.stat().st_size > 0, "Incomplete r8 C2 checkpoint")
        latest = checkpoint.parent / "latest_checkpointed_iteration.txt"
        require(latest.is_file() and latest.read_text().strip() == "2", "Uncommitted r8 C2 checkpoint")
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

    return validate_runtime(ROOT, os.environ.get("MIMO_R9_MODE"), os.environ.get("MIMO_R9_SOURCE_COMMIT"), time.time())


def replace_once(text, old, new):
    require(text.count(old) == 1, "Reviewed template fragment changed")
    return text.replace(old, new, 1)


def render_scripts(templates):
    for name, expected in TEMPLATE_SHA.items():
        require(hashlib.sha256(templates[name].encode()).hexdigest() == expected, f"Unreviewed {name} template")
    bundle = ROOT / "audit-code/r9-preparation"
    prefix = f"import runpy\nr9_plan = runpy.run_path({str(bundle / 'mimo_r9_preparation.py')!r})['runtime_gate']()\n"
    prepare = templates["prepare"].replace("r8", "r9")
    for old, new in ((38640, 38650), (38641, 38651), (38642, 38652), (38643, 38653)):
        prepare = prepare.replace(str(old), str(new))
    prepare = prepare.replace("gpu-discovery-r9.json", "gpu-discovery-r8.json")
    prepare = prepare.replace("gpu-known-hosts-r9", "gpu-known-hosts-r8")
    prepare = replace_once(
        prepare,
        "lease = json.loads((private / 'shared-run-window-r9.json').read_text())\n"
        "assert discovery['id'] == lease['id']",
        "# Reuse verified SSH host identity, never the expired r8 lease.",
    )
    prepare = replace_once(
        prepare,
        "value['deadline_unix'] = lease['deadline_unix'] - 180",
        "value['deadline_unix'] = r9_plan['deadline_unix']",
    )
    prepare = replace_once(prepare, "gpu_code = '''\n", "gpu_code = '''\n" + prefix)
    prepare = replace_once(
        prepare,
        "['env', 'CUDA_VISIBLE_DEVICES=', 'PYTHONPATH='",
        "['env', 'CUDA_VISIBLE_DEVICES=', 'MIMO_R9_MODE=' + os.environ['MIMO_R9_MODE'], "
        "'MIMO_R9_SOURCE_COMMIT=' + os.environ['MIMO_R9_SOURCE_COMMIT'], 'PYTHONPATH='",
    )
    driver = templates["driver"].replace("r8", "r9")
    driver = replace_once(
        driver,
        "wall = min(4800, int(spec['deadline_unix'] - time.time() - 180))",
        "assert spec['deadline_unix'] == r9_plan['deadline_unix']\n"
        "wall = int(spec['deadline_unix'] - time.time() - 180)",
    )
    driver = driver.replace(
        "audit-code/mimo-supervised-native-r9.py", "audit-code/r9-preparation/mimo-supervised-native-r9.py"
    )
    wrapper = replace_once(templates["wrapper"], "    ]\n", "    ] + r9_plan['training_flags']\n")
    result = {
        "prepare-r9.py": prefix + prepare,
        "launch-r9-driver.py": prefix + driver,
        "mimo-supervised-native-r9.py": prefix + wrapper,
    }
    for name, text in result.items():
        ast.parse(text, filename=name)
    return result


def stage(output, templates):
    scripts = render_scripts(templates)
    scripts["mimo_r9_preparation.py"] = Path(__file__).read_text()
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    hashes = {}
    for name, text in scripts.items():
        descriptor = os.open(output / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            stream.write(text)
        hashes[name] = hashlib.sha256(text.encode()).hexdigest()
    manifest = dict(
        schema="mimo.r9-script-preparation.v1", files=hashes, training_started=False, templates=TEMPLATE_SHA
    )
    (output / "scripts-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
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
