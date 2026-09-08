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
