"""Launch one prepared RSI worker side through existing strict inference and supervisor."""

import argparse
import json
import os
import subprocess
from pathlib import Path

import pyarrow.parquet as pq
import yaml

from deployment.services.harbor_training_supervisor import supervise
from examples.dsh.rsi_closed import prepare_worker_eval as prep
from examples.dsh.rsi_closed.profile import build_evaluation_patch, build_patch
from uni_agent.tasks.dsh.rsi_candidates import Registry


def _live_inputs(manifest, output, side):
    prep.check_verl_source(manifest)
    if set(manifest["sources"]) != set(prep.SOURCES):
        raise ValueError("Source inventory differs from fixed entry")
    mode = manifest.get("mode", "paired")
    sides = prep.evaluation_sides(mode, manifest.get("candidate_sha256"))
    if set(manifest["sides"]) != set(sides) or side not in sides:
        raise ValueError("Evaluation mode/side mismatch")
    registry = Registry(manifest["registry_root"], manifest["pins_sha256"])
    registry.load_active(manifest["parent_active_sha256"])
    if mode == "paired":
        registry.load_registered(manifest["candidate_sha256"], manifest["parent_active_sha256"])
    prep.checked_files(output, manifest["files"])
    prep.checked_files(Path(manifest["cases_root"]), manifest["case_files"])
    prep.checked_files(prep.ROOT, manifest["sources"])
    for bound_side in sides:
        rows = pq.read_table(output / bound_side / "eval.parquet").to_pylist()
        if len(rows) != 2 or any(
            row["extra_info"]["tools_kwargs"]["task"]["metadata"].get("rsi_evaluation_mode", "paired") != mode
            or row["extra_info"]["tools_kwargs"]["task"]["metadata"].get("rsi_side") != bound_side
            for row in rows
        ):
            raise ValueError("Prepared rows belong to a different evaluation mode/side")
    read_files = [Path(manifest["cases_root"]) / "file-constraint/sources/constraints.txt"]
    args = (manifest["registry_root"], manifest["pins_sha256"], manifest["parent_active_sha256"])
    render = (
        build_patch(*args, read_files)
        if side == "H0"
        else build_evaluation_patch(*args, manifest["candidate_sha256"], read_files)
    )
    if (
        render["selection"] != manifest["sides"][side]["selection"]
        or render != json.loads((output / side / "render.json").read_text())
        or prep.canonical_hash(render["patch"]) != manifest["sides"][side]["overlay_sha256"]
    ):
        raise ValueError("Live registry/overlay differs from prepared side")


