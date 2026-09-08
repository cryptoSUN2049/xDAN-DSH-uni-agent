"""Launch prepared context v2 strict inference with checked inputs and an owned deadline."""

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path

import pyarrow.parquet as pq
import yaml

from deployment.services.harbor_training_supervisor import supervise

ROOT = Path(__file__).resolve().parents[3]
MODULE = "examples.dsh.capabilities.context_verifier_v2"


def git_state(root):
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True, timeout=10
    )
    branch = subprocess.run(
        ["git", "symbolic-ref", "--quiet", "--short", "HEAD"], cwd=root, capture_output=True, text=True, timeout=10
    )
    if branch.returncode not in (0, 1):
        raise ValueError("Could not inspect checkout branch")
    return {"head": head.stdout.strip(), "branch": branch.stdout.strip() if branch.returncode == 0 else None}


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return "sha256:" + value.hexdigest()


def checked_files(root, files):
    if not isinstance(files, dict) or not files:
        raise ValueError("Missing file hashes")
    for relative, expected in files.items():
        path = (root / relative).resolve()
        if Path(relative).is_absolute() or not path.is_relative_to(root.resolve()):
            raise ValueError("File escapes hash root")
        if not path.is_file() or digest(path) != expected:
            raise ValueError(f"File hash mismatch: {relative}")


