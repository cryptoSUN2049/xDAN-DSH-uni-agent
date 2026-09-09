"""Registration must consume raw evidence, never caller-supplied candidate JSON."""

import pytest

from examples.dsh.rsi_closed import proposal_registration as registration


def test_missing_actual_episode_never_registers(tmp_path):
    with pytest.raises((FileNotFoundError, ValueError)):
        registration.audit_episode(tmp_path, {"task_id": "p"}, max_tokens=512)


def test_registration_refuses_unbound_manifest(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text("{}")
    with pytest.raises(ValueError, match="hash"):
        registration.register_verified_proposal(path, "sha256:" + "0" * 64, tmp_path / "registration.json")


def actual_format_episode(tmp_path):
    """Synthetic values in real v2 NPZ/artifact format; exercises the real audit code."""
    import json
    import shutil
    from unittest.mock import patch

    from tests.uni_agent.tasks.test_dsh_ops_audit import _write_run
    from tests.uni_agent.tasks.test_dsh_trajectory_audit import _valid_trajectory

    # Build the existing real-format fixture as validation, matching strict inference's val partition.
    with patch(
        "tests.uni_agent.tasks.test_dsh_ops_audit._valid_trajectory",
        lambda root: _valid_trajectory(root, split="validation"),
    ):
        run, dump_dir = _write_run(tmp_path)
    dump_path = dump_dir / "trajectory.json"
    dump = json.loads(dump_path.read_text())
    dump["partition_id"] = "val"
    dump_path.write_text(json.dumps(dump))
    (run / "artifacts").mkdir()
    shutil.move(str(run / "traces"), run / "artifacts/traces")
    shutil.move(str(run / "results"), run / "artifacts/results")
    artifact = next((run / "artifacts/results").glob("*/agent-result.json"))
    metadata = json.loads(artifact.read_text())["metadata"]
    evidence = {
        "status": "completed",
        "samples": [{"uid": "group-uid", "metadata": metadata}],
        "readback": {
            "final_keys": ["group-uid_0_0"],
            "traj_keys": ["group-uid_0_0"],
            "scores": [0.75],
            "uid_status": {"group-uid": "finished"},
        },
    }
    (run / "inference-evidence.json").write_text(json.dumps(evidence))
    return run, dump_dir, metadata


def test_real_npz_audit_counts_only_model_mask_tokens(tmp_path):
    run, _, metadata = actual_format_episode(tmp_path)
    report = registration.audit_episode(run, metadata, max_tokens=2)
    assert report["proof"]["model_tokens"] == 2
    assert report["proof"]["transfer_queue_key"] == "group-uid_0_0"


@pytest.mark.parametrize(
    "fault", ["npz", "mask-budget", "receipt", "trace", "readback", "dump-missing", "duplicate", "metadata"]
)
def test_real_raw_evidence_corruption_rejected(tmp_path, fault):
    import json

    run, dump, metadata = actual_format_episode(tmp_path)
    budget = 2
    if fault == "npz":
        (dump / "trajectory.npz").write_bytes(b"wrong")
    elif fault == "mask-budget":
        budget = 1
    elif fault == "receipt":
        next((run / "artifacts/results").glob("*/verifier-receipt.json")).write_text("{}")
    elif fault == "trace":
        next((run / "artifacts/traces").glob("*/session.jsonl")).write_text("{}")
    elif fault == "dump-missing":
        (dump / "trajectory.json").unlink()
    elif fault == "metadata":
        metadata = {**metadata, "phase": "wrong-stage"}
    else:
        path = run / "inference-evidence.json"
        data = json.loads(path.read_text())
        if fault == "readback":
            data["readback"]["scores"] = [1]
        else:
            data["samples"] *= 2
        path.write_text(json.dumps(data))
    with pytest.raises((ValueError, RuntimeError)):
        registration.audit_episode(run, metadata, max_tokens=budget)


@pytest.fixture
def proposal_run(tmp_path, monkeypatch, request):
    """Control-plane unit fixture; audit_parent/SDK/model runtime are explicit test substitutes."""
    import json

    from examples.dsh.rsi_closed import prepare_worker_eval as worker
    from examples.dsh.rsi_closed import proposal
    from uni_agent.tasks.dsh.rsi_candidates import Registry

    monkeypatch.setattr(registration, "require_clean_sources", lambda: None)
    args = request.getfixturevalue("parent_inputs")
    baseline = worker.prepare(**args, mode="parent-baseline")
    parent_path = args["output_dir"] / "preparation-manifest.json"
    diagnostics = {"schema": "dsh.rsi-parent-diagnostics.v1", "pair_id": baseline["pair_id"], "cases": []}
    monkeypatch.setattr(registration, "audit_parent", lambda *a: (baseline, diagnostics))
    output, run = tmp_path / "proposal", tmp_path / "proposal-run"
    manifest = registration.prepare_proposal(parent_path, worker.digest(parent_path), output, run)
    manifest_path = output / "preparation-manifest.json"
    run.mkdir()
    worker.write_json(
        run / "launch-manifest.json",
        {
            "schema": "dsh.rsi-proposal-launch.v1",
            "prepared_manifest_sha256": worker.digest(manifest_path),
            "command": manifest["command"],
            "environment": manifest["environment"],
            "wall_seconds": manifest["wall_seconds"],
        },
    )
    worker.write_json(run / "supervisor-result.json", {"exit_code": 0})
    (run / "inference-evidence.json").write_text(json.dumps({"samples": [{}]}))
    registry = Registry(baseline["registry_root"], baseline["pins_sha256"])
    spec = {**manifest["contract"]["parent_spec"], "allowed_tools": ["cordis_inspect_list", "str_replace_editor"]}
    raw = json.dumps(spec)
    envelope = {
        "prompt": manifest["contract"]["messages"],
        "response": raw,
        "finished": True,
        "dsh": {
            "profile": "sdk-minimal",
            "patches_sha256": proposal.parent._sha256_bytes(
                json.dumps([str(output / "overlay.json")], ensure_ascii=False, separators=(",", ":")).encode()
            ),
        },
    }
    events = [
        {"type": "assistant/message", "data": {"response": raw}},
        {"type": "turn/end", "data": {"reason": {"kind": "completed"}}},
    ]
    episode = {"envelope": envelope, "events": events, "reward": 1, "proof": {"synthetic_unit_fixture": True}}
    monkeypatch.setattr(registration, "audit_episode", lambda *a, **k: episode)
    monkeypatch.setattr(proposal, "sdk_final_response", lambda ev: ev[0]["data"]["response"])
    return manifest_path, worker.digest(manifest_path), tmp_path / "registration.json", registry, episode, baseline


# Reuse a local CPU-only setup fixture; it never executes the runtime or loads model weights.
from tests.uni_agent.examples.test_prepare_rsi_worker_eval import parent_inputs  # noqa: E402,F401


def test_verified_response_registers_exact_spec_without_promoting(proposal_run):
    path, sha, target, registry, episode, baseline = proposal_run
    before = registry.load_active(baseline["parent_active_sha256"])
    result = registration.register_verified_proposal(path, sha, target)
    assert result["spec"]["allowed_tools"] == ["cordis_inspect_list", "str_replace_editor"]
    assert registry.load_active(baseline["parent_active_sha256"]) == before
    assert result["promoted"] is False
    assert target.stat().st_mode & 0o777 == 0o600
    assert (
        registry.load_registered(result["candidate_sha256"], baseline["parent_active_sha256"])["content_sha256"]
        == result["content_sha256"]
    )


@pytest.mark.parametrize(
    "fault", ["no-change", "modified-response", "prompt", "patch", "receipt-score", "existing-sidecar", "active"]
)
def test_registration_rejects_bad_proposal_without_registering(proposal_run, fault, monkeypatch):
    import json

    path, sha, target, registry, episode, baseline = proposal_run
    if fault == "no-change":
        raw = json.dumps(registry.load_active(baseline["parent_active_sha256"])["spec"])
        episode["envelope"]["response"] = episode["events"][0]["data"]["response"] = raw
    elif fault == "modified-response":
        episode["envelope"]["response"] += "changed"
    elif fault == "prompt":
        episode["envelope"]["prompt"] = []
    elif fault == "patch":
        episode["envelope"]["dsh"]["patches_sha256"] = "sha256:" + "0" * 64
    elif fault == "receipt-score":
        episode["reward"] = 0
    elif fault == "existing-sidecar":
        target.write_text("occupied")
    else:
        from pathlib import Path

        (Path(baseline["registry_root"]) / "active.json").write_text("{}")

    def forbidden(*a, **k):
        raise AssertionError("Rejected proposal must not register")

    monkeypatch.setattr(type(registry), "register", forbidden)
    with pytest.raises((ValueError, RuntimeError, FileExistsError)):
        registration.register_verified_proposal(path, sha, target)


def test_registered_proposal_does_not_issue_provenance_after_active_race(proposal_run, monkeypatch):
    from pathlib import Path

    path, sha, target, registry, _, baseline = proposal_run
    original = type(registry).register

    def racing(self, spec, parent):
        candidate = original(self, spec, parent)
        (Path(baseline["registry_root"]) / "active.json").write_text("{}")
        return candidate

    monkeypatch.setattr(type(registry), "register", racing)
    with pytest.raises((ValueError, RuntimeError)):
        registration.register_verified_proposal(path, sha, target)
    assert not target.exists()


@pytest.mark.parametrize("fault", ["source-inventory", "task-phase", "model-pin", "extra-file"])
def test_rehashed_manifest_cannot_remove_fixed_contract_gates(proposal_run, fault):
    import json

    from examples.dsh.rsi_closed import prepare_worker_eval as worker

    path, _, target, _, _, _ = proposal_run
    manifest = json.loads(path.read_text())
    if fault == "source-inventory":
        manifest["sources"] = {}
    elif fault == "task-phase":
        manifest["metadata"]["phase"] = "worker"
    elif fault == "model-pin":
        contract = manifest["contract"]
        contract["model_sha256"] = "sha256:" + "0" * 64
        (path.parent / "contract.json").write_text(json.dumps(contract))
        manifest["files"]["contract.json"] = worker.digest(path.parent / "contract.json")
        manifest["metadata"]["fixture_sha256"] = manifest["files"]["contract.json"]
    else:
        (path.parent / "extra.txt").write_text("extra")
    path.write_text(json.dumps(manifest))
    with pytest.raises((ValueError, RuntimeError)):
        registration.register_verified_proposal(path, worker.digest(path), target)
    assert not target.exists()


def test_proposer_task_uses_existing_strict_cli_and_one_sample(proposal_run):
    import json

    import pyarrow.parquet as pq

    from examples.inference import parallel_infer_verl as cli
    from uni_agent.tasks.config import TaskConfigResolver

    path, _, _, _, _, _ = proposal_run
    manifest = json.loads(path.read_text())
    args = cli._parse_args(manifest["command"][2:])
    (path.parent.parent / "proposal-run/inference-evidence.json").unlink()
    cli._validate_evidence_args(args)
    assert args.n == 1 and args.limit == 1 and args.dsh_strict_audit
    rows = pq.read_table(path.parent / "eval.parquet").to_pylist()
    assert len(rows) == 1
    # The actual resolver/registration API validates the real DSH task metadata.
    registered = cli._registered_samples(
        rows, ["unit-proposer"], TaskConfigResolver.from_file(str(path.parent / "task.yaml")), strict=True
    )
    assert registered[0]["metadata"]["verifier_id"] == "dsh-rsi-proposal"


@pytest.mark.parametrize("fault", ["missing-launch", "wrong-command", "supervisor-failure"])
def test_registration_requires_actual_bounded_launch_binding(proposal_run, fault):
    import json
    from pathlib import Path

    path, sha, target, _, _, _ = proposal_run
    manifest = json.loads(path.read_text())
    run = Path(manifest["run_root"])
    if fault == "missing-launch":
        (run / "launch-manifest.json").unlink()
    elif fault == "wrong-command":
        launch = json.loads((run / "launch-manifest.json").read_text())
        launch["command"] = ["another-model"]
        (run / "launch-manifest.json").write_text(json.dumps(launch))
    else:
        (run / "supervisor-result.json").write_text('{"exit_code":1}')
    with pytest.raises((ValueError, FileNotFoundError)):
        registration.register_verified_proposal(path, sha, target)
    assert not target.exists()


def test_registration_rejects_changed_verl_manifest_before_registry_write(proposal_run):
    import json

    path, _, target, registry, _, baseline = proposal_run
    manifest = json.loads(path.read_text())
    manifest["verl_effective_source"]["manifest_sha256"] = "sha256:" + "0" * 64
    path.write_text(json.dumps(manifest))
    before = registry.load_active(baseline["parent_active_sha256"])
    with pytest.raises(ValueError, match="VERL effective source"):
        registration.register_verified_proposal(path, registration.worker.digest(path), target)
    assert not target.exists()
    assert registry.load_active(baseline["parent_active_sha256"]) == before
