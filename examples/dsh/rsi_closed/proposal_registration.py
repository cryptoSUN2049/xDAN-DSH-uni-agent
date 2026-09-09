"""Private control-plane proposal preparation/audit/registration; no loop or promotion."""

import hashlib
import json
import subprocess
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import yaml

from examples.dsh.ops.audit_qwen3_4b_online_rl import _audit_dump, _load_dump_trajectory
from examples.dsh.rsi_closed import prepare_worker_eval as worker
from examples.dsh.rsi_closed import proposal
from examples.dsh.rsi_closed.launch_worker_eval import _live_inputs, result_binding
from examples.dsh.rsi_closed.profile import build_patch
from uni_agent.tasks.dsh.rsi_candidates import Registry


def require_clean_sources():
    worker.require_clean_sources()
    paths = [str(p.relative_to(worker.ROOT)) for p in [Path(__file__), Path(proposal.__file__)]]
    subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", *paths],
        cwd=worker.ROOT,
        check=True,
        capture_output=True,
        timeout=15,
    )
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all", "--", *paths],
        cwd=worker.ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if status.stdout.strip():
        raise ValueError("Commit proposer execution sources before preparing")


def load_bound(path, sha):
    path = Path(path).absolute()
    if worker.digest(path) != sha:
        raise ValueError("External manifest hash mismatch")
    return json.loads(path.read_text())


def audit_episode(run, metadata, *, max_tokens):
    """Audit one exact episode using existing v2 NPZ/DSH receipt validation."""
    from examples.inference.parallel_infer_verl import _require_complete_readback

    run = Path(run)
    evidence = json.loads((run / "inference-evidence.json").read_text())
    samples = evidence["samples"]
    if evidence["status"] != "completed" or not samples:
        raise ValueError("Unfinished strict inference")
    uids = [sample["uid"] for sample in samples]
    if len(set(uids)) != len(uids):
        raise ValueError("Duplicate registered sample")
    _require_complete_readback(evidence["readback"], uids, 1)
    matched = [s for s in samples if s["metadata"] == metadata]
    if len(matched) != 1:
        raise ValueError("Missing/duplicate expected proposal/worker sample")
    uid = matched[0]["uid"]
    dumps = []
    for path in (run / "agent-logs").rglob("trajectory.json"):
        meta = json.loads(path.read_text())
        if meta.get("group_uid") == uid:
            dumps.append((path, meta))
    if len(dumps) != 1:
        raise ValueError("Require one complete raw trajectory for this episode")
    dump_path, meta = dumps[0]
    if (
        meta.get("schema") != "uni-agent.trajectory-dump.v2"
        or meta.get("partition_id") != "val"
        or metadata.get("split") != "validation"
        or meta.get("num_trajectories") != 1
        or meta.get("group_size") != 1
        or meta.get("session_index") != 0
        or meta.get("session_id") != meta.get("gateway_session_id")
    ):
        raise ValueError("Unexpected raw trajectory shape/session")
    trace_root, result_root = run / "artifacts/traces", run / "artifacts/results"
    reasons, keys, rewards, receipts = _audit_dump(
        dump_path=dump_path, meta=meta, trace_root=trace_root, result_root=result_root
    )
    if reasons or len(keys) != 1 or len(receipts) != 1:
        raise ValueError("Raw token/trace/receipt audit failed: " + str(reasons))
    read = evidence["readback"]
    final = {key: score for key, score in zip(read["final_keys"], read["scores"], strict=True)}
    if keys[0] not in read["traj_keys"] or final.get(keys[0]) != rewards[0]:
        raise ValueError("Raw trajectory not bound to consumed inference readback")
    trajectory = _load_dump_trajectory(
        npz_bytes=(dump_path.parent / "trajectory.npz").read_bytes(),
        trajectory_meta=meta["trajectories"][0],
        trajectory_index=0,
    )
    tokens = sum(trajectory.response_mask)
    if not 0 < tokens <= max_tokens:
        raise ValueError("Actual generated tokens exceed frozen budget")
    dsh = trajectory.extra_fields["dsh_reward_info"]["dsh"]
    result_key = hashlib.sha256(f"{dsh['dsh_session_id']}\0{dsh['trace_sha256']}".encode()).hexdigest()[:24]
    artifact = result_root / result_key / "agent-result.json"
    envelope = json.loads(artifact.read_text())
    if envelope["metadata"] != metadata:
        raise ValueError("Artifact belongs to another stage/task")
    trace = trace_root / hashlib.sha256(dsh["rollout_id"].encode()).hexdigest()[:24] / "session.jsonl"
    events = proposal.parent._load_trace(trace, dsh["trace_sha256"])
    return {
        "envelope": envelope,
        "events": events,
        "reward": rewards[0],
        "proof": {
            "uid": uid,
            "dsh_session_id": dsh["dsh_session_id"],
            "artifact_sha256": worker.digest(artifact),
            "trace_sha256": worker.digest(trace),
            "receipt_sha256": receipts[0],
            "dump_sha256": worker.digest(dump_path),
            "npz_sha256": worker.digest(dump_path.parent / "trajectory.npz"),
            "inference_evidence_sha256": worker.digest(run / "inference-evidence.json"),
            "transfer_queue_key": keys[0],
            "model_tokens": tokens,
        },
    }


