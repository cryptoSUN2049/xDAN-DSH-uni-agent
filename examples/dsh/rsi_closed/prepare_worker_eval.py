"""Prepare a pinned two-sided RSI worker inference run; never launch or promote."""

import argparse
import json
import os
import subprocess
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import yaml

from examples.dsh.capabilities.launch_context_inference import checked_files, digest, git_state
from examples.dsh.rsi_closed.profile import POLICY_SHA256, build_evaluation_patch, build_patch
from examples.dsh.rsi_closed.worker_verifier import RUNTIME_SHA256, VERIFIER_ID, bundle_digest
from uni_agent.tasks.dsh.rsi_candidates import Registry, _canonical, _spec

ROOT = Path(__file__).resolve().parents[3]
MODULE = "examples.dsh.rsi_closed.worker_verifier"
CASES = ["inspect-discovery", "file-constraint"]
SOURCES = [
    "examples/dsh/rsi_closed/prepare_worker_eval.py",
    "examples/dsh/rsi_closed/launch_worker_eval.py",
    "examples/dsh/rsi_closed/profile.py",
    "examples/dsh/rsi_closed/policy.mjs",
    "examples/dsh/rsi_closed/worker_tasks.py",
    "examples/dsh/rsi_closed/worker_verifier.py",
    "examples/dsh/verifier.py",
    "examples/dsh/evolution_verifier.py",
    "examples/dsh/evolution_verifier_v2.py",
    "uni_agent/tasks/dsh/rsi_candidates.py",
    "uni_agent/tasks/dsh/memory_artifacts.py",
    "uni_agent/tasks/dsh/task.py",
    "uni_agent/tasks/dsh/trajectory_audit.py",
    "uni_agent/framework/framework.py",
    "uni_agent/gateway/session/session.py",
    "uni_agent/gateway/session/types.py",
    "uni_agent/gateway/session/codec.py",
    "uni_agent/agents/dsh/agent.py",
    "uni_agent/agents/dsh/runner.py",
    "examples/dsh/capabilities/launch_context_inference.py",
    "examples/dsh/evolution_task_config_v3_live.yaml",
    "examples/inference/parallel_infer_verl.py",
    "deployment/services/harbor_training_supervisor.py",
    "deployment/versions/g1-deployment-lock.json",
    "deployment/checks/verl_source_overlay.py",
    "deployment/versions/verl-runtime-patches.json",
    "deployment/patches/verl/fefb080-preserve-finish-reason.patch",
]


def canonical_hash(value):
    import hashlib

    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def frozen_cases(root):
    root = Path(root).resolve()
    manifest = json.loads((root / "manifest.json").read_text())
    if manifest.get("schema") != "dsh.rsi-worker-data.v1" or manifest.get("verifier_code_digest") != bundle_digest():
        raise ValueError("Worker cases version/bundle mismatch")
    checked_files(root, manifest["artifacts"])
    inventory = {
        str(path.relative_to(root)) for path in root.rglob("*") if path.is_file() and path != root / "manifest.json"
    }
    if inventory != set(manifest["artifacts"]):
        raise ValueError("Worker cases file inventory mismatch")
    rows = [json.loads(line) for line in (root / "tasks.jsonl").read_text().splitlines()]
    if len(rows) != 2 or [row["metadata"]["task_id"] for row in rows] != ["dsh/rsi-worker/" + case for case in CASES]:
        raise ValueError("Expected exactly the fixed two worker cases")
    for row, case in zip(rows, CASES, strict=False):
        meta = row["metadata"]
        if (
            Path(meta["fixture_path"]) != root / case / "contract.json"
            or digest(meta["fixture_path"]) != meta["fixture_sha256"]
        ):
            raise ValueError("Worker fixture path/hash mismatch")
        if (
            meta["split"] != "validation"
            or meta["verifier_code_digest"] != bundle_digest()
            or meta["environment_digest"] != RUNTIME_SHA256
        ):
            raise ValueError("Worker metadata pin mismatch")
    return rows, manifest["artifacts"]


