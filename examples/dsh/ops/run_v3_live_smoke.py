"""Prepare and verify immutable inputs for the eight-family DSH process smoke.

Preparation uses no model, Gateway or GPU. The source bundle remains blocked;
its declared environment digest is preserved without claiming runtime evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import shutil
import signal
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as parquet
import yaml

from examples.dsh.evolution_v3_catalog import FAMILY_IDS, canonical_json_bytes
from examples.dsh.evolution_v3_live import load_live_scenarios, write_live_contract_bundle

SCHEMA = "dsh.evolution.live-smoke-run.v1"
RUNTIME_SCHEMA = "dsh.evolution.live-smoke-runtime.v1"
DSH_COMMIT = "3b8fad1e32fd9d62acdfdb3ccbd8c8074c22d2ea"
VERL_COMMIT = "483b8a009ba3a97563edee3a19887e4862b8094a"
MODEL_REVISION = "1cfa9a7208912126459214e8b04321603b3df60c"
_TERM_GRACE_SECONDS = 5.0
_RUNTIME_VERSIONS = {"python", "torch", "vllm", "transformers", "ray", "tensordict", "transfer-queue"}
_ML_VERSIONS = {"torch": "2.10.0", "vllm": "0.18.1", "transformers": "4.57.6", "ray": "2.58.0", "tensordict": "0.10.0"}
_CONFIG_SOURCE = "examples/dsh/evolution_task_config_v3_live.yaml"
_PATH_NAMES = {
    "data_path": "smoke.parquet",
    "task_config": "task-config.yaml",
    "result_path": "inference-results.json",
    "agent_log_dir": "agent-logs",
    "trace_root": "artifacts/traces",
    "result_root": "artifacts/results",
    "inference_evidence_path": "inference-evidence.json",
}


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON field: {key}")
        value[key] = item
    return value


def _json_object(data: bytes) -> dict[str, Any]:
    value = json.loads(data, parse_constant=_reject_constant, object_pairs_hook=_unique_object)
    if not isinstance(value, dict):
        raise ValueError("JSON record must be an object")
    # Reject overflowed JSON numbers (e.g. 1e999), as well as named constants.
    json.dumps(value, allow_nan=False)
    return value


def _directory(path: Path) -> Path:
    if ".." in path.parts or path.is_symlink():
        raise ValueError(f"directory path must not traverse or be a symlink: {path}")
    resolved = path.resolve()
    if not resolved.is_dir():
        raise ValueError(f"directory is missing: {path}")
    return resolved


def _relative_file(root: Path, name: object) -> Path:
    if not isinstance(name, str) or not name or Path(name).is_absolute() or ".." in Path(name).parts:
        raise ValueError("file path must be relative and traversal-free")
    path = root / name
    if not path.resolve().is_relative_to(root) or path.is_symlink():
        raise ValueError(f"file path escapes root or is a symlink: {name}")
    if not path.is_file():
        raise ValueError(f"required file is missing: {name}")
    return path


def _verified_entry(root: Path, entry: object) -> bytes:
    if not isinstance(entry, dict):
        raise ValueError("file digest entry must be an object")
    data = _relative_file(root, entry.get("path")).read_bytes()
    if _digest(data) != entry.get("sha256"):
        raise ValueError(f"file digest mismatch: {entry.get('path')}")
    return data


def _load_bundle(bundle_dir: Path, repository_root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    raw = _relative_file(bundle_dir, "manifest.json").read_bytes()
    manifest = _json_object(raw)
    body = {key: value for key, value in manifest.items() if key != "release_id"}
    if manifest.get("release_id") != _digest(canonical_json_bytes(body)):
        raise ValueError("bundle release_id does not match its content")
    if manifest.get("schema") != "dsh.evolution.live-contract-bundle.v1":
        raise ValueError("unsupported live bundle schema")
    try:
        scenario_source = manifest["scenario_source"]
        _verified_entry(repository_root, scenario_source)
        for entry in manifest["verifier_bundle"]["files"]:
            _verified_entry(repository_root, entry)
        for entry in manifest["fixtures"]:
            _json_object(_verified_entry(repository_root, entry))
        for entry in manifest["files"]:
            _verified_entry(bundle_dir, entry)
        runtime = manifest["runtime"]
        for patch in runtime["patches"]:
            _relative_file(repository_root, patch)
        scenario_path = _relative_file(repository_root, scenario_source["path"])
        scenarios = load_live_scenarios(scenario_path, repository_root=repository_root)
        # The author sorts before normalizing paths: an absolute scenario input
        # places its entry first. Preserve either supported author's ordering.
        verifier_files = manifest["verifier_bundle"]["files"]
        source_first = bool(verifier_files) and verifier_files[0]["path"] == scenario_source["path"]
        author_path = scenario_path if source_first else Path(scenario_source["path"])
        # The existing author is the authority for both structure and projection.
        with tempfile.TemporaryDirectory(prefix="dsh-live-bundle-check-") as temporary:
            regenerated = Path(temporary) / "bundle"
            expected = write_live_contract_bundle(
                scenarios,
                scenario_path=author_path,
                repository_root=repository_root,
                output_dir=regenerated,
                environment_digest=runtime["environment_digest"],
                profile=runtime["profile"],
                patches=runtime["patches"],
            )
            if manifest != expected:
                raise ValueError("bundle manifest differs from the canonical author")
            rows_raw = _relative_file(bundle_dir, "live-task-rows.jsonl").read_bytes()
            if rows_raw != (regenerated / "live-task-rows.jsonl").read_bytes():
                raise ValueError("bundle rows differ from the canonical author")
        rows = [_json_object(line) for line in rows_raw.splitlines()]
        families = [row["extra_info"]["tools_kwargs"]["task"]["metadata"]["family_id"] for row in rows]
        if families != list(FAMILY_IDS):
            raise ValueError("bundle must contain exactly the eight ordered families")
    except (KeyError, TypeError) as exc:
        raise ValueError("live bundle has missing or invalid fields") from exc
    return manifest, rows


def _paths(run_root: Path) -> dict[str, str]:
    return {key: str(run_root / name) for key, name in _PATH_NAMES.items()}


def _task_config(repository_root: Path, bundle: dict[str, Any], paths: dict[str, str]) -> bytes:
    config = yaml.safe_load(_relative_file(repository_root, _CONFIG_SOURCE).read_bytes())
    if (
        not isinstance(config, list)
        or len(config) != 1
        or not isinstance(config[0], dict)
        or config[0].get("name") != "dsh_architecture"
        or not isinstance(config[0].get("agent"), dict)
    ):
        raise ValueError("live task config must contain exactly one DSH task")
    task = config[0]
    task["workdir"] = str(repository_root)
    task["result_root"] = paths["result_root"]
    task["environment_digest"] = bundle["runtime"]["environment_digest"]
    task["verifier_id"] = "dsh-harness-evolution-v3-live-verifier"
    task["verifier_version"] = "1"
    task["verifier_code_digest"] = bundle["verifier_bundle"]["sha256"]
    task["require_trace"] = True
    task["verifier_command"] = [
        "python",
        "-m",
        "examples.dsh.evolution_v3_live_verifier",
        "--scenario-file",
        bundle["scenario_source"]["path"],
    ]
    task["agent"].update(
        profile=bundle["runtime"]["profile"],
        patches=bundle["runtime"]["patches"],
        default_workdir=str(repository_root),
        artifact_root=paths["trace_root"],
        dsh_home_root=str(Path(paths["trace_root"]).parent / "home"),
        keep_trace=True,
    )
    return yaml.safe_dump(config, sort_keys=True, allow_unicode=True).encode("utf-8")


def _samples(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"sample_index": index, "metadata": row["extra_info"]["tools_kwargs"]["task"]["metadata"]}
        for index, row in enumerate(rows)
    ]


def _patch_files(repository_root: Path, bundle: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {"path": path, "sha256": _digest(_relative_file(repository_root, path).read_bytes())}
        for path in bundle["runtime"]["patches"]
    ]


def _episode_files(repository_root: Path, bundle: dict[str, Any]) -> list[dict[str, str]]:
    entries = [*bundle["verifier_bundle"]["files"], *bundle["fixtures"], *_patch_files(repository_root, bundle)]
    return [
        {"path": path, "sha256": digest}
        for path, digest in sorted({entry["path"]: entry["sha256"] for entry in entries}.items())
    ]


def prepare_run(bundle_dir: Path, run_root: Path, *, repository_root: Path) -> dict[str, Any]:
    """Freeze verified eight-row inference inputs in a new operator-selected directory."""
    repository_root = _directory(repository_root)
    bundle_dir = _directory(bundle_dir)
    if ".." in run_root.parts or run_root.is_symlink():
        raise ValueError("run root path must not traverse or be a symlink")
    run_root = run_root.resolve()
    if run_root.exists():
        raise ValueError(f"run root already exists: {run_root}")
    bundle, rows = _load_bundle(bundle_dir, repository_root)
    paths = _paths(run_root)
    config_bytes = _task_config(repository_root, bundle, paths)
    patches = _patch_files(repository_root, bundle)
    run_root.parent.mkdir(parents=True, exist_ok=True)
    # mkdir(exist_ok=False) is the reservation; never overwrite an existing run.
    run_root.mkdir()
    try:
        parquet.write_table(pa.Table.from_pylist(rows), paths["data_path"])
        Path(paths["task_config"]).write_bytes(config_bytes)
        episode_file = run_root / "episode-files.json"
        episode_bytes = canonical_json_bytes(_episode_files(repository_root, bundle))
        episode_file.write_bytes(episode_bytes)
        for name in ("agent_log_dir", "trace_root", "result_root"):
            Path(paths[name]).mkdir(parents=True, exist_ok=True)
        manifest = {
            "schema": SCHEMA,
            "status": "prepared",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "repository_root": str(repository_root),
            "bundle": {
                "path": str(bundle_dir),
                "release_id": bundle["release_id"],
                "sha256": _digest((bundle_dir / "manifest.json").read_bytes()),
            },
            "runtime": bundle["runtime"],
            "verifier_bundle": bundle["verifier_bundle"],
            "patch_files": patches,
            "episode_files_path": str(episode_file),
            "episode_files_sha256": _digest(episode_bytes),
            "samples": _samples(rows),
            "paths": paths,
            "sha256": {key: _digest(Path(paths[key]).read_bytes()) for key in ("data_path", "task_config")},
            "training_eligible": False,
        }
        (run_root / "run-manifest.json").write_bytes(canonical_json_bytes(manifest))
    except BaseException:
        shutil.rmtree(run_root)
        raise
    return manifest


def load_prepared_run(run_root: Path, *, repository_root: Path) -> dict[str, Any]:
    """Recheck immutable inputs before execution or audit, leaving outputs uninspected."""
    run_root = _directory(run_root)
    repository_root = _directory(repository_root)
    manifest = _json_object(_relative_file(run_root, "run-manifest.json").read_bytes())
    if manifest.get("schema") != SCHEMA or manifest.get("training_eligible") is not False:
        raise ValueError("invalid smoke manifest schema or training eligibility")
    if manifest.get("repository_root") != str(repository_root):
        raise ValueError("prepared repository path does not match")
    paths = _paths(run_root)
    if manifest.get("paths") != paths:
        raise ValueError("prepared artifact paths do not match the run root")
    for path in paths.values():
        if not Path(path).resolve().is_relative_to(run_root) or Path(path).is_symlink():
            raise ValueError("prepared artifact path escapes the run root or is a symlink")
    try:
        bundle_dir = _directory(Path(manifest["bundle"]["path"]))
        bundle, rows = _load_bundle(bundle_dir, repository_root)
        expected_bundle = {
            "path": str(bundle_dir),
            "release_id": bundle["release_id"],
            "sha256": _digest((bundle_dir / "manifest.json").read_bytes()),
        }
        if manifest["bundle"] != expected_bundle:
            raise ValueError("prepared bundle identity mismatch")
        if manifest["runtime"] != bundle["runtime"] or manifest["verifier_bundle"] != bundle["verifier_bundle"]:
            raise ValueError("prepared runtime or verifier identity mismatch")
        if manifest["patch_files"] != _patch_files(repository_root, bundle):
            raise ValueError("prepared patch file digest mismatch")
        episode_file = _relative_file(run_root, "episode-files.json")
        episode_bytes = canonical_json_bytes(_episode_files(repository_root, bundle))
        if (
            manifest["episode_files_path"] != str(episode_file)
            or manifest["episode_files_sha256"] != _digest(episode_bytes)
            or episode_file.read_bytes() != episode_bytes
        ):
            raise ValueError("prepared episode file inventory mismatch")
        if manifest["samples"] != _samples(rows):
            raise ValueError("prepared sample identities do not match canonical rows")
        for key in ("data_path", "task_config"):
            if _digest(Path(paths[key]).read_bytes()) != manifest["sha256"][key]:
                raise ValueError(f"prepared {key} digest mismatch")
        if Path(paths["task_config"]).read_bytes() != _task_config(repository_root, bundle, paths):
            raise ValueError("prepared task config does not match pinned inputs")
        if parquet.read_table(paths["data_path"]).to_pylist() != rows:
            raise ValueError("prepared Parquet does not match canonical rows")
    except (KeyError, TypeError) as exc:
        raise ValueError("prepared smoke manifest has missing or invalid fields") from exc
    return manifest


def build_inference_command(manifest: dict[str, Any], model_path: Path, *, repository_root: Path) -> list[str]:
    """Return the fixed single-engine inference argv, never a shell command."""
    paths = manifest["paths"]
    run_root = Path(paths["data_path"]).parent
    return [
        sys.executable,
        str(repository_root / "examples/inference/parallel_infer_verl.py"),
        "--data-path",
        paths["data_path"],
        "--task-config",
        paths["task_config"],
        "--model-path",
        str(model_path.resolve()),
        "--served-model-name",
        "Qwen3-4B",
        "--result-path",
        paths["result_path"],
        "--log-dir",
        paths["agent_log_dir"],
        "--limit",
        "8",
        "--n",
        "1",
        "--concurrency",
        "1",
        "--nnodes",
        "1",
        "--n-gpus-per-node",
        "1",
        "--tensor-parallel-size",
        "1",
        "--gateway-count",
        "1",
        "--engine",
        "vllm",
        "--tool-parser",
        "hermes",
        "--max-model-len",
        "8192",
        "--gpu-memory-utilization",
        "0.5",
        "--require-reward-post",
        "--dsh-strict-audit",
        "--dsh-trace-root",
        paths["trace_root"],
        "--dsh-result-root",
        paths["result_root"],
        "--inference-evidence-path",
        paths["inference_evidence_path"],
        "--dsh-episode-workdir-root",
        str(run_root / "artifacts/workspaces"),
        "--dsh-episode-source-root",
        str(repository_root),
        "--dsh-episode-files",
        manifest["episode_files_path"],
    ]


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise ValueError("runtime source Git identity could not be verified")
    return result.stdout.strip()


def _verify_inventory(root: Path, entries: object, *, expected_paths: set[str] | None = None) -> None:
    if not isinstance(entries, list) or not entries:
        raise ValueError("runtime file inventory must be non-empty")
    names = [entry.get("path") for entry in entries if isinstance(entry, dict)]
    if len(names) != len(entries) or any(not isinstance(name, str) for name in names) or len(set(names)) != len(names):
        raise ValueError("runtime file inventory contains invalid or duplicate paths")
    if expected_paths is None:
        expected_paths = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}
    if set(names) != expected_paths:
        raise ValueError("runtime file inventory does not cover the complete artifact")
    for entry in entries:
        if _file_digest(_relative_file(root, entry["path"])) != entry.get("sha256"):
            raise ValueError("runtime artifact file digest mismatch")


def _check_source_clean(root: Path, *paths: str) -> None:
    _git(root, "diff", "--quiet", "HEAD", "--", *paths)
    untracked = _git(root, "ls-files", "--others", "--exclude-standard", "-z", "--", *paths)
    if any(Path(path).suffix in {".py", ".pyc", ".so", ".pth"} for path in untracked.split("\0") if path):
        raise ValueError("runtime import source contains untracked code")


def _execution_environment(repository_root: Path, runtime: dict[str, Any]) -> dict[str, str]:
    """Pass local runtime locations, without forwarding operator API credentials."""
    source = Path(runtime["dsh"]["source_root"])
    environment = {
        key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL", "LD_LIBRARY_PATH", "CUDA_HOME") if key in os.environ
    }
    environment.update(
        PATH=str(Path(sys.executable).parent) + os.pathsep + environment.get("PATH", os.defpath),
        PYTHONPATH=os.pathsep.join(
            map(
                str,
                [
                    repository_root,
                    repository_root / "verl",
                    source / "python/sdk/src",
                    source / "python/sdk-runtime/src",
                ],
            )
        ),
        DSH_RUNTIME_MODE=runtime["dsh"]["mode"],
        CUDA_VISIBLE_DEVICES="0",
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
        TOKENIZERS_PARALLELISM="false",
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONNOUSERSITE="1",
    )
    return environment


def _runtime_probe(repository_root: Path, runtime: dict[str, Any]) -> dict[str, Any]:
    # No engine/model is constructed. Imports and CUDA availability still require
    # a real Linux deployment, so dry-run deliberately never reaches this probe.
    code = """import json, platform, importlib.metadata as metadata
