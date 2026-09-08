import json
import os
import sys

import pytest

from deployment.services.harbor_training_supervisor import supervise, validate_health


def test_health_requires_frozen_identity():
    expected = {"run_id": "r5", "controller_id": "mac-r5", "run_spec_sha256": "sha256:abc"}
    good = {**expected, "state": "unregistered", "healthy": True}
    validate_health(good, expected)
    validate_health({**good, "state": "registering"}, expected)
    for patch in ({"run_id": "r4"}, {"healthy": False}, {"state": "closed"}, {"healthy": 1}):
        with pytest.raises(ValueError):
            validate_health({**good, **patch}, expected)


def test_unhealthy_preflight_never_launches(tmp_path):
    def bad():
        raise RuntimeError("down")

    with pytest.raises(RuntimeError):
        supervise([sys.executable, "-c", "raise Exception()"], tmp_path, os.environ.copy(), tmp_path, bad)
    assert not (tmp_path / "train.log").exists()


def test_unhealthy_runtime_stops_owned_process(tmp_path):
    calls = []

    def health():
        calls.append(1)
        if len(calls) > 1:
            raise RuntimeError("lost")

    result = supervise(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        tmp_path,
        os.environ.copy(),
        tmp_path,
        health,
        interval=0.01,
        grace=1,
    )
    assert result["reason"] == "controller-health-failed"
    assert result["exit_code"] != 0
    assert json.loads((tmp_path / "supervisor-result.json").read_text()) == result


def test_success_preserves_training_exit(tmp_path):
    result = supervise(
        [sys.executable, "-c", "pass"], tmp_path, os.environ.copy(), tmp_path, lambda: None, interval=0.02
    )
    assert result["exit_code"] == 0
    assert result["reason"] == "training-exited"


def test_training_command_preserves_old_argv():
    from deployment.services.harbor_training_supervisor import training_command

    assert training_command({"environment": {}}, "/run/launch.json", "/venv/python") == [
        "/venv/python",
        "-m",
        "examples.harbor.train_m2_online_rl",
        "--launch",
        "/run/launch.json",
    ]


def test_training_command_forwards_explicit_adapter():
    from deployment.services.harbor_training_supervisor import training_command

    digest = "sha256:" + "a" * 64
    command = training_command(
        {"lora_adapter": {"path": "/private/adapter", "bundle_sha256": digest}}, "/run/launch.json", "/venv/python"
    )
    assert command[-4:] == ["--lora-adapter-path", "/private/adapter", "--lora-adapter-bundle-sha256", digest]


@pytest.mark.parametrize(
    "adapter",
    [
        None,
        {},
        {"path": "/adapter"},
        {"path": "/adapter", "bundle_sha256": "bad"},
        {"path": "", "bundle_sha256": "sha256:" + "a" * 64},
        {"path": "/adapter", "bundle_sha256": "sha256:" + "a" * 64, "unknown": True},
    ],
)
def test_training_command_rejects_bad_adapter_schema(adapter):
    from deployment.services.harbor_training_supervisor import training_command

    with pytest.raises(ValueError, match="lora_adapter"):
        training_command({"lora_adapter": adapter}, "/run/launch.json", "/venv/python")


@pytest.mark.parametrize("phase", ["preflight", "runtime"])
def test_health_diagnostics_do_not_leak_http_secrets(tmp_path, phase):
    import urllib.error

    count = 0

    def health():
        nonlocal count
        count += 1
        if phase == "runtime" and count == 1:
            return
        raise urllib.error.HTTPError("https://secret-url", 403, "secret-token", {"secret-header": "private"}, None)

    if phase == "preflight":
        with pytest.raises(urllib.error.HTTPError):
            supervise([sys.executable, "-c", "pass"], tmp_path, os.environ.copy(), tmp_path, health)
        assert not (tmp_path / "train.log").exists()
    else:
        result = supervise(
            [sys.executable, "-c", "import time;time.sleep(60)"],
            tmp_path,
            os.environ.copy(),
            tmp_path,
            health,
            interval=0.01,
            grace=1,
        )
        assert result["health_failure"]["exception_type"] == "HTTPError"
    raw = (tmp_path / "health-failure.json").read_text()
    data = json.loads(raw)
    assert data["phase"] == phase and data["http_status"] == 403
    assert data["observed_at_unix"] > 0
    assert "secret" not in raw and "private" not in raw


