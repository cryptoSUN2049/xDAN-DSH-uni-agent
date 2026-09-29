import importlib.util
import json
import os
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "docs/verl-uni-agent-harbor-opd-rl/mimo-evidence-transport.py"
spec = importlib.util.spec_from_file_location("mimo_evidence_transport", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
pytestmark = [pytest.mark.cpu, pytest.mark.level0]
RUN = "mimo9b-001661-r8"
JOB = "job-" + "a" * 32
HASH = "sha256:" + "b" * 64


def raw(value, newline=True):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + ("\n" if newline else "")).encode()


def sha(data):
    import hashlib

    return "sha256:" + hashlib.sha256(data).hexdigest()


def put(root, name, data):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    parent = path.parent
    while parent != root:
        parent.chmod(0o700)
        parent = parent.parent
    path.write_bytes(data)
    path.chmod(0o600)
    return path


@pytest.fixture
def case(tmp_path):
    launch, agent, target = [tmp_path / name for name in ("launch", "agent", "archive")]
    launch.mkdir(mode=0o700)
    agent.mkdir(mode=0o700)
    context = dict(
        gateway_session_id="session-1",
        partition_id="train",
        global_steps=0,
        group_uid="g",
        group_size=4,
        sample_index=0,
        session_index=0,
    )
    policy = {
        "termination_policy": "budget-terminal-v1",
        "budget_limits": {"max_generated_tokens": 3, "trajectory_capacity": 100},
    }
    put(
        launch,
        "launch.json",
        raw({"schema": "dsh.harbor-m2-launch.v1", "postprocessor": {"run_id": RUN, "policy_template": policy}}),
    )
    put(launch, "task.yaml", b"worker_token: DO_NOT_COPY\n")
    request = dict(
        schema="dsh.harbor-job-request.v2",
        run_id=RUN,
        job_id=JOB,
        gateway_session_id="session-1",
        nonce="ab" * 16,
        termination_policy="budget-terminal-v1",
        budget_limits=policy["budget_limits"],
        budgets={"max_artifact_bytes": 65536},
    )
    request["request_sha256"] = sha(raw(request, False))
    entries = []
    for index, kind in enumerate(
        ("binding", "receipt", "dsh_trace", "dsh_result", "harbor_result", "verifier_log", "reward")
    ):
        content = b'{"sample":"raw bytes"}\n'
        entries.append(dict(id=f"object-{index}", kind=kind, size_bytes=len(content), sha256=sha(content)))
        put(launch, f"artifacts/{JOB}/object-{index}", content)
    manifest = dict(
        schema="dsh.harbor-job-manifest.v1",
        status="succeeded",
        worker_id="worker",
        trial_id="trial",
        artifacts=entries,
        **{k: request[k] for k in ("job_id", "gateway_session_id", "nonce", "request_sha256")},
    )
    put(launch, f"artifacts/{JOB}/request.json", raw(request))
    put(launch, f"artifacts/{JOB}/manifest.json", raw(manifest))
    receipt = dict(
        schema="dsh.harbor-verifier-receipt.v2",
        run_id=RUN,
        finished=False,
        termination_policy="budget-terminal-v1",
        termination_kind="budget_exhausted",
        framework_context=context,
        manifest_canonical_sha256=sha(raw(manifest)),
        **{
            k: manifest[k]
            for k in ("job_id", "gateway_session_id", "nonce", "request_sha256", "worker_id", "trial_id", "artifacts")
        },
    )
    receipt["receipt_id"] = sha(raw(receipt))
    put(launch, f"artifacts/{JOB}/receipt.json", raw(receipt))
    admission = dict(
        schema="dsh.harbor-budget-admission.v1",
        run_id=RUN,
        framework_context=context,
        chain_id=0,
        receipt_sha256=receipt["receipt_id"],
        termination_policy="budget-terminal-v1",
        termination_kind="budget_exhausted",
        finished=False,
    )
    admission["admission_sha256"] = sha(raw(admission, False))
    metadata = dict(
        schema="uni-agent.trajectory-dump.v2",
        gateway_session_id="session-1",
        session_id="session-1",
        **{k: v for k, v in context.items() if k != "gateway_session_id"},
        trajectory_npz_sha256=sha(b"npz-test-bytes"),
        num_trajectories=1,
        trajectories=[{"chain_id": 0, "reward_info": {"harbor_dsh": {"job_id": JOB}}}],
    )
    dump = dict(
        schema="dsh.harbor-budget-dump.v1",
        framework_context=context,
        admission_sha256=admission["admission_sha256"],
        trajectory_npz_sha256=metadata["trajectory_npz_sha256"],
        metadata_sha256=sha(raw(metadata, False)),
    )
    return dict(
        launch=launch, agent=agent, target=target, receipt=receipt, admission=admission, dump=dump, metadata=metadata
    )


