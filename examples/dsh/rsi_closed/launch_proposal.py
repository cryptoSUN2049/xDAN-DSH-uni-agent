"""Bounded strict proposer inference. Never registers or promotes a candidate."""

import argparse
import json
import os
import subprocess
from pathlib import Path

import pyarrow.parquet as pq
import yaml

from deployment.services.harbor_training_supervisor import supervise
from examples.dsh.rsi_closed import prepare_worker_eval as worker
from examples.dsh.rsi_closed import proposal
from examples.dsh.rsi_closed import proposal_registration as registration
from examples.dsh.rsi_closed.launch_worker_eval import _gpu_idle, _live_inputs
from examples.dsh.rsi_closed.profile import build_patch
from uni_agent.tasks.dsh.rsi_candidates import Registry


def check_launcher_source():
    relative = str(Path(__file__).relative_to(worker.ROOT))
    source = subprocess.run(
        ["git", "show", f"HEAD:{relative}"], cwd=worker.ROOT, capture_output=True, check=True, timeout=15
    ).stdout
    if source != Path(__file__).read_bytes():
        raise ValueError("Commit launcher source before executing a pinned proposal")


def check_sdk(python, environment):
    subprocess.run(
        [python, "-c", "from examples.dsh.rsi_closed.proposal import sdk_final_response; sdk_final_response([])"],
        cwd=worker.ROOT,
        env={**environment, "CUDA_VISIBLE_DEVICES": ""},
        check=True,
        capture_output=True,
        timeout=30,
    )


def live_inputs(path, sha, baseline):
    check_launcher_source()
    manifest = registration.load_bound(path, sha)
    worker.check_verl_source(manifest)
    worker.checked_files(path.parent, manifest["files"])
    worker.checked_files(worker.ROOT, manifest["sources"])
    actual = {str(p.relative_to(path.parent)) for p in path.parent.rglob("*") if p.is_file() and p != path}
    if actual != set(manifest["files"]):
        raise ValueError("Proposal file inventory changed")
    if manifest["checkout"] != {
        "integration": worker.git_state(worker.ROOT),
        "verl": worker.git_state(worker.ROOT / "verl"),
    }:
        raise ValueError("Proposal checkout changed")
    parent_path = Path(manifest["parent_manifest"])
    if registration.load_bound(parent_path, manifest["parent_manifest_sha256"]) != baseline:
        raise ValueError("Parent preparation changed")
    _live_inputs(baseline, parent_path.parent, "H0")
    contract = json.loads((path.parent / "contract.json").read_text())
    if contract != manifest["contract"]:
        raise ValueError("Proposal contract changed")
    proposal.validate_contract(contract)
    registry = Registry(baseline["registry_root"], baseline["pins_sha256"])
    active = registry.load_active(baseline["parent_active_sha256"])
    with registry._locked() as (_, pins):
        if (
            contract["pins_sha256"] != baseline["pins_sha256"]
            or contract["model_sha256"] != pins["model_sha256"]
            or contract["worker_devset_sha256"] != pins["devset_sha256"]
            or contract["pair_id"] != pins["evolution_run_id"]
        ):
            raise ValueError("Proposal pins changed")
    if (
        active["candidate_sha256"] != contract["parent_candidate_sha256"]
        or active["spec"] != contract["parent_spec"]
        or contract["parent_active_sha256"] != baseline["parent_active_sha256"]
    ):
        raise ValueError("Proposal parent identity changed")
    render = build_patch(
        baseline["registry_root"],
        baseline["pins_sha256"],
        baseline["parent_active_sha256"],
        [path.parent / "diagnostics.json"],
    )
    if render != manifest["render"] or worker.digest(path.parent / "overlay.json") != worker.canonical_hash(
        render["patch"]
    ):
        raise ValueError("Proposal parent policy changed")
    return manifest