def model_files(root):
    root = Path(root).resolve()
    files = ["config.json", "tokenizer_config.json", "tokenizer.json"]
    optional = [path.name for path in root.glob("*.json")]
    optional.extend(name for name in ("tokenizer.model", "merges.txt", "vocab.txt") if (root / name).is_file())
    weights = sorted(path.name for path in root.glob("*.safetensors"))
    if not weights:
        raise ValueError("Missing model weights")
    index = root / "model.safetensors.index.json"
    if index.exists():
        if set(json.loads(index.read_text())["weight_map"].values()) != set(weights):
            raise ValueError("Model shard inventory mismatch")
        files.append(index.name)
    return {name: digest(root / name) for name in sorted(set(files + weights + optional))}


def input_pins(cases_root, model_path, pair_id, max_tokens, parent_spec):
    _, files = frozen_cases(cases_root)
    return _input_pins(files, model_files(model_path), pair_id, max_tokens, parent_spec)


def _input_pins(files, weights, pair_id, max_tokens, parent_spec):
    return dict(
        model_sha256=canonical_hash(weights),
        runtime_sha256=RUNTIME_SHA256,
        base_harness_sha256=canonical_hash({"parent_spec": _spec(parent_spec), "policy_sha256": POLICY_SHA256}),
        devset_sha256=canonical_hash(files),
        verifier_sha256=bundle_digest(),
        case_ids=sorted(CASES),
        max_tokens=max_tokens,
        evolution_run_id=pair_id,
    )


def runtime_info(python, executable):
    python, executable = Path(python).absolute(), Path(executable).resolve()
    if (
        not python.is_file()
        or not executable.is_file()
        or not os.access(executable, os.X_OK)
        or digest(executable) != RUNTIME_SHA256
    ):
        raise ValueError("Runner/runtime binary mismatch")
    env = {key: value for key, value in os.environ.items() if not key.startswith("DSH_")}
    env.update(PYTHONPATH=f"{ROOT}:{ROOT / 'verl'}", DSH_RUNTIME_MODE="exe")
    env.pop("PYTHONHOME", None)
    code = (
        "import json;from importlib.metadata import version;"
        "from deepseek_harness_runtime import bundled_runtime_path;"
        "from examples.dsh.rsi_closed import worker_verifier as v;"
        "print(json.dumps(dict(path=str(bundled_runtime_path()),sdk=version('deepseek-harness-sdk'),"
        "version=version('deepseek-harness-runtime-bin'),bundle=v.bundle_digest(),module=v.__file__)))"
    )
    result = subprocess.run(
        [str(python), "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, check=True, timeout=30
    )
    info = json.loads(result.stdout)
    if (
        Path(info["path"]).resolve() != executable
        or info["sdk"] != "0.1.3a2"
        or info["version"] != "0.1.3a2"
        or info["bundle"] != bundle_digest()
        or Path(info["module"]).resolve() != ROOT / "examples/dsh/rsi_closed/worker_verifier.py"
    ):
        raise ValueError("Imported runtime/verifier identity mismatch")
    return {**info, "path": str(executable), "sha256": RUNTIME_SHA256, "python": str(python)}


def write_json(path, value):
    with Path(path).open("xb") as stream:
        stream.write(_canonical(value))
    Path(path).chmod(0o600)


def command_for(data, run, python, model):
    return [
        str(python),
        str(ROOT / "examples/inference/parallel_infer_verl.py"),
        "--data-path",
        str(data / "eval.parquet"),
        "--task-config",
        str(data / "task.yaml"),
        "--n",
        "1",
        "--limit",
        "2",
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
        "1",
        "--gpu-memory-utilization",
        "0.30",
        "--max-model-len",
        "16384",
    ]


def require_clean_sources():
    subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", *SOURCES], cwd=ROOT, check=True, capture_output=True, timeout=15
    )
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all", "--", *SOURCES],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if status.stdout.strip():
        raise ValueError("Commit the execution source files before preparing a reproducible run")
    verl_source_identity()