def audit_parent(path, sha):
    path = Path(path).absolute()
    manifest = load_bound(path, sha)
    if manifest.get("mode") != "parent-baseline" or set(manifest["sides"]) != {"H0"}:
        raise ValueError("Proposal requires an independent real parent baseline")
    _live_inputs(manifest, path.parent, "H0")
    if worker.model_files(manifest["model_path"]) != manifest["model_files"]:
        raise ValueError("Parent model bytes changed")
    rows = pq.read_table(path.parent / "H0/eval.parquet").to_pylist()
    prepared = {"manifest": manifest, "run": Path(manifest["sides"]["H0"]["run_root"]), "rows": rows}
    result_binding(prepared, "H0")
    episodes = [
        audit_episode(
            prepared["run"], row["extra_info"]["tools_kwargs"]["task"]["metadata"], max_tokens=manifest["max_tokens"]
        )
        for row in rows
    ]
    diagnostics = {
        "schema": "dsh.rsi-parent-diagnostics.v1",
        "pair_id": manifest["pair_id"],
        "parent_spec": manifest["sides"]["H0"]["selection"]["spec"],
        "cases": [],
    }
    for row, episode in zip(rows, episodes, strict=True):
        calls = proposal.parent._tool_calls(episode["events"])
        results = proposal.parent._tool_results(episode["events"])
        successful = sorted(
            {
                call["name"]
                for call in calls
                if call["call_id"] in results
                and not results[call["call_id"]]["is_error"]
                and results[call["call_id"]]["error"] is None
            }
        )
        denied = sorted(
            {
                call["name"]
                for call in calls
                if call["call_id"] in results and "RSI_POLICY_DENIED" in results[call["call_id"]]["text"]
            }
        )
        diagnostics["cases"].append(
            {
                "task_id": row["extra_info"]["tools_kwargs"]["task"]["metadata"]["task_id"],
                "reward": episode["reward"],
                "finished": True,
                "eligible": True,
                "proof": episode["proof"],
                "successful_tools": successful,
                "denied_tools": denied,
            }
        )
    return manifest, diagnostics


