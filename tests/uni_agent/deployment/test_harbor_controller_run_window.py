import asyncio
import json

import pytest

from deployment.services import harbor_run_controller as module
from tests.uni_agent.deployment.test_harbor_run_controller import make_spec

pytestmark = [pytest.mark.cpu, pytest.mark.level0]


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(module.time, "time", lambda: 1000)

    class Controller:
        def __init__(self, spec):
            calls.append("created")
            self.spec, self.state, self.spec_sha256 = spec, "starting", "sha256:fixture"

        async def start(self):
            calls.append("started")

        async def monitor(self):
            calls.append("monitored")

        async def close(self):
            calls.append("closed")

    class Runner:
        def __init__(self, *args, **kwargs):
            pass

        async def setup(self):
            pass

        async def cleanup(self):
            pass

    class Site:
        def __init__(self, *args):
            pass

        async def start(self):
            pass

    monkeypatch.setattr(module, "HarborRunController", Controller)
    monkeypatch.setattr(module, "create_app", lambda controller: None)
    monkeypatch.setattr(module.web, "AppRunner", Runner)
    monkeypatch.setattr(module.web, "TCPSite", Site)
    spec = make_spec(tmp_path).model_dump(mode="json")
    path = tmp_path / "spec.json"

    def write(remaining):
        spec["deadline_unix"] = 1000 + remaining
        path.write_text(json.dumps(spec))
        return path

    return write, calls


@pytest.mark.parametrize("limit", [1, 14400, 18000, 21600])
def test_explicit_window_accepts_boundary_without_rewriting_spec(runtime, limit):
    write, calls = runtime
    path = write(limit)
    original = path.read_bytes()
    asyncio.run(module.main(path, max_run_seconds=limit))
    assert calls == ["created", "started", "monitored", "closed"]
    assert path.read_bytes() == original


@pytest.mark.parametrize("remaining,accepted", [(14400, True), (14401, False), (18000, False)])
def test_default_four_hour_window_remains_compatible(runtime, remaining, accepted):
    write, calls = runtime
    if accepted:
        asyncio.run(module.main(write(remaining)))
        assert "monitored" in calls
    else:
        with pytest.raises(ValueError, match="deadline"):
            asyncio.run(module.main(write(remaining)))
        assert calls == []


@pytest.mark.parametrize("limit", [0, -1, 21601, True, 18000.0, float("inf"), float("nan"), "18000"])
def test_direct_main_rejects_invalid_limit_before_start(runtime, limit):
    write, calls = runtime
    with pytest.raises(ValueError, match="max_run_seconds"):
        asyncio.run(module.main(write(100), max_run_seconds=limit))
    assert calls == []


@pytest.mark.parametrize("remaining", [-1, 0, 18001])
def test_explicit_window_rejects_expired_or_overlong_deadline(runtime, remaining):
    write, calls = runtime
    with pytest.raises(ValueError, match="deadline"):
        asyncio.run(module.main(write(remaining), max_run_seconds=18000))
    assert calls == []


def test_cli_five_hour_flag_reaches_real_main(runtime):
    write, calls = runtime
    module.cli(["--run-spec", str(write(18000)), "--max-run-seconds", "18000"])
    assert calls == ["created", "started", "monitored", "closed"]


@pytest.mark.parametrize("value", ["0", "-1", "21601", "18000.0", "nan"])
def test_cli_invalid_window_is_parser_error_before_start(runtime, value):
    write, calls = runtime
    with pytest.raises(SystemExit) as exc:
        module.cli(["--run-spec", str(write(100)), "--max-run-seconds", value])
    assert exc.value.code == 2
    assert calls == []
