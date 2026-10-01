"""Run on cloud CPU against pinned native MiMo source; no provider credentials."""

from __future__ import annotations

import importlib
import importlib.util
import subprocess
import tempfile
import threading
from types import SimpleNamespace

import pytest

if importlib.util.find_spec("mimoagent") is None:
    pytest.importorskip("mimoagent", reason="Optional pinned MiMo reference source is not installed")

# Import errors inside an installed reference source remain real test failures.
native_environment = importlib.import_module("mimoagent.environments")
native_modal = importlib.import_module("mimoagent.environments.modal")
adapter = importlib.import_module("uni_agent.tasks.mimo_reference.modal_environment")
TransportError = native_environment.TransportError
_ExecOutcome = native_modal._ExecOutcome
ModalCleanupError = adapter.ModalCleanupError
ModalEnvironment = adapter.ModalEnvironment
ModalEnvironmentConfig = adapter.ModalEnvironmentConfig
NativeModalEnvironment = adapter.NativeModalEnvironment


class LocalProcess:
    def __init__(self, argv, **kwargs):
        self.proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.stdin = SimpleNamespace(
            write=self.proc.stdin.write,
            drain=lambda: None if self.proc.stdin.closed else self.proc.stdin.flush(),
            write_eof=self.proc.stdin.close,
        )
        self.stdout = iter(self.proc.stdout.readline, b"")
        self.stderr = iter(self.proc.stderr.readline, b"")

    def wait(self):
        return self.proc.wait(timeout=10)


class LocalSandbox:
    object_id = "sb-owned-contract-test"

    def __init__(self):
        self.calls = []
        self.terminated = False

    def exec(self, *argv, **kwargs):
        self.calls.append((argv, kwargs))
        return LocalProcess(argv, **kwargs)

    def terminate(self):
        self.terminated = True

    def poll(self):
        return 0 if self.terminated else None


@pytest.fixture
def env(tmp_path):
    item = ModalEnvironment(image="docker.io/example@sha256:" + "a" * 64, run_id="r22-contract", cwd=str(tmp_path))
    item.sandbox = LocalSandbox()
    item.sandbox_id = item.sandbox.object_id
    return item


def test_native_config_seam_accepts_extended_fields():
    item = ModalEnvironment(image="image", run_id="r22", exec_user="nobody", max_exec_budget=30, skip_precheck=True)
    assert isinstance(item.config, ModalEnvironmentConfig)
    assert item.get_template_vars()["exec_user"] == "nobody"


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"run_id": "../bad"},
        {"run_id": "r22", "gpu": "A100"},
        {"run_id": "r22", "secrets": ["host-key"]},
        {"run_id": "r22", "forward_env": ["TOKEN"]},
        {"run_id": "r22", "cleanup_timeout": 0},
        {"run_id": "r22", "max_exec_budget": float("nan")},
    ],
)
def test_bad_resource_contract_rejected(kwargs):
    with pytest.raises(ValueError):
        ModalEnvironment(image="image", **kwargs)


def test_normal_command_output_and_real_nonzero_exit(env):
    assert env.execute("printf ordinary-echo") == {"output": "ordinary-echo", "returncode": 0, "reason": "ok"}
    result = env.execute("printf ordinary-error >&2; exit 7")
    assert result == {"output": "ordinary-error", "returncode": 7, "reason": "ok"}


def test_shell_and_cwd_quotes_are_preserved(env, tmp_path):
    directory = tmp_path / "has space's"
    directory.mkdir()
    result = env.execute("pwd", cwd=str(directory), as_user="root")
    assert result["output"].strip() == str(directory)
    assert result["returncode"] == 0


def test_specified_user_has_real_distinct_identity(env):
    assert env.execute("id -un", cwd="/", as_user="nobody")["output"].strip() == "nobody"
    assert env.execute("id -un", cwd="/")["output"].strip() == "root"