def preflight(manifest_path, manifest_sha256, side):
    path = Path(manifest_path).resolve()
    if prep.digest(path) != manifest_sha256:
        raise ValueError("External preparation manifest hash mismatch")
    manifest = json.loads(path.read_text())
    if manifest.get("schema") != "dsh.rsi-worker-evaluation.v1" or side not in ("H0", "H1"):
        raise ValueError("Invalid RSI evaluation side/schema")
    output = path.parent
    _live_inputs(manifest, output, side)
    actual = {str(p.relative_to(output)) for p in output.rglob("*") if p.is_file() and p != path}
    if actual != set(manifest["files"]):
        raise ValueError("Preparation file inventory mismatch")
    checkout = {"integration": prep.git_state(prep.ROOT), "verl": prep.git_state(prep.ROOT / "verl")}
    if checkout != manifest["checkout"]:
        raise ValueError("Checkout changed since preparation")
    runtime = manifest["runtime"]
    if prep.runtime_info(runtime["python"], runtime["path"]) != runtime:
        raise ValueError("Runtime identity changed")
    weights = prep.model_files(manifest["model_path"])
    if weights != manifest["model_files"]:
        raise ValueError("Model bytes changed")
    registry = Registry(manifest["registry_root"], manifest["pins_sha256"])
    active = registry.load_active(manifest["parent_active_sha256"])
    _, case_files = prep.frozen_cases(manifest["cases_root"])
    expected_pins = prep._input_pins(case_files, weights, manifest["pair_id"], manifest["max_tokens"], active["spec"])
    with registry._locked() as (_, pins):
        if pins != expected_pins:
            raise ValueError("Registry pins no longer match worker inputs")
    item = manifest["sides"][side]
    run = Path(item["run_root"])
    if not run.is_absolute() or run.exists() or run.is_symlink():
        raise ValueError("Side run root must be new")
    command = prep.command_for(output / side, run, runtime["python"], Path(manifest["model_path"]))
    if command != item["command"]:
        raise ValueError("Inference command differs from fixed strict entry")
    config = yaml.safe_load((output / side / "task.yaml").read_text())[0]
    if (
        config["agent"]["patches"] != [str(output / side / "overlay.json")]
        or config["agent"]["profile"] != "sdk-minimal"
        or config["verifier_command"] != [runtime["python"], "-m", prep.MODULE]
    ):
        raise ValueError("Task does not load the bound SDK policy/verifier")
    expected_rows = pq.read_table(output / side / "eval.parquet").to_pylist()
    environment = {key: value for key, value in os.environ.items() if not key.startswith("DSH_")}
    environment.update(manifest["environment"])
    if manifest["environment"] != {"DSH_RUNTIME_MODE": "exe", "PYTHONPATH": f"{prep.ROOT}:{prep.ROOT / 'verl'}"}:
        raise ValueError("Unexpected worker environment")
    for key in ("RAY_ADDRESS", "PYTHONHOME", "PYTORCH_CUDA_ALLOC_CONF"):
        environment.pop(key, None)
    environment["PATH"] = f"{Path(runtime['python']).parent}:{os.environ.get('PATH', '')}"
    ray_tmp = Path("/tmp") / ("rsi-worker-" + prep.canonical_hash(str(run))[7:19])
    if ray_tmp.exists() or ray_tmp.is_symlink():
        raise ValueError("Owned Ray directory already exists")
    environment["RAY_TMPDIR"] = str(ray_tmp)
    return dict(manifest=manifest, output=output, run=run, command=command, environment=environment, rows=expected_rows)