def preflight(manifest_path, manifest_sha256):
    path = Path(manifest_path).absolute()
    manifest = registration.load_bound(path, manifest_sha256)
    if manifest.get("schema") != "dsh.rsi-proposal-preparation.v1":
        raise ValueError("Wrong proposal schema")
    expected_sources = {str(p.relative_to(worker.ROOT)) for p in [Path(registration.__file__), Path(proposal.__file__)]}
    if set(manifest["sources"]) != expected_sources:
        raise ValueError("Proposal source inventory mismatch")
    check_launcher_source()
    baseline, diagnostics = registration.audit_parent(manifest["parent_manifest"], manifest["parent_manifest_sha256"])
    live_inputs(path, manifest_sha256, baseline)
    if diagnostics != manifest["contract"]["diagnostics"]:
        raise ValueError("Parent observations changed")
    runtime = baseline["runtime"]
    if worker.runtime_info(runtime["python"], runtime["path"]) != runtime:
        raise ValueError("Runtime identity changed")
    run = Path(manifest["run_root"])
    if not run.is_absolute() or ".." in run.parts or run.exists() or run.is_symlink():
        raise ValueError("Proposal run root must be new and absolute")
    roots = [
        run.resolve(),
        path.parent.resolve(),
        Path(baseline["model_path"]).resolve(),
        Path(baseline["registry_root"]).resolve(),
        Path(baseline["cases_root"]).resolve(),
    ]
    if any(a.is_relative_to(b) or b.is_relative_to(a) for i, a in enumerate(roots) for b in roots[i + 1 :]):
        raise ValueError("Proposal roots overlap")
    command = worker.command_for(path.parent, run, runtime["python"], Path(baseline["model_path"]))
    command[command.index("--limit") + 1] = "1"
    if manifest["command"] != command:
        raise ValueError("Proposal command changed")
    if type(manifest["wall_seconds"]) is not int or manifest["wall_seconds"] != baseline["wall_seconds"]:
        raise ValueError("Proposal wall budget changed")
    expected_config = yaml.safe_load((Path(manifest["parent_manifest"]).parent / "H0/task.yaml").read_text())[0]
    expected_config.update(
        verifier_id=proposal.VERIFIER_ID,
        verifier_code_digest=proposal.bundle_digest(),
        verifier_command=[runtime["python"], "-m", "examples.dsh.rsi_closed.proposal"],
        workdir=str(path.parent),
        result_root=str(run / "artifacts/results"),
    )
    expected_config["agent"].update(patches=[str(path.parent / "overlay.json")], default_workdir=str(path.parent))
    if yaml.safe_load((path.parent / "task.yaml").read_text()) != [expected_config]:
        raise ValueError("Proposal task config/budget differs from parent contract")
    rows = pq.read_table(path.parent / "eval.parquet").to_pylist()
    metadata = manifest["metadata"]
    if (
        metadata.get("phase") != "proposal"
        or metadata.get("verifier_code_digest") != proposal.bundle_digest()
        or metadata.get("fixture_sha256") != worker.digest(path.parent / "contract.json")
        or metadata.get("fixture_path") != str(path.parent / "contract.json")
    ):
        raise ValueError("Proposal metadata identity changed")
    if (
        len(rows) != 1
        or rows[0]["prompt"] != manifest["contract"]["messages"]
        or rows[0]["extra_info"]["tools_kwargs"]["task"] != {"name": "dsh_architecture", "metadata": metadata}
    ):
        raise ValueError("Proposal must have exactly the frozen single task")
    expected_env = {"DSH_RUNTIME_MODE": "exe", "PYTHONPATH": f"{worker.ROOT}:{worker.ROOT / 'verl'}"}
    if manifest["environment"] != expected_env:
        raise ValueError("Proposal environment changed")
    environment = {key: value for key, value in os.environ.items() if not key.startswith("DSH_")}
    environment.update(expected_env)
    environment["CUDA_VISIBLE_DEVICES"] = "0"
    for key in ("RAY_ADDRESS", "PYTHONHOME", "PYTORCH_CUDA_ALLOC_CONF"):
        environment.pop(key, None)
    environment["PATH"] = f"{Path(runtime['python']).parent}:{os.environ.get('PATH', '')}"
    ray = Path("/tmp") / ("rsi-proposer-" + worker.canonical_hash(str(run))[7:19])
    if ray.exists() or ray.is_symlink():
        raise ValueError("Owned Ray directory already exists")
    environment["RAY_TMPDIR"] = str(ray)
    check_sdk(runtime["python"], environment)
    return {
        "path": path,
        "sha": manifest_sha256,
        "manifest": manifest,
        "baseline": baseline,
        "run": run,
        "command": command,
        "environment": environment,
    }