def add_chain(case, *, npz=True):
    for name in ("admission", "dump"):
        put(case["launch"], f"artifacts/{JOB}/{name}-chain-0.json", raw(case[name]))
    put(case["agent"], "step_0/session-1/trajectory.json", raw(case["metadata"]))
    if npz:
        put(case["agent"], "step_0/session-1/trajectory.npz", b"npz-test-bytes")


def collect(case, previous=None):
    return module.collect(case["launch"], case["agent"], RUN, previous)


def test_v2_candidate_is_preserved_without_fake_completion_or_credentials(case):
    snapshot = collect(case)
    report = module.archive(snapshot, case["target"])
    assert report["jobs"][JOB]["stage"] == "candidate"
    copied = case["target"] / "gpu-launch" / "artifacts" / JOB / "receipt.json"
    assert copied.read_bytes() == raw(case["receipt"])
    assert json.loads(copied.read_bytes())["finished"] is False
    assert not (case["target"] / "gpu-launch/task.yaml").exists()
    assert copied.stat().st_mode & 0o777 == 0o600
    assert copied.parent.stat().st_mode & 0o777 == 0o700


def test_receipt_does_not_seal_out_later_admission_and_dump_files(case):
    first = module.archive(collect(case), case["target"])
    add_chain(case)
    second = module.archive(collect(case, first["files"]), case["target"])
    assert second["jobs"][JOB]["stage"] == "dump_complete"
    assert (case["target"] / "gpu-agent/step_0/session-1/trajectory.npz").read_bytes() == b"npz-test-bytes"
    assert (case["target"] / f"gpu-launch/artifacts/{JOB}/admission-chain-0.json").exists()


def test_dump_binding_before_npz_is_pending_and_can_be_completed_later(case):
    add_chain(case, npz=False)
    result = module.archive(collect(case), case["target"])
    assert result["jobs"][JOB]["stage"] == "admitted"
    put(case["agent"], "step_0/session-1/trajectory.npz", b"npz-test-bytes")
    assert module.archive(collect(case, result["files"]), case["target"])["jobs"][JOB]["stage"] == "dump_complete"


@pytest.mark.parametrize("attack", ["artifact", "admission", "npz", "metadata"])
def test_digest_mismatch_is_not_archived_as_a_complete_chain(case, attack):
    add_chain(case)
    path = {
        "artifact": case["launch"] / f"artifacts/{JOB}/object-0",
        "admission": case["launch"] / f"artifacts/{JOB}/admission-chain-0.json",
        "npz": case["agent"] / "step_0/session-1/trajectory.npz",
        "metadata": case["agent"] / "step_0/session-1/trajectory.json",
    }[attack]
    path.write_bytes(path.read_bytes() + b"bad")
    snapshot = collect(case)
    assert snapshot["errors"] or snapshot["pending"]
    assert snapshot["jobs"].get(JOB, {}).get("stage") != "dump_complete"


@pytest.mark.parametrize("attack", ["symlink", "hardlink", "public-private-source"])
def test_unsafe_private_source_is_rejected(case, attack, tmp_path):
    path = case["launch"] / f"artifacts/{JOB}/receipt.json"
    if attack == "symlink":
        outside = put(tmp_path, "outside", path.read_bytes())
        path.unlink()
        path.symlink_to(outside)
    elif attack == "hardlink":
        os.link(path, tmp_path / "other")
    else:
        path.chmod(0o644)
    snapshot = collect(case)
    assert snapshot["errors"]
    assert f"gpu-launch/artifacts/{JOB}/receipt.json" not in snapshot["files"]