def test_urlerror_records_timeout_type_without_reason_text(tmp_path):
    import urllib.error

    from deployment.services.harbor_training_supervisor import record_health_failure

    value = record_health_failure(tmp_path, urllib.error.URLError(TimeoutError("secret-url-token")), "runtime")
    assert value["exception_type"] == "URLError"
    assert value["reason_type"] == "TimeoutError"
    assert "secret" not in (tmp_path / "health-failure.json").read_text()
    assert (tmp_path / "health-failure.json").stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize(
    "error, expected",
    [(TimeoutError(), True), (ConnectionRefusedError(), True), (ValueError(), False), (PermissionError(), False)],
)
def test_transport_error_classification(error, expected):
    from deployment.services.harbor_training_supervisor import transient_transport_error

    assert transient_transport_error(error) is expected


@pytest.mark.parametrize("scenario", ["recover", "reset", "continuous", "wall", "auth"])
def test_bounded_transport_windows_with_fake_clock(tmp_path, monkeypatch, scenario):
    import urllib.error

    from deployment.services import harbor_training_supervisor as module

    clock = [0.0]

    class Process:
        pid = 54321
        returncode = None

        def poll(self):
            return self.returncode

        def wait(self, timeout):
            self.returncode = -15
            return -15

    process = Process()
    monkeypatch.setattr(module.subprocess, "Popen", lambda *a, **k: process)
    monkeypatch.setattr(module.os, "killpg", lambda *a: None)
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(module.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    checks = []

    def health():
        checks.append(clock[0])
        if len(checks) == 1:
            return
        if scenario == "auth":
            raise urllib.error.HTTPError("secret", 403, "secret", {}, None)
        if scenario == "recover" and clock[0] >= 20:
            process.returncode = 0
            return
        if scenario == "reset" and clock[0] == 80:
            return
        if scenario == "reset" and clock[0] >= 160:
            process.returncode = 0
            return
        raise TimeoutError("secret")

    result = module.supervise(
        ["unused"], tmp_path, {}, tmp_path, health, interval=10, wall_seconds=25 if scenario == "wall" else 300
    )
    if scenario in ("recover", "reset"):
        assert result["reason"] == "training-exited"
        assert result["exit_code"] == 0
    else:
        assert result["reason"] == ("wall-clock-deadline" if scenario == "wall" else "controller-health-failed")
        assert clock[0] == ({"continuous": 90, "wall": 25, "auth": 0}[scenario])
    assert "secret" not in (tmp_path / "supervisor-result.json").read_text()


def test_wrapped_transport_and_permanent_failures_are_distinguished():
    import errno
    import socket
    import ssl
    import urllib.error

    from deployment.services.harbor_training_supervisor import transient_transport_error

    for reason in (
        TimeoutError(),
        ConnectionResetError(),
        OSError(errno.EHOSTUNREACH, "private"),
        socket.gaierror(socket.EAI_AGAIN, "private"),
    ):
        assert transient_transport_error(urllib.error.URLError(reason))
    for error in (
        urllib.error.HTTPError("private", 503, "private", {}, None),
        urllib.error.URLError("timed out"),
        urllib.error.URLError(ssl.SSLCertVerificationError()),
        socket.gaierror(socket.EAI_NONAME, "private"),
        json.JSONDecodeError("private", "x", 0),
    ):
        assert not transient_transport_error(error)


def test_transport_preflight_still_refuses_to_launch(tmp_path, monkeypatch):
    from deployment.services import harbor_training_supervisor as module

    def forbidden(*a, **k):
        raise AssertionError("must not start training")

    monkeypatch.setattr(module.subprocess, "Popen", forbidden)
    with pytest.raises(TimeoutError):
        supervise(["unused"], tmp_path, {}, tmp_path, lambda: (_ for _ in ()).throw(TimeoutError("private")))
    assert not (tmp_path / "train.log").exists()