def launch(manifest_path, manifest_sha256):
    prepared = preflight(manifest_path, manifest_sha256)
    _gpu_idle()
    run, manifest, baseline = prepared["run"], prepared["manifest"], prepared["baseline"]
    run.mkdir(parents=True, mode=0o700, exist_ok=False)
    worker.write_json(
        run / "launch-manifest.json",
        {
            "schema": "dsh.rsi-proposal-launch.v1",
            "prepared_manifest_sha256": manifest_sha256,
            "command": prepared["command"],
            "environment": manifest["environment"],
            "wall_seconds": manifest["wall_seconds"],
        },
    )
    worker.write_json(
        run / "launcher-evidence.json",
        {
            "launcher_sha256": worker.digest(Path(__file__)),
            "ray_tmpdir": prepared["environment"]["RAY_TMPDIR"],
            "cuda_visible_devices": prepared["environment"]["CUDA_VISIBLE_DEVICES"],
            "training": False,
            "automatic_registration": False,
        },
    )
    health = lambda: live_inputs(prepared["path"], manifest_sha256, baseline)
    result = supervise(
        prepared["command"], worker.ROOT, prepared["environment"], run, health, wall_seconds=manifest["wall_seconds"]
    )
    if result["exit_code"] != 0:
        return result
    health()
    final_baseline, final_diagnostics = registration.audit_parent(
        manifest["parent_manifest"], manifest["parent_manifest_sha256"]
    )
    if final_baseline != baseline or final_diagnostics != manifest["contract"]["diagnostics"]:
        raise ValueError("Parent evidence changed while proposer was running")
    evidence = json.loads((run / "inference-evidence.json").read_text())
    if len(evidence.get("samples", [])) != 1:
        raise ValueError("Proposer must complete exactly one registered sample")
    # Full original-token and receipt audit after the child finishes; no registry mutation.
    episode = registration.audit_episode(run, manifest["metadata"], max_tokens=baseline["max_tokens"])
    scored = proposal.score(manifest["contract"], episode["envelope"], episode["events"])
    patch_paths = json.dumps(
        [str(prepared["path"].parent / "overlay.json")], ensure_ascii=False, separators=(",", ":")
    ).encode()
    dsh = episode["envelope"]["dsh"]
    if (
        dsh.get("profile") != "sdk-minimal"
        or dsh.get("patches_sha256") != proposal.parent._sha256_bytes(patch_paths)
        or scored["eligible"] is not True
        or scored["reward"] != episode["reward"]
    ):
        raise ValueError("Proposer actual policy/score evidence mismatch")
    worker.write_json(
        run / "proposal-audit.json",
        {
            "schema": "dsh.rsi-proposal-audit.v1",
            "proof": episode["proof"],
            "reward": scored["reward"],
            "registration_ready": scored["reward"] == 1,
            "registered": False,
            "promoted": False,
            "training": False,
        },
    )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--launch", action="store_true")
    args = parser.parse_args()
    if args.launch:
        result = launch(args.manifest, args.manifest_sha256)
        print(json.dumps(result))
        return 0 if result["exit_code"] == 0 else 1
    value = preflight(args.manifest, args.manifest_sha256)
    print(json.dumps({"status": "preflight-passed-not-run", "command": value["command"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