def _gpu_idle():
    result = subprocess.run(
        ["nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader,nounits"],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if result.stdout.strip():
        raise RuntimeError("GPU has active compute processes; this single-GPU run was not started")


def result_binding(prepared, side):
    manifest, run = prepared["manifest"], prepared["run"]
    evidence = json.loads((run / "inference-evidence.json").read_text())
    if evidence.get("status") != "completed" or len(evidence.get("samples", [])) != 2:
        raise ValueError("Strict inference did not complete both worker samples")
    from examples.inference.parallel_infer_verl import _require_complete_readback

    samples = evidence["samples"]
    uids = [sample["uid"] for sample in samples]
    if len(set(uids)) != 2:
        raise ValueError("Expected two independent framework samples")
    readback = evidence.get("readback")
    if not isinstance(readback, dict):
        raise ValueError("Missing actual strict inference readback")
    _require_complete_readback(readback, uids, 1)
    sampled = {sample["metadata"]["task_id"]: sample for sample in samples}
    scores = {
        key.rsplit("_", 2)[0]: score for key, score in zip(readback["final_keys"], readback["scores"], strict=True)
    }
    expected = {
        row["extra_info"]["tools_kwargs"]["task"]["metadata"]["task_id"]: row["extra_info"]["tools_kwargs"]["task"][
            "metadata"
        ]
        for row in prepared["rows"]
    }
    entries = sorted((run / "artifacts/results").glob("*/agent-result.json"))
    if len(entries) != 2:
        raise ValueError("Expected two actual worker envelopes")
    seen, sessions, artifacts = set(), set(), {}
    for path in entries:
        envelope = json.loads(path.read_text())
        meta, dsh = envelope["metadata"], envelope["dsh"]
        task = meta["task_id"]
        session = dsh["dsh_session_id"]
        if task in seen or task not in expected or meta != expected[task] or session in sessions:
            raise ValueError("Worker result identity differs from prepared case/side")
        if dsh["profile"] != "sdk-minimal" or dsh["patches_sha256"] != manifest["sides"][side]["patch_paths_sha256"]:
            raise ValueError("Actual SDK patch path identity mismatch")
        if envelope.get("finished") is not True:
            raise ValueError("Worker episode unfinished")
        receipt = path.with_name("verifier-receipt.json")
        if not receipt.is_file():
            raise ValueError("Missing actual worker receipt")
        value = json.loads(receipt.read_text())
        from uni_agent.tasks.dsh.trajectory_audit import _canonical_json_bytes, _digest, _require_finite

        body = {key: item for key, item in value.items() if key != "receipt_id"}
        if receipt.read_bytes() != _canonical_json_bytes(value) or value.get("receipt_id") != _digest(
            _canonical_json_bytes(body)
        ):
            raise ValueError("Worker receipt canonical hash mismatch")
        if (
            value.get("schema") != "dsh.verifier-receipt.v1"
            or any(value.get(flag) is not True for flag in ("fresh", "eligible", "finished"))
            or value.get("artifact_sha256") != prep.digest(path)
            or value.get("dsh_session_id") != session
            or value.get("trace_sha256") != dsh.get("trace_sha256")
            or value.get("environment_digest") != meta["environment_digest"]
            or value.get("task_id") != task
            or value.get("task_version") != meta["task_version"]
            or value.get("verifier")
            != {
                "id": meta["verifier_id"],
                "version": meta["verifier_version"],
                "code_digest": meta["verifier_code_digest"],
            }
        ):
            raise ValueError("Worker receipt identity/admission mismatch")
        reward = _require_finite(value.get("reward"), field="worker receipt reward")
        if reward not in (0.0, 1.0):
            raise ValueError("Worker receipt must use binary business reward")
        sample = sampled.get(task)
        if sample is None or sample["metadata"] != meta or value.get("reward") != scores[sample["uid"]]:
            raise ValueError("Worker receipt differs from actual inference readback")
        seen.add(task)
        sessions.add(session)
        artifacts[task] = {
            "artifact_sha256": prep.digest(path),
            "receipt_sha256": prep.digest(receipt),
            "dsh_session_id": session,
        }
    if seen != set(expected) or len(seen) != 2 or len(sessions) != 2 or set(sampled) != seen:
        raise ValueError("Worker case/session coverage is incomplete")
    return {
        "scope": "SDK patch + canonical receipt + readback consistency; fixed strict runner owns token admission",
        "strict_readback_verified": True,
        "raw_token_reaudit": False,
        "schema": "dsh.rsi-worker-runtime-binding.v1",
        "mode": manifest.get("mode", "paired"),
        "side": side,
        "training": False,
        "promotion_verified": False,
        "sdk_patch_path_binding_verified": True,
        "policy_self_attestation": False,
        "overlay_sha256": manifest["sides"][side]["overlay_sha256"],
        "selection": manifest["sides"][side]["selection"],
        "artifacts": artifacts,
    }


def launch(manifest_path, manifest_sha256, side):
    prepared = preflight(manifest_path, manifest_sha256, side)
    _gpu_idle()
    run, manifest = prepared["run"], prepared["manifest"]
    run.mkdir(parents=True, mode=0o700, exist_ok=False)
    prep.write_json(
        run / "launch-manifest.json",
        {
            "schema": "dsh.rsi-worker-launch.v1",
            "mode": manifest.get("mode", "paired"),
            "prepared_manifest_sha256": manifest_sha256,
            "side": side,
            "command": prepared["command"],
            "environment": {
                key: prepared["environment"][key] for key in ("DSH_RUNTIME_MODE", "PYTHONPATH", "RAY_TMPDIR")
            },
            "wall_seconds": manifest["wall_seconds"],
        },
    )
    check = lambda: _live_inputs(manifest, prepared["output"], side)
    result = supervise(
        prepared["command"], prep.ROOT, prepared["environment"], run, check, wall_seconds=manifest["wall_seconds"]
    )
    if result["exit_code"] != 0:
        return result
    check()
    prep.write_json(run / "runtime-binding.json", result_binding(prepared, side))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--side", choices=["H0", "H1"], required=True)
    parser.add_argument(
        "--launch", action="store_true", help="Actually start the bounded GPU inference; omit for CPU preflight"
    )
    args = parser.parse_args()
    if args.launch:
        result = launch(args.manifest, args.manifest_sha256, args.side)
        print(json.dumps(result))
        return 0 if result["exit_code"] == 0 else 1
    result = preflight(args.manifest, args.manifest_sha256, args.side)
    print(json.dumps({"status": "preflight-only", "command": result["command"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