def test_existing_archive_conflict_is_never_overwritten(case):
    snapshot = collect(case)
    module.archive(snapshot, case["target"])
    path = case["target"] / "gpu-launch/launch.json"
    path.write_bytes(b"keep-this")
    with pytest.raises(ValueError, match="conflict"):
        module.archive(snapshot, case["target"])
    assert path.read_bytes() == b"keep-this"


def test_missing_roots_are_pending_without_side_effects(tmp_path):
    result = module.collect(tmp_path / "missing", tmp_path / "agent", RUN)
    assert result["pending"] and not result["files"]
    assert not (tmp_path / "missing").exists()


def test_receiver_rejects_path_traversal_before_writes(case):
    snapshot = collect(case)
    snapshot["files"]["../escape"] = {"raw": b"secret", "sha256": sha(b"secret"), "size_bytes": 6}
    with pytest.raises(ValueError):
        module.archive(snapshot, case["target"])
    assert not (case["target"].parent / "escape").exists()


def test_once_cli_only_runs_ssh_read_and_persists_private_status(case, monkeypatch, capsys):
    import subprocess
    import time
    from types import SimpleNamespace

    def remote(command, **kwargs):
        assert command[0] == "ssh"
        assert "--remote-read" in command[-1]
        assert kwargs["stderr"] == subprocess.DEVNULL
        previous = json.loads(kwargs["input"])
        snapshot = module.wire(collect(case, previous), True)
        return SimpleNamespace(stdout=raw(snapshot), returncode=0)

    monkeypatch.setattr(subprocess, "run", remote)
    args = [
        "--run-id",
        RUN,
        "--launch-root",
        str(case["launch"]),
        "--agent-log-root",
        str(case["agent"]),
        "--destination",
        str(case["target"]),
        "--deadline",
        str(time.time() + 60),
        "--gpu-host",
        "127.0.0.1",
        "--ssh-key",
        "/private/key",
        "--known-hosts",
        "/private/known-hosts",
        "--once",
    ]
    assert module.main(args) == 0
    assert module.main(args) == 0
    status = json.loads((case["target"] / "status.json").read_bytes())
    assert status["state"] == "once_finished"
    assert status["jobs"][JOB]["stage"] == "candidate"
    assert "DO_NOT_COPY" not in capsys.readouterr().out
    assert (case["target"] / "status.json").stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("deadline", ["nan", "inf", "0"])
def test_nonfinite_or_expired_deadline_rejected_before_remote_work(case, deadline):
    with pytest.raises(ValueError, match="invalid_deadline_or_run"):
        module.main(
            [
                "--run-id",
                RUN,
                "--launch-root",
                str(case["launch"]),
                "--agent-log-root",
                str(case["agent"]),
                "--deadline",
                deadline,
            ]
        )


def test_source_change_after_success_is_reported_without_overwriting_archive(case):
    first = module.archive(collect(case), case["target"])
    path = case["launch"] / "launch.json"
    path.write_bytes(raw({"changed": True}))
    snapshot = collect(case, first["files"])
    assert snapshot["errors"]
    assert "gpu-launch/launch.json" not in snapshot["files"]


def test_natural_completion_receipt_remains_true(case):
    receipt = case["receipt"]
    receipt.update(finished=True, termination_kind="completed")
    receipt.pop("receipt_id")
    receipt["receipt_id"] = sha(raw(receipt))
    put(case["launch"], f"artifacts/{JOB}/receipt.json", raw(receipt))
    result = module.archive(collect(case), case["target"])
    assert not result["errors"]
    saved = json.loads((case["target"] / f"gpu-launch/artifacts/{JOB}/receipt.json").read_bytes())
    assert saved["finished"] is True