def prepare_proposal(parent_manifest, parent_manifest_sha256, output_dir, run_root):
    """Produce one standard Task/parquet plus an immutable controller manifest."""
    require_clean_sources()
    parent_path = Path(parent_manifest).absolute()
    baseline, diagnostics = audit_parent(parent_path, parent_manifest_sha256)
    output, run = Path(output_dir).absolute(), Path(run_root).absolute()
    if output.exists() or output.is_symlink() or run.exists() or run.is_symlink():
        raise FileExistsError("Proposal roots must be new")
    roots = [
        output.resolve(),
        run.resolve(),
        parent_path.parent.resolve(),
        Path(baseline["registry_root"]).resolve(),
        Path(baseline["model_path"]).resolve(),
        Path(baseline["cases_root"]).resolve(),
    ]
    if any(a.is_relative_to(b) or b.is_relative_to(a) for i, a in enumerate(roots) for b in roots[i + 1 :]):
        raise ValueError("Proposal roots must be independent")
    registry = Registry(baseline["registry_root"], baseline["pins_sha256"])
    active = registry.load_active(baseline["parent_active_sha256"])
    with registry._locked() as (_, pins):
        pins = dict(pins)
    output.mkdir(parents=True, mode=0o700)
    worker.write_json(output / "diagnostics.json", diagnostics)
    contract = {
        "schema": "dsh.rsi-proposal.v1",
        "pair_id": baseline["pair_id"],
        "parent_active_sha256": baseline["parent_active_sha256"],
        "parent_candidate_sha256": active["candidate_sha256"],
        "parent_content_sha256": active["content_sha256"],
        "pins_sha256": baseline["pins_sha256"],
        "model_sha256": pins["model_sha256"],
        "runtime_sha256": proposal.RUNTIME_SHA256,
        "worker_devset_sha256": pins["devset_sha256"],
        "diagnostics": diagnostics,
        "diagnostics_sha256": worker.canonical_hash(diagnostics),
        "parent_spec": active["spec"],
        "messages": proposal.messages(diagnostics),
        "sdk_api_sha256": proposal.SDK_API_SHA256,
    }
    proposal.validate_contract(contract)
    worker.write_json(output / "contract.json", contract)
    render = build_patch(
        baseline["registry_root"],
        baseline["pins_sha256"],
        baseline["parent_active_sha256"],
        [output / "diagnostics.json"],
    )
    worker.write_json(output / "overlay.json", render["patch"])
    metadata = {
        "task_id": "dsh/rsi-proposal/" + baseline["pair_id"],
        "task_version": "1",
        "verifier_id": proposal.VERIFIER_ID,
        "verifier_version": "1",
        "verifier_code_digest": proposal.bundle_digest(),
        "environment_digest": proposal.RUNTIME_SHA256,
        "fixture_path": str(output / "contract.json"),
        "fixture_sha256": worker.digest(output / "contract.json"),
        "split": "validation",
        "dataset_role": "development",
        "phase": "proposal",
    }
    row = {
        "uid": baseline["pair_id"] + "-proposal",
        "data_source": "dsh/rsi-proposal",
        "agent_name": "task",
        "prompt": contract["messages"],
        "extra_info": {"tools_kwargs": {"task": {"name": "dsh_architecture", "metadata": metadata}}},
    }
    pq.write_table(pa.Table.from_pylist([row]), output / "eval.parquet")
    config = yaml.safe_load((parent_path.parent / "H0/task.yaml").read_text())[0]
    config.update(
        verifier_id=proposal.VERIFIER_ID,
        verifier_code_digest=proposal.bundle_digest(),
        verifier_command=[baseline["runtime"]["python"], "-m", "examples.dsh.rsi_closed.proposal"],
        workdir=str(output),
        result_root=str(run / "artifacts/results"),
    )
    config["agent"].update(patches=[str(output / "overlay.json")], default_workdir=str(output))
    (output / "task.yaml").write_text(yaml.safe_dump([config], sort_keys=False))
    command = worker.command_for(output, run, baseline["runtime"]["python"], Path(baseline["model_path"]))
    command[command.index("--limit") + 1] = "1"
    manifest = {
        "schema": "dsh.rsi-proposal-preparation.v1",
        "verl_effective_source": baseline["verl_effective_source"],
        "checkout": {"integration": worker.git_state(worker.ROOT), "verl": worker.git_state(worker.ROOT / "verl")},
        "status": "prepared-not-run",
        "training": False,
        "parent_manifest": str(parent_path),
        "parent_manifest_sha256": parent_manifest_sha256,
        "run_root": str(run),
        "metadata": metadata,
        "contract": contract,
        "render": render,
        "command": command,
        "environment": baseline["environment"],
        "wall_seconds": baseline["wall_seconds"],
        "sources": {
            str(p.relative_to(worker.ROOT)): worker.digest(p) for p in [Path(__file__), Path(proposal.__file__)]
        },
        "files": {str(p.relative_to(output)): worker.digest(p) for p in output.rglob("*") if p.is_file()},
    }
    registry.load_active(baseline["parent_active_sha256"])
    worker.write_json(output / "preparation-manifest.json", manifest)
    for path in output.iterdir():
        path.chmod(0o600)
    return manifest


