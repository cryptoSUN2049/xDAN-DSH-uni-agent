"""Synthetic artifact tests; these fixtures are never counted as live smoke."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import sys
from pathlib import Path
from uuid import UUID

import numpy as np
import pytest

from examples.dsh.evolution_v3_catalog import canonical_json_bytes
from examples.dsh.evolution_v3_live import load_live_scenarios, write_live_contract_bundle
from examples.dsh.evolution_v3_live_verifier import evaluate_live_trace
from examples.dsh.ops.audit_v3_live_smoke import audit_run, main
from examples.dsh.ops.run_v3_live_smoke import prepare_run
from tests.uni_agent.tasks.test_dsh_evolution_v3_live_verifier import _call, _provider_events, _result, _terminal

SCENARIO_PATH = Path("examples/dsh/evolution_v3_live_scenarios.jsonl")
ENVIRONMENT_DIGEST = "sha256:" + "e" * 64


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value))


def _successful_trace(scenario: dict) -> tuple[list[dict], str]:
    family = scenario["family_id"]
    live, spec = scenario["live"], scenario["verifier_spec"]
    events = []

    def call(name, arguments, result="ok", *, error=False):
        call_id = f"call-{len(events)}"
        events.extend([_call(call_id, name, arguments), _result(call_id, result, error=error)])

    if family in {"runtime-grounding", "transfer-composition"}:
        events.extend(_provider_events())
    if family == "multi-step-configuration":
        configuration = live["expected_configuration"]
        for query in configuration["queries"]:
            call("cordis_inspect_query", query, {**query, "data": {}})
        call("cordis_define", configuration["definition"], "Defined test/pkg")
        call("cordis_run", {"pluginId": "test", "packageId": "pkg", "mode": "run"})
        call(live["candidate_tool_name"], {}, spec["expected_behavior"])
    if family in {"lifecycle-composition", "diagnostic-recovery", "transfer-composition", "timeout-cleanup"}:
        call("cordis_define", {"plugin": {"kind": "new", "idPrefix": "test"}}, "Defined test/pkg")
        call(
            "cordis_run",
            {"pluginId": "test", "packageId": "pkg", "mode": "run"},
            "timed out" if family == "timeout-cleanup" else "running",
            error=family == "timeout-cleanup",
        )
        if family in {"diagnostic-recovery", "transfer-composition"}:
            call(
                "cordis_inspect_self",
                {"pluginId": "test"},
                {"runtime": {"host": {"waitingFor": [live["missing_provider"]]}}},
            )
        if family != "timeout-cleanup":
            call("cordis_define", {"plugin": {"kind": "existing", "pluginId": "test"}}, "Defined test/pkg2")
            call("cordis_run", {"pluginId": "test", "packageId": "pkg2", "mode": "update"})
            call(live["candidate_tool_name"], {}, spec.get("expected_result", spec.get("expected_retry")))
        call("cordis_stop", {"pluginId": "test"})
        call("cordis_undefine", {"pluginId": "test"})
        call("cordis_inspect_self", {}, {"mode": "plugins", "plugins": []})
    response = json.dumps({"decision": "refuse", "safe_alternative": "use an approved copy", "reward": 999})
    return _terminal(events), response


def _artifacts(tmp_path: Path, *, policy_failure: bool = False) -> tuple[Path, list[dict]]:
    repo = Path.cwd()
    scenarios = load_live_scenarios(SCENARIO_PATH, repository_root=repo)
    bundle = tmp_path / "bundle"
    write_live_contract_bundle(
        scenarios,
        scenario_path=SCENARIO_PATH,
        repository_root=repo,
        output_dir=bundle,
        environment_digest=ENVIRONMENT_DIGEST,
        profile="sdk-minimal",
        patches=["examples/dsh/evolution.patch.yml"],
    )
    root = tmp_path / "run"
    manifest = prepare_run(bundle, root, repository_root=repo)
    manifest.update(status="completed", started_at="2026-09-07T00:00:00Z", finished_at="2026-09-07T00:00:12Z")
    _write(root / "run-manifest.json", manifest)
    paths = {key: Path(value) for key, value in manifest["paths"].items()}
    samples, keys, scores, entries = [], [], [], []
    for index, (sample, scenario) in enumerate(zip(manifest["samples"], scenarios, strict=True)):
        uid = str(UUID(int=index + 1))
        gateway = f"session-sample-{index}-rollout-0-{index + 1:032x}"
        workspace = root / "artifacts/workspaces" / gateway
        for item in json.loads(Path(manifest["episode_files_path"]).read_text()):
            target = workspace / item["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(repo / item["path"], target)
        dsh_session = "dsh-" + gateway
        metadata = sample["metadata"]
        events, response = _successful_trace(scenario)
        if policy_failure and index == 0:
            events = _terminal([])
        trace_bytes = b"".join(canonical_json_bytes(event) for event in events)
        trace_digest = _digest(trace_bytes)
        evaluation = evaluate_live_trace(
            scenario,
            events=events,
            response=response,
            environment_digest=ENVIRONMENT_DIGEST,
            fixture_bytes=(repo / metadata["fixture_path"]).read_bytes(),
            trace_sha256=trace_digest,
        )
        assert evaluation["eligible"] is True
        assert evaluation["passed"] is (not policy_failure or index != 0)
        reward = evaluation["reward"]
        trace_path = paths["trace_root"] / hashlib.sha256(gateway.encode()).hexdigest()[:24] / "session.jsonl"
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        trace_path.write_bytes(trace_bytes)
        envelope = {
            "schema": "dsh.uni-agent.task-result.v1",
            "metadata": metadata,
            "finished": True,
            "response": response,
            "dsh": {"dsh_session_id": dsh_session, "gateway_session_id": gateway, "trace_sha256": trace_digest},
        }
        artifact_digest = _digest(canonical_json_bytes(envelope))
        result_dir = paths["result_root"] / hashlib.sha256(f"{dsh_session}\0{trace_digest}".encode()).hexdigest()[:24]
        envelope_path, receipt_path = result_dir / "agent-result.json", result_dir / "verifier-receipt.json"
        _write(envelope_path, envelope)
        receipt = {
            "schema": "dsh.verifier-receipt.v1",
            "task_id": metadata["task_id"],
            "task_version": metadata["task_version"],
            "dsh_session_id": dsh_session,
            "trace_sha256": trace_digest,
            "artifact_sha256": artifact_digest,
            "environment_digest": ENVIRONMENT_DIGEST,
            "verifier": {
                "id": metadata["verifier_id"],
                "version": metadata["verifier_version"],
                "code_digest": metadata["verifier_code_digest"],
            },
            "issued_at": "2026-09-07T00:00:05Z",
            "fresh": True,
            "eligible": True,
            "issuer": {"kind": "trusted-verifier", "id": "uni-agent-dsh"},
            "reward": reward,
            "accuracy": float(evaluation["passed"]),
            "finished": True,
            "evidence": ["trace"],
        }
        receipt["receipt_id"] = _digest(canonical_json_bytes(receipt))
        _write(receipt_path, receipt)
        lineage = {
            key: metadata[key]
            for key in (
                "task_id",
                "task_version",
                "split",
                "environment_digest",
                "verifier_id",
                "verifier_version",
                "verifier_code_digest",
            )
        }
        lineage.update(
            schema=receipt["schema"],
            receipt_sha256=receipt["receipt_id"],
            freshness="fresh",
            eligible=True,
            rollout_id=gateway,
            dsh_session_id=dsh_session,
            trace_sha256=trace_digest,
            artifact_sha256=artifact_digest,
            event_count=len(events),
        )
        reward_info = {"reward": reward, "verifier_reward": reward, "finished": True, "dsh": lineage}
        dump_path = paths["agent_log_dir"] / gateway / "trajectory.json"
        dump_path.parent.mkdir(parents=True, exist_ok=True)
        npz = dump_path.parent / "trajectory.npz"
        np.savez_compressed(
            npz,
            traj0_prompt_ids=np.array([10, 11], dtype=np.int32),
            traj0_response_ids=np.array([20, 21, 22], dtype=np.int32),
            traj0_response_mask=np.array([1, 0, 1], dtype=np.int8),
            traj0_response_logprobs=np.array([-0.1, 0.0, -0.2], dtype=np.float32),
        )
        key = f"{uid}_0_0"
        dump = {
            "schema": "uni-agent.trajectory-dump.v2",
            "session_id": gateway,
            "gateway_session_id": gateway,
            "partition_id": "val",
            "global_steps": None,
            "group_uid": uid,
            "group_size": 1,
            "sample_index": index,
            "session_index": 0,
            "trajectory_npz_sha256": _digest(npz.read_bytes()),
            "num_trajectories": 1,
            "trajectories": [
                {
                    "trajectory_index": 0,
                    "transfer_queue_key": key,
                    "num_turns": 1,
                    "finished": True,
                    "reward_score": reward,
                    "reward_info": reward_info,
                    "reward_extra_info": {"verifier_reward": reward, "dsh": lineage},
                    "prompt_len": 2,
                    "response_len": 3,
                    "model_token_count": 2,
                    "has_logprobs": True,
                }
            ],
        }
        _write(dump_path, dump)
        samples.append({"uid": uid, "sample_index": index, "metadata": metadata})
        keys.append(key)
        scores.append(reward)
        entries.append({"dump": dump_path, "trace": trace_path, "receipt": receipt_path, "envelope": envelope_path})
    _write(
        paths["inference_evidence_path"],
        {
            "schema": "dsh.inference-evidence.v1",
            "status": "completed",
            "started_at": "2026-09-07T00:00:01Z",
            "finished_at": "2026-09-07T00:00:10Z",
            "partition_id": "val",
            "global_steps": None,
            "samples": samples,
            "readback": {
                "final_keys": keys,
                "traj_keys": keys,
                "scores": scores,
                "uid_status": {sample["uid"]: "finished" for sample in samples},
            },
        },
    )
    return root, entries


def test_complete_eight_family_artifacts_require_real_readback_but_never_qualify_training(tmp_path):
    root, _ = _artifacts(tmp_path)
    report = audit_run(root, repository_root=Path.cwd())
    assert report["process_evidence_complete"] is True
    assert report["inference_readback_verified"] is True
    assert report["live_contract_passed"] is True
    assert report["training_eligible"] is False
    assert len(report["families"]) == 8


def test_eligible_policy_failure_keeps_evidence_valid_without_passing_smoke(tmp_path):
    root, _ = _artifacts(tmp_path, policy_failure=True)
    report = audit_run(root, repository_root=Path.cwd())
    assert report["process_evidence_complete"] is True
    assert report["inference_readback_verified"] is True
    assert report["live_contract_passed"] is False
    assert report["families"][0]["passed"] is False


@pytest.mark.parametrize("change", ["missing_trace", "npz_tamper", "stale_receipt", "wrong_family", "missing_readback"])
def test_smoke_rejects_incomplete_or_replayed_evidence(tmp_path, change):
    root, entries = _artifacts(tmp_path)
    entry = entries[0]
    if change == "missing_trace":
        entry["trace"].unlink()
    elif change == "npz_tamper":
        entry["dump"].with_name("trajectory.npz").write_bytes(b"tampered")
    elif change == "stale_receipt":
        receipt = json.loads(entry["receipt"].read_text())
        receipt["issued_at"] = "2026-09-06T00:00:05Z"
        receipt.pop("receipt_id")
        receipt["receipt_id"] = _digest(canonical_json_bytes(receipt))
        _write(entry["receipt"], receipt)
        dump = json.loads(entry["dump"].read_text())
        for field in ("reward_info", "reward_extra_info"):
            dump["trajectories"][0][field]["dsh"]["receipt_sha256"] = receipt["receipt_id"]
        _write(entry["dump"], dump)
    else:
        path = root / "inference-evidence.json"
        value = json.loads(path.read_text())
        if change == "wrong_family":
            value["samples"][0]["metadata"]["family_id"] = "permission-abstention"
        else:
            value["readback"] = None
        _write(path, value)
    report = audit_run(root, repository_root=Path.cwd())
    assert report["live_contract_passed"] is False
    assert report["training_eligible"] is False
    assert report["errors"] or any(family["errors"] for family in report["families"])


@pytest.mark.parametrize(
    "change",
    [
        "duplicate_uid",
        "bad_uid",
        "wrong_window",
        "failed_run",
        "failed_inference",
        "wrong_partition",
        "missing_dump",
        "duplicate_dump",
        "unknown_dump",
        "wrong_gateway",
        "wrong_rollout",
        "unfinished_chain",
        "trace_symlink",
        "result_symlink",
        "duplicate_json",
        "invalid_json",
        "wrong_npz_length",
        "wrong_score",
        "boolean_score",
        "duplicate_final_key",
        "missing_chain_key",
        "uid_failure",
        "wrong_issuer",
        "wrong_accuracy",
        "wrong_metadata",
        "non_utc_receipt",
        "fixture_identity",
    ],
)
def test_auditor_rejects_corrupt_boundaries(tmp_path, change):
    root, entries = _artifacts(tmp_path)
    entry = entries[0]
    evidence_path = root / "inference-evidence.json"
    if change in {
        "duplicate_uid",
        "bad_uid",
        "wrong_window",
        "failed_inference",
        "wrong_partition",
        "wrong_score",
        "boolean_score",
        "duplicate_final_key",
        "missing_chain_key",
        "uid_failure",
    }:
        value = json.loads(evidence_path.read_text())
        if change == "duplicate_uid":
            value["samples"][1]["uid"] = value["samples"][0]["uid"]
        elif change == "bad_uid":
            value["samples"][0]["uid"] = "invented"
        elif change == "wrong_window":
            value["finished_at"] = "2026-09-07T00:01:00Z"
        elif change == "failed_inference":
            value["status"] = "failed"
        elif change == "wrong_partition":
            value["partition_id"] = "train"
        elif change in {"wrong_score", "boolean_score"}:
            value["readback"]["scores"][0] = True if change == "boolean_score" else 999
        elif change == "duplicate_final_key":
            value["readback"]["final_keys"][1] = value["readback"]["final_keys"][0]
        elif change == "missing_chain_key":
            value["readback"]["traj_keys"].pop()
        else:
            value["readback"]["uid_status"][value["samples"][0]["uid"]] = "failed"
        _write(evidence_path, value)
    elif change == "failed_run":
        path = root / "run-manifest.json"
        value = json.loads(path.read_text())
        value["status"] = "timeout"
        _write(path, value)
    elif change == "missing_dump":
        entry["dump"].unlink()
    elif change == "duplicate_dump":
        shutil.copytree(entry["dump"].parent, entry["dump"].parent.with_name("duplicate"))
    elif change in {"unknown_dump", "wrong_gateway", "wrong_rollout", "unfinished_chain", "wrong_npz_length"}:
        value = json.loads(entry["dump"].read_text())
        if change == "unknown_dump":
            value["group_uid"] = str(UUID(int=99))
        elif change == "wrong_gateway":
            value["gateway_session_id"] = "0"
        elif change == "wrong_rollout":
            value["session_index"] = 1
        elif change == "unfinished_chain":
            value["trajectories"][0]["finished"] = False
        else:
            value["trajectories"][0]["response_len"] = 99
        _write(entry["dump"], value)
    elif change in {"trace_symlink", "result_symlink"}:
        path = entry["trace" if change == "trace_symlink" else "receipt"]
        outside = tmp_path / "outside.json"
        path.rename(outside)
        path.symlink_to(outside)
    elif change == "duplicate_json":
        evidence_path.write_text('{"status":"completed","status":"completed"}')
    elif change == "invalid_json":
        evidence_path.write_bytes(b"\xff")
    elif change in {"wrong_issuer", "wrong_accuracy", "non_utc_receipt"}:
        value = json.loads(entry["receipt"].read_text())
        if change == "wrong_issuer":
            value["issuer"]["id"] = "candidate"
        elif change == "wrong_accuracy":
            value["accuracy"] = 0
        else:
            value["issued_at"] = "2026-09-07T08:00:05+08:00"
        value.pop("receipt_id")
        value["receipt_id"] = _digest(canonical_json_bytes(value))
        _write(entry["receipt"], value)
        dump = json.loads(entry["dump"].read_text())
        for field in ("reward_info", "reward_extra_info"):
            dump["trajectories"][0][field]["dsh"]["receipt_sha256"] = value["receipt_id"]
        _write(entry["dump"], dump)
    elif change == "wrong_metadata":
        value = json.loads(entry["envelope"].read_text())
        value["metadata"]["family_id"] = "permission-abstention"
        _write(entry["envelope"], value)
    else:
        path = root / "run-manifest.json"
        value = json.loads(path.read_text())
        value["samples"][0]["metadata"]["fixture_digest"] = "sha256:" + "a" * 64
        _write(path, value)
    report = audit_run(root, repository_root=Path.cwd())
    assert not report["live_contract_passed"], change
    assert not report["training_eligible"]
    assert report["errors"] or any(family["errors"] for family in report["families"])


@pytest.mark.parametrize("case,code", [("pass", 0), ("policy_failure", 1), ("incomplete", 2)])
def test_audit_cli_distinguishes_policy_failure_from_missing_evidence(tmp_path, monkeypatch, capsys, case, code):
    root, entries = _artifacts(tmp_path, policy_failure=case == "policy_failure")
    if case == "incomplete":
        entries[0]["trace"].unlink()
    monkeypatch.setattr(sys, "argv", ["audit_v3_live_smoke.py", str(root)])
    with pytest.raises(SystemExit) as stopped:
        main()
    assert stopped.value.code == code
    assert json.loads(capsys.readouterr().out)["training_eligible"] is False


def test_multiple_token_chains_use_final_chain_readback_and_audit_every_chain(tmp_path):
    root, entries = _artifacts(tmp_path)
    entry = entries[0]
    dump = json.loads(entry["dump"].read_text())
    chain = copy.deepcopy(dump["trajectories"][0])
    chain.update(trajectory_index=1, transfer_queue_key=chain["transfer_queue_key"][:-1] + "1")
    dump["trajectories"].append(chain)
    dump["num_trajectories"] = 2
    npz_path = entry["dump"].with_name("trajectory.npz")
    with np.load(npz_path, allow_pickle=False) as archive:
        arrays = {key: archive[key] for key in archive.files}
    arrays.update({key.replace("traj0_", "traj1_"): array.copy() for key, array in list(arrays.items())})
    np.savez_compressed(npz_path, **arrays)
    dump["trajectory_npz_sha256"] = _digest(npz_path.read_bytes())
    _write(entry["dump"], dump)
    path = root / "inference-evidence.json"
    evidence = json.loads(path.read_text())
    evidence["readback"]["final_keys"][0] = chain["transfer_queue_key"]
    evidence["readback"]["traj_keys"].append(chain["transfer_queue_key"])
    _write(path, evidence)
    assert audit_run(root, repository_root=Path.cwd())["live_contract_passed"] is True
    arrays["traj0_response_mask"][:] = 0
    np.savez_compressed(npz_path, **arrays)
    dump["trajectory_npz_sha256"] = _digest(npz_path.read_bytes())
    _write(entry["dump"], dump)
    assert audit_run(root, repository_root=Path.cwd())["live_contract_passed"] is False


def test_audit_rechecks_trusted_files_in_earlier_episode_workspaces(tmp_path):
    root, entries = _artifacts(tmp_path)
    gateway = json.loads(entries[0]["dump"].read_text())["gateway_session_id"]
    files = json.loads((root / "episode-files.json").read_text())
    target = root / "artifacts/workspaces" / gateway / files[0]["path"]
    target.write_bytes(b"changed by a later episode")
    report = audit_run(root, repository_root=Path.cwd())
    assert report["live_contract_passed"] is False
    assert report["families"][0]["errors"]


@pytest.mark.parametrize("change", ["non_integer_ids", "negative_ids", "nested_ids", "bad_zip"])
def test_resealed_npz_requires_valid_token_ids_and_returns_invalid_report(tmp_path, change):
    root, entries = _artifacts(tmp_path)
    entry = entries[0]
    npz_path = entry["dump"].with_name("trajectory.npz")
    with np.load(npz_path, allow_pickle=False) as archive:
        arrays = {key: archive[key] for key in archive.files}
    if change == "bad_zip":
        npz_path.write_bytes(b"PK\x03\x04truncated")
    else:
        arrays["traj0_response_ids"] = {
            "non_integer_ids": np.array([np.nan, np.inf, -9.5]),
            "negative_ids": np.array([20, -1, 22], dtype=np.int64),
            "nested_ids": np.array([[20], [21], [22]], dtype=np.int64),
        }[change]
        np.savez_compressed(npz_path, **arrays)
    dump = json.loads(entry["dump"].read_text())
    dump["trajectory_npz_sha256"] = _digest(npz_path.read_bytes())
    _write(entry["dump"], dump)
    report = audit_run(root, repository_root=Path.cwd())
    assert report["live_contract_passed"] is False
    assert report["families"][0]["errors"]


def test_explicit_repository_root_binds_registry_independently_of_cwd(tmp_path, monkeypatch):
    repository = Path.cwd()
    root, _ = _artifacts(tmp_path)
    # A same-named untrusted registry in the caller cwd must never be opened.
    shadow = tmp_path / SCENARIO_PATH
    shadow.parent.mkdir(parents=True)
    shadow.write_text("untrusted registry")
    monkeypatch.chdir(tmp_path)
    report = audit_run(root, repository_root=repository)
    assert report["live_contract_passed"] is True