def test_watch_stops_at_deadline_without_training_commands(case, monkeypatch):
    import subprocess
    from types import SimpleNamespace

    now = [1000.0]
    monkeypatch.setattr(module.time, "time", lambda: now[0])

    def remote(command, **kwargs):
        assert command[0] == "ssh" and "--remote-read" in command[-1]
        now[0] = 2000.0
        return SimpleNamespace(stdout=raw(module.wire(collect(case), True)))

    monkeypatch.setattr(subprocess, "run", remote)
    assert (
        module.main(
            [
                "--run-id",
                RUN,
                "--launch-root",
                str(case["launch"]),
                "--agent-log-root",
                str(case["agent"]),
                "--destination",
                str(case["target"]),
                "--deadline",
                "2000",
                "--gpu-host",
                "127.0.0.1",
                "--ssh-key",
                "/private/key",
                "--known-hosts",
                "/private/known-hosts",
                "--watch",
            ]
        )
        == 0
    )
    status = json.loads((case["target"] / "status.json").read_bytes())
    assert status["state"] == "deadline_reached" and status["cycles"] == 1


def test_transport_failure_records_only_safe_error_type(case, monkeypatch, capsys):
    import subprocess
    import time

    def remote(command, **kwargs):
        raise subprocess.CalledProcessError(1, command, stderr=b"DO_NOT_COPY_CREDENTIAL")

    monkeypatch.setattr(subprocess, "run", remote)
    assert (
        module.main(
            [
                "--run-id",
                RUN,
                "--launch-root",
                str(case["launch"]),
                "--agent-log-root",
                str(case["agent"]),
                "--destination",
                str(case["target"]),
                "--deadline",
                str(time.time() + 60),
                "--gpu-host",
                "127.0.0.1",
                "--ssh-key",
                "/private/key",
                "--known-hosts",
                "/private/known-hosts",
                "--once",
            ]
        )
        == 1
    )
    saved = (case["target"] / "status.json").read_bytes()
    assert b"DO_NOT_COPY_CREDENTIAL" not in saved
    assert "DO_NOT_COPY_CREDENTIAL" not in capsys.readouterr().out
    assert json.loads(saved)["errors"][0]["error_type"] == "CalledProcessError"


def test_remote_reader_cli_round_trip_preserves_bytes(case):
    import subprocess
    import sys
    import time

    response = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--run-id",
            RUN,
            "--launch-root",
            str(case["launch"]),
            "--agent-log-root",
            str(case["agent"]),
            "--deadline",
            str(time.time() + 60),
            "--remote-read",
        ],
        input=b"{}",
        capture_output=True,
        timeout=15,
        check=True,
    )
    report = module.archive(module.wire(json.loads(response.stdout), False), case["target"])
    assert not report["errors"] and report["jobs"][JOB]["stage"] == "candidate"


@pytest.mark.parametrize("bad", [b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}'])
def test_control_json_rejects_duplicate_and_nonfinite_values(bad):
    with pytest.raises(ValueError):
        module.parse(bad)


def test_missing_published_artifact_is_pending_until_it_arrives(case):
    path = case["launch"] / f"artifacts/{JOB}/object-3"
    original = path.read_bytes()
    path.unlink()
    pending = collect(case)
    assert JOB in pending["pending"] and JOB not in pending["jobs"]
    put(case["launch"], f"artifacts/{JOB}/object-3", original)
    assert collect(case)["jobs"][JOB]["stage"] == "candidate"


def test_receiver_rejects_corrupt_wire_bytes(case):
    snapshot = collect(case)
    snapshot["files"]["gpu-launch/launch.json"]["raw"] = b"corrupt"
    with pytest.raises(ValueError, match="transport_hash"):
        module.archive(snapshot, case["target"])


def test_receiver_rejects_public_destination(case):
    case["target"].mkdir(mode=0o755)
    case["target"].chmod(0o755)
    with pytest.raises(ValueError, match="unsafe_directory"):
        module.archive(collect(case), case["target"])


def test_private_control_file_size_cap_is_enforced(case, monkeypatch):
    monkeypatch.setattr(module, "CONTROL_LIMIT", 16)
    snapshot = collect(case)
    assert snapshot["errors"] and not snapshot["jobs"]