def test_ordinary_file_copy_respects_nonroot_permissions(env, tmp_path):
    from pathlib import Path

    source = tmp_path / "ordinary input"
    source.write_bytes(b"ordinary data")
    with tempfile.TemporaryDirectory(prefix="mimo-ordinary-copy-") as directory:
        folder = Path(directory)
        folder.chmod(0o777)
        remote = folder / "remote file"
        env.copy_to(str(source), str(remote), as_user="nobody", max_retries=1)
        assert remote.read_bytes() == b"ordinary data"
        output = tmp_path / "ordinary output"
        env.copy_out(str(remote), str(output), as_user="nobody", max_retries=1)
        assert output.read_bytes() == b"ordinary data"
        folder.chmod(0o700)
        with pytest.raises((RuntimeError, BrokenPipeError)):
            env.copy_to(str(source), str(folder / "blocked"), as_user="nobody", max_retries=1)
        assert not (folder / "blocked").exists()


@pytest.mark.parametrize("user", ["root;echo bad", "", "-root", 123])
def test_invalid_execution_user_never_executes(env, user):
    with pytest.raises(ValueError):
        env.execute("echo ordinary", as_user=user)
    assert env.sandbox.calls == []


def test_native_shell_timeout_is_distinct_from_nonzero_reward(env):
    result = env.execute("sleep 1", timeout=0.05)
    assert result["reason"] == "pod_timeout"
    assert result["returncode"] == 124
    assert type(env.sandbox.calls[-1][1]["timeout"]) is int


@pytest.mark.parametrize("timeout", [1.0, 1.25, 120.0])
def test_float_timeout_reaches_provider_as_integer_without_changing_command(env, timeout):
    result = env.execute("printf ordinary", timeout=timeout)
    assert result["returncode"] == 0
    argv, options = env.sandbox.calls[-1]
    assert type(options["timeout"]) is int
    assert str(timeout) in argv


@pytest.mark.parametrize("timeout", [0, -1, True, float("inf")])
def test_invalid_timeout_rejected(env, timeout):
    with pytest.raises(ValueError):
        env.execute("echo ordinary", timeout=timeout)


def test_user_applies_to_native_tar_transfers_and_is_reset(env, tmp_path):
    source = tmp_path / "input with quote'"
    source.write_bytes(b"ordinary-file\x00bytes")
    remote = tmp_path / "remote file"
    output = tmp_path / "copied out"
    env.copy_to(str(source), str(remote), as_user="root", max_retries=1)
    env.copy_out(str(remote), str(output), as_user="root", max_retries=1)
    assert output.read_bytes() == source.read_bytes()
    assert all(call[0][:2] == ("su", "root") for call in env.sandbox.calls)
    env.execute("printf normal")
    assert env.sandbox.calls[-1][0][0] == "timeout"


def test_copy_failure_does_not_leak_user_context(env, tmp_path):
    with pytest.raises(FileNotFoundError):
        env.copy_to(str(tmp_path / "missing"), "/tmp/unused", as_user="root", max_retries=1)
    assert env.execute("echo normal")["returncode"] == 0
    assert env.sandbox.calls[-1][0][0] == "timeout"


def test_copy_user_context_is_thread_local(env, monkeypatch):
    captured = []
    barrier = threading.Barrier(2)

    def transfer(self, src, dest, **kwargs):
        barrier.wait(timeout=5)
        return self._exec(["echo", "ordinary"], timeout=1)

    def capture(self, argv, **kwargs):
        captured.append(tuple(argv))
        return _ExecOutcome(0, b"ordinary", b"", None)

    monkeypatch.setattr(NativeModalEnvironment, "copy_to", transfer)
    monkeypatch.setattr(NativeModalEnvironment, "_exec", capture)
    threads = [
        threading.Thread(target=env.copy_to, args=("unused", "unused"), kwargs={"as_user": user})
        for user in ("root", "nobody")
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=6)
    assert {row[1] for row in captured} == {"root", "nobody"}


def test_budget_exhaustion_prevents_another_command(env):
    env.config.max_exec_budget = 0.001
    assert env.execute("sleep 0.01")["returncode"] == 0
    before = len(env.sandbox.calls)
    assert env.execute("echo should-not-run")["reason"] == "budget_exhausted"
    assert len(env.sandbox.calls) == before


def test_transport_failure_does_not_become_exit_zero(env, monkeypatch):
    def failed(*args, **kwargs):
        raise RuntimeError("ordinary transport failure")

    monkeypatch.setattr(env.sandbox, "exec", failed)
    assert env.execute("echo ordinary")["returncode"] is None
    assert env.execute("echo ordinary")["reason"] == "transport_error"
    env.config.raise_on_transport_error = True
    with pytest.raises(TransportError):
        env.execute("echo ordinary")