def verl_source_identity():
    from deployment.checks.verl_source_overlay import verify_verl_source

    return verify_verl_source(ROOT / "verl", require_patched=True)


def check_verl_source(manifest):
    if manifest.get("verl_effective_source") != verl_source_identity():
        raise ValueError("VERL effective source changed; prepare a new run")


def evaluation_sides(mode, candidate_sha256):
    if mode == "parent-baseline" and candidate_sha256 is None:
        return ("H0",)
    if mode == "paired" and isinstance(candidate_sha256, str) and candidate_sha256:
        return ("H0", "H1")
    raise ValueError("Invalid evaluation mode/candidate combination")


def prepare(
    *,
    cases_root,
    model_path,
    pair_id,
    registry_root,
    pins_sha256,
    parent_active_sha256,
    candidate_sha256=None,
    mode="paired",
    runner_python,
    runtime_executable,
    output_dir,
    run_root,
    max_tokens=4096,
    per_turn=512,
    wall_seconds=1800,
):
    expected_sides = evaluation_sides(mode, candidate_sha256)
    output, run, cases, model = [Path(path).absolute() for path in (output_dir, run_root, cases_root, model_path)]
    if any(path.exists() or path.is_symlink() for path in (output, run)):
        raise FileExistsError("Preparation and run roots must be new")
    roots = [output.resolve(), run.resolve(), cases.resolve(), model.resolve(), Path(registry_root).resolve()]
    if any(a.is_relative_to(b) or b.is_relative_to(a) for i, a in enumerate(roots) for b in roots[i + 1 :]):
        raise ValueError("Preparation/run/cases/model/registry roots must be independent")
    if (
        type(max_tokens) is not int
        or not 512 <= max_tokens <= 8192
        or type(per_turn) is not int
        or not 128 <= per_turn <= max_tokens
        or type(wall_seconds) is not int
        or not 1 <= wall_seconds <= 3600
    ):
        raise ValueError("Invalid bounded inference budget")
    registry = Registry(registry_root, pins_sha256)
    active = registry.load_active(parent_active_sha256)
    if mode == "paired":
        registry.load_registered(candidate_sha256, parent_active_sha256)
    rows, case_files = frozen_cases(cases)
    weights = model_files(model)
    expected = _input_pins(case_files, weights, pair_id, max_tokens, active["spec"])
    with registry._locked() as (_, pins):
        if pins != expected:
            raise ValueError("Registry pins differ from actual worker inputs")
    runtime = runtime_info(runner_python, runtime_executable)
    runner_python = Path(runtime["python"])
    checkout = {"integration": git_state(ROOT), "verl": git_state(ROOT / "verl")}
    lock = json.loads((ROOT / "deployment/versions/g1-deployment-lock.json").read_text())
    if checkout["verl"]["head"] != lock["integration"]["verl_revision"]:
        raise ValueError("VERL checkout differs from deployment lock")
    require_clean_sources()
    effective_verl = verl_source_identity()
    sources = {path: digest(ROOT / path) for path in SOURCES}
    output.mkdir(parents=True, mode=0o700, exist_ok=False)
    sides = {}
    read_files = [cases / "file-constraint/sources/constraints.txt"]
    for side in expected_sides:
        data, execution = output / side, run / side
        data.mkdir(mode=0o700)
        render = (
            build_patch(registry_root, pins_sha256, parent_active_sha256, read_files)
            if side == "H0"
            else build_evaluation_patch(registry_root, pins_sha256, parent_active_sha256, candidate_sha256, read_files)
        )
        write_json(data / "overlay.json", render["patch"])
        write_json(data / "render.json", render)
        overlay_sha = digest(data / "overlay.json")
        config = yaml.safe_load((ROOT / "examples/dsh/evolution_task_config_v3_live.yaml").read_text())[0]
        config.update(
            environment_digest=RUNTIME_SHA256,
            verifier_id=VERIFIER_ID,
            verifier_version="1",
            verifier_code_digest=bundle_digest(),
            workdir=str(cases),
            result_root=str(execution / "artifacts/results"),
            verifier_command=[str(runner_python), "-m", MODULE],
        )
        config["agent"].update(
            runner_python=str(runner_python),
            default_workdir=str(cases),
            patches=[str(data / "overlay.json")],
            profile="sdk-minimal",
            run_timeout=wall_seconds,
        )
        config["agent"]["model"].update(max_total_tokens=max_tokens, max_tokens_per_turn=per_turn)
        (data / "task.yaml").write_text(yaml.safe_dump([config], sort_keys=False))
        records = []
        for case, row in zip(CASES, rows, strict=False):
            metadata = {
                **row["metadata"],
                "rsi_pair_id": pair_id,
                "rsi_side": side,
                "rsi_evaluation_mode": mode,
                "rsi_parent_active_sha256": parent_active_sha256,
                "rsi_candidate_sha256": render["selection"]["candidate_sha256"],
                "rsi_content_sha256": render["selection"]["content_sha256"],
                "rsi_overlay_sha256": overlay_sha,
                "rsi_policy_sha256": POLICY_SHA256,
            }
            records.append(
                {
                    "data_source": "dsh/rsi-worker/" + pair_id,
                    "uid": pair_id + "-" + side + "-" + case,
                    "agent_name": "task",
                    "prompt": row["messages"],
                    "extra_info": {"tools_kwargs": {"task": {"name": "dsh_architecture", "metadata": metadata}}},
                }
            )
        pq.write_table(pa.Table.from_pylist(records), data / "eval.parquet")
        patch_paths = json.dumps([str(data / "overlay.json")], ensure_ascii=False, separators=(",", ":")).encode()
        import hashlib

        sides[side] = {
            "run_root": str(execution),
            "selection": render["selection"],
            "overlay_sha256": overlay_sha,
            "patch_paths_sha256": "sha256:" + hashlib.sha256(patch_paths).hexdigest(),
            "command": command_for(data, execution, runner_python, model),
        }
    registry.load_active(parent_active_sha256)
    if mode == "paired":
        registry.load_registered(candidate_sha256, parent_active_sha256)
    manifest = dict(
        schema="dsh.rsi-worker-evaluation.v1",
        status="prepared-not-run",
        mode=mode,
        pair_id=pair_id,
        training=False,
        promoted=False,
        cases_root=str(cases),
        case_files=case_files,
        model_path=str(model),
        model_files=weights,
        runtime=runtime,
        registry_root=str(Path(registry_root).absolute()),
        pins_sha256=pins_sha256,
        parent_active_sha256=parent_active_sha256,
        candidate_sha256=candidate_sha256,
        max_tokens=max_tokens,
        per_turn=per_turn,
        wall_seconds=wall_seconds,
        checkout=checkout,
        verl_effective_source=effective_verl,
        sources=sources,
        sides=sides,
        environment={"DSH_RUNTIME_MODE": "exe", "PYTHONPATH": f"{ROOT}:{ROOT / 'verl'}"},
        files={str(p.relative_to(output)): digest(p) for p in output.rglob("*") if p.is_file()},
    )
    write_json(output / "preparation-manifest.json", manifest)
    for path in output.rglob("*"):
        path.chmod(0o700 if path.is_dir() else 0o600)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True, help="JSON keyword arguments for prepare; no credentials")
    args = parser.parse_args()
    result = prepare(**json.loads(args.config.read_text()))
    print(json.dumps({"status": result["status"], "pair_id": result["pair_id"]}))


if __name__ == "__main__":
    main()