import torch, vllm, ray, tensordict, transfer_queue, deepseek_harness
from deepseek_harness_runtime import resolve_bundled_launch_args
names = ['torch','vllm','transformers','ray','tensordict','transfer-queue']
versions = {name: metadata.version('TransferQueue' if name == 'transfer-queue' else name) for name in names}
versions['python'] = platform.python_version()
print(json.dumps({'versions': versions, 'cuda_available': torch.cuda.is_available(),
    'gpu_count': torch.cuda.device_count(), 'cuda_version': torch.version.cuda,
    'launch_args': list(resolve_bundled_launch_args())}))
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=repository_root,
        env=_execution_environment(repository_root, runtime),
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode:
        raise ValueError("runtime dependency/CUDA probe failed; no inference was launched")
    try:
        return _json_object(result.stdout.strip().splitlines()[-1].encode())
    except (ValueError, IndexError) as exc:
        raise ValueError("runtime probe did not return valid evidence") from exc


def _runtime_preflight(
    manifest: dict[str, Any], model_path: Path, runtime_manifest: Path | None, *, repository_root: Path
) -> dict[str, Any]:
    """Verify a complete operator deployment inventory before any inference spawn.

    The runtime manifest contains model.path/repo_id/revision/files; dsh.source_root/
    source_commit/source_files/mode/runtime_root/runtime_files/launch_args/launch_files;
    uni_agent_commit, verl_commit, environment_digest and exact versions. Source
    cleanliness binds the declared DSH commit to its files; runtime hashes bind
    the actual SDK-selected carrier. This does not prove a reproducible build.
    """
    if runtime_manifest is None:
        raise ValueError("runtime manifest is required for execution")
    if platform.system() != "Linux" or platform.machine() not in {"x86_64", "AMD64"}:
        raise ValueError("runtime execution requires a verified Linux x64 GPU deployment")
    runtime_bytes = runtime_manifest.read_bytes()
    runtime = _json_object(runtime_bytes)
    try:
        if (
            runtime.get("schema") != RUNTIME_SCHEMA
            or runtime["environment_digest"] != manifest["runtime"]["environment_digest"]
        ):
            raise ValueError("runtime schema/environment identity mismatch")
        if runtime["uni_agent_commit"] != _git(repository_root, "rev-parse", "HEAD"):
            raise ValueError("runtime Uni-Agent revision mismatch")
        _check_source_clean(repository_root, "examples", "uni_agent")
        if runtime["verl_commit"] != VERL_COMMIT or _git(repository_root / "verl", "rev-parse", "HEAD") != VERL_COMMIT:
            raise ValueError("runtime VERL revision mismatch")
        _check_source_clean(repository_root / "verl")
        model = runtime["model"]
        model_root = _directory(model_path)
        if (
            model["path"] != str(model_root)
            or model["repo_id"] != "Qwen/Qwen3-4B"
            or model["revision"] != MODEL_REVISION
        ):
            raise ValueError("runtime model identity mismatch")
        _verify_inventory(model_root, model["files"])
        config = _json_object(_relative_file(model_root, "config.json").read_bytes())
        _relative_file(model_root, "tokenizer_config.json")
        _relative_file(model_root, "tokenizer.json")
        if config.get("model_type") != "qwen3" or not any(model_root.glob("*.safetensors")):
            raise ValueError("runtime model is not a complete dense Qwen3 checkpoint")
        dsh = runtime["dsh"]
        source = _directory(Path(dsh["source_root"]))
        if dsh["source_commit"] != DSH_COMMIT or _git(source, "rev-parse", "HEAD") != DSH_COMMIT:
            raise ValueError("runtime DSH source revision mismatch")
        _check_source_clean(source)
        tracked = set(_git(source, "ls-files", "-z").split("\0")) - {""}
        _verify_inventory(source, dsh["source_files"], expected_paths=tracked)
        carrier = _directory(Path(dsh["runtime_root"]))
        _verify_inventory(carrier, dsh["runtime_files"])
        launch = dsh["launch_args"]
        if (
            dsh["mode"] not in {"exe", "node"}
            or not isinstance(launch, list)
            or len(launch) != (1 if dsh["mode"] == "exe" else 2)
        ):
            raise ValueError("runtime carrier mode/launch arguments are invalid")
        if not isinstance(dsh["launch_files"], list) or [entry["path"] for entry in dsh["launch_files"]] != launch:
            raise ValueError("runtime launch file inventory mismatch")
        for entry in dsh["launch_files"]:
            path = Path(entry["path"])
            if not path.is_absolute() or not path.is_file() or _file_digest(path) != entry["sha256"]:
                raise ValueError("runtime launch file digest mismatch")
        if not Path(launch[-1]).resolve().is_relative_to(carrier):
            raise ValueError("runtime launch entry is outside the verified carrier")
        versions = runtime["versions"]
        if set(versions) != _RUNTIME_VERSIONS or any(
            not isinstance(value, str) or not value for value in versions.values()
        ):
            raise ValueError("runtime dependency version inventory is incomplete")
        if not versions["python"].startswith("3.11.") or any(
            versions[name].split("+")[0] != version for name, version in _ML_VERSIONS.items()
        ):
            raise ValueError("runtime dependencies differ from the pinned ML compatibility lane")
        probe = _runtime_probe(repository_root, runtime)
        cuda = probe.get("cuda_version")
        if (
            probe.get("versions") != runtime["versions"]
            or probe.get("launch_args") != launch
            or probe.get("cuda_available") is not True
            or probe.get("gpu_count") != 1
            or not isinstance(cuda, str)
            or tuple(map(int, cuda.split(".")[:2])) < (12, 8)
        ):
            raise ValueError("runtime actual versions, carrier or CUDA device do not match deployment evidence")
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError("runtime manifest has missing or malformed identity fields") from exc
    if runtime_manifest.read_bytes() != runtime_bytes:
        raise ValueError("runtime manifest changed during preflight")
    return {**runtime, "manifest_sha256": _digest(runtime_bytes), "probe": probe}