def register_verified_proposal(manifest_path, expected_manifest_sha256, output_path):
    """No candidate argument: only an audited student's exact final text can be registered."""
    path = Path(manifest_path).absolute()
    manifest = load_bound(path, expected_manifest_sha256)
    if manifest.get("schema") != "dsh.rsi-proposal-preparation.v1":
        raise ValueError("Invalid proposal preparation schema")
    expected_sources = {str(p.relative_to(worker.ROOT)) for p in [Path(__file__), Path(proposal.__file__)]}
    if set(manifest["sources"]) != expected_sources:
        raise ValueError("Proposal execution source inventory mismatch")
    actual_files = {str(p.relative_to(path.parent)) for p in path.parent.rglob("*") if p.is_file() and p != path}
    if set(manifest["files"]) != actual_files:
        raise ValueError("Proposal preparation file inventory mismatch")
    checkout = {"integration": worker.git_state(worker.ROOT), "verl": worker.git_state(worker.ROOT / "verl")}
    if manifest["checkout"] != checkout:
        raise ValueError("Proposal checkout changed")
    worker.check_verl_source(manifest)
    worker.checked_files(path.parent, manifest["files"])
    worker.checked_files(worker.ROOT, manifest["sources"])
    baseline, diagnostics = audit_parent(manifest["parent_manifest"], manifest["parent_manifest_sha256"])
    contract = json.loads((path.parent / "contract.json").read_text())
    if contract != manifest["contract"] or diagnostics != contract["diagnostics"]:
        raise ValueError("Proposal parent diagnostics/input changed")
    registry = Registry(baseline["registry_root"], baseline["pins_sha256"])
    active = registry.load_active(contract["parent_active_sha256"])
    with registry._locked() as (_, pins):
        if (
            contract["pins_sha256"] != baseline["pins_sha256"]
            or contract["model_sha256"] != pins["model_sha256"]
            or contract["worker_devset_sha256"] != pins["devset_sha256"]
            or contract["pair_id"] != pins["evolution_run_id"]
        ):
            raise ValueError("Proposal contract differs from worker registry pins")
    if (
        manifest["metadata"].get("verifier_id") != proposal.VERIFIER_ID
        or manifest["metadata"].get("verifier_code_digest") != proposal.bundle_digest()
        or manifest["metadata"].get("fixture_sha256") != worker.digest(path.parent / "contract.json")
        or manifest["metadata"].get("fixture_path") != str(path.parent / "contract.json")
        or manifest["metadata"].get("phase") != "proposal"
    ):
        raise ValueError("Proposal task/verifier identity mismatch")
    if active["candidate_sha256"] != contract["parent_candidate_sha256"] or active["spec"] != contract["parent_spec"]:
        raise ValueError("Proposal parent selection mismatch")
    runtime = baseline["runtime"]
    if worker.runtime_info(runtime["python"], runtime["path"]) != runtime:
        raise ValueError("Runtime identity changed")
    render = build_patch(
        baseline["registry_root"],
        baseline["pins_sha256"],
        contract["parent_active_sha256"],
        [path.parent / "diagnostics.json"],
    )
    if render != manifest["render"] or worker.canonical_hash(render["patch"]) != worker.digest(
        path.parent / "overlay.json"
    ):
        raise ValueError("Proposal overlay identity changed")
    run = Path(manifest["run_root"])
    launch = json.loads((run / "launch-manifest.json").read_text())
    expected_launch = {
        "schema": "dsh.rsi-proposal-launch.v1",
        "prepared_manifest_sha256": expected_manifest_sha256,
        "command": manifest["command"],
        "environment": manifest["environment"],
        "wall_seconds": manifest["wall_seconds"],
    }
    if launch != expected_launch:
        raise ValueError("Actual proposer launch differs from frozen model/command/budget")
    supervised = json.loads((run / "supervisor-result.json").read_text())
    if type(supervised.get("exit_code")) is not int or supervised["exit_code"] != 0:
        raise ValueError("Proposer supervisor did not finish successfully")
    evidence = json.loads((run / "inference-evidence.json").read_text())
    if len(evidence["samples"]) != 1:
        raise ValueError("Require exactly one proposer attempt")
    episode = audit_episode(run, manifest["metadata"], max_tokens=baseline["max_tokens"])
    patch_paths = json.dumps([str(path.parent / "overlay.json")], ensure_ascii=False, separators=(",", ":")).encode()
    if (
        episode["envelope"]["dsh"].get("patches_sha256") != proposal.parent._sha256_bytes(patch_paths)
        or episode["envelope"]["dsh"].get("profile") != "sdk-minimal"
    ):
        raise ValueError("Actual proposer did not load parent overlay")
    scored = proposal.score(contract, episode["envelope"], episode["events"])
    if scored["eligible"] is not True or scored["reward"] != episode["reward"] or scored["reward"] != 1:
        raise ValueError("Proposal invalid, unchanged, or receipt score disagrees")
    parsed = proposal.parse_response(episode["envelope"]["response"], active["spec"])
    target = Path(output_path).absolute()
    if target.exists() or target.is_symlink():
        raise FileExistsError("Registration provenance must be new")
    # Candidate registration is immutable and does not promote. A concurrent active change
    # may leave an orphan object; no valid provenance is issued in that case.
    registry.load_active(contract["parent_active_sha256"])
    candidate = registry.register(parsed["spec"], active["candidate_sha256"])
    registry.load_active(contract["parent_active_sha256"])
    report = {
        "schema": "dsh.rsi-student-registration.v1",
        "proposal_manifest_sha256": expected_manifest_sha256,
        "parent_active_sha256": contract["parent_active_sha256"],
        "candidate_sha256": candidate,
        "parent_candidate_sha256": active["candidate_sha256"],
        "diagnostics_sha256": contract["diagnostics_sha256"],
        "model_sha256": contract["model_sha256"],
        "runtime_sha256": contract["runtime_sha256"],
        "proof": episode["proof"],
        "launch_manifest_sha256": worker.digest(run / "launch-manifest.json"),
        "supervisor_result_sha256": worker.digest(run / "supervisor-result.json"),
        **parsed,
        "promoted": False,
        "training": False,
    }
    worker.write_json(target, report)
    return report