@pytest.mark.parametrize(
    "outcome,reason",
    [
        (_ExecOutcome(-1, b"", b"", None), "client_timeout"),
        (_ExecOutcome(None, b"partial", b"", None), "transport_error"),
        (_ExecOutcome(0, b"partial", b"", OSError("stream")), "transport_error"),
    ],
)
def test_native_missing_status_and_stream_error_are_not_success(env, monkeypatch, outcome, reason):
    monkeypatch.setattr(env, "_exec", lambda *a, **k: outcome)
    result = env.execute("echo ordinary")
    assert result["reason"] == reason
    assert result["returncode"] is None


def test_creation_ownership_tags_are_atomic(env):
    kwargs = env._sandbox_create_kwargs(SimpleNamespace(), object(), object())
    assert kwargs["tags"]["owned_run"] == "r22-contract"
    assert kwargs["tags"]["owned_session"] == env.config.session_id


def test_network_flag_requires_actual_creation_policy_and_live_handle(env):
    assert not env.network_blocked
    env.config.block_network = True
    kwargs = env._sandbox_create_kwargs(SimpleNamespace(), object(), object())
    assert kwargs["block_network"] is True
    assert not env.network_blocked
    env._allocation_attempted = True
    assert env.network_blocked
    env.config.block_network = False
    assert env.network_blocked
    env.sandbox = None
    assert not env.network_blocked


def test_allocation_is_not_retried_or_reused(env, monkeypatch):
    calls = []
    monkeypatch.setattr(NativeModalEnvironment, "start", lambda self: calls.append(self.config.session_id))
    env.start()
    assert env.evidence["allocation_attempted"]
    with pytest.raises(RuntimeError):
        env.start()
    assert len(calls) == 1
    assert env._is_permanent_create_error(None, RuntimeError("lost ack"))


def test_tags_keep_owned_identity_after_native_tag_update(env):
    seen = []
    env.sandbox.set_tags = lambda tags: seen.append(tags)
    env._set_tags()
    assert env.evidence["sandbox_id"] == env.sandbox.object_id
    assert seen[0]["owned_run"] == env.config.run_id


def test_cleanup_uses_fresh_handle_and_keeps_evidence(env, monkeypatch):
    import modal

    owned = env.sandbox
    fresh = SimpleNamespace(poll=lambda: 137)
    seen = []
    monkeypatch.setattr(modal.Sandbox, "from_id", lambda key: seen.append(key) or fresh)
    env.cleanup()
    assert owned.terminated
    assert seen == [owned.object_id]
    assert env.sandbox is None
    assert env.evidence["cleanup_confirmed"]
    assert env.evidence["sandbox_id"] == owned.object_id
    assert env.evidence["returncode"] == 137
    env.cleanup()
    with pytest.raises(RuntimeError):
        env.start()


def test_cleanup_failure_keeps_owned_handle_for_retry(env, monkeypatch):
    import modal

    monkeypatch.setattr(modal.Sandbox, "from_id", lambda key: (_ for _ in ()).throw(RuntimeError("provider offline")))
    with pytest.raises(ModalCleanupError):
        env.cleanup()
    assert env.sandbox is not None
    assert not env.cleanup_confirmed


def test_cleanup_poll_timeout_is_not_termination(env, monkeypatch):
    import modal

    env.config.cleanup_timeout = 0.001
    monkeypatch.setattr(modal.Sandbox, "from_id", lambda key: SimpleNamespace(poll=lambda: None))
    with pytest.raises(ModalCleanupError):
        env.cleanup()
    assert not env.cleanup_confirmed


def test_missing_allocation_acknowledgement_is_indeterminate():
    env = ModalEnvironment(image="image", run_id="r22")
    env.cleanup()
    env._allocation_attempted = True
    with pytest.raises(ModalCleanupError):
        env.cleanup()


def test_no_provider_allocation_before_start(env):
    assert env.evidence["allocation_attempted"] is False
    assert env.evidence["cleanup_confirmed"] is False