def _write_manifest(run_root: Path, manifest: dict[str, Any]) -> None:
    _write_json(run_root / "run-manifest.json", manifest)


def _write_json(path: Path, value: dict[str, Any]) -> None:
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(canonical_json_bytes(value))
            stream.flush()
            os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def _seal_run(run_root: Path, manifest: dict[str, Any]) -> None:
    """Seal the final manifest/report and current artifacts; never hash the index itself."""
    report_path = run_root / "smoke-report.json"
    index_path = run_root / "artifact-sha256.json"
    manifest.update(smoke_report_path=str(report_path), artifact_sha256_path=str(index_path))
    _write_json(report_path, manifest["audit"])
    _write_manifest(run_root, manifest)
    files = []
    for path in sorted(run_root.rglob("*")):
        if path.is_symlink():
            raise ValueError("run artifact inventory must not contain symlinks")
        if path.is_file() and path != index_path:
            files.append({"path": path.relative_to(run_root).as_posix(), "sha256": _file_digest(path)})
    _write_json(
        index_path, {"schema": "dsh.evolution.live-smoke-artifacts.v1", "training_eligible": False, "files": files}
    )


def _stop_group(process: subprocess.Popen) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        process.wait(timeout=_TERM_GRACE_SECONDS)
        return
    try:
        process.wait(timeout=_TERM_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        pass
    # Kill descendants still in the group, even if the leader exited on TERM.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait(timeout=_TERM_GRACE_SECONDS)


def _audit_run(run_root: Path, *, repository_root: Path) -> dict[str, Any]:
    from examples.dsh.ops.audit_v3_live_smoke import audit_run

    return audit_run(run_root, repository_root=repository_root)


def run_prepared(
    run_root: Path,
    *,
    model_path: Path,
    runtime_manifest: Path | None,
    timeout_seconds: float,
    repository_root: Path,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run one prepared eight-row batch once, retaining failure and timeout evidence."""
    if not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 7200:
        raise ValueError("timeout must be finite and within (0, 7200] seconds")
    run_root = _directory(run_root)
    repository_root = _directory(repository_root)
    manifest = load_prepared_run(run_root, repository_root=repository_root)
    if manifest.get("status") != "prepared" or (run_root / "run-started.json").exists():
        raise ValueError("run is no longer prepared or has already been attempted")
    command = build_inference_command(manifest, model_path, repository_root=repository_root)
    if dry_run:
        return {"status": "dry-run", "command": command, "training_eligible": False, "execution_started": False}
    manifest.update(
        preflight_started_at=datetime.now(timezone.utc).isoformat(),
        execution_started=False,
        pid=None,
        exit_code=None,
        timed_out=False,
    )
    try:
        runtime = _runtime_preflight(manifest, model_path, runtime_manifest, repository_root=repository_root)
        load_prepared_run(run_root, repository_root=repository_root)
        for key in ("result_path", "inference_evidence_path"):
            if Path(manifest["paths"][key]).exists():
                raise ValueError("prepared run already contains inference outputs")
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        manifest.update(
            status="preflight_failed", finished_at=datetime.now(timezone.utc).isoformat(), error_type=type(exc).__name__
        )
        _write_manifest(run_root, manifest)
        raise
    with (run_root / "run-started.json").open("x") as stream:
        json.dump({"command": command, "timeout_seconds": timeout_seconds}, stream)
    manifest.update(
        status="running",
        command=command,
        runtime_evidence=runtime,
        timeout_seconds=timeout_seconds,
        started_at=datetime.now(timezone.utc).isoformat(),
    )
    _write_manifest(run_root, manifest)
    process = None
    try:
        with (run_root / "run.log").open("xb") as log:
            process = subprocess.Popen(
                command,
                cwd=repository_root,
                env=_execution_environment(repository_root, runtime),
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            manifest.update(pid=process.pid, execution_started=True)
            _write_manifest(run_root, manifest)
            try:
                process.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                manifest["timed_out"] = True
            finally:
                _stop_group(process)
            manifest["exit_code"] = process.returncode
        manifest["status"] = (
            "timed_out" if manifest["timed_out"] else "completed" if process.returncode == 0 else "failed"
        )
    except (Exception, KeyboardInterrupt, SystemExit) as exc:
        if process is not None:
            _stop_group(process)
            manifest["exit_code"] = process.returncode
        manifest.update(status="failed", error_type=type(exc).__name__)
        if isinstance(exc, KeyboardInterrupt | SystemExit):
            raise
    finally:
        manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
        try:
            load_prepared_run(run_root, repository_root=repository_root)
            manifest["input_integrity_verified"] = True
        except (OSError, ValueError) as exc:
            manifest.update(status="integrity_failed", input_integrity_verified=False, error_type=type(exc).__name__)
        _write_manifest(run_root, manifest)
    try:
        manifest["audit"] = _audit_run(run_root, repository_root=repository_root)
    except (OSError, ValueError, ImportError) as exc:
        manifest["audit"] = {
            "schema": "dsh.evolution.live-smoke-report.v1",
            "process_evidence_complete": False,
            "inference_readback_verified": False,
            "live_contract_passed": False,
            "training_eligible": False,
            "errors": [type(exc).__name__],
            "families": [],
        }
    _seal_run(run_root, manifest)
    return manifest


def main() -> None:
    """Prepare inputs or supervise a separately authorized, verified GPU deployment."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="Freeze verified CPU-only smoke inputs")
    prepare.add_argument("--bundle-dir", type=Path, required=True)
    prepare.add_argument("--run-root", type=Path, required=True)
    run = commands.add_parser("run", help="Run one prepared inference batch after runtime preflight")
    run.add_argument("--run-root", type=Path, required=True)
    run.add_argument("--model-path", type=Path, required=True)
    run.add_argument("--runtime-manifest", type=Path)
    run.add_argument("--timeout-seconds", type=float, required=True)
    run.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            manifest = prepare_run(args.bundle_dir, args.run_root, repository_root=Path.cwd())
        else:
            manifest = run_prepared(
                args.run_root,
                model_path=args.model_path,
                runtime_manifest=args.runtime_manifest,
                timeout_seconds=args.timeout_seconds,
                repository_root=Path.cwd(),
                dry_run=args.dry_run,
            )
    except (OSError, ValueError) as exc:
        parser.exit(2, f"DSH smoke operation failed: {exc}\n")
    if args.command == "prepare":
        print(json.dumps({"status": manifest["status"], "samples": len(manifest["samples"])}, sort_keys=True))
    else:
        print(json.dumps(manifest, sort_keys=True, allow_nan=False))
        if not args.dry_run:
            if manifest["status"] != "completed":
                raise SystemExit(2)
            audit = manifest.get("audit", {})
            if (
                audit.get("process_evidence_complete") is not True
                or audit.get("inference_readback_verified") is not True
            ):
                raise SystemExit(2)
            raise SystemExit(0 if audit.get("live_contract_passed") is True else 1)


if __name__ == "__main__":
    main()