def inference_arguments(data, run):
    return [
        "--data-path",
        str(data / "validation.parquet"),
        "--task-config",
        str(data / "task.yaml"),
        "--n",
        "1",
        "--limit",
        "4",
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


def preflight(manifest_path, model_path, *, concurrency=1, gpu_memory=0.30, max_model_len=16384):
    manifest_path = Path(manifest_path).resolve()
    data = manifest_path.parent
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("schema") != "dsh.context-online-rl-preparation.v2":
        raise ValueError("Expected prepared context v2 manifest")
    env = manifest["environment"]
    if not isinstance(env, dict) or any(not isinstance(v, str) for v in env.values()):
        raise ValueError("Manifest environment must contain strings")
    if env.get("PYTHONPATH") != f"{ROOT}:{ROOT / 'verl'}":
        raise ValueError("Manifest requires absolute PYTHONPATH for this checkout")
    if env.get("DSH_RUNTIME_MODE") != "exe" or env.get("DATA_ROOT") != str(data):
        raise ValueError("Manifest environment/data mismatch")
    run = Path(env["RUN_ROOT"])
    if (
        not run.is_absolute()
        or run.exists()
        or run.is_symlink()
        or run.resolve().is_relative_to(data)
        or data.is_relative_to(run.resolve())
    ):
        raise ValueError("Run root must be new and independent")
    required_sources = {
        "examples/dsh/verifier.py",
        "examples/dsh/evolution_verifier.py",
        "examples/dsh/evolution_verifier_v2.py",
        "examples/dsh/capabilities/context_tasks_v2.py",
        "examples/dsh/capabilities/context_verifier_v2.py",
        "examples/dsh/capabilities/prepare_context_training_v2.py",
        "examples/dsh/evolution_task_config_v3_live.yaml",
        "deployment/versions/g1-deployment-lock.json",
    }
    if not required_sources.issubset(manifest["sources"]):
        raise ValueError("Missing required source hashes")
    checked_files(ROOT, manifest["sources"])
    lock = json.loads((ROOT / "deployment/versions/g1-deployment-lock.json").read_text())
    checkout = {"integration": git_state(ROOT), "verl": git_state(ROOT / "verl")}
    if checkout["verl"]["head"] != lock["integration"]["verl_revision"]:
        raise ValueError("VERL checkout differs from deployment pin")
    checked_files(data, manifest["files"])
    actual_files = {str(p.relative_to(data)) for p in data.rglob("*") if p.is_file() and p != manifest_path}
    if actual_files != set(manifest["files"]):
        raise ValueError("Preparation file inventory mismatch")
    arguments = inference_arguments(data, run)
    if manifest.get("inference_arguments") != arguments:
        raise ValueError("Manifest inference argv differs from fixed context entry")
    runtime = manifest["runtime"]
    python = Path(env["PYTHON_BIN"])
    if not python.is_absolute() or str(python) != runtime["python"] or not python.is_file():
        raise ValueError("Python identity mismatch")
    if digest(runtime["path"]) != runtime["sha256"]:
        raise ValueError("Runtime binary hash mismatch")
    config = yaml.safe_load((data / "task.yaml").read_text())[0]
    bundle = manifest["verifier_bundle"]
    if (
        config["verifier_command"] != [str(python), "-m", MODULE]
        or config["verifier_code_digest"] != bundle["sha256"]
        or config["verifier_id"] != bundle["id"]
        or config["verifier_version"] != "2"
        or config["workdir"] != str(data)
        or config["environment_digest"] != runtime["sha256"]
        or config["result_root"] != str(run / "artifacts/results")
    ):
        raise ValueError("Task config identity/workdir mismatch")
    for split, count in (("train", 12), ("validation", 4)):
        rows = pq.read_table(data / f"{split}.parquet").to_pylist()
        if len(rows) != count:
            raise ValueError("Unexpected context dataset count")
        for row in rows:
            metadata = row["extra_info"]["tools_kwargs"]["task"]["metadata"]
            fixture = Path(metadata["fixture_path"]).resolve()
            if (
                metadata["split"] != split
                or metadata["verifier_code_digest"] != bundle["sha256"]
                or metadata["environment_digest"] != runtime["sha256"]
                or not fixture.is_relative_to(data)
                or digest(fixture) != metadata["fixture_sha256"]
            ):
                raise ValueError("Parquet task identity mismatch")
    model = Path(model_path).resolve()
    model_config = json.loads((model / "config.json").read_text())
    if (model_config.get("model_type"), model_config.get("hidden_size"), model_config.get("num_hidden_layers")) != (
        "qwen3",
        2560,
        36,
    ):
        raise ValueError("This entry supports the fixed Qwen3-4B architecture")
    model_files = [model / "config.json", model / "tokenizer_config.json", model / "tokenizer.json"]
    weights = sorted(model.glob("*.safetensors"))
    if not weights:
        raise ValueError("Missing local model weights")
    index = model / "model.safetensors.index.json"
    if index.exists():
        expected_weights = set(json.loads(index.read_text())["weight_map"].values())
        if expected_weights != {p.name for p in weights}:
            raise ValueError("Model shard inventory mismatch")
        model_files.append(index)
    model_files.extend(weights)
    if type(concurrency) is not int or not 1 <= concurrency <= 4 or not 0 < gpu_memory <= 0.6:
        raise ValueError("Invalid single-GPU concurrency/memory budget")
    if type(max_model_len) is not int or not 12288 <= max_model_len <= 32768:
        raise ValueError("Invalid context window budget")
    environment = {**os.environ, **env, "PATH": f"{python.parent}:{os.environ.get('PATH', '')}"}
    for key in ("RAY_ADDRESS", "PYTHONHOME", "PYTORCH_CUDA_ALLOC_CONF"):
        environment.pop(key, None)
    # Keep Ray's Unix socket paths short, and never attach to an inherited session.
    ray_tmp = Path("/tmp") / ("dsh-context-" + hashlib.sha256(str(run).encode()).hexdigest()[:12])
    if ray_tmp.exists() or ray_tmp.is_symlink():
        raise ValueError("Run-owned Ray temporary directory already exists")
    environment["RAY_TMPDIR"] = str(ray_tmp)
    probe_code = (
        "import json;from importlib.metadata import version;"
        "from examples.dsh.capabilities import context_verifier_v2 as v;"
        "from deepseek_harness_runtime import bundled_runtime_path;"
        "print(json.dumps(dict(bundle=v.bundle_digest(),module=v.__file__,runtime=str(bundled_runtime_path()),"
        "sdk=version('deepseek-harness-sdk'),runtime_version=version('deepseek-harness-runtime-bin'))))"
    )
    probe = subprocess.run(
        [str(python), "-c", probe_code], cwd=data, env=environment, capture_output=True, text=True, timeout=30
    )
    if probe.returncode:
        raise RuntimeError("Verifier import preflight failed from task cwd: " + probe.stderr[-2000:])
    imported = json.loads(probe.stdout)
    if (
        imported["bundle"] != bundle["sha256"]
        or Path(imported["module"]).resolve() != ROOT / "examples/dsh/capabilities/context_verifier_v2.py"
        or Path(imported["runtime"]).resolve() != Path(runtime["path"]).resolve()
        or imported["sdk"] != "0.1.3a2"
        or imported["runtime_version"] != "0.1.3a2"
    ):
        raise ValueError("Cross-cwd verifier/runtime import identity mismatch")
    command = [
        str(python),
        str(ROOT / "examples/inference/parallel_infer_verl.py"),
        *arguments,
        "--model-path",
        str(model),
        "--tool-parser",
        "hermes",
        "--n-gpus-per-node",
        "1",
        "--tensor-parallel-size",
        "1",
        "--gateway-count",
        "1",
        "--concurrency",
        str(concurrency),
        "--gpu-memory-utilization",
        str(gpu_memory),
        "--max-model-len",
        str(max_model_len),
    ]
    sources = dict(manifest["sources"])
    for relative in (
        str(Path(__file__).relative_to(ROOT)),
        "examples/inference/parallel_infer_verl.py",
        "deployment/services/harbor_training_supervisor.py",
    ):
        sources[relative] = digest(ROOT / relative)
    record = dict(
        schema="dsh.context-inference-launch.v1",
        prepared_manifest=str(manifest_path),
        prepared_manifest_sha256=digest(manifest_path),
        command=command,
        cwd=str(ROOT),
        environment={key: environment[key] for key in sorted(set(env) | {"PATH", "RAY_TMPDIR"}) if key in environment},
        removed_environment_keys=["RAY_ADDRESS", "PYTHONHOME", "PYTORCH_CUDA_ALLOC_CONF"],
        checkout=checkout,
        declared_integration_pin=lock["integration"],
        sources=sources,
        files=manifest["files"],
        runtime=runtime,
        import_preflight=imported,
        model=dict(
            path=str(model),
            files={p.name: digest(p) for p in model_files},
            revision_from_lock=lock["student"]["revision"],
            revision_scope="configured pin; local bytes measured, no Hub revision verification",
        ),
        cleanup_scope="owned process group only; independent Ray resource cleanup requires ownership audit",
    )
    return dict(command=command, environment=environment, record=record, run_root=run)


def launch(manifest_path, model_path, *, wall_seconds=3600, **kwargs):
    if type(wall_seconds) is not int or not 1 <= wall_seconds <= 7200:
        raise ValueError("Wall-clock budget must be 1..7200 seconds")
    prepared = preflight(manifest_path, model_path, **kwargs)
    run = prepared["run_root"]
    run.mkdir(parents=True, exist_ok=False, mode=0o700)
    prepared["record"]["wall_seconds"] = wall_seconds
    with (run / "launch-manifest.json").open("x") as stream:
        json.dump(prepared["record"], stream, sort_keys=True, indent=2)
        stream.write("\n")
    return supervise(prepared["command"], ROOT, prepared["environment"], run, lambda: None, wall_seconds=wall_seconds)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--wall-seconds", type=int, default=3600)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--gpu-memory", type=float, default=0.30)
    parser.add_argument("--max-model-len", type=int, default=16384)
    args = vars(parser.parse_args())
    args["manifest_path"] = args.pop("manifest")
    result = launch(**args)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["exit_code"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
