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
