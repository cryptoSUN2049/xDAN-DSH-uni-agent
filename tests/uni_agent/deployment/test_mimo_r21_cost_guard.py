"""Recovery cost guard must never stop an early or unrelated allocation."""

import hashlib
import importlib.util
import io
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

SOURCE = Path(__file__).resolve().parents[3] / "docs/verl-uni-agent-harbor-opd-rl/mimo_r21_cost_guard.py"
SPEC = importlib.util.spec_from_file_location("recovery_cost_guard", SOURCE)
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)


def allocated_pod():
    return {
        "id": guard.POD,
        "name": "mimo-dsh-9b-r21-dual-20261001",
        "gpu": {"count": 2, "id": "NVIDIA RTX PRO 6000 Blackwell Server Edition"},
        "dataCenterId": "EUR-IS-1",
        "mounts": {"network": [{"volumeId": guard.VOLUME}]},
        "status": "RUNNING",
        "actions": ["stop"],
    }


def test_early_stop_never_touches_api(monkeypatch):
    api = Mock()
    monkeypatch.setattr(guard, "request", api)
    with pytest.raises(ValueError, match="before"):
        guard.stop_owned("private-test-key", guard.DEADLINE - 1)
    api.assert_not_called()


@pytest.mark.parametrize("field,value", [("id", "another-pod"), ("name", "another-run"), ("dataCenterId", "US-MO-2")])
def test_foreign_pod_never_mutated(monkeypatch, field, value):
    pod = allocated_pod()
    pod[field] = value
    api = Mock(return_value=pod)
    monkeypatch.setattr(guard, "request", api)
    with pytest.raises(ValueError, match="outside"):
        guard.stop_owned("private-test-key", guard.DEADLINE)
    api.assert_called_once_with("private-test-key")


def test_changed_mount_never_mutated(monkeypatch):
    pod = allocated_pod()
    pod["mounts"]["network"] = [{"volumeId": "another-volume"}]
    api = Mock(return_value=pod)
    monkeypatch.setattr(guard, "request", api)
    with pytest.raises(ValueError, match="outside"):
        guard.stop_owned("private-test-key", guard.DEADLINE)
    api.assert_called_once_with("private-test-key")


def test_stop_after_exact_deadline_only(monkeypatch):
    pod = allocated_pod()
    stopped = {**pod, "status": "EXITED"}
    api = Mock(side_effect=[pod, stopped])
    monkeypatch.setattr(guard, "request", api)
    assert guard.stop_owned("private-test-key", guard.DEADLINE) == {"status": "EXITED", "already_stopped": False}
    assert [call.args for call in api.call_args_list] == [("private-test-key",), ("private-test-key", "stop")]


def test_missing_stop_does_not_delete(monkeypatch):
    pod = {**allocated_pod(), "actions": ["terminate"]}
    api = Mock(return_value=pod)
    monkeypatch.setattr(guard, "request", api)
    with pytest.raises(ValueError, match="no automatic delete"):
        guard.stop_owned("private-test-key", guard.DEADLINE)
    api.assert_called_once_with("private-test-key")


def test_already_stopped_is_read_only(monkeypatch):
    api = Mock(return_value={**allocated_pod(), "status": "EXITED"})
    monkeypatch.setattr(guard, "request", api)
    assert guard.stop_owned("private-test-key", guard.DEADLINE)["already_stopped"] is True
    api.assert_called_once_with("private-test-key")


def test_public_journal_does_not_include_key(tmp_path):
    path = tmp_path / "journal.jsonl"
    guard.emit(path, "armed", pid=42)
    value = json.loads(path.read_text())
    assert value["pod_id"] == guard.POD
    assert value["deadline_unix"] - guard.ALLOCATION == 21600
    assert "key" not in value


def test_private_key_symlink_rejected(tmp_path):
    key = tmp_path / "key"
    key.write_text("a" * 40)
    key.chmod(0o600)
    assert guard.read_private(key) == "a" * 40
    link = tmp_path / "link"
    link.symlink_to(key)
    with pytest.raises(OSError):
        guard.read_private(link)


def test_readable_key_rejected(tmp_path):
    key = tmp_path / "key"
    key.write_text("a" * 40)
    key.chmod(0o644)
    with pytest.raises(ValueError, match="private"):
        guard.read_private(key)


def test_mutable_authorization_rejected(tmp_path):
    path = tmp_path / "authorization.json"
    path.write_text("{}")
    with pytest.raises(ValueError, match="readonly"):
        guard.authorization(path)


def test_wrong_authorization_bytes_rejected(tmp_path):
    path = tmp_path / "authorization.json"
    path.write_text("{}")
    path.chmod(0o444)
    with pytest.raises(ValueError, match="bytes changed"):
        guard.authorization(path)


@pytest.fixture
def approved_files(tmp_path, monkeypatch):
    value = dict(
        schema="mimo.recovery-authorization.v1",
        pod_id=guard.POD,
        allocated_at_unix=guard.ALLOCATION,
        deadline_unix=guard.DEADLINE,
        max_run_seconds=21600,
        cleanup_reserve_seconds=180,
        stage="r20f",
    )
    authorization = tmp_path / "authorization.json"
    authorization.write_text(json.dumps(value))
    authorization.chmod(0o444)
    monkeypatch.setattr(guard, "AUTH_SHA", hashlib.sha256(authorization.read_bytes()).hexdigest())
    monkeypatch.setenv("RUNPOD_POD_ID", guard.POD)
    key = tmp_path / "synthetic-key"
    key.write_text("synthetic-test-credential-only-00000000000")
    key.chmod(0o600)
    journal = tmp_path / "journal.jsonl"
    monkeypatch.setattr(
        guard.os.sys,
        "argv",
        [str(SOURCE), "--authorization", str(authorization), "--key", str(key), "--journal", str(journal)],
    )
    return authorization, key, journal


def test_authorized_window_and_current_pod_are_both_required(approved_files, monkeypatch):
    authorization, _, _ = approved_files
    assert guard.authorization(authorization)["deadline_unix"] == guard.DEADLINE
    monkeypatch.setenv("RUNPOD_POD_ID", "foreign-pod")
    with pytest.raises(ValueError, match="owned Pod"):
        guard.authorization(authorization)
    monkeypatch.setenv("RUNPOD_POD_ID", guard.POD)
    value = json.loads(authorization.read_bytes())
    value["deadline_unix"] += 60
    authorization.chmod(0o644)
    authorization.write_text(json.dumps(value))
    authorization.chmod(0o444)
    monkeypatch.setattr(guard, "AUTH_SHA", hashlib.sha256(authorization.read_bytes()).hexdigest())
    with pytest.raises(ValueError, match="window differs"):
        guard.authorization(authorization)


def test_check_only_real_entry_issues_only_authenticated_get(approved_files, monkeypatch):
    _, key, journal = approved_files
    guard.os.sys.argv.append("--check-only")
    calls = []

    def api(request, timeout):
        calls.append((request.full_url, request.get_method(), request.get_header("Authorization"), timeout))
        return io.BytesIO(json.dumps(allocated_pod()).encode())

    monkeypatch.setattr(guard.urllib.request, "urlopen", api)
    guard.main()
    assert calls == [(guard.API, "GET", "Bearer " + key.read_text(), 30)]
    events = [json.loads(row) for row in journal.read_text().splitlines()]
    assert [e["event"] for e in events] == ["identity_checked"]
    assert key.read_text() not in journal.read_text()


def test_guard_waits_then_retries_transient_failure_without_delete(approved_files, monkeypatch):
    _, _, journal = approved_files
    clock = {"now": guard.DEADLINE - 1}
    sleeps = []
    monkeypatch.setattr(guard.time, "time", lambda: clock["now"])

    def sleep(seconds):
        sleeps.append(seconds)
        clock["now"] += seconds

    monkeypatch.setattr(guard.time, "sleep", sleep)
    pod = allocated_pod()
    api = Mock(side_effect=[pod, guard.urllib.error.URLError("synthetic outage"), pod, {**pod, "status": "EXITED"}])
    monkeypatch.setattr(guard, "request", api)
    guard.main()
    assert sleeps == [1, 30]
    assert [call.args[1:] for call in api.call_args_list] == [(), (), (), ("stop",)]
    events = [json.loads(row)["event"] for row in journal.read_text().splitlines()]
    assert events == ["identity_checked", "armed", "stop_retry", "stop_requested"]


def test_stop_request_uses_exact_reviewed_action_endpoint(monkeypatch):
    calls = []

    def api(request, timeout):
        calls.append((request.full_url, request.get_method(), json.loads(request.data)))
        return io.BytesIO(json.dumps({**allocated_pod(), "status": "EXITED"}).encode())

    monkeypatch.setattr(guard.urllib.request, "urlopen", api)
    guard.request("synthetic", "stop")
    assert calls == [(guard.API + "/action", "POST", {"action": "stop"})]
